# Run from this script's directory. Synthetic/offline demo mode only.
Set-Location $PSScriptRoot
if (-not $env:SESSION_SIGNING_KEY) {
    $env:SESSION_SIGNING_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
}
$env:DEMO_MODE = 'true'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
