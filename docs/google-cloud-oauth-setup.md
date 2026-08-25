# Google Cloud And OAuth Setup

Google is an optional identity provider for committee members. Applicant intake and application
data do not use Google APIs. Email magic links remain available independently when transactional
email delivery is enabled.

## Google Cloud project

1. Create a Google Cloud project named `Penta Application Screener`.
2. Configure the OAuth consent screen.
3. Add the intended Google accounts as test users while the consent screen is in testing mode.
4. No Drive, Sheets, Docs, or Picker API needs to be enabled.

## OAuth client

Create a Web application OAuth client and configure the origins used by the app.

Local JavaScript origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

Local redirect URIs:

- `http://localhost:8000/auth/google/callback`
- `http://127.0.0.1:8000/auth/google/callback`

Production:

- JavaScript origin: `https://screener.pentacoop.com`
- Redirect URI: `https://screener.pentacoop.com/auth/google/callback`

Use only the identity scopes `openid`, `email`, and `profile`. The backend verifies the returned
identity and then applies the same committee allowlist used by email sign-in.

## Local configuration

Set the following in `backend/.env.local`:

- `SESSION_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

Alternatively, place Google's downloaded OAuth client JSON under the ignored
`backend/secrets/` directory and set `GOOGLE_OAUTH_CLIENT_SECRETS_FILE` to its path. Do not commit
OAuth credentials.

Keep the frontend and backend on the same hostname family during local testing. The default uses
`localhost` for both so the temporary OAuth session cookie reaches the callback route.
