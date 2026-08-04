"""
Dubbing pipeline stages exposed to the web UI.

The prepare stage turns an existing translated SRT plus the source video into
per-cue TTS tasks and reference audio; the dub stage synthesizes, merges and
masters. They are separate so re-dubbing with another TTS engine skips Demucs
and LLM speaker tagging.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.utils.models import _8_1_AUDIO_TASK, _AUDIO_DONE_MARKER, _TEXT_DONE_MARKER
from webui.workspace import UPLOAD_SRC_SRT, UPLOAD_TRANS_SRT


def _drop(path):
    Path(path).unlink(missing_ok=True)


PREPARE_LABELS = [
    "导入字幕、标记人物并分离人声",
    "按人物合并并生成配音任务",
    "切分逐句参考音频",
]

DUB_LABELS = [
    "逐句克隆并合成配音",
    "按时间轴拼接完整音轨",
    "混音、响度母带并输出成片",
]

STAGES = [
    {
        "name": "prepare",
        "eyebrow": "STAGE 01",
        "title": "准备素材",
        "desc": "对齐字幕与视频时长，标记人物，分离人声并切出逐句参考音频。",
        "action": "开始准备",
        "steps": PREPARE_LABELS,
    },
    {
        "name": "dub",
        "eyebrow": "STAGE 02",
        "title": "生成配音",
        "desc": "逐句克隆合成、按时间轴拼接，再做响度母带并封装成片。",
        "action": "开始配音",
        "steps": DUB_LABELS,
    },
]


# ------------
# Stage 1: prepare
# ------------


def prepare_steps():
    if not UPLOAD_TRANS_SRT.is_file():
        raise FileNotFoundError("还没有上传译文 SRT。")

    src_srt = str(UPLOAD_SRC_SRT) if UPLOAD_SRC_SRT.is_file() else None

    def step_import():
        from core.import_translated_srt import import_translated_srt

        _drop(_AUDIO_DONE_MARKER)
        _drop(_TEXT_DONE_MARKER)
        import_translated_srt(trans_srt_path=str(UPLOAD_TRANS_SRT), src_srt_path=src_srt)

    def step_tasks():
        from core import _8_1_audio_task, _8_2_dub_chunks

        _drop(_8_1_AUDIO_TASK)
        _8_1_audio_task.gen_audio_task_main()
        _8_2_dub_chunks.gen_dub_chunks()

    def step_refers():
        from core import _9_refer_audio

        _9_refer_audio.extract_refer_audio_main()

    return list(zip(PREPARE_LABELS, [step_import, step_tasks, step_refers]))


# ------------
# Stage 2: dub
# ------------


def dub_steps(force=True):
    if not Path(_8_1_AUDIO_TASK).is_file():
        raise FileNotFoundError("还没有配音任务，先跑一次准备阶段。")

    def step_tts():
        from core import _10_gen_audio

        _drop(_AUDIO_DONE_MARKER)
        _10_gen_audio.gen_audio(force=force)

    def step_merge():
        from core import _11_merge_audio

        _11_merge_audio.merge_full_audio()

    def step_master():
        from core import _12_dub_to_vid

        _12_dub_to_vid.merge_video_audio()
        Path(_AUDIO_DONE_MARKER).write_text("webui\n", encoding="utf-8")

    return list(zip(DUB_LABELS, [step_tts, step_merge, step_master]))


# ------------
# Workspace reset
# ------------


def archive_workspace():
    from core.utils.onekeycleanup import cleanup

    cleanup()
    for path in (UPLOAD_TRANS_SRT, UPLOAD_SRC_SRT):
        _drop(path)
    os.makedirs("output", exist_ok=True)
