# Export only the effective commit identity from Windows Git, including includeIf.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$projectRoot = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $projectRoot '.windows-bridge'
New-Item -Path $bridge -ItemType Directory -Force | Out-Null
$destination = Join-Path $bridge 'git-identity.config'
$temporary = Join-Path $bridge ("git-identity-{0}.tmp" -f [Guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($temporary, '')
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($null -eq $git) {
        Write-Warning 'Windows Git was not found. Git identity fallback will be used.'
    }
    else {
        foreach ($key in @('user.name', 'user.email')) {
            $value = & $git.Source -C $projectRoot config --get $key
            $code = $LASTEXITCODE
            if ($code -eq 1) {
                Write-Warning "Windows Git has no $key."
                continue
            }
            if ($code -ne 0) { throw "Cannot read Windows Git $key (exit $code)." }
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                & $git.Source config --file $temporary $key $value
                if ($LASTEXITCODE -ne 0) { throw "Cannot export $key." }
            }
        }
    }
    Move-Item -LiteralPath $temporary -Destination $destination -Force
}
finally {
    Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue
}
