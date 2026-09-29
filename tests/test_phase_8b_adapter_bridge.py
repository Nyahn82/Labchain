"""No real Gateway: protocol fixtures and tiny local subprocesses only."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from app.config import settings, Settings
from app.services import blockchain_adapter_service as bridge
from app.services.blockchain_delivery_service import Claim
from phase8b_delivery_support import NOW, TX, anchor

CLAIM = Claim(1, '11111111-1111-4111-8111-111111111111', 'REPORT_RELEASED',
    '22222222-2222-4222-8222-222222222222', 'a'*64, None, 'node1', 'Org1MSP', 1,
    '33333333-3333-4333-8333-333333333333', NOW)


def reply(action='submit_anchor', **changes):
    result = dict(transaction_id=TX, validation_code=0, block_number='42', confirmed=True, anchor=anchor(CLAIM))
    result.update(changes)
    return json.dumps(dict(ok=True, action=action, result=result)).encode()


def code(error):
    return error.value.code


@pytest.mark.parametrize('value,expected', [('0', 0), ('42', 42), (str(2**64-1), 2**64-1), (None, None)])
def test_block_conversion(value, expected):
    assert bridge.block_number(value) == expected


@pytest.mark.parametrize('value', [True, 1, -1, '01', '-1', '1.0', '1\n', str(2**64), '9'*100, {}])
def test_block_invalid(value):
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.block_number(value)
    assert code(error) == 'INVALID_RESPONSE'


def test_valid_submit_and_absent_block():
    for block in ['42', None]:
        result = bridge.parse_response(reply(block_number=block), 0, 'submit_anchor')
        assert result['validation_code'] == 0 and result['confirmed'] is True
        assert result['block_number'] == block


@pytest.mark.parametrize('changes', [
    {'confirmed': False}, {'confirmed': 1}, {'validation_code': 11}, {'validation_code': False},
    {'validation_code': '0'}, {'transaction_id': 'x'*64}, {'block_number': 42},
    {'block_number': str(2**64)}, {'unexpected': 'private'},
    {'transaction_id': 'c'*64}, {'anchor': {}},
])
def test_invalid_commit_reply_never_accepted(changes):
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(reply(**changes), 0, 'submit_anchor')
    assert code(error) == 'INVALID_RESPONSE'


@pytest.mark.parametrize('raw', [b'', b'{bad', b'[]', b'null', b'NaN', b'\xff',
    b'{"ok":true,"ok":false,"action":"anchor_exists","result":true}',
    b'{"ok":true,"action":"anchor_exists","result":"true"}',
    b'{"ok":true,"action":"anchor_exists","result":true,"secret":"private"}',
    b'['*1000+b']'*1000, b'x'*16385,
])
def test_invalid_json_and_envelopes(raw):
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(raw, 0, 'anchor_exists')
    assert code(error) == 'INVALID_RESPONSE'


@pytest.mark.parametrize('field,value', [('source_node', []), ('event_type', {}), ('created_at', '2026-99-27T00:00:00.000Z'),
    ('entity_reference', 'invalid'), ('transaction_id', 'bad'), ('content_hash', 'a'*64+'\n')])
def test_invalid_anchor_shapes(field, value):
    existing = anchor(CLAIM)
    existing[field] = value
    raw = json.dumps(dict(ok=True, action='read_anchor', result=existing)).encode()
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(raw, 0, 'read_anchor')
    assert code(error) == 'INVALID_RESPONSE'


@pytest.mark.parametrize('action,result', [('anchor_exists', True), ('anchor_exists', False), ('read_anchor', anchor(CLAIM))])
def test_valid_read_protocol(action, result):
    raw = json.dumps(dict(ok=True, action=action, result=result)).encode()
    assert bridge.parse_response(raw, 0, action) == result
    with pytest.raises(bridge.DeliveryError):
        bridge.parse_response(raw, 1, action)


@pytest.mark.parametrize('name', sorted(bridge.ADAPTER_CODES))
def test_finite_adapter_error_codes_and_flag(name):
    retryable = bridge.ERRORS[name][0]
    detail = dict(code=name, retryable=retryable, message='SYNTHETIC_PRIVATE raw stderr PEM')
    raw = json.dumps(dict(ok=False, action='submit_anchor', error=detail)).encode()
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(raw, 1, 'submit_anchor')
    assert code(error) == name and error.value.retryable is retryable
    assert 'SYNTHETIC_PRIVATE' not in str(error.value)
    detail['retryable'] = not retryable
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(json.dumps(dict(ok=False, action='submit_anchor', error=detail)).encode(), 1, 'submit_anchor')
    assert code(error) == 'INVALID_RESPONSE'


@pytest.mark.parametrize('changes', [{'code': 'MADE_UP'}, {'retryable': 1}, {'extra': 'secret'},
    {'validation_code': True}, {'transaction_id': 'bad'}, {'block_number': '-1'}])
def test_malformed_error_receipt(changes):
    detail = dict(code='COMMIT_TIMEOUT', retryable=True, message='private')
    detail.update(changes)
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.parse_response(json.dumps(dict(ok=False, action='submit_anchor', error=detail)).encode(), 1, 'submit_anchor')
    assert code(error) == 'INVALID_RESPONSE'


def run_program(program, timeout=2, payload=b'{}'):
    return bridge.run_bounded([sys.executable, '-c', program], payload, {'PATH': '/usr/bin:/bin'}, timeout)


def test_real_bounded_process_json_and_stderr():
    status, raw = run_program("import sys; data=sys.stdin.buffer.read(); sys.stderr.write('SYNTHETIC_PRIVATE'); sys.stdout.buffer.write(data)")
    assert status == 0 and raw == b'{}'


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_real_process_output_flood_is_bounded(stream):
    with pytest.raises(bridge.DeliveryError) as error:
        run_program(f"import sys; sys.{stream}.buffer.write(b'x'*1000000); sys.{stream}.flush()")
    assert code(error) == 'INVALID_RESPONSE'


def test_real_process_timeout_and_child_cleanup(tmp_path):
    pidfile = tmp_path / 'pid'
    program = f"import os,time,pathlib; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(10)"
    start = time.monotonic()
    with pytest.raises(bridge.DeliveryError) as error:
        run_program(program, timeout=0.3)
    assert code(error) == 'ADAPTER_TIMEOUT' and time.monotonic()-start < 3
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_process_closes_pipes_but_does_not_exit():
    with pytest.raises(bridge.DeliveryError) as error:
        run_program('import os,time; os.close(0); os.close(1); os.close(2); time.sleep(10)', timeout=0.1)
    assert code(error) == 'ADAPTER_TIMEOUT'


def test_input_limit_rejects_before_spawn(monkeypatch):
    monkeypatch.setattr(bridge.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not start'))
    for payload in [b'', b'x'*4097]:
        with pytest.raises(bridge.DeliveryError) as error:
            run_program('', payload=payload)
        assert code(error) == 'INVALID_INPUT'


def test_process_error_sanitized():
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.run_bounded(['/nonexistent/SYNTHETIC_PRIVATE'], b'{}', {}, 1)
    assert code(error) == 'ADAPTER_PROCESS_FAILED' and 'SYNTHETIC_PRIVATE' not in str(error.value)


@pytest.fixture
def configured(tmp_path):
    tmp_path.chmod(0o700)
    paths = {}
    for field in ['gateway_tls_ca_path', 'client_cert_path', 'client_key_path']:
        path = tmp_path / field
        path.write_text('SYNTHETIC_FILE_CONTENTS')
        path.chmod(0o600)
        paths['blockchain_' + field] = path
    return settings.model_copy(update=paths)


def test_environment_allowlist_and_fixed_command(configured, monkeypatch):
    monkeypatch.setenv('NODE_OPTIONS', '--require /SYNTHETIC_PRIVATE')
    monkeypatch.setenv('LD_PRELOAD', '/SYNTHETIC_PRIVATE')
    monkeypatch.setenv('DB_PASSWORD', 'SYNTHETIC_PRIVATE')
    env = bridge.adapter_environment(configured)
    assert all(name.startswith('BLOCKCHAIN_') or name in {'PATH', 'LANG', 'TZ'} for name in env)
    assert 'SYNTHETIC_FILE_CONTENTS' not in str(env) and 'SYNTHETIC_PRIVATE' not in str(env)
    captured = []
    def invoke(argv, payload, environment, timeout):
        if argv == bridge.CREDENTIAL_COMMAND:
            return 0, b'{"ok":true}'
        captured.append((argv, payload, environment, timeout))
        return 0, b'{"ok":true,"action":"anchor_exists","result":false}'
    monkeypatch.setattr(bridge, 'run_bounded', invoke)
    adapter = bridge.GatewayAdapter(configured)
    assert adapter.call(dict(action='anchor_exists', anchorId=CLAIM.event_uuid), 5) is False
    assert captured[0][0] == bridge.FIXED_COMMAND and captured[0][2] == env
    assert str(configured.blockchain_client_key_path) not in str(captured[0][0])


@pytest.mark.parametrize('changes', [
    {'blockchain_adapter_command': ['/bin/sh', '-c', 'node something']},
    {'blockchain_adapter_command': ['/tmp/node', bridge.FIXED_COMMAND[1]]},
    {'blockchain_gateway_endpoint': 'remote:7051'}, {'blockchain_source_node': 'node2'},
    {'blockchain_client_msp_id': 'Org2MSP'}, {'blockchain_channel': 'other'},
    {'blockchain_chaincode': 'other'},
])
def test_worker_configuration_rejects_command_and_source_changes(configured, changes):
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.adapter_environment(configured.model_copy(update=changes))
    assert code(error) == 'CONFIG_INVALID'


def test_credentials_optional_for_app_required_for_worker():
    config = Settings(_env_file=None, blockchain_gateway_tls_ca_path=None,
                      blockchain_client_cert_path=None, blockchain_client_key_path=None)
    assert config.blockchain_client_key_path is None
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.GatewayAdapter(config)
    assert code(error) == 'CREDENTIAL_INVALID'


@pytest.mark.parametrize('kind', ['permissions', 'parent', 'symlink', 'missing', 'relative'])
def test_worker_rejects_bad_key_paths(configured, kind):
    path = configured.blockchain_client_key_path
    if kind == 'permissions':
        path.chmod(0o644)
    elif kind == 'parent':
        path.parent.chmod(0o755)
    elif kind == 'symlink':
        link = path.with_name('link')
        link.symlink_to(path)
        configured = configured.model_copy(update={'blockchain_client_key_path': link})
    elif kind == 'missing':
        path.unlink()
    else:
        configured = configured.model_copy(update={'blockchain_client_key_path': Path('relative')})
    with pytest.raises(bridge.DeliveryError) as error:
        bridge.adapter_environment(configured)
    assert code(error) == 'CREDENTIAL_INVALID'


@pytest.mark.parametrize('changes', [
    {'poll': 0}, {'poll': float('nan')}, {'timeout': float('inf')}, {'batch': 0},
    {'max_attempts': -1}, {'retry_base': 1000}, {'lease': 90}, {'timeout': 100},
    {'retry_max': 1000000}, {'source_node': 'node2'},
])
def test_worker_options_validated_only_at_startup(changes):
    with pytest.raises(bridge.DeliveryError):
        bridge.WorkerOptions(**changes)


def test_app_readiness_with_delivery_enabled_and_missing_key(monkeypatch):
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import health
    monkeypatch.setattr(settings, 'blockchain_delivery_enabled', True)
    monkeypatch.setattr(settings, 'blockchain_client_key_path', None)
    monkeypatch.setattr(bridge.subprocess, 'Popen', lambda *a, **k: pytest.fail('web must never launch adapter'))
    monkeypatch.setattr(health, 'engine', MagicMock())
    with TestClient(app) as client:
        response = client.get('/api/v1/ready')
    assert response.status_code == 200 and response.json()['status'] == 'ready'


def test_adapter_process_invocation_uses_shell_false(monkeypatch):
    original = bridge.subprocess.Popen
    calls = []
    def checked(argv, **kwargs):
        assert isinstance(argv, list) and kwargs['shell'] is False and kwargs['close_fds'] is True
        calls.append(argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(bridge.subprocess, 'Popen', checked)
    run_program('print("{}")')
    assert len(calls) == 1


@pytest.mark.parametrize('status,raw', [(1, b'{"ok":false,"code":"CREDENTIAL_INVALID"}'),
    (0, b'{"ok":1}'), (0, b'{"ok":true,"extra":"private"}'), (0, b'not-json'),
    (0, b'{"ok":false,"ok":true}')])
def test_offline_credential_failure_prevents_adapter_construction(configured, monkeypatch, status, raw):
    calls = []
    def invoke(argv, *args):
        calls.append(argv)
        return status, raw
    monkeypatch.setattr(bridge, 'run_bounded', invoke)
    with pytest.raises(bridge.DeliveryError):
        bridge.GatewayAdapter(configured)
    assert calls == [bridge.CREDENTIAL_COMMAND]
