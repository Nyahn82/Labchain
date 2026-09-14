from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
import pytest
from sqlalchemy.exc import OperationalError

from app.main import app
from app.api import health


def test_existing_application_and_health_routes():
    assert isinstance(app, FastAPI)
    paths = app.openapi()["paths"]
    for path in ("/api/v1/", "/api/v1/health", "/api/v1/ready"):
        assert "get" in paths[path]
    assert health.health()["status"] == "ok"
    assert health.health()["node_id"] == "test-node"


def test_readiness_success_uses_mock_connection(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr(health, "engine", engine)
    assert health.ready() == {
        "status": "ready", "mysql": {"connected": True, "database": "phase2a_test"}
    }
    connection = engine.connect.return_value.__enter__.return_value
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"


def test_readiness_failure_remains_generic(monkeypatch):
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("private details"))
    monkeypatch.setattr(health, "engine", engine)
    with pytest.raises(HTTPException) as raised:
        health.ready()
    assert raised.value.status_code == 503
    assert raised.value.detail == "Database connection unavailable"
