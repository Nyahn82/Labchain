# Workstream C: patient activation states

Patient activation is derived from the existing `patient_account_link` and
`patient_activation_token` tables. No additional field or migration is needed.
A pending invitation does **not** create a UserAccount. Successful redemption
creates the account, PATIENT role assignment and numeric patient/account link,
consumes the invitation and writes the audit event in the existing transaction.
Patient codes remain generated, immutable display identifiers.

## State model

| API state | Staff label | Meaning and action |
| --- | --- | --- |
| NOT_ACTIVATED | No portal account | No linked account or invitation history; verify identity and issue an invitation. |
| TOKEN_ACTIVE | Awaiting activation | Latest invitation is unused, unrevoked and not expired; reissue only when necessary. |
| TOKEN_EXPIRED | Invitation expired | Latest unused invitation has reached its expiry; issue a replacement. |
| TOKEN_REVOKED | Invitation revoked | Latest invitation was revoked; issue a replacement after identity verification. |
| ACTIVATED | Portal activated | An account is linked, including historical accounts without token history; do not activate again. |
| REVIEW_REQUIRED | Account review required | A consumed invitation exists but no account is linked; investigate history instead of creating another account. |

A link takes precedence over token history. With no link, any consumed-token
history takes precedence over the latest invitation. Otherwise the latest token
by primary key determines status; expiry is evaluated against server UTC time
and the exact expiry instant is already expired. Revoked tokens are not pending.

`ACTIVATED` describes completed account association, not current login
eligibility. Suspension, disabled/locked accounts, PATIENT role membership and
MFA policy still independently control access. Use existing authorized account
administration for those issues. The workflow never unlinks, relinks, changes
credentials for, or reactivates an existing account. Review-required history is
not automatically repaired; administrators must investigate separately.

## Staff API and directory

Existing routes remain in use:

- GET `/api/v1/patients/{id}/activation-status` returns only the state.
- POST `/api/v1/patients/{id}/activation-token` requires
  `PATIENT_ACCOUNT_ACTIVATE` and existing session/CSRF validation.
- Status readers require `PATIENT_ACCOUNT_ACTIVATE` or `ACCOUNT_READ`.
- Patient-role or patient-linked accounts cannot use either staff activation
  route, even with an additional SYSTEM_ADMIN role.
- GET patient detail/list adds `activation_status` only for authorized staff
  status readers who also have existing `PATIENT_READ`. Other readers receive
  the original fields with the new field omitted, not a fabricated default.
- Directory projection uses three bounded queries for the current page instead
  of a separate status request per patient. It never selects token hashes or
  account credentials. All original directory pagination/search behavior stays.
- CREATE/PATCH patient contracts are unchanged; neither accepts activation state
  or a manually assigned patient code. Public patient profile remains unchanged.

Issue/reissue retains the existing patient-first row lock, hash-only token
storage, expiry policy, revocation of earlier valid invitations, audit event and
single transaction. Public redemption retains its generic invalid/expired-token
error for unknown, revoked, expired, consumed or already-linked tokens, avoiding
public disclosure of patient/account state. A consumed history without a link
now also blocks both new issuance and redemption of another token. Rollback
preserves the previous invitation if replacement/auditing fails.

## User experience and credentials

The patient directory shows a Portal activation column only for authorized
staff. The patient detail shows a meaningful state, explanation and refresh
control. Supported states offer issue/reissue after identity confirmation;
activated and review-required states offer no invitation action. List refresh,
returning from details and status refresh retrieve current server state.

The issued token is shown only in the issuance dialog to the issuing staff
member. Staff must manually deliver it using their approved secure process;
there is no email/SMS integration or claim of delivery. The dialog displays the
actual returned patient code and expiration and a token-free activation-page
link. Nothing is written to browser storage, URL parameters, logs or clipboard.
Closing, navigation, permission/user changes or hiding the tab removes the
secret from the UI; late requests are aborted/ignored. A lost response requires
status refresh and deliberate reissue, never an automatic POST retry.

Public activation and patient login/MFA/portal pages use the existing contracts.
No production resources, migrations, identities or certificates are involved.

## Focused validation

Backend (isolated synthetic SQLite; ordinary pytest network protections remain):

```bash
.venv/bin/python -m pytest tests/test_patient_activation_states.py tests/test_phase_6a_patient_portal.py tests/test_phase_3a_authentication_rbac.py tests/test_phase_6b_mfa.py tests/test_phase_3b_identity_admin.py tests/test_auto_code_master_schemas.py -q -ra --tb=short
```

Frontend, from `frontend`:

```bash
npm run test -- --run src/test/patient-activation-staff.test.tsx src/test/patient-auth.test.tsx src/test/patient-security.test.tsx src/test/automatic-codes.test.tsx
npm run build
```

Coverage includes generated-code preservation, state projection and pagination,
permission filtering and patient/staff separation, expiry at the boundary,
reissue, replay, historical/restricted account links, duplicate username and
rollback/audit failures, portal ownership and MFA, loading/errors, one-time token
visibility, CSRF and cancellation under React StrictMode. Native MySQL activation
concurrency probes were not rerun; existing locking and uniqueness constraints
remain in place. These checks do not constitute a live delivery or production
smoke test.

Workstream B was finalized separately in local commit `ae37c1b`. Workstream A's
outstanding native migration-rehearsal verification remains a production-release
prerequisite; this work does not authorize deployment or remove that gate.
