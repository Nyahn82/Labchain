"""Explicitly enabled outbox worker; never imported by the web application."""
import argparse
import grp
import logging
import os
from pathlib import Path
import signal
import threading

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.worker_config import WorkerSettings, worker_sessions
from app.services.blockchain_adapter_service import DeliveryError, GatewayAdapter, WorkerOptions
from app.services.blockchain_delivery_service import DeliveryWorker

logger = logging.getLogger(__name__)


def reject_docker_privileges():
    # User= inherits account supplementary groups; never exempt the service user.
    if os.geteuid() == 0 or os.getuid() == 0:
        raise DeliveryError('CONFIG_INVALID')
    try:
        docker_gid = grp.getgrnam('docker').gr_gid
    except KeyError:
        docker_gid = None
    if docker_gid in {os.getgid(), os.getegid(), *os.getgroups()}:
        raise DeliveryError('CONFIG_INVALID')
    paths = {Path('/run/docker.sock'), Path('/var/run/docker.sock'),
             Path(f'/run/user/{os.getuid()}/docker.sock')}
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if runtime and Path(runtime).is_absolute():
        paths.add(Path(runtime) / 'docker.sock')
    docker_host = os.environ.get('DOCKER_HOST', '')
    if docker_host:
        # A service configuration must not carry an alternate Docker endpoint.
        raise DeliveryError('CONFIG_INVALID')
    if any(os.access(path, os.R_OK) or os.access(path, os.W_OK) for path in paths):
        raise DeliveryError('CONFIG_INVALID')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Deliver committed outbox events through Fabric Gateway.')
    parser.add_argument('--once', action='store_true', help='Process at most one configured batch, then exit.')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    stopping = threading.Event()
    previous = {}
    sessions = None
    try:
        settings = WorkerSettings()
        if not settings.blockchain_delivery_enabled:
            logger.info('blockchain_worker state=DISABLED')
            return 0
        reject_docker_privileges()
        options = WorkerOptions.from_settings(settings)
        # Offline certificate/key/CA validation finishes before any DB claim.
        adapter = GatewayAdapter(settings)
        sessions = worker_sessions(settings)
        worker = DeliveryWorker(sessions, adapter, options)
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, lambda *_: stopping.set())
        while not stopping.is_set():
            worker.cycle(stopping)
            if args.once:
                break
            stopping.wait(options.poll)
        return 0
    except ValidationError:
        logger.error('blockchain_worker state=STOPPED error_code=CONFIG_INVALID')
        return 1
    except DeliveryError as error:
        logger.error('blockchain_worker state=STOPPED error_code=%s', error.code)
        return 1
    except SQLAlchemyError:
        logger.error('blockchain_worker state=STOPPED error_code=DATABASE_UNAVAILABLE')
        return 1
    except Exception:
        logger.error('blockchain_worker state=STOPPED error_code=INTERNAL_ERROR')
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if sessions is not None:
            sessions.kw['bind'].dispose()


if __name__ == '__main__':
    raise SystemExit(main())
