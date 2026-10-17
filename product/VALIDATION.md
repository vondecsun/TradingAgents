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
