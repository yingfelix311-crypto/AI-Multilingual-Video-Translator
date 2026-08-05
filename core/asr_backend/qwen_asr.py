"""
Qwen ASR backend compatible with core/_2_asr.transcribe().

Returns WhisperX-shaped segments with per-character/word timestamps so
downstream cleaned_chunks.xlsx generation stays unchanged.
"""

from __future__ import annotations

import json
import os

from rich import print as rprint

from core.qwen_align import align_audio_segment
from core.utils import *


def _cache_signature(language):
    def cfg(key, default=None):
        try:
            return load_key(f"qwen_asr.{key}")
        except KeyError:
            return default

    return {
        "model": str(cfg("model", "qwen3-asr-flash-filetrans")),
        "language": language,
        "diarization": bool(cfg("diarization", False)),
    }


def transcribe_audio_qwen(raw_audio_path, vocal_audio_path, start=None, end=None):
    rprint(
        f"[cyan]🎤 Qwen ASR segment {start}-{end}, "
        f"file: {vocal_audio_path}[/cyan]"
    )
    if start is None or end is None:
        raise ValueError("Qwen ASR requires start/end segment bounds")

    language = None
    try:
        language = load_key("qwen_asr.language")
    except KeyError:
        language = load_key("whisper.language")

    signature = _cache_signature(language)
    log_file = f"output/log/qwen_transcribe_{start}_{end}.json"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if cached.get("signature") == signature:
            return cached
        rprint("[yellow]⚠️ Qwen ASR cache signature changed, re-transcribing[/yellow]")

    result = align_audio_segment(
        vocal_audio_path,
        float(start),
        float(end),
        language=language,
    )

    os.makedirs("output/log", exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as handle:
        json.dump({**result, "signature": signature}, handle, ensure_ascii=False, indent=2)
    return result
