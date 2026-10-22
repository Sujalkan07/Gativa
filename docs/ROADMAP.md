# Production readiness roadmap

Gativa is a functional engineering prototype. This roadmap separates product correctness from operational hardening. Priorities reflect safety, exposure, and data integrity. GitHub issues are the active tracking source; close an item only when its acceptance checks pass.

## P0 — Required before private hosted use

1. **Protect the API and enforce request limits.** Put the UI and API behind TLS and SSO/OIDC, reject unauthenticated API traffic, strip spoofable identity headers, and enforce per-user and per-instance limits for analysis, geocoding, and simulation work. Add tests that prove unauthenticated requests are rejected and limits return a controlled response.
2. **Establish an operational release gate.** CI now runs backend tests (including SUMO on Linux) and the frontend TypeScript/build check for pull requests. Configure branch protection to require both checks after their first successful workflow run; add a tested backup/restore procedure and production error monitoring before hosting real user data.

## P1 — Required for reliable simulation service

3. **Make simulation execution resilient.** Move long-running prepare/optimization work out of request handlers, persist job lifecycle and results, clean up child SUMO processes after failures, and define interruption/retry behavior. Preserve the current same-demand baseline/optimized contract.
4. **Validate native SUMO and fallback as separate products.** Maintain deterministic reference-network fixtures with signals and unsignalized junctions; assert route insertion, completed trips, signal phases, telemetry coverage, reset/stop cleanup, and comparison parity in native mode. Keep fallback tests separate and assert all fallback outputs stay labelled as estimated.
5. **Validate traffic engineering assumptions.** Compare demand, timing, LOS/congestion scores, and recommendations against reviewed reference cases and measured traffic inputs. Document calibration coverage and confidence; don't promote the outputs as engineering design approvals.

## P2 — Scale and maintainability

6. **Harden persistence and scaling.** Move shared analysis/job state from SQLite and process-local dictionaries to a managed database before running multiple workers. Add retention, migration, backup, restore, and concurrency tests.
7. **Improve provider and runtime operations.** Add provider retry/backoff and quota telemetry, structured logs with request/simulation IDs, latency/error dashboards, and documented incident/recovery steps.
8. **Reproducible releases.** Pin or lock backend dependencies, publish supported Python/SUMO versions, and add a repeatable packaging/deployment path with configuration validation.

## Current evidence

- Local native SUMO end-to-end congestion and signal extraction, fallback corridor, fallback signal status, and explicit engine-mismatch comparison checks passed during the October 22, 2026 review.
- Backend test suite: 85 passed, 1 skipped. Frontend `npm run build` passed with a bundle-size warning.
- CI workflow has been added, but its GitHub Actions result is pending the next push/PR.
- Native signal-state rendering now has unit coverage for green, yellow, red, and inactive SUMO states.
- Fallback time now advances at the same 0.2-second tick configured for native SUMO; mixed native/fallback pairs no longer report misleading percentage comparisons.

## GitHub tracking

- P0: [API authentication and rate limiting](https://github.com/Sujalkan07/Gativa/issues/2).
- P1: [Durable, non-blocking simulation jobs](https://github.com/Sujalkan07/Gativa/issues/1).
- P1: [Native SUMO reference scenarios and calibrated validation](https://github.com/Sujalkan07/Gativa/issues/3).
- P2: [Production persistence, backup, and observability](https://github.com/Sujalkan07/Gativa/issues/4).
