# Copies a new random hex secret to the clipboard. It is never printed to the screen.
# Usage:  .\make-secret.ps1          (24 random bytes = 48 hex chars; fine for passwords and AUTH_SECRET)
#         .\make-secret.ps1 32       (32 random bytes = 64 hex chars)
param([int]$Bytes = 24)
$b = New-Object byte[] $Bytes
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($b)
$hex = -join ($b | ForEach-Object { $_.ToString('x2') })
Set-Clipboard -Value $hex
"Copied a new $($hex.Length)-character hex secret to the clipboard. Paste it into .env now."
