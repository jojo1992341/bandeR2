@echo off
REM install.bat — lancement silencieux de install.ps1 (§18.4 / G-05)
REM Aucune conteneurisation — processus/services Windows natifs uniquement (§18.1)

echo ========================================
echo install.bat — CDC RythmoAI v2 §18.4
echo ========================================

REM Autoriser l'exécution PowerShell si nécessaire
powershell -ExecutionPolicy Bypass -File install.ps1 -Silent
if %ERRORLEVEL% neq 0 (
    echo ERREUR : install.ps1 a échoué (code %ERRORLEVEL%)
    exit /b %ERRORLEVEL%
)
echo Installation terminée avec succès. Voir logs\install_*.log
pause
