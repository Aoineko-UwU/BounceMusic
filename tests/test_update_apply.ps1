$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('BounceMusic-test-' + [guid]::NewGuid().ToString('N'))
$install = Join-Path $testRoot 'installed'
$stage = Join-Path $testRoot 'staged'
New-Item -ItemType Directory -Path $install,(Join-Path $install '_internal'),(Join-Path $stage 'files\_internal') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $install 'BounceMusic.exe') -Value 'old program'
Set-Content -LiteralPath (Join-Path $install '_internal\old.txt') -Value 'old internal'
Set-Content -LiteralPath (Join-Path $install '设置.json') -Value 'user settings'
Set-Content -LiteralPath (Join-Path $stage 'files\BounceMusic.exe') -Value 'new program'
Set-Content -LiteralPath (Join-Path $stage 'files\_internal\new.txt') -Value 'new internal'
function Start-Process { param($FilePath,$WorkingDirectory,$WindowStyle) }
try {
    & (Join-Path $PSScriptRoot '..\src\updater.ps1') -Stage $stage -Install $install -AppPid 2147483647
    if ((Get-Content -Raw -LiteralPath (Join-Path $install 'BounceMusic.exe')).Trim() -ne 'new program') { throw 'New program missing' }
    if (-not (Test-Path -LiteralPath (Join-Path $install '_internal\new.txt'))) { throw 'New internal files missing' }
    if (Test-Path -LiteralPath (Join-Path $install '_internal\old.txt')) { throw 'Old internal files remain' }
    if ((Get-Content -Raw -LiteralPath (Join-Path $install '设置.json')).Trim() -ne 'user settings') { throw 'Settings changed' }
    New-Item -ItemType Directory -Path (Join-Path $stage 'files\_internal') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $stage 'files\BounceMusic.exe') -Value 'broken update'
    Set-Content -LiteralPath (Join-Path $stage 'files\_internal\newer.txt') -Value 'broken internal'
    Add-Type -TypeDefinition 'namespace System.Windows { public static class MessageBox { public static object Show(string a, string b) { return null; } } }'
    function Add-Type { param($AssemblyName) }
    function Move-Item {
        param($LiteralPath,$Destination,$ErrorAction,[switch]$Force)
        if ($LiteralPath -eq (Join-Path $stage 'files\_internal')) { throw 'Simulated disk failure' }
        Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force -ErrorAction Stop
    }
    & (Join-Path $PSScriptRoot '..\src\updater.ps1') -Stage $stage -Install $install -AppPid 2147483647
    if ((Get-Content -Raw -LiteralPath (Join-Path $install 'BounceMusic.exe')).Trim() -ne 'new program') { throw 'Program was not restored' }
    if (-not (Test-Path -LiteralPath (Join-Path $install '_internal\new.txt'))) { throw 'Internal files were not restored' }
    if ((Get-Content -Raw -LiteralPath (Join-Path $install '设置.json')).Trim() -ne 'user settings') { throw 'Settings changed during rollback' }
    Write-Output 'Update apply checks passed.'
} finally {
    $resolved = (Resolve-Path -LiteralPath $testRoot).Path
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected test directory' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
