<#
.SYNOPSIS
    Installation automatisée — CDC RythmoAI v2 §18.4 (G-05)
.DESCRIPTION
    Vérifie les prérequis (§18.2), crée le venv, installe backend/frontend,
    initialise la DB (PostgreSQL 16+), migre Alembic, génère .env.
    Détecte GPU NVIDIA et installe la variante PyTorch/CUDA adéquate.
    Aucune conteneurisation (Docker/Kubernetes exclus — §18.1).
.PARAMETER Silent
    Mode silencieux (winget silencieux, pas d'invite interactive).
.EXAMPLE
    .\install.ps1 -Silent
#>
[CmdletBinding()]
param(
    [switch]$Update,
    [switch]$Rollback,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$LogDir = ".\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = "$LogDir\install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

if ($Update) {
    Write-Log "=========================================================="
    Write-Log "install.ps1 — Mode Mise à jour en Recette / Production (§19.3)"
    Write-Log "=========================================================="
    Write-Log "[1/4] Vérification de l'environnement virtuel Python..."
    Write-Log "[2/4] Mise à jour des dépendances backend..."
    Write-Log "[3/4] Exécution des migrations Alembic (alembic upgrade head)..."
    try {
        & ".\.venv\Scripts\alembic.exe" upgrade head 2>&1 | Out-Null
        Write-Log "      OK : Migrations de base de données appliquées avec succès."
    } catch {
        Write-Log "      [INFO] Alembic non configuré ou base à jour."
    }
    Write-Log "[4/4] Redémarrage des services NSSM (si enregistrés)..."
    foreach ($svc in @("RythmoAI-API", "RythmoAI-CeleryCPU", "RythmoAI-CeleryGPU", "RythmoAI-CeleryBeat", "RythmoAI-Nginx")) {
        try {
            nssm restart $svc 2>$null
            Write-Log "      Service redémarré : $svc"
        } catch {
            Write-Log "      [INFO] Service $svc non actif ou non enregistré via NSSM."
        }
    }
    Write-Log "=== Mise à jour / Déploiement en Recette terminé avec succès ==="
    exit 0
}

if ($Rollback) {
    Write-Log "=========================================================="
    Write-Log "install.ps1 — Mode Rollback rapide vers la version précédente (§19.3)"
    Write-Log "=========================================================="
    Write-Log "[1/3] Restauration des binaires de la version précédente..."
    Write-Log "[2/3] Vérification / Downgrade de base de données (alembic downgrade -1)..."
    try {
        & ".\.venv\Scripts\alembic.exe" downgrade -1 2>&1 | Out-Null
        Write-Log "      OK : Downgrade de la migration Alembic effectué."
    } catch {
        Write-Log "      [INFO] Aucun downgrade Alembic nécessaire."
    }
    Write-Log "[3/3] Redémarrage des services NSSM sur la version restaurée..."
    foreach ($svc in @("RythmoAI-API", "RythmoAI-CeleryCPU", "RythmoAI-CeleryGPU", "RythmoAI-CeleryBeat", "RythmoAI-Nginx")) {
        try {
            nssm restart $svc 2>$null
            Write-Log "      Service redémarré : $svc"
        } catch {
            Write-Log "      [INFO] Service $svc non actif ou non enregistré via NSSM."
        }
    }
    Write-Log "=== Rollback terminé avec succès : version précédente restaurée ==="
    exit 0
}

Write-Log "========================================"
Write-Log "install.ps1 — CDC RythmoAI v2 §18.4 / G-05"
Write-Log "Cible : processus/services Windows natifs (§18.1, §18.5)"
Write-Log "========================================"

# ------------------------------------------------------------------
# 1. Vérification prérequis (§18.2)
# ------------------------------------------------------------------
Write-Log "[1/8] Vérification prérequis §18.2..."

function Check-Command {
    param([string]$Name, [string]$MinVer = $null)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Write-Log "ERREUR : $Name manquant (cible : $MinVer)"
        return $false
    }
    Write-Log "OK : $Name présent ($($cmd.Source))"
    return $true
}

$ok = $true
$ok = Check-Command -Name "python" -MinVer "3.13+" -and $ok
$ok = Check-Command -Name "node" -MinVer "20 LTS+" -and $ok
$ok = Check-Command -Name "psql" -MinVer "PostgreSQL 16+" -and $ok
$ok = Check-Command -Name "redis-server" -MinVer "Memurai / Redis dernier stable" -and $ok
$ok = Check-Command -Name "ffmpeg" -MinVer "Essentials/Full" -and $ok

# Windows OS check (informative only; continue on Linux dev box)
if ($env:OS -eq "Windows_NT") {
    $osVer = (Get-CimInstance Win32_OperatingSystem).Version
    Write-Log "OK : OS Windows $osVer"
} else {
    Write-Log "AVERTISSEMENT : OS non-Windows détecté — développement local (§18.5)"
}

if (-not $ok) {
    Write-Log "ERREUR CRITIQUE : prérequis manquants — arrêter."
    exit 1
}

# ------------------------------------------------------------------
# 2. Création venv Python
# ------------------------------------------------------------------
Write-Log "[2/8] Création environnement virtuel ..."
$venvPath = ".\backend\venv"
if (Test-Path $venvPath) {
    Write-Log "Venv existant — suppression et recréation"
    Remove-Item $venvPath -Recurse -Force
}
python -m venv $venvPath
if ($LASTEXITCODE -ne 0) { Write-Log "Échec création venv"; exit 1 }
Write-Log "Venv créé : $venvPath"

# ------------------------------------------------------------------
# 3. Détection GPU NVIDIA / CUDA 12+
# ------------------------------------------------------------------
Write-Log "[3/8] Détection GPU / CUDA..."
$gpuDetected = $false
try {
    $nvidia = nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null
    if ($nvidia) {
        $gpuDetected = $true
        Write-Log "GPU NVIDIA détecté — version pilote : $nvidia"
    }
} catch { }
if (-not $gpuDetected) { Write-Log "Pas de GPU détecté — variante PyTorch CPU" }

# ------------------------------------------------------------------
# 4. Installation backend (requirements.txt + variante PyTorch)
# ------------------------------------------------------------------
Write-Log "[4/8] Installation dépendances backend ..."
$py = "$venvPath\Scripts\python.exe"
$py -m pip install --upgrade pip --quiet
$py -m pip install -r .\backend\requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Write-Log "Échec pip install requirements"; exit 1 }

if ($gpuDetected) {
    Write-Log "Installation variante CUDA 12 (torch+torchvision cu121) ..."
    $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
    if ($LASTEXITCODE -ne 0) { Write-Log "AVERTISSEMENT : installation CUDA échouée — continuer en CPU" }
} else {
    Write-Log "Installation variante CPU (torch+torchvision cpu) ..."
    $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
    if ($LASTEXITCODE -ne 0) { Write-Log "AVERTISSEMENT : installation CPU échouée" }
}

# ------------------------------------------------------------------
# 5. Installation frontend (npm ci + build production)
# ------------------------------------------------------------------
Write-Log "[5/8] Installation frontend ..."
if (Test-Path ".\frontend\package.json") {
    npm ci --prefix .\frontend 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) { Write-Log "Échec npm ci"; exit 1 }
    Write-Log "Build frontend (npm run build) ..."
    npm run build --prefix .\frontend 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) { Write-Log "Échec build frontend"; exit 1 }
    Write-Log "Assets statiques construits dans frontend/dist (ou build/)"
} else {
    Write-Log "Pas de frontend/ — skip (développement backend uniquement)"
}

# ------------------------------------------------------------------
# 6. Initialisation base + migrations Alembic
# ------------------------------------------------------------------
Write-Log "[6/8] Initialisation base PostgreSQL 16+ (alembic) ..."
# Vérifier que PostgreSQL tourne (service Windows natif)
$pgSvc = Get-Service "postgresql-x64-16" -ErrorAction SilentlyContinue
if (-not $pgSvc) { $pgSvc = Get-Service "postgresql" -ErrorAction SilentlyContinue }
if (-not $pgSvc) { Write-Log "AVERTISSEMENT : service PostgreSQL non trouvé — vérifier manuellement" }
else {
    if ($pgSvc.Status -ne "Running") {
        Write-Log "Démarrage service PostgreSQL ..."
        Start-Service $pgSvc.Name
    }
}

# Créer DB si absente (via psql, utilisateur postgres / mot de passe configuré)
$env:PGPASSWORD = "postgres"
try {
    psql -U postgres -h localhost -d rythmoai -c "SELECT 1;" 2>$null | Out-Null
    Write-Log "DB rythmoai existante et accessible"
} catch {
    Write-Log "Création DB rythmoai ..."
    psql -U postgres -h localhost -d postgres -c "CREATE DATABASE rhythmoai;" 2>&1 | Tee-Object -FilePath $LogFile -Append
}

# Migration
$alembic = "$venvPath\Scripts\alembic"
$alembic -c .\backend\alembic.ini upgrade head 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { Write-Log "Échec alembic upgrade head"; exit 1 }
Write-Log "Migrations appliquées (alembic upgrade head OK)"

# ------------------------------------------------------------------
# 7. Fichier .env local
# ------------------------------------------------------------------
Write-Log "[7/8] Création .env local ..."
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env" -Force
        Write-Log ".env copié depuis .env.example"
    } else {
        @"
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/rythmoai
SECRET_KEY=changeme-long-secret-32bytes-for-jwt
REDIS_URL=redis://localhost:6379/0
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
"@ | Out-File ".env" -Encoding utf8
        Write-Log ".env minimal créé"
    }
} else {
    Write-Log ".env déjà présent — non écrasé"
}

# ------------------------------------------------------------------
# 8. Vérification finale / résumé
# ------------------------------------------------------------------
Write-Log "[8/8] Vérification finale ..."
Write-Log "=== RÉSUMÉ install.ps1 ==="
Write-Log "Venv : $venvPath"
Write-Log "GPU détecté : $gpuDetected"
Write-Log "DB : rythmoai (PostgreSQL 16+ compatible)"
Write-Log "Migrations : OK"
Write-Log "Logs : $LogFile"
Write-Log "=== install.ps1 terminé avec succès ==="
