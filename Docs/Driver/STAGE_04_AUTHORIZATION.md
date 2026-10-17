# Stage 4: Drive authorization and Google Cloud setup

Stage 4 implements local, operator-authenticated Google Drive authorization.
It reuses Calendar's Google OAuth client and encrypted file store. Calendar keeps
its existing scopes, routes, credential format and file. Drive uses a separate
client configuration and encrypted, versioned grant containing owner, verified
Google account, actual granted scopes, refresh credential and PAM permissions.
No Drive file tools, downloads, model calls or Supermemory writes are added.

## What the implementation enforces

- Drive is disabled by default. Enabling it requires Drive client credentials,
  an expected Google email, a PAM owner, a valid encryption key and an operator
  `PAM_APP_SECRET` of at least 32 characters.
- Provisioning accepts direct loopback requests with the exact configured Host;
  cross-origin browser requests are rejected. Management endpoints also require
  `Authorization: Bearer <PAM_APP_SECRET>`. The Google callback uses the one-time
  state created by an authenticated operator instead of a bearer header.
- State and its PKCE verifier expire after ten minutes, are consumed once and
  are limited to 32 pending attempts. Calendar and Drive have separate state
  stores. Each Drive router is bound to one fixed client/account/owner config;
  restart clears pending state. Use one local server worker.
- The requested scope is exactly `drive.metadata.readonly`. Unknown, partial or
  extra granted scopes are rejected. Drive does not request incremental grant
  aggregation. Separate clients/files do not guarantee independent Google-side
  revocation: verify actual behavior before production use.
- An authenticated Drive `about.get` checks the actual account email and stable
  permission ID. It does not list or retrieve files. Wrong-account authorization
  cannot replace the saved grant. Future reads must still enforce current consent.
- New/repeated authorization resets model-transfer permission to false. A missing
  replacement refresh token is accepted only when an existing matching grant
  can be refreshed and its account verified. Other failures preserve the old file.
- Encrypted writes use a private temporary file, flush/fsync and atomic replace.
  Wrong keys/corruption fail safely. Windows confidentiality also depends on the
  directory's ACL; `chmod` is not an owner-only Windows ACL guarantee. Keep the
  checkout and credentials in a directory accessible only to your account.
- Explicit connection checks use bounded Google calls (20-second request/refresh
  timeouts, no application retry loop). A workflow can involve multiple requests.
  Expired/revoked grants require reconnect; transient failures return a safe retry
  error. Offline status does not claim live connectivity.
- A separate permissions endpoint can authorize metadata transfer to the exact
  configured model destination, or withdraw read/transfer consent. Content
  transfer remains disabled until the content stage. There is no memory-storage
  permission or automatic Supermemory ingestion in Stage 4.
- Disconnect removes only the local Drive grant and pending Drive state. It does
  not revoke the Google app, alter Calendar, or promise to cancel requests already
  sent to Google. Permissions are loaded afresh by the future trusted composition;
  conversation/Drive tool wiring is still later-stage work.

## Google Cloud: every setup step

Use the Google account whose Drive PAM should access. For an initial test, prefer
an account with non-sensitive test files. Only that configured account and PAM
owner can be connected in this stage; this is not multi-user Google onboarding.

### 1. Select or create the project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Sign in with the account that manages your PAM Google Cloud project. The
   Cloud administrator and the Drive owner may differ, but the latter must be
   an allowed test user and match PAM's configured expected email.
3. Click the project selector in the top bar, beside the Google Cloud logo.
4. If Calendar already uses a PAM project, select that project. Reusing it is the
   default; you do not need another repository, MCP server or memory service.
5. If there is no suitable project, click **New Project**, enter a name such as
   `PAM`, choose an organization/location if your account requires one, and click
   **Create**. Wait for creation and select it from the project selector.
6. Check the selected project name before each following section. A project ID
   is not the OAuth client ID and is not a PAM credential value.

### 2. Enable Google Drive API

1. Open the navigation menu, then **APIs & Services > Library**.
2. Search for **Google Drive API**.
3. Open the Google Drive API result and click **Enable**.
4. If the page says **Manage**, the API is already enabled.
5. You can verify it under **APIs & Services > Enabled APIs & services**.
6. Leave Google Calendar API enabled if Calendar uses this project.

Reference: [Google's API enablement guide](https://developers.google.com/workspace/guides/enable-apis).

### 3. Configure Branding

1. Open **Google Auth Platform > Branding**. If the console offers **OAuth consent
   screen** under APIs & Services, it leads to the auth configuration.
2. If setup already exists for Calendar, review it rather than creating another
   consent configuration in the same project.
3. For a new setup, click **Get Started**.
4. Enter an app name, such as `PAM Personal Assistant`.
5. Choose a user support email you control.
6. Choose the audience when prompted (next section explains the choice).
7. Enter the developer/contact email where Google can contact you.
8. Review the displayed policy, accept it if applicable, and click **Create**.
9. In an existing Branding form, save any changes. Use real app/homepage/privacy
   information if requested for your publishing setup; do not invent domains.
10. A logo and public launch are unnecessary for this local development workflow.

### 4. Configure Audience and test users

1. Open **Google Auth Platform > Audience**.
2. For a personal Gmail account, choose **External**.
3. Choose **Internal** only if your Workspace organization supports it and all
   intended users are inside that organization.
4. For External development, leave publishing status at **Testing**.
5. Find **Test users**, click **Add users**, enter the Google email whose Drive
   you will connect, and save.
6. Do not publish just to avoid development reconnects. External Testing grants
   for these scopes have seven-day refresh-token expiry; production requirements
   are a separate release decision.

Reference: [Google consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent)
and [refresh-token expiry](https://developers.google.com/identity/protocols/oauth2#expiration).

### 5. Configure Data Access

1. Open **Google Auth Platform > Data Access**.
2. Click **Add or Remove Scopes**.
3. Search for or manually enter:

   ```text
   https://www.googleapis.com/auth/drive.metadata.readonly
   ```

4. Select it, update the selection and save.
5. If this project already lists Calendar scopes, retain them. The PAM Drive
   flow requests only the Drive scope; Calendar retains its existing request.
6. Do not add full `drive`, write scopes, `drive.file`, or `drive.readonly` for
   this stage. Content permission will require a later reviewed change.
7. This metadata scope is classified as **restricted**. Test-user development
   setup is not production verification. Review verification/security-assessment
   requirements before a broader release, particularly for hosted data transfer.

Reference: [Google Drive scope definitions](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

### 6. Create the Drive OAuth client

1. Open **Google Auth Platform > Clients**.
2. Click **Create client**.
3. Select **Web application**. PAM uses a local HTTP callback, even though you
   operate it from PowerShell.
4. Enter a descriptive name, such as `PAM Drive Local`.
5. Leave **Authorized JavaScript origins** empty for this server-side flow.
6. Under **Authorized redirect URIs**, click **Add URI** and enter exactly:

   ```text
   http://127.0.0.1:8000/oauth/google/drive/callback
   ```

7. Click **Create**. Keep the client ID and client secret in your local secure
   configuration. Do not paste them in a PR, commit, chat, or screenshot.
8. If you download client JSON, keep it outside the repository. PAM uses the
   individual environment settings below; it does not need that JSON file.
9. Do not replace Calendar's OAuth client or callback. If Cloud configuration
   has propagation delay, wait briefly before retrying authorization.

Reference: [Create OAuth credentials](https://developers.google.com/workspace/guides/create-credentials).

## Configure PAM locally

1. Open `D:\Learning\PAM` in your editor and edit the ignored `.env` locally.
   Do not overwrite the existing file by copying the example on top of it.
2. Add or update these values, replacing placeholders locally:

   ```dotenv
   PAM_DRIVE_ENABLED=true
   PAM_DRIVE_GOOGLE_CLIENT_ID=your-drive-client-id
   PAM_DRIVE_GOOGLE_CLIENT_SECRET=your-drive-client-secret
   PAM_DRIVE_GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/oauth/google/drive/callback
   PAM_DRIVE_GOOGLE_ACCOUNT_EMAIL=the-google-account-you-will-authorize@gmail.com
   PAM_DRIVE_OWNER_ID=cli-local
   PAM_DRIVE_CREDENTIAL_STORAGE_PATH=.pam-drive-credentials.bin
   PAM_DRIVE_MAX_CONTEXT_CHARS=20000
   ```

3. `cli-local` matches the default `PAM_MEMORY_CLI_OWNER_ID`. If you changed that
   owner, use its exact value. A future Telegram integration must map its own
   authenticated owner explicitly; setting a Telegram allowlist is not sufficient.
4. Keep the existing `PAM_CREDENTIAL_ENCRYPTION_KEY`. Replacing it makes existing
   Calendar credentials unreadable. Only if no key exists, generate one with:

   ```powershell
   .venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Save it as `PAM_CREDENTIAL_ENCRYPTION_KEY` in `.env`, privately.
5. Use an existing strong `PAM_APP_SECRET` of at least 32 characters. If none exists
   or it is a placeholder, generate a random one:

   ```powershell
   .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Store it privately as `PAM_APP_SECRET`. Do not rotate an actively used production
   secret casually. Generated keys/secrets appear in your terminal: keep them private.
6. Preserve existing Calendar/model/memory settings. Stage 4 does not require a
   model call or Supermemory connection, but normal Settings validation still
   applies to whichever backends your environment selects.
7. Run the offline check:

   ```powershell
   .venv\Scripts\python.exe -m pam.conversation.cli --status
   ```

   It still reports Drive tools as unimplemented. That is correct: OAuth setup
   does not register file tools.

## Connect and check the Google account

1. In PowerShell, enter `D:\Learning\PAM` and start one local server worker:

   ```powershell
   .venv\Scripts\python.exe -m uvicorn pam.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
   ```

   Bind only to loopback. Do not expose provisioning through a public reverse
   proxy. Keep access logs off so OAuth callback query codes/state are not logged.
   Keep this terminal running; do not restart during the authorization attempt.
2. Open a second PowerShell terminal in the same repository. Load the operator
   secret through a hidden prompt (enter the exact `PAM_APP_SECRET` from `.env`):

   ```powershell
   $pamSecureSecret = Read-Host 'PAM_APP_SECRET' -AsSecureString
   $pamHeaders = @{ Authorization = 'Bearer ' + [System.Net.NetworkCredential]::new('', $pamSecureSecret).Password }
   $pamBase = 'http://127.0.0.1:8000/oauth/google/drive'
   $pamStart = Invoke-RestMethod -Method Post -Uri "$pamBase/start" -Headers $pamHeaders
   Start-Process $pamStart.authorization_url
   ```

3. In the browser, choose exactly `PAM_DRIVE_GOOGLE_ACCOUNT_EMAIL`.
4. Check that the app name is yours and the requested permission is read-only
   Drive metadata. Only proceed with the expected app/account/permission. Google
   may show a test/unverified-app notice; Workspace administrator policy may
   also require approval. Do not approve an unexpected application.
5. Grant the requested permission. The browser returns to the local callback.
6. Success is:

   ```json
   {"status":"connected","model_transfer":"not authorized"}
   ```

7. In the second terminal, check saved permissions without a Google call:

   ```powershell
   Invoke-RestMethod -Uri "$pamBase/status" -Headers $pamHeaders
   ```

   Read consent is true; metadata and content transfer are false. No token,
   account email or owner is returned. The operator-only report includes the
   configured model destination so you can review transfer consent.
8. Explicitly verify refresh and account identity:

   ```powershell
   Invoke-RestMethod -Method Post -Uri "$pamBase/check" -Headers $pamHeaders
   ```

   Expected status: `refresh and account verified`. This is the live acceptance
   check for authorization, not a file-search or Calendar/Drive assistant demo.
9. Verify your existing Calendar availability workflow still succeeds. Record
   only the result, never credential values. If it fails, investigate before
   progressing to Stage 5.

## Optional metadata-transfer consent, withdrawal and disconnect

Google OAuth does not authorize sending data to a model. To explicitly approve
metadata transfer, first review the destination shown by status and your model
provider's data handling. This stores a policy for future integration; Stage 4
still sends no documents/metadata to that model.

```powershell
$pamStatus = Invoke-RestMethod -Uri "$pamBase/status" -Headers $pamHeaders
# Review $pamStatus.model_destination before continuing.
$pamPermission = @{
    allow_read = $true
    allow_metadata_transfer = $true
    confirmed_destination = $pamStatus.model_destination
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$pamBase/permissions" -Headers $pamHeaders -ContentType 'application/json' -Body $pamPermission
```

A fake/unconfigured model has no eligible destination. A changed provider, model
or endpoint invalidates metadata-transfer permission until reviewed again. Content
transfer requests are rejected in this stage. To withdraw both local permissions:

```powershell
$pamPermission = @{ allow_read = $false; allow_metadata_transfer = $false } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$pamBase/permissions" -Headers $pamHeaders -ContentType 'application/json' -Body $pamPermission
```

To remove the local Drive credential and invalidate pending Drive authorization:

```powershell
Invoke-RestMethod -Method Post -Uri "$pamBase/disconnect" -Headers $pamHeaders
```

This does not revoke access at Google. Removing the app from your Google Account
connections is a separate action that can affect related grants, including
Calendar when grants are grouped; do not use it as a routine local-disconnect test
on your working Calendar setup. Use a test setup for revocation experiments.
For this single-process provisioning flow, stop the server with Ctrl+C when done,
close the callback tab, and remove the local header variable:

```powershell
Remove-Variable pamHeaders, pamSecureSecret
```

## Troubleshooting and verification

| Result | Action |
| --- | --- |
| `redirect_uri_mismatch` | Match scheme, `127.0.0.1`, port and full callback path in Google Clients and `.env`. |
| Access denied / app blocked | Check the signed-in account, test-user list, audience and Workspace administrator policy. |
| Wrong Google account | Restart authorization and choose the configured email. Existing credentials remain unchanged. |
| Invalid/expired state | Start a fresh attempt; use the same running server, finish within ten minutes and do not reuse callback URLs. |
| 401 | Use the exact operator secret in the bearer header. |
| 403 | Use direct `127.0.0.1`, the configured port/Host and no public proxy or cross-origin page. |
| 404 | Confirm `PAM_DRIVE_ENABLED=true` and restart the server after editing `.env`. |
| Invalid credential / reconnect | Check the encryption key, client/account/owner settings; reconnect without changing Calendar's key/file. |
| Temporary unavailable | Retry the operation; do not repeatedly authorize or delete existing credentials. |
| Seven-day expiry in External Testing | Reconnect; do not treat Testing mode as a production token-lifetime solution. |

Offline verification covers 51 new Stage 4 cases plus the existing regression
suite: configuration, exact scopes, PKCE parameters, state TTL/capacity/replay,
capability isolation, account/client/owner binding, credential encryption,
atomic-write rollback, missing refresh token, refresh errors/timeouts,
operator/loopback/origin guards, consent/withdrawal, safe errors, disabled startup
and shared Calendar/Drive routes. Tests use fake Google services.

Validation: all 259 tests pass; Ruff lint/format, strict mypy and Git whitespace
checks pass. Documentation links are checked locally.

Live Google consent, refresh, Google-side revocation behavior and Calendar
before/after acceptance remain manual and must be recorded after setup. Passing
offline tests does not establish a live connection or production readiness.
