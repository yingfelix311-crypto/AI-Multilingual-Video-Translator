import datetime

import pandas as pd


def _time(h=0, m=0, s=0, ms=0):
    return datetime.time(h, m, s, ms * 1000)


def _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=0.0, confidence=0.8):
    from core import _8_1_audio_task as audio_task

    monkeypatch.setattr(audio_task, "load_key", lambda key: {
        "speaker_tagging.min_confidence": confidence,
        "speaker_tagging.refer_merge_max_gap": refer_gap,
        "speaker_tagging.tts_merge_max_gap": tts_gap,
    }.get(key, 0))


def _two_cues():
    return pd.DataFrame(
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


def _tags(force_unmerge=False):
    return {
        1: {"speaker": "alice", "confidence": 0.95, "merge_with_previous": False, "manual_override": True},
        2: {
            "speaker": "alice",
            "confidence": 0.95,
            "merge_with_previous": False,
            "force_unmerge": force_unmerge,
            "manual_override": True,
        },
    }


def test_refer_merge_without_tts_text_merge(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=0.0)
    annotated = audio_task._annotate_speaker_cues(_two_cues(), _tags())
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is True
    assert bool(annotated.iloc[1]["tts_merge_with_previous"]) is False
    assert list(merged["number"]) == [1, 2]
    assert merged.iloc[0]["text"] == "Hello one"
    assert merged.iloc[1]["text"] == "Hello two"


def test_tts_text_merge_within_tts_gap(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=1.0)
    annotated = audio_task._annotate_speaker_cues(_two_cues(), _tags())
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is True
    assert bool(annotated.iloc[1]["tts_merge_with_previous"]) is True
    assert list(merged["number"]) == [1]
    assert merged.iloc[0]["source_numbers"] == [1, 2]
    assert merged.iloc[0]["text"] == "Hello one Hello two"


def test_force_unmerge_blocks_both(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=1.0)
    annotated = audio_task._annotate_speaker_cues(_two_cues(), _tags(force_unmerge=True))
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is False
    assert bool(annotated.iloc[1]["tts_merge_with_previous"]) is False
    assert list(merged["number"]) == [1, 2]


def test_refer_gap_can_be_looser_than_tts_gap(monkeypatch):
    from core import _8_1_audio_task as audio_task

    # 0.9s gap: refer allows 1.0s, tts allows 0.3s
    _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=0.3)
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
                "start_time": _time(s=2, ms=900),
                "end_time": _time(s=4),
                "duration": 1.1,
                "text": "Hello two",
                "origin": "B",
            },
        ]
    )
    annotated = audio_task._annotate_speaker_cues(df, _tags())
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is True
    assert bool(annotated.iloc[1]["tts_merge_with_previous"]) is False
    assert list(merged["number"]) == [1, 2]


def test_different_speakers_never_merge_even_within_gap(monkeypatch):
    from core import _8_1_audio_task as audio_task

    _patch_gaps(monkeypatch, refer_gap=1.0, tts_gap=1.0)
    df = _two_cues()
    tags = {
        1: {"speaker": "alice", "confidence": 0.95, "manual_override": True},
        2: {"speaker": "bob", "confidence": 0.95, "manual_override": True},
    }
    annotated = audio_task._annotate_speaker_cues(df, tags)
    merged = audio_task._merge_tts_by_speaker_gap(annotated)

    assert bool(annotated.iloc[1]["reference_merge_with_previous"]) is False
    assert bool(annotated.iloc[1]["tts_merge_with_previous"]) is False
    assert list(merged["number"]) == [1, 2]
    assert merged.iloc[0]["text"] == "Hello one"
    assert merged.iloc[1]["text"] == "Hello two"
