# Run this in YOUR terminal. It asks for the API token with hidden input and appends it to auto-ontology\.env.
# The token is never printed, never put on a command line, and written only to .env.
$envFile = Join-Path $PSScriptRoot 'auto-ontology\.env'
if (-not (Test-Path $envFile)) { Write-Host "Not found: $envFile"; return }
if (Select-String -Path $envFile -Pattern '^AUTO_ONTOLOGY_API_TOKEN=' -Quiet) {
    Write-Host "AUTO_ONTOLOGY_API_TOKEN already exists in .env. Edit that line by hand if you need to replace it."; return
}
$secure = Read-Host -AsSecureString -Prompt 'Paste the API token (input is hidden), then press Enter'
$plain = [System.Net.NetworkCredential]::new('', $secure).Password.Trim()
if ($plain.Length -lt 10) { Write-Host "That looks too short to be a token. Nothing was written."; return }
$text = [System.IO.File]::ReadAllText($envFile)
if (-not $text.EndsWith("`n")) { $text += "`n" }   # keep the file's last line intact
[System.IO.File]::WriteAllText($envFile, $text + "AUTO_ONTOLOGY_API_TOKEN=$plain`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Saved to .env ($($plain.Length) characters). Nothing else was changed."
