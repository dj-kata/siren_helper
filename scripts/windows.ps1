# Run from Windows PowerShell: .\scripts\windows.ps1 run
[CmdletBinding()]
param(
    [ValidateSet('sync', 'run', 'build', 'check')]
    [string]$Action = 'run'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousVirtualEnv = $env:VIRTUAL_ENV
Push-Location $projectRoot
try {
    # Read only this setting as literal text; never execute .env as a script.
    $uvPath = $env:WINDOWS_UV_PATH
    if (-not $uvPath -and (Test-Path -LiteralPath '.env')) {
        foreach ($line in Get-Content -LiteralPath '.env') {
            if ($line -match '^\s*WINDOWS_UV_PATH\s*=\s*(.*?)\s*$') {
                $uvPath = $Matches[1]
                if ($uvPath.Length -ge 2 -and (
                    ($uvPath.StartsWith('"') -and $uvPath.EndsWith('"')) -or
                    ($uvPath.StartsWith("'") -and $uvPath.EndsWith("'"))
                )) {
                    $uvPath = $uvPath.Substring(1, $uvPath.Length - 2)
                }
            }
        }
    }
    if (-not $uvPath) {
        $uvPath = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    }
    if (-not (Test-Path -LiteralPath $uvPath -PathType Leaf)) {
        throw "Windows uv not found: $uvPath. Set WINDOWS_UV_PATH in .env or the environment."
    }

    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-win'
    $env:VIRTUAL_ENV = $null
    switch ($Action) {
        'check' { & $uvPath --version }
        'sync' { & $uvPath sync }
        'run' { & $uvPath run python siren6_helper.pyw }
        'build' {
            & $uvPath run python setup.py build
            if ($LASTEXITCODE -eq 0) {
                Get-ChildItem -Path 'siren6_helper/lib/PySide6/Qt6WebEngine*.dll' -ErrorAction SilentlyContinue |
                    Remove-Item -Force
                New-Item -Path 'siren6_helper/.built' -ItemType File -Force | Out-Null
            }
        }
    }
    $result = $LASTEXITCODE
}
finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    $env:VIRTUAL_ENV = $previousVirtualEnv
    Pop-Location
}
exit $result
