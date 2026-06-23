# Meant for developer use only as a quick setup script for the project.
# Not intended for production use since all directories/files depend on the installed dependencies on the local machines.
# This script is meant to be run in a Windows Terminal tab.

$root = "C:\git\zelta-stockscreener"
$ps = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

Write-Host "Starting all services..." -ForegroundColor Cyan

$dockerCmd = "`$host.UI.RawUI.WindowTitle = 'Docker'; cd $root; docker-compose up -d; Write-Host 'Docker is running.' -ForegroundColor Green"
$encodedDocker = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($dockerCmd))

$backendCmd = "`$host.UI.RawUI.WindowTitle = 'Backend'; cd $root\backend; .\venv\Scripts\Activate.ps1; .\venv\Scripts\uvicorn.exe main:app --reload"
$encodedBackend = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($backendCmd))

$frontendCmd = "`$host.UI.RawUI.WindowTitle = 'Frontend'; cd $root\frontend; npm run dev"
$encodedFrontend = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($frontendCmd))

Start-Process wt -ArgumentList "new-tab --title Docker --suppressApplicationTitle -d `"$root`" `"$ps`" -NoExit -EncodedCommand $encodedDocker ; new-tab --title Backend --suppressApplicationTitle -d `"$root\backend`" `"$ps`" -NoExit -EncodedCommand $encodedBackend ; new-tab --title Frontend --suppressApplicationTitle -d `"$root\frontend`" `"$ps`" -NoExit -EncodedCommand $encodedFrontend"

Write-Host "Setup is ready." -ForegroundColor Green