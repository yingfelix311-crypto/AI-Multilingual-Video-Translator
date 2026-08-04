import datetime

import pandas as pd


def _time(h=0, m=0, s=0, ms=0):
    return datetime.time(h, m, s, ms * 1000)


def _patch_gap(monkeypatch, gap=1.0, confidence=0.8):
    from core import _8_1_audio_task as audio_task

    monkeypatch.setattr(audio_task, "load_key", lambda key: {
        "speaker_tagging.min_confidence": confidence,
        "speaker_tagging.tts_merge_max_gap": gap,
    }.get(key, 0))


def test_auto_merges_same_speaker_within_gap_without_flag(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gap(monkeypatch, gap=1.0)
    df = pd.DataFrame(
        [
            {
                "number": 1,
                "start_time": _time(s=1),
                "end_time": _time(s=2),
                "duration": 1.0,
                "text": "Hello one",
                "origin": "A",
            },
            {
                "number": 2,
                "start_time": _time(s=2, ms=100),
                "end_time": _time(s=3),
                "duration": 0.9,
                "text": "Hello two",
                "origin": "B",
            },
        ]
    )
    tags = {
        1: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
        2: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
    }

    annotated = audio_task._annotate_speaker_cues(df, tags)
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["merge_with_previous"]) is True
    assert list(merged["number"]) == [1]
    assert merged.iloc[0]["source_numbers"] == [1, 2]


def test_force_unmerge_keeps_separate_even_with_small_gap(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gap(monkeypatch, gap=1.0)
    df = pd.DataFrame(
        [
            {
                "number": 1,
                "start_time": _time(s=1),
                "end_time": _time(s=2),
                "duration": 1.0,
                "text": "Hello one",
                "origin": "A",
            },
            {
                "number": 2,
                "start_time": _time(s=2, ms=100),
                "end_time": _time(s=3),
                "duration": 0.9,
                "text": "Hello two",
                "origin": "B",
            },
        ]
    )
    tags = {
        1: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
        2: {
            "speaker": "alice",
            "confidence": 0.95,
            "merge_with_previous": False,
            "force_unmerge": True,
            "manual_override": True,
        },
    }

    annotated = audio_task._annotate_speaker_cues(df, tags)
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert list(merged["number"]) == [1, 2]
    assert merged.iloc[0]["source_numbers"] == [1]
    assert merged.iloc[1]["source_numbers"] == [2]
    assert bool(merged.iloc[1]["reference_merge_with_previous"]) is False


def test_merge_true_within_gap_joins_tts_and_reference(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gap(monkeypatch, gap=1.0)
    df = pd.DataFrame(
        [
            {
                "number": 1,
                "start_time": _time(s=1),
                "end_time": _time(s=2),
                "duration": 1.0,
                "text": "Hello one",
                "origin": "A",
            },
            {
                "number": 2,
                "start_time": _time(s=2, ms=200),
                "end_time": _time(s=3),
                "duration": 0.8,
                "text": "Hello two",
                "origin": "B",
            },
        ]
    )
    tags = {
        1: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
        2: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": True, "manual_override": True},
    }

    annotated = audio_task._annotate_speaker_cues(df, tags)
    assert bool(annotated.iloc[1]["merge_with_previous"]) is True
    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is True

    merged = audio_task._merge_tts_by_speaker_gap(annotated)
    assert list(merged["number"]) == [1]
    assert merged.iloc[0]["source_numbers"] == [1, 2]
    assert merged.iloc[0]["text"] == "Hello one Hello two"


def test_merge_beyond_gap_stays_separate(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gap(monkeypatch, gap=0.3)
    df = pd.DataFrame(
        [
            {
                "number": 1,
                "start_time": _time(s=1),
                "end_time": _time(s=2),
                "duration": 1.0,
                "text": "Hello one",
                "origin": "A",
            },
            {
                "number": 2,
                "start_time": _time(s=3),
                "end_time": _time(s=4),
                "duration": 1.0,
                "text": "Hello two",
                "origin": "B",
            },
        ]
    )
    tags = {
        1: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
        2: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": True, "manual_override": True},
    }

    annotated = audio_task._annotate_speaker_cues(df, tags)
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["merge_with_previous"]) is False
    assert list(merged["number"]) == [1, 2]
    assert merged.iloc[1]["source_numbers"] == [2]
