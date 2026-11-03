$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv }
& .venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name BounceMusic --icon (Join-Path $PSScriptRoot 'assets\icon.ico') --collect-submodules proctap src\app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath 'third_party\ProcTap-LICENSE.txt' -Destination 'dist\BounceMusic\ProcTap-LICENSE.txt' -Force
Write-Host 'Built dist\BounceMusic\BounceMusic.exe; retain the accompanying _internal directory.'
