"""Unit tests for speaker editing and reference-override helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.speaker_tagging import load_speaker_tags, save_speaker_tags
from webui import editing


SAMPLE_SRT = """1
00:00:01,000 --> 00:00:02,000
Hello one

2
00:00:02,100 --> 00:00:03,000
Hello two

3
00:00:04,000 --> 00:00:05,000
Hello three
"""


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.chdir(root)
    (root / "output" / "audio").mkdir(parents=True)
    (root / "output" / "trans.srt").write_text(SAMPLE_SRT, encoding="utf-8")
    (root / "output" / "src.srt").write_text(SAMPLE_SRT, encoding="utf-8")
    return root


def _items(merge_second=False, speaker2="alice"):
    return [
        {
            "cue": 1,
            "speaker": "alice",
            "merge_with_previous": False,
            "confidence": 1.0,
            "manual_override": True,
            "reason": "manual",
        },
        {
            "cue": 2,
            "speaker": speaker2,
            "merge_with_previous": merge_second,
            "confidence": 1.0,
            "manual_override": True,
            "reason": "manual",
        },
        {
            "cue": 3,
            "speaker": "bob",
            "merge_with_previous": False,
            "confidence": 1.0,
            "manual_override": True,
            "reason": "manual",
        },
    ]


def test_validate_accepts_same_speaker_merge(workspace):
    items = editing.validate_speaker_items(_items(merge_second=True, speaker2="alice"))
    assert items[1]["merge_with_previous"] is True
    assert items[1]["manual_override"] is True


def test_validate_rejects_cross_speaker_merge(workspace):
    with pytest.raises(ValueError, match="人物不同"):
        editing.validate_speaker_items(_items(merge_second=True, speaker2="bob"))


def test_validate_rejects_first_cue_merge(workspace):
    items = _items()
    items[0]["merge_with_previous"] = True
    with pytest.raises(ValueError, match="第一条"):
        editing.validate_speaker_items(items)


def _cue_items():
    return [
        {
            "source_id": "two",
            "start": "00:00:02,000",
            "end": "00:00:03,000",
            "text": "Second",
            "origin": "",
            "speaker": "alice",
            "merge_with_previous": True,
        },
        {
            "source_id": "one",
            "start": "00:00:01,000",
            "end": "00:00:02,100",
            "text": "First",
            "origin": "Original first",
            "speaker": "alice",
            "merge_with_previous": False,
        },
    ]


def test_validate_cues_sorts_renumbers_mirrors_origin_and_warns_overlap(workspace):
    result = editing.validate_cue_items(_cue_items(), media_duration=5)
    assert [item["cue"] for item in result["items"]] == [1, 2]
    assert [item["text"] for item in result["items"]] == ["First", "Second"]
    assert result["items"][1]["origin"] == "Second"
    assert result["warnings"] == ["字幕 1 与 2 时间重叠"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"start": "bad"}, "无效时间"),
        ({"end": "00:00:00,900"}, "结束时间必须晚于"),
        ({"text": " "}, "译文不能为空"),
        ({"speaker": ""}, "人物不能为空"),
        ({"end": "00:00:06,000"}, "超出媒体时长"),
    ],
)
def test_validate_cues_rejects_invalid_fields(workspace, change, message):
    items = _cue_items()
    items[1].update(change)
    with pytest.raises(ValueError, match=message):
        editing.validate_cue_items(items, media_duration=5)


def test_apply_cue_draft_syncs_files_and_clears_numbered_artifacts(workspace, monkeypatch):
    from types import SimpleNamespace
    import core

    monkeypatch.setattr(
        core,
        "_8_1_audio_task",
        SimpleNamespace(gen_audio_task_main=lambda: None),
        raising=False,
    )
    monkeypatch.setattr(
        core,
        "_8_2_dub_chunks",
        SimpleNamespace(gen_dub_chunks=lambda: None),
        raising=False,
    )
    monkeypatch.setattr(
        core,
        "_9_refer_audio",
        SimpleNamespace(extract_refer_audio_main=lambda: None),
        raising=False,
    )

    for directory in (
        Path("output/audio/tmp"),
        Path("output/audio/segs"),
        editing.CANDIDATE_DIR,
        editing.OVERRIDE_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "stale.wav").write_bytes(b"old")
    Path("output/audio/tts_tasks.xlsx").write_bytes(b"old")
    Path("output/audio/merge_pending.json").write_text("[1]", encoding="utf-8")
    Path("output/output_dub.mp4").write_bytes(b"old video")

    result = editing.apply_cue_draft(_cue_items(), media_duration=5)

    trans = Path("output/trans.srt").read_text(encoding="utf-8")
    src = Path("output/src.srt").read_text(encoding="utf-8")
    assert "1\n00:00:01,000 --> 00:00:02,100\nFirst" in trans
    assert "2\n00:00:02,000 --> 00:00:03,000\nSecond" in trans
    assert "Original first" in src
    assert src.rstrip().endswith("Second")
    for path in (
        "output/audio/trans_subs_for_audio.srt",
        "output/_import_trans.srt",
    ):
        assert Path(path).read_text(encoding="utf-8") == trans
    for path in (
        "output/audio/src_subs_for_audio.srt",
        "output/_import_src.srt",
    ):
        assert Path(path).read_text(encoding="utf-8") == src
    tags = load_speaker_tags()
    assert list(tags) == [1, 2]
    assert tags[2]["merge_with_previous"] is True
    assert not list(Path("output").rglob("*.tmp"))
    for directory in (
        Path("output/audio/tmp"),
        Path("output/audio/segs"),
        editing.CANDIDATE_DIR,
        editing.OVERRIDE_DIR,
    ):
        assert list(directory.iterdir()) == []
    assert not Path("output/audio/merge_pending.json").exists()
    assert not Path("output/audio/tts_tasks.xlsx").exists()
    assert Path("output/output_dub.mp4").read_bytes() == b"old video"
    assert editing.SUBTITLE_STALE_PATH.is_file()
    assert result["cue_count"] == 2


def test_save_speaker_tags_persists_manual_flags(workspace):
    saved = save_speaker_tags(_items(merge_second=True), model="manual")
    assert saved[2]["speaker"] == "alice"
    loaded = load_speaker_tags()
    assert loaded[2]["manual_override"] is True
    assert loaded[2]["merge_with_previous"] is True
    data = json.loads(Path("output/audio/speaker_tags.json").read_text(encoding="utf-8"))
    assert data["model"] == "manual"
    assert len(data["items"]) == 3


def test_parse_task_number_from_name():
    assert editing._parse_task_number_from_name("11.wav") == 11
    assert editing._parse_task_number_from_name("task_12_ref.mp3") == 12
    assert editing._parse_task_number_from_name("ref-3.flac") == 3
    assert editing._parse_task_number_from_name("voice.wav") is None


def test_validate_task_numbers(workspace, monkeypatch):
    monkeypatch.setattr(
        editing,
        "snapshot_tasks",
        lambda: [{"number": 1}, {"number": 3}, {"number": 5}],
    )
    assert editing.validate_task_numbers([5, 1, 1]) == [1, 5]
    with pytest.raises(ValueError, match="未知任务编号"):
        editing.validate_task_numbers([2])


def test_changed_task_numbers_detects_topology_shift():
    before = [
        {"number": 1, "source_numbers": [1], "text": "a", "speaker": "alice"},
        {"number": 2, "source_numbers": [2], "text": "b", "speaker": "alice"},
    ]
    after = [
        {"number": 1, "source_numbers": [1, 2], "text": "a b", "speaker": "alice"},
    ]
    changed = editing._changed_task_numbers(before, after)
    assert 1 in changed
    assert 2 in changed


# ------------
# Regeneration candidates
# ------------


def _write_silent_wav(path, duration_ms=400):
    from pydub import AudioSegment

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    AudioSegment.silent(duration=duration_ms).export(str(path), format="wav")


def _seed_config(workspace):
    repo_config = Path(__file__).resolve().parents[1] / "config.yaml"
    shutil.copy2(repo_config, workspace / "config.yaml")


def _seed_task_workbook(workspace):
    import pandas as pd

    _seed_config(workspace)
    path = workspace / "output" / "audio" / "tts_tasks.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [
            {
                "number": 1,
                "source_numbers": "[1]",
                "lines": "['Hello one']",
                "text": "Hello one",
                "speaker": "alice",
                "start_time": "00:00:01.000",
                "end_time": "00:00:02.000",
                "duration": 1.0,
                "tolerance": 0.2,
                "real_dur": 0.4,
                "new_sub_times": "[[1.0, 1.4]]",
            },
            {
                "number": 2,
                "source_numbers": "[2]",
                "lines": "['Hello two']",
                "text": "Hello two",
                "speaker": "alice",
                "start_time": "00:00:02.100",
                "end_time": "00:00:03.000",
                "duration": 0.9,
                "tolerance": 0.2,
                "real_dur": 0.4,
                "new_sub_times": "[[2.1, 2.5]]",
            },
        ]
    )
    df.to_excel(path, index=False)
    live_temp = workspace / "output" / "audio" / "tmp" / "1_0_temp.wav"
    live_seg = workspace / "output" / "audio" / "segs" / "1_0.wav"
    _write_silent_wav(live_temp, 400)
    _write_silent_wav(live_seg, 400)
    return live_temp, live_seg


def test_generate_candidate_leaves_live_audio_untouched(workspace, monkeypatch):
    live_temp, live_seg = _seed_task_workbook(workspace)
    before_temp = live_temp.read_bytes()
    before_seg = live_seg.read_bytes()

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 550)

    monkeypatch.setattr("core.tts_backend.tts_main.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    manifest = _10_gen_audio.generate_task_candidate(1)
    assert manifest["number"] == 1
    assert Path("output/audio/regeneration_candidates/1/manifest.json").is_file()
    assert Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").is_file()
    assert Path("output/audio/regeneration_candidates/1/segs/1_0.wav").is_file()
    assert live_temp.read_bytes() == before_temp
    assert live_seg.read_bytes() == before_seg


def test_candidate_prefers_saved_manual_task_text(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    import pandas as pd

    tasks = pd.read_excel("output/audio/tts_tasks.xlsx")
    row_index = tasks.index[tasks["number"] == 1][0]
    tasks.at[row_index, "text"] = "Manually revised line"
    tasks.at[row_index, "lines"] = ["Manually revised line"]
    tasks.to_excel("output/audio/tts_tasks.xlsx", index=False)
    generated = []

    def fake_tts(text, save_as, number, task_df):
        generated.append(text)
        _write_silent_wav(save_as, 500)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr(
        "core._10_gen_audio.load_key",
        lambda key: 1.5 if key == "speed_factor.max" else None,
    )
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    manifest = _10_gen_audio.generate_task_candidate(1)
    assert generated == ["Manually revised line"]
    assert manifest["original_text"] == "Manually revised line"
    assert manifest["candidate_text"] == "Manually revised line"
    assert manifest["writeback_subtitles"] is False

    editing.accept_candidate(1)
    assert "Hello one" in Path("output/trans.srt").read_text(encoding="utf-8")


def test_discard_candidate_keeps_live_audio(workspace, monkeypatch):
    live_temp, live_seg = _seed_task_workbook(workspace)
    before_temp = live_temp.read_bytes()

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 550)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    _10_gen_audio.generate_task_candidate(1)
    editing.discard_candidate(1)
    assert editing.read_candidate_manifest(1) is None
    assert not Path("output/audio/regeneration_candidates/1").exists()
    assert live_temp.read_bytes() == before_temp
    assert live_seg.is_file()


def test_accept_candidate_promotes_and_marks_pending(workspace, monkeypatch):
    live_temp, live_seg = _seed_task_workbook(workspace)

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 700)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio
    import pandas as pd

    _10_gen_audio.generate_task_candidate(1)
    candidate_temp = Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").read_bytes()
    result = editing.accept_candidate(1)

    assert result["accepted"] is True
    assert result["merge_pending"] == [1]
    assert editing.read_merge_pending() == [1]
    assert editing.read_candidate_manifest(1) is None
    assert live_temp.read_bytes() == candidate_temp
    assert live_seg.is_file()

    df = pd.read_excel("output/audio/tts_tasks.xlsx")
    row = df[df["number"] == 1].iloc[0]
    assert float(row["real_dur"]) > 0.4


def test_accept_candidate_without_timing_columns(workspace, monkeypatch):
    """Regression: accepting must work when tts_tasks.xlsx lacks new_sub_times."""
    live_temp, live_seg = _seed_task_workbook(workspace)
    import pandas as pd

    tasks = pd.read_excel("output/audio/tts_tasks.xlsx")
    tasks = tasks.drop(columns=["real_dur", "new_sub_times"], errors="ignore")
    tasks.to_excel("output/audio/tts_tasks.xlsx", index=False)

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 700)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    _10_gen_audio.generate_task_candidate(1)
    result = editing.accept_candidate(1)
    assert result["accepted"] is True

    df = pd.read_excel("output/audio/tts_tasks.xlsx")
    row = df[df["number"] == 1].iloc[0]
    assert float(row["real_dur"]) > 0
    assert row["new_sub_times"] not in (None, "", float("nan"))
    assert live_temp.is_file() and live_seg.is_file()


def test_regenerate_candidate_replaces_previous_only(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    sizes = {"n": 0}

    def fake_tts(text, save_as, number, task_df):
        sizes["n"] += 1
        _write_silent_wav(save_as, 300 + sizes["n"] * 100)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    first = _10_gen_audio.generate_task_candidate(1)
    first_bytes = Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").read_bytes()
    second = _10_gen_audio.generate_task_candidate(1)
    second_bytes = Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").read_bytes()

    assert first["created_at"] != second["created_at"] or first_bytes != second_bytes
    assert editing.read_candidate_manifest(1) is not None
    assert first_bytes != second_bytes


def test_generate_multiple_candidates_keeps_each_version(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    sizes = {"n": 0}

    def fake_tts(text, save_as, number, task_df):
        sizes["n"] += 1
        _write_silent_wav(save_as, 300 + sizes["n"] * 100)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr(
        "core._10_gen_audio.load_key",
        lambda key: 1.5 if key == "speed_factor.max" else None,
    )
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    first = _10_gen_audio.generate_task_candidate(1, candidate_id="batch-1")
    second = _10_gen_audio.generate_task_candidate(1, candidate_id="batch-2")
    manifests = editing.list_candidate_manifests(1)

    assert first["candidate_id"] == "batch-1"
    assert second["candidate_id"] == "batch-2"
    assert {item["candidate_id"] for item in manifests} == {"batch-1", "batch-2"}
    assert Path("output/audio/regeneration_candidates/1/batch-1/manifest.json").is_file()
    assert Path("output/audio/regeneration_candidates/1/batch-2/manifest.json").is_file()

    editing.discard_candidate(1, "batch-1")
    assert editing.read_candidate_manifest(1, "batch-1") is None
    assert editing.read_candidate_manifest(1, "batch-2") is not None


def test_candidate_steps_validate_requested_count(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    steps = editing.generate_candidate_steps(1, count=3)
    assert len(steps) == 1
    assert "3 个候选" in steps[0][0]
    with pytest.raises(ValueError, match="1 到 5"):
        editing.generate_candidate_steps(1, count=6)


def test_candidate_batch_uses_configured_concurrency(workspace, monkeypatch):
    import threading

    _seed_task_workbook(workspace)
    barrier = threading.Barrier(3, timeout=2)
    threads = set()

    def fake_generate(number, candidate_id=None, force_shorten=False):
        threads.add(threading.current_thread().name)
        barrier.wait()
        return {"number": number, "candidate_id": candidate_id}

    def fake_load_key(key):
        values = {
            "tts_method": "custom_tts",
            "noiz_tts.max_workers": 4,
        }
        return values[key]

    monkeypatch.setattr("core._10_gen_audio.generate_task_candidate", fake_generate)
    monkeypatch.setattr("core.utils.config_utils.load_key", fake_load_key)

    steps = editing.generate_candidate_steps(1, count=3)
    steps[0][1]()
    assert len(threads) == 3


def test_remaster_steps_require_pending(workspace):
    with pytest.raises(ValueError, match="没有待重新合片"):
        editing.remaster_steps()

    editing.mark_merge_pending([1])
    steps = editing.remaster_steps()
    assert len(steps) == 2
    assert "1 条" in steps[0][0]


def test_clear_merge_pending_after_remaster_marker(workspace):
    editing.mark_merge_pending([1, 2])
    editing.clear_merge_pending([1])
    assert editing.read_merge_pending() == [2]
    editing.clear_merge_pending()
    assert editing.read_merge_pending() == []
    assert not Path("output/audio/merge_pending.json").exists()


def test_update_task_text_clears_cache_and_candidate(workspace, monkeypatch):
    live_temp, live_seg = _seed_task_workbook(workspace)

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 500)

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.5 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio
    import pandas as pd

    _10_gen_audio.generate_task_candidate(1)
    editing.mark_merge_pending([1])
    Path("output/.dubbing_done").write_text("ok\n", encoding="utf-8")

    result = editing.update_task_text(1, "  Hello   revised  ")
    assert result["changed"] is True
    assert result["text"] == "Hello revised"
    assert not live_temp.exists()
    assert not live_seg.exists()
    assert editing.read_candidate_manifest(1) is None
    assert editing.read_merge_pending() == []
    assert not Path("output/.dubbing_done").exists()

    df = pd.read_excel("output/audio/tts_tasks.xlsx")
    row = df[df["number"] == 1].iloc[0]
    assert row["text"] == "Hello revised"
    lines = row["lines"]
    if isinstance(lines, str):
        lines = eval(lines)
    assert lines == ["Hello revised"]

    same = editing.update_task_text(1, "Hello revised")
    assert same["changed"] is False


def test_update_task_text_rejects_empty(workspace):
    _seed_task_workbook(workspace)
    with pytest.raises(ValueError, match="不能为空"):
        editing.update_task_text(1, "   ")


def test_copy_reference_from_task(workspace):
    _seed_task_workbook(workspace)
    _write_silent_wav(workspace / "output" / "audio" / "refers" / "1.wav", 500)
    _write_silent_wav(workspace / "output" / "audio" / "refers" / "2.wav", 300)

    result = editing.copy_reference_from_task(1, [2])
    assert result["source"] == 1
    assert result["overridden"] == [2]
    assert editing.has_override(2)
    assert (workspace / "output" / "audio" / "reference_overrides" / "2.wav").is_file()


def test_list_reference_library_groups_by_speaker(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    _write_silent_wav(workspace / "output" / "audio" / "refers" / "1.wav", 400)
    _write_silent_wav(workspace / "output" / "audio" / "refers" / "2.wav", 400)

    monkeypatch.setattr(
        "webui.workspace.read_tasks",
        lambda: {
            "tasks": [
                {
                    "number": 1,
                    "speaker": "alice",
                    "text": "Hello one",
                    "start_time": "00:00:01.000",
                    "end_time": "00:00:02.000",
                    "has_override": False,
                    "refer": {"url": "/files/audio/refers/1.wav", "source": "auto"},
                },
                {
                    "number": 2,
                    "speaker": "alice",
                    "text": "Hello two",
                    "start_time": "00:00:02.100",
                    "end_time": "00:00:03.000",
                    "has_override": False,
                    "refer": {"url": "/files/audio/refers/2.wav", "source": "auto"},
                },
                {
                    "number": 3,
                    "speaker": "bob",
                    "text": "Hello three",
                    "start_time": "00:00:04.000",
                    "end_time": "00:00:05.000",
                    "has_override": False,
                    "refer": {"url": "/files/audio/refers/3.wav", "source": "auto"},
                },
            ]
        },
    )

    library = editing.list_reference_library()
    names = [item["name"] for item in library["speakers"]]
    assert names == ["alice", "bob"]
    alice = next(item for item in library["speakers"] if item["name"] == "alice")
    assert alice["count"] == 2
    assert [clip["number"] for clip in alice["clips"]] == [1, 2]


# ------------
# Candidate shorten / no-trim fitting
# ------------


def test_fit_task_to_window_force_merges_without_trim(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    from core import _10_gen_audio
    import pandas as pd

    monkeypatch.setattr(_10_gen_audio, "load_key", lambda key: 1.2 if key == "speed_factor.max" else None)
    tasks_df = pd.read_excel("output/audio/tts_tasks.xlsx")
    temp_dir = Path("output/audio/tmp")
    seg_dir = Path("output/audio/segs")
    _write_silent_wav(temp_dir / "1_0_temp.wav", 2500)

    result = _10_gen_audio.fit_task_to_window(tasks_df, 0, tasks_df.iloc[0], str(temp_dir), str(seg_dir))
    assert result["fits"] is False
    assert result["status"] == "forced_merge"
    assert (seg_dir / "1_0.wav").exists()
    assert result["new_sub_times"]
    assert (temp_dir / "1_0_temp.wav").stat().st_size > 100


def test_validate_shortened_cues_rejects_longer_or_reordered():
    from core import _10_gen_audio

    previous = [
        {"cue": 1, "text": "Hello one", "origin": "A", "budget": 1.0},
        {"cue": 2, "text": "Hello two", "origin": "B", "budget": 1.0},
    ]
    with pytest.raises(ValueError, match="longer"):
        _10_gen_audio._validate_shortened_cues(
            previous,
            {"cues": [{"cue": 1, "text": "Hello one longer"}, {"cue": 2, "text": "Hello two"}]},
        )
    with pytest.raises(ValueError, match="mismatch"):
        _10_gen_audio._validate_shortened_cues(
            previous,
            {"cues": [{"cue": 2, "text": "Hi"}, {"cue": 1, "text": "Hey"}]},
        )


def test_generate_candidate_shortens_until_fit(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    save_speaker_tags(_items(), model="manual")

    def fake_tts(text, save_as, number, task_df):
        duration = 2200 if "Hello one" in text else 800
        _write_silent_wav(save_as, duration)

    def fake_ask_gpt(prompt, resp_type=None, valid_def=None, log_title="default"):
        response = {"analysis": "drop filler", "cues": [{"cue": 1, "text": "Hi"}]}
        if valid_def:
            assert valid_def(response)["status"] == "success"
        return response

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.ask_gpt", fake_ask_gpt)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.2 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    manifest = _10_gen_audio.generate_task_candidate(1)
    assert manifest["fits"] is True
    assert manifest["shorten_rounds"] == 1
    assert manifest["text_changed"] is True
    assert manifest["candidate_text"] == "Hi"
    assert Path("output/audio/regeneration_candidates/1/segs/1_0.wav").is_file()
    assert Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").is_file()


def test_force_shorten_generates_optimized_candidate_even_when_audio_fits(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    calls = {"tts": 0, "llm": 0}

    def fake_tts(text, save_as, number, task_df):
        calls["tts"] += 1
        _write_silent_wav(save_as, 500)

    def fake_ask_gpt(prompt, resp_type=None, valid_def=None, log_title="default"):
        calls["llm"] += 1
        response = {"analysis": "remove filler", "cues": [{"cue": 1, "text": "Hi"}]}
        if valid_def:
            assert valid_def(response)["status"] == "success"
        return response

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.ask_gpt", fake_ask_gpt)
    monkeypatch.setattr(
        "core._10_gen_audio.load_key",
        lambda key: 1.5 if key == "speed_factor.max" else None,
    )
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    manifest = _10_gen_audio.generate_task_candidate(
        1,
        candidate_id="manual-optimize",
        force_shorten=True,
    )
    assert manifest["fits"] is True
    assert manifest["force_shorten"] is True
    assert manifest["candidate_text"] == "Hi"
    assert manifest["shorten_rounds"] == 1
    assert calls == {"tts": 2, "llm": 1}


def test_generate_candidate_force_merges_after_one_shorten_round(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    calls = {"n": 0}

    def fake_tts(text, save_as, number, task_df):
        _write_silent_wav(save_as, 2200)

    def fake_ask_gpt(prompt, resp_type=None, valid_def=None, log_title="default"):
        calls["n"] += 1
        response = {"analysis": "still long", "cues": [{"cue": 1, "text": f"Hi{calls['n']}"}]}
        if valid_def:
            assert valid_def(response)["status"] == "success"
        return response

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.ask_gpt", fake_ask_gpt)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.2 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio

    manifest = _10_gen_audio.generate_task_candidate(1)
    assert manifest["fits"] is False
    assert manifest["status"] == "forced_merge"
    assert manifest["shorten_rounds"] == 1
    assert calls["n"] == 1
    assert Path("output/audio/regeneration_candidates/1/tmp/1_0_temp.wav").is_file()
    assert Path("output/audio/regeneration_candidates/1/segs/1_0.wav").is_file()
    result = editing.accept_candidate(1)
    assert result["accepted"] is True


def test_accept_candidate_writes_shortened_trans_srt(workspace, monkeypatch):
    _seed_task_workbook(workspace)
    save_speaker_tags(_items(), model="manual")

    def fake_tts(text, save_as, number, task_df):
        duration = 2200 if "Hello one" in text else 700
        _write_silent_wav(save_as, duration)

    def fake_ask_gpt(prompt, resp_type=None, valid_def=None, log_title="default"):
        return {"analysis": "ok", "cues": [{"cue": 1, "text": "Hi one"}]}

    monkeypatch.setattr("core._10_gen_audio.tts_main", fake_tts)
    monkeypatch.setattr("core._10_gen_audio.ask_gpt", fake_ask_gpt)
    monkeypatch.setattr("core._10_gen_audio.load_key", lambda key: 1.2 if key == "speed_factor.max" else None)
    monkeypatch.setattr("core._10_gen_audio.check_cancel", lambda: None)

    from core import _10_gen_audio
    import pandas as pd

    _10_gen_audio.generate_task_candidate(1)
    result = editing.accept_candidate(1)
    assert result["accepted"] is True
    assert result["text_changed"] is True

    trans = Path("output/trans.srt").read_text(encoding="utf-8")
    assert "Hi one" in trans
    assert Path("output/audio/trans_subs_for_audio.srt").read_text(encoding="utf-8") == trans
    assert Path("output/_import_trans.srt").read_text(encoding="utf-8") == trans
    assert "Hello one" in Path("output/src.srt").read_text(encoding="utf-8")
    assert "Hi one" not in Path("output/src.srt").read_text(encoding="utf-8")

    df = pd.read_excel("output/audio/tts_tasks.xlsx")
    row = df[df["number"] == 1].iloc[0]
    assert row["text"] == "Hi one"
    tags = load_speaker_tags()
    assert tags[1]["speaker"] == "alice"
