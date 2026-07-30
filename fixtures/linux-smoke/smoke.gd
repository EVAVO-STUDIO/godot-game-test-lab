extends Node2D

var elapsed := 0.0

func _ready() -> void:
    print("EVAVO_LINUX_SANDBOX_FIXTURE_READY")
    queue_redraw()

func _process(delta: float) -> void:
    elapsed += delta
    queue_redraw()

func _draw() -> void:
    var viewport_size := get_viewport_rect().size
    draw_rect(Rect2(Vector2.ZERO, viewport_size), Color("08101c"))
    for index in range(12):
        var y := 72.0 + float(index) * 30.0
        draw_line(
            Vector2(64.0, y),
            Vector2(viewport_size.x - 64.0, y),
            Color(0.12, 0.2, 0.3, 0.55),
            1.0
        )
    var travel := fmod(elapsed * 150.0, maxf(1.0, viewport_size.x - 240.0))
    draw_rect(Rect2(Vector2(90.0 + travel, 350.0), Vector2(150.0, 26.0)), Color("ff244e"))
    draw_circle(Vector2(viewport_size.x * 0.72, 225.0), 86.0, Color(0.18, 0.78, 0.94, 0.92))
    draw_circle(Vector2(viewport_size.x * 0.72, 225.0), 62.0, Color("08101c"))
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
        "GODOT 4.6.2  |  XVFB  |  SOFTWARE MESA  |  MOVIE EVIDENCE",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1.0,
        18,
        Color(0.72, 0.8, 0.9, 1.0)
    )
    draw_string(
        ThemeDB.fallback_font,
        Vector2(72.0, 455.0),
        "Rendered frames prove this lane is not using dummy headless rendering.",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1.0,
        18,
        Color(0.86, 0.9, 0.96, 1.0)
    )
