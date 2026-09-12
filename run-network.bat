@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
  echo   [!] Сначала запустите install.bat
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
echo.
echo   Запускаю с доступом для коллег по локальной сети.
echo   Коллеги открывают в браузере: http://ВАШ-IP-АДРЕС:7860
echo   Узнать свой IP: команда ipconfig
echo.
fitter ui --host 0.0.0.0
pause
