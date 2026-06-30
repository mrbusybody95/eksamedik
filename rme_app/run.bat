@echo off
title Dashboard RME Penelitian
cd /d "%~dp0"
echo.
echo ========================================
echo   Dashboard RME Penelitian v3.0
echo   Disease-Agnostic Medical Record
echo   Extraction System
echo ========================================
echo.
echo Buka browser: http://localhost:8503
echo Tekan Ctrl+C untuk stop.
echo.
streamlit run run_rme_app.py --server.port 8503
pause
