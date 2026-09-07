@tool
extends EditorPlugin

func _enter_tree() -> void:
    await get_tree().process_frame
    await get_tree().process_frame
    print("LIFECYCLE_EDITOR_READY")
    if "--lifecycle-editor-cycle" in OS.get_cmdline_user_args():
        if FileAccess.file_exists("user://lifecycle-ready.json"):
            DirAccess.remove_absolute("user://lifecycle-ready.json")
        EditorInterface.play_main_scene()
        while not FileAccess.file_exists("user://lifecycle-ready.json"):
            await get_tree().process_frame
        var report: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("user://lifecycle-ready.json"))
        print("LIFECYCLE_EDITOR_GAME_REPORT=", JSON.stringify(report))
        EditorInterface.stop_playing_scene()
        while EditorInterface.is_playing_scene():
            await get_tree().process_frame
        print("LIFECYCLE_EDITOR_GAME_STOPPED")
