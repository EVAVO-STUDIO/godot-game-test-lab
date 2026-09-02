from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence


MAX_CONFIG_BYTES = 256 * 1024


def load_base() -> ModuleType:
    path = Path(__file__).with_name("run_evavo_authenticated_stack_campaign.py")
    spec = importlib.util.spec_from_file_location(
        "evavo_authenticated_stack_campaign_base",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load authenticated campaign base: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


def run_realtime_campaign(config: Any) -> Path:
    started_at = base.epoch_ms()
    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{secrets.token_hex(4)}"
    campaign_id = f"{config.campaign_id}-realtime-admission"
    evidence_root = config.evidence_directory / f"{campaign_id}-{run_id}"
    logs_directory = evidence_root / "logs"
    secrets_directory = evidence_root / ".secrets"
    logs_directory.mkdir(parents=True, exist_ok=False)
    secrets_directory.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_root / "evidence.json"

    processes: list[Any] = []
    workers: dict[str, Any] = {}
    admission_workers: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    status = "failed"
    error_message: str | None = None
    lease_token: str | None = None

    ports = {
        "backend": base.free_port(),
        "identity": base.free_port(),
        "gateway": base.free_port(),
        "broker": base.free_port(),
        "gameplay": base.free_port(),
    }
    if len(set(ports.values())) != len(ports):
        raise RuntimeError("failed to allocate distinct campaign ports")

    secret_values = base.campaign_secrets()
    secret_values.update(
        {
            "target_service": secrets.token_urlsafe(48),
            "connection_grant": secrets.token_urlsafe(48),
        }
    )
    if len(set(secret_values.values())) != len(secret_values):
        raise RuntimeError("random campaign secret collision")

    try:
        base.validate_game_services_repo(config.game_services_repo)
        revision = base.git_revision(config.game_services_repo)
        if config.build_before_run:
            base.run_logged_command(
                [base.npm_executable(), "run", "build"],
                cwd=config.game_services_repo,
                log_path=logs_directory / "build.log",
                timeout=config.timeouts.build_seconds,
            )
        base.validate_compiled_entrypoints(config.game_services_repo)
        broker_entrypoint = (
            config.game_services_repo
            / "dist"
            / "apps"
            / "player-connection-broker"
            / "server.js"
        )
        if not broker_entrypoint.is_file():
            raise FileNotFoundError(
                f"compiled player connection broker is missing: {broker_entrypoint}"
            )

        backend_url = f"http://127.0.0.1:{ports['backend']}"
        identity_url = f"http://127.0.0.1:{ports['identity']}"
        gateway_url = f"http://127.0.0.1:{ports['gateway']}"
        broker_url = f"http://127.0.0.1:{ports['broker']}"
        gameplay_url = f"ws://127.0.0.1:{ports['gameplay']}"
        state_path = secrets_directory / "player-identity.evavo"

        backend = base.start_service(
            "platform-backend",
            [base.node_executable(), "dist/apps/platform-server/server.js"],
            config.game_services_repo,
            base.minimal_environment(
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
            ),
            logs_directory / "platform-backend.log",
        )
        processes.append(backend)
        base.wait_for_http(
            f"{backend_url}/health",
            backend,
            config.timeouts.startup_seconds,
        )
        base.record_step(steps, "backend-health", True, {"status": 200})

        identity = base.start_service(
            "player-identity",
            [base.node_executable(), "dist/apps/player-identity-platform/server.js"],
            config.game_services_repo,
            base.minimal_environment(
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
            ),
            logs_directory / "player-identity.log",
        )
        processes.append(identity)
        base.wait_for_http(
            f"{identity_url}/health",
            identity,
            config.timeouts.startup_seconds,
        )
        base.record_step(steps, "identity-health", True, {"status": 200})

        gateway = base.start_service(
            "authenticated-gateway",
            [base.node_executable(), "dist/apps/authenticated-platform-gateway/server.js"],
            config.game_services_repo,
            base.minimal_environment(
                {
                    "EVAVO_AUTHENTICATED_GATEWAY_HOST": "127.0.0.1",
                    "EVAVO_AUTHENTICATED_GATEWAY_PORT": str(ports["gateway"]),
                    "EVAVO_PLATFORM_BACKEND_URL": backend_url,
                    "EVAVO_PLAYER_IDENTITY_URL": identity_url,
                    "EVAVO_PLAYER_SESSION_ISSUER_TOKEN": secret_values["issuer"],
                    "EVAVO_PLATFORM_BACKEND_ACCESS_TOKEN": secret_values["backend_access"],
                }
            ),
            logs_directory / "authenticated-gateway.log",
        )
        processes.append(gateway)
        base.wait_for_http(
            f"{gateway_url}/gateway-health",
            gateway,
            config.timeouts.startup_seconds,
        )
        base.record_step(steps, "gateway-health", True, {"status": 200})

        broker = base.start_service(
            "player-connection-broker",
            [base.node_executable(), "dist/apps/player-connection-broker/server.js"],
            config.game_services_repo,
            base.minimal_environment(
                {
                    "EVAVO_PLAYER_CONNECTION_BROKER_HOST": "127.0.0.1",
                    "EVAVO_PLAYER_CONNECTION_BROKER_PORT": str(ports["broker"]),
                    "EVAVO_PLAYER_IDENTITY_URL": identity_url,
                    "EVAVO_PLAYER_SESSION_ISSUER_TOKEN": secret_values["issuer"],
                    "EVAVO_CONNECTION_TARGET_SERVICE_TOKEN": secret_values["target_service"],
                    "EVAVO_CONNECTION_GRANT_SECRET": secret_values["connection_grant"],
                    "EVAVO_PLAYER_CONNECTION_BROKER_PLAYER_REQUESTS_PER_MINUTE": "1000",
                    "EVAVO_PLAYER_CONNECTION_BROKER_SERVICE_REQUESTS_PER_MINUTE": "1000",
                }
            ),
            logs_directory / "player-connection-broker.log",
        )
        processes.append(broker)
        base.wait_for_http(
            f"{broker_url}/health",
            broker,
            config.timeouts.startup_seconds,
        )
        base.record_step(steps, "broker-health", True, {"status": 200})

        for player in config.players:
            worker = start_worker(
                player=player,
                config=config,
                identity_url=identity_url,
                request_base_url=gateway_url,
                secrets_directory=secrets_directory,
                logs_directory=logs_directory,
                suffix="platform",
            )
            workers[player.player_id] = worker
            public_key = base.require_string(
                worker.ready,
                "publicKeyPem",
                32_768,
            )
            base.register_player_and_device(
                identity_url=identity_url,
                admin_token=secret_values["identity_admin"],
                player=player,
                public_key_pem=public_key,
            )
            login = base.require_success(
                worker.command("login"),
                f"login {player.player_id}",
            )
            base.record_step(
                steps,
                f"login:{player.player_id}",
                True,
                base.redact(login),
            )

        owner_config = config.players[0]
        guest_config = config.players[1]
        owner = workers[owner_config.player_id]
        guest = workers[guest_config.player_id]

        created = base.require_worker_http(
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
        base.record_step(
            steps,
            "lobby-create",
            True,
            base.summarize_lobby(created.get("payload")),
        )

        joined = base.require_worker_http(
            guest.command(
                "gateway",
                method="POST",
                path=f"/v1/lobbies/{config.lobby.lobby_id}/join",
                body={},
            ),
            expected_status=200,
            name="join lobby",
        )
        base.assert_lobby_members(joined.get("payload"), config.players)

        for player in config.players[:2]:
            base.require_worker_http(
                workers[player.player_id].command(
                    "gateway",
                    method="POST",
                    path=f"/v1/lobbies/{config.lobby.lobby_id}/ready",
                    body={"ready": True},
                ),
                expected_status=200,
                name=f"ready {player.player_id}",
            )

        converged = base.require_worker_http(
            owner.command(
                "gateway",
                method="GET",
                path=f"/v1/lobbies/{config.lobby.lobby_id}",
            ),
            expected_status=200,
            name="read converged lobby",
        )
        base.assert_lobby_members(
            converged.get("payload"),
            config.players,
            require_ready=True,
        )
        base.record_step(
            steps,
            "lobby-converged",
            True,
            base.summarize_lobby(converged.get("payload")),
        )

        target_status, target_registration = base.http_json(
            "POST",
            f"{broker_url}/v1/targets",
            {
                "resourceKind": "lobby",
                "resourceId": config.lobby.lobby_id,
                "gameId": config.game_id,
                "protocolVersion": config.protocol_version,
                "buildHash": config.build_hash,
                "endpoint": {
                    "transport": "websocket",
                    "address": gameplay_url,
                    "secure": False,
                    "roomId": config.lobby.lobby_id,
                    "metadata": {"region": config.lobby.region},
                },
                "topology": "websocket-room",
                "accepting": True,
                "expiresAt": base.epoch_ms() + 5 * 60_000,
                "participants": [
                    {
                        "playerId": owner_config.player_id,
                        "roles": ["host", "player"],
                        "metadata": {"team": "owner"},
                    },
                    {
                        "playerId": guest_config.player_id,
                        "roles": ["player"],
                        "metadata": {"team": "guest"},
                    },
                ],
                "metadata": {
                    "region": config.lobby.region,
                    "mode": config.lobby.mode,
                    "testLab": True,
                },
                "leaseMs": 120_000,
            },
            token=secret_values["target_service"],
        )
        if target_status != 201 or not isinstance(target_registration, dict):
            raise AssertionError(
                f"target registration failed: {target_status}: {base.redact(target_registration)}"
            )
        lease_token_value = target_registration.get("leaseToken")
        if not isinstance(lease_token_value, str) or not lease_token_value:
            raise AssertionError("target registration returned no lease token")
        lease_token = lease_token_value
        base.record_step(
            steps,
            "canonical-target-registered",
            True,
            {
                "resourceKind": "lobby",
                "resourceId": config.lobby.lobby_id,
                "revision": (target_registration.get("target") or {}).get("revision"),
                "endpoint": gameplay_url,
            },
        )

        for player in config.players[:2]:
            admission = start_worker(
                player=player,
                config=config,
                identity_url=identity_url,
                request_base_url=broker_url,
                secrets_directory=secrets_directory,
                logs_directory=logs_directory,
                suffix="admission",
            )
            if admission.ready.get("credentialsLoaded") is not True:
                raise AssertionError(
                    f"admission worker did not load credentials for {player.player_id}"
                )
            admission_workers[player.player_id] = admission

        grants: dict[str, dict[str, Any]] = {}
        for player, role in (
            (owner_config, "host"),
            (guest_config, "player"),
        ):
            response = base.require_worker_http(
                admission_workers[player.player_id].command(
                    "gateway",
                    method="POST",
                    path="/v1/player/connection-grants",
                    body={
                        "requestId": f"grant-{player.player_id}",
                        "resourceKind": "lobby",
                        "resourceId": config.lobby.lobby_id,
                        "role": role,
                        "usage": "reconnectable",
                        "maximumUses": 2,
                        "lifetimeMs": 60_000,
                    },
                ),
                expected_status=201,
                name=f"connection grant {player.player_id}",
            )
            payload = require_dict(response.get("payload"), "grant receipt")
            claims = require_dict(
                require_dict(payload.get("grant"), "grant").get("claims"),
                "grant claims",
            )
            if claims.get("playerId") != player.player_id:
                raise AssertionError("connection grant player binding mismatch")
            if claims.get("resourceId") != config.lobby.lobby_id:
                raise AssertionError("connection grant resource binding mismatch")
            endpoint = require_dict(claims.get("endpoint"), "grant endpoint")
            if endpoint.get("address") != gameplay_url:
                raise AssertionError("connection grant endpoint was not canonical")
            if claims.get("role") != role:
                raise AssertionError("connection grant role binding mismatch")
            grants[player.player_id] = {
                "playerId": claims.get("playerId"),
                "role": claims.get("role"),
                "resourceKind": claims.get("resourceKind"),
                "resourceId": claims.get("resourceId"),
                "transport": endpoint.get("transport"),
                "address": endpoint.get("address"),
                "usage": claims.get("usage"),
                "maximumUses": claims.get("maximumUses"),
            }
        base.record_step(
            steps,
            "player-bound-grants-issued",
            True,
            {"grants": grants},
        )

        repeated = base.require_worker_http(
            admission_workers[owner_config.player_id].command(
                "gateway",
                method="POST",
                path="/v1/player/connection-grants",
                body={
                    "requestId": f"grant-{owner_config.player_id}",
                    "resourceKind": "lobby",
                    "resourceId": config.lobby.lobby_id,
                    "role": "host",
                    "usage": "reconnectable",
                    "maximumUses": 2,
                    "lifetimeMs": 60_000,
                },
            ),
            expected_status=200,
            name="idempotent grant replay",
        )
        if require_dict(repeated.get("payload"), "repeat receipt").get("reused") is not True:
            raise AssertionError("connection grant was not idempotently reused")
        base.record_step(
            steps,
            "grant-idempotency",
            True,
            {"reused": True},
        )

        base.require_worker_http(
            admission_workers[guest_config.player_id].command(
                "gateway",
                method="POST",
                path="/v1/player/connection-grants",
                body={
                    "requestId": "guest-host-spoof",
                    "resourceKind": "lobby",
                    "resourceId": config.lobby.lobby_id,
                    "role": "host",
                },
            ),
            expected_status=403,
            name="guest host-role spoof",
        )
        base.record_step(
            steps,
            "grant-role-spoof-rejected",
            True,
            {"status": 403},
        )

        base.require_worker_http(
            admission_workers[guest_config.player_id].command(
                "gateway",
                method="POST",
                path="/v1/player/connection-grants",
                body={
                    "requestId": "guest-endpoint-injection",
                    "resourceKind": "lobby",
                    "resourceId": config.lobby.lobby_id,
                    "endpoint": {
                        "transport": "websocket",
                        "address": "wss://attacker.invalid",
                    },
                },
            ),
            expected_status=400,
            name="endpoint injection",
        )
        base.record_step(
            steps,
            "grant-endpoint-injection-rejected",
            True,
            {"status": 400},
        )

        owner_admission = admission_workers.pop(owner_config.player_id)
        owner_admission.stop(config.timeouts.shutdown_seconds)
        restarted = start_worker(
            player=owner_config,
            config=config,
            identity_url=identity_url,
            request_base_url=broker_url,
            secrets_directory=secrets_directory,
            logs_directory=logs_directory,
            suffix="admission-restart",
        )
        admission_workers[owner_config.player_id] = restarted
        if restarted.ready.get("credentialsLoaded") is not True:
            raise AssertionError("restarted admission worker did not load credentials")
        after_restart = base.require_worker_http(
            restarted.command(
                "gateway",
                method="POST",
                path="/v1/player/connection-grants",
                body={
                    "requestId": f"grant-{owner_config.player_id}",
                    "resourceKind": "lobby",
                    "resourceId": config.lobby.lobby_id,
                    "role": "host",
                    "usage": "reconnectable",
                    "maximumUses": 2,
                    "lifetimeMs": 60_000,
                },
            ),
            expected_status=200,
            name="restarted admission worker grant",
        )
        if require_dict(after_restart.get("payload"), "restart receipt").get("reused") is not True:
            raise AssertionError("restarted client did not recover idempotent grant")
        base.record_step(
            steps,
            "admission-client-restart",
            True,
            {"credentialsLoaded": True, "grantReused": True},
        )

        unregister_status, unregister_payload = base.http_json(
            "POST",
            f"{broker_url}/v1/targets/lobby/{config.lobby.lobby_id}/unregister",
            {"leaseToken": lease_token},
            token=secret_values["target_service"],
        )
        if unregister_status != 200 or not isinstance(unregister_payload, dict) or unregister_payload.get("removed") is not True:
            raise AssertionError(
                f"target unregister failed: {unregister_status}: {base.redact(unregister_payload)}"
            )
        lease_token = None
        base.require_worker_http(
            admission_workers[guest_config.player_id].command(
                "gateway",
                method="POST",
                path="/v1/player/connection-grants",
                body={
                    "requestId": "grant-after-unregister",
                    "resourceKind": "lobby",
                    "resourceId": config.lobby.lobby_id,
                    "role": "player",
                },
            ),
            expected_status=404,
            name="grant after target unregister",
        )
        base.record_step(
            steps,
            "target-unregister-enforced",
            True,
            {"removed": True, "newGrantStatus": 404},
        )

        status = "passed"
    except Exception as error:  # noqa: BLE001
        error_message = base.bounded_error(error)
        base.record_step(
            steps,
            "campaign-failure",
            False,
            {"error": error_message},
        )
    finally:
        for worker in reversed(list(admission_workers.values())):
            try:
                worker.stop(config.timeouts.shutdown_seconds)
            except Exception as error:  # noqa: BLE001
                base.record_step(
                    steps,
                    f"cleanup-admission-worker:{worker.name}",
                    False,
                    {"error": base.bounded_error(error)},
                )
        for worker in reversed(list(workers.values())):
            try:
                worker.stop(config.timeouts.shutdown_seconds)
            except Exception as error:  # noqa: BLE001
                base.record_step(
                    steps,
                    f"cleanup-platform-worker:{worker.name}",
                    False,
                    {"error": base.bounded_error(error)},
                )
        for managed in reversed(processes):
            try:
                base.stop_managed_process(
                    managed,
                    config.timeouts.shutdown_seconds,
                )
            except Exception as error:  # noqa: BLE001
                base.record_step(
                    steps,
                    f"cleanup-service:{managed.name}",
                    False,
                    {"error": base.bounded_error(error)},
                )

        shutil.rmtree(secrets_directory, ignore_errors=True)
        ended_at = base.epoch_ms()
        evidence = {
            "schemaVersion": 1,
            "campaignId": campaign_id,
            "runId": run_id,
            "status": status,
            "startedAt": started_at,
            "endedAt": ended_at,
            "durationMs": max(0, ended_at - started_at),
            "gameServicesRepo": str(config.game_services_repo),
            "gameServicesRevision": base.safe_git_revision(
                config.game_services_repo
            ),
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
            "logs": sorted(
                str(path.relative_to(evidence_root))
                for path in logs_directory.glob("*.log")
            ),
            "secretDirectoryRemoved": not secrets_directory.exists(),
            "targetLeaseRemoved": lease_token is None,
            "secretsRedacted": True,
            **({} if error_message is None else {"error": error_message}),
        }
        base.write_json_atomic(evidence_path, evidence)

    if status != "passed":
        raise RuntimeError(
            f"authenticated real-time campaign failed; evidence: {evidence_path}: {error_message}"
        )
    return evidence_path


def start_worker(
    *,
    player: Any,
    config: Any,
    identity_url: str,
    request_base_url: str,
    secrets_directory: Path,
    logs_directory: Path,
    suffix: str,
) -> Any:
    worker_script = Path(__file__).with_name(
        "evavo_authenticated_client_worker.mjs"
    )
    if not worker_script.is_file():
        raise FileNotFoundError(f"client worker is missing: {worker_script}")
    player_directory = secrets_directory / player.player_id
    environment = base.minimal_environment(
        {
            "EVAVO_TEST_PLAYER_ID": player.player_id,
            "EVAVO_TEST_DISPLAY_NAME": player.display_name,
            "EVAVO_TEST_DEVICE_ID": player.device_id,
            "EVAVO_TEST_GAME_ID": config.game_id,
            "EVAVO_TEST_BUILD_HASH": config.build_hash,
            "EVAVO_TEST_PROTOCOL_VERSION": str(config.protocol_version),
            "EVAVO_TEST_IDENTITY_URL": identity_url,
            "EVAVO_TEST_GATEWAY_URL": request_base_url,
            "EVAVO_TEST_PRIVATE_KEY_PATH": str(
                player_directory / "device-private.pem"
            ),
            "EVAVO_TEST_CREDENTIAL_PATH": str(
                player_directory / "credentials.json"
            ),
            "EVAVO_TEST_HTTP_TIMEOUT_MS": str(
                int(config.timeouts.command_seconds * 1000)
            ),
        }
    )
    return base.JsonLineWorker(
        name=f"{player.player_id}-{suffix}",
        command=[base.node_executable(), str(worker_script)],
        environment=environment,
        cwd=Path(__file__).resolve().parents[1],
        stderr_path=logs_directory / f"client-{player.player_id}-{suffix}.log",
        command_timeout=config.timeouts.command_seconds,
    )


def require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must be an object")
    return value


def load_config(path: Path) -> Any:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("campaign configuration exceeds the size limit")
    return base.parse_campaign_config(
        json.loads(raw.decode("utf-8")),
        base_directory=path.parent.resolve(),
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the EVAVO authenticated real-time admission campaign."
        ),
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Authenticated stack campaign JSON path",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Use existing compiled game-services outputs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        config = load_config(arguments.config.resolve())
        if arguments.no_build:
            config = base.CampaignConfig(
                **{**config.__dict__, "build_before_run": False},
            )
        evidence = run_realtime_campaign(config)
        print(json.dumps({"ok": True, "evidence": str(evidence)}, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001
        print(
            json.dumps(
                {"ok": False, "error": base.bounded_error(error)},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
