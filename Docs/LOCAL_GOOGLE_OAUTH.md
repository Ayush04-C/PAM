# Local Google OAuth setup

Phase 4 supports local, read-only Google Calendar testing only. It never exposes
an OAuth callback publicly.

1. In Google Cloud, create or select a project and enable **Google Calendar API**.
2. Configure the OAuth consent screen, then create a **Web application** OAuth
   client with this authorized redirect URI:
   `http://127.0.0.1:8000/oauth/google/callback`
3. Generate a Fernet encryption key locally:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
4. Put the following values in the ignored `.env` file:

   ```text
   PAM_CALENDAR_BACKEND=google
   PAM_GOOGLE_CLIENT_ID=...
   PAM_GOOGLE_CLIENT_SECRET=...
   PAM_GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/oauth/google/callback
   PAM_CREDENTIAL_ENCRYPTION_KEY=...
   PAM_CREDENTIAL_STORAGE_PATH=.pam-google-credentials.bin
   ```

5. Start PAM locally with `python -m uvicorn pam.main:app --reload` and open
   `http://127.0.0.1:8000/oauth/google/start`.
6. The consent screen must request only
   `https://www.googleapis.com/auth/calendar.events.readonly`.
7. After a safe `{"status":"connected"}` callback response, call
   `POST /availability` with an inclusive date range and `Asia/Kolkata`.

The encrypted local credential file is ignored by Git and is temporary until
Phase 9 persistent credential storage. Do not publish the callback or commit
any of these values.
