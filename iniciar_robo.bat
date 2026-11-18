@echo off
REM Liga o robo e o dashboard em duas janelas. Para parar, feche as janelas (ou Ctrl+C).
cd /d "%~dp0"
start "ROBO - nao feche esta janela" cmd /k py -3.13 bot.py
timeout /t 5 /nobreak >nul
start "DASHBOARD" cmd /k py -3.13 dashboard.py
