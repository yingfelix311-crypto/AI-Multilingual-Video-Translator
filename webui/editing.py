"""
Manual editing services for speaker tags and per-task reference audio.

Speaker edits are applied explicitly (save + rebuild). Reference overrides live
in a separate directory so automatic timestamp extraction never overwrites them.
Per-task regeneration candidates are also non-destructive until the user
accepts them and later remasters the full dub.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from core.speaker_tagging import SPEAKER_TAGS_FILE, _source_hash, save_speaker_tags
from core.utils.models import (
    _8_1_AUDIO_TASK,
    _AUDIO_CANDIDATES_DIR,
    _AUDIO_DONE_MARKER,
    _AUDIO_REF_OVERRIDES_DIR,
    _AUDIO_REFERS_DIR,
    _AUDIO_SEGS_DIR,
    _AUDIO_TMP_DIR,
    _MERGE_PENDING_FILE,
    _SUBTITLE_STALE_MARKER,
)
from webui.workspace import (
    SRC_SRT,
    TRANS_SRT,
    UPLOAD_SRC_SRT,
    UPLOAD_TRANS_SRT,
    parse_srt,
)

OVERRIDE_DIR = Path(_AUDIO_REF_OVERRIDES_DIR)
CANDIDATE_DIR = Path(_AUDIO_CANDIDATES_DIR)
MERGE_PENDING_PATH = Path(_MERGE_PENDING_FILE)
SUBTITLE_STALE_PATH = Path(_SUBTITLE_STALE_MARKER)
TRANS_AUDIO_SRT = Path("output/audio/trans_subs_for_audio.srt")
SRC_AUDIO_SRT = Path("output/audio/src_subs_for_audio.srt")


# ------------
# Task snapshots
# ------------


def _ensure_object_column(tasks_df, column):
    """Ensure a column can hold list/dict cells (pandas .at fails otherwise)."""
    if column not in tasks_df.columns:
        tasks_df[column] = pd.Series([None] * len(tasks_df), dtype=object)
    elif str(tasks_df[column].dtype) != "object":
        tasks_df[column] = tasks_df[column].astype(object)
    return tasks_df


def _set_task_cell(tasks_df, row_index, column, value):
    """Set one cell, creating object dtype first when value is list-like."""
    if isinstance(value, (list, tuple, dict, set)):
        _ensure_object_column(tasks_df, column)
    elif column not in tasks_df.columns:
        tasks_df[column] = pd.NA
    tasks_df.at[row_index, column] = value


def _task_signature(row):
    source = row.get("source_numbers")
    if isinstance(source, str):
        from core._11_merge_audio import _parse_list

        try:
            source = _parse_list(source)
        except Exception:
            source = [row["number"]]
    if not isinstance(source, (list, tuple)):
        source = [row["number"]]
    return {
        "number": int(row["number"]),
        "source_numbers": [int(n) for n in source],
        "text": str(row.get("text") or ""),
        "speaker": str(row.get("speaker") or ""),
    }


def snapshot_tasks():
    path = Path(_8_1_AUDIO_TASK)
    if not path.is_file():
        return []
    df = pd.read_excel(path)
    return [_task_signature(row) for row in df.to_dict("records")]


def _changed_task_numbers(before, after):
    """Return task numbers whose topology/text changed, plus orphans from before."""
    before_by_sources = {
        tuple(item["source_numbers"]): item for item in before
    }
    after_by_sources = {
        tuple(item["source_numbers"]): item for item in after
    }
    changed = set()
    for key, item in after_by_sources.items():
        previous = before_by_sources.get(key)
        if previous is None or previous["text"] != item["text"] or previous["speaker"] != item["speaker"]:
            changed.add(item["number"])
        else:
            # Same grouping kept the same number only if topology preserved;
            # still clear if the task number itself moved.
            if previous["number"] != item["number"]:
                changed.add(item["number"])
                changed.add(previous["number"])
    for key, item in before_by_sources.items():
        if key not in after_by_sources:
            changed.add(item["number"])
    return sorted(changed)


def _clear_tts_cache(task_numbers):
    for number in task_numbers:
        for path in Path(_AUDIO_TMP_DIR).glob(f"{number}_*_temp.wav"):
            path.unlink(missing_ok=True)
        for path in Path(_AUDIO_SEGS_DIR).glob(f"{number}_*.wav"):
            path.unlink(missing_ok=True)


def _invalidate_dub_outputs():
    Path(_AUDIO_DONE_MARKER).unlink(missing_ok=True)
    for name in (
        "output/dub.wav",
        "output/dub.mp3",
        "output/dub.srt",
        "output/output_dub.mp4",
        "output/output_dub_premaster.mkv",
    ):
        Path(name).unlink(missing_ok=True)


# ------------
# Speaker validation / apply
# ------------


_SRT_TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})$")


def _parse_srt_seconds(value):
    text = str(value or "").strip()
    match = _SRT_TIME_RE.fullmatch(text)
    if not match:
        raise ValueError(f"无效时间：{text or '空'}（应为 HH:MM:SS,mmm）")
    hours, minutes, seconds, millis = match.groups()
    millis = int(millis.ljust(3, "0"))
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + millis / 1000


def _format_srt_seconds(seconds):
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total_ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clean_cue_text(value):
    return " ".join(str(value or "").split()).strip()


def validate_cue_items(items, media_duration=None):
    """Validate, sort and renumber a complete editable subtitle cue payload."""
    if not isinstance(items, list) or not items:
        raise ValueError("字幕列表不能为空")

    normalized = []
    errors = []
    for position, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            errors.append(f"第 {position} 行不是有效字幕")
            continue
        try:
            start_seconds = _parse_srt_seconds(raw.get("start"))
            end_seconds = _parse_srt_seconds(raw.get("end"))
        except ValueError as exc:
            errors.append(f"第 {position} 行：{exc}")
            continue

        text = _clean_cue_text(raw.get("text"))
        origin = _clean_cue_text(raw.get("origin")) or text
        speaker = str(raw.get("speaker") or "").strip()
        if end_seconds <= start_seconds:
            errors.append(f"第 {position} 行结束时间必须晚于开始时间")
        if media_duration is not None and end_seconds > float(media_duration) + 0.001:
            errors.append(f"第 {position} 行结束时间超出媒体时长")
        if not text:
            errors.append(f"第 {position} 行译文不能为空")
        if not speaker:
            errors.append(f"第 {position} 行人物不能为空")

        merge = bool(raw.get("merge_with_previous", False))
        normalized.append({
            "source_id": str(raw.get("source_id") or raw.get("cue") or position),
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "start": _format_srt_seconds(start_seconds),
            "end": _format_srt_seconds(end_seconds),
            "text": text,
            "origin": origin,
            "speaker": speaker,
            "merge_with_previous": merge,
            # Unchecked merge is an explicit split; checked/auto clears the lock.
            "force_unmerge": bool(raw.get("force_unmerge", False)) and not merge,
            "confidence": 1.0,
            "reason": str(raw.get("reason") or "").strip(),
            "manual_override": True,
        })

    if errors:
        raise ValueError("；".join(errors))

    normalized.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))
    from core.utils import load_key

    try:
        max_gap = float(load_key("speaker_tagging.tts_merge_max_gap"))
    except Exception:
        max_gap = 1.0
    warnings = []
    for index, item in enumerate(normalized):
        item["cue"] = index + 1
        if index == 0:
            item["merge_with_previous"] = False
            item["force_unmerge"] = False
            continue
        previous = normalized[index - 1]
        if item["start_seconds"] < previous["end_seconds"]:
            warnings.append(f"字幕 {index} 与 {index + 1} 时间重叠")
        gap = item["start_seconds"] - previous["end_seconds"]
        eligible = (
            item["speaker"] == previous["speaker"]
            and -0.5 <= gap <= max_gap
        )
        if item.get("force_unmerge"):
            item["merge_with_previous"] = False
        elif eligible:
            item["merge_with_previous"] = True
        else:
            item["merge_with_previous"] = False
        if item["merge_with_previous"] and item["speaker"] != previous["speaker"]:
            errors.append(
                f"字幕 {index + 1} 与上一条人物不同"
                f"（{item['speaker']} ≠ {previous['speaker']}），不能合并参考音频"
            )
    if errors:
        raise ValueError("；".join(errors))
    return {"items": normalized, "warnings": warnings}


def _cues_to_srt(items, field):
    blocks = []
    for item in items:
        blocks.append(
            f"{item['cue']}\n{item['start']} --> {item['end']}\n{item[field]}"
        )
    return "\n\n".join(blocks) + "\n"


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
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def validate_speaker_items(items):
    """Validate a full speaker tag payload without writing it."""
    cues = parse_srt(TRANS_SRT)
    if not cues:
        raise ValueError("还没有译文字幕，先完成准备阶段。")

    expected = [cue["cue"] for cue in cues]
    if not isinstance(items, list) or not items:
        raise ValueError("人物标记列表不能为空")

    normalized = []
    errors = []
    for raw in items:
        if not isinstance(raw, dict):
            errors.append("每条标记必须是对象")
            continue
        try:
            cue = int(raw["cue"])
        except Exception:
            errors.append(f"无效的 cue：{raw.get('cue')}")
            continue
        speaker = str(raw.get("speaker", "")).strip()
        if not speaker:
            errors.append(f"字幕 {cue} 缺少人物标记")
        merge = bool(raw.get("merge_with_previous", False))
        force_unmerge = bool(raw.get("force_unmerge", False)) and not merge
        normalized.append({
            "cue": cue,
            "speaker": speaker,
            "merge_with_previous": merge,
            "force_unmerge": force_unmerge,
            "confidence": float(raw.get("confidence", 1.0)),
            "reason": str(raw.get("reason", "")).strip(),
            "manual_override": True,
        })

    actual = [item["cue"] for item in normalized]
    if actual != expected:
        raise ValueError(f"字幕编号不完整或不匹配：期望 {expected}，收到 {actual}")

    if normalized and normalized[0]["merge_with_previous"]:
        errors.append(f"字幕 {normalized[0]['cue']} 是第一条，不能合并上一条参考")

    for index, item in enumerate(normalized[1:], start=1):
        if not item["merge_with_previous"]:
            continue
        previous = normalized[index - 1]
        if item["speaker"] != previous["speaker"]:
            errors.append(
                f"字幕 {item['cue']} 与上一条人物不同"
                f"（{item['speaker']} ≠ {previous['speaker']}），不能合并参考音频"
            )

    if errors:
        raise ValueError("；".join(errors))
    return normalized


def apply_speaker_tags(items):
    """Save manual speaker tags and rebuild TTS tasks + auto reference audio."""
    normalized = validate_speaker_items(items)
    before = snapshot_tasks()

    save_speaker_tags(normalized, srt_path=str(TRANS_SRT), model="manual")

    Path(_8_1_AUDIO_TASK).unlink(missing_ok=True)

    from core import _8_1_audio_task, _8_2_dub_chunks, _9_refer_audio

    _8_1_audio_task.gen_audio_task_main()
    _8_2_dub_chunks.gen_dub_chunks()
    _9_refer_audio.extract_refer_audio_main()

    after = snapshot_tasks()
    changed = _changed_task_numbers(before, after)
    if changed:
        _clear_tts_cache(changed)
    _invalidate_dub_outputs()

    # Drop overrides for task numbers that no longer exist after rebuild.
    after_numbers = {item["number"] for item in after}
    if OVERRIDE_DIR.is_dir():
        for path in OVERRIDE_DIR.glob("*.wav"):
            try:
                number = int(path.stem)
            except ValueError:
                continue
            if number not in after_numbers:
                path.unlink(missing_ok=True)

    return {
        "cue_count": len(normalized),
        "task_count": len(after),
        "changed_tasks": changed,
        "groups": len(after),
    }


def apply_cue_draft(items, media_duration=None):
    """Atomically persist complete cue edits, then rebuild all derived tasks."""
    result = validate_cue_items(items, media_duration=media_duration)
    normalized = result["items"]
    trans_content = _cues_to_srt(normalized, "text")
    src_content = _cues_to_srt(normalized, "origin")

    tags = [
        {
            "cue": item["cue"],
            "speaker": item["speaker"],
            "merge_with_previous": item["merge_with_previous"],
            "force_unmerge": bool(item.get("force_unmerge", False)),
            "confidence": 1.0,
            "reason": item["reason"],
            "manual_override": True,
        }
        for item in normalized
    ]
    tags_content = json.dumps(
        {
            "source_hash": _source_hash(trans_content),
            "model": "manual",
            "items": tags,
        },
        ensure_ascii=False,
        indent=2,
    )
    _atomic_write_many({
        Path(TRANS_SRT): trans_content,
        Path(SRC_SRT): src_content,
        TRANS_AUDIO_SRT: trans_content,
        SRC_AUDIO_SRT: src_content,
        Path(UPLOAD_TRANS_SRT): trans_content,
        Path(UPLOAD_SRC_SRT): src_content,
        Path(SPEAKER_TAGS_FILE): tags_content,
    })

    # Cue insertion/deletion or temporal reordering invalidates every numbered
    # task artifact. Clear them all instead of trying to preserve unsafe maps.
    Path(_8_1_AUDIO_TASK).unlink(missing_ok=True)
    _clear_dir(_AUDIO_TMP_DIR)
    _clear_dir(_AUDIO_SEGS_DIR)
    _clear_dir(CANDIDATE_DIR)
    _clear_dir(OVERRIDE_DIR)
    clear_merge_pending()
    Path(_AUDIO_DONE_MARKER).unlink(missing_ok=True)
    SUBTITLE_STALE_PATH.write_text(
        json.dumps(
            {"cue_count": len(normalized), "updated_at": time.time()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from core import _8_1_audio_task, _8_2_dub_chunks, _9_refer_audio

    _8_1_audio_task.gen_audio_task_main()
    _8_2_dub_chunks.gen_dub_chunks()
    _9_refer_audio.extract_refer_audio_main()
    after = snapshot_tasks()
    return {
        "cue_count": len(normalized),
        "task_count": len(after),
        "changed_tasks": [item["number"] for item in after],
        "groups": len(after),
        "warnings": result["warnings"],
        "structure_changed": True,
    }


def rebuild_speaker_steps(items):
    """Return (label, callable) steps for the job runner."""
    payload = {"items": items}

    def step_validate_and_save():
        payload["result"] = apply_speaker_tags(payload["items"])

    return [
        ("校验并保存人物标记，重建配音任务", step_validate_and_save),
    ]


def rebuild_cue_steps(items, media_duration=None):
    payload = {"items": items, "media_duration": media_duration}

    def step_apply_and_rebuild():
        payload["result"] = apply_cue_draft(
            payload["items"],
            media_duration=payload["media_duration"],
        )

    return [
        ("保存字幕校正并重建配音任务", step_apply_and_rebuild),
    ]


# ------------
# Reference overrides
# ------------


def override_path(number):
    return OVERRIDE_DIR / f"{int(number)}.wav"


def has_override(number):
    return override_path(number).is_file()


def list_override_numbers():
    if not OVERRIDE_DIR.is_dir():
        return []
    numbers = []
    for path in OVERRIDE_DIR.glob("*.wav"):
        try:
            numbers.append(int(path.stem))
        except ValueError:
            continue
    return sorted(numbers)


def _ffmpeg_to_wav(src_path, dst_path):
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_suffix(".tmp.wav")
    cmd = [
        "ffmpeg", "-y", "-i", str(src_path),
        "-ac", "1", "-ar", "16000",
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"参考音频转换失败：{(result.stderr or result.stdout)[-300:]}")
    tmp.replace(dst_path)


def _parse_task_number_from_name(filename):
    stem = Path(filename).stem
    match = re.search(r"(?:^|[_\-\s.])(\d+)(?:$|[_\-\s.])", stem)
    if match:
        return int(match.group(1))
    if stem.isdigit():
        return int(stem)
    return None


def set_reference_overrides(task_numbers, file_bytes_list, filenames, mode="broadcast"):
    """
    Save reference overrides.

    mode=broadcast: one audio file applied to every task_number
    mode=mapped: each file maps to a task number parsed from its filename
                 (task_numbers acts as an allow-list when provided)
    """
    if not file_bytes_list:
        raise ValueError("没有上传参考音频")

    available = {item["number"] for item in snapshot_tasks()}
    if not available:
        raise ValueError("还没有配音任务，先完成准备阶段。")

    written = []
    with tempfile.TemporaryDirectory(prefix="ref_override_") as tmpdir:
        tmpdir = Path(tmpdir)

        if mode == "broadcast":
            if len(file_bytes_list) != 1:
                raise ValueError("广播模式只接受一个音频文件")
            numbers = [int(n) for n in task_numbers]
            if not numbers:
                raise ValueError("请选择要覆盖的任务")
            unknown = [n for n in numbers if n not in available]
            if unknown:
                raise ValueError(f"未知任务编号：{unknown}")

            src = tmpdir / (filenames[0] or "ref.wav")
            src.write_bytes(file_bytes_list[0])
            for number in numbers:
                _ffmpeg_to_wav(src, override_path(number))
                written.append(number)
        elif mode == "mapped":
            allow = {int(n) for n in task_numbers} if task_numbers else available
            for data, name in zip(file_bytes_list, filenames):
                number = _parse_task_number_from_name(name or "")
                if number is None:
                    raise ValueError(f"无法从文件名解析任务编号：{name}")
                if number not in available:
                    raise ValueError(f"未知任务编号：{number}（来自 {name}）")
                if number not in allow:
                    raise ValueError(f"任务 {number} 不在选中列表中（来自 {name}）")
                src = tmpdir / (name or f"{number}.wav")
                src.write_bytes(data)
                _ffmpeg_to_wav(src, override_path(number))
                written.append(number)
        else:
            raise ValueError(f"未知上传模式：{mode}")

    return {"overridden": sorted(set(written))}


def clear_reference_overrides(task_numbers):
    numbers = [int(n) for n in task_numbers]
    if not numbers:
        raise ValueError("请选择要恢复的任务")
    cleared = []
    for number in numbers:
        path = override_path(number)
        if path.is_file():
            path.unlink()
            cleared.append(number)
    return {"cleared": cleared}


def _source_reference_path(number):
    """Resolve the effective reference WAV for a task (override wins)."""
    number = int(number)
    override = override_path(number)
    if override.is_file():
        return override, "override"
    auto = Path(_AUDIO_REFERS_DIR) / f"{number}.wav"
    if auto.is_file():
        return auto, "auto"
    raise FileNotFoundError(f"任务 {number} 没有可用的参考音频")


def list_reference_library():
    """Group existing task reference clips by speaker for the picker UI."""
    from webui.workspace import read_tasks

    payload = read_tasks()
    by_speaker = {}
    for task in payload.get("tasks") or []:
        refer = task.get("refer")
        if not refer:
            continue
        speaker = (task.get("speaker") or "").strip() or "未标记"
        by_speaker.setdefault(speaker, []).append(
            {
                "number": task["number"],
                "text": task.get("text") or "",
                "start_time": task.get("start_time"),
                "end_time": task.get("end_time"),
                "has_override": bool(task.get("has_override")),
                "refer": refer,
            }
        )

    speakers = []
    for name, clips in sorted(by_speaker.items(), key=lambda item: item[0].lower()):
        clips.sort(key=lambda item: item["number"])
        speakers.append({"name": name, "count": len(clips), "clips": clips})
    return {"speakers": speakers}


def copy_reference_from_task(source_number, target_numbers):
    """Copy one task's effective reference onto the target tasks as overrides."""
    source = int(source_number)
    targets = validate_task_numbers(target_numbers)
    src_path, source_kind = _source_reference_path(source)
    written = []
    for number in targets:
        _ffmpeg_to_wav(src_path, override_path(number))
        written.append(number)
    return {
        "source": source,
        "source_kind": source_kind,
        "overridden": written,
    }


def validate_task_numbers(task_numbers):
    numbers = sorted({int(n) for n in task_numbers})
    if not numbers:
        raise ValueError("请选择任务")
    available = {item["number"] for item in snapshot_tasks()}
    missing = [n for n in numbers if n not in available]
    if missing:
        raise ValueError(f"未知任务编号：{missing}")
    return numbers


def update_task_text(task_number, text):
    """Update one task's dubbing text and invalidate its TTS cache.

    Manual edits collapse ``lines`` to a single chunk of the new text so the
    next candidate/regeneration reads exactly what the user saved. Existing
    audio for that task is cleared; the mastered video is kept until remaster.
    """
    number = validate_task_numbers([task_number])[0]
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        raise ValueError("字幕文本不能为空")

    tasks_df = pd.read_excel(_8_1_AUDIO_TASK)
    matches = tasks_df.index[tasks_df["number"] == number].tolist()
    if not matches:
        raise ValueError(f"未知任务编号：{number}")
    row_index = matches[0]
    previous = str(tasks_df.at[row_index, "text"] or "").strip()
    if previous == cleaned:
        return {"number": number, "text": cleaned, "changed": False}

    tasks_df.at[row_index, "text"] = cleaned
    _set_task_cell(tasks_df, row_index, "lines", [cleaned])
    tasks_df.at[row_index, "manual_text_override"] = True
    if "src_lines" in tasks_df.columns or "origin" in tasks_df.columns:
        origin = tasks_df.at[row_index, "origin"] if "origin" in tasks_df.columns else ""
        _set_task_cell(tasks_df, row_index, "src_lines", [str(origin or "")])
    tasks_df.to_excel(_8_1_AUDIO_TASK, index=False)

    _clear_tts_cache([number])
    discard_candidate(number)
    clear_merge_pending([number])
    Path(_AUDIO_DONE_MARKER).unlink(missing_ok=True)

    return {"number": number, "text": cleaned, "changed": True}


def selective_dub_steps(task_numbers):
    """Batch regenerate: apply immediately and remaster (destructive)."""
    numbers = validate_task_numbers(task_numbers)

    def step_tts():
        from core import _10_gen_audio

        Path(_AUDIO_DONE_MARKER).unlink(missing_ok=True)
        _10_gen_audio.regenerate_tasks(numbers)
        for number in numbers:
            discard_candidate(number)
        clear_merge_pending(numbers)

    def step_merge():
        from core import _11_merge_audio

        _11_merge_audio.merge_full_audio()

    def step_master():
        from core import _12_dub_to_vid

        _12_dub_to_vid.merge_video_audio()
        Path(_AUDIO_DONE_MARKER).write_text("webui\n", encoding="utf-8")

    labels = [
        f"批量重生成并直接应用（{len(numbers)} 条）",
        "按时间轴拼接完整音轨",
        "混音、响度母带并输出成片",
    ]
    return list(zip(labels, [step_tts, step_merge, step_master]))


# ------------
# Regeneration candidates
# ------------


def candidate_root(number, candidate_id=None):
    root = CANDIDATE_DIR / str(int(number))
    if candidate_id is None:
        return root
    cleaned = str(candidate_id).strip()
    if not cleaned or not re.fullmatch(r"[A-Za-z0-9_-]+", cleaned):
        raise ValueError("无效的候选编号")
    return root / cleaned


def candidate_manifest_path(number, candidate_id=None):
    return candidate_root(number, candidate_id) / "manifest.json"


def _read_candidate_manifest_path(number, path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or int(data.get("number", -1)) != int(number):
        return None
    line_count = int(data.get("line_count") or 0)
    if line_count < 1:
        return None
    root = path.parent
    for index in range(line_count):
        temp = root / "tmp" / f"{int(number)}_{index}_temp.wav"
        if not temp.is_file() or temp.stat().st_size < 100:
            return None
    fits = bool(data.get("fits", True))
    for index in range(line_count):
        seg = root / "segs" / f"{int(number)}_{index}.wav"
        if not seg.is_file() or seg.stat().st_size < 100:
            return None
    data["fits"] = fits
    data["status"] = data.get("status") or ("fitted" if fits else "forced_merge")
    return data


def list_candidate_manifests(number):
    root = candidate_root(number)
    manifests = []
    legacy = _read_candidate_manifest_path(number, root / "manifest.json")
    if legacy:
        manifests.append(legacy)
    if root.is_dir():
        for path in root.glob("*/manifest.json"):
            manifest = _read_candidate_manifest_path(number, path)
            if manifest:
                manifest["candidate_id"] = manifest.get("candidate_id") or path.parent.name
                manifests.append(manifest)
    return sorted(
        manifests,
        key=lambda item: float(item.get("created_at") or 0),
        reverse=True,
    )


def read_candidate_manifest(number, candidate_id=None):
    if candidate_id is not None:
        return _read_candidate_manifest_path(
            number,
            candidate_manifest_path(number, candidate_id),
        )
    manifests = list_candidate_manifests(number)
    return manifests[0] if manifests else None


def discard_candidate(number, candidate_id=None):
    root = candidate_root(number, candidate_id)
    if root.exists():
        shutil.rmtree(root)
    task_root = candidate_root(number)
    if candidate_id is not None and task_root.is_dir() and not any(task_root.iterdir()):
        task_root.rmdir()
    return {
        "number": int(number),
        "candidate_id": candidate_id,
        "discarded": True,
    }


def read_merge_pending():
    if not MERGE_PENDING_PATH.is_file():
        return []
    try:
        data = json.loads(MERGE_PENDING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    numbers = data.get("numbers") if isinstance(data, dict) else None
    if not isinstance(numbers, list):
        return []
    cleaned = sorted({int(n) for n in numbers})
    return cleaned


def write_merge_pending(numbers):
    cleaned = sorted({int(n) for n in numbers})
    MERGE_PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not cleaned:
        MERGE_PENDING_PATH.unlink(missing_ok=True)
        return []
    MERGE_PENDING_PATH.write_text(
        json.dumps({"numbers": cleaned, "updated_at": time.time()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cleaned


def mark_merge_pending(numbers):
    pending = set(read_merge_pending())
    pending.update(int(n) for n in numbers)
    return write_merge_pending(pending)


def clear_merge_pending(numbers=None):
    if numbers is None:
        MERGE_PENDING_PATH.unlink(missing_ok=True)
        return []
    drop = {int(n) for n in numbers}
    remaining = [n for n in read_merge_pending() if n not in drop]
    return write_merge_pending(remaining)


def generate_candidate_steps(task_number, count=1, force_shorten=False):
    number = validate_task_numbers([task_number])[0]
    count = int(count)
    if not 1 <= count <= 5:
        raise ValueError("候选数量必须在 1 到 5 之间")
    batch_key = str(time.time_ns())
    candidate_ids = []
    for index in range(count):
        candidate_id = f"{batch_key}-{index + 1}"
        candidate_ids.append(candidate_id)

    def step_generate():
        from core import _10_gen_audio
        from core.utils.config_utils import load_key

        tts_method = load_key("tts_method")
        if tts_method == "gpt_sovits":
            max_workers = 1
        elif tts_method == "custom_tts":
            max_workers = int(load_key("noiz_tts.max_workers") or 1)
        elif tts_method == "elevenlabs_tts":
            max_workers = int(load_key("elevenlabs_tts.max_workers") or 1)
        else:
            max_workers = int(load_key("max_workers") or 1)
        max_workers = max(1, min(count, max_workers))

        def generate_one(candidate_id):
            return _10_gen_audio.generate_task_candidate(
                number,
                candidate_id=candidate_id,
                force_shorten=force_shorten,
            )

        if max_workers == 1:
            for candidate_id in candidate_ids:
                generate_one(candidate_id)
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(generate_one, candidate_id): candidate_id
                for candidate_id in candidate_ids
            }
            try:
                for future in as_completed(futures):
                    future.result()
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

    label = (
        f"LLM 缩短并生成任务 {number} 的候选配音"
        if force_shorten
        else f"并发生成任务 {number} 的 {count} 个候选配音"
    )
    return [(label, step_generate)]


def _writeback_candidate_subtitles(manifest):
    """Atomically write shortened translated cues from an accepted candidate."""
    if not manifest.get("writeback_subtitles", True):
        return False
    candidate_cues = manifest.get("candidate_cues") or []
    if not candidate_cues:
        return False

    by_cue = {int(item["cue"]): " ".join(str(item.get("text") or "").split()).strip() for item in candidate_cues}
    if any(not text for text in by_cue.values()):
        raise ValueError("候选字幕存在空文本，无法写回")

    cues = parse_srt(TRANS_SRT)
    if not cues:
        raise ValueError("还没有译文字幕，无法写回缩写结果")
    updated = False
    for cue in cues:
        text = by_cue.get(int(cue["cue"]))
        if text is None:
            continue
        if cue["text"] != text:
            cue["text"] = text
            updated = True

    if not updated:
        return False

    from core.speaker_tagging import load_speaker_tags

    trans_content = _cues_to_srt(
        [
            {
                "cue": cue["cue"],
                "start": cue["start"],
                "end": cue["end"],
                "text": cue["text"],
            }
            for cue in cues
        ],
        "text",
    )
    tags = load_speaker_tags(str(TRANS_SRT))
    tag_items = []
    for cue in cues:
        tag = tags.get(cue["cue"], {})
        tag_items.append({
            "cue": cue["cue"],
            "speaker": tag.get("speaker") or "unknown",
            "merge_with_previous": bool(tag.get("merge_with_previous", False)),
            "confidence": float(tag.get("confidence", 1.0) or 1.0),
            "reason": str(tag.get("reason") or ""),
            "manual_override": bool(tag.get("manual_override", False)),
        })
    tags_content = json.dumps(
        {
            "source_hash": _source_hash(trans_content),
            "model": "manual",
            "items": tag_items,
        },
        ensure_ascii=False,
        indent=2,
    )
    _atomic_write_many({
        Path(TRANS_SRT): trans_content,
        TRANS_AUDIO_SRT: trans_content,
        Path(UPLOAD_TRANS_SRT): trans_content,
        Path(SPEAKER_TAGS_FILE): tags_content,
    })
    return True


def accept_candidate(task_number, candidate_id=None):
    """Promote a candidate into the live cache without remastering yet."""
    number = validate_task_numbers([task_number])[0]
    manifest = read_candidate_manifest(number, candidate_id)
    if not manifest:
        raise ValueError(f"任务 {number} 没有可采用的候选配音")
    # Forced-merge candidates (still over max-speed window) are allowed.

    root = candidate_root(number, manifest.get("candidate_id"))
    line_count = int(manifest["line_count"])
    Path(_AUDIO_TMP_DIR).mkdir(parents=True, exist_ok=True)
    Path(_AUDIO_SEGS_DIR).mkdir(parents=True, exist_ok=True)

    text_changed = _writeback_candidate_subtitles(manifest)

    # Stage into sidecar files first, then atomically replace live paths.
    staged = []
    try:
        for index in range(line_count):
            src_temp = root / "tmp" / f"{number}_{index}_temp.wav"
            src_seg = root / "segs" / f"{number}_{index}.wav"
            dst_temp = Path(_AUDIO_TMP_DIR) / f"{number}_{index}_temp.wav"
            dst_seg = Path(_AUDIO_SEGS_DIR) / f"{number}_{index}.wav"
            stage_temp = dst_temp.with_suffix(".accepting.wav")
            stage_seg = dst_seg.with_suffix(".accepting.wav")
            shutil.copy2(src_temp, stage_temp)
            shutil.copy2(src_seg, stage_seg)
            staged.append((stage_temp, dst_temp, stage_seg, dst_seg))

        for stage_temp, dst_temp, stage_seg, dst_seg in staged:
            stage_temp.replace(dst_temp)
            stage_seg.replace(dst_seg)
    except Exception:
        for stage_temp, _, stage_seg, _ in staged:
            stage_temp.unlink(missing_ok=True)
            stage_seg.unlink(missing_ok=True)
        raise

    tasks_df = pd.read_excel(_8_1_AUDIO_TASK)
    matches = tasks_df.index[tasks_df["number"] == number].tolist()
    if not matches:
        raise ValueError(f"未知任务编号：{number}")
    row_index = matches[0]
    candidate_cues = manifest.get("candidate_cues") or []
    if candidate_cues:
        texts = [" ".join(str(item.get("text") or "").split()).strip() for item in candidate_cues]
        candidate_text = " ".join(texts).strip()
        previous_lines = tasks_df.at[row_index, "lines"]
        if isinstance(previous_lines, str):
            try:
                previous_lines = eval(previous_lines)
            except Exception:
                previous_lines = [previous_lines]
        if not isinstance(previous_lines, list):
            previous_lines = [candidate_text]
        if len(previous_lines) == 1 or ("speaker" in tasks_df.columns and pd.notna(tasks_df.at[row_index, "speaker"])):
            _set_task_cell(tasks_df, row_index, "lines", [candidate_text])
        else:
            _set_task_cell(tasks_df, row_index, "lines", texts)
        tasks_df.at[row_index, "text"] = candidate_text
    _set_task_cell(tasks_df, row_index, "real_dur", float(manifest["real_dur"]))
    _set_task_cell(tasks_df, row_index, "new_sub_times", str(manifest["new_sub_times"]))
    tasks_df.to_excel(_8_1_AUDIO_TASK, index=False)

    discard_candidate(number)
    mark_merge_pending([number])
    # Keep the previous mastered video playable until the user remasters.
    Path(_AUDIO_DONE_MARKER).unlink(missing_ok=True)

    return {
        "number": number,
        "accepted": True,
        "text_changed": text_changed,
        "merge_pending": read_merge_pending(),
    }


def remaster_steps():
    pending = read_merge_pending()
    if not pending:
        raise ValueError("没有待重新合片的任务")

    def step_merge():
        from core import _11_merge_audio

        _11_merge_audio.merge_full_audio()

    def step_master():
        from core import _12_dub_to_vid

        _12_dub_to_vid.merge_video_audio()
        Path(_AUDIO_DONE_MARKER).write_text("webui\n", encoding="utf-8")
        clear_merge_pending()
        SUBTITLE_STALE_PATH.unlink(missing_ok=True)

    labels = [
        f"按时间轴拼接完整音轨（含 {len(pending)} 条已采用修改）",
        "混音、响度母带并输出成片",
    ]
    return list(zip(labels, [step_merge, step_master]))
