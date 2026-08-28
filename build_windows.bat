@echo off
rem Локальная сборка exe. Нужен установленный Python 3.10+.
setlocal

echo === Создаю виртуальное окружение ===
python -m venv .venv || goto :error
call .venv\Scripts\activate.bat

echo === Ставлю зависимости ===
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error

echo === Собираю ===
pyinstaller --noconfirm --clean build.spec || goto :error

echo.
echo Готово: dist\ImgFitter.exe
pause
exit /b 0

:error
echo.
echo Сборка не удалась. Посмотрите сообщение выше.
pause
exit /b 1
