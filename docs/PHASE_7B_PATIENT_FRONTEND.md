# Phase 7B — Patient portal, MFA, and public verification

Phase 7B extends the Phase 7A React application, HashRouter, cookie session, centralized client, and light neumorphic design system. It adds no backend behavior, database schema, migration, report-file change, analytics, offline storage, blockchain integration, or separate authentication service.

## Routes

All paths below are fragment routes on the existing origin, for example `https://labchain.online/#/patient/login`. Staff routes remain available and retain their permission guards.

| Route | Purpose |
| --- | --- |
| `#/patient/activate` | Manual activation-token entry and account creation |
| `#/patient/login` | Patient sign-in using the existing auth endpoint |
| `#/patient/mfa` | Authenticator or recovery-code challenge |
| `#/patient/setup-mfa` | Authenticator enrollment and one-time recovery codes |
| `#/patient` | Patient home, recent releases, security summary |
| `#/patient/profile` | Read-only patient profile |
| `#/patient/reports` | Own released reports, search, dates, pagination |
| `#/patient/reports/:reportId` | Historical snapshot and authenticated PDF actions |
| `#/patient/security` | Status, recovery regeneration, MFA disable, password change |
| `#/patient/access-history` | Own report views/downloads, with pagination |
| `#/verify` | Public verification-token entry |
| `#/verify/:token` | Public redacted integrity result |

## Architecture and role-aware authentication

`auth/PatientAccess.tsx` provides the patient guard and security context. `layouts/PatientShell.tsx` supplies simpler patient navigation and logout. Patient pages reuse the existing `api/client.ts`, abortable resource hook, dialogs, tables, detail fields, typography, spacing, colors, and focus states. The same `pages/Login.tsx` supports staff and patient entry points.

Both login screens submit to `POST /api/v1/auth/login`, then recover authoritative identity through `GET /api/v1/auth/me`. The login response's role list is not used to authorize routing. A current PATIENT role leads to `/patient`; other accounts use the staff portal. Patients opening staff routes are redirected to the patient portal, and non-patients opening patient routes return to the staff workspace. The backend remains authoritative for identity, ownership, RBAC, and session assurance.

The guard explicitly models UNKNOWN, UNAUTHENTICATED, PASSWORD_AUTHENTICATED_MFA_SETUP_REQUIRED, MFA_CHALLENGE, AUTHENTICATED_PATIENT, and AUTHENTICATED_STAFF. A patient session first checks `GET /patient/security`. Required-but-unconfigured MFA leads to setup before clinical requests are made. Required MFA with an unverified session returns to sign-in with a notice. Optional MFA policy is respected: clinical reads remain available when the backend allows them, while security mutations still follow the backend's verified-session requirement.

The client recognizes only the backend's allowlisted `MFA_ENROLLMENT_REQUIRED`, `MFA_REQUIRED`, and `MFA verification required.` 403 details. These become a policy event, never raw UI text. Enrollment errors invalidate the previously cached security status; verification errors clear client identity and return to sign-in. Ordinary 403s remain generic permission errors. Authenticated 401 clears the private app and patient guards send the user to patient login. There are no automatic retry loops. Older session-bootstrap requests are aborted when a newer login refresh or logout takes precedence; regression tests ensure a delayed pre-login response cannot replace a newly authenticated identity.

Non-sensitive completion notices live briefly in the existing auth context, so route guards cannot discard password-change or reauthentication feedback while clearing identity. No credentials or MFA material are placed in router state or auth context.

## Activation

Activation accepts a pasted token, username, password, and matching confirmation. Password guidance and input bounds follow the backend: at least 12 and at most 1,024 characters; username at most 60 characters. The POST body contains only `activation_token`, `username`, and `password`.

The token is never accepted from query parameters or route fragments. Form inputs clear when submitted; the response never redisplays the token. Success shows “Activation complete” with a “Go to login” link. Activation does not assume that a session was created. Invalid, expired, used, unavailable-username, or malformed activation responses use a safe combined message.

## MFA challenge and enrollment

A patient login response with `mfa_required: true` opens `#/patient/mfa`. It submits only `{code}` to `/auth/mfa/verify` or `{recovery_code}` to `/auth/mfa/recovery`. The HttpOnly challenge cookie is neither read nor represented in frontend state. A challenge-page reload can still submit to the backend; expired challenges give a generic failure and a route back to sign-in.

Enrollment starts only after an explicit button press; React effects do not create or rotate secrets. `POST /patient/mfa/totp/enroll` returns the setup key and provisioning URI. The new pinned dependency [qrcode.react 4.2.0](https://github.com/zpao/qrcode.react) renders that URI as a local SVG with descriptive accessible text and a manual key fallback. There is no remote QR service, image request, or provisioning-URI link.

Confirmation submits the six-digit `{code}` to `/patient/mfa/totp/confirm`. On success, the enrollment key and URI are removed from component state and the returned recovery codes are shown. The security/auth session is refreshed after the user acknowledges saving the codes, then the portal opens. Leaving setup unmounts its sensitive state. Late enrollment responses are discarded after unmount.

## Recovery codes and account security

The shared one-time component says “Save these codes now. They cannot be viewed again.” It renders an accessible list, provides an explicit clipboard-copy action and a locally generated text-file download, and requires acknowledgement before Continue. Setup navigation links are hidden during the one-time display. A browser unload warning helps prevent accidental loss. A SPA back/navigation action can still discard the codes; returning does not retrieve them again. Lost codes must be replaced through the authenticated regeneration workflow.

Only a user-requested copy or download exports these codes. The application has no persistent browser store. Clipboard/file handling after the explicit export is controlled by the user/browser. Temporary download object URLs are revoked after delivery or on unmount. Codes disappear after acknowledgement or leaving the page.

Security settings read `/patient/security` and show the required-policy flag, authenticator state, current-session verification, and unused recovery-code count. They do not show existing TOTP keys or recovery codes.

- **Regenerate:** warns that old unused codes stop working; submits `{password, totp_code}` to `/patient/mfa/recovery-codes/regenerate`; displays the new set once.
- **Disable:** requires a high-impact acknowledgement and password plus exactly one of TOTP/recovery proof; submits to `/patient/mfa/disable`. The UI explains session revocation and the need to set up MFA again when policy requires it. Successful disable clears auth state and returns to login.
- **Password change:** validates confirmation and sends only `{current_password, new_password}` to `/auth/change-password`. Success clears auth state and shows “Password updated. Please sign in again.”

Sensitive forms clear password/code inputs immediately on submission, disable controls while pending, and clear their temporary value object when the request finishes. The MFA-disable proof-method selector is inside the disabled form fieldset, so switching methods cannot replace a pending form or permit a concurrent submission; dialog dismissal remains blocked until the request finishes. An invalid proof never exposes hashes, encrypted secrets, or internal error details.

## Patient information and reports

The dashboard uses `/patient/me`, a small page of `/patient/reports`, and security status. Counts and recent reports come from these APIs. Empty reports mean only that no released reports are available yet.

The profile is read-only and renders an explicit field allowlist: patient code, name, birth date, sex, civil status, nationality, contact number, email, and address. No account ID, role, hash, or security detail is displayed.

The report list supports search and inclusive released-date filters supplied by the backend, plus pagination. It never sends a `patient_id` query parameter. It displays the backend's released-report summaries without maintaining an independent cache or adding historical revoked versions.

Report detail uses only `/patient/reports/{report_id}`. Snapshot result rows are sorted by `sort_order`, retain section headings, and show the historical test name, value, unit, reference text, and backend flag. Current catalog/range APIs are never queried to replace historical content. Human-readable flags retain text as well as color, with an explicit explanation that flags are not diagnoses. No diagnosis or treatment advice is generated.

Signatories, patient/physician details, and release/version information also come from the historical patient response. The verification section shows its approved integrity status; the patient API does not expose the verification token or a public verification link. A report ownership/status 404 always becomes “Report not available.” There is no attempt to query an alternate patient ID or staff report endpoint.

## Secure PDFs

View and Download both request `GET /patient/reports/{report_id}/pdf` through the existing credentialed, no-store client. Ownership, release, and SHA-256 checks remain backend responsibilities.

View opens a titled browser-native iframe inside the existing keyboard-accessible dialog, with a download fallback. Download creates a temporary Blob URL and local anchor. URLs are revoked on close/unmount or shortly after download; in-flight requests are aborted on unmount. No PDF is saved to an application browser database or offline cache. A 409 integrity failure is rendered as: “The report could not be verified and is not available for download. Please contact the laboratory.”

Native inline PDF support varies by browser, particularly on phones. Download remains available when the native preview is unavailable. The downloaded file is an explicit user export, not application-managed offline storage.

## Access history

`GET /patient/access-history` is paginated and rendered through a field allowlist: localized timestamp, readable activity (“Viewed report” / “Downloaded report”), and safe report reference. Raw audit JSON, IP addresses, database IDs, and unrelated events are not rendered.

## Public verification and the existing QR limitation

Public routes do not require a logged-in account or patient guard. They request `/api/v1/verify/{token}` with an encoded path token and render explicit VERIFIED, REVOKED, ALTERED, or NOT_FOUND text. Only the approved issuing facility, report date, and version metadata are shown. The API supplies no safe report code/reference, so the frontend does not invent one or substitute an internal ID. Messages are mapped from the known state; unexpected/private response fields are ignored. After a temporary failure, the patient can choose “Try again” or resubmit the same token. Both issue a fresh request without a page reload; there is no automatic retry loop. Changing the token aborts the previous request.

No patient name, patient code, birth date, result, diagnosis, order/report ID, filesystem path, or hash is displayed publicly. “Verified” describes the stored laboratory report's integrity; it is not a blockchain assertion or a check of an arbitrary uploaded copy.

**Existing released PDF QR codes continue pointing to `/api/v1/verify/{token}`.** They still open the redacted JSON API. This phase does not change that endpoint, rewrite released PDFs, or alter verification semantics. The richer `/#/verify/{token}` page can be opened directly or through manual token entry. Using the frontend URL in newly generated PDFs is a future, separately reviewed enhancement; no report URL configuration was silently changed here.

## Responsive behavior and accessibility

The patient shell uses a simple desktop navigation column and a compact wrapping mobile navigation area. Reports appear as readable cards; filters and PDF actions remain reachable on narrow screens. QR codes scale to their container, recovery codes wrap, and result tables are keyboard-scrollable. Existing focus outlines, native dialog focus handling, reduced-motion rules, and print styles are reused. Forms use associated labels and asynchronous status/alert text. Status is never color-only.

Browser validation uses synthetic data and intercepted APIs, not real patient records. Chromium/axe checks covered patient login, activation, public verification, home, profile, report list/detail, security, access history, enrollment, and recovery-code display at 1440, 768, 390, and 320 pixels: 44 page/viewport checks, no document overflow, no reported WCAG A/AA violations, no JavaScript page errors, and no third-party network requests. This is a scoped automated check, not full accessibility certification.

## No-secret-persistence policy

There are no application writes to localStorage, sessionStorage, IndexedDB, service-worker caches, or analytics. Tests forbid persistence and HTML injection sinks in application source, verify that only the public CSRF cookie name is read from Vite configuration, and exercise credential clearing and one-time displays. QR payloads remain local; activation credentials, MFA challenge data, TOTP keys, provisioning URIs, passwords, and recovery codes are absent from build/configuration. Patient data renders as React text.

All authenticated API calls retain `credentials: include`, same-origin `/api/v1` paths, no-store request handling, and the existing `rhu_csrf` / `X-CSRF-Token` behavior for unsafe methods. Public activation/login/challenge endpoints use their existing backend flow without authenticated-session CSRF. No API host is hardcoded. Vite variables are public and must never contain secrets.

## Tests and build

Requires Node **>=22.12.0**; this phase was validated with **Node 24.21.0**. The only added runtime dependency is pinned `qrcode.react` 4.2.0. Dependencies remain bundled locally.

```bash
cd /opt/rhu-labchain/frontend
npm ci
npm run test -- --run
npm run build

cd /opt/rhu-labchain
.venv/bin/python -m pytest -vv -ra --tb=long
```

The frontend suite includes the Phase 7A tests plus activation, authoritative role routing, MFA challenge/setup/policy transitions, local QR generation, one-time codes/copy/download, password/MFA session clearing, profile redaction, report filters/snapshots/ownership errors, authenticated PDF lifecycle, access history, public verification states/privacy, and no-secret-persistence guards.

Full backend regression: **1,075 passed**, two existing Starlette/httpx and AnyIO deprecation warnings, 919.87 seconds (15 minutes 19 seconds), rerun on 2026-09-20. No backend file was changed.

Final frontend result: **134 passed** across eight Vitest files (including all Phase 7A tests). TypeScript checking and Vite production build passed: 396.20 kB JavaScript / 119.23 kB gzip, and 18.26 kB CSS / 4.99 kB gzip. `git diff --check` passed.

## Hostinger deployment

Phase 7B uses the same `frontend/dist/` deployment and Nginx root as Phase 7A. No new Nginx location, API rewrite, certificate change, backend restart, or migration is required. Codex did not edit Nginx, restart a service, publish the build, or change released PDFs during this phase.

Run these commands manually after the reviewed source has been placed on the VPS. Keep the private `.env`, database, report files, and service configuration intact.

```bash
cd /opt/rhu-labchain/frontend
node --version                 # >=22.12.0
npm ci
npm run test -- --run
npm run build

sudo install -d -o root -g root -m 0755 /var/www/rhu-labchain/assets
sudo install -d -o root -g root -m 0700 /var/backups/rhu-labchain
if sudo test -f /var/www/rhu-labchain/index.html; then
  sudo cp -a /var/www/rhu-labchain/index.html /var/backups/rhu-labchain/index.before-phase7b.html
fi
# Publish assets first and retain older hashes for existing browser tabs.
sudo cp -a dist/assets/. /var/www/rhu-labchain/assets/
sudo chown -R root:root /var/www/rhu-labchain/assets
sudo find /var/www/rhu-labchain/assets -type d -exec chmod 0755 {} +
sudo find /var/www/rhu-labchain/assets -type f -exec chmod 0644 {} +
sudo install -o root -g root -m 0644 dist/index.html /var/www/rhu-labchain/index.html.next
sudo mv /var/www/rhu-labchain/index.html.next /var/www/rhu-labchain/index.html

curl -I https://labchain.online/
curl -fsS https://labchain.online/api/v1/health
```

Nginx should already use `root /var/www/rhu-labchain;` and the Phase 7A `/assets/` and no-store index locations. If Phase 7A's deployment is not yet applied, follow [its deployment guide](PHASE_7A_STAFF_FRONTEND.md#hostinger-deployment), preserving the installed HTTPS/Certbot and API proxy configuration. Do not publish the repository, source, node_modules, private environment, or report storage as static content.

Open `https://labchain.online/#/patient/login`, `/#/patient/activate`, and `/#/verify`. Use an authorized test account and appropriate test report for functional checks; do not mutate clinical records just to smoke-test a deployment. Existing QR links to the verification API continue working.

Rollback uses the retained older hashed assets and backed-up entry:

```bash
sudo install -o root -g root -m 0644 /var/backups/rhu-labchain/index.before-phase7b.html /var/www/rhu-labchain/index.html.next
sudo mv /var/www/rhu-labchain/index.html.next /var/www/rhu-labchain/index.html
```

## Continuation review — 2026-09-20

The patient implementation was already present in the working tree when development resumed. Review checked Phase 7A routing/authentication/CSRF and shared components, the Phase 6A/6B patient and MFA contracts, Phase 5B verification, and the existing frontend/backend tests. No independent frontend or new API was introduced.

Two reproduced defects were fixed:

- Resubmitting the same verification token after a failed request previously did nothing because the route parameter had not changed. Explicit attempts now refresh verification; a “Try again” button also retries the current token.
- The MFA-disable proof-method button previously remained active outside the pending form. It now disables with the rest of the form, preserving the in-flight operation and dialog guard.

Three added regression cases cover same-token resubmission, the retry button, and proof-method/dialog locking during a delayed disable response. Both original defect tests failed before the fixes. All 134 frontend tests then passed, and TypeScript/Vite production build passed. Chromium/axe validation was rerun against that build: all 44 page/viewport combinations passed the scoped checks described above. The required full backend command completed successfully: 1,075 passed, two existing deprecation warnings, exit code 0.

Only `frontend/src/pages/Verification.tsx`, `frontend/src/pages/patient/Security.tsx`, their two test files, and this document were edited during this continuation. The file inventory below describes the complete Phase 7B working tree, including work already present. Pre-existing tracked `pytest-full.log`/`pytest-full.pid` changes were left intact; the new full backend run writes to `/tmp/rhu-phase7b-backend.log`.

## Files and limitations

Created: `frontend/src/auth/PatientAccess.tsx`, `layouts/PatientShell.tsx`, `pages/Verification.tsx`, `pages/patient/Activation.tsx`, `Portal.tsx`, `PatientReport.tsx`, `Security.tsx`, `Shared.tsx`, `types/patient.ts`, `styles/patient.css`; test fixtures and `patient-auth.test.tsx`, `patient-security.test.tsx`, `patient-reports.test.tsx`, `verification.test.tsx`; this document.

Modified: frontend package/lock files, `src/App.tsx`, `src/api/client.ts`, `src/auth/Auth.tsx`, `src/pages/Login.tsx`, `src/styles/main.css`, the existing persistence security test, and the frontend README.

No blocking backend/API gap was identified. The documented existing QR/API target, absence of a public safe report reference/token in patient detail, one-time recovery-code visibility, and browser-native PDF support are intentional boundaries. There is no patient profile editing, SMS/email OTP, social sign-in, AI interpretation, offline report storage, PWA, or blockchain implementation. Phase 7B is the stopping point.
