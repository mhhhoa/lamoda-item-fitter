#!/bin/bash
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "  [!] Сначала запустите install.command"
  read -r -p "  Нажмите Enter..."
  exit 1
fi

source .venv/bin/activate
echo
echo "  Запускаю. Браузер откроется сам через несколько секунд."
echo "  Чтобы закрыть программу - закройте это окно."
echo
fitter ui
