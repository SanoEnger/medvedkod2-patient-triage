# Launch the MAX-connected backend locally. Read secrets from existing environment variables.
Set-Location $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:CORE_SERVICE_TOKEN)) {
    throw 'Set CORE_SERVICE_TOKEN in your PowerShell session or hosting secret settings first.'
}
if ([string]::IsNullOrWhiteSpace($env:SESSION_SIGNING_KEY)) {
    throw 'Set a random SESSION_SIGNING_KEY (at least 32 characters) first.'
}
$env:CORE_URL = 'https://tm-test-yakut.hostco.ru'
$env:DEMO_MODE = 'false'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
