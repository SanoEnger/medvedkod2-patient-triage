param([string]$EnvFile = "$PSScriptRoot\..\..\.local\runtime\backend.env")
Set-Location $PSScriptRoot
$env:DEMO_MODE = 'true'
python -m app.run_api --env-file $EnvFile
