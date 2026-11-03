$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw 'Install Python 3.12 x64 and add it to PATH.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
}
& .venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name BounceMusic --icon (Join-Path $PSScriptRoot 'assets\icon.ico') --collect-submodules proctap src\app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath 'third_party\ProcTap-LICENSE.txt' -Destination 'dist\BounceMusic\ProcTap-LICENSE.txt' -Force
Write-Host 'Built dist\BounceMusic\BounceMusic.exe; retain the accompanying _internal directory.'
