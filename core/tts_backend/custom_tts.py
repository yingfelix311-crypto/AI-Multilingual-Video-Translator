from pathlib import Path
from collections import deque
import json
import math
import threading
import time
import requests
from pydub import AudioSegment
from core.utils import load_key, except_handler
from core.utils.config_utils import load_secret
from core.utils.models import _AUDIO_REF_OVERRIDES_DIR, _AUDIO_REFERS_DIR

NOIZ_BASE_URL = "https://noiz.ai/v1"
MIN_REF_SECONDS = 3.0
MAX_REF_SECONDS = 12.0
NOIZ_RATE_LIMIT = 60
NOIZ_RATE_WINDOW = 30.0
_REQUEST_TIMES = deque()
_RATE_LOCK = threading.Lock()


def _wait_for_rate_limit():
    """Keep all Noiz requests within the account's 60 requests / 30s limit."""
    while True:
        with _RATE_LOCK:
            now = time.monotonic()
            while _REQUEST_TIMES and now - _REQUEST_TIMES[0] >= NOIZ_RATE_WINDOW:
                _REQUEST_TIMES.popleft()
            if len(_REQUEST_TIMES) < NOIZ_RATE_LIMIT:
                _REQUEST_TIMES.append(now)
                return
            wait_seconds = NOIZ_RATE_WINDOW - (now - _REQUEST_TIMES[0]) + 0.01
        time.sleep(wait_seconds)


def _get_api_key():
    api_key = load_secret("noiz_tts.api_key", "NOIZ_API_KEY")
    if not api_key or api_key in ("YOUR_API_KEY",):
        raise ValueError("NoizAI API key is not set. Put it in config noiz_tts.api_key or NOIZ_API_KEY file.")
    return api_key


def _ensure_refers_dir():
    current_dir = Path.cwd()
    refers_dir = current_dir / _AUDIO_REFERS_DIR
    sample = refers_dir / "1.wav"
    if sample.exists():
        return refers_dir

    from core._9_refer_audio import extract_refer_audio_main
    print(f"Reference audio missing, extracting to {_AUDIO_REFERS_DIR}...")
    extract_refer_audio_main()
    if not sample.exists():
        raise FileNotFoundError(f"Failed to extract reference audio into {_AUDIO_REFERS_DIR}")
    return refers_dir


def _audio_duration_seconds(path):
    return len(AudioSegment.from_file(path)) / 1000.0


def _atomic_export(audio, out_path):
    out_path = Path(out_path)
    temp_path = out_path.with_name(
        f".{out_path.stem}.{threading.get_ident()}.tmp.wav"
    )
    try:
        audio.export(temp_path, format="wav")
        temp_path.replace(out_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _override_ref_path(number):
    return Path(_AUDIO_REF_OVERRIDES_DIR) / f"{number}.wav"


def _sentence_ref_path(refers_dir, number):
    override = _override_ref_path(number)
    if override.is_file():
        return override, "override"
    primary = refers_dir / f"{number}.wav"
    if primary.exists():
        return primary, "auto"
    raise FileNotFoundError(f"Reference audio not found for sentence {number}")


def _resolve_clone_source(number):
    """
    Prefer a manual override for this task; otherwise use the timestamp refer.
    If it is shorter than 3s, loop only that same clip until it reaches 3s.
    """
    refers_dir = _ensure_refers_dir()
    sentence_ref, source = _sentence_ref_path(refers_dir, number)
    duration = _audio_duration_seconds(sentence_ref)
    if duration <= 0:
        raise ValueError(f"Reference audio is empty for sentence {number}: {sentence_ref}")
    audio = AudioSegment.from_file(sentence_ref)
    out_path = refers_dir / f"_noiz_ref_{number}.wav"
    label = "override" if source == "override" else "sentence refer"

    if duration < MIN_REF_SECONDS:
        repeat_count = math.ceil(MIN_REF_SECONDS / duration)
        repeated = (audio * repeat_count)[: int(MIN_REF_SECONDS * 1000)]
        _atomic_export(repeated, out_path)
        print(
            f"{label} #{number} is {duration:.2f}s; "
            f"looped the same clip {repeat_count}x to {MIN_REF_SECONDS:.2f}s"
        )
        return {"type": "file", "path": out_path, "source": source}

    if duration > MAX_REF_SECONDS:
        audio = audio[: int(MAX_REF_SECONDS * 1000)]
        _atomic_export(audio, out_path)
        print(f"Using {label} #{number}: trimmed {duration:.2f}s -> {MAX_REF_SECONDS:.1f}s")
        return {"type": "file", "path": out_path, "source": source}

    print(f"Using {label} #{number}: {duration:.2f}s")
    return {"type": "file", "path": sentence_ref, "source": source}


def _save_audio_response(response, save_path):
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.content

    if response.status_code != 200:
        raise RuntimeError(f"NoizAI TTS error {response.status_code}: {response.text[:300]}")

    # Noiz may return HTTP 200 with JSON error payload
    if "application/json" in content_type or (body[:1] == b"{"):
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get("code", 0) not in (0, None) and "message" in payload:
            raise RuntimeError(f"NoizAI TTS error: {payload.get('message')}")
        if isinstance(payload, dict) and "message" in payload and "audio" not in content_type:
            if payload.get("code") not in (0, None):
                raise RuntimeError(f"NoizAI TTS error: {payload.get('message')}")

    if len(body) < 1000:
        raise RuntimeError(f"NoizAI TTS returned unexpectedly small payload ({len(body)} bytes)")

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(body)
    duration = response.headers.get("X-Audio-Duration", "unknown")
    print(f"Audio saved to {save_path} (duration: {duration}s)")


def _build_common_data(text):
    target_lang = load_key("noiz_tts.target_lang") or ""
    speed = load_key("noiz_tts.speed")
    if speed is None:
        speed = 1.0
    similarity_enh = load_key("noiz_tts.similarity_enh")
    if similarity_enh is None:
        similarity_enh = True

    data = {
        "text": text,
        "speed": str(speed),
        "output_format": "wav",
        "trim_silence": "true",
        "similarity_enh": "true" if similarity_enh else "false",
    }
    if target_lang:
        data["target_lang"] = target_lang
    return data


# ------------
# Preset mode: fixed Noiz voice_id
# ------------

@except_handler("Failed to generate audio using NoizAI TTS (preset)", retry=3, delay=1)
def _noiz_tts_preset(text, save_path):
    voice_id = load_key("noiz_tts.voice_id")
    if not voice_id:
        raise ValueError("NoizAI voice_id is not set in config.yaml (noiz_tts.voice_id).")

    data = _build_common_data(text)
    data["voice_id"] = voice_id
    _wait_for_rate_limit()
    response = requests.post(
        f"{NOIZ_BASE_URL}/text-to-speech",
        headers={"Authorization": _get_api_key()},
        data=data,
        timeout=120,
    )
    _save_audio_response(response, save_path)


# ------------
# Clone mode: always use the corresponding timestamp reference
# ------------

@except_handler("Failed to generate audio using NoizAI TTS (clone)", retry=3, delay=1)
def _noiz_tts_clone(text, save_path, number):
    source = _resolve_clone_source(number)
    data = _build_common_data(text)
    data["save_voice"] = "false"

    ref_audio_path = Path(source["path"])
    with open(ref_audio_path, "rb") as f:
        _wait_for_rate_limit()
        response = requests.post(
            f"{NOIZ_BASE_URL}/text-to-speech",
            headers={"Authorization": _get_api_key()},
            data=data,
            files={"file": (ref_audio_path.name, f, "audio/wav")},
            timeout=180,
        )

    _save_audio_response(response, save_path)


def custom_tts(text, save_path, number=None, task_df=None):
    """
    NoizAI TTS backend.
    mode=clone: use the exact timestamp refer; loop that clip itself if under 3s
    mode=preset: fixed voice_id
    """
    mode = load_key("noiz_tts.mode") or "clone"
    if mode == "preset":
        _noiz_tts_preset(text, save_path)
        return

    if number is None:
        raise ValueError("NoizAI clone mode requires sentence number for refer audio.")
    _noiz_tts_clone(text, save_path, number)


if __name__ == "__main__":
    custom_tts("This is a NoizAI TTS test.", "custom_tts_test.wav", number=1)
