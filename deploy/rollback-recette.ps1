<#
.SYNOPSIS
    Rollback rapide vers la version précédente en recette — §19.3
.DESCRIPTION
    Restaure l'archive de la version précédente (rythmoai-release-previous.zip),
    applique un downgrade de base de données si nécessaire, et redémarre les services NSSM.
#>
[CmdletBinding()]
param(
    [string]$TargetDir = "$PSScriptRoot\recette"
)

$ErrorActionPreference = "Stop"
Write-Host "=== Rollback rapide vers la version précédente (§19.3) ===" -ForegroundColor Yellow

$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

& $python "$PSScriptRoot\rollback_recette.py"
if ($LASTEXITCODE -ne 0) { throw "Échec du rollback recette" }
Write-Host "=== Rollback terminé avec succès ===" -ForegroundColor Green
