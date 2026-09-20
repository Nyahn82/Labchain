> **Phase 7A frontend deployment supersedes the legacy frontend instructions below.** Serve compiled Vite assets from `/var/www/rhu-labchain` and follow [the Phase 7A deployment guide](../docs/PHASE_7A_STAFF_FRONTEND.md#hostinger-deployment). Preserve the installed HTTPS/Certbot configuration. The historical `/opt/rhu-labchain/frontend` static root is no longer the production portal root.

# RHU LabChain Phase 1 deployment

This project remains a modular monolith. MySQL holds application data. No patient modules or blockchain implementation are included.

## Current deployment state

Verified on 2026-09-10: MySQL authentication is repaired using the application account `rhu_app` and the corrected password in the private `.env` file. The installed `rhu-labchain-node1.service` is active and enabled, and the restarted backend passes `/api/v1/health` and `/api/v1/ready` on `127.0.0.1:5001`. MySQL and Nginx are also active and enabled.

Nginx still has only Ubuntu's default site enabled and returns 404 for `/api/v1/ready`. The project Nginx configuration remains a draft awaiting installation with administrator access; noninteractive sudo requires a password in this session. Follow the Nginx installation steps below or `FRONTEND-NGINX-MANUAL.md`, skipping the already installed systemd unit. The draft serves the landing page from `frontend/` and proxies API and documentation requests to FastAPI. Stop at any failed check.

## Local configuration

The application reads `/opt/rhu-labchain/.env` using pydantic-settings. Existing process environment variables override that file. Keep `.env` owned by `rhuadmin` with mode `0600`. `.env.example` contains nonsecret example settings and a password placeholder; do not overwrite the existing `.env` with it.

SQLAlchemy uses `URL.create`, `pool_pre_ping=True`, and five-second driver I/O timeouts. Passwords are redacted in settings representations. Readiness returns HTTP 503 with a generic error when MySQL cannot be reached.

## Administrator inspection if authentication fails again

Run in the VPS terminal. The query does not select password hashes or password values:

```bash
sudo mysql --table -e "SELECT User, Host, plugin, account_locked, password_expired FROM mysql.user WHERE User='rhu_app'; SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='rhu_labchain'; SHOW GRANTS FOR 'rhu_app'@'localhost';"
```

If the account does not exist, `SHOW GRANTS` will fail after the earlier queries display their findings. Use those findings to decide the correction. The application must keep using `rhu_app` via `127.0.0.1:3306`, and the password must come from `.env`. Do not place a password in shell arguments or paste it into a chat. Administrator/root access is only for maintenance, never the FastAPI connection.

## Verify the application after authentication is repaired

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pip check
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5001
```

From a second terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/ready
```

Readiness must return:

```json
{"status":"ready","mysql":{"connected":true,"database":"rhu_labchain"}}
```

Stop the manually started Uvicorn process with Ctrl+C before starting systemd.

## Install systemd only if absent and readiness passes

The unit runs as `rhuadmin`, reads `.env` through the application, binds only to loopback, restarts on failure, and starts after networking and MySQL. No systemd `EnvironmentFile` is needed because the application parses dotenv itself.

```bash
sudo install -o root -g root -m 0644 /opt/rhu-labchain/deploy/rhu-labchain-node1.service /etc/systemd/system/rhu-labchain-node1.service
sudo systemctl daemon-reload
sudo systemctl enable --now rhu-labchain-node1.service
systemctl status rhu-labchain-node1 --no-pager
systemctl is-enabled rhu-labchain-node1
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/health
curl --fail --silent --show-error http://127.0.0.1:5001/api/v1/ready
```

## Install Nginx only after systemd passes

Inspection found only Ubuntu's default welcome site enabled. Recheck before installation if the server configuration has since changed. These commands preserve its source configuration and replace only the enabled symlink. Port 80 is already listening; no firewall changes are prescribed.

```bash
sudo install -o root -g root -m 0644 /opt/rhu-labchain/deploy/nginx-rhu-labchain.conf /etc/nginx/sites-available/rhu-labchain
sudo ln -s /etc/nginx/sites-available/rhu-labchain /etc/nginx/sites-enabled/rhu-labchain
sudo unlink /etc/nginx/sites-enabled/default
sudo nginx -t
```

Only if validation succeeds:

```bash
sudo systemctl reload nginx
systemctl is-active nginx
systemctl is-enabled nginx
curl --fail --silent --show-error http://127.0.0.1/api/v1/health
curl --fail --silent --show-error http://127.0.0.1/api/v1/ready
```

If validation fails, do not reload. Restore the enabled default site:

```bash
sudo unlink /etc/nginx/sites-enabled/rhu-labchain
sudo ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
sudo nginx -t
```

From another computer, verify `http://labchain.online/` and `/api/v1/ready`. The apex domain resolved to `187.53.137.228` during landing-page development. This external check is needed to verify public reachability independently of the VPS itself. The draft is HTTP only. HTTPS still requires certificate issuance and TLS configuration; a domain name alone does not enable it.

## Final checks

```bash
systemctl is-active mysql rhu-labchain-node1 nginx
systemctl is-enabled mysql rhu-labchain-node1 nginx
ss -lnt
```

Expect MySQL `127.0.0.1:3306`, MySQL X Protocol `127.0.0.1:33060`, and FastAPI `127.0.0.1:5001`. Ports 5002–5004 should not listen. Public listeners should be SSH and HTTP at this phase. Enabled units establish boot configuration; an actual reboot recovery test has not been performed.

## Git

`.gitignore` excludes `.env` and other local environment files, the virtual environment, Python caches, editor settings, and logs. `.env.example` is intentionally trackable. Review `git status --short` before staging. No commit is needed for these deployment steps.

## Public landing page

Frontend source lives in `frontend/index.html` and `frontend/static/`. It uses plain HTML, CSS, and a small mobile-navigation script. No build step or new backend dependency is needed. See `frontend/README.md` for behavior and testing details.

FastAPI serves the HTML at `/` and assets at `/static/`. The previous root JSON response is preserved at `/api/v1/`. `/api/v1/health`, `/api/v1/ready`, `/docs`, and `/openapi.json` keep their existing behavior.

When installed, Nginx serves `/` and `/static/` directly. The document root is only `/opt/rhu-labchain/frontend`, never the project root. API and documentation requests continue to the private FastAPI service. Do not put secrets or private documents under `frontend/static/`.
