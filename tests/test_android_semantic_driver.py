from __future__ import annotations

import json
import socket
import threading

import pytest

from godot_game_test_lab.android_semantic_driver import (
    AndroidSemanticDriverClient,
    AndroidSemanticDriverError,
    SCHEMA,
    validate_action_name,
    validate_duration_ms,
    validate_port,
)


def _serve_once(listener: socket.socket, responses: list[dict[str, object]]) -> None:
    conn, _ = listener.accept()
    with conn:
        for response in responses:
            request = b""
            while not request.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    return
                request += chunk
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")


def test_validation_is_bounded() -> None:
    assert validate_port(43821) == 43821
    assert validate_action_name("move_right") == "move_right"
    assert validate_duration_ms(100) == 100
    with pytest.raises(ValueError):
        validate_port(80)
    with pytest.raises(ValueError):
        validate_action_name("bad action")
    with pytest.raises(ValueError):
        validate_duration_ms(5000)


def test_client_uses_loopback_and_target_allow_list() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    responses = [
        {
            "schema": SCHEMA,
            "ok": True,
            "session": "0123456789abcdef0123456789abcdef",
            "allowedActions": ["jump"],
            "scene": "res://main.tscn",
        },
        {"schema": SCHEMA, "ok": True, "op": "action", "name": "jump"},
        {"schema": SCHEMA, "ok": True, "op": "state", "scene": "res://main.tscn"},
    ]
    worker = threading.Thread(target=_serve_once, args=(listener, responses), daemon=True)
    worker.start()
    try:
        with AndroidSemanticDriverClient(port) as client:
            assert client.pulse("jump", duration_ms=80)["name"] == "jump"
            assert client.state()["scene"] == "res://main.tscn"
            with pytest.raises(AndroidSemanticDriverError, match="not allowed"):
                client.press("delete_save")
    finally:
        listener.close()
        worker.join(timeout=1)


def test_client_rejects_wrong_schema() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    worker = threading.Thread(
        target=_serve_once,
        args=(listener, [{"schema": "wrong", "ok": True}]),
        daemon=True,
    )
    worker.start()
    try:
        with pytest.raises(AndroidSemanticDriverError, match="hello"):
            AndroidSemanticDriverClient(port).connect()
    finally:
        listener.close()
        worker.join(timeout=1)
