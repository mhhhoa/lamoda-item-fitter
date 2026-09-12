@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo   Установка. Это нужно сделать один раз, займёт 5-10 минут.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   [!] Python не найден.
  echo       Скачайте его с https://www.python.org/downloads/
  echo       При установке обязательно поставьте галочку "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo   Создаю окружение...
python -m venv .venv || (echo   [!] Не удалось создать окружение. & pause & exit /b 1)
call .venv\Scripts\activate.bat

echo   Ставлю зависимости...
python -m pip install --upgrade pip --quiet
pip install -e ".[matting,ui]" || (echo   [!] Установка не удалась. & pause & exit /b 1)

echo.
echo   Готово. Теперь запускайте run.bat
echo.
pause
