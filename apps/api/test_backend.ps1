Set-Location $PSScriptRoot
if (-not $env:SESSION_SIGNING_KEY) {
    $env:SESSION_SIGNING_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
}
python -m pytest -q tests
