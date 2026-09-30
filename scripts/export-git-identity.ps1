# Read identity from the default WSL distro (the host development environment).
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
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
$wslArgs = @()
if ($env:GIT_IDENTITY_WSL_DISTRO) { $wslArgs += @('--distribution', $env:GIT_IDENTITY_WSL_DISTRO) }
try {
    if (-not (Test-Path -LiteralPath $wsl)) { throw 'wsl.exe was not found.' }
    $linuxRoot = & $wsl @wslArgs --exec wslpath -u $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the project path in WSL.' }
    $lines = @('[user]')
    foreach ($key in @('name', 'email')) {
        $value = & $wsl @wslArgs --exec git -C $linuxRoot config --get "user.$key"
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
            throw "WSL Git user.$key is unset or unreadable. Check the default WSL distro or GIT_IDENTITY_WSL_DISTRO."
        }
        # Git config quoted-value escaping; no shell evaluation or Windows Git required.
        $escaped = $value.Replace('\', '\\').Replace('"', '\"').Replace("`n", '\n').Replace("`t", '\t').Replace("`b", '\b')
        $lines += "`t$key = `"$escaped`""
    }
    [IO.File]::WriteAllText($temporary, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $destination -Force
    Write-Host 'Git identity exported from WSL.'
}
finally {
    Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue
}
