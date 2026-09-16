"""Use synthetic settings and block network access before importing the app."""

import os
import socket

import pytest

# Environment variables take precedence over the existing private .env file.
# Set every application field so tests never use production configuration.
os.environ.update({
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
