$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onedir --name StinkSNIFFER --icon assets/sniffy.ico --add-data "assets;assets" --add-binary "bin/ffmpeg.exe;bin" --add-binary "bin/ffprobe.exe;bin" app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
# Qt uses Windows 10/11's ICU. A Conda DLL with the same filename has incompatible exports.
$icuPath = Join-Path $PSScriptRoot 'dist\StinkSNIFFER\_internal\icuuc.dll'
if (Test-Path -LiteralPath $icuPath) { Remove-Item -LiteralPath $icuPath }
$qtPath = python -c "import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).parent)"
Copy-Item (Join-Path $qtPath 'msvcp140*.dll') 'dist\StinkSNIFFER\_internal' -Force
Copy-Item (Join-Path $qtPath 'vcruntime140*.dll') 'dist\StinkSNIFFER\_internal' -Force
Copy-Item (Join-Path $qtPath 'concrt140.dll') 'dist\StinkSNIFFER\_internal' -Force
