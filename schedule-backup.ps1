<#
.SYNOPSIS
    Planification de la sauvegarde automatique quotidienne dans le Planificateur de tâches Windows — §18.7
.DESCRIPTION
    Enregistre une tâche planifiée Windows (RythmoAI-DailyBackup) s'exécutant tous les jours
    à 02:00 pour lancer le script backup.ps1, assurant la rétention de 30 jours
    et la copie distante des médias.
.PARAMETER Install
    Enregistre la tâche planifiée quotidienne dans Windows.
.PARAMETER Uninstall
    Supprime la tâche planifiée.
#>
[CmdletBinding(DefaultParameterSetName="Install")]
param(
    [Parameter(ParameterSetName="Install")][switch]$Install,
    [Parameter(ParameterSetName="Uninstall")][switch]$Uninstall,
    [string]$TaskName = "RythmoAI-DailyBackup",
    [string]$Time = "02:00AM"
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
    Write-Host "Suppression de la tâche planifiée $TaskName..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tâche planifiée supprimée." -ForegroundColor Green
    exit 0
}

Write-Host "Enregistrement de la tâche planifiée quotidienne : $TaskName à $Time..." -ForegroundColor Cyan
$scriptPath = "$PSScriptRoot\backup.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "RythmoAI v2 - Sauvegarde quotidienne PostgreSQL & Médias (§18.7)" -Force | Out-Null
Write-Host "Tâche planifiée enregistrée avec succès (exécution quotidienne à $Time)." -ForegroundColor Green
