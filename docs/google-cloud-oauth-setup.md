# Google Cloud And OAuth Setup

This checklist documents the planned local MVP setup for Google login and Google Sheets access.

## Google Cloud Project

1. Create a separate Google Cloud project named `Penta Application Screener`.
2. Configure the OAuth consent screen for testing.
3. Add Jeff's Google accounts as test users while the app is local/MVP-only.
4. Enable the APIs needed for the current milestone and planned report milestone:
   - Google Sheets API
   - Google Docs API
   - Google Drive API

## OAuth Client

1. Create an OAuth client for a web application.
2. Add local JavaScript origins:
   - `http://localhost:5173`
   - `http://127.0.0.1:5173`
3. Add local redirect URIs:
   - `http://localhost:8000/auth/google/callback`
   - `http://127.0.0.1:8000/auth/google/callback`
4. Store the client ID and secret in `.env.local`, or store Google's downloaded OAuth client JSON in `backend/secrets/`.
5. Do not commit OAuth credentials.

## Initial Scopes

Use the minimum scopes that support the MVP plus report generation:

- `openid`
- `https://www.googleapis.com/auth/userinfo.email`
- `https://www.googleapis.com/auth/userinfo.profile`
- `https://www.googleapis.com/auth/spreadsheets.readonly`
- `https://www.googleapis.com/auth/documents`
- `https://www.googleapis.com/auth/drive.file`

These scopes keep login simple, allow read-only application import from Google Sheets, and allow later Google Docs report generation with app-created Drive files.

## Local Environment

Create `.env.local` from `.env.example` or `backend/.env.example` and fill in:

- `SESSION_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`
- `GOOGLE_REDIRECT_URI`

For frontend-only values, create `frontend/.env.local` from `frontend/.env.example`.

For local browser testing, keep the app on one hostname family. The default setup uses `127.0.0.1` for both frontend and backend callback URLs so OAuth session cookies are sent back to the callback route.

If using Google's downloaded OAuth client JSON, store it under `backend/secrets/`, which is ignored by Git. A simple local filename is preferred:

- `backend/secrets/google-oauth-client.json`

The local backend can also point directly to Google's downloaded filename through `backend/.env.local`:

- `GOOGLE_OAUTH_CLIENT_SECRETS_FILE=./secrets/<downloaded-client-secret-file>.json`

Admin settings such as source Google Sheet link or ID, unit size, move-in date, income range, AI spending cap, and provider/model choices should live in the database, not `.env.local`.
