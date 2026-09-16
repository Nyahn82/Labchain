"""Private, server-owned artifacts. No client path or remote resource is accepted."""
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile

from app.config import settings


class ArtifactUnavailable(Exception):
    pass


def safe_path(root, relative):
    if root is None or not relative or '\\' in relative:
        raise ArtifactUnavailable()
    name = PurePosixPath(relative)
    if name.is_absolute() or any(part in {'.', '..'} for part in relative.split('/')):
        raise ArtifactUnavailable()
    root = Path(root).resolve(strict=True)
    target = root.joinpath(*name.parts)
    # Reject symlinks at every level, including ones pointing inside the root.
    cursor = root
    for part in name.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ArtifactUnavailable()
    if not target.resolve().is_relative_to(root):
        raise ArtifactUnavailable()
    return target


def read_private(root, relative):
    try:
        path = safe_path(root, relative)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ArtifactUnavailable()
            return stream.read()
    except (OSError, ValueError, RuntimeError) as exc:
        raise ArtifactUnavailable() from exc


def publish_pdf(data, relative):
    """Atomic no-clobber publication via hard link on the same filesystem."""
    temporary = None
    final = None
    published = False
    try:
        final = safe_path(settings.report_storage_dir, relative)
        final.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        final = safe_path(settings.report_storage_dir, relative)
        fd, temporary = tempfile.mkstemp(prefix='.release-', suffix='.tmp', dir=final.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        # Unlike rename/replace, link refuses an existing destination.
        os.link(temporary, final)
        published = True
        os.unlink(temporary)
        temporary = None
        directory_fd = os.open(final.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return final
    except (OSError, ValueError, RuntimeError) as exc:
        if published:
            remove_artifact(final)
        raise ArtifactUnavailable() from exc
    finally:
        if temporary is not None:
            remove_artifact(Path(temporary))


def remove_artifact(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A crash or cleanup failure can leave an unreferenced private artifact.
        import logging
        logging.getLogger(__name__).error('Report artifact cleanup failed; private storage reconciliation required.')
