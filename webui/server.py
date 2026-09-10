"""
FastAPI backend for the dubbing web UI.

Thin request layer: every route delegates to webui.workspace (read/write state)
or webui.pipeline (build the step list) and never reimplements pipeline logic.
"""

from __future__ import annotations

import glob
import re
import shutil
from pathlib import Path

from typing import List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core._1_ytdlp import GENERATED_AUDIO_NAMES, write_input_manifest
from core.utils.config_utils import load_key
from webui import editing, jobs, pipeline, workspace

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="video translator", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


def _guard(action):
    """Turn pipeline/config errors into 400s carrying a readable message."""
    try:
        return action()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc) or exc.__class__.__name__)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ------------
# State
# ------------


@app.get("/api/status")
def status():
    def payload():
        from core.utils.api_usage import read_usage_summary

        return {
            "job": jobs.snapshot(),
            "workspace": workspace.read_state(),
            "usage": read_usage_summary(),
        }

    return _guard(payload)


@app.get("/api/usage")
def usage():
    from core.utils.api_usage import read_usage_summary

    return _guard(read_usage_summary)


@app.get("/api/stages")
def stages():
    return _guard(lambda: {"stages": pipeline.stages_for_mode(), "mode": pipeline.prepare_mode()})


@app.get("/api/speakers")
def speakers():
    return _guard(workspace.read_speakers)


@app.get("/api/tasks")
def tasks():
    return _guard(workspace.read_tasks)


@app.get("/api/loudness")
def loudness():
    return _guard(workspace.read_loudness)


# ------------
# Config and secrets
# ------------


@app.get("/api/config")
def get_config():
    return _guard(workspace.read_config)


@app.patch("/api/config")
def patch_config(patch=Body(...)):
    return _guard(lambda: workspace.write_config(patch))


@app.post("/api/secrets")
def post_secret(payload=Body(...)):
    return _guard(lambda: workspace.write_secret(payload.get("name"), payload.get("value")))


# ------------
# Uploads
# ------------


def _clear_existing_media():
    allowed = set(load_key("allowed_video_formats")) | set(load_key("allowed_audio_formats"))
    for path in glob.glob("output/*"):
        file = Path(path)
        if not file.is_file() or file.suffix.lower().lstrip(".") not in allowed:
            continue
        if file.name.startswith("output") or file.name in GENERATED_AUDIO_NAMES:
            continue
        file.unlink()


@app.post("/api/upload/media")
def upload_media(file: UploadFile = File(...)):
    def action():
        video_formats = set(load_key("allowed_video_formats"))
        audio_formats = set(load_key("allowed_audio_formats"))
        suffix = Path(file.filename or "").suffix.lower()
        ext = suffix.lstrip(".")
        if ext in video_formats:
            media_type = "video"
        elif ext in audio_formats:
            media_type = "audio"
        else:
            raise ValueError(f"不支持的媒体格式：.{ext}")

        _clear_existing_media()
        stem = re.sub(r"[^\w\-_.]", "", Path(file.filename).stem.replace(" ", "_")) or "media"
        target = OUTPUT_DIR / f"{stem}{suffix}"
        with target.open("wb") as dst:
            shutil.copyfileobj(file.file, dst)
        write_input_manifest(str(target), media_type)
        return workspace.read_state()

    return _guard(action)


@app.post("/api/upload/srt")
def upload_srt(kind: str, file: UploadFile = File(...)):
    def action():
        targets = {"trans": workspace.UPLOAD_TRANS_SRT, "src": workspace.UPLOAD_SRC_SRT}
        if kind not in targets:
            raise ValueError(f"未知字幕类型：{kind}")
        if not (file.filename or "").lower().endswith(".srt"):
            raise ValueError("只接受 .srt 文件")
        target = targets[kind]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as dst:
            shutil.copyfileobj(file.file, dst)
        if not workspace.parse_srt(target):
            target.unlink(missing_ok=True)
            raise ValueError("SRT 里没有解析到有效字幕块")
        return workspace.read_state()

    return _guard(action)


@app.delete("/api/upload/srt")
def delete_srt(kind: str):
    def action():
        targets = {"trans": workspace.UPLOAD_TRANS_SRT, "src": workspace.UPLOAD_SRC_SRT}
        if kind not in targets:
            raise ValueError(f"未知字幕类型：{kind}")
        targets[kind].unlink(missing_ok=True)
        return workspace.read_state()

    return _guard(action)


# ------------
# Jobs
# ------------


@app.post("/api/jobs/prepare")
def start_prepare():
    return _guard(lambda: jobs.start("prepare", pipeline.prepare_steps()))


@app.post("/api/jobs/dub")
def start_dub(payload=Body(default={})):
    force = bool((payload or {}).get("force", True))
    return _guard(lambda: jobs.start("dub", pipeline.dub_steps(force=force)))


@app.get("/api/alignment")
def get_alignment():
    return _guard(workspace.read_alignment)


@app.post("/api/alignment/apply")
def apply_alignment():
    return _guard(lambda: jobs.start("alignment_apply", pipeline.alignment_apply_steps()))


@app.post("/api/alignment/skip")
def skip_alignment():
    return _guard(lambda: jobs.start("alignment_skip", pipeline.alignment_skip_steps()))


@app.post("/api/jobs/control")
def control_job(payload=Body(...)):
    return _guard(lambda: jobs.control((payload or {}).get("action")))


@app.post("/api/reset")
def reset_workspace():
    def action():
        if jobs.snapshot()["state"] in ("running", "paused"):
            raise RuntimeError("任务正在运行，先停止它。")
        pipeline.archive_workspace()
        return workspace.read_state()

    return _guard(action)


# ------------
# Speaker editing
# ------------


@app.post("/api/speakers/validate")
def validate_speakers(payload=Body(...)):
    body = payload or {}
    if body.get("cues") is not None:
        media = workspace.read_media()
        duration = media.get("duration") if media else None
        return _guard(lambda: editing.validate_cue_items(body.get("cues"), duration))
    return _guard(lambda: {"items": editing.validate_speaker_items(body.get("items"))})


@app.post("/api/cues/split")
def split_cue(payload=Body(...)):
    return _guard(lambda: editing.split_cue_draft(payload or {}))


@app.post("/api/speakers/apply")
def apply_speakers(payload=Body(...)):
    def action():
        body = payload or {}
        cues = body.get("cues")
        if cues is not None:
            media = workspace.read_media()
            duration = media.get("duration") if media else None
            keep_original = body.get("keep_original")
            editing.validate_cue_items(cues, duration, keep_original=keep_original)
            return jobs.start(
                "rebuild_speakers",
                pipeline.rebuild_cues_steps(
                    cues, media_duration=duration, keep_original=keep_original
                ),
            )
        items = body.get("items")
        # Validate synchronously so the UI gets immediate field errors.
        editing.validate_speaker_items(items)
        return jobs.start("rebuild_speakers", pipeline.rebuild_speakers_steps(items))

    return _guard(action)


# ------------
# Reference overrides & selective dub
# ------------


@app.get("/api/tasks/reference/library")
def reference_library():
    return _guard(editing.list_reference_library)


@app.post("/api/tasks/reference")
async def upload_reference(
    files: List[UploadFile] = File(...),
    numbers: Optional[str] = Form(None),
    mode: str = Form("broadcast"),
):
    task_numbers = []
    if numbers:
        task_numbers = [int(part) for part in numbers.split(",") if part.strip()]
    payloads = []
    names = []
    for upload in files:
        payloads.append(await upload.read())
        names.append(upload.filename or "")
    return _guard(
        lambda: editing.set_reference_overrides(task_numbers, payloads, names, mode=mode)
    )


@app.post("/api/tasks/reference/copy")
def copy_reference(payload=Body(...)):
    body = payload or {}
    return _guard(
        lambda: editing.copy_reference_from_task(body.get("source"), body.get("numbers") or [])
    )


@app.post("/api/tasks/reference/clear")
def clear_reference(payload=Body(...)):
    return _guard(lambda: editing.clear_reference_overrides((payload or {}).get("numbers") or []))


@app.patch("/api/tasks/text")
def patch_task_text(payload=Body(...)):
    body = payload or {}
    return _guard(lambda: editing.update_task_text(body.get("number"), body.get("text")))


@app.post("/api/jobs/regenerate")
def regenerate_selected(payload=Body(...)):
    def action():
        numbers = editing.validate_task_numbers((payload or {}).get("numbers") or [])
        return jobs.start("regenerate", pipeline.selective_dub_steps(numbers))

    return _guard(action)


@app.post("/api/tasks/keep-original")
def keep_original_tasks(payload=Body(...)):
    def action():
        numbers = editing.validate_task_numbers((payload or {}).get("numbers") or [])
        return editing.keep_original_tasks(numbers)

    return _guard(action)


@app.post("/api/jobs/candidate")
def generate_candidate(payload=Body(...)):
    def action():
        body = payload or {}
        number = body.get("number")
        if number is None:
            raise ValueError("请提供任务编号")
        count = int(body.get("count") or 1)
        return jobs.start(
            "candidate",
            pipeline.candidate_steps(
                number,
                count=count,
                force_shorten=bool(body.get("force_shorten", False)),
            ),
        )

    return _guard(action)


@app.post("/api/tasks/candidate/accept")
def accept_candidate(payload=Body(...)):
    body = payload or {}
    return _guard(
        lambda: editing.accept_candidate(
            body.get("number"),
            body.get("candidate_id"),
        )
    )


@app.post("/api/tasks/candidate/discard")
def discard_candidate(payload=Body(...)):
    def action():
        number = (payload or {}).get("number")
        if number is None:
            raise ValueError("请提供任务编号")
        editing.validate_task_numbers([number])
        return editing.discard_candidate(
            number,
            (payload or {}).get("candidate_id"),
        )

    return _guard(action)


@app.post("/api/jobs/remaster")
def remaster_pending():
    return _guard(lambda: jobs.start("remaster", pipeline.remaster_steps()))
