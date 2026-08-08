@echo off
REM install-service.bat — Lanceur Windows pour install-service.ps1 (§18.4)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-service.ps1" %*
