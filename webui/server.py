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

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core._1_ytdlp import GENERATED_AUDIO_NAMES, write_input_manifest
from core.utils.config_utils import load_key
from webui import jobs, pipeline, workspace

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VideoLingo Dubbing", docs_url=None, redoc_url=None)
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
    return _guard(lambda: {"job": jobs.snapshot(), "workspace": workspace.read_state()})


@app.get("/api/stages")
def stages():
    return {"stages": pipeline.STAGES}


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
