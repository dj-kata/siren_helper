# Start in an interactive Windows desktop session, not inside the container.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$bridge = Join-Path (Split-Path -Parent $PSScriptRoot) '.windows-bridge'
New-Item -Path $bridge -ItemType Directory -Force | Out-Null
# One host per workspace; releasing this handle also works after a crash.
$lock = [IO.File]::Open((Join-Path $bridge 'host.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$heartbeat = Join-Path $bridge 'heartbeat'
$process = $null
$job = $null

function Update-Heartbeat {
    [IO.File]::WriteAllText($heartbeat, [DateTime]::UtcNow.ToString('o'))
}
function Complete-Job($Directory, $Code) {
    $temporary = Join-Path $Directory 'exit-code.tmp'
    [IO.File]::WriteAllText($temporary, [string]$Code)
    Move-Item -LiteralPath $temporary -Destination (Join-Path $Directory 'exit-code') -Force
}
function Stop-JobProcess {
    if ($null -ne $process -and -not $process.HasExited) {
        # Kill only the process tree started for this job, including uv/Python.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
        $process.WaitForExit()
    }
}

try {
    Remove-Item -LiteralPath $heartbeat -ErrorAction SilentlyContinue
    # Never replay requests left over from an earlier host session.
    Get-ChildItem -LiteralPath $bridge -Directory | Where-Object Name -Match '^[a-f0-9]{32}$' |
        ForEach-Object {
            if (-not (Test-Path (Join-Path $_.FullName 'exit-code'))) {
                [IO.File]::WriteAllText((Join-Path $_.FullName 'stderr.log'), "Host restarted; please retry.`n")
                Complete-Job $_.FullName 1
            }
        }
    Write-Host 'Windows host ready. In the container: make test / make build (Ctrl+C to stop host).'
    while ($true) {
        if (Test-Path -LiteralPath (Join-Path $bridge 'stop-host')) { break }
        Update-Heartbeat
        if ($null -ne $process) {
            if (Test-Path (Join-Path $job 'cancel')) { Stop-JobProcess }
            if ($process.HasExited) {
                $process.WaitForExit()
                Complete-Job $job $process.ExitCode
                $process.Dispose()
                $process = $null
                $job = $null
            }
        }
        if ($null -eq $process) {
            $request = Get-ChildItem -LiteralPath $bridge -Directory |
                Where-Object {
                    $_.Name -match '^[a-f0-9]{32}$' -and
                    (Test-Path (Join-Path $_.FullName 'request.json')) -and
                    -not (Test-Path (Join-Path $_.FullName 'exit-code'))
                } | Sort-Object CreationTimeUtc | Select-Object -First 1
            if ($null -ne $request) {
                $job = $request.FullName
                try {
                    if (Test-Path (Join-Path $job 'cancel')) {
                        Complete-Job $job 130
                        $job = $null
                        continue
                    }
                    $action = (Get-Content -LiteralPath (Join-Path $job 'request.json') -Raw | ConvertFrom-Json).action
                    if ($action -notin @('check', 'sync', 'run', 'build')) { throw 'Unsupported action' }
                    # The request cannot supply commands, executable paths or arguments.
                    $script = Join-Path $PSScriptRoot 'windows.ps1'
                    $process = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
                        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"", $action) `
                        -WorkingDirectory (Split-Path -Parent $PSScriptRoot) -NoNewWindow -PassThru `
                        -RedirectStandardOutput (Join-Path $job 'stdout.log') `
                        -RedirectStandardError (Join-Path $job 'stderr.log')
                    $null = $process.Handle # Retain the handle so ExitCode remains available.
                    Write-Host "Started $action (PID $($process.Id))"
                }
                catch {
                    [IO.File]::WriteAllText((Join-Path $job 'stderr.log'), "$_`n")
                    Complete-Job $job 1
                    $job = $null
                }
            }
        }
        Start-Sleep -Milliseconds 200
    }
}
finally {
    Stop-JobProcess
    if ($null -ne $job) { Complete-Job $job 130 }
    Remove-Item -LiteralPath $heartbeat -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $bridge 'stop-host') -ErrorAction SilentlyContinue
    $lock.Dispose()
}
