import json
from pathlib import Path


def _write_srt(path, cues):
    blocks = []
    for index, (start, end, text) in enumerate(cues, 1):
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    Path(path).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def test_propose_repair_snaps_to_char_edges(tmp_path, monkeypatch):
    from core import srt_timing_repair as repair

    trans = tmp_path / "trans.srt"
    src = tmp_path / "src.srt"
    proposal_path = tmp_path / "proposal.json"
    _write_srt(
        trans,
        [
            ("00:00:00,440", "00:00:01,280", "我叫你一声"),
            ("00:00:01,320", "00:00:02,640", "你敢答应吗"),
        ],
    )
    _write_srt(
        src,
        [
            ("00:00:00,440", "00:00:01,280", "我叫你一声"),
            ("00:00:01,320", "00:00:02,640", "你敢答应吗"),
        ],
    )
    monkeypatch.setattr(repair, "TRANS_SRT", trans)
    monkeypatch.setattr(repair, "SRC_SRT", src)
    monkeypatch.setattr(repair, "_SRT_TIMING_PROPOSAL_FILE", str(proposal_path))

    alignment = {
        "words": [
            {"text": "我", "start": 0.24, "end": 0.40},
            {"text": "叫", "start": 0.40, "end": 0.64},
            {"text": "你", "start": 0.64, "end": 0.88},
            {"text": "一", "start": 0.88, "end": 0.88},
            {"text": "声", "start": 0.88, "end": 0.96},
            {"text": "你", "start": 1.28, "end": 1.44},
            {"text": "敢", "start": 1.44, "end": 1.68},
            {"text": "答", "start": 1.68, "end": 1.92},
            {"text": "应", "start": 2.00, "end": 2.08},
            {"text": "吗", "start": 2.08, "end": 2.24},
        ]
    }

    proposal = repair.propose_repair(alignment)
    assert proposal["changed_count"] == 2
    first = proposal["items"][0]
    assert first["new_start"] == 0.24
    assert first["new_end"] == 0.96
    assert first["text"] == "我叫你一声"
    second = proposal["items"][1]
    assert second["new_start"] == 1.28
    assert second["new_end"] == 2.24
    assert proposal_path.is_file()


def test_propose_repair_keeps_already_aligned_cues(tmp_path, monkeypatch):
    from core import srt_timing_repair as repair

    trans = tmp_path / "trans.srt"
    src = tmp_path / "src.srt"
    proposal_path = tmp_path / "proposal.json"
    _write_srt(trans, [("00:00:00,240", "00:00:00,960", "我叫你一声")])
    _write_srt(src, [("00:00:00,240", "00:00:00,960", "我叫你一声")])
    monkeypatch.setattr(repair, "TRANS_SRT", trans)
    monkeypatch.setattr(repair, "SRC_SRT", src)
    monkeypatch.setattr(repair, "_SRT_TIMING_PROPOSAL_FILE", str(proposal_path))

    alignment = {
        "words": [
            {"text": "我", "start": 0.24, "end": 0.40},
            {"text": "声", "start": 0.88, "end": 0.96},
        ]
    }
    proposal = repair.propose_repair(alignment)
    assert proposal["changed_count"] == 0
    assert proposal["items"][0]["changed"] is False


def test_apply_repair_rewrites_timing_only(tmp_path, monkeypatch):
    from core import srt_timing_repair as repair

    paths = {
        "trans": tmp_path / "trans.srt",
        "src": tmp_path / "src.srt",
        "trans_audio": tmp_path / "trans_audio.srt",
        "src_audio": tmp_path / "src_audio.srt",
        "upload_trans": tmp_path / "_import_trans.srt",
        "upload_src": tmp_path / "_import_src.srt",
        "mode": tmp_path / "alignment_mode.json",
        "proposal": tmp_path / "proposal.json",
    }
    _write_srt(paths["trans"], [("00:00:00,440", "00:00:01,280", "我叫你一声")])
    _write_srt(paths["src"], [("00:00:00,440", "00:00:01,280", "我叫你一声")])
    monkeypatch.setattr(repair, "TRANS_SRT", paths["trans"])
    monkeypatch.setattr(repair, "SRC_SRT", paths["src"])
    monkeypatch.setattr(repair, "TRANS_AUDIO_SRT", paths["trans_audio"])
    monkeypatch.setattr(repair, "SRC_AUDIO_SRT", paths["src_audio"])
    monkeypatch.setattr(repair, "UPLOAD_TRANS_SRT", paths["upload_trans"])
    monkeypatch.setattr(repair, "UPLOAD_SRC_SRT", paths["upload_src"])
    monkeypatch.setattr(repair, "_ALIGNMENT_MODE_FILE", str(paths["mode"]))
    monkeypatch.setattr(repair, "_SRT_TIMING_PROPOSAL_FILE", str(paths["proposal"]))

    proposal = {
        "changed_count": 1,
        "items": [
            {
                "cue": 1,
                "text": "我叫你一声",
                "origin": "我叫你一声",
                "old_start": 0.44,
                "old_end": 1.28,
                "new_start": 0.24,
                "new_end": 0.96,
                "start_delta": -0.2,
                "end_delta": -0.32,
                "changed": True,
                "matched_words": 5,
            }
        ],
    }
    repair.apply_repair(proposal, rebuild_tasks=False)

    rewritten = paths["trans"].read_text(encoding="utf-8")
    assert "00:00:00,240 --> 00:00:00,960" in rewritten
    assert "我叫你一声" in rewritten
    assert paths["src"].read_text(encoding="utf-8") == rewritten
    mode = json.loads(paths["mode"].read_text(encoding="utf-8"))
    assert mode["mode"] == "aligned"


def test_skip_repair_writes_conservative_mode(tmp_path, monkeypatch):
    from core import srt_timing_repair as repair

    mode_path = tmp_path / "alignment_mode.json"
    monkeypatch.setattr(repair, "_ALIGNMENT_MODE_FILE", str(mode_path))
    payload = repair.skip_repair(rebuild_tasks=False)
    assert payload["mode"] == "conservative"
    assert json.loads(mode_path.read_text(encoding="utf-8"))["mode"] == "conservative"
