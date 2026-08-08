<#
.SYNOPSIS
    Arrêt propre — CDC RythmoAI v2 §18.4 (G-05)
.DESCRIPTION
    Arrête API (Uvicorn), workers Celery (CPU/GPU), Nginx.
    Ne stoppe PAS PostgreSQL ni Memurai (services système persistants).
#>
[CmdletBinding()]
param()

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line
    $LogDir = ".\logs"
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
    Add-Content -Path "$LogDir\stop_$(Get-Date -Format 'yyyyMMdd_HHmmss').log" -Value $line -Encoding UTF8
}

Write-Log "=== stop.ps1 — arrêt propre (§18.3 / §18.4) ==="

# Arrêt Uvicorn (par port / nom)
Get-Process | Where-Object { $_.ProcessName -match "uvicorn" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Log "API Uvicorn arrêté."

# Arrêt Celery workers (CPU et GPU)
Get-Process | Where-Object { $_.ProcessName -match "celery" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Log "Workers Celery arrêtés."

# Arrêt Nginx
Get-Process | Where-Object { $_.ProcessName -match "nginx" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Log "Nginx arrêté."

# PostgreSQL et Memurai restent actifs (services système)
Write-Log "Services PostgreSQL / Memurai non arrêtés (persistance §18.3)."
Write-Log "=== stop.ps1 terminé ==="
