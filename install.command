#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo
echo "  Установка. Это нужно сделать один раз, займёт 5-10 минут."
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "  [!] Python 3 не найден. Установите его с https://www.python.org/downloads/"
  read -r -p "  Нажмите Enter..."
  exit 1
fi

echo "  Создаю окружение..."
python3 -m venv .venv || { echo "  [!] Не удалось создать окружение."; read -r; exit 1; }
source .venv/bin/activate

echo "  Ставлю зависимости..."
python -m pip install --upgrade pip --quiet
pip install -e ".[matting,ui]" || { echo "  [!] Установка не удалась."; read -r; exit 1; }

echo
echo "  Готово. Теперь запускайте run.command"
echo
read -r -p "  Нажмите Enter..."
