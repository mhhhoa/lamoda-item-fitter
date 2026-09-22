"""Единая защита от падений.

PySide6 завершает процесс, если исключение вылетело из слота или из
перерисовки виджета: окно просто исчезает, ничего не показав. Для программы,
которую запускают коллеги, это худшее поведение из возможных — поэтому любой
сбой перехватывается, пишется в лог рядом с программой и превращается в
статус строки, а не в закрытие окна.
"""

from __future__ import annotations

import functools
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import app_dir

LOG_NAME = "LamodaItemFitter.log"

_lock = threading.Lock()
_listeners: list[Callable[[str], None]] = []


def log_path() -> Path:
    return app_dir() / LOG_NAME


def add_listener(callback: Callable[[str], None]) -> None:
    """Подписка интерфейса на сообщения о сбоях."""
    _listeners.append(callback)


def describe(error: BaseException) -> str:
    """Короткое человеческое описание сбоя для строки статуса."""
    if isinstance(error, MemoryError):
        return "не хватило оперативной памяти"
    if isinstance(error, (FileNotFoundError, PermissionError, OSError)):
        return f"файловая ошибка: {error}"
    text = str(error).strip()
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


#: больше этого лог не растёт: при перезапуске старый отодвигается в .1
MAX_LOG_BYTES = 2 * 1024 * 1024


def _write(text: str) -> None:
    try:
        with _lock:
            with log_path().open("a", encoding="utf-8") as handle:
                handle.write(text)
    except Exception:
        pass  # лог — не повод падать


def trace(message: str) -> None:
    """Короткая строка о том, что программа делает прямо сейчас.

    Нужна ровно для одного случая: когда процесс убивает система — из-за
    нехватки памяти или падения внутри системной библиотеки. Исключения при
    этом не возникает, перехватывать нечего, и единственный след — последняя
    строка в логе. По ней видно, на каком файле всё оборвалось; без неё о
    причине можно только гадать.
    """
    _write(f"{datetime.now().strftime('%H:%M:%S')}  {message}\n")


def start_log(header: str) -> None:
    """Открывает лог нового запуска, отодвинув разросшийся старый."""
    try:
        path = log_path()
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except Exception:
        pass
    _write(f"\n===== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {header} =====\n")


def log_only(where: str, error: BaseException) -> str:
    """Пишет сбой в лог, но не тревожит интерфейс.

    Для ожидаемых отказов конкретного файла: причина и так видна в его строке,
    а строка статуса должна показывать итог пакета, а не последний битый кадр.
    """
    summary = describe(error)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    _write(f"\n===== {stamp} — {where} =====\n{body}")
    return summary


def report(where: str, error: BaseException) -> str:
    """Пишет сбой в лог и уведомляет интерфейс. Для неожиданных сбоев."""
    summary = log_only(where, error)
    for listener in list(_listeners):
        try:
            listener(f"{where}: {summary}")
        except Exception:
            pass
    return summary


def guard(where: str):
    """Оборачивает слот Qt: исключение внутри не должно ронять приложение."""

    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as error:  # noqa: BLE001 — на то и защита
                report(where, error)
                return None

        return wrapper

    return decorator


def install() -> None:
    """Ставит перехватчики на необработанные исключения во всех потоках."""

    def hook(kind, value, tb) -> None:
        if issubclass(kind, KeyboardInterrupt):
            return
        report("необработанная ошибка", value if value else kind())

    sys.excepthook = hook

    def thread_hook(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        report(f"поток {args.thread.name if args.thread else '?'}",
               args.exc_value or args.exc_type())

    threading.excepthook = thread_hook
