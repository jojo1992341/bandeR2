<#
.SYNOPSIS
    Démarrage automatisé — CDC RythmoAI v2 §18.4 (G-05)
.DESCRIPTION
    Vérifie prérequis (§18.2), démarre services PostgreSQL/Memurai,
    applique migrations Alembic, lance Uvicorn (API), Celery (CPU/GPU),
    Nginx, attend /health, ouvre navigateur.
    Aucune conteneurisation (§18.1) — processus/services Windows natifs.
#>
[CmdletBinding()]
param()

$LogDir = ".\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = "$LogDir\start_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== start.ps1 — §18.4 / G-05 ==="

# ------------------------------------------------------------------
# 25. Vérifier présence des prérequis dans PATH
# ------------------------------------------------------------------
Write-Log "[25/33] Vérification PATH prérequis..."
$required = @{ "python" = "Python 3.13+"; "node" = "Node 20 LTS+"; "psql" = "PostgreSQL 16+"; "redis-server" = "Memurai/Redis"; "ffmpeg" = "FFmpeg"; "nginx" = "Nginx" }
$missing = @()
foreach ($cmd in $required.Keys) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        $missing += "$cmd ($($required[$cmd]))"
    }
}
if ($missing.Count -gt 0) {
    Write-Log "ERREUR : prérequis manquants : $($missing -join '; ') — exécuté install.ps1 d'abord"
    exit 1
}
Write-Log "Tous prérequis présents dans PATH."

# ------------------------------------------------------------------
# 26. Démarrer services Windows PostgreSQL et Memurai
# ------------------------------------------------------------------
Write-Log "[26/33] Vérification/démarrage services..."
$pgSvcName = "postgresql-x64-16"
$pgSvc = Get-Service $pgSvcName -ErrorAction SilentlyContinue
if (-not $pgSvc) { $pgSvc = Get-Service "postgresql" -ErrorAction SilentlyContinue }
if ($pgSvc) {
    if ($pgSvc.Status -ne "Running") {
        Write-Log "Démarrage service PostgreSQL ($($pgSvc.Name)) ..."
        Start-Service $pgSvc.Name
    } else {
        Write-Log "PostgreSQL déjà démarré ($($pgSvc.Name))."
    }
} else {
    Write-Log "AVERTISSEMENT : service PostgreSQL non trouvé."
}

$memSvc = Get-Service "memurai" -ErrorAction SilentlyContinue
if (-not $memSvc) { $memSvc = Get-Service "redis-server" -ErrorAction SilentlyContinue }
if ($memSvc) {
    if ($memSvc.Status -ne "Running") {
        Write-Log "Démarrage service Memurai/Redis ($($memSvc.Name)) ..."
        Start-Service $memSvc.Name
    } else {
        Write-Log "Memurai/Redis déjà démarré ($($memSvc.Name))."
    }
} else {
    Write-Log "AVERTISSEMENT : service Memurai/Redis non trouvé."
}

# ------------------------------------------------------------------
# 27. Activer venv Python
# ------------------------------------------------------------------
Write-Log "[27/33] Activation venv Python ..."
$venvPath = ".\backend\venv"
$python = "$venvPath\Scripts\python.exe"
$uvicorn = "$venvPath\Scripts\uvicorn.exe"

if (-not (Test-Path $python)) {
    Write-Log "ERREUR : venv non trouvé ($venvPath) — exécuter install.ps1"
    exit 1
}

# ------------------------------------------------------------------
# 28. Migrations Alembic avant démarrage API
# ------------------------------------------------------------------
Write-Log "[28/33] Migrations Alembic (alembic upgrade head) ..."
$alembic = "$venvPath\Scripts\alembic.exe"
& $alembic -c .\backend\alembic.ini upgrade head 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERREUR : migrations Alembic échouées"
    exit 1
}
Write-Log "Migrations OK"

# ------------------------------------------------------------------
# 29. Démarrer API FastAPI (Uvicorn) — processus autonome
# ------------------------------------------------------------------
Write-Log "[29/33] Démarrage API FastAPI (Uvicorn) ..."
$apiLog = ".\logs\uvicorn_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
Start-Process -FilePath $uvicorn -ArgumentList "app.main:app","--host","0.0.0.0","--port","8000","--app-dir",".\backend","--log-level","info" -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError $apiLog -PassThru | Out-Null
Start-Sleep -Seconds 2
Write-Log "API lancée (port 8000) — log : $apiLog"

# ------------------------------------------------------------------
# 30. Detection GPU NVIDIA → worker GPU sinon CPU
# ------------------------------------------------------------------
Write-Log "[30/33] Détection GPU NVIDIA ..."
$gpuDetected = $false
try {
    $gpuInfo = nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null
    if ($gpuInfo) { $gpuDetected = $true; Write-Log "GPU détecté — lancement worker GPU" }
} catch { }
if (-not $gpuDetected) { Write-Log "Pas de GPU — lancement worker CPU uniquement" }

# Worker CPU (toujours)
Write-Log "[30/33] Lancement worker CPU Celery ..."
$celeryLog = ".\logs\celery_cpu_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
# Note : le worker doit être lancé depuis le répertoire backend avec le venv activé
Start-Process -FilePath "$venvPath\Scripts\celery.exe" -ArgumentList "-A","app.tasks","worker","-Q","cpu","-P","solo","-l","info" -WorkingDirectory ".\backend" -WindowStyle Hidden -RedirectStandardOutput $celeryLog -RedirectStandardError $celeryLog -PassThru | Out-Null

if ($gpuDetected) {
    Write-Log "Lancement worker GPU Celery ..."
    $celeryGpuLog = ".\logs\celery_gpu_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
    Start-Process -FilePath "$venvPath\Scripts\celery.exe" -ArgumentList "-A","app.tasks","worker","-Q","gpu","-P","solo","--concurrency=1","-l","info" -WorkingDirectory ".\backend" -WindowStyle Hidden -RedirectStandardOutput $celeryGpuLog -RedirectStandardError $celeryGpuLog -PassThru | Out-Null
}

# ------------------------------------------------------------------
# 31. Démarrer Nginx (reverse proxy + statiques)
# ------------------------------------------------------------------
Write-Log "[31/33] Démarrage Nginx ..."
$nginxPath = "C:\Program Files\nginx\nginx.exe"
if (-not (Test-Path $nginxPath)) { $nginxPath = "nginx.exe" }
Start-Process -FilePath $nginxPath -WindowStyle Hidden -PassThru | Out-Null
Start-Sleep -Seconds 1
Write-Log "Nginx lancé (config : deploy/nginx/nginx.conf si présent)"

# ------------------------------------------------------------------
# 32. Attendre /health (polling 30s) avant navigateur
# ------------------------------------------------------------------
Write-Log "[32/33] Attente endpoint /health (timeout 30s) ..."
$healthOk = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $healthOk = $true
            Write-Log "/health répondu 200 OK — $($resp.Content)"
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $healthOk) {
    Write-Log "AVERTISSEMENT : /health non répondu dans le délai — vérifier api/logs"
}

# ------------------------------------------------------------------
# 33. Résumé console / ouverture navigateur
# ------------------------------------------------------------------
Write-Log "[33/33] Résumé des services démarrés :"
Write-Log "  - PostgreSQL : $($pgSvc.Name) ($($pgSvc.Status))"
Write-Log "  - Memurai/Redis : $($memSvc.Name) ($($memSvc.Status))"
Write-Log "  - API Uvicorn : port 8000 (log $apiLog)"
Write-Log "  - Celery CPU : log $celeryLog"
if ($gpuDetected) { Write-Log "  - Celery GPU : log $celeryGpuLog" }
Write-Log "  - Nginx : reverse proxy + statiques frontend"
Write-Log "=== start.ps1 terminé ==="

# Ouvrir navigateur si /health OK
if ($healthOk) {
    Start-Process "http://localhost:8080"
}
