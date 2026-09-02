from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import queue
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MAX_CONFIG_BYTES = 256 * 1024
MAX_HTTP_BYTES = 8 * 1024 * 1024
MAX_WORKER_LINE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class PlayerConfig:
    player_id: str
    display_name: str
    device_id: str


@dataclass(frozen=True)
class LobbyConfig:
    lobby_id: str
    visibility: str
    max_players: int
    region: str
    mode: str


@dataclass(frozen=True)
class TimeoutConfig:
    build_seconds: float
    startup_seconds: float
    command_seconds: float
    shutdown_seconds: float


@dataclass(frozen=True)
class CampaignConfig:
    schema_version: int
    campaign_id: str
    game_services_repo: Path
    game_id: str
    build_hash: str
    protocol_version: int
    players: tuple[PlayerConfig, ...]
    lobby: LobbyConfig
    timeouts: TimeoutConfig
    evidence_directory: Path
    build_before_run: bool


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_handle: Any
    log_path: Path


class JsonLineWorker:
    def __init__(
        self,
        *,
        name: str,
        command: Sequence[str],
        environment: Mapping[str, str],
        cwd: Path,
        stderr_path: Path,
        command_timeout: float,
    ) -> None:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.command_timeout = command_timeout
        self._stderr_handle = stderr_path.open("w", encoding="utf-8", newline="")
        self._process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError(f"{name}: failed to allocate worker pipes")
        self._events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending: dict[str, dict[str, Any]] = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.ready = self._wait_for_event("ready", command_timeout)
        self._next_id = 1

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def command(self, command: str, **payload: Any) -> dict[str, Any]:
        if not self.alive:
            raise RuntimeError(f"{self.name}: worker exited with {self._process.returncode}")
        request_id = f"{self.name}-{self._next_id}"
        self._next_id += 1
        message = {"id": request_id, "command": command, **payload}
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        assert self._process.stdin is not None
        self._process.stdin.write(encoded + "\n")
        self._process.stdin.flush()
        deadline = time.monotonic() + self.command_timeout
        while time.monotonic() < deadline:
            cached = self._pending.pop(request_id, None)
            if cached is not None:
                return cached
            remaining = max(0.01, deadline - time.monotonic())
            try:
                event = self._events.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"{self.name}: command {command} timed out") from exc
            event_id = event.get("id")
            if event_id == request_id:
                return event
            if isinstance(event_id, (str, int)):
                self._pending[str(event_id)] = event
            elif event.get("event") == "fatal":
                raise RuntimeError(f"{self.name}: {event.get('error', 'fatal worker error')}")
        raise TimeoutError(f"{self.name}: command {command} timed out")

    def stop(self, timeout: float) -> None:
        if self.alive:
            try:
                self.command_timeout = min(self.command_timeout, max(0.5, timeout))
                self.command("exit")
            except Exception:
                pass
        stop_process_tree(self._process, timeout)
        self._stderr_handle.close()

    def _wait_for_event(self, name: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(f"{self.name}: exited before {name} with {self._process.returncode}")
            try:
                event = self._events.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError(f"{self.name}: did not emit {name}") from exc
            if event.get("event") == name:
                return event
            if event.get("event") == "fatal":
                raise RuntimeError(f"{self.name}: {event.get('error', 'fatal worker error')}")
        raise TimeoutError(f"{self.name}: did not emit {name}")

    def _read_loop(self) -> None:
        assert self._process.stdout is not None
        for raw_line in self._process.stdout:
            if len(raw_line.encode("utf-8", errors="replace")) > MAX_WORKER_LINE_BYTES:
                self._events.put({"event": "fatal", "error": "worker_output_line_too_large"})
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError:
                self._events.put({"event": "fatal", "error": "worker_output_invalid_json"})
                continue
            if not isinstance(value, dict):
                self._events.put({"event": "fatal", "error": "worker_output_not_object"})
                continue
            self._events.put(value)


def parse_campaign_config(value: object, *, base_directory: Path) -> CampaignConfig:
    data = require_object(value, "campaign")
    exact_keys(
        data,
        {
            "schemaVersion",
            "campaignId",
            "gameServicesRepo",
            "gameId",
            "buildHash",
            "protocolVersion",
            "players",
            "lobby",
            "timeouts",
            "evidenceDirectory",
            "buildBeforeRun",
        },
        "campaign",
    )
    schema_version = require_int(data, "schemaVersion", 1, 1)
    campaign_id = require_identifier(data, "campaignId", 96)
    repo = resolve_path(base_directory, require_string(data, "gameServicesRepo", 32_768))
    game_id = require_game_id(data, "gameId")
    build_hash = require_pattern_string(
        data,
        "buildHash",
        8,
        128,
        lambda text: all(character.isalnum() or character in "._:+-" for character in text),
    )
    protocol_version = require_int(data, "protocolVersion", 1, 1_000_000)
    player_values = require_list(data, "players", 2, 16)
    players: list[PlayerConfig] = []
    player_ids: set[str] = set()
    device_ids: set[str] = set()
    for index, raw_player in enumerate(player_values):
        player = require_object(raw_player, f"players[{index}]")
        exact_keys(player, {"playerId", "displayName", "deviceId"}, f"players[{index}]")
        player_id = require_identifier(player, "playerId", 96)
        device_id = require_identifier(player, "deviceId", 128)
        if player_id in player_ids:
            raise ValueError(f"duplicate playerId: {player_id}")
        if device_id in device_ids:
            raise ValueError(f"duplicate deviceId: {device_id}")
        player_ids.add(player_id)
        device_ids.add(device_id)
        players.append(
            PlayerConfig(
                player_id=player_id,
                display_name=require_string(player, "displayName", 96),
                device_id=device_id,
            )
        )

    lobby_data = require_object(data.get("lobby"), "lobby")
    exact_keys(lobby_data, {"lobbyId", "visibility", "maxPlayers", "region", "mode"}, "lobby")
    visibility = require_string(lobby_data, "visibility", 32)
    if visibility not in {"public", "friends", "invite", "private", "lan"}:
        raise ValueError("lobby.visibility is invalid")
    lobby = LobbyConfig(
        lobby_id=require_identifier(lobby_data, "lobbyId", 96),
        visibility=visibility,
        max_players=require_int(lobby_data, "maxPlayers", len(players), 4096),
        region=require_string(lobby_data, "region", 64),
        mode=require_string(lobby_data, "mode", 96),
    )

    timeout_data = require_object(data.get("timeouts", {}), "timeouts")
    exact_keys(timeout_data, {"buildSeconds", "startupSeconds", "commandSeconds", "shutdownSeconds"}, "timeouts")
    timeouts = TimeoutConfig(
        build_seconds=optional_number(timeout_data, "buildSeconds", 1, 1800, 300),
        startup_seconds=optional_number(timeout_data, "startupSeconds", 1, 300, 30),
        command_seconds=optional_number(timeout_data, "commandSeconds", 0.5, 300, 15),
        shutdown_seconds=optional_number(timeout_data, "shutdownSeconds", 0.5, 60, 5),
    )
    evidence_directory = resolve_path(
        base_directory,
        require_string(data, "evidenceDirectory", 32_768),
    )
    build_before_run = data.get("buildBeforeRun", True)
    if not isinstance(build_before_run, bool):
        raise ValueError("buildBeforeRun must be boolean")
    return CampaignConfig(
        schema_version=schema_version,
        campaign_id=campaign_id,
        game_services_repo=repo,
        game_id=game_id,
        build_hash=build_hash,
        protocol_version=protocol_version,
        players=tuple(players),
        lobby=lobby,
        timeouts=timeouts,
        evidence_directory=evidence_directory,
        build_before_run=build_before_run,
    )


def run_campaign(config: CampaignConfig) -> Path:
    started_at = epoch_ms()
    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{secrets.token_hex(4)}"
    evidence_root = config.evidence_directory / f"{config.campaign_id}-{run_id}"
    logs_directory = evidence_root / "logs"
    secrets_directory = evidence_root / ".secrets"
    logs_directory.mkdir(parents=True, exist_ok=False)
    secrets_directory.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_root / "evidence.json"
    processes: list[ManagedProcess] = []
    workers: dict[str, JsonLineWorker] = {}
    steps: list[dict[str, Any]] = []
    status = "failed"
    error_message: str | None = None
    ports = {
        "backend": free_port(),
        "identity": free_port(),
        "gateway": free_port(),
    }
    if len(set(ports.values())) != len(ports):
        raise RuntimeError("failed to allocate distinct campaign ports")
    secret_values = campaign_secrets()

    try:
        validate_game_services_repo(config.game_services_repo)
        revision = git_revision(config.game_services_repo)
        if config.build_before_run:
            run_logged_command(
                [npm_executable(), "run", "build"],
                cwd=config.game_services_repo,
                log_path=logs_directory / "build.log",
                timeout=config.timeouts.build_seconds,
            )
        validate_compiled_entrypoints(config.game_services_repo)

        backend_url = f"http://127.0.0.1:{ports['backend']}"
        identity_url = f"http://127.0.0.1:{ports['identity']}"
        gateway_url = f"http://127.0.0.1:{ports['gateway']}"
        state_path = secrets_directory / "player-identity.evavo"

        backend_env = minimal_environment(
            {
                "EVAVO_GAME_SERVICES_HOST": "127.0.0.1",
                "EVAVO_GAME_SERVICES_PORT": str(ports["backend"]),
                "EVAVO_PLATFORM_HOST": "127.0.0.1",
                "EVAVO_PLATFORM_PORT": str(ports["backend"]),
                "EVAVO_GAME_SERVICES_ALLOWED_ORIGINS": "http://127.0.0.1",
                "EVAVO_GAME_SERVICES_ACCESS_TOKEN": secret_values["backend_access"],
                "EVAVO_GAME_SERVICES_ADMIN_TOKEN": secret_values["backend_admin"],
                "EVAVO_MATCH_RESULT_SECRET": secret_values["match_result"],
            }
        )
        backend = start_service(
            "platform-backend",
            [node_executable(), "dist/apps/platform-server/server.js"],
            config.game_services_repo,
            backend_env,
            logs_directory / "platform-backend.log",
        )
        processes.append(backend)
        wait_for_http(f"{backend_url}/health", backend, config.timeouts.startup_seconds)
        record_step(steps, "backend-health", True, {"status": 200})

        identity_env = minimal_environment(
            {
                "EVAVO_PLAYER_IDENTITY_HOST": "127.0.0.1",
                "EVAVO_PLAYER_IDENTITY_PORT": str(ports["identity"]),
                "EVAVO_PLAYER_SESSION_SECRET": secret_values["session"],
                "EVAVO_PLAYER_SESSION_ISSUER_TOKEN": secret_values["issuer"],
                "EVAVO_PLAYER_SESSION_ADMIN_TOKEN": secret_values["identity_admin"],
                "EVAVO_PLAYER_IDENTITY_STATE_PATH": str(state_path),
                "EVAVO_PLAYER_IDENTITY_STATE_KEY": secret_values["state_key"],
                "EVAVO_PLAYER_IDENTITY_CHALLENGE_MS": "30000",
                "EVAVO_PLAYER_IDENTITY_SESSION_MS": "600000",
                "EVAVO_PLAYER_IDENTITY_REFRESH_MS": "3600000",
            }
        )
        identity = start_service(
            "player-identity",
            [node_executable(), "dist/apps/player-identity-platform/server.js"],
            config.game_services_repo,
            identity_env,
            logs_directory / "player-identity.log",
        )
        processes.append(identity)
        wait_for_http(f"{identity_url}/health", identity, config.timeouts.startup_seconds)
        record_step(steps, "identity-health", True, {"status": 200})

        gateway_env = minimal_environment(
            {
                "EVAVO_AUTHENTICATED_GATEWAY_HOST": "127.0.0.1",
                "EVAVO_AUTHENTICATED_GATEWAY_PORT": str(ports["gateway"]),
                "EVAVO_PLATFORM_BACKEND_URL": backend_url,
                "EVAVO_PLAYER_IDENTITY_URL": identity_url,
                "EVAVO_PLAYER_SESSION_ISSUER_TOKEN": secret_values["issuer"],
                "EVAVO_PLATFORM_BACKEND_ACCESS_TOKEN": secret_values["backend_access"],
            }
        )
        gateway = start_service(
            "authenticated-gateway",
            [node_executable(), "dist/apps/authenticated-platform-gateway/server.js"],
            config.game_services_repo,
            gateway_env,
            logs_directory / "authenticated-gateway.log",
        )
        processes.append(gateway)
        wait_for_http(f"{gateway_url}/gateway-health", gateway, config.timeouts.startup_seconds)
        record_step(steps, "gateway-health", True, {"status": 200})

        for player in config.players:
            worker = start_worker(
                player=player,
                config=config,
                identity_url=identity_url,
                gateway_url=gateway_url,
                secrets_directory=secrets_directory,
                logs_directory=logs_directory,
            )
            workers[player.player_id] = worker
            public_key = require_string(worker.ready, "publicKeyPem", 32_768)
            register_player_and_device(
                identity_url=identity_url,
                admin_token=secret_values["identity_admin"],
                player=player,
                public_key_pem=public_key,
            )
            login = require_success(worker.command("login"), f"login {player.player_id}")
            record_step(steps, f"login:{player.player_id}", True, redact(login))

        owner = workers[config.players[0].player_id]
        guest = workers[config.players[1].player_id]
        create_response = require_worker_http(
            owner.command(
                "gateway",
                method="POST",
                path="/v1/lobbies",
                body={
                    "lobbyId": config.lobby.lobby_id,
                    "gameId": config.game_id,
                    "owner": {},
                    "visibility": config.lobby.visibility,
                    "maxPlayers": config.lobby.max_players,
                    "region": config.lobby.region,
                    "mode": config.lobby.mode,
                },
            ),
            expected_status=201,
            name="create lobby",
        )
        record_step(steps, "lobby-create", True, summarize_lobby(create_response.get("payload")))

        join_response = require_worker_http(
            guest.command(
                "gateway",
                method="POST",
                path=f"/v1/lobbies/{config.lobby.lobby_id}/join",
                body={},
            ),
            expected_status=200,
            name="join lobby",
        )
        assert_lobby_members(join_response.get("payload"), config.players)
        record_step(steps, "lobby-join", True, summarize_lobby(join_response.get("payload")))

        for player in config.players[:2]:
            ready_response = require_worker_http(
                workers[player.player_id].command(
                    "gateway",
                    method="POST",
                    path=f"/v1/lobbies/{config.lobby.lobby_id}/ready",
                    body={"ready": True},
                ),
                expected_status=200,
                name=f"ready {player.player_id}",
            )
            record_step(steps, f"lobby-ready:{player.player_id}", True, summarize_lobby(ready_response.get("payload")))

        converged = require_worker_http(
            owner.command(
                "gateway",
                method="GET",
                path=f"/v1/lobbies/{config.lobby.lobby_id}",
            ),
            expected_status=200,
            name="read converged lobby",
        )
        assert_lobby_members(converged.get("payload"), config.players, require_ready=True)
        record_step(steps, "lobby-converged", True, summarize_lobby(converged.get("payload")))

        refreshed = require_success(owner.command("refresh"), "refresh owner")
        if refreshed.get("tokenChanged") is not True:
            raise AssertionError("owner refresh did not rotate the token")
        record_step(steps, "refresh-rotated", True, redact(refreshed))

        guest_config = config.players[1]
        guest.stop(config.timeouts.shutdown_seconds)
        del workers[guest_config.player_id]
        restarted_guest = start_worker(
            player=guest_config,
            config=config,
            identity_url=identity_url,
            gateway_url=gateway_url,
            secrets_directory=secrets_directory,
            logs_directory=logs_directory,
            suffix="restart",
        )
        workers[guest_config.player_id] = restarted_guest
        if restarted_guest.ready.get("credentialsLoaded") is not True:
            raise AssertionError("restarted client did not load isolated credentials")
        after_restart = require_worker_http(
            restarted_guest.command(
                "gateway",
                method="GET",
                path=f"/v1/lobbies/{config.lobby.lobby_id}",
            ),
            expected_status=200,
            name="restarted client reads lobby",
        )
        assert_lobby_members(after_restart.get("payload"), config.players, require_ready=True)
        record_step(steps, "client-restart-reconnect", True, summarize_lobby(after_restart.get("payload")))

        spoof = require_worker_http(
            restarted_guest.command(
                "gateway",
                method="POST",
                path=f"/v1/lobbies/{config.lobby.lobby_id}/ready",
                body={
                    "playerId": config.players[0].player_id,
                    "ready": False,
                },
            ),
            expected_status=403,
            name="spoofed ready request",
        )
        record_step(steps, "actor-spoof-rejected", True, {"status": spoof["status"]})

        replay = require_success(owner.command("replay_previous_refresh"), "replay old refresh")
        if replay.get("rejected") is not True or replay.get("credentialsCleared") is not True:
            raise AssertionError("refresh replay did not revoke and clear the family")
        record_step(steps, "refresh-replay-revoked", True, redact(replay))
        missing = owner.command("me")
        if missing.get("ok") is not False or "credentials_missing" not in str(missing.get("error", "")):
            raise AssertionError("client retained credentials after refresh replay")

        relogin = require_success(owner.command("login"), "owner relogin")
        record_step(steps, "device-relogin-after-replay", True, redact(relogin))
        final_lobby = require_worker_http(
            owner.command(
                "gateway",
                method="GET",
                path=f"/v1/lobbies/{config.lobby.lobby_id}",
            ),
            expected_status=200,
            name="owner final lobby read",
        )
        assert_lobby_members(final_lobby.get("payload"), config.players, require_ready=True)
        record_step(steps, "final-lobby-proof", True, summarize_lobby(final_lobby.get("payload")))

        status = "passed"
    except Exception as error:  # noqa: BLE001 - evidence must retain bounded campaign failure.
        error_message = bounded_error(error)
        record_step(steps, "campaign-failure", False, {"error": error_message})
    finally:
        for worker in reversed(list(workers.values())):
            try:
                worker.stop(config.timeouts.shutdown_seconds)
            except Exception as error:  # noqa: BLE001
                record_step(steps, f"cleanup-worker:{worker.name}", False, {"error": bounded_error(error)})
        for managed in reversed(processes):
            try:
                stop_managed_process(managed, config.timeouts.shutdown_seconds)
            except Exception as error:  # noqa: BLE001
                record_step(steps, f"cleanup-service:{managed.name}", False, {"error": bounded_error(error)})
        shutil.rmtree(secrets_directory, ignore_errors=True)
        ended_at = epoch_ms()
        revision = safe_git_revision(config.game_services_repo)
        evidence = {
            "schemaVersion": 1,
            "campaignId": config.campaign_id,
            "runId": run_id,
            "status": status,
            "startedAt": started_at,
            "endedAt": ended_at,
            "durationMs": max(0, ended_at - started_at),
            "gameServicesRepo": str(config.game_services_repo),
            "gameServicesRevision": revision,
            "gameId": config.game_id,
            "buildHash": config.build_hash,
            "protocolVersion": config.protocol_version,
            "players": [
                {
                    "playerId": player.player_id,
                    "displayName": player.display_name,
                    "deviceId": player.device_id,
                }
                for player in config.players
            ],
            "lobbyId": config.lobby.lobby_id,
            "ports": ports,
            "steps": steps,
            "logs": sorted(str(path.relative_to(evidence_root)) for path in logs_directory.glob("*.log")),
            "secretDirectoryRemoved": not secrets_directory.exists(),
            "secretsRedacted": True,
            **({} if error_message is None else {"error": error_message}),
        }
        write_json_atomic(evidence_path, evidence)
    if status != "passed":
        raise RuntimeError(f"campaign failed; evidence: {evidence_path}: {error_message}")
    return evidence_path


def start_worker(
    *,
    player: PlayerConfig,
    config: CampaignConfig,
    identity_url: str,
    gateway_url: str,
    secrets_directory: Path,
    logs_directory: Path,
    suffix: str = "initial",
) -> JsonLineWorker:
    worker_script = Path(__file__).with_name("evavo_authenticated_client_worker.mjs")
    if not worker_script.is_file():
        raise FileNotFoundError(f"client worker is missing: {worker_script}")
    player_directory = secrets_directory / player.player_id
    environment = minimal_environment(
        {
            "EVAVO_TEST_PLAYER_ID": player.player_id,
            "EVAVO_TEST_DISPLAY_NAME": player.display_name,
            "EVAVO_TEST_DEVICE_ID": player.device_id,
            "EVAVO_TEST_GAME_ID": config.game_id,
            "EVAVO_TEST_BUILD_HASH": config.build_hash,
            "EVAVO_TEST_PROTOCOL_VERSION": str(config.protocol_version),
            "EVAVO_TEST_IDENTITY_URL": identity_url,
            "EVAVO_TEST_GATEWAY_URL": gateway_url,
            "EVAVO_TEST_PRIVATE_KEY_PATH": str(player_directory / "device-private.pem"),
            "EVAVO_TEST_CREDENTIAL_PATH": str(player_directory / "credentials.json"),
            "EVAVO_TEST_HTTP_TIMEOUT_MS": str(int(config.timeouts.command_seconds * 1000)),
        }
    )
    return JsonLineWorker(
        name=f"{player.player_id}-{suffix}",
        command=[node_executable(), str(worker_script)],
        environment=environment,
        cwd=Path(__file__).resolve().parents[1],
        stderr_path=logs_directory / f"client-{player.player_id}-{suffix}.log",
        command_timeout=config.timeouts.command_seconds,
    )


def register_player_and_device(
    *,
    identity_url: str,
    admin_token: str,
    player: PlayerConfig,
    public_key_pem: str,
) -> None:
    account = http_json(
        "POST",
        f"{identity_url}/v1/admin/accounts",
        {
            "playerId": player.player_id,
            "displayName": player.display_name,
            "metadata": {"source": "godot-game-test-lab"},
        },
        token=admin_token,
    )
    if account[0] not in {200, 201}:
        raise RuntimeError(f"account registration failed for {player.player_id}: {account[0]}")
    device = http_json(
        "POST",
        f"{identity_url}/v1/admin/accounts/{urllib.parse.quote(player.player_id, safe='')}/devices",
        {
            "deviceId": player.device_id,
            "label": f"Test Lab {player.display_name}",
            "publicKeyPem": public_key_pem,
            "metadata": {"ephemeral": True},
        },
        token=admin_token,
    )
    if device[0] not in {200, 201}:
        raise RuntimeError(f"device registration failed for {player.player_id}: {device[0]}")


def start_service(
    name: str,
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8", newline="")
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    return ManagedProcess(name=name, process=process, log_handle=log_handle, log_path=log_path)


def wait_for_http(url: str, managed: ManagedProcess, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        if managed.process.poll() is not None:
            raise RuntimeError(f"{managed.name} exited during startup with {managed.process.returncode}")
        try:
            status, payload = http_json("GET", url, timeout=min(2.0, timeout))
            if 200 <= status < 300 and isinstance(payload, dict) and payload.get("ok") is True:
                return
            last_error = f"status={status} payload={redact(payload)}"
        except Exception as error:  # noqa: BLE001
            last_error = bounded_error(error)
        time.sleep(0.1)
    raise TimeoutError(f"{managed.name} health timed out: {last_error}")


def stop_managed_process(managed: ManagedProcess, timeout: float) -> None:
    try:
        stop_process_tree(managed.process, timeout)
    finally:
        managed.log_handle.close()


def stop_process_tree(process: subprocess.Popen[Any], timeout: float) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=max(1.0, timeout),
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=max(1.0, timeout))


def run_logged_command(
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout: float,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=minimal_environment({}),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(command)}")


def validate_game_services_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        raise FileNotFoundError(f"gameServicesRepo is not a Git checkout: {repo}")
    if not (repo / "package.json").is_file():
        raise FileNotFoundError(f"gameServicesRepo has no package.json: {repo}")


def validate_compiled_entrypoints(repo: Path) -> None:
    required = [
        "dist/apps/platform-server/server.js",
        "dist/apps/player-identity-platform/server.js",
        "dist/apps/authenticated-platform-gateway/server.js",
    ]
    missing = [path for path in required if not (repo / path).is_file()]
    if missing:
        raise FileNotFoundError(f"compiled EVAVO entrypoints are missing: {', '.join(missing)}")


def assert_lobby_members(
    value: object,
    players: Sequence[PlayerConfig],
    *,
    require_ready: bool = False,
) -> None:
    lobby = require_object(value, "lobby response")
    members = lobby.get("members")
    if not isinstance(members, list):
        raise AssertionError("lobby response has no members list")
    expected = {player.player_id for player in players[:2]}
    actual: set[str] = set()
    for raw_member in members:
        member = require_object(raw_member, "lobby member")
        identity = require_object(member.get("player"), "lobby member player")
        member_id = require_string(identity, "playerId", 96)
        actual.add(member_id)
        if require_ready and member_id in expected and member.get("ready") is not True:
            raise AssertionError(f"lobby member {member_id} is not ready")
    if not expected.issubset(actual):
        raise AssertionError(f"lobby members did not converge: expected {sorted(expected)}, actual {sorted(actual)}")


def summarize_lobby(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"valid": False}
    members = value.get("members")
    summary: dict[str, Any] = {
        "lobbyId": value.get("lobbyId"),
        "gameId": value.get("gameId"),
        "phase": value.get("phase"),
        "memberCount": len(members) if isinstance(members, list) else None,
    }
    if isinstance(members, list):
        summary["members"] = [
            {
                "playerId": ((member.get("player") or {}).get("playerId") if isinstance(member, dict) and isinstance(member.get("player"), dict) else None),
                "ready": member.get("ready") if isinstance(member, dict) else None,
            }
            for member in members[:32]
        ]
    return summary


def require_success(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if value.get("ok") is not True:
        raise AssertionError(f"{name} failed: {value.get('error')}")
    result = value.get("result")
    if not isinstance(result, dict):
        raise AssertionError(f"{name} returned no result object")
    return result


def require_worker_http(
    value: Mapping[str, Any],
    *,
    expected_status: int,
    name: str,
) -> dict[str, Any]:
    result = require_success(value, name)
    status = result.get("status")
    if status != expected_status:
        raise AssertionError(f"{name}: expected HTTP {expected_status}, received {status}: {redact(result.get('payload'))}")
    return result


def record_step(
    steps: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: Mapping[str, Any],
) -> None:
    steps.append(
        {
            "sequence": len(steps) + 1,
            "name": name,
            "passed": passed,
            "at": epoch_ms(),
            "detail": redact(dict(detail)),
        }
    )


def campaign_secrets() -> dict[str, str]:
    values = {
        "session": secrets.token_urlsafe(48),
        "issuer": secrets.token_urlsafe(48),
        "identity_admin": secrets.token_urlsafe(48),
        "state_key": "base64:" + base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        "backend_access": secrets.token_urlsafe(48),
        "backend_admin": secrets.token_urlsafe(48),
        "match_result": secrets.token_urlsafe(48),
    }
    plain = list(values.values())
    if len(set(plain)) != len(plain):
        raise RuntimeError("random secret collision")
    return values


def minimal_environment(additions: Mapping[str, str]) -> dict[str, str]:
    retained = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "TMPDIR",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMDATA",
            "LANG",
            "LC_ALL",
            "NODE_OPTIONS",
        }
    }
    retained.update({str(key): str(value) for key, value in additions.items()})
    return retained


def http_json(
    method: str,
    url: str,
    body: object | None = None,
    *,
    token: str | None = None,
    timeout: float = 5.0,
) -> tuple[int, object | None]:
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = read_http_payload(response, MAX_HTTP_BYTES)
            return response.status, payload
    except urllib.error.HTTPError as error:
        payload = read_http_payload(error, MAX_HTTP_BYTES)
        return error.code, payload


def read_http_payload(response: Any, maximum_bytes: int) -> object | None:
    declared = response.headers.get("Content-Length") if response.headers is not None else None
    if declared is not None and int(declared) > maximum_bytes:
        raise ValueError("HTTP response exceeds configured size limit")
    raw = response.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError("HTTP response exceeds configured size limit")
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw[:512].decode("utf-8", errors="replace")}


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def load_config(path: Path) -> CampaignConfig:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("campaign configuration exceeds the size limit")
    value = json.loads(raw.decode("utf-8"))
    return parse_campaign_config(value, base_directory=path.parent.resolve())


def redact(value: object, depth: int = 0) -> object:
    if depth > 16:
        return "[depth-redacted]"
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for key, item in value.items():
            if any(fragment in key.lower() for fragment in ("token", "secret", "signature", "privatekey", "private_key", "authorization")):
                output[str(key)] = "[redacted]"
            else:
                output[str(key)] = redact(item, depth + 1)
        return output
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:1_000]]
    if isinstance(value, tuple):
        return [redact(item, depth + 1) for item in value[:1_000]]
    if isinstance(value, str) and len(value) >= 32 and all(character.isalnum() or character in "_-+=:/" for character in value):
        return "[redacted-long-value]"
    return value


def git_revision(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"unable to read game-services revision: {completed.stderr.strip()}")
    revision = completed.stdout.strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise RuntimeError("game-services revision is invalid")
    return revision


def safe_git_revision(repo: Path) -> str | None:
    try:
        return git_revision(repo)
    except Exception:
        return None


def node_executable() -> str:
    executable = shutil.which("node")
    if executable is None:
        raise FileNotFoundError("Node.js is required")
    return executable


def npm_executable() -> str:
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if executable is None:
        raise FileNotFoundError("npm is required")
    return executable


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def bounded_error(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}"
    return message[:2_000]


def resolve_path(base: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def require_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def exact_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{name} contains unknown keys: {', '.join(unknown)}")


def require_list(value: Mapping[str, Any], key: str, minimum: int, maximum: int) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list) or not minimum <= len(item) <= maximum:
        raise ValueError(f"{key} must contain {minimum} to {maximum} entries")
    return item


def require_string(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string")
    normalized = " ".join(item.strip().split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{key} must contain 1 to {maximum} characters")
    return normalized


def require_identifier(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = require_string(value, key, maximum)
    if not item[0].isalnum() or any(not (character.isalnum() or character in "._:-") for character in item):
        raise ValueError(f"{key} is invalid")
    return item


def require_game_id(value: Mapping[str, Any], key: str) -> str:
    item = require_string(value, key, 80)
    if not item[0].islower() and not item[0].isdigit():
        raise ValueError(f"{key} is invalid")
    if any(not (character.islower() or character.isdigit() or character == "-") for character in item):
        raise ValueError(f"{key} is invalid")
    return item


def require_pattern_string(
    value: Mapping[str, Any],
    key: str,
    minimum: int,
    maximum: int,
    predicate: Any,
) -> str:
    item = require_string(value, key, maximum)
    if len(item) < minimum or not predicate(item):
        raise ValueError(f"{key} is invalid")
    return item


def require_int(value: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or not minimum <= item <= maximum:
        raise ValueError(f"{key} must be an integer from {minimum} to {maximum}")
    return item


def optional_number(
    value: Mapping[str, Any],
    key: str,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    item = value.get(key, default)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not minimum <= float(item) <= maximum:
        raise ValueError(f"{key} must be from {minimum} to {maximum}")
    return float(item)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the EVAVO authenticated multi-client stack campaign.",
    )
    parser.add_argument("--config", required=True, type=Path, help="Campaign JSON path")
    parser.add_argument("--no-build", action="store_true", help="Use existing compiled game-services outputs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        config = load_config(arguments.config.resolve())
        if arguments.no_build:
            config = CampaignConfig(
                **{**config.__dict__, "build_before_run": False},
            )
        evidence = run_campaign(config)
        print(json.dumps({"ok": True, "evidence": str(evidence)}, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": bounded_error(error)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
