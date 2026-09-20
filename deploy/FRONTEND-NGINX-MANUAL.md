> **Phase 7A frontend deployment supersedes the legacy frontend instructions below.** Serve compiled Vite assets from `/var/www/rhu-labchain` and follow [the Phase 7A deployment guide](../docs/PHASE_7A_STAFF_FRONTEND.md#hostinger-deployment). Preserve the installed HTTPS/Certbot configuration. The historical `/opt/rhu-labchain/frontend` static root is no longer the production portal root.

# RHU LabChain frontend and Nginx deployment manual

Run these commands on the Hostinger VPS as `rhuadmin`, using an SSH terminal or Hostinger's VPS browser terminal. Paste one numbered step at a time. Enter your sudo password only at the terminal prompt; nothing appears while you type. Stop on any error and keep the error message for troubleshooting. Do not paste passwords, `.env` contents, or database credentials into chat.

This procedure installs the existing deployment files. It does not develop new features or change MySQL configuration, `.env`, SSH, UFW, database structure, or backend business logic.

## Latest verified state (2026-09-10)

The backend systemd service is now installed, active, and enabled. Its database password has been corrected in the private `.env`, and both health and readiness pass on `127.0.0.1:5001` after restart. Nginx still enables only the default welcome site. Complete the inspection in step 2, verify the existing backend in step 3 without reinstalling it, then continue with step 4 using administrator access. The inspection below records the earlier state.

## 1. Understand the original problem

Inspection on 2026-09-10 found:

- Only `/etc/nginx/sites-enabled/default` is enabled. It serves `/var/www/html`, which contains the Nginx welcome page.
- `/opt/rhu-labchain/deploy/nginx-rhu-labchain.conf` is a draft and is not enabled.
- The frontend HTML, CSS, JavaScript, and favicon exist and are readable by Nginx. No build step is needed.
- Both domain names resolve to this VPS at `187.53.137.228`.
- FastAPI is not listening on port 5001, and `rhu-labchain-node1.service` is not installed. API proxying needs the existing backend to be started.
- MySQL ports 3306 and 33060 listen only on `127.0.0.1`.

The desired request routing is:

| Public request | Destination |
| --- | --- |
| `/` | `/opt/rhu-labchain/frontend/index.html` |
| `/static/...` | Files under `/opt/rhu-labchain/frontend/static/` |
| `/api/...` | `http://127.0.0.1:5001/api/...` |
| `/docs` | `http://127.0.0.1:5001/docs` |
| `/openapi.json` | `http://127.0.0.1:5001/openapi.json` |

The existing catch-all proxy preserves the request path. Its `proxy_pass` has no trailing slash. The public listener is port 80; it does not open port 5001 or any MySQL port.

## 2. Confirm the files and current state

```bash
cd /opt/rhu-labchain
ls -l frontend/index.html frontend/static/css/styles.css frontend/static/js/main.js frontend/static/assets/favicon.svg
cat deploy/nginx-rhu-labchain.conf
ls -l /etc/nginx/sites-available /etc/nginx/sites-enabled
ss -lnt
```

The draft must contain:

```nginx
server_name labchain.online www.labchain.online;
root /opt/rhu-labchain/frontend;
```

If other sites have been enabled since the inspection, stop and have their configuration reviewed before replacing the default site.

## 3. Start the existing private backend persistently

Use the existing systemd draft so FastAPI keeps running after you close the terminal. This installs the existing service definition without changing application code or secrets.

First inspect the service and check whether it has already been installed:

```bash
cat /opt/rhu-labchain/deploy/rhu-labchain-node1.service
systemctl show rhu-labchain-node1.service -p LoadState -p ActiveState -p FragmentPath
systemctl is-active mysql
ss -lnt '( sport = :5001 )'
```

MySQL should report `active`. If it is inactive, stop and report that condition; this manual does not change MySQL.

The inspected state was `LoadState=not-found` with no listener on port 5001. For that state, install and start the existing service:

```bash
sudo install -o root -g root -m 0644 \
  /opt/rhu-labchain/deploy/rhu-labchain-node1.service \
  /etc/systemd/system/rhu-labchain-node1.service &&
sudo systemctl daemon-reload &&
sudo systemctl enable --now rhu-labchain-node1.service
```

If the service already exists, do not overwrite it: inspect it with `systemctl cat rhu-labchain-node1.service` and confirm it uses the expected project and `--host 127.0.0.1 --port 5001`. If a different process already owns port 5001, stop and identify it before starting another backend.

Check the backend:

```bash
systemctl status rhu-labchain-node1.service --no-pager
systemctl is-enabled rhu-labchain-node1.service
curl --fail --show-error -i --max-time 10 http://127.0.0.1:5001/api/v1/health
ss -lnt '( sport = :5001 )'
```

Expect an active service, `enabled`, HTTP 200, and a listener at `127.0.0.1:5001`. If the service has just started, allow a few seconds before the health check. Do not proceed until health succeeds. Do not bind FastAPI to `0.0.0.0` or `[::]`.

If it fails, inspect locally:

```bash
sudo journalctl -u rhu-labchain-node1.service -n 50 --no-pager
```

Review logs for secrets before sharing them. Do not repair database credentials as part of this procedure. The health check verifies the running API, not database readiness.

## 4. Install and enable the Nginx site

Keep the default configuration file as a rollback source. Remove only its enabled symlink. The draft declares `default_server`, so the old default site must be disabled to avoid a duplicate default-server error.

These checks should pass silently for the inspected state. If they fail, stop and re-inspect rather than overwriting files:

```bash
test ! -e /etc/nginx/sites-available/rhu-labchain &&
test ! -L /etc/nginx/sites-available/rhu-labchain &&
test ! -e /etc/nginx/sites-enabled/rhu-labchain &&
test ! -L /etc/nginx/sites-enabled/rhu-labchain &&
test "$(readlink /etc/nginx/sites-enabled/default)" = /etc/nginx/sites-available/default &&
echo 'Site state confirmed; continue with installation.'
```

Proceed only if the confirmation message appears:

```bash
sudo install -o root -g root -m 0644 \
  /opt/rhu-labchain/deploy/nginx-rhu-labchain.conf \
  /etc/nginx/sites-available/rhu-labchain &&
sudo ln -s /etc/nginx/sites-available/rhu-labchain \
  /etc/nginx/sites-enabled/rhu-labchain &&
sudo unlink /etc/nginx/sites-enabled/default &&
sudo nginx -t
```

Expected validation messages include `syntax is ok` and `test is successful`.

**If `sudo nginx -t` fails, stop. Do not reload Nginx.** Save its exact error. The running Nginx workers continue using their previous configuration until a successful reload. Use step 7 to restore the original site if needed.

## 5. Reload only after validation succeeds

Run validation again immediately before the reload. The `&&` ensures a failed validation prevents the reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Then check:

```bash
systemctl is-active nginx
```

Expect `active`. If reload reports an error, stop and inspect `sudo journalctl -u nginx -n 30 --no-pager`.

## 6. Verify the deployed website and API

Run the three required checks:

```bash
curl --fail --show-error -i --max-time 15 http://127.0.0.1/
curl --fail --show-error -i --max-time 15 http://labchain.online/
curl --fail --show-error -i --max-time 15 http://127.0.0.1/api/v1/health
```

Both homepages should return HTTP 200 and RHU LabChain HTML instead of `Welcome to nginx!`. The health route should return HTTP 200 with JSON.

Check assets, documentation, and the www hostname:

```bash
curl --fail --show-error -I --max-time 15 http://labchain.online/static/css/styles.css
curl --fail --show-error -I --max-time 15 http://labchain.online/static/js/main.js
curl --fail --show-error -I --max-time 15 http://labchain.online/static/assets/favicon.svg
curl --fail --show-error -sS -o /dev/null -w 'docs: %{http_code}\n' --max-time 15 http://labchain.online/docs
curl --fail --show-error -sS -o /dev/null -w 'openapi: %{http_code}\n' --max-time 15 http://labchain.online/openapi.json
curl --fail --show-error -sS -o /dev/null -w 'www homepage: %{http_code}\n' --max-time 15 http://www.labchain.online/
ss -lnt
```

Expect HTTP 200 for each route. Confirm these private listeners:

- FastAPI: `127.0.0.1:5001`
- MySQL: `127.0.0.1:3306`
- MySQL X Protocol, if running: `127.0.0.1:33060`

Open **http://labchain.online/** on your own computer to independently verify public access. Hard-refresh with Ctrl+Shift+R if necessary.

This deployment is HTTP only. There is no HTTPS listener or certificate configured. The frontend footer currently links to HTTPS; that link will require a separate TLS deployment. If the browser automatically upgrades to HTTPS, use the explicit HTTP address and compare with the curl results.

## 7. Restore the original default site if necessary

This rollback applies after step 4 has enabled `rhu-labchain` and removed the default symlink. If step 4 stopped partway through, inspect `ls -l /etc/nginx/sites-enabled` first; do not unlink a missing entry or recreate an existing one.

```bash
sudo unlink /etc/nginx/sites-enabled/rhu-labchain &&
sudo ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default &&
sudo nginx -t
```

If validation fails, stop and report the exact error. If it succeeds, restore the running configuration:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Rollback restores the Nginx welcome page. It does not remove frontend files or change the private backend service.

## Troubleshooting

| Result | What to check |
| --- | --- |
| `sudo: a password is required` | Run the command in your interactive VPS terminal and enter the password there. |
| `duplicate default server` | Inspect `sites-enabled`; only one site may declare `default_server` for each address and port. Do not reload. |
| `File exists` when creating a symlink | Stop and inspect the enabled sites. The command may have already run. |
| Homepage works but API returns 502 | Check the backend service and direct health URL on `127.0.0.1:5001`. |
| CSS or JavaScript returns 404 | Compare the requested `/static/` path with the files under `frontend/static/`. |
| Homepage returns 403 | Check file traversal/read permissions with `namei -l /opt/rhu-labchain/frontend/index.html`; avoid broad permission changes. |
| Local homepage works but public domain does not | Check domain resolution and test HTTP from another computer. Do not change UFW as part of this procedure. |
| Browser fails on HTTPS while HTTP curl succeeds | TLS is not configured by this draft. |
| `/api/v1/ready` returns 503 | This is a separate database-readiness issue. Do not change database settings under this deployment task. |

Because an administrator password was shared in chat, change it in your VPS terminal using `passwd`. Do not store it in this manual or any command file.
