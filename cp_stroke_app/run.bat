@echo off
title Anonimisasi RME Stroke - Dashboard
cd /d "%~dp0"

echo ============================================
echo   Anonimisasi RME Stroke - Dashboard
echo   100%% Lokal - Offline
echo ============================================
echo.

:: Aktivasi virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ERROR] Virtual environment tidak ditemukan.
    echo Jalankan dulu: python -m venv .venv
    pause
    exit /b 1
)

echo [INFO] Menjalankan Streamlit app...
echo [INFO] Buka browser di http://localhost:8501
echo [INFO] Tekan CTRL+C untuk berhenti.
echo.

streamlit run run_stroke_app.py

echo.
echo [INFO] Aplikasi ditutup.
pause
