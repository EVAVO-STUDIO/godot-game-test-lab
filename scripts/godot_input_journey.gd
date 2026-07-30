extends SceneTree

const REPORT_SCHEMA_VERSION := 1
const MAX_CONTROL_RECORDS := 512
const MAX_INTERACTIVE_RECORDS := 192
const MAX_OVERLAP_PAIRS := 1024

var _journey: Dictionary = {}
var _result: Dictionary = {}
var _failures := PackedStringArray()
var _step_results: Array[Dictionary] = []
var _checkpoint_records: Array[Dictionary] = []
var _elapsed_frames := 0
var _max_frames := 900
var _report_path := ""
var _checkpoint_root := ""
var _scene_path := ""


func _initialize() -> void:
    _report_path = OS.get_environment("EVAVO_JOURNEY_REPORT")
    _checkpoint_root = OS.get_environment("EVAVO_JOURNEY_CHECKPOINT_ROOT")
    _scene_path = OS.get_environment("EVAVO_JOURNEY_SCENE")
    _max_frames = maxi(30, int(OS.get_environment("EVAVO_JOURNEY_MAX_FRAMES")))
    call_deferred("_run")


func _run() -> void:
    var journey_path := OS.get_environment("EVAVO_JOURNEY_PATH")
    _journey = _load_json_object(journey_path)
    if _journey.is_empty():
        _failures.append("Journey JSON is missing or invalid.")
        _finish()
        return

    _result = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "journeyId": String(_journey.get("id", "unknown")),
        "device": String(_journey.get("device", "semantic")),
        "syntheticInput": true,
        "physicalGamepadConnected": not Input.get_connected_joypads().is_empty(),
        "startedUnixMsec": Time.get_unix_time_from_system() * 1000.0,
    }
    Input.use_accumulated_input = false
    if not await _load_requested_scene():
        _finish()
        return

    await _wait_frames(int(_journey.get("settleFrames", 30)))
    _validate_required_actions()
    await _execute_steps()
    await _run_assertions()
    await _capture_checkpoint("final")
    _finish()


func _load_requested_scene() -> bool:
    var requested := _scene_path.strip_edges()
    if requested.is_empty():
        requested = String(ProjectSettings.get_setting("application/run/main_scene", ""))
    if requested.is_empty():
        _failures.append("No journey scene or application/run/main_scene is configured.")
        return false
    var packed_value: Variant = load(requested)
    if not packed_value is PackedScene:
        _failures.append("Journey scene could not be loaded: %s" % requested)
        return false
    var instance := (packed_value as PackedScene).instantiate()
    if instance == null:
        _failures.append("Journey scene could not be instantiated: %s" % requested)
        return false
    root.add_child(instance)
    current_scene = instance
    _result["scene"] = requested
    return true


func _execute_steps() -> void:
    var raw_steps: Variant = _journey.get("steps", [])
    if not raw_steps is Array:
        _failures.append("Journey steps are not an array.")
        return
    var steps := Array(raw_steps)
    for index in range(steps.size()):
        if _elapsed_frames >= _max_frames:
            _failures.append("Journey exceeded its maximum frame budget.")
            return
        var raw_step: Variant = steps[index]
        if not raw_step is Dictionary:
            _failures.append("Journey step %d is not an object." % index)
            continue
        var step := Dictionary(raw_step)
        var step_type := String(step.get("type", ""))
        var accepted := await _execute_step(step)
        _step_results.append({
            "index": index,
            "type": step_type,
            "accepted": accepted,
            "elapsedFrames": _elapsed_frames,
        })
        if not accepted:
            _failures.append("Journey step %d failed: %s" % [index, step_type])


func _execute_step(step: Dictionary) -> bool:
    match String(step.get("type", "")):
        "wait":
            await _wait_frames(int(step.get("frames", 1)))
            return true
        "action":
            return await _send_action(
                String(step.get("action", "")),
                bool(step.get("pressed", true)),
                float(step.get("strength", 1.0))
            )
        "action_tap":
            var action := String(step.get("action", ""))
            var strength := float(step.get("strength", 1.0))
            if not await _send_action(action, true, strength):
                return false
            await _wait_frames(int(step.get("holdFrames", 1)))
            return await _send_action(action, false, 0.0)
        "key":
            return await _send_key(
                int(step.get("physicalKeycode", 0)),
                bool(step.get("pressed", true))
            )
        "key_tap":
            var keycode := int(step.get("physicalKeycode", 0))
            if not await _send_key(keycode, true):
                return false
            await _wait_frames(int(step.get("holdFrames", 1)))
            return await _send_key(keycode, false)
        "mouse_move":
            return await _send_mouse_motion(step)
        "mouse_button":
            return await _send_mouse_button(step, bool(step.get("pressed", true)))
        "mouse_click":
            if not await _send_mouse_button(step, true):
                return false
            await _wait_frames(int(step.get("holdFrames", 1)))
            return await _send_mouse_button(step, false)
        "joy_button":
            return await _send_joy_button(step, bool(step.get("pressed", true)))
        "joy_button_tap":
            if not await _send_joy_button(step, true):
                return false
            await _wait_frames(int(step.get("holdFrames", 1)))
            return await _send_joy_button(step, false)
        "joy_axis":
            return await _send_joy_axis(step)
        "checkpoint":
            return await _capture_checkpoint(String(step.get("id", "checkpoint")))
    return false


func _send_action(action_name: String, pressed: bool, strength: float) -> bool:
    if not InputMap.has_action(action_name):
        return false
    var event := InputEventAction.new()
    event.action = StringName(action_name)
    event.pressed = pressed
    event.strength = clampf(strength, 0.0, 1.0) if pressed else 0.0
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


func _send_key(physical_keycode: int, pressed: bool) -> bool:
    if physical_keycode <= 0:
        return false
    var event := InputEventKey.new()
    event.physical_keycode = physical_keycode
    event.pressed = pressed
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


func _send_mouse_motion(step: Dictionary) -> bool:
    var event := InputEventMouseMotion.new()
    event.position = Vector2(float(step.get("x", 0)), float(step.get("y", 0)))
    event.global_position = event.position
    event.relative = Vector2(
        float(step.get("relativeX", 0)),
        float(step.get("relativeY", 0))
    )
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


func _send_mouse_button(step: Dictionary, pressed: bool) -> bool:
    var button_index := int(step.get("buttonIndex", 0))
    if button_index <= 0:
        return false
    var event := InputEventMouseButton.new()
    event.button_index = button_index
    event.position = Vector2(float(step.get("x", 0)), float(step.get("y", 0)))
    event.global_position = event.position
    event.pressed = pressed
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


func _send_joy_button(step: Dictionary, pressed: bool) -> bool:
    var button_index := int(step.get("buttonIndex", -1))
    if button_index < 0:
        return false
    var event := InputEventJoypadButton.new()
    event.device = int(step.get("deviceId", 0))
    event.button_index = button_index
    event.pressed = pressed
    event.pressure = 1.0 if pressed else 0.0
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


func _send_joy_axis(step: Dictionary) -> bool:
    var axis := int(step.get("axis", -1))
    if axis < 0:
        return false
    var event := InputEventJoypadMotion.new()
    event.device = int(step.get("deviceId", 0))
    event.axis = axis
    event.axis_value = clampf(float(step.get("value", 0.0)), -1.0, 1.0)
    Input.parse_input_event(event)
    Input.flush_buffered_events()
    await _wait_frames(1)
    return true


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
        var accepted := _evaluate_assertion(assertion)
        records.append({
            "index": index,
            "type": assertion_type,
            "accepted": accepted,
        })
        if not accepted:
            _failures.append("Journey assertion %d failed: %s" % [index, assertion_type])
    _result["assertions"] = records


func _evaluate_assertion(assertion: Dictionary) -> bool:
    match String(assertion.get("type", "")):
        "scene_loaded":
            return current_scene != null and is_instance_valid(current_scene)
        "input_action_exists":
            return InputMap.has_action(String(assertion.get("action", "")))
        "node_exists":
            return _find_assertion_node(String(assertion.get("path", ""))) != null
        "node_visible":
            var node := _find_assertion_node(String(assertion.get("path", "")))
            return node != null and node is CanvasItem and (node as CanvasItem).is_visible_in_tree()
        "focus_present":
            return root.gui_get_focus_owner() != null
        "metadata_equals":
            var node := _find_assertion_node(String(assertion.get("path", "")))
            if node == null or not node.has_meta(StringName(assertion.get("key", ""))):
                return false
            return node.get_meta(StringName(assertion.get("key", ""))) == assertion.get("value")
    return false


func _find_assertion_node(path: String) -> Node:
    if path.begins_with("/root"):
        return root.get_node_or_null(NodePath(path))
    if current_scene == null:
        return null
    return current_scene.get_node_or_null(NodePath(path))


func _validate_required_actions() -> void:
    var records: Array[Dictionary] = []
    var raw_requirements: Variant = _journey.get("requiredActions", [])
    if not raw_requirements is Array:
        _failures.append("requiredActions is not an array.")
        return
    for raw_requirement: Variant in Array(raw_requirements):
        if not raw_requirement is Dictionary:
            continue
        var requirement := Dictionary(raw_requirement)
        var action_name := String(requirement.get("name", ""))
        var exists := InputMap.has_action(action_name)
        var available_devices := PackedStringArray()
        if exists:
            for event: InputEvent in InputMap.action_get_events(action_name):
                var category := _event_category(event)
                if not category.is_empty() and category not in available_devices:
                    available_devices.append(category)
        var missing_devices := PackedStringArray()
        for required_device: String in Array(requirement.get("devices", [])):
            if required_device not in available_devices:
                missing_devices.append(required_device)
        var accepted := exists and missing_devices.is_empty()
        records.append({
            "name": action_name,
            "exists": exists,
            "availableDevices": Array(available_devices),
            "missingDevices": Array(missing_devices),
            "accepted": accepted,
        })
        if not accepted:
            _failures.append(
                "Required input action is missing or lacks device coverage: %s"
                % action_name
            )
    _result["requiredActions"] = records


func _event_category(event: InputEvent) -> String:
    if event is InputEventKey:
        return "keyboard"
    if event is InputEventMouseButton or event is InputEventMouseMotion:
        return "mouse"
    if event is InputEventJoypadButton or event is InputEventJoypadMotion:
        return "gamepad"
    if event is InputEventAction:
        return "action"
    return "other"


func _capture_checkpoint(checkpoint_id: String) -> bool:
    if checkpoint_id.is_empty() or _checkpoint_root.is_empty():
        return false
    await _wait_frames(2)
    DirAccess.make_dir_recursive_absolute(_checkpoint_root)
    var image := root.get_texture().get_image()
    if image == null or image.is_empty():
        return false
    var path := _checkpoint_root.path_join("%s.png" % checkpoint_id)
    var error := image.save_png(path)
    if error != OK:
        return false
    _checkpoint_records.append({
        "id": checkpoint_id,
        "path": path.get_file(),
        "width": image.get_width(),
        "height": image.get_height(),
    })
    return true


func _wait_frames(count: int) -> void:
    for _index in range(maxi(0, count)):
        await process_frame
        _elapsed_frames += 1
        if _elapsed_frames >= _max_frames:
            return


func _collect_input_map() -> Dictionary:
    var actions: Array[Dictionary] = []
    var coverage := {"keyboard": 0, "mouse": 0, "gamepad": 0, "action": 0, "other": 0}
    for action_value: Variant in InputMap.get_actions():
        var action_name := String(action_value)
        var event_records: Array[Dictionary] = []
        for event: InputEvent in InputMap.action_get_events(action_name):
            var category := _event_category(event)
            coverage[category] = int(coverage.get(category, 0)) + 1
            event_records.append({
                "type": event.get_class(),
                "category": category,
                "device": event.device,
            })
        actions.append({
            "name": action_name,
            "deadzone": InputMap.action_get_deadzone(action_name),
            "events": event_records,
        })
    return {"actions": actions, "coverage": coverage}


func _collect_ui_telemetry() -> Dictionary:
    var ux := Dictionary(_journey.get("ux", {}))
    var viewport_rect := root.get_visible_rect()
    var visible_controls: Array[Dictionary] = []
    var interactive_controls: Array[Dictionary] = []
    var stack: Array[Node] = [root]
    while not stack.is_empty() and visible_controls.size() < MAX_CONTROL_RECORDS:
        var node := stack.pop_back()
        for child: Node in node.get_children():
            stack.append(child)
        if not node is Control:
            continue
        var control := node as Control
        if not control.is_visible_in_tree():
            continue
        var rect := control.get_global_rect()
        var record := {
            "path": String(control.get_path()),
            "class": control.get_class(),
            "name": control.name,
            "x": rect.position.x,
            "y": rect.position.y,
            "width": rect.size.x,
            "height": rect.size.y,
            "focusMode": control.focus_mode,
            "mouseFilter": control.mouse_filter,
            "insideViewport": viewport_rect.encloses(rect),
        }
        visible_controls.append(record)
        if (
            _is_interactive_control(control)
            and interactive_controls.size() < MAX_INTERACTIVE_RECORDS
        ):
            interactive_controls.append(record)

    var minimum_width := float(ux.get("minimumInteractiveWidth", 24))
    var minimum_height := float(ux.get("minimumInteractiveHeight", 24))
    var out_of_bounds: Array[Dictionary] = []
    var small_targets: Array[Dictionary] = []
    for record: Dictionary in interactive_controls:
        if not bool(record.get("insideViewport", false)):
            out_of_bounds.append(record)
        if (
            float(record.get("width", 0.0)) < minimum_width
            or float(record.get("height", 0.0)) < minimum_height
        ):
            small_targets.append(record)

    var overlaps: Array[Dictionary] = []
    for left_index in range(interactive_controls.size()):
        if overlaps.size() >= MAX_OVERLAP_PAIRS:
            break
        var left := Dictionary(interactive_controls[left_index])
        var left_rect := Rect2(
            Vector2(float(left["x"]), float(left["y"])),
            Vector2(float(left["width"]), float(left["height"]))
        )
        if left_rect.size.x <= 0.0 or left_rect.size.y <= 0.0:
            continue
        for right_index in range(left_index + 1, interactive_controls.size()):
            var right := Dictionary(interactive_controls[right_index])
            var right_rect := Rect2(
                Vector2(float(right["x"]), float(right["y"])),
                Vector2(float(right["width"]), float(right["height"]))
            )
            if left_rect.intersects(right_rect):
                overlaps.append({"left": left["path"], "right": right["path"]})
                if overlaps.size() >= MAX_OVERLAP_PAIRS:
                    break

    var focus_owner := root.gui_get_focus_owner()
    var telemetry := {
        "viewport": {
            "width": viewport_rect.size.x,
            "height": viewport_rect.size.y,
        },
        "visibleControlCount": visible_controls.size(),
        "interactiveControlCount": interactive_controls.size(),
        "focusOwner": String(focus_owner.get_path()) if focus_owner != null else "",
        "mouseMode": Input.mouse_mode,
        "outOfBoundsInteractive": out_of_bounds,
        "smallInteractiveTargets": small_targets,
        "overlappingInteractivePairs": overlaps,
    }
    if bool(ux.get("captureControlTree", true)):
        telemetry["controls"] = visible_controls
    return telemetry


func _is_interactive_control(control: Control) -> bool:
    if control.focus_mode != Control.FOCUS_NONE:
        return true
    return (
        control is BaseButton
        or control is LineEdit
        or control is TextEdit
        or control is Range
        or control is OptionButton
        or control is ItemList
        or control is Tree
        or control is TabBar
    )


func _validate_ux(telemetry: Dictionary) -> PackedStringArray:
    var errors := PackedStringArray()
    var ux := Dictionary(_journey.get("ux", {}))
    if (
        int(telemetry.get("visibleControlCount", 0))
        < int(ux.get("minimumVisibleControls", 0))
    ):
        errors.append("Visible control count is below the governed minimum.")
    if (
        Array(telemetry.get("outOfBoundsInteractive", [])).size()
        > int(ux.get("maximumOutOfBoundsInteractive", 0))
    ):
        errors.append("Interactive controls extend outside the viewport.")
    if (
        Array(telemetry.get("overlappingInteractivePairs", [])).size()
        > int(ux.get("maximumOverlappingInteractivePairs", 0))
    ):
        errors.append("Interactive controls overlap beyond the governed limit.")
    if (
        bool(ux.get("requireFocusOwner", false))
        and String(telemetry.get("focusOwner", "")).is_empty()
    ):
        errors.append("A keyboard or gamepad journey has no GUI focus owner.")
    if (
        Array(telemetry.get("smallInteractiveTargets", [])).size()
        > int(ux.get("maximumSmallInteractiveTargets", 8))
    ):
        errors.append("Too many interactive controls are below the target size.")
    return errors


func _finish() -> void:
    var ui_telemetry := _collect_ui_telemetry()
    _failures.append_array(_validate_ux(ui_telemetry))
    _result["status"] = "passed" if _failures.is_empty() else "failed"
    _result["elapsedFrames"] = _elapsed_frames
    _result["completedUnixMsec"] = Time.get_unix_time_from_system() * 1000.0
    _result["steps"] = _step_results
    _result["checkpoints"] = _checkpoint_records
    _result["inputMap"] = _collect_input_map()
    _result["ui"] = ui_telemetry
    _result["failures"] = Array(_failures)
    _write_report()
    quit(0 if _failures.is_empty() else 1)


func _write_report() -> void:
    if _report_path.is_empty():
        return
    DirAccess.make_dir_recursive_absolute(_report_path.get_base_dir())
    var file := FileAccess.open(_report_path, FileAccess.WRITE)
    if file == null:
        return
    file.store_string(JSON.stringify(_result, "  ", true) + "\n")


func _load_json_object(path: String) -> Dictionary:
    if path.is_empty() or not FileAccess.file_exists(path):
        return {}
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return {}
    var parsed: Variant = JSON.parse_string(file.get_as_text())
    return Dictionary(parsed).duplicate(true) if parsed is Dictionary else {}
