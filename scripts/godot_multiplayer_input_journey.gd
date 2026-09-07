extends "res://.evavo-lab/godot_input_journey.gd"

const MAX_CAPTURE_SESSION_BYTES := 256
const MAX_CAPTURE_OBSERVED_PEERS := 32
const MAX_CAPTURE_PEER_ID := 2147483647
const RESERVED_CAPTURE_KEYS := [
    "evavo_peer_session_id",
    "evavo_local_peer_id",
    "evavo_observed_peer_ids",
    "evavo_authority_peer_id",
]


func _run_assertions() -> void:
    var raw_assertions: Variant = _journey.get("assertions", [])
    if not raw_assertions is Array:
        _failures.append("Journey assertions are not an array.")
        return
    var records: Array[Dictionary] = []
    for index in range(Array(raw_assertions).size()):
        var raw_assertion: Variant = Array(raw_assertions)[index]
        if not raw_assertion is Dictionary:
            _failures.append("Journey assertion %d is not an object." % index)
            continue
        var assertion := Dictionary(raw_assertion)
        var assertion_type := String(assertion.get("type", ""))
        var accepted := false
        var record := {
            "index": index,
            "type": assertion_type,
            "accepted": false,
        }
        if assertion_type == "metadata_capture":
            var capture := _capture_reserved_metadata(assertion)
            accepted = bool(capture.get("ok", false))
            record["accepted"] = accepted
            if accepted:
                record["actual"] = capture.get("value")
            else:
                record["reason"] = String(capture.get("reason", "capture_rejected")).substr(0, 128)
        else:
            accepted = _evaluate_assertion(assertion)
            record["accepted"] = accepted
        records.append(record)
        if not accepted:
            _failures.append("Journey assertion %d failed: %s" % [index, assertion_type])
    _result["assertions"] = records


func _capture_reserved_metadata(assertion: Dictionary) -> Dictionary:
    var key := String(assertion.get("key", ""))
    if key not in RESERVED_CAPTURE_KEYS:
        return {"ok": false, "reason": "capture_key_not_reserved"}
    var path := String(assertion.get("path", ""))
    var node := _find_assertion_node(path)
    if node == null:
        return {"ok": false, "reason": "capture_node_missing"}
    var meta_key := StringName(key)
    if not node.has_meta(meta_key):
        return {"ok": false, "reason": "capture_metadata_missing"}
    var value: Variant = node.get_meta(meta_key)
    match key:
        "evavo_peer_session_id":
            return _capture_session(value)
        "evavo_local_peer_id", "evavo_authority_peer_id":
            return _capture_peer_id(value)
        "evavo_observed_peer_ids":
            return _capture_peer_ids(value)
    return {"ok": false, "reason": "capture_key_not_reserved"}


func _capture_session(value: Variant) -> Dictionary:
    if typeof(value) != TYPE_STRING:
        return {"ok": false, "reason": "capture_session_not_string"}
    var session := String(value)
    if (
        session.is_empty()
        or session != session.strip_edges()
        or session.to_utf8_buffer().size() > MAX_CAPTURE_SESSION_BYTES
        or session.contains("\r")
        or session.contains("\n")
    ):
        return {"ok": false, "reason": "capture_session_invalid"}
    return {"ok": true, "value": session}


func _capture_peer_id(value: Variant) -> Dictionary:
    if typeof(value) != TYPE_INT:
        return {"ok": false, "reason": "capture_peer_id_not_integer"}
    var peer_id := int(value)
    if peer_id < 1 or peer_id > MAX_CAPTURE_PEER_ID:
        return {"ok": false, "reason": "capture_peer_id_out_of_range"}
    return {"ok": true, "value": peer_id}


func _capture_peer_ids(value: Variant) -> Dictionary:
    var raw_items: Array = []
    match typeof(value):
        TYPE_ARRAY:
            raw_items = Array(value)
        TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY:
            raw_items = Array(value)
        _:
            return {"ok": false, "reason": "capture_peer_ids_not_array"}
    if raw_items.size() > MAX_CAPTURE_OBSERVED_PEERS:
        return {"ok": false, "reason": "capture_peer_ids_too_large"}
    var peers: Array[int] = []
    var seen := {}
    for raw_peer: Variant in raw_items:
        if typeof(raw_peer) != TYPE_INT:
            return {"ok": false, "reason": "capture_peer_ids_contains_non_integer"}
        var peer_id := int(raw_peer)
        if peer_id < 1 or peer_id > MAX_CAPTURE_PEER_ID:
            return {"ok": false, "reason": "capture_peer_ids_contains_out_of_range"}
        if seen.has(peer_id):
            return {"ok": false, "reason": "capture_peer_ids_contains_duplicate"}
        seen[peer_id] = true
        peers.append(peer_id)
    peers.sort()
    return {"ok": true, "value": peers}
