@echo off
REM stop.bat — arrêt démon (§18.4 / G-05)
echo ========================================
echo stop.bat — arrêt processus applicatifs (§18.3)
echo ========================================
powershell -ExecutionPolicy Bypass -File stop.ps1
if %ERRORLEVEL% neq 0 (
    echo AVERTISSEMENT : stop.ps1 a retourné un code non nul
)
echo Arrêt terminé. Services PostgreSQL / Memurai conservent leur état.
pause
