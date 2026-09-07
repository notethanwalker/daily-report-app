# Daily Report authentication architecture

## Credential model

The account system uses **email + password authentication**. The administrator-supplied login secret is treated as a password, not as a WebAuthn/FIDO passkey.

- Passwords are never stored in plaintext and are never reversibly encrypted. They are stored as salted Scrypt password hashes.
- Email addresses and display names are encrypted with AES-GCM before they are written to Postgres.
- Email lookup uses a keyed HMAC-SHA256 value so authentication can locate an account without storing a plaintext searchable email column.
- Application tables use an opaque user ID instead of the user's email address.
- Session cookies contain random opaque tokens. Postgres stores only an HMAC digest of each session token.
- Session cookies are `HttpOnly`, `Secure`, and `SameSite=Lax`.

## Secret boundaries

The AES key, email-lookup HMAC key, and session-token pepper are Render service secrets. They are not present in GitHub, the browser bundle, or Vercel public environment variables. The initial administrator is bootstrapped using only encrypted/HMAC/password-hash material, never a plaintext password environment variable.

A hosting-platform administrator with sufficient access to the running Render service can necessarily access runtime secrets. Access to the Render workspace should therefore remain restricted and protected with strong account security.

## Request path

The browser talks only to the same-origin Next.js `/backend/*` proxy. The proxy forwards requests to the Render API and strips legacy client-supplied identity headers. The backend derives the authenticated opaque user ID from the secure session cookie and injects that identity internally for legacy route compatibility.

## Account lifecycle

1. A visitor submits email and password.
2. The backend encrypts the email, hashes the password, and creates a disabled `pending` account.
3. The owner account sees pending requests under Settings → Pending account approvals.
4. The owner approves or rejects each request there. No approval or decision emails are sent.
5. Approved accounts receive the default watchlist and access to the existing shared market/macro/intelligence data.
6. On first successful login, the account must provide a display name.
7. Name, email and password can later be changed under Account & security. Email/password changes require current-password verification as applicable.

## User-specific vs shared data

Market snapshots, fundamentals, macro data, news, flow intelligence and security calculations remain shared by symbol to avoid duplicate provider calls. Watchlists, holdings, preferences, alerts, theses and account details are scoped to the opaque user ID. A new approved user receives the existing default ticker watchlist, then may add or remove tickers independently.

## Approval model

Account approval is intentionally in-app only. The owner account is the only role allowed to list pending requests or call approval/rejection endpoints. Pending accounts remain disabled and cannot create authenticated sessions until approved.
