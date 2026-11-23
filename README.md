# Auto Ontology test project

A small, honest test harness for [NVIDIA Auto Ontology](https://github.com/NVIDIA/auto-ontology).

**The idea being tested:** a certified "business dictionary" (terms, SQL attributes, relationships) lets an agent
answer questions over a SQL database **correctly**, **show the SQL**, and **refuse** questions the data cannot answer.

This repo contains only the test scripts, the ground truth and the local configuration. It does **not** contain
NVIDIA's code or the sample data: you clone those next to it (step 1). Everything runs locally with Docker on
Windows/PowerShell, against the Wide World Importers sample database (fake data) only.

> **Never connect a real company database to this setup.** It is a throwaway test environment.

## Status

Last updated 2026-11-23. "Verified" means I ran it and checked the output. Nothing is marked done that was not run.

| Area | Script | Status |
| --- | --- | --- |
| Stack up, localhost-only ports, sample data seeded | `dc.ps1`, `seed.ps1` | **Verified**: 4 services healthy + 2 migrate jobs exited 0; 48 tables, 98 foreign keys, row counts checked in Postgres |
| Security (ports, passwords, KumoRFM) | `tests/test_security.py` | **Verified**: PASS on every check that could run (MCP port check SKIPPED: MCP server not started) |
| Ground truth from direct SQL | `tests/make_ground_truth.py` | **Verified**: 6 answerable, 3 unanswerable, 2 ambiguous (+1 certify question); key values cross-checked with independent SQL |
| Ontology generation | (Auto Ontology itself) | **Ran, degraded**: 51 terms, 100 join links, **0 SQL attributes**; about a dozen model calls failed (see [Findings](#findings-so-far)) |
| Generation check | `tests/test_generate.py` | Written, **not run yet** (needs an API token) |
| Answers vs ground truth | `tests/test_answers.py` | Written, **not run yet** |
| Refusal / clarification | `tests/test_refusal.py` | Written, **not run yet** |
| Certification before/after | `tests/test_certify.py` | Written, **not run yet** |
| MCP tools | `tests/test_mcp.py` | Written, **not run yet** (needs MCP server + one browser sign-in) |
| Ossie YAML export | `tests/test_export.py` | Written, **not run yet** |
| Accuracy summary and cost | `RESULTS.md` | **Not written yet** (needs the runs above) |

Without an API token every token-based check prints `SKIPPED`, never `PASS`.

## What is in this repo

```text
README.md                this file
progress.md              running log: what is done, verified, and not verified
pyproject.toml, uv.lock  Python 3.12 environment (uv): psycopg, requests, pyyaml; optional "mcp" group
compose.override.yml     binds every published port to 127.0.0.1 and keeps pgAdmin off (the NVIDIA repo is not edited)
dc.ps1                   wrapper: docker compose with the NVIDIA compose file + our override
seed.ps1                 seeds Wide World Importers into Postgres and verifies the result
make-secret.ps1          puts a new random hex secret on the clipboard (never printed)
add-token.ps1            adds your API token to .env using hidden input
tests/
  common.py              shared helpers: .env reader, REST client, answer checking
  make_ground_truth.py   queries the sample DB directly and writes questions.json
  questions.json         ground truth: expected values + the SQL that produced them
  test_*.py              one short script per area (see below)
  results/               created by the tests: raw answers, SQL, steps (no secrets)
```

Not in this repo (git-ignored; you clone them): `auto-ontology/` (NVIDIA's app) and `auto-ontology-eval/` (its sample data).

## Privacy and safety rules

- **Sample data only.** Wide World Importers, fake data. No real database is ever connected.
- **KumoRFM stays off.** The optional predictive feature uploads tables to an outside service. `KUMO_RFM_*` is never set.
- **Ports 3001 and 3002 stay private.** NVIDIA's README says the ingestion endpoints have no authentication. Compose publishes
  them on all interfaces by default, so `compose.override.yml` binds ports 3000, 3001, 3002 and 5432 to `127.0.0.1`.
  `tests/test_security.py` verifies this with netstat, `docker inspect` and connection attempts from this PC's other IP addresses.
- **No default passwords.** Replace every default in `.env` (step 2). The security test checks them.
- **Secrets live only in `auto-ontology/.env`.** It is git-ignored. Never put a key on a command line or in any other file.
  The scripts read secrets from `.env` and never print them.
- **The NVIDIA clones are never edited.** Problems are worked around from outside and reported instead.

## Requirements

- Windows 10/11, PowerShell, Docker Desktop (Compose v2), Git, [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 itself)
- An NVIDIA API key (`nvapi-...`) from [build.nvidia.com](https://build.nvidia.com)
- No GPU: the models run on NVIDIA's hosted API
- Disk and downloads (measured here): Postgres image 637 MB, backend image 1.37 GB, frontend image 954 MB, sample data 238 MB

## Setup

Run all commands from this repo's folder.

### 1. Clone the two NVIDIA repos next to this project (at the tested commits)
Use `core.autocrlf=false`. With the Windows default, the clone gets CRLF line endings and a shell script that runs inside a Linux
container breaks.

```powershell
git -c core.autocrlf=false clone https://github.com/NVIDIA/auto-ontology.git auto-ontology
```

```powershell
git -C auto-ontology config core.autocrlf false
```

```powershell
git -C auto-ontology checkout f3c310c7a279fcdfadf559d3fd7cd34e976d73e0
```

```powershell
git -c core.autocrlf=false clone https://github.com/NVIDIA/auto-ontology-eval.git auto-ontology-eval
```

```powershell
git -C auto-ontology-eval config core.autocrlf false
```

```powershell
git -C auto-ontology-eval checkout e727e4d6e1e198355099de4803590bb3681793a4
```

### 2. Create `.env` and fill it in yourself

```powershell
Copy-Item auto-ontology\.env.example auto-ontology\.env
```

Edit `auto-ontology\.env` in an editor and save it. Set:

| Variable | Value |
| --- | --- |
| `DEFAULT_MODELS_API_KEY` | your `nvapi-...` key |
| `AUTH_SECRET` | a new random value, at least 32 characters |
| `POSTGRES_PASSWORD` | a new password (letters and digits only, so it is safe inside a URL) |
| `CONNECTION_STRINGS` | `postgresql://postgres:<POSTGRES_PASSWORD>@postgres:5432/wideworldimporters` (host is `postgres`, not `localhost`) |
| `AUTO_ONTOLOGY_ADMIN_PASSWORD` | a new password (you sign in with it) |
| `PGADMIN_PASSWORD` | a new password (pgAdmin is off, but do not leave the default) |

Delete the four per-role `*_API_KEY` lines so they fall back to `DEFAULT_MODELS_API_KEY`, but **keep** every `*_ENDPOINT` and
`*_MODEL` line. In particular `EMBED_*` and `RERANK_*` must stay: if they are missing, embedding and reranking fall back to the chat model.

To generate a random value onto your clipboard without printing it, run `.\make-secret.ps1`.

### 3. Python environment

```powershell
uv sync
```

(`pyproject.toml` lists `auto-ontology/mcp` as a workspace member, so step 1 must come first. Add `--group mcp` for the MCP test.)

### 4. Start Postgres, then seed the sample database

```powershell
.\dc.ps1 up -d --wait postgres
```

```powershell
.\seed.ps1
```

`seed.ps1` ends with `OK: seed complete and verified.` If it prints `PROBLEM`, do not continue.

### 5. Build and start the rest of the stack

```powershell
.\dc.ps1 up -d --build
```

```powershell
.\dc.ps1 ps
```

Wait until the frontend, backend and ingestion service show `healthy` and both `*-migrate` containers show `Exited (0)`.
Always use `.\dc.ps1`, never plain `docker compose`: plain compose would also start pgAdmin and publish ports on all interfaces.

### 6. Sign in and turn on Semantic Compilation (you do this)

Open <http://localhost:3000> and sign in with `AUTO_ONTOLOGY_ADMIN_EMAIL` (default `admin@nvidia.com`) and your admin password.
Go to **Settings → Semantic Compilation** and switch it on. This builds the ontology and **calls the LLM many times**
(observed here: about 41 minutes for 48 tables). Wait for "Semantic compilation is ready".

### 7. API token for the REST tests (you do this)
In the UI: user menu → **API Tokens → New token** (give it an expiry such as 7 days). Then add it to `.env` with hidden input:

```powershell
.\add-token.ps1
```

Revoke the token in the UI when you are done.

> `add-token.ps1` has **not been confirmed to work** on the test machine yet: during this project the token never showed up in `.env`.
> If the script does not work, add the line `AUTO_ONTOLOGY_API_TOKEN=<token>` to `auto-ontology\.env` by hand and **save the file**.
> To check without printing the value: `Select-String -Path auto-ontology\.env -Pattern '^AUTO_ONTOLOGY_API_TOKEN=\S+' -Quiet` should print `True`.

## Running the tests

```powershell
uv run python tests\make_ground_truth.py
```

Rebuilds `tests/questions.json` from direct SQL. No LLM, no cost. Expected values are never edited by hand.

| Script | What it checks | Needs | LLM calls (estimate) |
| --- | --- | --- | --- |
| `tests\test_security.py` | Ports on 127.0.0.1 only, no default passwords, KumoRFM off | stack running | none |
| `tests\test_generate.py` | Key terms exist (Customer, Invoice Line ...), main joins, SQL attributes | token | none |
| `tests\test_export.py` | Ossie YAML export is well-formed, has the key content, no password in it | token (admin) | none |
| `tests\test_answers.py [A1 A4 ...]` | 6 answerable questions vs ground truth; SQL, steps and rows returned | token | 10-30 per question |
| `tests\test_refusal.py [U1 B1 ...]` | 3 unanswerable and 2 ambiguous: refuses or asks, no invented number | token | 5-30 per question |
| `tests\test_certify.py [--cleanup]` | Asks the margin question, certifies a "Gross Margin Percentage" SQL attribute, asks again | token | 10-30 per ask (2 asks) |
| `tests\test_mcp.py` | `check_answerable` and `ask_question` through MCP | MCP server + browser sign-in | 25-65 |

Run each with `uv run python tests\<name>.py` (the MCP test with `uv run --group mcp python tests\test_mcp.py`).
**Start with one question** (`tests\test_answers.py A1`) to see the cost and any errors before running the rest.

Every check prints one line: `PASS`, `FAIL` or `SKIPPED` with a reason. A check that could not run is `SKIPPED`, never `PASS`.
Answers are checked by plain code against the direct-SQL values, never by an LLM. If a model gives a different but equivalent
answer (rounding, ordering), the reason is printed, not hidden.

**LLM call counts are estimates.** NVIDIA's client does not log chat requests, so the real number cannot be read from the logs.
`tests/results/ask_log.jsonl` records every question asked and its number of agent steps instead.

### MCP test: extra steps
The MCP server is not part of the compose stack, and **its default bind address is 0.0.0.0**. Start it in its own window on localhost only:

```powershell
$env:AUTO_ONTOLOGY_MCP_HOST = '127.0.0.1'; $env:AUTO_ONTOLOGY_API_URL = 'http://localhost:3000'; uv run --group mcp auto-ontology-mcp
```

Then run the test in another window. Your browser opens once for the Auto Ontology sign-in; the token stays in memory only.

## The questions (ground truth from direct SQL)

| ID | Question | Expected |
| --- | --- | --- |
| A1 | Revenue for the 20 mm Double sided bubble wrap 50m in Texas in March 2015 | 36,018.00 |
| A2 | Invoice lines on invoices dated March 2016 | 6,074 |
| A3 | Total revenue from Gift Store customers in 2015 | 4,484,174.95 |
| A4 | Top 3 stock items by total revenue | Air cushion machine (Blue); 32 mm Anti static bubble wrap (Blue) 50m; 10 mm Anti static bubble wrap (Blue) 50m |
| A5 | Average revenue per invoice line in 2015 | 863.5876 |
| A6 | Distinct customers invoiced in 2015 | 657 |
| C1 | Gross margin % in 2015 (certify test) | 43.4168 |
| U1-U3 | Advertising spend; employee satisfaction; next year's weather | refuse or clarify, no invented number |
| B1-B2 | "Who is our best customer?"; "Which product is the most popular?" | ask which metric |

"Revenue" is defined as `SUM(invoicelines.extendedprice)` (as in NVIDIA's README) and the state as the customer's delivery city.
In this data `extendedprice` includes tax, so a different but defensible definition is possible; any mismatch is reported with the SQL used.

## Findings so far

Observed in this setup. Each is a fact about one run, not a general verdict on the tool.

**Windows problems and fixes**
- **CRLF line endings.** `core.autocrlf=true` makes a clone break a shell script run inside a container. Clone with `core.autocrlf=false` (step 1).
- **Seed script and encoding.** `seed_wwi.py` opens CSV files without an encoding. On Windows it fails on 4 files, logs the error, carries on, and the foreign keys then fail. Fix: `python -X utf8` (in `seed.ps1`). `PYTHONUTF8=1` does not work together with `python -I`.
- **`localhost` hangs.** Windows tries IPv6 `::1` first, Docker publishes only IPv4, and connections wait for a timeout. Use `127.0.0.1` in scripts.
- **Compose publishes ports on all interfaces** and the MCP server binds `0.0.0.0` by default. Both are bound to localhost here.

**Ontology generation with the default model (`nvidia/nemotron-3.5-lightning-30b-a3b`)**
- Result: 51 terms (Customer, Invoice, Invoice Line, Stock Item, State Province ... exist), 100 semantic join links, 410 of 489 column attributes described, **0 SQL attributes**, 0 term families.
- About a dozen structured-output model calls failed with HTTP 400 (`unknown field guided_json`) from the NVIDIA endpoint. Affected steps: table naming (5), column descriptions (4 batches), foreign-key detection, join default selection. Two tables hit an unexpected error. Some terms got fallback names like `Customer (wideworldimporters.website.customers)`.
- The compile log still ends with "finished successfully", so check the log and the counts, not the status.
- Whether the answering agent hits the same error is **not yet known**: that is what `test_answers.py` will show.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Every token-based check prints `SKIPPED` | `AUTO_ONTOLOGY_API_TOKEN` is not in `auto-ontology\.env` (step 7). Save the file after editing. |
| A script hangs on a database connection | You used `localhost`. Use `127.0.0.1`. |
| UI loads without its left menu | Stale session cookie. Clear site data for `localhost:3000` and sign in again. |
| Seed prints `PROBLEM` | Postgres not up, or a seed error; read the log above it. Re-run `.\seed.ps1` (it recreates only the sample database). |
| Answers are empty with no SQL | Check that Semantic Compilation finished and the `EMBED_*` lines are in `.env`. |
| MCP: "Protected resource ... does not match" | The client must use `http://localhost:3003/mcp` exactly as in `AUTO_ONTOLOGY_MCP_PUBLIC_URL`. |

## Stop, reset, clean up

```powershell
.\dc.ps1 stop
```

Stops everything and keeps the data. To delete the containers **and all data** (the ontology, the sample database, users):

```powershell
.\dc.ps1 down -v
```

Also revoke your API token in the UI, and rotate the NVIDIA key if you shared the machine.

## Credits and licence

NVIDIA Auto Ontology and auto-ontology-eval are NVIDIA's projects under their own licences (Apache-2.0 for Auto Ontology). The Wide World Importers
data is Microsoft's sample database (MIT), ported to PostgreSQL in auto-ontology-eval. This repo only adds test scripts and configuration.
