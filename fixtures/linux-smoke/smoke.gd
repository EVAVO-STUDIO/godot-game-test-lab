extends Node2D

var elapsed := 0.0
var fixture_accept_count := 0
var _status_label: Label
var _test_button: Button


func _ready() -> void:
    print("EVAVO_LINUX_SANDBOX_FIXTURE_READY")
    _build_interface()
    set_meta("fixture_accept_count", fixture_accept_count)
    queue_redraw()


func _process(delta: float) -> void:
    elapsed += delta
    queue_redraw()


func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("fixture_accept"):
        _record_accept("ACTION")
        get_viewport().set_input_as_handled()


func _build_interface() -> void:
    var panel := Panel.new()
    panel.name = "ControlPanel"
    panel.position = Vector2(56.0, 382.0)
    panel.size = Vector2(360.0, 112.0)
    add_child(panel)

    _test_button = Button.new()
    _test_button.name = "JourneyButton"
    _test_button.text = "TEST INPUT JOURNEY"
    _test_button.position = Vector2(16.0, 14.0)
    _test_button.size = Vector2(250.0, 44.0)
    _test_button.focus_mode = Control.FOCUS_ALL
    _test_button.pressed.connect(_on_test_button_pressed)
    panel.add_child(_test_button)

    _status_label = Label.new()
    _status_label.name = "JourneyStatus"
    _status_label.text = "INPUT COUNT 0"
    _status_label.position = Vector2(18.0, 70.0)
    _status_label.size = Vector2(300.0, 28.0)
    panel.add_child(_status_label)
    _test_button.grab_focus()


func _on_test_button_pressed() -> void:
    _record_accept("POINTER")


func _record_accept(source: String) -> void:
    fixture_accept_count += 1
    set_meta("fixture_accept_count", fixture_accept_count)
    set_meta("fixture_last_input_source", source)
    if _status_label != null:
        _status_label.text = "INPUT COUNT %d  |  %s" % [fixture_accept_count, source]


func _draw() -> void:
    var viewport_size := get_viewport_rect().size
    draw_rect(Rect2(Vector2.ZERO, viewport_size), Color("08101c"))
    for index in range(10):
        var y := 72.0 + float(index) * 28.0
        draw_line(
            Vector2(64.0, y),
            Vector2(viewport_size.x - 64.0, y),
            Color(0.12, 0.2, 0.3, 0.55),
            1.0
        )
    var travel := fmod(elapsed * 150.0, maxf(1.0, viewport_size.x - 240.0))
    draw_rect(
        Rect2(Vector2(560.0 + travel * 0.35, 398.0), Vector2(150.0, 26.0)),
        Color("ff244e")
    )
    draw_circle(
        Vector2(viewport_size.x * 0.72, 225.0),
        86.0,
        Color(0.18, 0.78, 0.94, 0.92)
    )
    draw_circle(
        Vector2(viewport_size.x * 0.72, 225.0),
        62.0,
        Color("08101c")
    )
    draw_string(
        ThemeDB.fallback_font,
        Vector2(70.0, 120.0),
        "EVAVO GODOT LINUX SANDBOX",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1.0,
        34,
        Color("f4f7fb")
    )
    draw_string(
        ThemeDB.fallback_font,
        Vector2(72.0, 168.0),
        "GODOT 4.6.2  |  XVFB  |  SOFTWARE MESA  |  INTERACTIVE QA",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1.0,
        18,
        Color(0.72, 0.8, 0.9, 1.0)
    )
    draw_string(
        ThemeDB.fallback_font,
        Vector2(500.0, 475.0),
        "KEYBOARD  |  MOUSE  |  SYNTHETIC GAMEPAD  |  UX TELEMETRY",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1.0,
        16,
        Color(0.86, 0.9, 0.96, 1.0)
    )
