$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$pythonExe = if (Test-Path '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $pythonExe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $pythonExe scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
& $pythonExe -m PyInstaller --noconfirm --clean --onedir --windowed --name VoiceChanger --collect-all pedalboard --collect-all _sounddevice_data --add-data 'voice_changer/engine_worker.py;voice_changer' --add-data 'voice_changer/engine-requirements.txt;voice_changer' --add-data 'LICENSE;.' --add-data 'THIRD_PARTY_NOTICES.md;.' launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item README.md,LICENSE,THIRD_PARTY_NOTICES.md -Destination dist/VoiceChanger
Copy-Item docs -Destination dist/VoiceChanger/docs -Recurse -Force
Copy-Item build/licenses -Destination dist/VoiceChanger/licenses -Recurse -Force
$process = Start-Process -FilePath (Resolve-Path 'dist/VoiceChanger/VoiceChanger.exe') -ArgumentList '--self-test','--report','build/packaged-smoke.txt' -WindowStyle Hidden -PassThru -Wait
if ($process.ExitCode -ne 0 -or !(Test-Path 'build/packaged-smoke.txt')) { throw 'Packaged executable smoke test failed' }
$version = & $pythonExe -c 'from voice_changer import __version__; print(__version__)'
$archiveName = "VoiceChanger-$version-win-x64.zip"
Compress-Archive -Path dist/VoiceChanger -DestinationPath "dist/$archiveName" -Force
(Get-FileHash "dist/$archiveName" -Algorithm SHA256).Hash.ToLower() + "  $archiveName" | Set-Content dist/SHA256SUMS.txt -Encoding ascii
