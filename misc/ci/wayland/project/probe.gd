extends Node

func _ready() -> void:
    print("LIFECYCLE_BACKEND=", DisplayServer.get_name())
    while Engine.get_frames_drawn() < 2:
        await RenderingServer.frame_post_draw
    print("LIFECYCLE_READY frames=", Engine.get_frames_drawn())
    var report := FileAccess.open("user://lifecycle-ready.json.tmp", FileAccess.WRITE)
    report.store_string(JSON.stringify({"backend": DisplayServer.get_name(), "pid": OS.get_process_id(), "frames": Engine.get_frames_drawn()}))
    report.close()
    DirAccess.rename_absolute("user://lifecycle-ready.json.tmp", "user://lifecycle-ready.json")
    if "--lifecycle-auto-quit" in OS.get_cmdline_user_args():
        await get_tree().create_timer(0.2).timeout
        get_tree().quit()

func _exit_tree() -> void:
    print("LIFECYCLE_EXIT")
