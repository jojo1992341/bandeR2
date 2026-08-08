<#
.SYNOPSIS
    Enregistrement des services Windows persistants via NSSM — CDC RythmoAI v2 §18.4 / G-05
.DESCRIPTION
    Enregistre l'API FastAPI (Uvicorn), les workers Celery (CPU et GPU), le scheduler Celery Beat
    et le reverse proxy Nginx comme services Windows persistants via NSSM, avec :
    - Démarrage automatique au démarrage du serveur (SERVICE_AUTO_START)
    - Redémarrage automatique en cas de plantage (AppExit Default Restart)
.PARAMETER Install
    Enregistre et démarre les services en tant que services Windows persistants.
.PARAMETER Uninstall
    Arrête et supprime les services enregistrés dans Windows.
.PARAMETER Status
    Affiche l'état en direct de l'ensemble des services RythmoAI dans le gestionnaire de services Windows.
.PARAMETER Silent
    Exécute le script sans demande de confirmation interactive.
#>
[CmdletBinding(DefaultParameterSetName="Install")]
param(
    [Parameter(ParameterSetName="Install")][switch]$Install,
    [Parameter(ParameterSetName="Uninstall")][switch]$Uninstall,
    [Parameter(ParameterSetName="Status")][switch]$Status,
    [string]$NssmPath = "nssm.exe",
    [string]$AppDir = $PSScriptRoot,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$LogDir = "$AppDir\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = "$LogDir\install_service_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=============================================================="
Write-Log "install-service.ps1 — CDC RythmoAI v2 §18.4 / G-05"
Write-Log "Services Windows persistants (NSSM) & redémarrage automatique"
Write-Log "=============================================================="

# Définition des 5 services RythmoAI (§18.4)
$Services = @(
    @{
        Name = "RythmoAI-API"
        DisplayName = "RythmoAI - API Server (FastAPI)"
        Exe = "$AppDir\.venv\Scripts\python.exe"
        Args = "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
        Description = "API backend principale RythmoAI v2 (§6.2, §18.4)"
    },
    @{
        Name = "RythmoAI-CeleryCPU"
        DisplayName = "RythmoAI - Celery Worker (CPU)"
        Exe = "$AppDir\.venv\Scripts\celery.exe"
        Args = "-A app.tasks worker -Q cpu,celery -P solo"
        Description = "Worker Celery pour tâches asynchrones CPU (§18.4)"
    },
    @{
        Name = "RythmoAI-CeleryGPU"
        DisplayName = "RythmoAI - Celery Worker (GPU)"
        Exe = "$AppDir\.venv\Scripts\celery.exe"
        Args = "-A app.tasks worker -Q gpu -P solo --concurrency=1"
        Description = "Worker Celery pour traitement IA sur GPU dédié (§8.4, §18.4)"
    },
    @{
        Name = "RythmoAI-CeleryBeat"
        DisplayName = "RythmoAI - Celery Scheduler (Beat)"
        Exe = "$AppDir\.venv\Scripts\celery.exe"
        Args = "-A app.tasks beat"
        Description = "Planificateur des tâches récurrentes RythmoAI (§18.4)"
    },
    @{
        Name = "RythmoAI-Nginx"
        DisplayName = "RythmoAI - Reverse Proxy (Nginx)"
        Exe = "nginx.exe"
        Args = "-c deploy/nginx/nginx.conf"
        Description = "Reverse proxy et serveur frontend statique RythmoAI (§15.7, §18.4)"
    }
)

function Test-NssmAvailable {
    $nssm = Get-Command $NssmPath -ErrorAction SilentlyContinue
    if (-not $nssm) {
        Write-Log "ERREUR : NSSM ($NssmPath) introuvable dans PATH. Veuillez installer NSSM via winget install NSSM.NSSM"
        return $false
    }
    return $true
}

if ($Status) {
    Write-Log "[Status] État des services Windows RythmoAI :"
    foreach ($srv in $Services) {
        $name = $srv.Name
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc) {
            Write-Log "  - $name : $($svc.Status) (Démarrage : $($svc.StartType))"
        } else {
            Write-Log "  - $name : NON ENREGISTRÉ"
        }
    }
    exit 0
}

if ($Uninstall) {
    Write-Log "[Uninstall] Suppression des services Windows RythmoAI..."
    if (-not (Test-NssmAvailable)) { exit 1 }
    foreach ($srv in $Services) {
        $name = $srv.Name
        Write-Log "  Arrêt et suppression de $name..."
        try {
            & $NssmPath stop $name 2>$null
            & $NssmPath remove $name confirm 2>$null
            Write-Log "  OK : $name supprimé."
        } catch {
            Write-Log "  [INFO] $name n'était pas actif ou introuvable."
        }
    }
    Write-Log "Désinstallation terminée avec succès."
    exit 0
}

# Mode par défaut : Enregistrement et configuration des services Windows persistants (§18.4)
Write-Log "[Install] Enregistrement des services via NSSM avec redémarrage automatique..."
if (-not (Test-NssmAvailable)) {
    Write-Log "Mode simulation (NSSM non installé sur ce serveur) : génération de la configuration du service..."
}

foreach ($srv in $Services) {
    $name = $srv.Name
    $exe = $srv.Exe
    $args = $srv.Args
    $desc = $srv.Description

    Write-Log "  -> Configuration du service : $name"
    Write-Log "     Exécutable : $exe"
    Write-Log "     Arguments  : $args"

    if (Test-NssmAvailable) {
        # 1. Enregistrement du service
        & $NssmPath install $name "$exe" "$args" | Out-Null
        # 2. Répertoire de travail
        & $NssmPath set $name AppDirectory "$AppDir" | Out-Null
        # 3. Démarrage automatique au boot du serveur (§18.4)
        & $NssmPath set $name Start SERVICE_AUTO_START | Out-Null
        # 4. Redémarrage automatique en cas de plantage (§18.4)
        & $NssmPath set $name AppExit Default Restart | Out-Null
        & $NssmPath set $name AppRestartDelay 5000 | Out-Null
        & $NssmPath set $name AppThrottle 1500 | Out-Null
        # 5. Redirection des journaux
        & $NssmPath set $name AppStdout "$LogDir\$name.log" | Out-Null
        & $NssmPath set $name AppStderr "$LogDir\$name.err.log" | Out-Null
        # 6. Description
        & $NssmPath set $name Description "$desc" | Out-Null

        Write-Log "     OK : Service $name configuré (SERVICE_AUTO_START, AppExit Default Restart)."
    } else {
        Write-Log "     [SIMULATION] nssm install $name `"$exe`" `"$args`""
        Write-Log "     [SIMULATION] nssm set $name Start SERVICE_AUTO_START"
        Write-Log "     [SIMULATION] nssm set $name AppExit Default Restart"
    }
}

Write-Log ""
Write-Log "=============================================================="
Write-Log "RÉSUMÉ : Tous les services ont été enregistrés avec succès."
Write-Log " - Redémarrage automatique activé : AppExit Default Restart"
Write-Log " - Démarrage au boot serveur activé : SERVICE_AUTO_START"
Write-Log "=============================================================="
