"""
Character-level speech alignment via Qwen DashScope filetrans.

Uploads a 16 kHz mono clip to GCS, submits an async transcription job with
enable_words=true, and caches the resulting word/character timestamps.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from rich import print as rprint

from core.utils import load_key
from core.utils.config_utils import load_secret
from core.utils.models import _CHAR_ALIGNMENT_FILE, _VOCAL_AUDIO_FILE

SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/"


# ------------
# Config / cache helpers
# ------------


def _cfg(key, default=None):
    try:
        return load_key(f"qwen_asr.{key}")
    except KeyError:
        return default


def _api_key():
    key = load_secret("qwen_asr.api_key", "QWEN_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("Missing Qwen API key (QWEN_API_KEY or qwen_asr.api_key)")
    text = key.strip()
    if text in {"your_qwen_api_key", "YOUR_API_KEY"}:
        raise RuntimeError("Qwen API key is still a placeholder")
    return text


def _audio_sha1(path):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _alignment_signature(audio_path, language):
    return {
        "model": str(_cfg("model", "qwen3-asr-flash-filetrans")),
        "language": language,
        "audio_sha1": _audio_sha1(audio_path),
        "enable_words": True,
        "diarization": _diarization_enabled(),
    }


def _cache_valid(audio_path, language):
    cache = Path(_CHAR_ALIGNMENT_FILE)
    if not cache.is_file():
        return False
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("signature") == _alignment_signature(audio_path, language)


def load_char_alignment():
    cache = Path(_CHAR_ALIGNMENT_FILE)
    if not cache.is_file():
        return None
    return json.loads(cache.read_text(encoding="utf-8"))


def char_intervals_from_alignment(alignment=None, join_gap=0.2):
    payload = alignment or load_char_alignment()
    if not payload:
        return []
    words = payload.get("words") or []
    intervals = []
    for item in words:
        start = float(item["start"])
        end = float(item["end"])
        if end <= start:
            end = start + 0.04
        if intervals and start - intervals[-1][1] <= join_gap:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    return intervals


# ------------
# Audio prep + GCS upload
# ------------


def _resample_to_16k_mono(audio_path, dest_path):
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(dest_path),
        ],
        check=True,
    )


def _upload_to_gcs(local_path):
    bucket = str(_cfg("gcs_bucket", "hihub-test"))
    prefix = str(_cfg("gcs_prefix", "qwen_asr_align")).strip("/")
    digest = _audio_sha1(local_path)[:16]
    object_name = f"{prefix}/{digest}_{Path(local_path).name}"
    uri = f"gs://{bucket}/{object_name}"
    public_url = f"https://storage.googleapis.com/{bucket}/{object_name}"
    rprint(f"[cyan]☁️ Uploading alignment audio to {uri}[/cyan]")
    subprocess.run(
        ["gcloud", "storage", "cp", str(local_path), uri],
        check=True,
        capture_output=True,
        text=True,
    )
    return public_url


# ------------
# DashScope HTTP
# ------------


def _http_json(method, url, key, payload=None, timeout=120):
    headers = {"Authorization": f"Bearer {key}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen ASR HTTP {exc.code}: {body[:500]}") from exc


def _diarization_enabled():
    return bool(_cfg("diarization", False))


def _build_submit_payload(file_url, language, model):
    """
    qwen3-asr-flash-filetrans takes a single file_url and needs enable_words to
    get character timestamps, but has no speaker diarization. The filetrans v2
    family (qwen-audio-3.0 / fun-asr / paraformer) takes a file_urls array, has
    word timestamps always on, and is the only one supporting diarization.
    """
    if model.startswith("qwen3-asr"):
        parameters = {"enable_words": True}
        if language:
            parameters["language"] = language
        return {"model": model, "input": {"file_url": file_url}, "parameters": parameters}

    parameters = {}
    if language:
        parameters["language_hints"] = [language]
    if _diarization_enabled():
        parameters["diarization_enabled"] = True
        speaker_count = _cfg("speaker_count")
        if speaker_count:
            parameters["speaker_count"] = int(speaker_count)
    return {"model": model, "input": {"file_urls": [file_url]}, "parameters": parameters}


def _submit_filetrans(file_url, language, key):
    model = str(_cfg("model", "qwen3-asr-flash-filetrans"))
    payload = _build_submit_payload(file_url, language, model)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    request = urllib.request.Request(
        SUBMIT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen ASR HTTP {exc.code}: {body[:500]}") from exc


def _poll_task(task_id, key):
    interval = float(_cfg("poll_interval_s", 3))
    timeout = float(_cfg("poll_timeout_s", 900))
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _http_json("GET", TASK_URL + task_id, key, timeout=60)
        state = status.get("output", {}).get("task_status")
        if state in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return status
        rprint(f"[blue]⏳ Qwen ASR polling: {state}[/blue]")
        time.sleep(interval)
    raise TimeoutError(f"Qwen ASR task {task_id} timed out after {timeout}s")


def _fetch_transcription(status):
    output = status.get("output") or {}
    result = output.get("result") or {}
    if not result and output.get("results"):
        result = output["results"][0]
    url = result.get("transcription_url")
    if not url:
        raise RuntimeError(f"Qwen ASR succeeded without transcription_url: {output}")
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _record_task_usage(status, task_id=None):
    try:
        from core.utils.api_usage import record_qwen_usage

        model = str(_cfg("model", "qwen3-asr-flash-filetrans"))
        recorded = record_qwen_usage(model, status.get("usage"), task_id=task_id)
        if recorded:
            rprint(
                f"[blue]💳 Qwen ASR usage +{recorded['seconds']:.3f}s "
                f"(¥{recorded['cost_cny']:.4f})[/blue]"
            )
    except Exception as exc:
        rprint(f"[yellow]⚠️ Failed to record Qwen usage: {exc}[/yellow]")


def parse_words_from_transcription(transcription, time_offset=0.0):
    words = []
    sentences = []
    for track in transcription.get("transcripts") or []:
        for sentence in track.get("sentences") or []:
            speaker_id = sentence.get("speaker_id")
            sentence_words = []
            for item in sentence.get("words") or []:
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                start = float(item.get("begin_time", 0)) / 1000.0 + time_offset
                end = float(item.get("end_time", item.get("begin_time", 0))) / 1000.0 + time_offset
                word = {
                    "text": text,
                    "start": start,
                    "end": end,
                    "punctuation": item.get("punctuation") or "",
                    "speaker_id": item.get("speaker_id", speaker_id),
                }
                words.append(word)
                sentence_words.append(word)
            sentences.append(
                {
                    "text": str(sentence.get("text") or "").strip(),
                    "start": float(sentence.get("begin_time", 0)) / 1000.0 + time_offset,
                    "end": float(sentence.get("end_time", 0)) / 1000.0 + time_offset,
                    "speaker_id": speaker_id,
                    "words": sentence_words,
                }
            )
    return words, sentences


# ------------
# Public API
# ------------


def align_audio(audio_path=None, language=None, force=False):
    """
    Align audio and persist character-level timestamps.

    Returns the cached payload: {signature, words, sentences, transcription}.
    Fails hard when the key, upload, or API call fails.
    """
    audio_path = Path(audio_path or _VOCAL_AUDIO_FILE)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Alignment audio missing: {audio_path}")

    language = language or str(_cfg("language") or load_key("whisper.language") or "zh")
    if not force and _cache_valid(audio_path, language):
        rprint(f"[yellow]⚠️ Character alignment cache hit for {audio_path.name}[/yellow]")
        return load_char_alignment()

    key = _api_key()
    signature = _alignment_signature(audio_path, language)

    with tempfile.TemporaryDirectory(prefix="qwen_align_") as tmp:
        mono_path = Path(tmp) / "align_16k.wav"
        _resample_to_16k_mono(audio_path, mono_path)
        public_url = _upload_to_gcs(mono_path)
        submitted = _submit_filetrans(public_url, language, key)
        task_id = submitted.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Qwen ASR submit failed: {submitted}")
        rprint(f"[cyan]🎤 Qwen ASR task submitted: {task_id}[/cyan]")
        status = _poll_task(task_id, key)
        state = status.get("output", {}).get("task_status")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Qwen ASR task ended with {state}: {status}")
        _record_task_usage(status, task_id=task_id)
        transcription = _fetch_transcription(status)

    words, sentences = parse_words_from_transcription(transcription)
    payload = {
        "signature": signature,
        "words": words,
        "sentences": sentences,
        "transcription": transcription,
        "task_id": task_id,
        "audio_url": public_url,
    }
    out = Path(_CHAR_ALIGNMENT_FILE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rprint(
        f"[green]✅ Character alignment saved: {len(words)} words, "
        f"{len(sentences)} sentences -> {out}[/green]"
    )
    return payload


def align_audio_segment(audio_path, start, end, language=None):
    """
    Align a clipped segment and return WhisperX-compatible segments.

    Times in the returned words are absolute (start offset applied).
    """
    audio_path = Path(audio_path)
    language = language or str(_cfg("language") or load_key("whisper.language") or "zh")
    key = _api_key()

    with tempfile.TemporaryDirectory(prefix="qwen_seg_") as tmp:
        clip_path = Path(tmp) / "clip_16k.wav"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(start),
                "-to", str(end),
                "-i", str(audio_path),
                "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le",
                str(clip_path),
            ],
            check=True,
        )
        public_url = _upload_to_gcs(clip_path)
        submitted = _submit_filetrans(public_url, language, key)
        task_id = submitted.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Qwen ASR segment submit failed: {submitted}")
        status = _poll_task(task_id, key)
        if status.get("output", {}).get("task_status") != "SUCCEEDED":
            raise RuntimeError(f"Qwen ASR segment failed: {status}")
        _record_task_usage(status, task_id=task_id)
        transcription = _fetch_transcription(status)

    words, sentences = parse_words_from_transcription(transcription, time_offset=float(start))
    segments = []
    for sentence in sentences:
        segments.append(
            {
                "text": sentence["text"],
                "start": sentence["start"],
                "end": sentence["end"],
                "speaker_id": sentence.get("speaker_id"),
                "words": [
                    {
                        "word": item["text"],
                        "start": item["start"],
                        "end": item["end"],
                    }
                    for item in sentence["words"]
                ],
            }
        )
    if not segments and words:
        segments.append(
            {
                "text": "".join(item["text"] for item in words),
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "speaker_id": None,
                "words": [
                    {
                        "word": item["text"],
                        "start": item["start"],
                        "end": item["end"],
                    }
                    for item in words
                ],
            }
        )
    return {"segments": segments}


if __name__ == "__main__":
    align_audio(force=True)
