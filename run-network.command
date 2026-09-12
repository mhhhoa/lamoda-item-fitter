#!/bin/bash
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "  [!] Сначала запустите install.command"
  read -r -p "  Нажмите Enter..."
  exit 1
fi

source .venv/bin/activate
echo
echo "  Запускаю с доступом для коллег по локальной сети."
echo "  Коллеги открывают в браузере: http://ВАШ-IP-АДРЕС:7860"
echo "  Узнать свой IP: Системные настройки -> Сеть"
echo
fitter ui --host 0.0.0.0
