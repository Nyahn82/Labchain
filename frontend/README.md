# RHU LabChain staff portal

Phase 7A: React, TypeScript, Vite, HashRouter, same-origin cookie authentication, and permission-aware staff workflows.

Requires **Node >=22.12.0**.

```bash
cd frontend
npm ci
npm run test -- --run
npm run build
```

Deploy only `dist/` output to `/var/www/rhu-labchain`. Do not publish source, configuration, or node_modules. Build output is ignored. The backend’s direct root serves compiled output when present, with the original landing page retained as a source-checkout fallback.

See [Phase 7A documentation](../docs/PHASE_7A_STAFF_FRONTEND.md) for architecture, route map, auth/CSRF, permissions, test coverage, operational limitations, and exact production deployment instructions. Preserve the installed HTTPS/Certbot configuration when applying the repository Nginx template changes.

For UI-only development use `npm run dev`; for compiled UI preview use `npm run preview`. Real secure-cookie authentication requires the same-origin HTTPS setup described in the phase guide.
