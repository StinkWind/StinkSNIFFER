$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onedir --name StinkSNIFFER --add-data "assets;assets" --add-binary "bin/ffmpeg.exe;bin" --add-binary "bin/ffprobe.exe;bin" app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
