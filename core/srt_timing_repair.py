"""
Snap imported SRT cue windows to character-level alignment timestamps.

Only timing changes; cue text is never rewritten. Decisions are persisted in
alignment_mode.json so mastering can choose the best or conservative path.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from rich import print as rprint

from core.qwen_align import load_char_alignment
from core.utils.models import (
    _8_1_AUDIO_TASK,
    _ALIGNMENT_MODE_FILE,
    _AUDIO_CANDIDATES_DIR,
    _AUDIO_SEGS_DIR,
    _AUDIO_TMP_DIR,
    _SRT_TIMING_PROPOSAL_FILE,
)

SRC_SRT = Path("output/src.srt")
TRANS_SRT = Path("output/trans.srt")
SRC_AUDIO_SRT = Path("output/audio/src_subs_for_audio.srt")
TRANS_AUDIO_SRT = Path("output/audio/trans_subs_for_audio.srt")
UPLOAD_SRC_SRT = Path("output/_import_src.srt")
UPLOAD_TRANS_SRT = Path("output/_import_trans.srt")

_SRT_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})")


# ------------
# Time helpers
# ------------


def _parse_srt_seconds(value):
    match = _SRT_TIME_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError(f"Invalid SRT time: {value}")
    hours, minutes, seconds, millis = match.groups()
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis.ljust(3, "0")) / 1000
    )


def _format_srt_seconds(seconds):
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total_ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _parse_srt_cues(path):
    file = Path(path)
    if not file.is_file():
        return []
    cues = []
    for block in file.read_text(encoding="utf-8").replace("\r\n", "\n").strip().split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split("-->")]
        cues.append(
            {
                "cue": int(lines[0]),
                "start": start,
                "end": end,
                "text": "\n".join(lines[2:]),
            }
        )
    return cues


def _cues_to_srt(cues):
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{cue['start']} --> {cue['end']}\n{cue['text']}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _atomic_write_many(contents):
    staged = []
    try:
        for path, content in contents.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
            temp.write_text(content, encoding="utf-8")
            staged.append((temp, path))
        for temp, path in staged:
            temp.replace(path)
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)


def _clear_dir(path):
    directory = Path(path)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)


# ------------
# Alignment mode
# ------------


def read_alignment_mode():
    path = Path(_ALIGNMENT_MODE_FILE)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_alignment_mode(mode, source="manual"):
    if mode not in {"aligned", "conservative"}:
        raise ValueError(f"Unknown alignment mode: {mode}")
    payload = {"mode": mode, "source": source}
    path = Path(_ALIGNMENT_MODE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# ------------
# Propose / apply
# ------------


def _words_for_cue(words, start, end, prev_end=None, next_start=None, pad=0.25):
    """Assign characters by midpoint, clipped by neighboring cue midpoints."""
    lo = start - pad
    hi = end + pad
    if prev_end is not None:
        lo = max(lo, (prev_end + start) / 2)
    if next_start is not None:
        hi = min(hi, (end + next_start) / 2)
    selected = []
    for word in words:
        word_start = float(word["start"])
        word_end = float(word["end"])
        if word_end <= word_start:
            word_end = word_start + 0.04
        mid = (word_start + word_end) / 2
        if lo <= mid <= hi:
            selected.append(word)
    return selected


def propose_repair(alignment=None):
    """
    Build a non-destructive timing proposal for every cue in trans.srt.

    Each cue start snaps to the first overlapping char start; end snaps to the
    last overlapping char end. Text is untouched.
    """
    alignment = alignment or load_char_alignment()
    if not alignment or not alignment.get("words"):
        raise FileNotFoundError(
            f"Character alignment missing: {_CHAR_ALIGNMENT_MISSING}"
        )

    trans_cues = _parse_srt_cues(TRANS_SRT)
    src_cues = _parse_srt_cues(SRC_SRT)
    if not trans_cues:
        raise FileNotFoundError(f"Translated SRT missing: {TRANS_SRT}")

    words = alignment["words"]
    cue_bounds = [
        (_parse_srt_seconds(cue["start"]), _parse_srt_seconds(cue["end"]))
        for cue in trans_cues
    ]
    items = []
    changed = 0
    for index, cue in enumerate(trans_cues):
        old_start, old_end = cue_bounds[index]
        prev_end = cue_bounds[index - 1][1] if index > 0 else None
        next_start = cue_bounds[index + 1][0] if index + 1 < len(cue_bounds) else None
        overlapping = _words_for_cue(
            words, old_start, old_end, prev_end=prev_end, next_start=next_start
        )
        if overlapping:
            new_start = float(overlapping[0]["start"])
            new_end = float(overlapping[-1]["end"])
            if new_end <= new_start:
                new_end = new_start + 0.04
        else:
            new_start, new_end = old_start, old_end

        start_delta = new_start - old_start
        end_delta = new_end - old_end
        is_changed = abs(start_delta) >= 0.02 or abs(end_delta) >= 0.02
        if is_changed:
            changed += 1

        src_text = src_cues[index]["text"] if index < len(src_cues) else cue["text"]
        items.append(
            {
                "cue": cue["cue"],
                "text": cue["text"],
                "origin": src_text,
                "old_start": old_start,
                "old_end": old_end,
                "new_start": new_start,
                "new_end": new_end,
                "start_delta": start_delta,
                "end_delta": end_delta,
                "changed": is_changed,
                "matched_words": len(overlapping),
            }
        )

    proposal = {
        "items": items,
        "changed_count": changed,
        "cue_count": len(items),
        "word_count": len(words),
    }
    out = Path(_SRT_TIMING_PROPOSAL_FILE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    rprint(
        f"[green]✅ Timing proposal: {changed}/{len(items)} cues would move "
        f"-> {out}[/green]"
    )
    return proposal


_CHAR_ALIGNMENT_MISSING = "output/log/char_alignment.json"


def load_proposal():
    path = Path(_SRT_TIMING_PROPOSAL_FILE)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def apply_repair(proposal=None, rebuild_tasks=True):
    """Apply proposed cue timings to all SRT mirrors and optionally rebuild tasks."""
    proposal = proposal or load_proposal() or propose_repair()
    items = proposal.get("items") or []
    if not items:
        raise ValueError("Empty timing proposal")

    trans_cues = _parse_srt_cues(TRANS_SRT)
    src_cues = _parse_srt_cues(SRC_SRT)
    if len(trans_cues) != len(items):
        raise ValueError(
            f"Proposal cue count ({len(items)}) != trans.srt ({len(trans_cues)})"
        )

    new_trans = []
    new_src = []
    for index, item in enumerate(items):
        trans_cue = dict(trans_cues[index])
        src_cue = dict(src_cues[index]) if index < len(src_cues) else dict(trans_cues[index])
        start = _format_srt_seconds(item["new_start"])
        end = _format_srt_seconds(item["new_end"])
        trans_cue["start"] = start
        trans_cue["end"] = end
        src_cue["start"] = start
        src_cue["end"] = end
        new_trans.append(trans_cue)
        new_src.append(src_cue)

    trans_content = _cues_to_srt(new_trans)
    src_content = _cues_to_srt(new_src)
    _atomic_write_many(
        {
            TRANS_SRT: trans_content,
            SRC_SRT: src_content,
            TRANS_AUDIO_SRT: trans_content,
            SRC_AUDIO_SRT: src_content,
            UPLOAD_TRANS_SRT: trans_content,
            UPLOAD_SRC_SRT: src_content,
        }
    )
    write_alignment_mode("aligned", source="repair")
    rprint(
        f"[green]✅ Applied timing repair to {proposal.get('changed_count', 0)} cues[/green]"
    )

    if rebuild_tasks:
        _rebuild_audio_tasks()
    return proposal


def skip_repair(rebuild_tasks=True):
    """Keep original cue timings and mark conservative mastering mode."""
    write_alignment_mode("conservative", source="skip")
    rprint("[yellow]⚠️ Keeping original SRT timings (conservative gap vocals)[/yellow]")
    if rebuild_tasks:
        _rebuild_audio_tasks()
    return read_alignment_mode()


def mark_aligned_from_asr():
    """Video-only path: subtitles already come from char-level ASR."""
    return write_alignment_mode("aligned", source="asr")


def _rebuild_audio_tasks():
    from core import _8_1_audio_task, _8_2_dub_chunks, _9_refer_audio
    from core.tts_backend.qwen_tts import tag_audio_tasks_emotions

    Path(_8_1_AUDIO_TASK).unlink(missing_ok=True)
    _clear_dir(_AUDIO_TMP_DIR)
    _clear_dir(_AUDIO_SEGS_DIR)
    _clear_dir(_AUDIO_CANDIDATES_DIR)
    _8_1_audio_task.gen_audio_task_main()
    _8_2_dub_chunks.gen_dub_chunks()
    tag_audio_tasks_emotions()
    _9_refer_audio.extract_refer_audio_main()
