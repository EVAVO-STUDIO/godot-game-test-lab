extends Node

const SCHEMA := "evavo.godot.android-semantic-driver.v1"
const DEFAULT_PORT := 43821
const MAX_MESSAGE_BYTES := 16384
const MAX_ACTIONS := 128

var _server := TCPServer.new()
var _peer: StreamPeerTCP
var _buffer := PackedByteArray()
var _session := ""
var _allowed_actions: Dictionary = {}
var _pulse_deadlines: Dictionary = {}
var _enabled := false


func _ready() -> void:
    if not OS.has_feature("debug"):
        return
    if not bool(ProjectSettings.get_setting("evavo/test_driver/enabled", false)):
        return

    var configured_actions: Variant = ProjectSettings.get_setting(
        "evavo/test_driver/allowed_actions",
        PackedStringArray(),
    )
    var actions: Array[String] = []
    if configured_actions is PackedStringArray:
        for value in configured_actions:
            actions.append(str(value))
    elif configured_actions is Array:
        for value in configured_actions:
            actions.append(str(value))

    if actions.is_empty() or actions.size() > MAX_ACTIONS:
        push_error("EVAVO Android semantic driver requires 1..128 allowed actions.")
        return

    for action in actions:
        if not _valid_action_name(action) or not InputMap.has_action(action):
            push_error("EVAVO Android semantic driver rejected invalid InputMap action: %s" % action)
            return
        _allowed_actions[action] = true

    var port := int(ProjectSettings.get_setting("evavo/test_driver/port", DEFAULT_PORT))
    if port < 1024 or port > 65535:
        push_error("EVAVO Android semantic driver port must be 1024..65535.")
        return

    _session = Crypto.new().generate_random_bytes(16).hex_encode()
    var error := _server.listen(port, "127.0.0.1")
    if error != OK:
        push_error("EVAVO Android semantic driver failed to bind loopback port %d." % port)
        return
    _enabled = true
    print("EVAVO_ANDROID_SEMANTIC_DRIVER_READY port=%d" % port)


func _process(_delta: float) -> void:
    if not _enabled:
        return
    _release_expired_pulses()
    if _peer == null and _server.is_connection_available():
        _peer = _server.take_connection()
        _buffer.clear()
    if _peer == null:
        return
    _peer.poll()
    if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
        _peer = null
        _buffer.clear()
        return
    var available := _peer.get_available_bytes()
    if available <= 0:
        return
    var chunk := _peer.get_data(available)
    if chunk[0] != OK:
        _peer = null
        _buffer.clear()
        return
    _buffer.append_array(chunk[1])
    if _buffer.size() > MAX_MESSAGE_BYTES:
        _send_error("message_too_large")
        _peer = null
        _buffer.clear()
        return
    _consume_lines()


func _consume_lines() -> void:
    while true:
        var newline := _buffer.find(10)
        if newline < 0:
            return
        var line := _buffer.slice(0, newline)
        _buffer = _buffer.slice(newline + 1)
        if line.is_empty():
            continue
        var parsed: Variant = JSON.parse_string(line.get_string_from_utf8())
        if not parsed is Dictionary:
            _send_error("invalid_json")
            continue
        _handle_request(parsed)


func _handle_request(request: Dictionary) -> void:
    var op := str(request.get("op", ""))
    if op == "hello":
        _send({
            "schema": SCHEMA,
            "ok": true,
            "op": "hello",
            "session": _session,
            "allowedActions": _allowed_actions.keys(),
            "scene": _current_scene_path(),
            "debugOnly": true,
            "loopbackOnly": true,
        })
        return

    if str(request.get("session", "")) != _session:
        _send_error("invalid_session")
        return

    match op:
        "state":
            _send({
                "schema": SCHEMA,
                "ok": true,
                "op": "state",
                "session": _session,
                "scene": _current_scene_path(),
                "paused": get_tree().paused,
                "processFrames": Engine.get_process_frames(),
                "pressedActions": _pressed_allowed_actions(),
            })
        "action":
            _handle_action(request)
        _:
            _send_error("unsupported_operation")


func _handle_action(request: Dictionary) -> void:
    var action := str(request.get("name", ""))
    if not _allowed_actions.has(action):
        _send_error("action_not_allowed")
        return
    var kind := str(request.get("kind", ""))
    var strength := float(request.get("strength", 1.0))
    if strength < 0.0 or strength > 1.0:
        _send_error("invalid_strength")
        return

    match kind:
        "press":
            Input.action_press(action, strength)
            _pulse_deadlines.erase(action)
        "release":
            Input.action_release(action)
            _pulse_deadlines.erase(action)
        "pulse":
            var duration_ms := int(request.get("durationMs", 100))
            if duration_ms < 16 or duration_ms > 2000:
                _send_error("invalid_duration")
                return
            Input.action_press(action, strength)
            _pulse_deadlines[action] = Time.get_ticks_msec() + duration_ms
        _:
            _send_error("unsupported_action_kind")
            return

    _send({
        "schema": SCHEMA,
        "ok": true,
        "op": "action",
        "session": _session,
        "name": action,
        "kind": kind,
        "scene": _current_scene_path(),
    })


func _release_expired_pulses() -> void:
    if _pulse_deadlines.is_empty():
        return
    var now := Time.get_ticks_msec()
    var expired: Array[String] = []
    for action in _pulse_deadlines:
        if now >= int(_pulse_deadlines[action]):
            Input.action_release(str(action))
            expired.append(str(action))
    for action in expired:
        _pulse_deadlines.erase(action)


func _pressed_allowed_actions() -> Array[String]:
    var pressed: Array[String] = []
    for action in _allowed_actions:
        if Input.is_action_pressed(str(action)):
            pressed.append(str(action))
    return pressed


func _current_scene_path() -> String:
    var scene := get_tree().current_scene
    if scene == null:
        return ""
    return scene.scene_file_path


func _valid_action_name(value: String) -> bool:
    if value.is_empty() or value.length() > 64:
        return false
    for index in value.length():
        var code := value.unicode_at(index)
        var valid := (
            (code >= 48 and code <= 57)
            or (code >= 65 and code <= 90)
            or (code >= 97 and code <= 122)
            or code == 95
            or code == 46
            or code == 58
            or code == 45
        )
        if not valid:
            return false
    return true


func _send_error(code: String) -> void:
    _send({"schema": SCHEMA, "ok": false, "code": code})


func _send(value: Dictionary) -> void:
    if _peer == null:
        return
    var encoded := (JSON.stringify(value) + "\n").to_utf8_buffer()
    if encoded.size() > MAX_MESSAGE_BYTES:
        return
    _peer.put_data(encoded)
