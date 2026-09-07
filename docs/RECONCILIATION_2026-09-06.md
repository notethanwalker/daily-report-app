# Daily Report reconciliation — 2026-09-06

This file is the authoritative implementation record for the reconciled app backlog.

## Completed / retained

- Markets table with per-ticker removal and inline expanded security detail.
- Startup, tab and provider loading/error states with retries and contextual messages.
- User-specific watchlists backed by shared symbol-level market/fundamental/history caches.
- Historical macro/rotation tracking with continuous freshness repair rather than a one-time bar-count backfill.
- Independent market cross-checking: Twelve Data primary plus Yahoo Finance daily-history verification on refreshed snapshots.
- Data-health coverage for freshness, verification, provider state and macro-history depth.
- Large Flow v2: significance is ranked separately from inferred bullish/bearish direction; provider unusualness remains visible as evidence.
- Events, Research, Portfolio, Opportunities, Alerts, Theses, Regime, Command Center and enhanced workspace architecture retained.
- Secure account architecture: encrypted email/name, Scrypt password hashes, opaque user IDs, hashed session tokens, same-origin HttpOnly cookie sessions, first-login name onboarding, account settings, and administrator approval workflow.
- New approved accounts inherit the existing default market watchlist while retaining independent ticker customization.

## External configuration dependency

- Account-approval requests are stored and visible to the owner immediately.
- Automatic approval-request email delivery is implemented but requires the private Render secret `AUTH_SMTP_APP_PASSWORD` (for the configured Gmail SMTP account). No password, password hash, encryption key, or SMTP secret belongs in this repository.

## Security boundary

Application credentials are not stored in plaintext. Runtime cryptographic keys reside only in Render service secrets. Authorized infrastructure administrators with sufficient service-level access can necessarily access runtime secrets; this is a hosting trust boundary rather than something application encryption can eliminate.
