# Seeds the Wide World Importers sample database into the local Postgres container.
# Run AFTER:  .\dc.ps1 up -d --wait postgres
# Needs auto-ontology\.env (password) and the cloned auto-ontology-eval folder. WARNING: --drop recreates ONLY the
# 'wideworldimporters' database (not the app's own database).
#
# Why not the README command? On Windows seed_wwi.py opens the CSV files with the cp1252 encoding, fails on 4 files
# (People, People_Archive, Customers, Invoices), logs the error and carries on, and the foreign keys then fail.
# `python -X utf8` fixes that without touching the cloned source. (Do not use PYTHONUTF8=1 with `-I`: -I ignores it.)
# The light command below also avoids `uv sync` of the whole eval repo (ray, mlflow, ...): only psycopg is needed.
$root = $PSScriptRoot
$kv = @{}
Get-Content "$root\auto-ontology\.env" | Where-Object { $_ -match '^\s*[A-Za-z_]\w*\s*=' } | ForEach-Object {
    $i = $_.IndexOf('='); $kv[$_.Substring(0, $i).Trim()] = $_.Substring($i + 1).Trim().Trim('"').Trim("'")
}
$env:POSTGRES_HOST = '127.0.0.1'   # not 'localhost': on Windows that tries IPv6 ::1 first and hangs
$env:POSTGRES_PORT = $kv['POSTGRES_PORT']; $env:POSTGRES_USER = $kv['POSTGRES_USER']
$env:POSTGRES_PASSWORD = $kv['POSTGRES_PASSWORD']; $env:POSTGRES_DATABASE = $kv['POSTGRES_DATABASE']
try {
    uv run --no-project --python 3.12 --with "psycopg[binary]" --with python-dotenv python -X utf8 -I "$root\auto-ontology-eval\scripts\seed\seed_wwi.py" --database-name wideworldimporters --drop
    $code = $LASTEXITCODE
} finally {
    Remove-Item Env:POSTGRES_PASSWORD -ErrorAction SilentlyContinue
}
# The script swallows per-file errors, so verify the result instead of trusting the exit code.
$sql = "select (select count(*) from application.people)||' '||(select count(*) from sales.customers)||' '||(select count(*) from sales.invoices)||' '||(select count(*) from sales.invoicelines)||' '||(select count(*) from pg_constraint where contype='f')"
$got = (docker exec postgres psql -U postgres -d wideworldimporters -At -c $sql) -join ''
Write-Host "people customers invoices invoicelines foreign-keys = $got   (expected: 1111 663 70510 228265 98)"
if ($code -ne 0 -or $got.Trim() -ne '1111 663 70510 228265 98') { Write-Host "PROBLEM: the seed is incomplete."; exit 1 }
Write-Host "OK: seed complete and verified."
