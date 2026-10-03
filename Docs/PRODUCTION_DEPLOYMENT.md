# PAM Production Deployment

This guide records the current production deployment for PAM. It is an
operations guide: it does not change PAM's runtime architecture or behavior.

Never place credentials, API keys, Telegram IDs, OAuth client values, encrypted
credential contents, server IP addresses, or Supermemory owner identifiers in
this file, a commit, a log, or a support request.

## Production architecture

The production host is an Azure Linux VM running Ubuntu 24.04 LTS on x86_64.
It uses Python 3.12 and `uv`; PAM is installed at `~/PAM` with its virtual
environment at `~/PAM/.venv`.

```text
Telegram
    |
    v
pam-telegram (PM2)
    |
    v
ConversationService
    |-- BharatCode
    |-- Supermemory
    `-- MCP get_weekly_availability
            |
            v
      Google Calendar
```

The Telegram bot uses polling. PAM does not currently need a publicly exposed
HTTP server for its Telegram workload, so FastAPI does not need to run
continuously and Nginx, a domain, and HTTPS are not required for this
deployment.

Calendar access remains read-only through the MCP boundary. Supermemory stores
durable long-term memory; Phase 8 in-memory history is only short-term
conversation history. CLI and Telegram use separate memory-owner identities;
Telegram ownership is derived from the authorized Telegram user. The `/new`
command clears short-term history only and does not delete durable Supermemory
memory.

PM2 is configured through systemd. The production process is named
`pam-telegram`. The VM has a persistent 1 GiB swap file at `/swapfile`, enabled
through `/etc/fstab`.

## Required production configuration

Keep production configuration in an ignored `.env` file. It must be readable
only by its owner:

```bash
chmod 600 .env
chmod 600 .pam-google-credentials.bin
```

Both `.env` and `.pam-google-credentials.bin` must remain Git-ignored. Never
commit secrets.

Configure these settings by **name only** in production:

| Area | Environment variables | Purpose |
| --- | --- | --- |
| Application | `PAM_ENVIRONMENT`, `PAM_APP_SECRET` | Selects production behavior and protects application state. |
| Google Calendar / OAuth | `PAM_CALENDAR_BACKEND`, `PAM_GOOGLE_CLIENT_ID`, `PAM_GOOGLE_CLIENT_SECRET`, `PAM_GOOGLE_REDIRECT_URI` | Enables the configured read-only Calendar backend and OAuth client. |
| Credential protection | `PAM_CREDENTIAL_ENCRYPTION_KEY`, `PAM_CREDENTIAL_STORAGE_PATH` | Encrypts and locates the stored Google credential file. |
| BharatCode | `PAM_MODEL_PROVIDER`, `PAM_BHARATCODE_API_KEY`, `PAM_BHARATCODE_MODEL`, `PAM_BHARATCODE_BASE_URL` | Selects and configures BharatCode generation. |
| Conversation | `PAM_CONVERSATION_MAX_HISTORY_MESSAGES`, `PAM_CONVERSATION_MAX_SESSIONS` | Bounds short-term conversation history and retained sessions. |
| Supermemory | `PAM_MEMORY_BACKEND`, `PAM_SUPERMEMORY_API_KEY`, `PAM_SUPERMEMORY_BASE_URL`, `PAM_MEMORY_MAX_RECALLED_ITEMS`, `PAM_MEMORY_MAX_CONTENT_CHARS`, `PAM_MEMORY_CLI_OWNER_ID` | Enables durable memory, configures bounded recall, and supplies the CLI-only owner identity. |
| Telegram | `PAM_TELEGRAM_ENABLED`, `PAM_TELEGRAM_BOT_TOKEN`, `PAM_TELEGRAM_ALLOWED_USER_IDS` | Enables the bot, authenticates it, and limits access to approved Telegram users. |

Use the names and defaults in [`.env.example`](../.env.example) as the current
configuration reference. Put real values only in the ignored production `.env`.

## Initial deployment

Run these steps on the VM. Verify each command before proceeding.

1. Clone the repository and enter `~/PAM`.
2. Install `uv` using its official installation instructions.
3. Create the environment from the lock file:

   ```bash
   uv sync --locked
   ```

4. For deployment verification, install development dependencies too:

   ```bash
   uv sync --locked --extra dev
   ```

5. Create and secure the production `.env`; do not copy values into shell history or source control.
6. When appropriate, securely transfer the encrypted Google credential file to
   the configured storage path and set it to mode `600`.
7. Run the full verification suite:

   ```bash
   source .venv/bin/activate
   ruff format --check .
   ruff check .
   mypy pam
   pytest
   ```

8. Manually verify PAM through the CLI.
9. Manually verify Telegram while no other machine is polling the same bot.
10. Start the Telegram worker with the virtual-environment Python:

    ```bash
    pm2 start /home/food-iuser/PAM/.venv/bin/python \
      --name pam-telegram \
      --cwd /home/food-iuser/PAM \
      -- -m pam.telegram.bot
    ```

11. Verify the process with `pm2 list` and inspect its logs.
12. Persist the PM2 process list:

    ```bash
    pm2 save
    ```

13. Verify the `pm2-food-iuser` systemd startup service.
14. Verify persistent swap is active.
15. Reboot the VM.
16. Confirm PM2 automatically restores `pam-telegram`.
17. Confirm Telegram works after the reboot without manually starting PAM.

## Normal update and release workflow

Do not restart the production process until the updated checkout has passed all
verification.

```bash
cd ~/PAM
git status
git pull --ff-only
uv sync --locked --extra dev
source .venv/bin/activate

ruff format --check .
ruff check .
mypy pam
pytest
```

Only after every check succeeds:

```bash
pm2 restart pam-telegram
pm2 list
pm2 logs pam-telegram --lines 50
```

Perform a real Telegram smoke test. If the PM2 process configuration changed,
run `pm2 save` after verifying the process.

## PM2 operations

```bash
pm2 list
pm2 logs pam-telegram
pm2 logs pam-telegram --lines 50
pm2 restart pam-telegram
pm2 stop pam-telegram
pm2 save
```

## Rollback

1. Identify the previous known-good commit with `git log --oneline` or release
   records.
2. Inspect `git status` first. Do not discard uncommitted production changes
   without understanding them.
3. Stop the worker if required: `pm2 stop pam-telegram`.
4. Move the checkout to the known-good commit using a deliberate, reviewed Git
   operation. Commands such as `git reset --hard` discard uncommitted changes;
   use them only when those changes are known to be unnecessary or recoverable.
5. Recreate the locked environment state:

   ```bash
   uv sync --locked --extra dev
   source .venv/bin/activate
   ruff format --check .
   ruff check .
   mypy pam
   pytest
   ```

6. Restart `pam-telegram`, inspect PM2 and its logs, then verify Telegram with
   a real message.

## Operations and troubleshooting

### Host and service health

```bash
free -h
swapon --show
uptime
pm2 list
pm2 logs pam-telegram --lines 50
systemctl status pm2-food-iuser
```

`free -h` confirms RAM and aggregate swap availability; `swapon --show` confirms
that `/swapfile` is active. `pm2 list` should show `pam-telegram` as `online`.

### BharatCode failures

For 401 or 403 responses, verify that the BharatCode API-key variable is present
in the process environment, valid, authorized for the configured model, and not
expired or revoked. Restart only after fixing the secure `.env` configuration;
never paste the key into logs or tickets.

### Supermemory and owner isolation

Confirm the Supermemory backend and API-key variables are configured. CLI and
Telegram must not share an owner identity. Telegram memory identity is derived
from the authorized Telegram user, so a configuration change must never replace
that derivation with a shared identifier. Recall failures should be investigated
from safe logs without revealing returned memory content.

### Google credentials

An encrypted credential file cannot be decrypted if its encryption key changes.
Verify the configured credential storage path, file permissions, and matching
encryption key. If a credential or key is rotated, re-authorize and securely
replace the encrypted credential file rather than attempting to edit it.

### Telegram polling conflicts

Only one running process may poll a Telegram bot token. Stop the local Windows
Telegram process before Azure production starts polling, and stop production
before intentionally testing polling locally. Two pollers cause update conflicts
and unreliable message handling.

### Secret rotation

At a high level: create the replacement secret with its provider, update the
secured production `.env`, rotate or recreate dependent encrypted credentials
when applicable, verify configuration without printing it, restart the PM2
worker, and perform an end-to-end smoke test. Revoke the old secret only after
the replacement is confirmed working.

## Production acceptance gate

Treat production as healthy only when all of the following are true:

- PM2 reports `pam-telegram` as online.
- Telegram responds.
- BharatCode generation succeeds.
- Supermemory recall succeeds.
- Google Calendar availability succeeds.
- Explicit `Remember` followed by `/new` and recall succeeds.
- Swap is active.
- A VM reboot restores `pam-telegram` automatically.
- Telegram works after reboot without manually starting PAM.
