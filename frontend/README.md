# RHU LabChain public landing page

A responsive, dependency-free introduction to the project. No authentication, patient records, verification engine, dashboard, database mutations, or external asset requests are implemented.

## Files

- `index.html`: semantic page structure, copy, original inline SVG icons, and concept illustrations.
- `static/css/styles.css`: colors, typography, components, responsive breakpoints, focus states, and reduced-motion support.
- `static/js/main.js`: mobile navigation toggle with Escape handling and automatic closing.
- `static/assets/favicon.svg`: original project mark.

Use the same brand colors and spacing when integrating with a future Vue/Vuetify application. No framework is required to run this page.

## Links and truthful placeholders

Login and Access System link to `#system-access`, which explains that login is not available yet. Verify Laboratory Report links to `#verification`, which explains the proposed architecture and labels the displayed states as an illustrative example. Features and security capabilities are described as planned. There are no fake API responses, form submissions, patient data, or live verification requests.

## Preview

From `/opt/rhu-labchain`:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5001
```

The page is available at `http://127.0.0.1:5001/` on the VPS. An existing local SSH tunnel may be used to view it from another computer; do not bind the server publicly just to preview it.

Routes:

| Path | Behavior |
| --- | --- |
| `/` | HTML landing page |
| `/static/…` | Public frontend assets only |
| `/api/v1/` | Original root JSON response |
| `/api/v1/health` | Existing health check |
| `/api/v1/ready` | Existing MySQL readiness check |
| `/docs` | Existing FastAPI documentation |
| `/openapi.json` | Existing OpenAPI schema |

Database readiness remains independent of the public page. A 503 readiness response indicates an existing database connection problem, not a frontend failure.

## Deployment

Reuse `deploy/nginx-rhu-labchain.conf` and follow `deploy/README.md` after database readiness and systemd checks pass. The draft supports `labchain.online` over HTTP. It does not install a certificate or enable HTTPS. The active Nginx configuration is unchanged by frontend development.

Keep `.env`, private keys, configuration, logs, database exports, and clinical information outside the public frontend asset directory.

## Validation performed

- Chromium viewport checks at 1440, 1024, 768, 390, 375, and 320 pixels: no horizontal overflow, broken section anchors, external asset requests, or JavaScript errors.
- Mobile menu open/close, Escape, Login placeholder link, and no-JavaScript navigation checked.
- Automated axe WCAG A/AA checks at desktop and mobile sizes: zero reported violations after contrast corrections. This is an automated audit, not a claim of full accessibility certification.
- FastAPI returned 200 for the landing page, public assets, `/api/v1/`, `/api/v1/health`, `/docs`, and `/openapi.json`.
- `/api/v1/ready` retained its existing 503 database-unavailable response; database credentials and schema were not changed.
- The Nginx draft was validated and exercised in an isolated process with only its listeners changed to loopback port 18080. It served the frontend and proxied API/documentation requests correctly. This does not replace `sudo nginx -t` against the installed production configuration.
- Private files and directory listings were rejected by FastAPI and Nginx. Malformed above-root traversal requests were rejected by Nginx with 400.
- Public frontend files were checked for the configured database password; `.env` remains ignored by Git with mode 0600.
- Temporary test servers were stopped. The installed Nginx site and systemd configuration remain unchanged.

Browser tools, runtime libraries, and audit scripts were downloaded only under `/tmp`; application requirements and system packages were not changed.
