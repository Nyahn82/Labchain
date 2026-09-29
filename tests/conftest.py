"""Use synthetic settings and block network access before importing the app."""

import os
import socket
from pathlib import Path
import json

import pytest

# Environment variables take precedence over the existing private .env file.
# Set every application field so tests never use production configuration.
os.environ.update({
    "MFA_SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "MFA_TOTP_ISSUER": "RHU LabChain",
    "MFA_CHALLENGE_TTL_MINUTES": "5",
    "MFA_MAX_CHALLENGE_ATTEMPTS": "5",
    "MFA_TOTP_VALID_WINDOW": "1",
    "MFA_RECOVERY_CODE_COUNT": "8",
    "MFA_CHALLENGE_COOKIE_NAME": "rhu_mfa_challenge",
    "PATIENT_MFA_REQUIRED": "true",
    "PATIENT_ACTIVATION_TTL_MINUTES": "30",
    "AUTH_SESSION_TTL_MINUTES": "480",
    "AUTH_SESSION_COOKIE_NAME": "rhu_session",
    "AUTH_CSRF_COOKIE_NAME": "rhu_csrf",
    "AUTH_COOKIE_SECURE": "true",
    "AUTH_COOKIE_SAMESITE": "strict",
    "REPORT_STORAGE_DIR": "/tmp/rhu-test-reports-unconfigured",
    "PUBLIC_BASE_URL": "https://verify.example.test",
    "REPORT_SIGNATURE_DIR": "/tmp/rhu-test-signatures-unconfigured",
    "APP_NAME": "RHU LabChain Test",
    "ENVIRONMENT": "test",
    "BLOCKCHAIN_DELIVERY_ENABLED": "false",
    "BLOCKCHAIN_GATEWAY_ENDPOINT": "127.0.0.1:7051",
    "BLOCKCHAIN_GATEWAY_TLS_CA_PATH": "/tmp/rhu-test-unconfigured/tls-ca.crt",
    "BLOCKCHAIN_CLIENT_MSP_ID": "Org1MSP",
    "BLOCKCHAIN_CLIENT_CERT_PATH": "/tmp/rhu-test-unconfigured/client.crt",
    "BLOCKCHAIN_CLIENT_KEY_PATH": "/tmp/rhu-test-unconfigured/client.key",
    "BLOCKCHAIN_CHANNEL": "labchain-channel",
    "BLOCKCHAIN_CHAINCODE": "labchain-anchor",
    "BLOCKCHAIN_ADAPTER_COMMAND": json.dumps(['/usr/bin/node', str(Path(__file__).resolve().parents[1] / 'blockchain/gateway-adapter/src/cli.js')]),
    "BLOCKCHAIN_WORKER_POLL_SECONDS": "2",
    "BLOCKCHAIN_WORKER_BATCH_SIZE": "1",
    "BLOCKCHAIN_WORKER_MAX_ATTEMPTS": "8",
    "BLOCKCHAIN_WORKER_RETRY_BASE_SECONDS": "15",
    "BLOCKCHAIN_WORKER_RETRY_MAX_SECONDS": "900",
    "BLOCKCHAIN_WORKER_LEASE_SECONDS": "120",
    "BLOCKCHAIN_ADAPTER_TIMEOUT_SECONDS": "90",
    "BLOCKCHAIN_SOURCE_NODE": "node1",
    "BLOCKCHAIN_SOURCE_MSP": "Org1MSP",
    "NODE_ID": "test-node",
    "NODE_NAME": "Test Node",
    "NODE_PORT": "5001",
    "DB_HOST": "database.invalid",
    "DB_PORT": "3306",
    "DB_NAME": "phase2a_test",
    "DB_USER": "phase2a_test",
    "DB_PASSWORD": "synthetic-test-only-%@:/",
})


def deny_network(*args, **kwargs):
    raise AssertionError("Tests must not connect to network services or production")


# Install before test collection as well as during test execution.
_network_guard = pytest.MonkeyPatch()
_network_guard.setattr(socket.socket, "connect", deny_network)
_network_guard.setattr(socket.socket, "connect_ex", deny_network)
_network_guard.setattr(socket, "create_connection", deny_network)


def pytest_unconfigure(config):
    _network_guard.undo()
