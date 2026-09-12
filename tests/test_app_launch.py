"""Тесты запуска интерфейса.

Фиксируют регрессию, из-за которой программа падала со стек-трейсом, если порт
7860 оставался занят предыдущим окном. Для человека, который не программист,
это выглядело как поломка инструмента, хотя достаточно было занять соседний порт.
"""

import socket
import threading
import time
import urllib.request

import pytest

from item_fitter import app

_MISSING = object()


class FakeDemo:
    """Заглушка Gradio-приложения, запоминающая переданные аргументы.

    Параметры объявлены явно, а не через **kwargs: launch() отбирает аргументы
    по сигнатуре, и у заглушки с одним **kwargs не прошёл бы ни один.
    """

    def __init__(self, raises: Exception | None = None):
        self.kwargs: dict | None = None
        self._raises = raises

    def launch(
        self,
        server_name=_MISSING,
        server_port=_MISSING,
        share=_MISSING,
        inbrowser=_MISSING,
        show_api=_MISSING,
        theme=_MISSING,
        prevent_thread_lock=_MISSING,
    ):
        self.kwargs = {
            k: v for k, v in locals().items() if k != "self" and v is not _MISSING
        }
        if self._raises is not None:
            raise self._raises


@pytest.fixture
def occupy():
    """Занимает порт на время теста и отдаёт его номер."""
    held: list[socket.socket] = []

    def _occupy(port: int) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        held.append(sock)
        return port

    yield _occupy
    for sock in held:
        sock.close()


def _patch_build(monkeypatch, demo: FakeDemo) -> None:
    monkeypatch.setattr(app, "build", lambda: demo)


def test_uses_default_port_when_free(monkeypatch, occupy):
    demo = FakeDemo()
    _patch_build(monkeypatch, demo)

    if not app._port_is_free("127.0.0.1", app.DEFAULT_PORT):
        pytest.skip("порт по умолчанию занят посторонним процессом")

    app.launch(host="127.0.0.1")
    assert demo.kwargs["server_port"] == app.DEFAULT_PORT


def test_busy_default_port_falls_back_instead_of_crashing(monkeypatch, occupy):
    """Главный тест: занятый 7860 — это повод взять соседний, а не упасть."""
    occupy(app.DEFAULT_PORT)
    demo = FakeDemo()
    _patch_build(monkeypatch, demo)

    app.launch(host="127.0.0.1")

    chosen = demo.kwargs["server_port"]
    assert chosen != app.DEFAULT_PORT, "не подобрал свободный порт"
    assert app.DEFAULT_PORT < chosen < app.DEFAULT_PORT + 60


def test_explicit_port_is_honoured(monkeypatch):
    demo = FakeDemo()
    _patch_build(monkeypatch, demo)

    free = app._pick_port("127.0.0.1", None)[0]
    app.launch(host="127.0.0.1", port=free)
    assert demo.kwargs["server_port"] == free


def test_explicit_busy_port_is_an_error_not_a_silent_move(monkeypatch, occupy, capsys):
    """Явно заданный порт — это обещание: молча уехать на соседний нельзя."""
    port = occupy(app._pick_port("127.0.0.1", None)[0])
    demo = FakeDemo()
    _patch_build(monkeypatch, demo)

    with pytest.raises(SystemExit) as exc:
        app.launch(host="127.0.0.1", port=port)

    assert exc.value.code == 1
    assert demo.kwargs is None, "сервер не должен был стартовать"
    out = capsys.readouterr().out
    assert str(port) in out and "уже запущена" in out


def test_late_port_race_gives_advice_not_traceback(monkeypatch, capsys):
    """Если порт перехватили между проверкой и стартом — объясняем, а не падаем."""
    demo = FakeDemo(raises=OSError("Cannot find empty port in range: 7860-7860"))
    _patch_build(monkeypatch, demo)

    with pytest.raises(SystemExit) as exc:
        app.launch(host="127.0.0.1")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "уже запущена" in out
    assert "--port" in out, "человеку нужен готовый способ обойти проблему"


def test_network_mode_prints_reachable_address(monkeypatch, capsys):
    """В сетевом режиме коллегам нужен адрес, а не 0.0.0.0."""
    demo = FakeDemo()
    _patch_build(monkeypatch, demo)

    app.launch(host="0.0.0.0")

    out = capsys.readouterr().out
    assert "0.0.0.0:" not in out
    assert "Адрес для коллег" in out


def test_real_server_starts_when_default_port_is_busy(occupy):
    """Живая проверка: настоящий сервер поднимается и отдаёт страницу."""
    gr = pytest.importorskip("gradio")
    occupy(app.DEFAULT_PORT)

    thread = threading.Thread(
        target=lambda: app.launch(host="127.0.0.1", prevent_thread_lock=True),
        daemon=True,
    )
    thread.start()

    deadline = time.time() + 60
    body = None
    while time.time() < deadline and body is None:
        for port in range(app.DEFAULT_PORT + 1, app.DEFAULT_PORT + 6):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                    body = resp.read().decode("utf-8", "ignore")
                    break
            except OSError:
                continue
        if body is None:
            time.sleep(1)

    assert body is not None, "сервер не поднялся ни на одном соседнем порту"
    assert "Замена фона" in body
