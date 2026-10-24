$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$pythonExe = if (Test-Path '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $pythonExe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $pythonExe scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
& $pythonExe -m PyInstaller --noconfirm --clean --onedir --windowed --name VoiceChanger --collect-all pedalboard --collect-all _sounddevice_data --add-data 'LICENSE;.' --add-data 'THIRD_PARTY_NOTICES.md;.' launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item README.md,LICENSE,THIRD_PARTY_NOTICES.md -Destination dist/VoiceChanger
Copy-Item docs -Destination dist/VoiceChanger/docs -Recurse -Force
Copy-Item build/licenses -Destination dist/VoiceChanger/licenses -Recurse -Force
$process = Start-Process -FilePath (Resolve-Path 'dist/VoiceChanger/VoiceChanger.exe') -ArgumentList '--self-test','--report','build/packaged-smoke.txt' -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0 -or !(Test-Path 'build/packaged-smoke.txt')) { throw 'Packaged executable smoke test failed' }
Compress-Archive -Path dist/VoiceChanger -DestinationPath dist/VoiceChanger-0.1.0-win-x64.zip -Force
(Get-FileHash dist/VoiceChanger-0.1.0-win-x64.zip -Algorithm SHA256).Hash.ToLower() + '  VoiceChanger-0.1.0-win-x64.zip' | Set-Content dist/SHA256SUMS.txt -Encoding ascii
