"""Serving a compiled portal must not expose source files or private paths."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app import main


def test_source_checkout_root_preserves_legacy_landing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'FRONTEND_BUILD_DIR', tmp_path / 'missing-build')
    with TestClient(main.app) as client:
        response = client.get('/')
    assert response.status_code == 200
    assert 'RHU LabChain' in response.text
    assert '/src/main.tsx' not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_built_portal_and_hashed_assets_are_served(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'FRONTEND_BUILD_DIR', tmp_path)
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app-hash.js').write_text('const compiled = true;')
    (tmp_path / 'index.html').write_text('<main>Compiled staff portal</main>')
    with TestClient(main.app) as client:
        response = client.get('/')
        asset = client.get('/assets/app-hash.js')
        missing = client.get('/assets/missing.js')
    assert response.text == '<main>Compiled staff portal</main>'
    assert response.headers['cache-control'] == 'no-store'
    assert asset.status_code == 200
    assert 'immutable' in asset.headers['cache-control']
    assert asset.headers['x-content-type-options'] == 'nosniff'
    assert missing.status_code == 404


@pytest.mark.parametrize('path', ['../private.txt', '../../private.txt', '/etc/passwd', 'link.txt', ''])
def test_asset_boundary_rejects_escape_and_directories(tmp_path, monkeypatch, path):
    assets = tmp_path / 'dist' / 'assets'
    assets.mkdir(parents=True)
    private = tmp_path / 'private.txt'
    private.write_text('private')
    (assets / 'link.txt').symlink_to(private)
    monkeypatch.setattr(main, 'FRONTEND_BUILD_DIR', tmp_path / 'dist')
    with pytest.raises(HTTPException) as exc:
        main.frontend_asset(path)
    assert exc.value.status_code == 404
