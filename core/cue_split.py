"""
Map a caret position in a cue's source-language text onto an audio timestamp.

Manual re-splitting should not require typing timestamps. The words that fall
inside the cue window are concatenated using the same punctuation stripping that
subtitle generation uses, so a character offset in the source text lands on a
word boundary and therefore on a time.
"""

from __future__ import annotations

import re

from core.qwen_align import load_char_alignment

MIN_WORD_DURATION = 0.04
WINDOW_PAD = 0.25


# ------------
# Text normalization
# ------------


def _normalize(text):
    stripped = re.sub(r"\s+", "", str(text))
    return re.sub(r"[^\w]", "", stripped, flags=re.UNICODE).lower()


def _words_in_window(words, start, end):
    selected = []
    for word in words:
        word_start = float(word["start"])
        word_end = max(float(word["end"]), word_start + MIN_WORD_DURATION)
        middle = (word_start + word_end) / 2
        if start - WINDOW_PAD <= middle <= end + WINDOW_PAD:
            selected.append((word_start, word_end, str(word.get("text") or "")))
    return selected


def _position_map(selected):
    concat = ""
    owners = []
    for index, (_, _, text) in enumerate(selected):
        piece = _normalize(text)
        concat += piece
        owners.extend([index] * len(piece))
    return concat, owners


# ------------
# Public API
# ------------


def split_cue_time(origin, start, end, split_index, alignment=None):
    """
    Return (left_end, right_start) in seconds for a split inside the source text.

    The gap between the two values is real silence between the utterances, so the
    halves stay non-contiguous on purpose.
    """
    payload = alignment if alignment is not None else load_char_alignment()
    words = (payload or {}).get("words") or []
    if not words:
        raise ValueError("缺少字级对齐数据，无法自动匹配时间戳")

    whole = _normalize(origin)
    prefix = _normalize(str(origin)[:split_index])
    if not prefix or len(prefix) >= len(whole):
        raise ValueError("分句点必须落在源文中间，不能在首尾")

    selected = _words_in_window(words, float(start), float(end))
    concat, owners = _position_map(selected)
    if not concat:
        raise ValueError("该字幕的时间范围内没有对齐到任何字词")

    # The cue text can drift from the ASR transcript after manual edits; when it
    # no longer matches, fall back to counting from the start of the window.
    offset = concat.find(whole)
    if offset < 0:
        offset = 0
    cut = offset + len(prefix)
    if cut <= 0 or cut >= len(owners):
        raise ValueError("分句点无法映射到音频时间")

    left_word = owners[cut - 1]
    right_word = owners[cut]
    if right_word == left_word:
        # Caret landed inside a multi-character token; keep that token on the left.
        right_word = left_word + 1
        if right_word >= len(selected):
            raise ValueError("分句点无法映射到音频时间")

    left_end = min(selected[right_word - 1][1], float(end))
    right_start = max(selected[right_word][0], float(start))
    if right_start < left_end:
        right_start = left_end
    return left_end, right_start


def split_origin_text(origin, split_index):
    text = str(origin)
    return text[:split_index].strip(), text[split_index:].strip()
