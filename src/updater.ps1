param([string]$Stage, [string]$Install, [int]$AppPid)
$ErrorActionPreference = 'Stop'
$backup = Join-Path $Install ('.bounce-update-backup-' + $PID)
$files = @('BounceMusic.exe', '_internal', 'ProcTap-LICENSE.txt')
$old = @()
$installed = @()
try {
    Wait-Process -Id $AppPid -Timeout 30 -ErrorAction SilentlyContinue
    if (Get-Process -Id $AppPid -ErrorAction SilentlyContinue) { throw 'App did not exit.' }
    New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
    foreach ($name in $files) {
        $target = Join-Path $Install $name
        if (Test-Path -LiteralPath $target) {
            Move-Item -LiteralPath $target -Destination (Join-Path $backup $name) -ErrorAction Stop
            $old += $name
        }
    }
    foreach ($name in $files) {
        $source = Join-Path (Join-Path $Stage 'files') $name
        if (Test-Path -LiteralPath $source) {
            $installed += $name
            Move-Item -LiteralPath $source -Destination (Join-Path $Install $name) -ErrorAction Stop
        }
    }
    Start-Process -FilePath (Join-Path $Install 'BounceMusic.exe') -WorkingDirectory $Install -WindowStyle Normal
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    $restoreFailed = $false
    foreach ($name in $installed) {
        Remove-Item -LiteralPath (Join-Path $Install $name) -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in $old) {
        $source = Join-Path $backup $name
        if (Test-Path -LiteralPath $source) {
            try { Move-Item -LiteralPath $source -Destination (Join-Path $Install $name) -Force -ErrorAction Stop }
            catch { $restoreFailed = $true }
        }
    }
    Add-Type -AssemblyName PresentationFramework
    if ($restoreFailed) { $message = 'The update failed and could not fully restore the previous version. Backup: ' + $backup }
    else { $message = 'The update failed. The previous version was restored. Please download the release manually.' }
    [System.Windows.MessageBox]::Show($message, 'BounceMusic Update') | Out-Null
    if (-not $restoreFailed -and (Test-Path -LiteralPath (Join-Path $Install 'BounceMusic.exe'))) {
        Start-Process -FilePath (Join-Path $Install 'BounceMusic.exe') -WorkingDirectory $Install -WindowStyle Normal
    }
}
