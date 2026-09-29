"""Bounded, private subprocess bridge to the fixed Phase 8B-2 Gateway adapter."""
from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time

from app.services.blockchain_event_validation import EVENT_TYPES, HASH_PATTERN, NODE_MSPS, UUID_PATTERN

# The adapter's code AND retryable flag must agree. Messages never come from stderr.
ERRORS = {
    'CONFIG_INVALID': (False, 'Worker or adapter configuration is invalid.'),
    'CREDENTIAL_INVALID': (False, 'Dedicated client credentials are invalid or inaccessible.'),
    'GATEWAY_UNAVAILABLE': (True, 'Gateway is unavailable.'),
    'TLS_FAILED': (False, 'Gateway TLS validation failed.'),
    'ENDORSEMENT_FAILED': (True, 'Transaction endorsement failed.'),
    'SUBMISSION_FAILED': (True, 'Transaction submission outcome is uncertain.'),
    'COMMIT_TIMEOUT': (True, 'Commit confirmation is unavailable.'),
    'COMMIT_INVALID': (False, 'Fabric rejected the transaction.'),
    'ANCHOR_NOT_FOUND': (False, 'Anchor was not found.'),
    'ANCHOR_CONFLICT': (False, 'Committed anchor conflicts with this event; review required.'),
    'EVALUATION_FAILED': (True, 'Anchor evaluation failed.'),
    'INVALID_INPUT': (False, 'Request does not match the adapter protocol.'),
    'INVALID_RESPONSE': (False, 'Adapter response is invalid.'),
    'INTERNAL_ERROR': (False, 'Adapter action could not be completed.'),
    'ADAPTER_TIMEOUT': (True, 'Adapter time budget expired; reconciliation is required.'),
    'ADAPTER_PROCESS_FAILED': (True, 'Adapter process ended without a valid result.'),
    'OUTBOX_INTEGRITY_FAILURE': (False, 'Immutable outbox validation failed; review required.'),
    'PREDECESSOR_DEAD': (False, 'Release predecessor requires manual review.'),
    'MAX_ATTEMPTS': (False, 'Delivery attempt limit reached; review required.'),
}
ADAPTER_CODES = frozenset({
    'CONFIG_INVALID', 'CREDENTIAL_INVALID', 'GATEWAY_UNAVAILABLE', 'TLS_FAILED',
    'ENDORSEMENT_FAILED', 'SUBMISSION_FAILED', 'COMMIT_TIMEOUT', 'COMMIT_INVALID',
    'ANCHOR_NOT_FOUND', 'ANCHOR_CONFLICT', 'EVALUATION_FAILED', 'INVALID_INPUT',
    'INVALID_RESPONSE', 'INTERNAL_ERROR',
})
ROOT = Path(__file__).resolve().parents[2]
FIXED_COMMAND = ('/usr/bin/node', str(ROOT / 'blockchain/gateway-adapter/src/cli.js'))
CREDENTIAL_COMMAND = ('/usr/bin/node', str(ROOT / 'blockchain/gateway-adapter/src/check-credentials.js'))
MAX_INPUT = 4096
MAX_OUTPUT = 16384


class DeliveryError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'INTERNAL_ERROR'
        self.retryable, message = ERRORS[self.code]
        super().__init__(message)


@dataclass(frozen=True)
class WorkerOptions:
    poll: float = 2
    batch: int = 1
    max_attempts: int = 8
    retry_base: float = 15
    retry_max: float = 900
    lease: float = 120
    timeout: float = 90
    source_node: str = 'node1'
    source_msp: str = 'Org1MSP'

    def __post_init__(self):
        numbers = (self.poll, self.retry_base, self.retry_max, self.lease, self.timeout)
        if (any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in numbers)
                or type(self.batch) is not int or not 1 <= self.batch <= 100
                or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100
                or not 0.1 <= self.poll <= 3600 or self.retry_base > self.retry_max
                or self.retry_max > 86400 or self.timeout > 90 or self.lease > 86400
                or self.lease < self.timeout + 10
                or (self.source_node, self.source_msp) != ('node1', 'Org1MSP')):
            raise DeliveryError('CONFIG_INVALID')

    @classmethod
    def from_settings(cls, settings):
        return cls(**{name: getattr(settings, 'blockchain_' + field) for name, field in {
            'poll': 'worker_poll_seconds', 'batch': 'worker_batch_size',
            'max_attempts': 'worker_max_attempts', 'retry_base': 'worker_retry_base_seconds',
            'retry_max': 'worker_retry_max_seconds', 'lease': 'worker_lease_seconds',
            'timeout': 'adapter_timeout_seconds', 'source_node': 'source_node',
            'source_msp': 'source_msp',
        }.items()})


def adapter_environment(settings):
    """Worker-only validation; the API never reads these files or starts Node."""
    if (tuple(settings.blockchain_adapter_command) != FIXED_COMMAND
            or settings.blockchain_gateway_endpoint != '127.0.0.1:7051'
            or settings.blockchain_client_msp_id != 'Org1MSP'
            or settings.blockchain_source_msp != 'Org1MSP'
            or settings.blockchain_source_node != 'node1'
            or settings.blockchain_channel != 'labchain-channel'
            or settings.blockchain_chaincode != 'labchain-anchor'):
        raise DeliveryError('CONFIG_INVALID')
    paths = {
        'BLOCKCHAIN_GATEWAY_TLS_CA_PATH': settings.blockchain_gateway_tls_ca_path,
        'BLOCKCHAIN_CLIENT_CERT_PATH': settings.blockchain_client_cert_path,
        'BLOCKCHAIN_CLIENT_KEY_PATH': settings.blockchain_client_key_path,
    }
    try:
        for name, path in paths.items():
            if path is None or not path.is_absolute():
                raise DeliveryError('CREDENTIAL_INVALID')
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 65536 or not os.access(path, os.R_OK):
                raise DeliveryError('CREDENTIAL_INVALID')
            if name == 'BLOCKCHAIN_CLIENT_KEY_PATH':
                parent = path.parent.stat()
                if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                        or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
                    raise DeliveryError('CREDENTIAL_INVALID')
        if not os.access(FIXED_COMMAND[0], os.X_OK) or not Path(FIXED_COMMAND[1]).is_file():
            raise DeliveryError('CONFIG_INVALID')
    except OSError:
        raise DeliveryError('CREDENTIAL_INVALID') from None
    # No inherited NODE_OPTIONS, NODE_PATH, LD_PRELOAD, DB passwords, or proxy env.
    return {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TZ': 'UTC',
        'BLOCKCHAIN_GATEWAY_ENDPOINT': settings.blockchain_gateway_endpoint,
        'BLOCKCHAIN_CLIENT_MSP_ID': settings.blockchain_client_msp_id,
        'BLOCKCHAIN_CHANNEL': settings.blockchain_channel,
        'BLOCKCHAIN_CHAINCODE': settings.blockchain_chaincode,
        'BLOCKCHAIN_SOURCE_NODE': settings.blockchain_source_node,
        **{name: str(path) for name, path in paths.items()},
        'BLOCKCHAIN_READY_TIMEOUT_MS': '5000', 'BLOCKCHAIN_EVALUATE_TIMEOUT_MS': '10000',
        'BLOCKCHAIN_ENDORSE_TIMEOUT_MS': '30000', 'BLOCKCHAIN_SUBMIT_TIMEOUT_MS': '10000',
        'BLOCKCHAIN_COMMIT_TIMEOUT_MS': '30000',
    }


def run_bounded(argv, payload, env, timeout):
    """Drain both pipes concurrently, retaining at most 16 KiB per stream.

    A new process group lets timeout/output-limit cleanup reap the adapter and
    terminate its descendants. The adapter has no legitimate child processes.
    """
    if not 0 < len(payload) <= MAX_INPUT:
        raise DeliveryError('INVALID_INPUT')
    if timeout <= 0:
        raise DeliveryError('ADAPTER_TIMEOUT')
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(list(argv), shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT,
            start_new_session=True, close_fds=True)
    except OSError:
        raise DeliveryError('ADAPTER_PROCESS_FAILED') from None
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    sent = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream, kind in ((process.stdin, 'stdin'), (process.stdout, 'stdout'), (process.stderr, 'stderr')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_WRITE if kind == 'stdin' else selectors.EVENT_READ, kind)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DeliveryError('ADAPTER_TIMEOUT')
                for key, _ in selector.select(remaining):
                    if key.data == 'stdin':
                        try:
                            sent += os.write(key.fd, payload[sent:])
                        except BrokenPipeError:
                            sent = len(payload)
                        if sent == len(payload):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        elif len(buffers[key.data]) + len(chunk) > MAX_OUTPUT:
                            raise DeliveryError('INVALID_RESPONSE')
                        else:
                            buffers[key.data].extend(chunk)
        try:
            status = process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise DeliveryError('ADAPTER_TIMEOUT') from None
        return status, bytes(buffers['stdout'])
    except OSError:
        raise DeliveryError('ADAPTER_PROCESS_FAILED') from None
    finally:
        # Always kill the group, even if its leader exited while a child held pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def _require(condition):
    if not condition:
        raise DeliveryError('INVALID_RESPONSE')


def _hash(value):
    return isinstance(value, str) and HASH_PATTERN.fullmatch(value) is not None


def _uuid(value):
    return isinstance(value, str) and UUID_PATTERN.fullmatch(value) is not None


def block_number(value):
    if value is None:
        return None
    _require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None)
    result = int(value)
    _require(result <= 2**64 - 1)
    return result


def validate_anchor(anchor):
    keys = {'anchor_id', 'event_type', 'entity_type', 'entity_reference', 'content_hash',
            'previous_hash', 'created_at', 'source_node', 'source_msp', 'transaction_id'}
    _require(type(anchor) is dict and set(anchor) == keys)
    _require(_uuid(anchor['anchor_id']) and _uuid(anchor['entity_reference'])
             and isinstance(anchor['event_type'], str) and anchor['event_type'] in EVENT_TYPES
             and anchor['entity_type'] == 'REPORT' and _hash(anchor['content_hash'])
             and _hash(anchor['transaction_id'])
             and (anchor['previous_hash'] is None or _hash(anchor['previous_hash']))
             and isinstance(anchor['source_node'], str)
             and anchor['source_node'] in NODE_MSPS
             and NODE_MSPS[anchor['source_node']] == anchor['source_msp'])
    stamp = anchor['created_at']
    _require(isinstance(stamp, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', stamp) is not None)
    try:
        datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        raise DeliveryError('INVALID_RESPONSE') from None
    return anchor


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def parse_response(raw, status, action):
    try:
        _require(0 < len(raw) <= MAX_OUTPUT)
        response = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs,
                              parse_constant=lambda _: _require(False))
        _require(type(response) is dict and type(response.get('ok')) is bool and response.get('action') == action)
        if not response['ok']:
            _require(status == 1 and set(response) == {'ok', 'action', 'error'})
            error = response['error']
            _require(type(error) is dict and {'code', 'retryable', 'message'} <= set(error)
                     and set(error) <= {'code', 'retryable', 'message', 'transaction_id', 'validation_code', 'block_number'})
            code = error['code']
            _require(isinstance(code, str) and code in ADAPTER_CODES and type(error['retryable']) is bool
                     and error['retryable'] == ERRORS[code][0] and isinstance(error['message'], str))
            if 'transaction_id' in error:
                _require(_hash(error['transaction_id']))
            if 'validation_code' in error:
                _require(type(error['validation_code']) is int and 0 <= error['validation_code'] <= 255)
            if 'block_number' in error:
                block_number(error['block_number'])
            raise DeliveryError(code)
        _require(status == 0 and set(response) == {'ok', 'action', 'result'})
        result = response['result']
        if action == 'anchor_exists':
            _require(type(result) is bool)
        elif action == 'read_anchor':
            validate_anchor(result)
        elif action == 'submit_anchor':
            _require(type(result) is dict and set(result) == {'transaction_id', 'validation_code', 'block_number', 'confirmed', 'anchor'})
            _require(result['confirmed'] is True and type(result['validation_code']) is int
                     and result['validation_code'] == 0 and _hash(result['transaction_id']))
            block_number(result['block_number'])
            validate_anchor(result['anchor'])
            _require(result['anchor']['transaction_id'] == result['transaction_id'])
        else:
            _require(False)
        return result
    except (ValueError, TypeError, KeyError, RecursionError):
        raise DeliveryError('INVALID_RESPONSE') from None


class GatewayAdapter:
    def __init__(self, settings):
        self.environment = adapter_environment(settings)
        # Reuse the Node adapter's cryptographic role/key/CA validation offline.
        status, raw = run_bounded(CREDENTIAL_COMMAND, b'{}', self.environment, 5)
        try:
            result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
        except (ValueError, TypeError, RecursionError):
            raise DeliveryError('CREDENTIAL_INVALID') from None
        if status != 0 or type(result) is not dict or set(result) != {'ok'} or result['ok'] is not True:
            raise DeliveryError('CREDENTIAL_INVALID')

    def call(self, request, timeout):
        payload = json.dumps(request, separators=(',', ':'), allow_nan=False).encode('utf-8')
        status, raw = run_bounded(FIXED_COMMAND, payload, self.environment, timeout)
        if not raw and status != 0:
            raise DeliveryError('ADAPTER_PROCESS_FAILED')
        return parse_response(raw, status, request['action'])
