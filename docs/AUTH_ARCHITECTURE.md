# Daily Report authentication architecture

## Credential storage

- Passwords are never stored in plaintext and are never reversibly encrypted. They are stored as salted Scrypt password hashes.
- Email addresses and display names are encrypted with AES-GCM before they are written to Postgres.
- Email lookup uses a keyed HMAC-SHA256 value so authentication can locate an account without storing a plaintext searchable email column.
- Application tables use an opaque user ID instead of the user's email address.
- Session cookies contain random opaque tokens. Postgres stores only an HMAC digest of each session token.
- Session cookies are `HttpOnly`, `Secure`, and `SameSite=Lax`.

## Secret boundaries

The AES key, email-lookup HMAC key, and session-token pepper are Render service secrets. They are not present in GitHub, the browser bundle, or Vercel public environment variables. The initial administrator is bootstrapped using only encrypted/HMAC/password-hash material, never a plaintext password environment variable.

A hosting-platform administrator with sufficient access to the running Render service can necessarily access runtime secrets. No application architecture can make a decryption key usable by a server while simultaneously hiding that key from every administrator of that server. Access to the Render workspace should therefore remain restricted and protected with strong account security.

## Request path

The browser talks only to the same-origin Next.js `/backend/*` proxy. The proxy forwards requests to the Render API and strips legacy client-supplied identity headers. The backend derives the authenticated opaque user ID from the secure session cookie and injects that identity internally for legacy route compatibility.

## Account lifecycle

1. A visitor submits email and password.
2. The backend encrypts the email, hashes the password, creates a disabled `pending` account, and records the approval request.
3. When SMTP credentials are configured, the owner receives an approval-request email. Passwords and password hashes are never included in email.
4. The owner approves or rejects the account from Settings.
5. Approved accounts receive the default watchlist and access to the existing shared market/macro/intelligence data.
6. On first successful login, the account must provide a display name.
7. Name, email and password can later be changed under Account & security. Email/password changes require current-password verification as applicable.

## User-specific vs shared data

Market snapshots, fundamentals, macro data, news, flow intelligence and security calculations remain shared by symbol to avoid duplicate provider calls. Watchlists, holdings, preferences, alerts, theses and account details are scoped to the opaque user ID. A new approved user receives the existing default ticker watchlist, then may add or remove tickers independently.

## Approval-email dependency

Approval requests are persisted even when email delivery is unavailable. Automatic approval-request email delivery requires a private SMTP application password in the Render service secret `AUTH_SMTP_APP_PASSWORD`; this secret must never be committed to GitHub or exposed to the browser.
