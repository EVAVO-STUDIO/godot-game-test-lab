from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from typing import Any

SCHEMA = "evavo.godot.android-semantic-driver.v1"
MAX_MESSAGE_BYTES = 16_384
_ACTION_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class AndroidSemanticDriverError(RuntimeError):
    """Raised when the physical-device semantic driver contract is violated."""


def validate_port(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
        raise ValueError("port must be an integer between 1024 and 65535")
    return value


def validate_action_name(value: str) -> str:
    if not isinstance(value, str) or _ACTION_RE.fullmatch(value) is None:
        raise ValueError("action name must match [A-Za-z0-9_.:-]{1,64}")
    return value


def validate_strength(value: float) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("strength must be between 0 and 1")
    return number


def validate_duration_ms(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 16 <= value <= 2000:
        raise ValueError("durationMs must be an integer between 16 and 2000")
    return value


@dataclass(frozen=True)
class DriverHello:
    session: str
    allowed_actions: tuple[str, ...]
    scene: str | None


class AndroidSemanticDriverClient:
    """Bounded loopback client for a debug-only Godot physical-device driver."""

    def __init__(self, port: int, *, timeout_seconds: float = 2.0) -> None:
        self.port = validate_port(port)
        self.timeout_seconds = float(timeout_seconds)
        if not 0.1 <= self.timeout_seconds <= 10.0:
            raise ValueError("timeout_seconds must be between 0.1 and 10.0")
        self._socket: socket.socket | None = None
        self._buffer = bytearray()
        self._session: str | None = None
        self._allowed_actions: frozenset[str] = frozenset()

    def __enter__(self) -> AndroidSemanticDriverClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> DriverHello:
        if self._socket is not None:
            raise AndroidSemanticDriverError("driver client is already connected")
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout_seconds)
        sock.settimeout(self.timeout_seconds)
        self._socket = sock
        try:
            response = self._request({"op": "hello"}, include_session=False)
            session = response.get("session")
            actions = response.get("allowedActions")
            if not isinstance(session, str) or len(session) != 32:
                raise AndroidSemanticDriverError("driver returned an invalid session id")
            if not isinstance(actions, list) or len(actions) > 128:
                raise AndroidSemanticDriverError(
                    "driver returned an invalid action allow-list"
                )
            normalized = tuple(validate_action_name(action) for action in actions)
            if len(set(normalized)) != len(normalized):
                raise AndroidSemanticDriverError(
                    "driver returned duplicate allowed actions"
                )
            self._session = session
            self._allowed_actions = frozenset(normalized)
            scene = response.get("scene")
            if scene is not None and not isinstance(scene, str):
                scene = None
            return DriverHello(
                session=session,
                allowed_actions=normalized,
                scene=scene,
            )
        except (OSError, ValueError, AndroidSemanticDriverError):
            self.close()
            raise

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
                self._buffer.clear()
                self._session = None
                self._allowed_actions = frozenset()

    def state(self) -> dict[str, Any]:
        return self._request({"op": "state"})

    def press(self, action: str, *, strength: float = 1.0) -> dict[str, Any]:
        return self._action(action, "press", strength=strength)

    def release(self, action: str) -> dict[str, Any]:
        return self._action(action, "release", strength=0.0)

    def pulse(
        self,
        action: str,
        *,
        duration_ms: int = 100,
        strength: float = 1.0,
    ) -> dict[str, Any]:
        return self._action(
            action,
            "pulse",
            strength=strength,
            duration_ms=validate_duration_ms(duration_ms),
        )

    def _action(
        self,
        action: str,
        kind: str,
        *,
        strength: float,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        name = validate_action_name(action)
        if name not in self._allowed_actions:
            raise AndroidSemanticDriverError(f"action is not allowed by target: {name}")
        payload: dict[str, Any] = {
            "op": "action",
            "name": name,
            "kind": kind,
            "strength": validate_strength(strength),
        }
        if duration_ms is not None:
            payload["durationMs"] = duration_ms
        return self._request(payload)

    def _request(
        self,
        payload: dict[str, Any],
        *,
        include_session: bool = True,
    ) -> dict[str, Any]:
        if self._socket is None:
            raise AndroidSemanticDriverError("driver client is not connected")
        body = dict(payload)
        operation = body.get("op")
        operation_name = (
            operation
            if isinstance(operation, str) and _ACTION_RE.fullmatch(operation) is not None
            else "request"
        )
        if include_session:
            if self._session is None:
                raise AndroidSemanticDriverError("driver session is not established")
            body["session"] = self._session
        encoded = (
            json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("ascii")
            + b"\n"
        )
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise AndroidSemanticDriverError("driver request exceeds message bound")
        self._socket.sendall(encoded)
        response = self._read_message()
        if response.get("schema") != SCHEMA:
            raise AndroidSemanticDriverError(
                f"driver {operation_name} response schema mismatch"
            )
        if response.get("ok") is not True:
            code = response.get("code", "driver_rejected_request")
            raise AndroidSemanticDriverError(
                f"driver {operation_name} request rejected: {code}"
            )
        return response

    def _read_message(self) -> dict[str, Any]:
        assert self._socket is not None
        while b"\n" not in self._buffer:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise AndroidSemanticDriverError("driver closed the connection")
            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_MESSAGE_BYTES:
                raise AndroidSemanticDriverError("driver response exceeds message bound")
        line, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AndroidSemanticDriverError("driver returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise AndroidSemanticDriverError("driver response must be a JSON object")
        return value
