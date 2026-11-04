param([string]$Stage, [string]$Install, [int]$AppPid, [switch]$SetupMode)
$ErrorActionPreference = 'Stop'
$backup = Join-Path $Install ('.bounce-update-backup-' + $PID)
$helpFile = [string]::Concat([char]0x4f7f, [char]0x7528, [char]0x8bf4, [char]0x660e, '.txt')
$files = @('BounceMusic.exe', '_internal', 'ProcTap-LICENSE.txt', $helpFile)
$old = @()
$installed = @()
try {
    Wait-Process -Id $AppPid -Timeout 30 -ErrorAction SilentlyContinue
    if (Get-Process -Id $AppPid -ErrorAction SilentlyContinue) { throw 'App did not exit.' }
    if ($SetupMode) {
        $setupPath = Join-Path $Stage 'setup.exe'
        $setup = Start-Process -FilePath $setupPath -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="' + $Install + '"')) -WindowStyle Hidden -Wait -PassThru
        if ($setup.ExitCode -ne 0) { throw ('Setup exited with code ' + $setup.ExitCode) }
        Start-Process -FilePath (Join-Path $Install 'BounceMusic.exe') -WorkingDirectory $Install -WindowStyle Normal
        Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
        exit 0
    }
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
    if ($SetupMode) { $message = 'The update installer failed. Please download the latest Setup from the release page and try again.' }
    elseif ($restoreFailed) { $message = 'The update failed and could not fully restore the previous version. Backup: ' + $backup }
    else { $message = 'The update failed. The previous version was restored. Please download the release manually.' }
    [System.Windows.MessageBox]::Show($message, 'BounceMusic Update') | Out-Null
    if (-not $restoreFailed -and (Test-Path -LiteralPath (Join-Path $Install 'BounceMusic.exe'))) {
        Start-Process -FilePath (Join-Path $Install 'BounceMusic.exe') -WorkingDirectory $Install -WindowStyle Normal
    }
}
