# Phase 7A — Staff Web Portal

The staff portal uses the existing Phase 3–6B APIs. This phase adds no database migration, clinical business logic, patient portal UI, public verification page, blockchain integration, analytics, or offline functionality.

## Architecture and dependencies

`frontend/src/main.tsx` mounts React, `App.tsx` defines HashRouter routes, `auth/` recovers the opaque-cookie session, `api/` owns HTTP/error handling, `components/` contains reusable semantic controls, and `pages/` contains staff workflows. Directory forms share declarative, allowlisted field definitions in `pages/resources.ts`. Values from APIs render as React text. There is no HTML injection or browser persistence layer.

Pinned runtime dependencies: React/React DOM 19.3.0, React Router DOM 7.18.4, Lucide React 1.47.0. Development dependencies: TypeScript 7.0.2, Vite 8.3.0, React Vite plugin 6.1.1, Vitest 5.0.1, React Testing Library 16.3.3, user-event 14.6.7, jest-dom 7.0.1, jsdom 30.1.0, and React/DOM/Node types. `package-lock.json` pins transitive dependencies; use `npm ci`.

**Node requirement: 22.12.0 or newer.** The maintained toolchain selected here requires this minimum, so an existing Node 20 installation must be upgraded. Validation used official Node 22.23.2 binaries. No Node runtime is needed to serve the compiled site.

The backend hosting-only adjustment in `app/main.py` serves `frontend/dist/index.html` and bounded `/assets/` files for direct previews. Without a build, it retains the original landing page from `frontend/static/backend-landing.html`. Traversal, symlink escapes, and directory reads under the asset route return 404. Production Nginx serves the separate deployment directory directly. API contracts and clinical services are unchanged.

## Routes and modules

All paths below follow `/#` on the same origin, for example `https://labchain.online/#/patients`.

| Route | Module |
| --- | --- |
| `/login` | Staff login, TOTP and recovery-code challenge |
| `/dashboard` | Existing API totals, recent orders, permission-aware quick actions |
| `/patients`, `/patients/:id` | Search, sex filter, pagination, creation, edit, detail, authorized activation status |
| `/physicians` | Physician CRUD, active filter, searchable facility selector |
| `/facilities` | Referring facility search, pagination, create/edit |
| `/staff`, `/staff/:id` | Staff CRUD, activity, linked account/status, controlled account creation |
| `/laboratory` | Laboratory setup navigation |
| `/laboratory/departments`, `/laboratory/samples` | Department/sample-type create/edit/deactivate |
| `/laboratory/tests`, `/laboratory/tests/:id` | Catalog, result-type/activity filters, sample mapping/default, reference ranges, interpretation rules |
| `/laboratory/panels`, `/laboratory/panels/:id` | Panel metadata, sections, composition, ordering, required flags |
| `/laboratory/reasons` | Active/inactive rejection reasons |
| `/orders`, `/orders/new`, `/orders/:id` | Search, status/priority filters, creation, detail, cancellation, append-only payments |
| `/orders/:id/specimens`, `/specimens/:id` | Register, collect, receive, reject, history and recollection |
| `/specimens` | Order-based specimen workspace |
| `/orders/:id/results`, `/results` | Result entry/draft edits, reference/flag context, confirmed review/verification |
| `/reports`, `/reports/:id`, `/orders/:id/reports` | Report generation, assignment, signing, approval, release, PDF/print, revocation, revision, verification metadata |
| `/administration`, `/administration/:id` | Accounts/status/roles, role/permission discovery, confirmed MFA reset |

Reference ranges and interpretation rules are reached through their parent test. Specimens and results use order-based workspaces because there is no global specimen/result list endpoint. Dashboard counts are returned API totals; unavailable metrics are omitted or labeled unavailable. There are no invented patient records, trends, or statistics.

## Authentication, CSRF, and authorization

- `GET /api/v1/auth/me` bootstraps and refreshes the session. No bearer token is used.
- Login posts to `/auth/login`. A `202` response with `mfa_required: true` shows the challenge in the login screen. TOTP posts to `/auth/mfa/verify`; recovery codes post to `/auth/mfa/recovery`. The backend controls the HttpOnly challenge cookie. Password/code fields are cleared after submission.
- The centralized client always uses relative `/api/v1` URLs, `credentials: "include"`, and `cache: "no-store"`.
- Authenticated POST/PUT/PATCH/DELETE requests read the current `rhu_csrf` cookie and send `X-CSRF-Token`. Login and pre-authentication MFA requests use the backend's same-origin challenge flow without session CSRF. If the backend cookie name is explicitly customized, build with the matching public `VITE_CSRF_COOKIE_NAME`; there is no API host setting.
- Logout calls the CSRF-protected `/auth/logout` endpoint, clears in-memory identity, and unmounts the private application. Authenticated 401 responses do the same. Failed logout remains visible with a retryable error.
- `AuthenticatedRoute` blocks anonymous routes. `PermissionGuard` protects route content and action controls separately from navigation. Permissions and roles come from `/auth/me`; the backend's `SYSTEM_ADMIN` bypass is reflected in `allowed()`. All writes remain subject to server RBAC and state checks.
- There is **no localStorage/sessionStorage use** for sessions, CSRF, credentials, records, or UI state. Vite variables are public; never put secrets into `VITE_*` variables.
- All API errors are mapped to safe messages for 401/403/404/409/422/5xx/network failure. Structured validation errors expose only sanitized field names, never submitted values or arbitrary server detail.

### Permission dependencies

Assign read permissions needed to discover records alongside write permissions. In particular:

- Order creation uses `PATIENT_READ`, `PHYSICIAN_READ`, and `LAB_MASTER_READ` for its selectors.
- The order-based specimen/result workspaces require `LAB_ORDER_READ` plus their own read/action permissions. New result entry retrieves `result_type` through `LAB_MASTER_READ`.
- Rejection reason discovery currently requires the backend's `REJECTION_REASON_MANAGE`, even when the intended operation is `SPECIMEN_REJECT`. The frontend reports that requirement; it does not bypass it.
- Signatory assignment requires `SIGNATORY_READ` and `SIGNATORY_MANAGE`. Optional template discovery requires `REPORT_TEMPLATE_READ`. Existing signatory profiles and facility/report configuration must already exist through the established backend setup workflows.
- Role discovery requires `ROLE_READ`; replacement requires `ROLE_ASSIGN`. Staff account creation without role-assignment permission submits an empty role set.
- Activation status requires `PATIENT_ACCOUNT_ACTIVATE` or `ACCOUNT_READ`.

## Workflow integrity

Forms construct explicit allowlisted payloads. Panel and individual-test selections remain distinct; backend panel expansion owns provenance. Sample mappings permit at most one selected default. The panel editor offers only sections from its current panel.

Amounts, numeric results, and reference decimals remain strings. The frontend never submits `numeric_value`, `flag`, or `reference_range_id`. Numeric thresholds and qualitative normal fields have separate headings. Interpretation and flags are laboratory context, not generated diagnoses. The diagnosis field contains only clinician-entered text.

Result edit buttons appear only for DRAFT. Review and verify require confirmation. Report action availability follows GENERATED/APPROVED/RELEASED/REVOKED and permission rules. Signing is offered only for unsigned assignments associated with the current staff identity. Approval requires at least one assignment and all signatures. The backend rejects stale or inconsistent actions with a conflict response.

Cancel, specimen rejection, result review/verification, report approval/release/revocation, account status/role changes, and MFA reset use labeled native dialogs. Rejections remain in specimen history; recollections create new records. Payments are append-only.

PDF delivery uses the authenticated backend endpoint, a temporary Blob URL, and URL revocation. Print records the requested copy count through the backend print endpoint, then downloads the official PDF for printing in the browser/PDF viewer. It cannot confirm that a physical printer completed the job. Internal report-storage paths are never rendered or constructed. Staff metadata uses “Report integrity verification”; no blockchain claim is made.

## Design and accessibility

The CSS-variable design system uses light gray surfaces, restrained raised/inset shadows, teal primary controls, readable system fonts, rounded cards, and semantic tables. Navigation becomes a mobile drawer; grids collapse and tables scroll within their containers. Status badges include readable text. Errors and success states are explicit. Forms have labels, decimal input modes, required-field indicators, keyboard focus outlines, and disabled busy states. Native dialogs provide focus containment, Escape dismissal, and focus restoration; busy submissions prevent dismissal. Reduced motion and print styles are included. Assets and fonts are bundled/local; there are no third-party scripts or telemetry.

## Build and tests

```bash
cd /opt/rhu-labchain/frontend
node --version                 # >=22.12.0
npm ci
npm run test -- --run
npm run build
```

Build output is `frontend/dist/`; dist, node_modules, coverage, and TypeScript build metadata are ignored. Source maps are disabled. There are no production credentials in frontend source or configuration.

```bash
cd /opt/rhu-labchain
.venv/bin/python -m pytest -vv -ra --tb=long
```

Frontend tests cover credentialed requests/CSRF, safe error mapping, auth bootstrap/login/logout/MFA, route permissions, patient forms/search/pagination, order provenance/cancellation, specimen transitions, decimal result payloads/immutability, report lifecycle/signing/version display, account roles/status/MFA reset, escaped API content, and keyboard dialogs. Hosting regression tests cover compiled/legacy entry delivery and asset path isolation. See the final implementation report for measured test counts.

For a local UI-only preview: `npm run dev` or `npm run preview`. Real cookie authentication should be tested through a same-origin HTTPS reverse proxy to Vite (development) or the compiled site (production). A standalone Vite server does not proxy production patient APIs. Do not weaken Secure-cookie settings to make an HTTP preview authenticate. Browser verification here uses synthetic intercepted API responses, not live patient records or production mutations.

## Hostinger deployment

These are manual deployment commands for the existing Ubuntu VPS. Development did not execute them or edit running Nginx. Run with Node >=22.12 already installed, after putting the reviewed source on the server. Keep the existing `.env`, backend service, database, and report directory intact.

```bash
cd /opt/rhu-labchain/frontend
node --version
npm ci
npm run test -- --run
npm run build

sudo install -d -o root -g root -m 0755 /var/www/rhu-labchain
sudo install -d -o root -g root -m 0755 /var/www/rhu-labchain/assets
# Assets first; retain earlier hashed assets so open tabs survive deployment.
sudo cp -a dist/assets/. /var/www/rhu-labchain/assets/
sudo chown -R root:root /var/www/rhu-labchain/assets
sudo find /var/www/rhu-labchain/assets -type d -exec chmod 0755 {} +
sudo find /var/www/rhu-labchain/assets -type f -exec chmod 0644 {} +
# Publish the new entry atomically after assets are available.
sudo install -o root -g root -m 0644 dist/index.html /var/www/rhu-labchain/index.html.next
sudo mv /var/www/rhu-labchain/index.html.next /var/www/rhu-labchain/index.html
```

Identify the installed site without guessing its file name:

```bash
sudo nginx -T 2>&1 | grep -n -E '^# configuration file|server_name|root '
```

The installed site was confirmed to be `/etc/nginx/sites-available/rhu-labchain` (enabled by a symlink). Back it up and open it for the reviewed change:

```bash
sudo cp -a /etc/nginx/sites-available/rhu-labchain /etc/nginx/sites-available/rhu-labchain.before-phase7a
sudoedit /etc/nginx/sites-available/rhu-labchain
```

Edit the **existing HTTPS server block for labchain.online**, preserving its certificate paths, TLS settings, redirects, and API proxy headers. The exact root change is:

```nginx
# Previous:
# root /opt/rhu-labchain/frontend;
root /var/www/rhu-labchain;
```

Within that same block, replace its legacy static frontend locations with:

```nginx
location = / {
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    try_files /index.html =404;
}
location = /index.html {
    add_header Cache-Control "no-store" always;
    try_files $uri =404;
}
location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header X-Content-Type-Options "nosniff" always;
    try_files $uri =404;
}
```

Keep the hidden-file deny rule and existing FastAPI reverse proxy to `http://127.0.0.1:5001`. HashRouter needs no history fallback or new backend API URL. Do not replace the live HTTPS configuration wholesale with `deploy/nginx-rhu-labchain.conf`: that repository file is an HTTP template and intentionally contains no certificate configuration.

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -I https://labchain.online/
curl -fsS https://labchain.online/api/v1/health
curl -fsS https://labchain.online/api/v1/ready
```

Open `https://labchain.online/#/login`. Verify a staff login, MFA where enabled, permissions, a read-only record view, and logout. Do not submit clinical mutations merely to smoke-test production. No database migration command is required. A frontend deployment does not require restarting the backend service; the optional direct-preview hosting adjustment takes effect on the next normal backend deployment.

For rollback, retain the prior deployed `index.html` in a private backup location before publishing; restore it atomically. Retaining previous hashed assets makes that rollback possible. Never copy source, `.env`, node_modules, logs, report files, or the repository itself into `/var/www/rhu-labchain`.

## Known limits and API gaps

No blocking backend/API gap was identified. Existing API permission combinations above are required; missing permissions are surfaced rather than bypassed. Staff account association uses authorized paginated `/users` discovery because there is no staff-ID account filter, so discovery may take several requests on a large installation. Signatory selectors show profile/staff IDs and license snapshots because the profile list does not embed staff names. Full names are present on report assignments.

The portal does not add global specimen/result search, reporting-configuration administration, audit browsing, account self-service/MFA enrollment, a patient portal, or a public verification page. Report facility/templates/signatory profiles are prerequisites managed through existing backend configuration. No Phase 7B work is included.

## Validation results and file inventory

- Full backend regression: **1,075 passed**, two existing Starlette/httpx/AnyIO deprecation warnings, 952.17 seconds. Includes seven new frontend-hosting boundary cases. Command: `.venv/bin/python -m pytest -vv -ra --tb=long`.
- Frontend: **71 passed** across four Vitest files. Command: `npm run test -- --run`.
- Production: TypeScript checking and Vite build passed. Build output is about 345 kB JavaScript (105 kB gzip) and 13.3 kB CSS (4.0 kB gzip).
- Chromium with synthetic API responses: login at 1440/768/390/320 px, dashboard at 1440/1024/768/390/320 px, no document overflow or page errors. Automated axe WCAG A/AA checks reported zero violations on these screens after fixing table contrast and keyboard scrolling. Native dialog Escape dismissal was checked. This is a scoped automated check, not a full accessibility certification or a production workflow test.
- Static source/build checks found no credential-storage calls, HTML injection sink, private credential markers, or external script source. Only the public CSRF cookie name is read from Vite configuration. `git diff --check` passed.
- Repository Nginx template passed an isolated `nginx -t` syntax check with temporary configuration and loopback listeners; the installed configuration was not changed.
- No schema, migration, clinical service, or running Nginx changes. No deployment or commit was performed.

Created:

- `frontend/package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`.
- `frontend/src/App.tsx`, `main.tsx`.
- `frontend/src/api/client.ts`, `useResource.ts`; `auth/Auth.tsx`; `layouts/Shell.tsx`.
- `frontend/src/components/UI.tsx`, `Form.tsx`, `Details.tsx`.
- `frontend/src/pages/Login.tsx`, `Dashboard.tsx`, `People.tsx`, `ResourcePage.tsx`, `resources.ts`, `Laboratory.tsx`, `Orders.tsx`, `Specimens.tsx`, `Results.tsx`, `Reports.tsx`.
- `frontend/src/types/domain.ts`, `utils/display.ts`, `styles/main.css`, `styles/portal.css`.
- `frontend/src/test/setup.ts`, `helpers.tsx`, `client.test.ts`, `auth.test.tsx`, `workflows.test.tsx`, `security.test.ts`.
- `frontend/static/backend-landing.html` (preserved original entry).
- `tests/test_phase_7a_frontend_hosting.py` and this document.

Modified: `.gitignore`, `app/main.py` (hosting only), `frontend/index.html`, `frontend/README.md`, `deploy/nginx-rhu-labchain.conf`, `deploy/README.md`, `deploy/FRONTEND-NGINX-MANUAL.md`.

Pre-existing user changes to `.env.example`, `pytest-full.log`, and `pytest-full.pid` were preserved. Validation output for this phase was written under `/tmp`, not over those files.
