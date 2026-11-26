param([string]$EnvFile = "$PSScriptRoot\..\..\.local\runtime\backend.env")
Set-Location $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:CORE_SERVICE_TOKEN)) {
    throw 'Set CORE_SERVICE_TOKEN in the current environment first.'
}
$env:DEMO_MODE = 'false'
python -m app.run_api --env-file $EnvFile
