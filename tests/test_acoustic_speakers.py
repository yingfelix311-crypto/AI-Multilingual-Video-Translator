import json

import pandas as pd
import pytest

from core.speaker_tagging import (
    _build_naming_prompt,
    _cue_cluster_ids,
    _load_acoustic_words,
    _srt_time_to_seconds,
    _tag_from_clusters,
    _validate_naming_response,
)


def _cue(number, start, end):
    return {"cue": number, "start": start, "end": end, "text": f"line {number}"}


def test_srt_time_to_seconds():
    assert _srt_time_to_seconds("00:00:06,560") == pytest.approx(6.56)
    assert _srt_time_to_seconds("00:01:30.939") == pytest.approx(90.939)


def test_cue_cluster_uses_dominant_overlap():
    cues = [_cue(1, "00:00:00,000", "00:00:02,000"), _cue(2, "00:00:02,000", "00:00:04,000")]
    words = [
        (0.0, 1.8, 0),
        (1.8, 2.1, 1),
        (2.2, 3.9, 1),
    ]
    assert _cue_cluster_ids(cues, words) == {1: 0, 2: 1}


def test_zero_duration_word_still_votes():
    cues = [_cue(1, "00:00:00,000", "00:00:01,000")]
    words = [(0.5, 0.5, 3)]
    assert _cue_cluster_ids(cues, words) == {1: 3}


def test_naming_prompt_groups_lines_by_cluster():
    cues = [_cue(1, "00:00:00,000", "00:00:01,000"), _cue(2, "00:00:01,000", "00:00:02,000")]
    prompt = _build_naming_prompt(cues, {1: 0, 2: 1})

    assert "cluster 0 (1 lines)" in prompt
    assert "cluster 1 (1 lines)" in prompt
    assert "Cover exactly these cluster ids: 0, 1" in prompt


def test_naming_response_rejects_duplicate_names():
    response = {"speakers": [{"cluster": 0, "name": "king"}, {"cluster": 1, "name": "king"}]}
    assert _validate_naming_response(response, [0, 1])["status"] == "error"


def test_naming_response_rejects_missing_cluster():
    response = {"speakers": [{"cluster": 0, "name": "king"}]}
    assert _validate_naming_response(response, [0, 1])["status"] == "error"


def test_naming_response_accepts_complete_unique_names():
    response = {"speakers": [{"cluster": 1, "name": "monk"}, {"cluster": 0, "name": "king"}]}
    assert _validate_naming_response(response, [0, 1])["status"] == "success"


def test_tag_from_clusters_never_merges_across_speakers(monkeypatch):
    import core.speaker_tagging as tagging

    monkeypatch.setattr(
        tagging,
        "_name_clusters",
        lambda cues, clusters: {0: ("silver_horned_king", "r0"), 1: ("sun_wukong", "r1")},
    )
    cues = [
        _cue(1, "00:00:00,000", "00:00:02,000"),
        _cue(2, "00:00:02,000", "00:00:04,000"),
        _cue(3, "00:00:04,000", "00:00:06,000"),
    ]
    # Audio says cue 2 is a different person than cues 1 and 3.
    items = _tag_from_clusters(cues, {1: 0, 2: 1, 3: 0})

    assert [i["speaker"] for i in items] == ["silver_horned_king", "sun_wukong", "silver_horned_king"]
    assert [i["merge_with_previous"] for i in items] == [False, False, False]
    assert all(i["confidence"] == 1.0 for i in items)


def test_tag_from_clusters_hints_merge_within_one_speaker(monkeypatch):
    import core.speaker_tagging as tagging

    monkeypatch.setattr(tagging, "_name_clusters", lambda cues, clusters: {0: ("monk", "r")})
    cues = [_cue(1, "00:00:00,000", "00:00:02,000"), _cue(2, "00:00:02,000", "00:00:04,000")]

    items = _tag_from_clusters(cues, {1: 0, 2: 0})

    assert [i["merge_with_previous"] for i in items] == [False, True]


def test_tag_from_clusters_marks_uncovered_cue_unknown(monkeypatch):
    import core.speaker_tagging as tagging

    monkeypatch.setattr(tagging, "_name_clusters", lambda cues, clusters: {0: ("monk", "r")})
    cues = [_cue(1, "00:00:00,000", "00:00:02,000"), _cue(2, "00:00:02,000", "00:00:04,000")]

    items = _tag_from_clusters(cues, {1: 0})

    assert items[1]["speaker"] == "unknown_2"
    assert items[1]["confidence"] == 0.0


def test_load_acoustic_words_skips_missing_speaker(tmp_path):
    path = tmp_path / "cleaned_chunks.xlsx"
    pd.DataFrame(
        {
            "text": ['"a"', '"b"', '"c"'],
            "start": [0.0, 0.5, 1.0],
            "end": [0.4, 0.9, 1.0],
            "speaker_id": [0, None, 1],
        }
    ).to_excel(path, index=False)

    words = _load_acoustic_words(path)

    assert words == [(0.0, 0.4, 0), (1.0, 1.0, 1)]


def test_load_acoustic_words_falls_back_to_char_alignment(tmp_path, monkeypatch):
    from core import speaker_tagging

    alignment = tmp_path / "char_alignment.json"
    alignment.write_text(
        json.dumps(
            {
                "words": [
                    {"text": "嗯", "start": 1.0, "end": 1.2, "speaker_id": 0},
                    {"text": "哈", "start": 2.0, "end": 2.1, "speaker_id": 1},
                    {"text": "无", "start": 3.0, "end": 3.1},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        speaker_tagging,
        "_load_acoustic_words_from_chunks",
        lambda path=None: [],
    )
    monkeypatch.setattr(
        "core.qwen_align.load_char_alignment",
        lambda: json.loads(alignment.read_text(encoding="utf-8")),
    )

    words = _load_acoustic_words(tmp_path / "missing.xlsx")

    assert words == [(1.0, 1.2, 0), (2.0, 2.1, 1)]
