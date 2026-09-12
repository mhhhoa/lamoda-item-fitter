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
echo   Запускаю. Браузер откроется сам через несколько секунд.
echo   Чтобы закрыть программу - закройте это окно.
echo.
fitter ui
pause
