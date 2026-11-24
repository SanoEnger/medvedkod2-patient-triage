param([Parameter(Mandatory=$true)][string]$Python, [Parameter(Mandatory=$true)][string]$VercelCli)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$runtime = Join-Path $repoRoot '.local/core-relay'
$supervisor = Join-Path $PSScriptRoot 'relay_autostart.py'
$pythonWindowless = Join-Path (Split-Path $Python) 'pythonw.exe'
foreach ($required in @($Python, $pythonWindowless, $VercelCli, (Join-Path $runtime 'private.env'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required file missing: $required" }
}
@{python=$Python; vercel_cli=$VercelCli} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'autostart.json') -Encoding utf8
# Existing working address is already configured in Vercel. Preserve it on install.
$published = Join-Path $runtime 'published-url.txt'
if (-not (Test-Path -LiteralPath $published)) {
    Copy-Item -LiteralPath (Join-Path $runtime 'url.txt') -Destination $published
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('"' + $supervisor + '"') -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'MedVedCoreRelay' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'MedVedCoreRelay'
Write-Output 'Installed and started MedVedCoreRelay for the current Windows user.'
