@echo off
chcp 65001 >nul
rem Просит программу положить ярлык на рабочий стол.
rem Имя exe содержит номер версии, поэтому ищем по маске: при следующей
rem версии файл переименуется, а этот запускатель останется рабочим.
setlocal
for %%f in ("%~dp0LamodaItemFitter*.exe") do (
    start "" "%%~ff" --create-shortcut
    exit /b 0
)
echo Рядом с этим файлом нет программы LamodaItemFitter.
echo Положите его в ту же папку, где лежит LamodaItemFitter-<версия>.exe
pause
