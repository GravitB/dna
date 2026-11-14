# Supabase archive persistence

Lazarus stores digital DNA (FASTA/CSV), reports, and verified restored files in a **private** Storage bucket. Postgres stores archive records, activity events, artifact checksums, simulated location availability, and encrypted recovery keys. The browser continues to use the Python API; Supabase credentials never go into frontend environment variables.

## Configure and initialize

Use the existing project `feiddjfuuqfvvsiionds`. Add these values to the repository's ignored `.env` file:

```dotenv
SUPABASE_URL=https://feiddjfuuqfvvsiionds.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
SUPABASE_DB_URL=postgresql://...  # database owner connection from the Supabase Connect dialog
```

If tables are already installed through the authenticated Supabase MCP connection or SQL Editor, skip the database setup command and run `lazarus-cloud check`; `SUPABASE_DB_URL` is not needed by the running application.

Use the session pooler connection if the direct database host cannot be reached on your network. URL-encode special characters in the database password. A backend API secret permits Storage/Data API access but **cannot run schema migrations**; setup requires the database connection string (or applying the SQL migration in the dashboard's SQL Editor).

From `lazarus/`:

```bash
uv sync --group cloud-setup
uv run lazarus-cloud keygen
uv run --group cloud-setup lazarus-cloud setup
uv run lazarus-cloud check
```

`keygen` appends a new 32-byte wrapping key to `.env` only if no wrapping key is already set. It never prints the value. Back up `LAZARUS_KEY_ENCRYPTION_KEY` in a separate secure password manager **before relying on portable recovery**. Losing it prevents decryption; generating a replacement will not restore old archives.

`setup` installs versioned SQL migrations transactionally, records their checksums, reloads the Data API schema, and creates/verifies the private bucket. It is repeatable. Alternatively, run `supabase/migrations/202611140001_archive_storage.sql` in the SQL Editor and then run `uv run lazarus-cloud bucket` and `uv run lazarus-cloud check`.

Only after setup and verification succeed, add:

```dotenv
LAZARUS_STORAGE_BACKEND=supabase
```

Restart `scripts/run.sh`. Archive details show saving/saved/failed cloud states. Keep `LAZARUS_STORAGE_BACKEND=local` for the original disk-only mode. Cloud mode fails explicitly if configuration or connectivity is missing; it never falls back to disk.

## Import existing archives

From `lazarus/`, explicitly import one completed local archive:

```bash
uv run lazarus-cloud import jobs/ARCHIVE_ID
```

The command preflights DNA files, key files, reports, and verified restored-file hashes. It uploads and downloads every artifact to verify checksums, wraps every archive key, and imports events with deterministic IDs. Original files are retained. Repeating an identical import is safe; a conflicting cloud archive is rejected. Incomplete archives are reported and are not marked saved.

For an archive containing a simulated lost location, import only surviving location files and preserve its unavailable state. Do not delete local directories until import and cloud recovery have been verified.

## What survives another computer

On another computer, check out the code, install dependencies, and configure the same Supabase URL/secret and **the original wrapping master key**. An empty local jobs directory is sufficient to list completed archives, read DNA from available locations, unlock archive keys, run recovery, and download current reports and restored files.

Uploads and intermediate encoding pools stay local during analysis. Active agent runs and approvals do not resume after a restart; interrupted jobs remain visible. Run a single active backend instance: the application is still a single-business workspace without end-user authentication. Private database tables and buckets deny direct anonymous access, but this change does not turn the application API into a public, multi-tenant service.

## Integrity and failure behavior

- DNA orders are committed only after every artifact upload and wrapped key is verified. Primary-file deletion verifies the cloud archive again first.
- Postgres updates use revision checks; event appends allocate sequence numbers transactionally and support safe retries after a lost response.
- Objects use content-addressed paths. An earlier report is retained in Storage, but downloads are authorized against the current archive outcome, so a failed test cannot expose a stale successful report or restored-file link.
- Simulating location loss changes availability and removes cached local files. It **does not erase the cloud backup**. Recovery deliberately ignores unavailable locations.
- Master keys are separate from Supabase. Archive keys are encrypted with AES-256-GCM and bound to their archive and key IDs. Uploads, intermediate pools, and unencrypted keys are never published as cloud artifacts.
- All simulated vaults share one Supabase project. This models multiple locations; it does not provide independent physical disaster-recovery sites.

## Verification

```bash
uv run pytest -q
cd ../web && npm test && npm run build
```

The storage suite exercises the real HTTP adapter with a protocol double, including revision conflicts, lost responses, upload failures, corruption, encrypted key custody, imports, and recovery after deleting the entire local job directory. A live Supabase database test additionally requires the installed migration and valid project credentials.

## Opt-in live backend verification

With the backend running in Supabase mode, run this from the repository root:

```bash
lazarus/.venv/bin/python scripts/verify_supabase.py
```

This creates a fictional Northstar Bio archive, approves its simulated order and working-copy deletion, checks every file, simulates losing one location, and verifies recovery again from an empty temporary local jobs directory. It preserves the resulting cloud archive and report for inspection. It uses a $100 modeled budget and makes no physical purchase.

The normal pytest suite explicitly defaults to local storage; cloud unit tests install their protocol double. It never uses the configured live project. Live verification is a separate, opt-in command.
