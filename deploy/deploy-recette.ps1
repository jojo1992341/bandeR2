<#
.SYNOPSIS
    Déploiement automatique en recette à chaque merge sur main — §19.3
.DESCRIPTION
    1. Package l'artefact de livraison (.zip versionné)
    2. Conserve la version précédente (rythmoai-release-previous.zip) pour rollback rapide
    3. Décompresse dans le dossier de recette
    4. Exécute install.ps1 -Update (migrations Alembic)
    5. Redémarre les services Windows persistants via NSSM
#>
[CmdletBinding()]
param(
    [string]$TargetDir = "$PSScriptRoot\recette"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Déploiement automatique en recette RythmoAI v2 (§19.3) ===" -ForegroundColor Cyan
$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "1. Packaging de l'artefact de livraison..." -ForegroundColor Yellow
& $python "$PSScriptRoot\package_release.py"
if ($LASTEXITCODE -ne 0) { throw "Échec du packaging" }

Write-Host "2. Déploiement en recette et redémarrage NSSM..." -ForegroundColor Yellow
& $python "$PSScriptRoot\deploy_recette.py"
if ($LASTEXITCODE -ne 0) { throw "Échec du déploiement recette" }

Write-Host "=== Déploiement recette terminé avec succès ===" -ForegroundColor Green
