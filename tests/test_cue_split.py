import pytest

from core.cue_split import split_cue_time, split_origin_text


def _alignment(pairs):
    words = []
    for text, start, end in pairs:
        words.append({"text": text, "start": start, "end": end, "punctuation": ""})
    return {"words": words}


# "行者孙" 12.20-12.84 (king), "爷爷在此" 13.50-14.20 (monk)
CUE = _alignment(
    [
        ("行", 12.20, 12.52),
        ("者", 12.52, 12.60),
        ("孙", 12.60, 12.84),
        ("爷", 13.50, 13.70),
        ("爷", 13.70, 13.85),
        ("在", 13.85, 14.05),
        ("此", 14.05, 14.20),
    ]
)


def test_split_lands_on_word_boundary():
    left_end, right_start = split_cue_time(
        "行者孙，爷爷在此。", 12.2, 14.2, split_index=4, alignment=CUE
    )
    assert left_end == pytest.approx(12.84)
    assert right_start == pytest.approx(13.50)


def test_punctuation_offset_does_not_shift_the_cut():
    # split_index 3 sits before the comma, 4 sits after it: same word boundary.
    assert split_cue_time("行者孙，爷爷在此。", 12.2, 14.2, 3, CUE) == split_cue_time(
        "行者孙，爷爷在此。", 12.2, 14.2, 4, CUE
    )


def test_caret_inside_multi_char_token_snaps_forward():
    alignment = _alignment([("这里是", 0.0, 0.6), ("阿里巴巴", 0.8, 1.4)])
    left_end, right_start = split_cue_time("这里是阿里巴巴", 0.0, 1.4, 1, alignment)

    assert left_end == pytest.approx(0.6)
    assert right_start == pytest.approx(0.8)


def test_split_at_edges_is_rejected():
    with pytest.raises(ValueError, match="首尾"):
        split_cue_time("行者孙，爷爷在此。", 12.2, 14.2, 0, CUE)
    with pytest.raises(ValueError, match="首尾"):
        split_cue_time("行者孙，爷爷在此。", 12.2, 14.2, 99, CUE)


def test_missing_alignment_is_reported():
    with pytest.raises(ValueError, match="字级对齐"):
        split_cue_time("行者孙", 0.0, 1.0, 1, {"words": []})


def test_words_outside_the_cue_window_are_ignored():
    alignment = _alignment(
        [
            ("别", 0.0, 0.3),
            ("的", 0.3, 0.6),
            ("行", 12.20, 12.52),
            ("者", 12.52, 12.60),
            ("孙", 12.60, 12.84),
            ("爷", 13.50, 13.70),
        ]
    )
    left_end, right_start = split_cue_time("行者孙爷", 12.2, 13.7, 3, alignment)

    assert left_end == pytest.approx(12.84)
    assert right_start == pytest.approx(13.50)


def test_edited_text_that_drifted_from_asr_still_splits():
    # Source text no longer matches the transcript; must not raise.
    left_end, right_start = split_cue_time("完全不同的四个字", 12.2, 14.2, 4, CUE)

    # Adjacent words carry no silence between them, so the halves may touch.
    assert 12.2 <= left_end <= right_start <= 14.2


def test_split_origin_text_trims_halves():
    assert split_origin_text("行者孙， 爷爷在此。", 4) == ("行者孙，", "爷爷在此。")
