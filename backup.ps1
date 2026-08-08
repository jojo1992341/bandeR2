<#
.SYNOPSIS
    Sauvegarde quotidienne automatisée de PostgreSQL et copie du stockage médias — §18.7
.DESCRIPTION
    Exécute un dump SQL de la base de données (pg_dump planifié), applique une politique
    de rétention de 30 jours sur le dossier de sauvegarde, et copie le stockage des médias
    et exports vers un emplacement distant (partage réseau ou stockage cloud) pour PRA/PCA.
.PARAMETER BackupDir
    Dossier cible pour les sauvegardes de la base de données (défaut: .\backups\db)
.PARAMETER RemoteMediaDir
    Dossier de stockage distant pour la copie planifiée des médias (défaut: .\backups\remote_storage)
.PARAMETER RetentionDays
    Nombre de jours de rétention pour les sauvegardes (défaut: 30)
#>
[CmdletBinding()]
param(
    [string]$BackupDir = "$PSScriptRoot\backups\db",
    [string]$RemoteMediaDir = "$PSScriptRoot\backups\remote_storage",
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$LogDir = "$PSScriptRoot\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = "$LogDir\backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line -ForegroundColor Green
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== Sauvegarde automatique quotidienne RythmoAI v2 (§18.7) ==="
Write-Log "Dossier sauvegardes DB      : $BackupDir (rétention: $RetentionDays jours)"
Write-Log "Dossier distant médias/exp.  : $RemoteMediaDir"

# Exécution du service de sauvegarde unifié
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$cmd = @"
import os, sys, json
from pathlib import Path
from app.core.database import SessionLocal
from app.core.backup_service import create_daily_backup

db = SessionLocal()
try:
    res = create_daily_backup(
        db,
        backup_dir=Path(r'$BackupDir'),
        remote_media_dir=Path(r'$RemoteMediaDir'),
        retention_days=$RetentionDays
    )
    print(json.dumps(res, indent=2))
finally:
    db.close()
"@

Write-Log "Exécution du dump SQL et copie planifiée des médias..."
$output = & $python -c $cmd
Write-Log $output
Write-Log "=== Sauvegarde et purge (rétention 30 jours) terminées avec succès ==="
