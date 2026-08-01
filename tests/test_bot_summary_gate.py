from __future__ import annotations

from godot_game_test_lab.bot_qa import enforce_exploration_evidence


def valid_summary() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "status": "passed",
        "findings": [],
        "campaigns": [
            {
                "id": "fixture",
                "required": True,
                "status": "passed",
                "stateCount": 2,
                "transitionCount": 1,
                "states": [
                    {"id": "s0000", "depth": 0, "trace": []},
                    {
                        "id": "s0001",
                        "depth": 1,
                        "trace": [{"type": "action_tap"}],
                    },
                ],
                "transitions": [
                    {
                        "from": "s0000",
                        "to": "s0001",
                        "result": "new-state",
                        "trace": [
                            {"type": "action_tap", "action": "fixture_action"}
                        ],
                    }
                ],
                "representativeReplays": [
                    {
                        "state": "s0001",
                        "depth": 1,
                        "trace": [
                            {"type": "action_tap", "action": "fixture_action"}
                        ],
                        "status": "passed",
                        "evidence": [
                            "campaigns/fixture/replay/journey-report.json"
                        ],
                    }
                ],
                "failures": [],
                "findings": [],
            }
        ],
    }


def test_changed_state_and_nonbaseline_replay_pass() -> None:
    summary = valid_summary()

    result = enforce_exploration_evidence(summary)

    assert result["status"] == "passed"
    campaign = result["campaigns"][0]
    assert campaign["status"] == "passed"
    assert campaign["failures"] == []


def test_baseline_only_campaign_fails_closed() -> None:
    summary = valid_summary()
    campaign = summary["campaigns"][0]
    campaign["stateCount"] = 1
    campaign["states"] = [{"id": "s0000", "depth": 0, "trace": []}]
    campaign["transitions"][0].update(
        {"from": "s0000", "to": "s0000", "result": "no-change"}
    )
    campaign["representativeReplays"][0].update(
        {"state": "s0000", "depth": 0, "trace": []}
    )

    result = enforce_exploration_evidence(summary)

    assert result["status"] == "failed"
    assert campaign["status"] == "failed"
    assert any("changed runtime state" in item for item in campaign["findings"])
    assert any("non-baseline replay" in item for item in campaign["findings"])
    assert campaign["failures"][-1]["source"] == "bot-summary-exploration-gate"


def test_optional_baseline_only_campaign_does_not_fail_run() -> None:
    summary = valid_summary()
    campaign = summary["campaigns"][0]
    campaign["required"] = False
    campaign["stateCount"] = 1
    campaign["states"] = [{"id": "s0000", "depth": 0, "trace": []}]
    campaign["transitions"][0].update(
        {"from": "s0000", "to": "s0000", "result": "no-change"}
    )
    campaign["representativeReplays"][0].update(
        {"state": "s0000", "depth": 0, "trace": []}
    )

    result = enforce_exploration_evidence(summary)

    assert result["status"] == "passed"
    assert campaign["status"] == "passed"


def test_replay_requires_retained_evidence() -> None:
    summary = valid_summary()
    campaign = summary["campaigns"][0]
    campaign["representativeReplays"][0]["evidence"] = []

    result = enforce_exploration_evidence(summary)

    assert result["status"] == "failed"
    assert campaign["status"] == "failed"
    assert any("non-baseline replay" in item for item in campaign["findings"])
