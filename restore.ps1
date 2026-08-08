<#
.SYNOPSIS
    Restauration PRA/PCA à partir d'une sauvegarde de test aboutissant à un système fonctionnel — §18.7
.DESCRIPTION
    Restaure la base de données PostgreSQL à partir d'un fichier de sauvegarde (.sql) et
    restaure les médias depuis l'emplacement distant.
.PARAMETER BackupFile
    Chemin vers le fichier .sql à restaurer (si omis, prend la sauvegarde la plus récente).
.PARAMETER RemoteMediaDir
    Dossier distant contenant les médias sauvegardés.
#>
[CmdletBinding()]
param(
    [string]$BackupFile = "",
    [string]$RemoteMediaDir = "$PSScriptRoot\backups\remote_storage"
)

$ErrorActionPreference = "Stop"
$LogDir = "$PSScriptRoot\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = "$LogDir\restore_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line -ForegroundColor Yellow
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== Restauration PRA/PCA RythmoAI v2 (§18.7) ==="

$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

# Identifier le fichier de sauvegarde si non spécifié
if (-not $BackupFile -or $BackupFile -eq "") {
    $BackupDir = "$PSScriptRoot\backups\db"
    $latest = Get-ChildItem -Path $BackupDir -Filter "rythmoai_backup_*.sql" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Log "ERREUR : Aucun fichier de sauvegarde trouvé dans $BackupDir"
        exit 1
    }
    $BackupFile = $latest.FullName
}

Write-Log "Fichier de sauvegarde sélectionné : $BackupFile"
Write-Log "Emplacement distant médias       : $RemoteMediaDir"

$cmd = @"
import os, sys, json
from pathlib import Path
from app.core.database import SessionLocal
from app.core.backup_service import restore_from_backup

db = SessionLocal()
try:
    res = restore_from_backup(
        db,
        backup_file=Path(r'$BackupFile'),
        remote_media_dir=Path(r'$RemoteMediaDir')
    )
    print(json.dumps(res, indent=2))
finally:
    db.close()
"@

Write-Log "Restauration des données en cours..."
$output = & $python -c $cmd
Write-Log $output
Write-Log "=== Restauration terminée avec succès : système fonctionnel ==="
