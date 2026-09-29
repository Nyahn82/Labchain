#!/usr/bin/env python3
"""Root-operated preparation, with an injectable host facade for disposable tests.

The command has fixed production paths and no test/override flags. Tests import
prepare() with an isolated filesystem and a fake host: no real account operations.
"""
from dataclasses import dataclass
import fcntl
import grp
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile

ACCOUNT = 'rhu-labchain-worker'
UNIT = 'rhu-labchain-blockchain-worker.service'
BASE_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}


class PreparationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise PreparationError(message)


@dataclass(frozen=True)
class Paths:
    repo: Path = Path('/opt/rhu-labchain')
    state_parent: Path = Path('/var/lib/rhu-labchain')
    etc: Path = Path('/etc/rhu-labchain')
    units: Path = Path('/etc/systemd/system')

    @property
    def runtime(self):
        return self.state_parent / 'blockchain-worker'

    @property
    def source(self):
        return self.repo / 'blockchain/network/runtime/app-client-single-vps/org1/msp'

    @property
    def public(self):
        return self.repo / 'blockchain/network/runtime/single-vps/public'

    @property
    def env(self):
        return self.etc / 'blockchain-worker.env'


def no_symlinks(path):
    for parent in [*reversed(path.parents), path]:
        require(not parent.is_symlink(), 'Symlinked preparation paths are prohibited.')


def read_regular(path):
    no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 65536,
                'Required input is not a bounded regular file.')
        return os.read(fd, 65537)
    finally:
        os.close(fd)


def one(directory):
    no_symlinks(directory)
    files = list(directory.iterdir())
    require(len(files) == 1, 'Dedicated client MSP must contain exactly one file per credential directory.')
    read_regular(files[0])
    return files[0]


def run(argv, *, cwd=None, env=None, allowed=(0,)):
    # All output is captured and never included in errors; no private material is printed.
    try:
        result = subprocess.run([str(value) for value in argv], cwd=cwd,
            env=env or BASE_ENV, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise PreparationError('A preparation verification command could not complete.') from None
    require(result.returncode in allowed, 'A preparation verification failed; inspect trusted configuration locally.')
    return result


def source_material(paths):
    cert, key, ca = (one(paths.source / part) for part in ('signcerts', 'keystore', 'cacerts'))
    trusted = one(paths.public / 'org1/msp/cacerts')
    tls = paths.public / 'org1-tls-ca.crt'
    require(read_regular(ca) == read_regular(trusted), 'Client signing CA differs from the retained Org1 trust root.')
    require(stat.S_IMODE(key.stat().st_mode) == 0o600, 'Original client key must already have mode 0600.')
    subject = run(['openssl', 'x509', '-in', cert, '-noout', '-subject', '-nameopt', 'RFC2253']).stdout.decode().strip()
    fields = subject.removeprefix('subject=').split(',')
    require('OU=client' in fields and not {'OU=admin', 'OU=peer', 'OU=orderer'}.intersection(fields),
            'Only the dedicated CLIENT certificate may be copied.')
    run(['openssl', 'verify', '-CAfile', ca, cert])
    run(['openssl', 'x509', '-in', cert, '-checkend', '0', '-noout'])
    run(['openssl', 'x509', '-in', ca, '-checkend', '0', '-noout'])
    require(run(['openssl', 'x509', '-in', cert, '-pubkey', '-noout']).stdout ==
            run(['openssl', 'pkey', '-in', key, '-pubout']).stdout, 'Client certificate and key do not match.')
    material = {
        'fabric-client/org1/msp/signcerts/client-cert.pem': read_regular(cert),
        'fabric-client/org1/msp/keystore/client-key.pem': read_regular(key),
        'fabric-client/org1/msp/cacerts/org1-ca.pem': read_regular(ca),
        'tls/peer1-ca.crt': read_regular(tls),
    }
    require(all(b'PRIVATE KEY' not in value for name, value in material.items()
                if name != 'fabric-client/org1/msp/keystore/client-key.pem'),
            'Unexpected private material outside the dedicated client key.')
    return material


class Host:
    def is_root(self):
        return os.geteuid() == 0

    def stopped(self):
        for action in ('is-active', 'is-enabled'):
            result = run(['systemctl', action, '--quiet', UNIT], allowed=(0, 1, 3, 4))
            require(result.returncode != 0, 'Stop and disable the existing worker before preparation; no service state was changed.')

    def account(self, paths):
        try:
            group = grp.getgrnam(ACCOUNT)
        except KeyError:
            run(['groupadd', '--system', ACCOUNT])
            group = grp.getgrnam(ACCOUNT)
        try:
            user = pwd.getpwnam(ACCOUNT)
        except KeyError:
            run(['useradd', '--system', '--gid', ACCOUNT, '--home-dir', paths.runtime,
                 '--no-create-home', '--shell', '/usr/sbin/nologin', ACCOUNT])
            user = pwd.getpwnam(ACCOUNT)
        uid_min = gid_min = 1000
        for line in Path('/etc/login.defs').read_text().splitlines():
            fields = line.split()
            if fields and fields[0] == 'UID_MIN':
                uid_min = int(fields[1])
            if fields and fields[0] == 'GID_MIN':
                gid_min = int(fields[1])
        require(0 < user.pw_uid < uid_min and user.pw_gid == group.gr_gid and 0 < group.gr_gid < gid_min,
                'Existing worker account is not a dedicated system account.')
        require(user.pw_shell in {'/usr/sbin/nologin', '/sbin/nologin'} and user.pw_dir == str(paths.runtime),
                'Existing worker account must have a non-login shell and the dedicated home.')
        require(set(os.getgrouplist(ACCOUNT, group.gr_gid)) == {group.gr_gid},
                'Worker has supplementary groups; preparation will not remove or bypass them.')
        password = run(['passwd', '-S', ACCOUNT]).stdout.decode().split()
        require(len(password) >= 2 and password[1] == 'L', 'Worker password must be locked.')
        # Exit 0 means sudo found privileges; failure is fail-closed unless it
        # explicitly states that the account is not allowed to use sudo.
        result = run(['sudo', '-n', '-l', '-U', ACCOUNT], allowed=(0, 1))
        require(result.returncode == 1 and b'not allowed' in result.stderr + result.stdout,
                'Worker must have no sudo privileges; verify sudo policy.')
        require(run(['pgrep', '-u', str(user.pw_uid)], allowed=(0, 1)).returncode == 1,
                'Worker account still has running processes; stop them before preparation.')
        return user.pw_uid, group.gr_gid

    def owner(self, path):
        info = path.stat()
        return info.st_uid, info.st_gid

    def secure(self, path, uid, gid, mode):
        os.chown(path, uid, gid, follow_symlinks=False)
        os.chmod(path, mode, follow_symlinks=False)

    def not_tracked(self, paths):
        require(not paths.runtime.is_relative_to(paths.repo) and not paths.env.is_relative_to(paths.repo),
                'Worker runtime and real environment must be outside Git.')
        git = ['git', '-c', f'safe.directory={paths.repo}', '-C', paths.repo]
        tracked = run(git + ['ls-files', '--', '.env', 'blockchain-worker.env', 'deploy/blockchain-worker.env',
            'blockchain/network/runtime', 'blockchain/network/generated']).stdout
        require(not tracked.strip(), 'Credential/runtime files are tracked by Git; preparation refused.')
        run(git + ['check-ignore', '--quiet', 'blockchain/network/runtime/app-client-single-vps/org1/msp/keystore/client-key.pem'])
        run(git + ['check-ignore', '--quiet', 'deploy/blockchain-worker.env'])

    def validate_unit(self, source):
        run(['systemd-analyze', 'verify', source])

    def validate_worker(self, paths):
        # This imports the worker and its pure settings only. It cannot read the
        # web .env, construct a DB engine, start a cycle, or contact Fabric.
        program = '''import os, sys
from pathlib import Path
from app.cli.blockchain_worker import reject_docker_privileges
reject_docker_privileges()
root = Path.cwd()
assert not os.access(root, os.W_OK)
assert not os.access(root / '.env', os.R_OK)
assert 'app.config' not in sys.modules and 'app.database' not in sys.modules
'''
        env = ['PATH=/usr/bin:/bin', 'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1']
        prefix = ['runuser', '-u', ACCOUNT, '--', '/usr/bin/env', '-i', *env]
        run(prefix + [paths.repo / '.venv/bin/python', '-B', '-c', program], cwd=paths.repo)
        msp = paths.runtime / 'fabric-client/org1/msp'
        gateway = {
            'BLOCKCHAIN_GATEWAY_TLS_CA_PATH': paths.runtime / 'tls/peer1-ca.crt',
            'BLOCKCHAIN_CLIENT_CERT_PATH': msp / 'signcerts/client-cert.pem',
            'BLOCKCHAIN_CLIENT_KEY_PATH': msp / 'keystore/client-key.pem',
            'BLOCKCHAIN_CLIENT_MSP_ID': 'Org1MSP', 'BLOCKCHAIN_SOURCE_NODE': 'node1',
        }
        result = run(prefix + [f'{key}={value}' for key, value in gateway.items()] + [
            '/usr/bin/node', paths.repo / 'blockchain/gateway-adapter/src/check-credentials.js'], cwd=paths.repo)
        require(result.stdout.strip() == b'{"ok":true}', 'Copied CLIENT credentials failed offline validation.')

    def reload(self):
        run(['systemctl', 'daemon-reload'])


def directory(path, uid, gid, mode, host):
    no_symlinks(path)
    if path.exists():
        require(path.is_dir() and host.owner(path)[0] in {0, uid}, 'Unexpected directory ownership/type.')
    else:
        path.mkdir()
    host.secure(path, uid, gid, mode)


def install(path, content, uid, gid, mode, host, *, replace=False):
    no_symlinks(path)
    if path.exists():
        existing = read_regular(path)
        require(host.owner(path)[0] in {0, uid}, 'Unexpected file owner.')
        if existing == content:
            host.secure(path, uid, gid, mode)
            return False
        require(replace, 'Existing worker credential differs; use a separately reviewed rotation procedure.')
    fd, name = tempfile.mkstemp(prefix='.worker-prepare-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        host.secure(temporary, uid, gid, mode)
        os.replace(temporary, path)
        host.secure(path, uid, gid, mode)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def prepare(paths, host):
    require(host.is_root(), 'Preparation requires root; no changes made.')
    host.stopped()
    host.not_tracked(paths)
    material = source_material(paths)  # validate original without mutating it
    source_unit = paths.repo / 'deploy' / UNIT
    unit_bytes = read_regular(source_unit)
    host.validate_unit(source_unit)
    uid, gid = host.account(paths)
    for path in (paths.state_parent, paths.etc, paths.units):
        no_symlinks(path)
        if path.exists():
            require(path.is_dir() and host.owner(path)[0] == 0 and not path.stat().st_mode & 0o022,
                    'Parent directories must be root-owned and not group/world writable.')
    directory(paths.state_parent, 0, 0, 0o755, host)
    directory(paths.etc, 0, gid, 0o750, host)
    directory(paths.runtime, uid, gid, 0o700, host)
    allowed_dirs = {paths.runtime}
    for relative in material:
        target = paths.runtime / relative
        allowed_dirs.update(parent for parent in target.parents if parent.is_relative_to(paths.runtime))
    allowed_files = {paths.runtime / name for name in material}
    for existing in paths.runtime.rglob('*'):
        require(not existing.is_symlink() and existing in allowed_dirs | allowed_files,
                'Unexpected files in worker runtime; no files were removed.')
    # Validate every existing destination before writing any credential.
    for name, content in material.items():
        target = paths.runtime / name
        if target.exists():
            require(read_regular(target) == content, 'Existing worker identity differs; manual rotation review required.')
    for path in sorted(allowed_dirs, key=lambda value: len(value.parts)):
        directory(path, uid, gid, 0o700, host)
    for name, content in material.items():
        install(paths.runtime / name, content, uid, gid, 0o600, host)
    if paths.env.exists() or paths.env.is_symlink():
        no_symlinks(paths.env)
        info = paths.env.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and host.owner(paths.env) == (0, gid)
                and stat.S_IMODE(info.st_mode) == 0o640, 'Existing worker environment must be root:worker, mode 0640.')
    host.validate_worker(paths)
    install(paths.units / UNIT, unit_bytes, 0, 0, 0o644, host, replace=True)
    # Reload is idempotent and also recovers a prior interrupted preparation.
    host.reload()
    # Nothing here creates or edits an environment file, database user or password.
    if not paths.env.exists():
        print('Worker remains stopped. Create /etc/rhu-labchain/blockchain-worker.env separately from the tracked example,')
        print('set root:rhu-labchain-worker ownership and mode 0640, and keep delivery disabled pending controlled deployment.')
    else:
        print('Preparation verified. Worker remains stopped and disabled; environment contents were not read or changed.')


def main():
    try:
        require(os.geteuid() == 0, 'Preparation requires root; no changes made.')
        # Serialize root preparation runs; never put a lock file in Fabric runtime.
        fd = os.open('/run/lock/rhu-labchain-worker-prepare.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1,
                    'Preparation lock must be a root-owned regular file.')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prepare(Paths(), Host())
        return 0
    except PreparationError as error:
        print('Worker preparation refused: ' + str(error))
        return 1
    except (OSError, ValueError, KeyError):
        print('Worker preparation refused. Check root access, account policy, stopped/disabled service, trusted paths, permissions and CLIENT material.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
