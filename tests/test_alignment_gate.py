from pathlib import Path


def test_prepare_mode_depends_on_translated_srt(tmp_path, monkeypatch):
    from webui import workspace

    trans = tmp_path / "_import_trans.srt"
    monkeypatch.setattr(workspace, "UPLOAD_TRANS_SRT", trans)
    assert workspace.prepare_mode() == "video_only"
    trans.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    assert workspace.prepare_mode() == "import"


def test_stages_for_mode_switch_labels():
    from webui import pipeline

    import_stages = pipeline.stages_for_mode("import")
    video_stages = pipeline.stages_for_mode("video_only")
    assert len(import_stages[0]["steps"]) == 3
    assert "字级对齐" in import_stages[0]["steps"][1]
    assert "人物" in import_stages[0]["steps"][2]
    assert any("转写" in step for step in video_stages[0]["steps"])
    assert len(video_stages[0]["steps"]) == 4


def test_alignment_apply_and_skip_steps_write_mode(tmp_path, monkeypatch):
    from core import srt_timing_repair as repair
    from webui import pipeline

    mode_path = tmp_path / "alignment_mode.json"
    monkeypatch.setattr(repair, "_ALIGNMENT_MODE_FILE", str(mode_path))

    # Skip path
    labels, funcs = zip(*pipeline.alignment_skip_steps())
    monkeypatch.setattr(repair, "skip_repair", lambda rebuild_tasks=True: repair.write_alignment_mode("conservative", "skip"))
    funcs[0]()
    assert "conservative" in mode_path.read_text(encoding="utf-8")

    # Apply path stubs rebuild
    monkeypatch.setattr(
        repair,
        "apply_repair",
        lambda rebuild_tasks=True: repair.write_alignment_mode("aligned", "repair"),
    )
    labels, funcs = zip(*pipeline.alignment_apply_steps())
    funcs[0]()
    assert "aligned" in mode_path.read_text(encoding="utf-8")
