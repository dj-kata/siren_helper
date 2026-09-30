# Called on Windows by Dev Containers initializeCommand.
[CmdletBinding()]
param(
    [ValidateSet('start', 'stop')]
    [string]$Action = 'start'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $projectRoot '.windows-bridge'
New-Item -Path $bridge -ItemType Directory -Force | Out-Null
$heartbeat = Join-Path $bridge 'heartbeat'
$stopFile = Join-Path $bridge 'stop-host'

function Test-HostReady {
    $item = Get-Item -LiteralPath $heartbeat -ErrorAction SilentlyContinue
    return ($null -ne $item -and ([DateTime]::UtcNow - $item.LastWriteTimeUtc).TotalSeconds -lt 15)
}

# Serialize concurrent initializeCommand calls before opening the same log files.
$launcherLock = $null
$deadline = [DateTime]::UtcNow.AddSeconds(30)
while ($null -eq $launcherLock) {
    try {
        $launcherLock = [IO.File]::Open((Join-Path $bridge 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    }
    catch [IO.IOException] {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Another Windows host launcher is still running.' }
        Start-Sleep -Milliseconds 200
    }
}
try {
    if ($Action -eq 'stop') {
        if (-not (Test-HostReady)) {
            Write-Host 'Windows host is not responding; no stop was sent.'
            exit 0
        }
        [IO.File]::WriteAllText($stopFile, '')
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while (Test-Path -LiteralPath $heartbeat) {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw 'Host did not stop. If using the old foreground host, close its PowerShell window.'
            }
            Start-Sleep -Milliseconds 200
        }
        Write-Host 'Windows host stopped.'
        exit 0
    }
    & (Join-Path $PSScriptRoot 'export-git-identity.ps1')
    if (Test-HostReady) {
        Write-Host 'Windows host is already ready.'
        exit 0
    }
    Remove-Item -LiteralPath $stopFile -ErrorAction SilentlyContinue
    $hostScript = Join-Path $PSScriptRoot 'windows-host.ps1'
    $child = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$hostScript`"") `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $bridge 'host.stdout.log') `
        -RedirectStandardError (Join-Path $bridge 'host.stderr.log')
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while (-not (Test-HostReady)) {
            if ($child.HasExited -or [DateTime]::UtcNow -ge $deadline) {
                throw "Windows host failed to become ready. See $bridge\host.stderr.log"
            }
            Start-Sleep -Milliseconds 200
        }
        Write-Host "Windows host ready in background (PID $($child.Id))."
    }
    finally { $child.Dispose() }
}
finally { $launcherLock.Dispose() }
