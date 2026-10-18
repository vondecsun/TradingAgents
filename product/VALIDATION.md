# v0.1 validation record

Date: 2026-10-17. Environment: Linux, Python 3.12, Node 24.

## Passed

- `python -m pytest product/tests -q -o addopts=''`: **11 passed**.
- Account/session isolation and logout revocation.
- Paper cash reservation/release, insufficient cash, T+1 sell restriction,
  duplicated order requests, atomic cash ledger and cross-account rejection.
- Concurrent paper orders do not overspend; concurrent jobs do not overbook quota.
- No lookahead in chart/report snapshots; single-price days conservatively do not fill.
- CSV malformed OHLC rejection, immutable bars, source retained as untrusted text.
- Analysis queue cancellation, quota release, subprocess report generation,
  service-restart interrupted-job handling.
- Billing wrong signature/wrong amount rejection and same/different-event duplicate-payment deduplication.
- Raw passwords and bearer tokens are not stored in the database.
- Node syntax check; Python compile check.
- DOM integration with isolated running local server: registration, demo data,
  market search, durable task/report, paper order/fill, test subscription,
  broker-not-configured state, data page and logout.

A TestClient dependency emitted a deprecation warning concerning its HTTP client;
it did not fail tests. Revalidate framework updates before production use.

## Not verified / not delivered

- Graphical-browser screenshots, responsive visual layout, real Windows or mobile devices.
- Docker image build and target-host deployment (configuration supplied only).
- Native Windows installer, APK or iOS distribution.
- Live TradingAgents provider calls, commercial quote/news feeds, Guojin account/API integration.
- Real merchant checkout, refunds, reconciliation, production subscriptions or sales authorization.
- Corporate actions, exchange calendars and a complete A-share execution simulator.
- Multi-process/multi-host workers, PostgreSQL/Redis migration and production security audit.

Do not use these tests as evidence of profitability, market-data accuracy,
regulatory approval or readiness to accept real customer payments.

## v0.2 — 2026-10-18

- 17 backend tests pass, including the original 11 and new download/cache,
  validation/failure atomicity, tenant isolation, research/paper separation,
  adapter response validation and non-destructive schema upgrade checks.
- DOM flow test now includes the one-click button, automatic market navigation,
  online research report, folded CSV import, provider timeout feedback and
  unchanged existing paper ledger. Its provider fixture exists only in tests.
- Actual public provider + API + background report integration passed:
  000001.SZ, 2025-01-02 through 2025-01-10, 7 daily bars. See LIVE_HISTORY_CHECK.json.
- TickFlow was evaluated but returned HTTP403 in this environment; it is not
  enabled as a hidden fallback. Only the explicitly identified Yahoo source is used.
- Windows native runtime, graphical layout and the user's running local process
  have not been updated or verified automatically.

## v0.3 — original-core integration, 2026-10-18

- 23 product tests passed. Four of these execute the original graph with the
  source repository's scripted model/vendor fixtures, not replacement agents.
- Verified 12-role output, every original analyst tool route, full native reports,
  portfolio input, durable isolated memory, fewer calls on checkpoint resume,
  original backtest/summarize and automatic/manual reflection settlement.
- API checks cover native settings snapshots, missing-key rejection without
  fallback, batch quotas, explicit resume, cross-user resume/artifact denial.
- Selected original core tests: 204 passed across graph end-to-end, checkpoint
  lifecycle/resume, reporting/HTML, portfolio context, memory/time cutoff, backtest.
- 93 original tradingagents/cli Python source files are pinned and unchanged.
- No paid-provider live calls were made. Actual provider authentication, output
  quality, Windows native setup and target-host Docker build remain unverified.

## v0.3.1 — local test member

- 24 product tests passed, including opt-in loopback-only passwordless access,
  Host/Origin/cross-site rejection, idempotent account creation and privilege
  removal when the local test mode is disabled.
- Root Windows launchers explicitly enable local test mode and bind to loopback.
- The fixed test account receives a local-only test entitlement, never a paid subscription.

## v0.3.2 — task failure diagnostics

- 22 API/product tests passed in the current runtime (test_product.py), including
  a real child-process failure surfaced in the task list and fixed safe error mapping.
- Product worker/engine IPC explicitly uses UTF-8 on Windows.
- Provider response bodies, prompts and keys are never copied into public error text.
- Rechecked all 93 original Python source hashes: unchanged.
- No live provider call was made; the user's two failures remain undiagnosed until
  a new run supplies the classified error. This package is not proof of a model fix.
