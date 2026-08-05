"""
Dubbing pipeline stages exposed to the web UI.

Two prepare modes:
- import: video + translated SRT → Demucs → char align → user timing gate
- video_only: video only → Qwen ASR → translate → auto-aligned tasks
"""

from __future__ import annotations

import os
from pathlib import Path

from core.utils.models import (
    _8_1_AUDIO_TASK,
    _AUDIO_DONE_MARKER,
    _SUBTITLE_STALE_MARKER,
    _TEXT_DONE_MARKER,
)
from webui.workspace import UPLOAD_SRC_SRT, UPLOAD_TRANS_SRT, prepare_mode, read_media


def _drop(path):
    Path(path).unlink(missing_ok=True)


IMPORT_PREPARE_LABELS = [
    "导入字幕并分离人声",
    "字级对齐并生成时间提案",
    "按声学聚类标记人物",
]

VIDEO_ONLY_PREPARE_LABELS = [
    "转写人声并生成词级时间戳",
    "分句与翻译",
    "生成字幕并标记为已对齐",
    "生成配音任务与参考音频",
]

DUB_LABELS = [
    "逐句克隆并合成配音",
    "按时间轴拼接完整音轨",
    "混音、响度母带并输出成片",
]

REBUILD_SPEAKERS_LABELS = [
    "校验并保存人物标记，重建配音任务",
]

ALIGNMENT_APPLY_LABELS = [
    "按字级对齐修复字幕时间轴并重建任务",
]

ALIGNMENT_SKIP_LABELS = [
    "保持原时间轴并生成配音任务",
]


def stages_for_mode(mode=None):
    mode = mode or prepare_mode()
    if mode == "video_only":
        prepare = {
            "name": "prepare",
            "title": "准备素材（视频直入）",
            "desc": "仅需原视频：Qwen 转写、翻译、生成字幕，字级时间戳自动对齐后切出参考音频。",
            "action": "开始准备",
            "steps": VIDEO_ONLY_PREPARE_LABELS,
            "mode": "video_only",
        }
    else:
        prepare = {
            "name": "prepare",
            "title": "准备素材（导入字幕）",
            "desc": "导入译文 SRT，分离人声后做字级对齐，并用对齐里的说话人聚类标记人物；随后可选择是否修复时间轴。",
            "action": "开始准备",
            "steps": IMPORT_PREPARE_LABELS,
            "mode": "import",
        }
    return [
        prepare,
        {
            "name": "dub",
            "title": "生成配音",
            "desc": "逐句克隆合成、按时间轴拼接，再做响度母带并封装成片。",
            "action": "开始配音",
            "steps": DUB_LABELS,
            "mode": mode,
        },
    ]


# Keep a default for import-time consumers; /api/stages recomputes dynamically.
STAGES = stages_for_mode("import")


# ------------
# Stage 1: prepare
# ------------


def prepare_steps():
    if not read_media():
        raise FileNotFoundError("还没有上传原视频或音频。")

    mode = prepare_mode()
    if mode == "import":
        return _import_prepare_steps()
    return _video_only_prepare_steps()


def _import_prepare_steps():
    src_srt = str(UPLOAD_SRC_SRT) if UPLOAD_SRC_SRT.is_file() else None

    def step_import():
        from core.import_translated_srt import import_translated_srt
        from core.utils.models import _ALIGNMENT_MODE_FILE, _SRT_TIMING_PROPOSAL_FILE

        _drop(_AUDIO_DONE_MARKER)
        _drop(_TEXT_DONE_MARKER)
        _drop(_ALIGNMENT_MODE_FILE)
        _drop(_SRT_TIMING_PROPOSAL_FILE)
        _drop(_8_1_AUDIO_TASK)
        import_translated_srt(trans_srt_path=str(UPLOAD_TRANS_SRT), src_srt_path=src_srt)

    def step_align():
        from core.qwen_align import align_audio
        from core.srt_timing_repair import propose_repair
        from core.utils.models import _VOCAL_AUDIO_FILE

        align_audio(_VOCAL_AUDIO_FILE, force=False)
        propose_repair()

    def step_speakers():
        from core.speaker_tagging import tag_srt_speakers
        from core.utils import load_key
        from webui.workspace import TRANS_SRT

        try:
            enabled = bool(load_key("speaker_tagging.enabled"))
        except KeyError:
            enabled = False
        if not enabled:
            return
        # force=True so a stale text-only tag file from older runs is replaced
        # once acoustic diarization from this alignment is available.
        tag_srt_speakers(TRANS_SRT, force=True)

    return list(zip(IMPORT_PREPARE_LABELS, [step_import, step_align, step_speakers]))


def _video_only_prepare_steps():
    def step_asr():
        from core import _2_asr
        from core.utils import load_key, update_key
        from core.utils.models import _ALIGNMENT_MODE_FILE, _SRT_TIMING_PROPOSAL_FILE

        from core.utils.models import (
            _2_CLEANED_CHUNKS,
            _3_1_SPLIT_BY_NLP,
            _3_2_SPLIT_BY_MEANING,
            _4_1_TERMINOLOGY,
            _4_2_TRANSLATION,
            _5_SPLIT_SUB,
            _5_REMERGED,
            _CHAR_ALIGNMENT_FILE,
        )

        _drop(_AUDIO_DONE_MARKER)
        _drop(_TEXT_DONE_MARKER)
        _drop(_ALIGNMENT_MODE_FILE)
        _drop(_SRT_TIMING_PROPOSAL_FILE)
        _drop(_CHAR_ALIGNMENT_FILE)
        _drop(_8_1_AUDIO_TASK)
        for path in (
            _2_CLEANED_CHUNKS,
            _3_1_SPLIT_BY_NLP,
            _3_2_SPLIT_BY_MEANING,
            _4_1_TERMINOLOGY,
            _4_2_TRANSLATION,
            _5_SPLIT_SUB,
            _5_REMERGED,
        ):
            _drop(path)
        # Video-only best path requires character timestamps from Qwen.
        try:
            runtime = load_key("whisper.runtime")
        except KeyError:
            runtime = None
        if runtime != "qwen":
            update_key("whisper.runtime", "qwen")
        _2_asr.transcribe()

    def step_split_translate():
        from core import _3_1_split_nlp, _3_2_split_meaning, _4_1_summarize, _4_2_translate

        _3_1_split_nlp.split_by_spacy()
        _3_2_split_meaning.split_sentences_by_meaning()
        _4_1_summarize.get_summary()
        _4_2_translate.translate_all()

    def step_subtitles():
        from core import _5_split_sub, _6_gen_sub
        from core.srt_timing_repair import mark_aligned_from_asr
        from core.utils.models import _2_CLEANED_CHUNKS, _CHAR_ALIGNMENT_FILE
        import json
        import pandas as pd

        _5_split_sub.split_for_sub_main()
        _6_gen_sub.align_timestamp_main()
        # Persist char alignment from cleaned chunks so mastering can mute precisely.
        if not Path(_2_CLEANED_CHUNKS).is_file():
            raise FileNotFoundError(_2_CLEANED_CHUNKS)
        df = pd.read_excel(_2_CLEANED_CHUNKS)
        words = []
        for _, row in df.iterrows():
            text = str(row.get("text", "")).strip().strip('"')
            if not text:
                continue
            words.append(
                {
                    "text": text,
                    "start": float(row["start"]),
                    "end": float(row["end"]),
                    "punctuation": "",
                }
            )
        Path(_CHAR_ALIGNMENT_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(_CHAR_ALIGNMENT_FILE).write_text(
            json.dumps(
                {
                    "signature": {
                        "model": "cleaned_chunks",
                        "language": "from_asr",
                        "audio_sha1": "from_asr",
                        "enable_words": True,
                    },
                    "words": words,
                    "sentences": [],
                    "source": "video_only_asr",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        mark_aligned_from_asr()
        Path(_TEXT_DONE_MARKER).write_text("video_only_qwen\n", encoding="utf-8")

    def step_tasks():
        from core import _8_1_audio_task, _8_2_dub_chunks, _9_refer_audio

        _drop(_8_1_AUDIO_TASK)
        _8_1_audio_task.gen_audio_task_main()
        _8_2_dub_chunks.gen_dub_chunks()
        _9_refer_audio.extract_refer_audio_main()

    return list(
        zip(
            VIDEO_ONLY_PREPARE_LABELS,
            [step_asr, step_split_translate, step_subtitles, step_tasks],
        )
    )


# ------------
# Alignment gate jobs
# ------------


def alignment_apply_steps():
    def step_apply():
        from core.srt_timing_repair import apply_repair

        apply_repair(rebuild_tasks=True)

    return list(zip(ALIGNMENT_APPLY_LABELS, [step_apply]))


def alignment_skip_steps():
    def step_skip():
        from core.srt_timing_repair import skip_repair

        skip_repair(rebuild_tasks=True)

    return list(zip(ALIGNMENT_SKIP_LABELS, [step_skip]))


# ------------
# Stage 2: dub
# ------------


def dub_steps(force=True):
    if not Path(_8_1_AUDIO_TASK).is_file():
        raise FileNotFoundError("还没有配音任务，先跑一次准备阶段并完成时间轴决策。")

    from core.srt_timing_repair import read_alignment_mode

    if prepare_mode() == "import" and not read_alignment_mode():
        raise RuntimeError("请先选择「按对齐修复」或「保持原时间轴」。")

    def step_tts():
        from core import _10_gen_audio
        from webui.editing import CANDIDATE_DIR, clear_merge_pending
        import shutil

        _drop(_AUDIO_DONE_MARKER)
        clear_merge_pending()
        if CANDIDATE_DIR.exists():
            shutil.rmtree(CANDIDATE_DIR, ignore_errors=True)
        _10_gen_audio.gen_audio(force=force)

    def step_merge():
        from core import _11_merge_audio

        _11_merge_audio.merge_full_audio()

    def step_master():
        from core import _12_dub_to_vid

        _12_dub_to_vid.merge_video_audio()
        Path(_AUDIO_DONE_MARKER).write_text("webui\n", encoding="utf-8")
        _drop(_SUBTITLE_STALE_MARKER)

    return list(zip(DUB_LABELS, [step_tts, step_merge, step_master]))


# ------------
# Manual edits
# ------------


def rebuild_speakers_steps(items):
    from webui.editing import rebuild_speaker_steps

    return rebuild_speaker_steps(items)


def rebuild_cues_steps(items, media_duration=None, keep_original=None):
    from webui.editing import rebuild_cue_steps

    return rebuild_cue_steps(
        items, media_duration=media_duration, keep_original=keep_original
    )


def selective_dub_steps(task_numbers):
    from webui.editing import selective_dub_steps as _steps

    return _steps(task_numbers)


def candidate_steps(task_number, count=1, force_shorten=False):
    from webui.editing import generate_candidate_steps

    return generate_candidate_steps(
        task_number,
        count=count,
        force_shorten=force_shorten,
    )


def remaster_steps():
    from webui.editing import remaster_steps as _steps

    return _steps()


# ------------
# Workspace reset
# ------------


def archive_workspace():
    from core.utils.onekeycleanup import cleanup
    from webui.editing import CANDIDATE_DIR, clear_merge_pending
    from core.utils.api_usage import clear_usage
    from core.utils.models import (
        _ALIGNMENT_MODE_FILE,
        _CHAR_ALIGNMENT_FILE,
        _PRESERVE_ORIGINAL_INTERVALS_FILE,
        _SRT_TIMING_PROPOSAL_FILE,
    )
    import shutil

    cleanup()
    for path in (
        UPLOAD_TRANS_SRT,
        UPLOAD_SRC_SRT,
        _ALIGNMENT_MODE_FILE,
        _CHAR_ALIGNMENT_FILE,
        _SRT_TIMING_PROPOSAL_FILE,
        _PRESERVE_ORIGINAL_INTERVALS_FILE,
    ):
        _drop(path)
    clear_usage()
    clear_merge_pending()
    if CANDIDATE_DIR.exists():
        shutil.rmtree(CANDIDATE_DIR, ignore_errors=True)
    os.makedirs("output", exist_ok=True)
