# progress.md

## Step 1 - read the repo (DONE, approved)
Verified from files: README, .env.example, docker-compose.yml, Dockerfile, docs/mcp.md,
docs/conversation-api.md, docs/authentication.md, OpenAPI spec, troubleshooting doc, seed_wwi.py (read directly).

## Step 2 - start the stack (IN PROGRESS)
Done and verified:
- Re-cloned auto-ontology (f3c310c) and auto-ontology-eval (e727e4d) with core.autocrlf=false; 0 CR chars in migrate.sh, .env.example, seed_wwi.py.
- compose.override.yml (outside the repo) + dc.ps1 wrapper. `config` output shows 3000/3001/3002/5432 bound to 127.0.0.1; pgAdmin disabled via profile.
- auto-ontology/.env created from .env.example (still contains DEFAULT values - user must fill in).

- .env checked (no secrets printed): defaults replaced, CONNECTION_STRINGS correct, embed/rerank lines restored, KumoRFM unset.
- Postgres container healthy, bound to 127.0.0.1:5432 (image 637 MB).

RESOLVED: seed_wwi.py on Windows opens CSVs with cp1252 -> UnicodeDecodeError on 4 files (People, People_Archive,
Customers, Invoices); the script swallows it and 05_fkeys.sql then failed. Failed twice (2nd try used PYTHONUTF8=1,
ignored under `python -I`). Third run with `python -X utf8 -I` succeeded, no source edited. Command in README.md (to write).
Verified directly in Postgres: 48 base tables, 98 foreign keys, 3 views (schema website), People 1111, Customers 663,
Invoices 70510, InvoiceLines 228265, StockItems 227, DB 375 MB. Only 2 tables empty: sales.buyinggroups_archive,
warehouse.packagetypes_archive (genuinely empty archives; they were 0 rows in the log too).

- Images built (backend 1.37 GB, frontend 954 MB). `.\dc.ps1 up -d --wait`: frontend, backend, ingestion all healthy; both migrate jobs exited 0.
- VERIFIED ports: listening sockets for 3000/3001/3002/5432 are 127.0.0.1 only; TCP connects to this PC's 3 LAN IPs on those ports were refused. pgAdmin not running.
- VERIFIED: GET localhost:3000 -> 307 (login redirect); /.well-known/oauth-authorization-server -> 200; backend /api/health/live 200; ingestion /health/live 200.
- Startup ingest (actual): 51 tables, 589 columns, 640 embedding rows, 20 embedding HTTP calls, 0 chat calls, 15.8 s. (Estimate was 10-40 calls: OK.)

- Semantic compilation ran (user enabled it 13:13:55 UTC, finished 13:55:08, 2474 s). VERIFIED in Postgres: 51 terms
  (incl. Customer, Invoice, Invoice Line, Stock Item, State Province, People, City), 489 column attributes (410 with
  description), 100 semantic FK edges, 29 unmatched FK columns attached, 0 term families, **0 SQL attributes**, 0 bridge tables.
  catalog_column: 484 of 589 have a description.
- DEGRADED RUN (record in RESULTS.md): ~12 structured-output LLM calls failed with HTTP 400 from integrate.api.nvidia.com:
  "unknown field `guided_json`" for model nvidia/nemotron-3.5-lightning-30b-a3b (langchain_nvidia_ai_endpoints warns the model
  is "not known to support structured output"). Failed: RawTableTermsResult x5 (2 tables errored: buyinggroups_archive,
  specialdeals), ColumnDescriptionResult x4 batches, FkAndPkResult x1, FkHitSelection x1, SemanticFkJoinDefaultSelection x1
  (fell back to default). Compile still logged "finished successfully". Some terms got fallback names like
  "Customer (wideworldimporters.website.customers)". Repo source untouched.
- LLM call count: NOT measurable from container logs (NVIDIA client does not log chat requests; 0 chat lines, 193 embedding lines).
  Use build.nvidia.com usage page if available. Do not claim an exact number.

## Step 3 - ground truth (DONE, verified)
- uv project (Python 3.12, .venv; deps psycopg[binary], requests, pyyaml). tests/common.py, tests/make_ground_truth.py -> tests/questions.json.
- 6 answerable (A1-A6) + 1 extra certify question (C1 gross margin %) + 3 unanswerable (U1-U3) + 2 ambiguous (B1-B2).
- Expected values come only from direct SQL. A1, A2, A6 re-checked with differently written SQL (psql): identical. A3, A5, C1 match my earlier exploratory queries.
- Ambiguity check built in: B1 readings (revenue/profit/invoice count) give 2 different customers, B2 gives 3 different products, so both are truly ambiguous.
- Output is deterministic (2 runs identical apart from timestamp). No LLM, no cost.
- WINDOWS FINDING: "localhost" resolves to ::1 first; Docker publishes only IPv4 127.0.0.1, so ::1 connections hang (8 s timeout, unbounded
  without one). First 2 reruns of my script hung; fixed in MY helper (127.0.0.1 + connect_timeout). Use 127.0.0.1 for every test, not localhost.
- Caveat: "revenue" is defined as SUM(extendedprice) (includes tax in WWI) as in the repo README; the agent may legitimately choose
  another definition. Any mismatch will be reported with the SQL it used, not hidden.

## Step 4 - tests (scripts WRITTEN; only test_security RUN so far)
- Written in tests/: common.py, test_generate.py, test_answers.py, test_refusal.py, test_certify.py, test_mcp.py, test_export.py, test_security.py.
- Dry run without a token: every token-needing check printed SKIPPED (none PASS, none crash). test_mcp SKIPPED (MCP server not running).
- test_security RUN, all PASS where it could run: ports 3000/3001/3002/5432 listen on 127.0.0.1 only (netstat + docker inspect),
  refused on 3 other local IPs, no default secrets in .env or containers, KumoRFM unset, pgAdmin off, .env git-ignored.
  SKIPPED: port 3003 (MCP server not running).
- MCP: package installed into MY env via `uv add --group mcp ./auto-ontology/mcp` (clone stays clean). fastmcp 3.4.11; OAuth token kept in memory only.
  MCP server default bind is 0.0.0.0 -> must start with AUTO_ONTOLOGY_MCP_HOST=127.0.0.1. Needs one browser sign-in by the user.
- Needs from user: API token (UI: user menu -> API Tokens), put in auto-ontology\.env as AUTO_ONTOLOGY_API_TOKEN (scripts read it from there).
- Planned run order: generate + export (0 LLM) -> answers smoke test A1 -> rest of answers -> refusal -> certify -> mcp.
- NOT yet verified: whether the answering agent also hits the 400 `guided_json` structured-output error seen during compilation.

## README (written 2026-11-23, locally only, NOT yet committed or pushed)
- README.md rewritten (was a 1-line GitHub stub): status table, repo layout, safety rules, setup 1-7, test table with LLM-cost
  estimates, ground-truth questions, findings, troubleshooting, cleanup. Status table is honest: only security, ground truth,
  stack and seed are marked verified; generate/answers/refusal/certify/mcp/export are "written, not run yet".
- seed.ps1 added (the seed command I ran by hand, plus a count check). Parse-checked and its expected counts match the live DB;
  NOT re-run (it drops/recreates the sample DB for no benefit).
- Checks: secret scan of all publishable files = clean; uv lock --check OK; README path references OK
  (expected-missing: RESULTS.md, results/ask_log.jsonl, NVIDIA's seed_wwi.py).
- add-token.ps1 is still UNCONFIRMED (the token never appeared in .env during this project); README says so.
- User pushed the first version to GitHub (main, 2 commits); git history shows "Initial commit" + "Initial commit: Auto Ontology test harness".

Not done yet:
- Run Step 4 tests with a token (blocked on API token in .env), then Step 5 RESULTS.md
- (done) User signed in and turned on Semantic Compilation
- UI check in a browser (only HTTP-level check done so far)
- Build and start stack (large download: ask first), health, UI, port binding check
- User turns on Semantic Compilation

## Not verified
- Image sizes (estimates only); whether check_answerable calls an LLM
- Steps 3-5 not started
