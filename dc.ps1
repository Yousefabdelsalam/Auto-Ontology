# Wrapper: run docker compose against the cloned repo plus our localhost-only override.
# Usage:  .\dc.ps1 up -d --wait postgres
#         .\dc.ps1 ps
$root = $PSScriptRoot
docker compose --project-directory "$root\auto-ontology" `
    -f "$root\auto-ontology\docker-compose.yml" `
    -f "$root\compose.override.yml" @args
