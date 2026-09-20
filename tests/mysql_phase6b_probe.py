"""Native account-lock serialization probes against disposable MySQL only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
import secrets
import stat
import sys
from threading import Barrier

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pyotp
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import AuthSession, MfaChallenge, MfaRecoveryCode, UserAccount, UserTotpMfa
from app.security.mfa_crypto import decode_key, encrypt_secret
from app.security.tokens import hash_token
from app.services import mfa_service as service
from app.services.auth_service import utc_now


def main(socket, scenario):
    socket_path = Path(socket).resolve()
    assert socket_path.parent.parent == Path('/tmp')
    assert socket_path.parent.name.startswith('rhu-phase3b-mysql-')
    assert stat.S_ISSOCK(socket_path.stat().st_mode)
    assert scenario in {'challenge', 'recovery', 'totp', 'attempts', 'stale_revoked'}
    options = {'hide_parameters': True, 'connect_args': {'unix_socket': str(socket_path), 'connect_timeout': 5}}
    engine = create_engine('mysql+pymysql://root@localhost/', **options)
    with engine.begin() as db: db.execute(text('CREATE DATABASE phase6b_synthetic CHARACTER SET utf8mb4'))
    engine.dispose()
    engine = create_engine('mysql+pymysql://root@localhost/phase6b_synthetic', isolation_level='REPEATABLE READ', **options)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
            for revision in reversed(list(scripts.walk_revisions())): revision.module.upgrade()
        now = utc_now()
        service.utc_now = lambda: now
        secret = pyotp.random_base32()
        ciphertext, nonce = encrypt_secret(secret, decode_key(settings.mfa_secret_encryption_key.get_secret_value()), 1)
        tokens = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        recovery = secrets.token_hex(16)
        with factory.begin() as db:
            db.add(UserAccount(user_id=1, username='synthetic', password_hash='unused', account_status='ACTIVE'))
            db.flush()
            db.add(UserTotpMfa(mfa_id=1, user_id=1, secret_ciphertext=ciphertext, secret_nonce=nonce,
                created_at=now, confirmed_at=now, enabled_at=now))
            db.flush()
            db.add(MfaRecoveryCode(mfa_id=1, code_hash=hash_token(recovery), created_at=now))
            for i, token in enumerate(tokens):
                db.add(MfaChallenge(challenge_id=i+1, user_id=1, token_hash=hash_token(token), created_at=now,
                    expires_at=now+timedelta(minutes=5), attempt_count=0))
        code = pyotp.TOTP(secret).at(now.replace(tzinfo=timezone.utc))
        if scenario == 'stale_revoked':
            with factory() as stale:
                stale.scalar(select(MfaChallenge).where(MfaChallenge.challenge_id == 1))
                with factory.begin() as db: db.get(MfaChallenge, 1).revoked_at = now
                assert isinstance(service.verify_challenge(stale, tokens[0], code, None, None), service.ChallengeFailure)
        else:
            if scenario == 'attempts': settings.mfa_max_challenge_attempts = 2
            barrier = Barrier(2)
            def contend(number):
                with factory() as db:
                    list(db.scalars(select(MfaChallenge)))
                    list(db.scalars(select(UserTotpMfa)))
                    barrier.wait(timeout=10)
                    token = tokens[0] if scenario in {'challenge', 'attempts'} else tokens[number]
                    supplied = 'unknown' if scenario == 'attempts' else recovery if scenario == 'recovery' else code
                    result = service.verify_challenge(db, token, supplied, None, None,
                        recovery=scenario in {'recovery', 'attempts'})
                    return not isinstance(result, service.ChallengeFailure)
            with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(contend, (0, 1)))
            assert sum(results) == (0 if scenario == 'attempts' else 1), results
        with factory() as db:
            sessions = list(db.scalars(select(AuthSession)))
            assert len(sessions) == (0 if scenario in {'attempts', 'stale_revoked'} else 1)
            assert all(s.mfa_verified_at is not None for s in sessions)
            if scenario == 'recovery': assert db.scalar(select(MfaRecoveryCode)).used_at
            if scenario == 'attempts':
                row = db.get(MfaChallenge, 1)
                assert row.attempt_count == 2 and row.revoked_at
                assert db.get(UserAccount, 1).account_status == 'ACTIVE'
        print('MFA serialization checks passed')
    finally:
        with engine.begin() as db: db.execute(text('DROP DATABASE phase6b_synthetic'))
        engine.dispose()


if __name__ == '__main__': main(*sys.argv[1:])
