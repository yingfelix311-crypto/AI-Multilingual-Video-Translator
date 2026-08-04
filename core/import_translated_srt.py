"""
Import an existing translated SRT and prepare VideoLingo for dubbing-only.

Skips Whisper / NLP / translation. Still converts video audio and (optionally)
runs Demucs so clone-mode TTS can use output/audio/refers/.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from core._1_ytdlp import find_media_file, write_input_manifest
from core.asr_backend.audio_preprocess import convert_video_to_audio, prepare_audio_for_asr
from core.asr_backend.demucs_vl import demucs_audio
from core.utils import load_key, rprint
from core.utils.models import (
    _AUDIO_DIR,
    _RAW_AUDIO_FILE,
    _TEXT_DONE_MARKER,
    _VOCAL_AUDIO_FILE,
)

OUTPUT_DIR = "output"
SRC_SRT = "output/src.srt"
TRANS_SRT = "output/trans.srt"
SRC_SUBS_FOR_AUDIO = "output/audio/src_subs_for_audio.srt"
TRANS_SUBS_FOR_AUDIO = "output/audio/trans_subs_for_audio.srt"
SUB_VIDEO = "output/output_sub.mp4"


def _srt_time_to_seconds(time_str):
    h, m, rest = time_str.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _seconds_to_srt_time(seconds):
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_blocks(content):
    blocks = []
    for raw in content.replace("\r\n", "\n").strip().split("\n\n"):
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        if len(lines) < 3:
            continue
        if "-->" not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split("-->")]
        text = "\n".join(lines[2:])
        blocks.append({"start": start, "end": end, "text": text})
    return blocks


def _blocks_to_srt(blocks):
    parts = []
    for i, block in enumerate(blocks, 1):
        parts.append(f"{i}\n{block['start']} --> {block['end']}\n{block['text']}")
    return "\n\n".join(parts) + ("\n" if parts else "")


def _clip_blocks_to_duration(blocks, media_dur):
    """Keep only cues within media duration; clamp the last overlapping cue."""
    kept = []
    dropped = 0
    for block in blocks:
        start = _srt_time_to_seconds(block["start"])
        end = _srt_time_to_seconds(block["end"])
        if start >= media_dur:
            dropped += 1
            continue
        new_block = dict(block)
        if end > media_dur:
            new_block["end"] = _seconds_to_srt_time(media_dur)
        kept.append(new_block)
    return kept, dropped

def _get_media_duration_seconds(media_path):
    import subprocess

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        media_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _ensure_media_in_output(video_path=None):
    """Return (media_path, media_type). Copy external video into output/ if needed."""
    try:
        return find_media_file()
    except Exception:
        pass

    if not video_path:
        raise FileNotFoundError("No media in output/. Provide video_path or upload a video first.")

    src = Path(video_path)
    if not src.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ext = src.suffix.lower().lstrip(".")
    allowed_video = load_key("allowed_video_formats")
    allowed_audio = load_key("allowed_audio_formats")
    if ext in allowed_video:
        media_type = "video"
    elif ext in allowed_audio:
        media_type = "audio"
    else:
        raise ValueError(f"Unsupported media extension: .{ext}")

    clean_name = re.sub(r"[^\w\-_\.]", "", src.stem.replace(" ", "_")) + src.suffix.lower()
    dst = Path(OUTPUT_DIR) / clean_name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    write_input_manifest(str(dst), media_type)
    return str(dst), media_type


def _write_placeholder_sub_video():
    """Satisfy UI/text_done checks without burning subtitles."""
    if os.path.exists(SUB_VIDEO):
        return
    import cv2
    import numpy as np

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(SUB_VIDEO, fourcc, 1, (1920, 1080))
    out.write(frame)
    out.release()


def import_translated_srt(
    trans_srt_path,
    src_srt_path=None,
    video_path=None,
    run_demucs=None,
):
    """
    Prepare dubbing-only workspace from an existing translated SRT.

    Always truncates SRT cues to the media duration.
    """
    media_path, media_type = _ensure_media_in_output(video_path)
    trans_path = Path(trans_srt_path)
    if not trans_path.is_file():
        raise FileNotFoundError(f"Translated SRT not found: {trans_srt_path}")

    content = trans_path.read_text(encoding="utf-8")
    blocks = _parse_srt_blocks(content)
    if not blocks:
        raise ValueError("No valid subtitle blocks found in translated SRT.")

    media_dur = _get_media_duration_seconds(media_path)
    original_count = len(blocks)
    srt_end = _srt_time_to_seconds(blocks[-1]["end"])
    blocks, dropped = _clip_blocks_to_duration(blocks, media_dur)
    if not blocks:
        raise ValueError("After clipping to media duration, no subtitle cues remain.")
    if dropped or srt_end > media_dur + 0.05:
        rprint(
            f"[yellow]⚠️ SRT longer than media ({srt_end:.1f}s > {media_dur:.1f}s). "
            f"Auto-truncated: kept {len(blocks)}/{original_count}, dropped {dropped}.[/yellow]"
        )

    srt_text = _blocks_to_srt(blocks)
    os.makedirs(_AUDIO_DIR, exist_ok=True)

    # Source SRT: use provided file, else reuse translated text with same timing
    if src_srt_path and Path(src_srt_path).is_file():
        src_blocks = _parse_srt_blocks(Path(src_srt_path).read_text(encoding="utf-8"))
        src_blocks, _ = _clip_blocks_to_duration(src_blocks, media_dur)
        # Align count to translated blocks by timestamps order
        if len(src_blocks) != len(blocks):
            rprint(
                f"[yellow]⚠️ Source SRT cue count ({len(src_blocks)}) != "
                f"translated count ({len(blocks)}). Falling back to mirrored trans SRT.[/yellow]"
            )
            src_text = srt_text
        else:
            # Keep source text, force timing from translated blocks for alignment
            merged = []
            for i, block in enumerate(blocks):
                merged.append(
                    {
                        "start": block["start"],
                        "end": block["end"],
                        "text": src_blocks[i]["text"],
                    }
                )
            src_text = _blocks_to_srt(merged)
    else:
        rprint("[blue]No source SRT provided; mirroring translated SRT as src.[/blue]")
        src_text = srt_text

    Path(TRANS_SRT).write_text(srt_text, encoding="utf-8")
    Path(SRC_SRT).write_text(src_text, encoding="utf-8")
    Path(TRANS_SUBS_FOR_AUDIO).write_text(srt_text, encoding="utf-8")
    Path(SRC_SUBS_FOR_AUDIO).write_text(src_text, encoding="utf-8")

    try:
        speaker_tagging_enabled = bool(load_key("speaker_tagging.enabled"))
    except KeyError:
        speaker_tagging_enabled = False
    if speaker_tagging_enabled:
        from core.speaker_tagging import tag_srt_speakers
        tag_srt_speakers(TRANS_SRT)

    if media_type == "video":
        convert_video_to_audio(media_path)
        _write_placeholder_sub_video()
    else:
        prepare_audio_for_asr(media_path)

    if run_demucs is None:
        run_demucs = bool(load_key("demucs"))
    if run_demucs:
        if not os.path.exists(_RAW_AUDIO_FILE):
            raise FileNotFoundError(f"Missing {_RAW_AUDIO_FILE} before Demucs.")
        demucs_audio()
    else:
        # Clone mode can still fall back to raw audio via demucs_audio later;
        # keep vocal path available by copying raw if demucs disabled.
        if not os.path.exists(_VOCAL_AUDIO_FILE):
            shutil.copy2(_RAW_AUDIO_FILE, _VOCAL_AUDIO_FILE)

    Path(_TEXT_DONE_MARKER).parent.mkdir(parents=True, exist_ok=True)
    Path(_TEXT_DONE_MARKER).write_text("imported_translated_srt\n", encoding="utf-8")

    summary = {
        "media_path": media_path,
        "media_type": media_type,
        "media_duration": media_dur,
        "cue_count": len(blocks),
        "dropped_cues": dropped,
        "trans_srt": TRANS_SRT,
        "src_srt": SRC_SRT,
        "vocal_ready": os.path.exists(_VOCAL_AUDIO_FILE),
    }
    rprint(
        f"[green]✅ Import ready for dubbing: {summary['cue_count']} cues, "
        f"media {summary['media_duration']:.1f}s"
        + (f", dropped {dropped} out-of-range cues" if dropped else "")
        + "[/green]"
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import translated SRT for dubbing-only")
    parser.add_argument("--trans-srt", required=True)
    parser.add_argument("--src-srt", default=None)
    parser.add_argument("--video", default=None)
    parser.add_argument("--no-demucs", action="store_true")
    args = parser.parse_args()
    import_translated_srt(
        trans_srt_path=args.trans_srt,
        src_srt_path=args.src_srt,
        video_path=args.video,
        run_demucs=False if args.no_demucs else None,
    )
