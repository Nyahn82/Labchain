"""Read-only Unix socket boundary. No Fabric credential or subprocess access."""
import json
import socket
import time
from datetime import datetime, timezone
from pydantic import ValidationError

from app.config import settings


class MonitorUnavailable(Exception):
    pass


def query(request, schema):
    path = settings.blockchain_monitor_socket
    if path is None:
        raise MonitorUnavailable()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            deadline = time.monotonic() + 12
            client.settimeout(12)
            client.connect(str(path))
            client.sendall(json.dumps(request).encode() + b'\n')
            data = bytearray()
            while not data.endswith(b'\n'):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or len(data) > 1024 * 1024:
                    raise MonitorUnavailable()
                client.settimeout(remaining)
                part = client.recv(min(65536, 1024 * 1024 + 1 - len(data)))
                if not part:
                    raise MonitorUnavailable()
                data.extend(part)
            if len(data) > 1024 * 1024:
                raise MonitorUnavailable()
        result = json.loads(data)
        if set(result) != {'ok', 'result'} or result['ok'] is not True:
            raise MonitorUnavailable()
        parsed = schema.model_validate(result['result'])
        observed = parsed.checked_at
        if observed.tzinfo is None or not -5 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 30:
            raise MonitorUnavailable()
        return parsed
    except (OSError, ValueError, TypeError, ValidationError):
        raise MonitorUnavailable() from None
