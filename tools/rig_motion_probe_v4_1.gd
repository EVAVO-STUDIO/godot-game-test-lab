extends SceneTree

const KIND := "evavo-godot-rig-motion-probe-v4.1"

func _argument(name: String) -> String:
    for value in OS.get_cmdline_user_args():
        if value.begins_with(name + "="):
            return value.substr(name.length() + 1)
    return ""

func _walk(node: Node, inventory: Dictionary) -> void:
    inventory["nodeCount"] += 1
    if node is MeshInstance3D:
        inventory["meshInstanceCount"] += 1
    if node is Skeleton3D:
        inventory["skeletonCount"] += 1
        inventory["boneCount"] += node.get_bone_count()
    if node is AnimationPlayer:
        inventory["animationPlayerCount"] += 1
        for library_name in node.get_animation_library_list():
            var library := node.get_animation_library(library_name)
            for animation_name in library.get_animation_list():
                inventory["animations"].append(str(animation_name))
    for child in node.get_children():
        _walk(child, inventory)

func _transform_signature(node: Node) -> float:
    var total := 0.0
    if node is Node3D:
        var transform := node.global_transform
        total += transform.origin.length()
        total += abs(transform.basis.determinant())
    for child in node.get_children():
        total += _transform_signature(child)
    return total

func _sample_animation(root: Node, player: AnimationPlayer, animation_name: String) -> Dictionary:
    var animation := player.get_animation(animation_name)
    var duration := max(animation.length, 0.001)
    var values: Array[float] = []
    for fraction in [0.0, 0.333333, 0.666667, 1.0]:
        player.play(animation_name)
        player.seek(duration * float(fraction), true)
        values.append(_transform_signature(root))
    var maximum_delta := 0.0
    for value in values:
        maximum_delta = max(maximum_delta, abs(value - values[0]))
    return {
        "sampleCount": values.size(),
        "maximumTransformDelta": maximum_delta,
        "samples": values,
    }

func _find_player(node: Node) -> AnimationPlayer:
    if node is AnimationPlayer:
        return node
    for child in node.get_children():
        var found := _find_player(child)
        if found != null:
            return found
    return null

func _initialize() -> void:
    var asset_path := _argument("--asset")
    var manifest_path := _argument("--manifest")
    var family := _argument("--family")
    var output_path := _argument("--output")
    var receipt := {
        "schemaVersion": 1,
        "kind": KIND,
        "family": family,
        "loadOk": false,
        "instantiateOk": false,
        "nodeCount": 0,
        "meshInstanceCount": 0,
        "skeletonCount": 0,
        "boneCount": 0,
        "animationPlayerCount": 0,
        "animations": [],
        "motion": {},
        "authority": {
            "runtimeAdmission": false,
            "targetRepositoryMutation": false,
            "gitMutation": false,
            "deployment": false,
            "publication": false
        }
    }
    var resource := ResourceLoader.load(asset_path)
    receipt["loadOk"] = resource != null
    if resource is PackedScene:
        var instance := resource.instantiate()
        receipt["instantiateOk"] = instance != null
        if instance != null:
            root.add_child(instance)
            _walk(instance, receipt)
            var player := _find_player(instance)
            if player != null:
                for animation_name in player.get_animation_list():
                    receipt["motion"][animation_name] = _sample_animation(instance, player, animation_name)
    var file := FileAccess.open(output_path, FileAccess.WRITE)
    file.store_string(JSON.stringify(receipt, "  ", false))
    file.store_string("\n")
    file.close()
    quit(0 if receipt["loadOk"] and receipt["instantiateOk"] else 2)
