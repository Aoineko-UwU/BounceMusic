param([switch]$SkipInstaller, [string]$InnoCompiler = '', [string]$PythonExe = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not $PythonExe -and -not (Test-Path '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw 'Install Python 3.12 x64 and add it to PATH.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
}
if (-not $PythonExe) { $PythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Python executable not found.' }
& $PythonExe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $PythonExe -m PyInstaller --noconfirm --clean --windowed --onedir --name BounceMusic --icon (Join-Path $PSScriptRoot 'assets\icon.ico') --add-data ((Join-Path $PSScriptRoot 'assets\Loading.gif') + ';assets') --add-data ((Join-Path $PSScriptRoot 'assets\icon.ico') + ';assets') --add-data ((Join-Path $PSScriptRoot 'assets\matou.png') + ';assets') --add-data ((Join-Path $PSScriptRoot 'src\updater.ps1') + ';.') --collect-submodules proctap --collect-submodules winrt.windows.media.control src\app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath 'third_party\ProcTap-LICENSE.txt' -Destination 'dist\BounceMusic\ProcTap-LICENSE.txt' -Force
Write-Host 'Built dist\BounceMusic\BounceMusic.exe; retain the accompanying _internal directory.'
if (-not $SkipInstaller) {
    if (-not $InnoCompiler) {
        $candidate = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($candidate) { $InnoCompiler = $candidate.Source }
        elseif (Test-Path 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe') { $InnoCompiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
        elseif (Test-Path "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") { $InnoCompiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" }
        else { throw 'Install Inno Setup 6 or pass -InnoCompiler. Use -SkipInstaller to build only the portable folder.' }
    }
    $versionLine = Select-String -Path 'src\app.py' -Pattern "^VERSION = '([0-9.]+)'"
    if (-not $versionLine) { throw 'Could not determine application version.' }
    $version = $versionLine.Matches[0].Groups[1].Value
    & $InnoCompiler /Q ("/DAppVersion=$version") ("/DSourceDir=" + (Join-Path $PSScriptRoot 'dist\BounceMusic')) ("/DOutputDir=" + (Join-Path $PSScriptRoot 'dist')) 'installer\BounceMusic.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Write-Host "Built dist\BounceMusic-v$version-Setup-win64.exe"
}
