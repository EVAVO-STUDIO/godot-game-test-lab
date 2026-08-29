extends SceneTree

const REPORT_SCHEMA_VERSION := 1
const MAX_CONTROL_RECORDS := 512
const MAX_INTERACTIVE_RECORDS := 192
const MAX_LAYOUT_PAIRS := 1024
const MAX_PAIR_CHECKS := 50000
const MAX_PERFORMANCE_SAMPLES := 2048
const PERFORMANCE_SAMPLE_INTERVAL := 5
const MAX_CONTROL_TEXT_CHARACTERS := 256

var _journey: Dictionary = {}
var _result: Dictionary = {}
var _failures := PackedStringArray()
var _step_results: Array[Dictionary] = []
var _checkpoint_records: Array[Dictionary] = []
var _checkpoint_ui_records: Array[Dictionary] = []
var _performance_samples: Array[Dictionary] = []
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
    var ux := Dictionary(_journey.get("ux", {}))
    var ui_captured := false
    if checkpoint_id != "final" and bool(ux.get("captureUiAtCheckpoints", true)):
        _checkpoint_ui_records.append({
            "id": checkpoint_id,
            "screenshot": path.get_file(),
            "ui": _collect_ui_telemetry(),
        })
        ui_captured = true
    _checkpoint_records.append({
        "id": checkpoint_id,
        "path": path.get_file(),
        "width": image.get_width(),
        "height": image.get_height(),
        "uiCaptured": ui_captured,
    })
    return true


func _wait_frames(count: int) -> void:
    for _index in range(maxi(0, count)):
        await process_frame
        _elapsed_frames += 1
        if _elapsed_frames % PERFORMANCE_SAMPLE_INTERVAL == 0:
            _sample_performance()
        if _elapsed_frames >= _max_frames:
            return


func _sample_performance() -> void:
    if _performance_samples.size() >= MAX_PERFORMANCE_SAMPLES:
        return
    _performance_samples.append({
        "frame": _elapsed_frames,
        "fps": Performance.get_monitor(Performance.TIME_FPS),
        "processMs": Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
        "physicsMs": Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0,
        "memoryStaticBytes": Performance.get_monitor(Performance.MEMORY_STATIC),
        "objectCount": Performance.get_monitor(Performance.OBJECT_COUNT),
        "nodeCount": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
        "drawCalls": Performance.get_monitor(
            Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME
        ),
    })


func _metric_summary(key: String) -> Dictionary:
    var values: Array[float] = []
    var total := 0.0
    for sample: Dictionary in _performance_samples:
        var value := float(sample.get(key, 0.0))
        values.append(value)
        total += value
    if values.is_empty():
        return {"samples": 0}
    values.sort()
    var p95_index := clampi(
        int(ceil(float(values.size()) * 0.95)) - 1,
        0,
        values.size() - 1
    )
    return {
        "samples": values.size(),
        "minimum": values[0],
        "mean": total / float(values.size()),
        "p95": values[p95_index],
        "maximum": values[values.size() - 1],
    }


func _summarize_performance() -> Dictionary:
    return {
        "sampleIntervalFrames": PERFORMANCE_SAMPLE_INTERVAL,
        "sampleCount": _performance_samples.size(),
        "fps": _metric_summary("fps"),
        "processMs": _metric_summary("processMs"),
        "physicsMs": _metric_summary("physicsMs"),
        "memoryStaticBytes": _metric_summary("memoryStaticBytes"),
        "objectCount": _metric_summary("objectCount"),
        "nodeCount": _metric_summary("nodeCount"),
        "drawCalls": _metric_summary("drawCalls"),
    }


func _input_event_record(event: InputEvent, category: String) -> Dictionary:
    var record := {
        "type": event.get_class(),
        "category": category,
        "device": event.device,
    }
    if event is InputEventKey:
        var key_event := event as InputEventKey
        record["keycode"] = int(key_event.keycode)
        record["physicalKeycode"] = int(key_event.physical_keycode)
        record["unicode"] = int(key_event.unicode)
    elif event is InputEventMouseButton:
        record["buttonIndex"] = int((event as InputEventMouseButton).button_index)
    elif event is InputEventJoypadButton:
        record["buttonIndex"] = int((event as InputEventJoypadButton).button_index)
    elif event is InputEventJoypadMotion:
        var motion := event as InputEventJoypadMotion
        record["axis"] = int(motion.axis)
        record["axisValue"] = motion.axis_value
    elif event is InputEventAction:
        var action_event := event as InputEventAction
        record["action"] = String(action_event.action)
        record["strength"] = action_event.strength
    return record


func _collect_input_map() -> Dictionary:
    var actions: Array[Dictionary] = []
    var coverage := {"keyboard": 0, "mouse": 0, "gamepad": 0, "action": 0, "other": 0}
    for action_value: Variant in InputMap.get_actions():
        var action_name := String(action_value)
        var event_records: Array[Dictionary] = []
        for event: InputEvent in InputMap.action_get_events(action_name):
            var category := _event_category(event)
            coverage[category] = int(coverage.get(category, 0)) + 1
            event_records.append(_input_event_record(event, category))
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
    var total_interactive := 0
    var records_truncated := false
    var stack: Array[Node] = [root]
    while not stack.is_empty():
        if visible_controls.size() >= MAX_CONTROL_RECORDS:
            records_truncated = true
            break
        var node: Node = stack.pop_back()
        var children := node.get_children()
        for child_index in range(children.size() - 1, -1, -1):
            var child: Node = children[child_index]
            stack.append(child)
        if not node is Control:
            continue
        var control := node as Control
        if not control.is_visible_in_tree():
            continue
        var rect := control.get_global_rect()
        var interactive := _is_interactive_control(control)
        var disabled := _control_disabled(control)
        var parent := control.get_parent()
        var record := {
            "path": String(control.get_path()),
            "parentPath": String(parent.get_path()) if parent is Control else "",
            "ancestorPaths": Array(_control_ancestor_paths(control)),
            "class": control.get_class(),
            "name": String(control.name),
            "text": _control_text(control),
            "inputTextRedacted": control is LineEdit or control is TextEdit,
            "x": rect.position.x,
            "y": rect.position.y,
            "width": rect.size.x,
            "height": rect.size.y,
            "focusMode": control.focus_mode,
            "mouseFilter": control.mouse_filter,
            "interactive": interactive,
            "disabled": disabled,
            "editable": _control_editable(control),
            "insideViewport": viewport_rect.encloses(rect),
            "clippedByAncestor": _control_clipped_by_ancestor(control, rect),
            "clipContents": control.clip_contents,
            "treeOrder": visible_controls.size(),
            "paintOrder": visible_controls.size(),
            "canvasLayer": _canvas_layer(control),
            "zIndex": control.z_index,
            "effectiveZIndex": _effective_z_index(control),
            "zAsRelative": control.z_as_relative,
        }
        visible_controls.append(record)
        if interactive:
            total_interactive += 1
            if not disabled and interactive_controls.size() < MAX_INTERACTIVE_RECORDS:
                interactive_controls.append(record)

    _annotate_center_occlusion(visible_controls, interactive_controls)
    var minimum_width := float(ux.get("minimumInteractiveWidth", 24))
    var minimum_height := float(ux.get("minimumInteractiveHeight", 24))
    var minimum_gap := float(ux.get("minimumInteractiveGap", 8))
    var out_of_bounds: Array[Dictionary] = []
    var small_targets: Array[Dictionary] = []
    var ancestor_clipped: Array[Dictionary] = []
    var occluded: Array[Dictionary] = []
    for record: Dictionary in interactive_controls:
        if not bool(record.get("insideViewport", false)):
            out_of_bounds.append(record)
        if bool(record.get("clippedByAncestor", false)):
            ancestor_clipped.append(record)
        if not String(record.get("centerBlockedBy", "")).is_empty():
            occluded.append(record)
        if (
            float(record.get("width", 0.0)) < minimum_width
            or float(record.get("height", 0.0)) < minimum_height
        ):
            small_targets.append(record)

    var overlaps: Array[Dictionary] = []
    var close_pairs: Array[Dictionary] = []
    var pair_checks := 0
    var pair_analysis_truncated := false
    var maximum_pair_checks := mini(
        MAX_PAIR_CHECKS,
        maxi(0, int(ux.get("maximumPairChecks", MAX_PAIR_CHECKS)))
    )
    for left_index in range(interactive_controls.size()):
        if pair_analysis_truncated:
            break
        var left := Dictionary(interactive_controls[left_index])
        var left_rect := _record_rect(left)
        if not left_rect.has_area():
            continue
        for right_index in range(left_index + 1, interactive_controls.size()):
            if pair_checks >= maximum_pair_checks:
                pair_analysis_truncated = true
                break
            pair_checks += 1
            var right := Dictionary(interactive_controls[right_index])
            if _paths_related(String(left["path"]), String(right["path"])):
                continue
            var right_rect := _record_rect(right)
            if not right_rect.has_area():
                continue
            if left_rect.intersects(right_rect):
                if overlaps.size() < MAX_LAYOUT_PAIRS:
                    var intersection := left_rect.intersection(right_rect)
                    var overlap_area := intersection.get_area()
                    var left_coverage := overlap_area / left_rect.get_area()
                    var right_coverage := overlap_area / right_rect.get_area()
                    overlaps.append({
                        "left": left["path"],
                        "right": right["path"],
                        "overlapArea": overlap_area,
                        "overlapWidth": intersection.size.x,
                        "overlapHeight": intersection.size.y,
                        "leftCoverage": left_coverage,
                        "rightCoverage": right_coverage,
                        "minimumCoverage": minf(left_coverage, right_coverage),
                    })
                continue
            var horizontal_overlap := _axis_overlap(
                left_rect.position.x,
                left_rect.end.x,
                right_rect.position.x,
                right_rect.end.x
            )
            var vertical_overlap := _axis_overlap(
                left_rect.position.y,
                left_rect.end.y,
                right_rect.position.y,
                right_rect.end.y
            )
            var gap := -1.0
            if horizontal_overlap > 0.0:
                gap = _axis_gap(
                    left_rect.position.y,
                    left_rect.end.y,
                    right_rect.position.y,
                    right_rect.end.y
                )
            elif vertical_overlap > 0.0:
                gap = _axis_gap(
                    left_rect.position.x,
                    left_rect.end.x,
                    right_rect.position.x,
                    right_rect.end.x
                )
            if gap >= 0.0 and gap < minimum_gap and close_pairs.size() < MAX_LAYOUT_PAIRS:
                close_pairs.append({
                    "left": left["path"],
                    "right": right["path"],
                    "gap": gap,
                    "minimumGap": minimum_gap,
                })

    var focus_owner := root.gui_get_focus_owner()
    var telemetry := {
        "viewport": {
            "width": viewport_rect.size.x,
            "height": viewport_rect.size.y,
        },
        "visibleControlCount": visible_controls.size(),
        "interactiveControlCount": total_interactive,
        "retainedInteractiveControlCount": interactive_controls.size(),
        "controlRecordsTruncated": records_truncated,
        "interactiveRecordsTruncated": total_interactive > interactive_controls.size(),
        "pairChecks": pair_checks,
        "pairAnalysisTruncated": pair_analysis_truncated,
        "focusOwner": String(focus_owner.get_path()) if focus_owner != null else "",
        "mouseMode": Input.mouse_mode,
        "outOfBoundsInteractive": out_of_bounds,
        "ancestorClippedInteractive": ancestor_clipped,
        "occludedInteractive": occluded,
        "smallInteractiveTargets": small_targets,
        "overlappingInteractivePairs": overlaps,
        "closeInteractivePairs": close_pairs,
        "interactiveControls": interactive_controls,
    }
    if bool(ux.get("captureControlTree", true)):
        telemetry["controls"] = visible_controls
    return telemetry


func _control_text(control: Control) -> String:
    if control is LineEdit or control is TextEdit:
        return ""
    if control is Button:
        return _bounded_control_text((control as Button).text)
    if control is LinkButton:
        return _bounded_control_text((control as LinkButton).text)
    if control is Label:
        return _bounded_control_text((control as Label).text)
    if control is RichTextLabel:
        return _bounded_control_text((control as RichTextLabel).get_parsed_text())
    return ""


func _bounded_control_text(value: String) -> String:
    return value.replace("\r", " ").replace("\n", " ").strip_edges().substr(
        0,
        MAX_CONTROL_TEXT_CHARACTERS
    )


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


func _control_disabled(control: Control) -> bool:
    if control is BaseButton:
        return (control as BaseButton).disabled
    if control is LineEdit:
        return not (control as LineEdit).editable
    if control is TextEdit:
        return not (control as TextEdit).editable
    return false


func _control_editable(control: Control) -> bool:
    if control is LineEdit:
        return (control as LineEdit).editable
    if control is TextEdit:
        return (control as TextEdit).editable
    return not _control_disabled(control)


func _control_ancestor_paths(control: Control) -> PackedStringArray:
    var paths := PackedStringArray()
    var ancestor := control.get_parent()
    while ancestor != null:
        if ancestor is Control:
            paths.append(String(ancestor.get_path()))
        ancestor = ancestor.get_parent()
    return paths


func _control_clipped_by_ancestor(control: Control, rect: Rect2) -> bool:
    var ancestor := control.get_parent()
    while ancestor != null:
        if ancestor is Control:
            var ancestor_control := ancestor as Control
            if (
                ancestor_control.clip_contents
                and not ancestor_control.get_global_rect().encloses(rect)
            ):
                return true
        ancestor = ancestor.get_parent()
    return false


func _canvas_layer(control: Control) -> int:
    var ancestor: Node = control
    while ancestor != null:
        if ancestor is CanvasLayer:
            return (ancestor as CanvasLayer).layer
        ancestor = ancestor.get_parent()
    return 0


func _effective_z_index(control: Control) -> int:
    var total := control.z_index
    var relative := control.z_as_relative
    var ancestor := control.get_parent()
    while relative and ancestor is CanvasItem:
        var item := ancestor as CanvasItem
        total += item.z_index
        relative = item.z_as_relative
        ancestor = item.get_parent()
    return total


func _record_rect(record: Dictionary) -> Rect2:
    return Rect2(
        Vector2(float(record.get("x", 0.0)), float(record.get("y", 0.0))),
        Vector2(float(record.get("width", 0.0)), float(record.get("height", 0.0)))
    )


func _paths_related(left: String, right: String) -> bool:
    return left == right or left.begins_with(right + "/") or right.begins_with(left + "/")


func _record_is_above(candidate: Dictionary, target: Dictionary) -> bool:
    var candidate_layer := int(candidate.get("canvasLayer", 0))
    var target_layer := int(target.get("canvasLayer", 0))
    if candidate_layer != target_layer:
        return candidate_layer > target_layer
    var candidate_z := int(candidate.get("effectiveZIndex", 0))
    var target_z := int(target.get("effectiveZIndex", 0))
    if candidate_z != target_z:
        return candidate_z > target_z
    return int(candidate.get("paintOrder", -1)) > int(target.get("paintOrder", -1))


func _annotate_center_occlusion(
    visible_controls: Array[Dictionary],
    interactive_controls: Array[Dictionary]
) -> void:
    var blockers := {}
    for target: Dictionary in interactive_controls:
        var target_rect := _record_rect(target)
        if not target_rect.has_area():
            continue
        var center := target_rect.get_center()
        var selected: Dictionary = {}
        for candidate: Dictionary in visible_controls:
            var target_path := String(target.get("path", ""))
            var candidate_path := String(candidate.get("path", ""))
            if (
                candidate_path.is_empty()
                or _paths_related(target_path, candidate_path)
                or int(candidate.get("mouseFilter", Control.MOUSE_FILTER_STOP))
                    == Control.MOUSE_FILTER_IGNORE
                or not _record_is_above(candidate, target)
                or not _record_rect(candidate).has_point(center)
            ):
                continue
            if selected.is_empty() or _record_is_above(candidate, selected):
                selected = candidate
        if not selected.is_empty():
            blockers[String(target.get("path", ""))] = String(selected.get("path", ""))
    for index in range(visible_controls.size()):
        var record := Dictionary(visible_controls[index])
        var path := String(record.get("path", ""))
        if blockers.has(path):
            record["centerBlockedBy"] = blockers[path]
            visible_controls[index] = record
    for index in range(interactive_controls.size()):
        var record := Dictionary(interactive_controls[index])
        var path := String(record.get("path", ""))
        if blockers.has(path):
            record["centerBlockedBy"] = blockers[path]
            interactive_controls[index] = record


func _axis_gap(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    if left_end < right_start:
        return right_start - left_end
    if right_end < left_start:
        return left_start - right_end
    return 0.0


func _axis_overlap(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float
) -> float:
    return maxf(0.0, minf(left_end, right_end) - maxf(left_start, right_start))


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
        Array(telemetry.get("ancestorClippedInteractive", [])).size()
        > int(ux.get("maximumAncestorClippedInteractive", 0))
    ):
        errors.append("Interactive controls are clipped by ancestor controls.")
    if (
        Array(telemetry.get("occludedInteractive", [])).size()
        > int(ux.get("maximumOccludedInteractive", 0))
    ):
        errors.append("Interactive controls are occluded at their centre point.")
    if (
        Array(telemetry.get("overlappingInteractivePairs", [])).size()
        > int(ux.get("maximumOverlappingInteractivePairs", 0))
    ):
        errors.append("Interactive controls overlap beyond the governed limit.")
    if (
        Array(telemetry.get("closeInteractivePairs", [])).size()
        > int(ux.get("maximumCloseInteractivePairs", 32))
    ):
        errors.append("Interactive controls are too closely spaced.")
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
    if (
        bool(ux.get("failOnTruncatedLayoutAnalysis", false))
        and (
            bool(telemetry.get("controlRecordsTruncated", false))
            or bool(telemetry.get("interactiveRecordsTruncated", false))
            or bool(telemetry.get("pairAnalysisTruncated", false))
        )
    ):
        errors.append("Semantic UI layout analysis reached a configured bound.")
    return errors


func _finish() -> void:
    var ui_telemetry := _collect_ui_telemetry()
    _failures.append_array(_validate_ux(ui_telemetry))
    _result["status"] = "passed" if _failures.is_empty() else "failed"
    _result["elapsedFrames"] = _elapsed_frames
    _result["completedUnixMsec"] = Time.get_unix_time_from_system() * 1000.0
    _result["steps"] = _step_results
    _result["checkpoints"] = _checkpoint_records
    _result["checkpointUi"] = _checkpoint_ui_records
    _result["inputMap"] = _collect_input_map()
    _result["ui"] = ui_telemetry
    _result["performance"] = _summarize_performance()
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
