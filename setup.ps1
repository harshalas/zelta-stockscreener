# Meant for developer use only as a quick setup script for the project.
# Not intended for production use since all directories/files depend on the installed dependencies on the local machines.
# This script is meant to be run in a Windows Terminal tab.


# Docker
Write-Host "Starting Docker" -ForegroundColor Cyan
docker-compose up -d

# Backend
Write-Host "Starting Backend" -ForegroundColor Cyan
Start-Process "wt" -ArgumentList "new-tab --title backend powershell -NoExit -Command `"cd C:\git\zelta-stockscreener\backend; .\venv\Scripts\Activate.ps1; uvicorn main:app --reload`""

# Frontend
Write-Host "Starting Frontend" -ForegroundColor Cyan
Start-Process "wt" -ArgumentList "new-tab --title frontend powershell -NoExit -Command `"cd C:\git\zelta-stockscreener\frontend; npm run dev`""

Write-Host "Setup is ready." -ForegroundColor Green