@echo off
REM start.bat — lancement démarrage (§18.4 / G-05)
REM Aucune conteneurisation — processus/services Windows natifs (§18.1)
echo ========================================
echo start.bat — CDC RythmoAI v2 §18.4
echo ========================================
powershell -ExecutionPolicy Bypass -File start.ps1
if %ERRORLEVEL% neq 0 (
    echo ERREUR : start.ps1 a échoué (code %ERRORLEVEL%)
    exit /b %ERRORLEVEL%
)
echo Démarrage terminé. Voir logs\start_*.log
pause
