# Google Cloud And OAuth Setup

Google is an optional identity provider for committee members and applicants. It is identity-only:
application data does not use Google APIs. Email magic links remain available independently when
transactional email delivery is enabled, and applicants may still continue as guests.

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
- `http://localhost:8000/applicant/auth/google/callback`
- `http://127.0.0.1:8000/auth/google/callback`
- `http://127.0.0.1:8000/applicant/auth/google/callback`

Production redirect URIs:

- `https://screener.pentacoop.com/auth/google/callback`
- `https://applications.pentacoop.com/applicant/auth/google/callback`

The current implementation uses the server-side authorization-code flow, so applicant access
requires the applicant redirect URI but no additional authorized JavaScript origin.

Use only the identity scopes `openid`, `email`, and `profile`. The backend verifies the returned
identity. Committee access applies the same allowlist used by email sign-in. Applicant access
requires the verified normalized Google email to match the application email and binds Google's
stable subject to that application.

## Local configuration

Set the following in `backend/.env.local`:

- `SESSION_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_APPLICANT_REDIRECT_URI`

Alternatively, place Google's downloaded OAuth client JSON under the ignored
`backend/secrets/` directory and set `GOOGLE_OAUTH_CLIENT_SECRETS_FILE` to its path. Do not commit
OAuth credentials.

Keep the frontend and backend on the same hostname family during local testing. The default uses
`localhost` for both so the temporary OAuth session cookie reaches the callback route.
