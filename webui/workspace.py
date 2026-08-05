"""
Workspace inspection and config access for the dubbing web UI.

Everything here reads the same output/ layout and config.yaml that the core
pipeline writes, so the UI never keeps a second copy of pipeline state.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from core._11_merge_audio import _parse_list
from core.utils.config_utils import _PLACEHOLDER_KEYS, load_key, load_secret, update_key
from core.utils.models import (
    _8_1_AUDIO_TASK,
    _AUDIO_CANDIDATES_DIR,
    _AUDIO_DONE_MARKER,
    _AUDIO_REF_OVERRIDES_DIR,
    _AUDIO_REFERS_DIR,
    _AUDIO_SEGS_DIR,
    _AUDIO_TMP_DIR,
    _BACKGROUND_AUDIO_FILE,
    _RAW_AUDIO_FILE,
    _SUBTITLE_STALE_MARKER,
    _TEXT_DONE_MARKER,
    _VOCAL_AUDIO_FILE,
)

OUTPUT_DIR = Path("output")
TRANS_SRT = OUTPUT_DIR / "trans.srt"
SRC_SRT = OUTPUT_DIR / "src.srt"
DUB_SRT = OUTPUT_DIR / "dub.srt"
DUB_AUDIO = OUTPUT_DIR / "dub.wav"
DUB_VIDEO = OUTPUT_DIR / "output_dub.mp4"
SPEAKER_TAGS = OUTPUT_DIR / "audio" / "speaker_tags.json"
UPLOAD_TRANS_SRT = OUTPUT_DIR / "_import_trans.srt"
UPLOAD_SRC_SRT = OUTPUT_DIR / "_import_src.srt"

# ------------
# Secrets: kept in gitignored key files rather than the tracked config.yaml
# ------------

SECRETS = {
    "gemini": {
        "label": "Gemini API Key",
        "hint": "字幕人物标记使用的 LLM",
        "config_key": "api.key",
        "key_file": "GEMINI_API_KEY",
    },
    "noiz": {
        "label": "NoizAI API Key",
        "hint": "NoizAI 克隆配音",
        "config_key": "noiz_tts.api_key",
        "key_file": "NOIZ_API_KEY",
    },
    "elevenlabs": {
        "label": "ElevenLabs API Key",
        "hint": "ElevenLabs 克隆配音",
        "config_key": "elevenlabs_tts.api_key",
        "key_file": "ELEVENLABS_API_KEY",
    },
    "qwen": {
        "label": "Qwen API Key",
        "hint": "字级对齐 / 视频直入转写（DashScope）",
        "config_key": "qwen_asr.api_key",
        "key_file": "QWEN_API_KEY",
    },
}

# ------------
# Config schema shared with the frontend so field lists live in one place
# ------------

TTS_OPTIONS = [
    ["custom_tts", "NoizAI"],
    ["elevenlabs_tts", "ElevenLabs"],
    ["edge_tts", "Edge TTS（免费，无克隆）"],
]

CONFIG_GROUPS = [
    {
        "id": "engine",
        "title": "配音引擎",
        "desc": "克隆模式会为每句取对应时间戳的人声做参考音频。",
        "fields": [
            {"key": "tts_method", "label": "TTS 引擎", "type": "select", "options": TTS_OPTIONS},
        ],
    },
    {
        "id": "noiz",
        "title": "NoizAI 参数",
        "when": ["tts_method", "custom_tts"],
        "fields": [
            {
                "key": "noiz_tts.mode",
                "label": "音色模式",
                "type": "select",
                "options": [["clone", "克隆原说话人"], ["preset", "固定音色"]],
            },
            {"key": "noiz_tts.voice_id", "label": "固定音色 ID", "type": "text"},
            {"key": "noiz_tts.target_lang", "label": "目标语言代码", "type": "text"},
            {"key": "noiz_tts.speed", "label": "语速", "type": "number", "min": 0.5, "max": 2, "step": 0.05},
            {"key": "noiz_tts.similarity_enh", "label": "相似度增强", "type": "bool"},
            {"key": "noiz_tts.max_workers", "label": "并发数", "type": "number", "min": 1, "max": 16, "step": 1},
        ],
    },
    {
        "id": "elevenlabs",
        "title": "ElevenLabs 参数",
        "when": ["tts_method", "elevenlabs_tts"],
        "fields": [
            {
                "key": "elevenlabs_tts.mode",
                "label": "音色模式",
                "type": "select",
                "options": [["clone", "临时克隆（用完即删）"], ["preset", "固定音色"]],
            },
            {"key": "elevenlabs_tts.voice_id", "label": "固定音色 ID", "type": "text"},
            {
                "key": "elevenlabs_tts.model_id",
                "label": "模型",
                "type": "select",
                "options": [
                    ["eleven_v3", "eleven_v3"],
                    ["eleven_multilingual_v2", "eleven_multilingual_v2"],
                    ["eleven_turbo_v2_5", "eleven_turbo_v2_5"],
                ],
            },
            {"key": "elevenlabs_tts.stability", "label": "稳定性", "type": "number", "min": 0, "max": 1, "step": 0.05},
            {"key": "elevenlabs_tts.similarity_boost", "label": "相似度", "type": "number", "min": 0, "max": 1, "step": 0.05},
            {"key": "elevenlabs_tts.style", "label": "风格强度", "type": "number", "min": 0, "max": 1, "step": 0.05},
            {"key": "elevenlabs_tts.use_speaker_boost", "label": "Speaker Boost", "type": "bool"},
            {"key": "elevenlabs_tts.max_workers", "label": "并发数", "type": "number", "min": 1, "max": 16, "step": 1},
        ],
    },
    {
        "id": "speaker",
        "title": "人物标记与参考音频分组",
        "desc": "由 LLM 推断人物；相邻同人物字幕可合并参考音频，间隔不超过阈值时合成一次 TTS。",
        "fields": [
            {"key": "speaker_tagging.enabled", "label": "启用 LLM 人物标记", "type": "bool"},
            {
                "key": "speaker_tagging.min_confidence",
                "label": "自动合并所需最低置信度",
                "type": "number",
                "min": 0,
                "max": 1,
                "step": 0.05,
            },
            {
                "key": "speaker_tagging.tts_merge_max_gap",
                "label": "合并上一条允许的最大间隔（秒）",
                "type": "number",
                "min": 0,
                "max": 5,
                "step": 0.1,
            },
        ],
    },
    {
        "id": "mastering",
        "title": "响度母带与原声区间",
        "desc": "成片做两遍 EBU R128 归一化；原声区间内配音让位，回放视频原始音轨。",
        "fields": [
            {"key": "audio_mastering.target_lufs", "label": "成片目标响度 (LUFS)", "type": "number", "min": -30, "max": -8, "step": 0.5},
            {"key": "audio_mastering.voice_lufs", "label": "配音轨响度 (LUFS)", "type": "number", "min": -30, "max": -8, "step": 0.5},
            {"key": "audio_mastering.true_peak", "label": "真峰值上限 (dBTP)", "type": "number", "min": -6, "max": 0, "step": 0.1},
            {"key": "audio_mastering.loudness_range", "label": "响度范围 (LU)", "type": "number", "min": 1, "max": 20, "step": 0.5},
            {"key": "audio_mastering.crossfade_ms", "label": "交叉淡化 (ms)", "type": "number", "min": 0, "max": 500, "step": 10},
            {"key": "audio_mastering.audio_bitrate", "label": "音频码率", "type": "text"},
            {"key": "audio_mastering.background_ducking", "label": "对白时自动降低背景", "type": "bool"},
            {"key": "audio_mastering.ducking_threshold", "label": "背景避让触发阈值", "type": "number", "min": 0.001, "max": 1, "step": 0.005},
            {"key": "audio_mastering.ducking_ratio", "label": "背景避让压缩比", "type": "number", "min": 1, "max": 20, "step": 0.5},
            {"key": "audio_mastering.ducking_attack_ms", "label": "背景避让启动 (ms)", "type": "number", "min": 1, "max": 500, "step": 5},
            {"key": "audio_mastering.ducking_release_ms", "label": "背景避让释放 (ms)", "type": "number", "min": 10, "max": 2000, "step": 10},
            {"key": "audio_mastering.preserve_original_vocals_in_gaps", "label": "TTS 空白处保留原人声", "type": "bool"},
            {"key": "audio_mastering.gap_vocals_guard_ms", "label": "原人声保护静音余量 (ms，保守)", "type": "number", "min": 0, "max": 1000, "step": 10},
            {"key": "audio_mastering.gap_vocals_aligned_guard_ms", "label": "原人声保护静音余量 (ms，对齐)", "type": "number", "min": 0, "max": 500, "step": 10},
            {"key": "audio_mastering.gap_vocals_merge_ms", "label": "相邻对白合并间隔 (ms)", "type": "number", "min": 0, "max": 2000, "step": 50},
            {"key": "audio_mastering.gap_vocals_min_duration_ms", "label": "保留原人声最短空档 (ms)", "type": "number", "min": 0, "max": 5000, "step": 100},
            {"key": "audio_mastering.gap_vocals_gain", "label": "空档原人声音量", "type": "number", "min": 0, "max": 1.5, "step": 0.05},
            {"key": "audio_mastering.original_audio_intervals", "label": "保留原声区间（秒）", "type": "intervals"},
        ],
    },
    {
        "id": "pipeline",
        "title": "流程与变速",
        "fields": [
            {"key": "demucs", "label": "Demucs 人声分离", "type": "bool"},
            {"key": "burn_subtitles", "label": "字幕烧进画面", "type": "bool"},
            {
                "key": "whisper.runtime",
                "label": "转写后端",
                "type": "select",
                "options": [
                    ["qwen", "Qwen（字级对齐，视频直入）"],
                    ["local", "WhisperX 本地"],
                    ["cloud", "WhisperX 云端"],
                    ["elevenlabs", "ElevenLabs"],
                ],
            },
            {"key": "qwen_asr.language", "label": "Qwen 语种", "type": "text"},
            {"key": "qwen_asr.gcs_bucket", "label": "GCS 存储桶", "type": "text"},
            {"key": "qwen_asr.gcs_prefix", "label": "GCS 前缀", "type": "text"},
            {"key": "speed_factor.min", "label": "最小变速", "type": "number", "min": 0.5, "max": 1, "step": 0.05},
            {"key": "speed_factor.accept", "label": "可接受变速", "type": "number", "min": 1, "max": 2, "step": 0.05},
            {"key": "speed_factor.max", "label": "最大变速", "type": "number", "min": 1, "max": 2.5, "step": 0.05},
        ],
    },
    {
        "id": "llm",
        "title": "LLM 接入",
        "fields": [
            {"key": "api.model", "label": "模型", "type": "text"},
            {"key": "api.base_url", "label": "Base URL", "type": "text"},
            {"key": "max_workers", "label": "LLM 并发数", "type": "number", "min": 1, "max": 16, "step": 1},
        ],
    },
]

EDITABLE_KEYS = {field["key"] for group in CONFIG_GROUPS for field in group["fields"]}


def _to_relative(path):
    text = str(path).replace("\\", "/")
    return text[len("output/"):] if text.startswith("output/") else text


def _file_entry(path, label):
    file = Path(path)
    if not file.is_file():
        return None
    stat = file.stat()
    mtime = int(stat.st_mtime)
    return {
        "label": label,
        "path": str(path),
        "url": f"/files/{_to_relative(path)}?v={stat.st_mtime_ns}",
        "size": stat.st_size,
        "mtime": mtime,
    }


def _effective_refer(number):
    override = Path(_AUDIO_REF_OVERRIDES_DIR) / f"{number}.wav"
    if override.is_file():
        entry = _file_entry(override, "手工参考")
        if entry:
            entry["source"] = "override"
        return entry
    auto = Path(_AUDIO_REFERS_DIR) / f"{number}.wav"
    entry = _file_entry(auto, "参考音频")
    if entry:
        entry["source"] = "auto"
    return entry


def _task_needs_regen(number, lines):
    """True when a task has no temp TTS cache (or empty cache)."""
    count = len(lines) if lines else 1
    for index in range(count):
        temp = Path(_AUDIO_TMP_DIR) / f"{number}_{index}_temp.wav"
        if not temp.is_file() or temp.stat().st_size < 100:
            return True
    return False


# ------------
# Config
# ------------


def read_config():
    values = {}
    for key in EDITABLE_KEYS:
        try:
            values[key] = load_key(key)
        except KeyError:
            values[key] = None
    return {"groups": CONFIG_GROUPS, "values": values, "secrets": read_secrets()}


def write_config(patch):
    rejected = [key for key in patch if key not in EDITABLE_KEYS]
    if rejected:
        raise ValueError(f"Not editable from the UI: {', '.join(sorted(rejected))}")
    for key, value in patch.items():
        if key == "audio_mastering.original_audio_intervals":
            value = _normalize_intervals(value)
        update_key(key, value)
    return read_config()


def _normalize_intervals(value):
    intervals = []
    for item in value or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"区间格式应为 [开始, 结束]：{item}")
        start, end = float(item[0]), float(item[1])
        if start < 0 or end <= start:
            raise ValueError(f"区间无效：{item}")
        intervals.append([round(start, 3), round(end, 3)])
    return sorted(intervals)


def read_secrets():
    entries = []
    for name, spec in SECRETS.items():
        if _looks_real(load_key(spec["config_key"])):
            source = "config"
        elif _looks_real(load_secret(spec["config_key"], spec["key_file"])):
            source = "file"
        else:
            source = None
        entries.append(
            {
                "name": name,
                "label": spec["label"],
                "hint": spec["hint"],
                "key_file": spec["key_file"],
                "configured": source is not None,
                "source": source,
            }
        )
    return entries


def _looks_real(value):
    return isinstance(value, str) and value.strip() not in _PLACEHOLDER_KEYS


def write_secret(name, value):
    spec = SECRETS.get(name)
    if spec is None:
        raise ValueError(f"未知密钥：{name}")
    text = (value or "").strip()
    if not text:
        raise ValueError("密钥不能为空")
    Path(spec["key_file"]).write_text(text + "\n", encoding="utf-8")
    return read_secrets()


# ------------
# Media / subtitles
# ------------


def media_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def read_media():
    from core._1_ytdlp import find_media_file

    try:
        path, media_type = find_media_file()
    except Exception:
        return None
    file = Path(path)
    try:
        duration = media_duration(path)
    except Exception:
        duration = None
    return {
        "path": path,
        "name": file.name,
        "type": media_type,
        "size": file.stat().st_size,
        "duration": duration,
        "url": f"/files/{_to_relative(path)}",
    }


def parse_srt(path):
    file = Path(path)
    if not file.is_file():
        return []
    cues = []
    for block in file.read_text(encoding="utf-8").replace("\r\n", "\n").strip().split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split("-->")]
        cues.append({"cue": int(lines[0]), "start": start, "end": end, "text": " ".join(lines[2:])})
    return cues


def read_speakers():
    cues = parse_srt(TRANS_SRT)
    if not cues:
        return {"cues": [], "speakers": [], "groups": 0, "stale": False}

    tags = {}
    stale = False
    if SPEAKER_TAGS.is_file():
        from core.speaker_tagging import load_speaker_tags

        tags = load_speaker_tags(str(TRANS_SRT), str(SPEAKER_TAGS))
        stale = not tags

    src_by_cue = {cue["cue"]: cue["text"] for cue in parse_srt(SRC_SRT)}
    rows = []
    for cue in cues:
        tag = tags.get(cue["cue"], {})
        rows.append(
            {
                **cue,
                "origin": src_by_cue.get(cue["cue"], ""),
                "speaker": tag.get("speaker"),
                "confidence": tag.get("confidence"),
                "merge_with_previous": tag.get("merge_with_previous"),
                "force_unmerge": bool(tag.get("force_unmerge", False)),
                "reason": tag.get("reason"),
                "manual_override": bool(tag.get("manual_override", False)),
            }
        )

    speakers = []
    for row in rows:
        if row["speaker"] and row["speaker"] not in [item["name"] for item in speakers]:
            speakers.append({"name": row["speaker"], "cues": 0})
    for row in rows:
        for item in speakers:
            if item["name"] == row["speaker"]:
                item["cues"] += 1
    merged = sum(1 for row in rows if row.get("merge_with_previous"))
    return {
        "cues": rows,
        "speakers": speakers,
        "speaker_names": [item["name"] for item in speakers],
        "groups": len(rows) - merged,
        "stale": stale,
    }


# ------------
# TTS tasks
# ------------


def _read_candidates(number, line_count):
    from webui.editing import list_candidate_manifests

    candidates = []
    for manifest in list_candidate_manifests(number):
        count = int(manifest.get("line_count") or line_count or 1)
        candidate_id = manifest.get("candidate_id")
        root = Path(_AUDIO_CANDIDATES_DIR) / str(number)
        if candidate_id:
            root = root / str(candidate_id)
        segments = [
            entry
            for entry in (
                _file_entry(root / "segs" / f"{number}_{index}.wav", f"候选片段 {index + 1}")
                for index in range(count)
            )
            if entry
        ]
        temps = [
            entry
            for entry in (
                _file_entry(root / "tmp" / f"{number}_{index}_temp.wav", f"候选完整音频 {index + 1}")
                for index in range(count)
            )
            if entry
        ]
        if not temps and not segments:
            continue
        fits = bool(manifest.get("fits", True))
        candidates.append({
            "number": number,
            "candidate_id": candidate_id,
            "real_dur": manifest.get("real_dur"),
            "available": manifest.get("available"),
            "required_speed": manifest.get("required_speed"),
            "speed_factor": manifest.get("speed_factor"),
            "created_at": manifest.get("created_at"),
            "fits": fits,
            "status": manifest.get("status") or ("fitted" if fits else "forced_merge"),
            "shorten_rounds": manifest.get("shorten_rounds", 0),
            "force_shorten": bool(manifest.get("force_shorten", False)),
            "text_changed": bool(manifest.get("text_changed")),
            "original_text": manifest.get("original_text") or "",
            "candidate_text": manifest.get("candidate_text") or "",
            "original_cues": manifest.get("original_cues") or [],
            "candidate_cues": manifest.get("candidate_cues") or [],
            "failure_reason": manifest.get("failure_reason"),
            "segments": segments,
            "temps": temps,
        })
    return candidates


def _read_candidate(number, line_count):
    candidates = _read_candidates(number, line_count)
    return candidates[0] if candidates else None


def read_tasks():
    task_file = Path(_8_1_AUDIO_TASK)
    if not task_file.is_file():
        return {"tasks": [], "merge_pending": [], "columns": []}

    import pandas as pd
    from webui.editing import read_merge_pending

    df = pd.read_excel(task_file)
    pending = set(read_merge_pending())
    rows = []
    for record in df.to_dict("records"):
        number = int(record["number"])
        lines = _safe_list(record.get("lines"))
        line_count = len(lines) if lines else 1
        candidates = _read_candidates(number, line_count)
        rows.append(
            {
                "number": number,
                "speaker": _safe_text(record.get("speaker")),
                "confidence": _safe_float(record.get("speaker_confidence")),
                "source_numbers": _safe_list(record.get("source_numbers")) or [number],
                "start_time": _safe_text(record.get("start_time")),
                "end_time": _safe_text(record.get("end_time")),
                "duration": _safe_float(record.get("duration")),
                "est_dur": _safe_float(record.get("est_dur")),
                "real_dur": _safe_float(record.get("real_dur")),
                "text": _safe_text(record.get("text")),
                "origin": _safe_text(record.get("origin")),
                "line_count": line_count,
                "refer": _effective_refer(number),
                "has_override": (Path(_AUDIO_REF_OVERRIDES_DIR) / f"{number}.wav").is_file(),
                "needs_regen": _task_needs_regen(number, lines),
                "merge_pending": number in pending,
                "candidate": candidates[0] if candidates else None,
                "candidates": candidates,
                "segments": [
                    entry
                    for entry in (
                        _file_entry(f"{_AUDIO_SEGS_DIR}/{number}_{index}.wav", f"片段 {index + 1}")
                        for index in range(line_count)
                    )
                    if entry
                ],
            }
        )
    return {"tasks": rows, "merge_pending": sorted(pending)}


def _safe_list(value):
    try:
        parsed = _parse_list(value)
    except Exception:
        return []
    return list(parsed) if isinstance(parsed, (list, tuple)) else []


def _safe_text(value):
    import pandas as pd

    return "" if value is None or pd.isna(value) else str(value)


def _safe_float(value):
    import pandas as pd

    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


# ------------
# Stage / artifact state
# ------------


def _upload_entry(path):
    if not Path(path).is_file():
        return None
    cues = parse_srt(path)
    return {
        "cue_count": len(cues),
        "last_end": cues[-1]["end"] if cues else None,
        "url": f"/files/{_to_relative(path)}",
    }


def prepare_mode():
    if UPLOAD_TRANS_SRT.is_file():
        return "import"
    return "video_only"


def read_state():
    from webui.editing import read_merge_pending
    from core.srt_timing_repair import load_proposal, read_alignment_mode
    from core.utils.models import (
        _CHAR_ALIGNMENT_FILE,
        _SRT_TIMING_PROPOSAL_FILE,
    )

    media = read_media()
    cues = parse_srt(TRANS_SRT)
    task_file = Path(_8_1_AUDIO_TASK)
    refers = sorted(Path(_AUDIO_REFERS_DIR).glob("*.wav")) if Path(_AUDIO_REFERS_DIR).is_dir() else []
    segs = sorted(Path(_AUDIO_SEGS_DIR).glob("*.wav")) if Path(_AUDIO_SEGS_DIR).is_dir() else []
    merge_pending = read_merge_pending()
    subtitle_stale = Path(_SUBTITLE_STALE_MARKER).is_file()
    mode = prepare_mode()
    alignment_mode = read_alignment_mode()
    proposal = load_proposal()
    alignment_ready = Path(_CHAR_ALIGNMENT_FILE).is_file() and Path(_SRT_TIMING_PROPOSAL_FILE).is_file()
    # Pending until the user picks aligned/conservative. Do not hide the gate
    # just because a leftover tts_tasks.xlsx exists from a previous run.
    decision_pending = mode == "import" and alignment_ready and not alignment_mode

    artifacts = [
        entry
        for entry in (
            _file_entry(DUB_VIDEO, "配音成片"),
            _file_entry(DUB_AUDIO, "配音音轨"),
            _file_entry(DUB_SRT, "配音字幕"),
            _file_entry(TRANS_SRT, "译文字幕"),
            _file_entry(SRC_SRT, "原文字幕"),
            _file_entry(_VOCAL_AUDIO_FILE, "分离人声"),
            _file_entry(_BACKGROUND_AUDIO_FILE, "背景音"),
            _file_entry(_RAW_AUDIO_FILE, "原始音轨"),
        )
        if entry
    ]

    return {
        "media": media,
        "uploads": {
            "trans": _upload_entry(UPLOAD_TRANS_SRT),
            "src": _upload_entry(UPLOAD_SRC_SRT),
        },
        "prepare_mode": mode,
        "prepared": {
            "imported": Path(_TEXT_DONE_MARKER).is_file() and bool(cues),
            "cue_count": len(cues),
            "vocal_ready": Path(_VOCAL_AUDIO_FILE).is_file(),
            "tasks_ready": task_file.is_file(),
            "refer_count": len(refers),
            "alignment_ready": alignment_ready,
            "alignment_decision_pending": decision_pending,
        },
        "alignment": {
            "mode": (alignment_mode or {}).get("mode"),
            "source": (alignment_mode or {}).get("source"),
            "proposal_ready": bool(proposal),
            "changed_count": (proposal or {}).get("changed_count", 0),
            "cue_count": (proposal or {}).get("cue_count", 0),
            "decision_pending": decision_pending,
        },
        "dubbed": {
            "done": Path(_AUDIO_DONE_MARKER).is_file(),
            "segment_count": len(segs),
            "video_ready": DUB_VIDEO.is_file(),
            "audio_ready": DUB_AUDIO.is_file(),
            "stale": bool(merge_pending or subtitle_stale) and DUB_VIDEO.is_file(),
            "subtitle_stale": subtitle_stale,
            "merge_pending": merge_pending,
        },
        "artifacts": artifacts,
        "tts_method": load_key("tts_method"),
    }


def read_alignment():
    from core.srt_timing_repair import load_proposal, read_alignment_mode, propose_repair
    from core.qwen_align import load_char_alignment

    proposal = load_proposal()
    if not proposal and load_char_alignment() and TRANS_SRT.is_file():
        proposal = propose_repair()
    mode = read_alignment_mode()
    return {
        "mode": (mode or {}).get("mode"),
        "source": (mode or {}).get("source"),
        "proposal": proposal,
        "decision_pending": bool(proposal) and not mode,
    }


def read_loudness():
    if not DUB_VIDEO.is_file():
        raise FileNotFoundError("还没有成片，先跑一次配音。")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(DUB_VIDEO), "-map", "0:a:0",
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, re.DOTALL)
    if not matches:
        raise RuntimeError("无法解析 FFmpeg 响度测量结果")
    measured = json.loads(matches[-1])
    return {
        "integrated_lufs": float(measured["input_i"]),
        "true_peak_dbtp": float(measured["input_tp"]),
        "loudness_range_lu": float(measured["input_lra"]),
        "target_lufs": float(load_key("audio_mastering.target_lufs")),
        "target_true_peak": float(load_key("audio_mastering.true_peak")),
        "target_loudness_range": float(load_key("audio_mastering.loudness_range")),
    }
