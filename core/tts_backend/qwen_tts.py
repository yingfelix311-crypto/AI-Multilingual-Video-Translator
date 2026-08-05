from collections import deque
from pathlib import Path
import ast
import math
import re
import shutil
import tempfile
import threading
import time
import uuid

from pydub import AudioSegment

from core.prompts import get_qwen_emotion_tag_prompt
from core.tts_backend.custom_tts import (
    _atomic_export,
    _audio_duration_seconds,
    _ensure_refers_dir,
    _sentence_ref_path,
)
from core.utils import load_key, except_handler, ask_gpt
from core.utils.config_utils import load_secret


DEFAULT_MODEL = "qwen-audio-3.0-tts-plus"
DEFAULT_VOICE = "longanhuan_v3.6"
DEFAULT_HTTP_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
PLACEHOLDERS = {"", "YOUR_API_KEY", "your_qwen_api_key"}

# Official Qwen-Audio TTS control / rich-language tags
CONTROL_TAGS = {
    "[sad]",
    "[amazed]",
    "[deep and loud shouting]",
    "[trembling]",
    "[angry]",
    "[excited]",
    "[sarcastic]",
    "[curious]",
    "[like dracula]",
    "[bored]",
    "[tired]",
    "[scornful]",
    "[shouting]",
    "[asmr]",
    "[panicked]",
    "[mischievously]",
    "[empathetic]",
    "[whispers]",
    "[reluctantly]",
    "[crying]",
    "[serious]",
    "[very slowly]",
    "[very fast]",
}
RICH_TAGS = {
    "[gasp]",
    "[sighing]",
    "[clears throat]",
    "[giggles]",
    "[laughing]",
    "[cough]",
    "[snorts]",
}
ALLOWED_TAGS = {tag.lower() for tag in CONTROL_TAGS | RICH_TAGS}
TAG_PATTERN = re.compile(r"\[[^\]]+\]")

# Qwen-Audio voice clone wants real speech (docs: >=5s clear speech, prefer 10~20s).
# Never loop short clips — that breaks DashScope enrollment ASR.
MIN_QWEN_REF = 6.0
MAX_QWEN_REF = 12.0

# Official DashScope limits (Beijing):
# qwen-audio-3.0-tts-plus submit RPS = 3 (~180 RPM)
# voice-enrollment submit RPS = 10
TTS_RPS = 3
VOICE_ENROLL_RPS = 10
_TTS_TIMES = deque()
_ENROLL_TIMES = deque()
_TTS_LOCK = threading.Lock()
_ENROLL_LOCK = threading.Lock()


def _wait_rps(times, lock, rps):
    """Keep submit rate under the DashScope RPS quota."""
    window = 1.0
    while True:
        with lock:
            now = time.monotonic()
            while times and now - times[0] >= window:
                times.popleft()
            if len(times) < rps:
                times.append(now)
                return
            wait_seconds = window - (now - times[0]) + 0.01
        time.sleep(max(wait_seconds, 0.01))


def _cfg(key, default=None):
    try:
        return load_key(f"qwen_tts.{key}")
    except KeyError:
        return default


def _get_api_key():
    key = load_secret("qwen_tts.api_key", "QWEN_API_KEY")
    if isinstance(key, str) and key.strip() not in PLACEHOLDERS:
        return key.strip()
    try:
        asr_key = load_secret("qwen_asr.api_key", "QWEN_API_KEY")
        if isinstance(asr_key, str) and asr_key.strip() not in PLACEHOLDERS:
            return asr_key.strip()
    except KeyError:
        pass
    raise ValueError(
        "Qwen TTS API key is not set. Put it in QWEN_API_KEY, "
        "qwen_tts.api_key, or qwen_asr.api_key."
    )


def _configure_dashscope():
    try:
        import dashscope
    except ImportError as exc:
        raise ImportError(
            "dashscope is required for Qwen TTS. Install with: pip install dashscope"
        ) from exc

    dashscope.api_key = _get_api_key()
    dashscope.base_http_api_url = str(_cfg("base_http_api_url", DEFAULT_HTTP_URL))
    dashscope.base_websocket_api_url = str(_cfg("base_websocket_api_url", DEFAULT_WS_URL))
    return dashscope


def _model_name():
    return str(_cfg("model", DEFAULT_MODEL) or DEFAULT_MODEL)


def _language_hints():
    hint = _cfg("language_hints", "zh")
    if isinstance(hint, list):
        return [str(item) for item in hint if item]
    if hint:
        return [str(hint)]
    return ["zh"]


def _preset_voice():
    return str(_cfg("voice", DEFAULT_VOICE) or DEFAULT_VOICE)


def _is_recoverable_clone_error(error):
    text = str(error).lower()
    return (
        "request asr failed" in text
        or "inputdownloadfailed" in text
        or "download audio failed" in text
        or "voice clone rejected" in text
        or "not ready after" in text
        or isinstance(error, TimeoutError)
    )


def _task_row(task_df, number):
    if task_df is None:
        return None
    try:
        rows = task_df[task_df["number"] == number]
    except Exception:
        return None
    if rows is None or len(rows) == 0:
        return None
    return rows.iloc[0]


def _task_speaker(task_df, number):
    row = _task_row(task_df, number)
    if row is None:
        return None
    speaker = row.get("speaker")
    if speaker is None:
        return None
    if isinstance(speaker, float) and math.isnan(speaker):
        return None
    text = str(speaker).strip()
    return text or None


def _task_origin(task_df, number):
    row = _task_row(task_df, number)
    if row is None:
        return None
    origin = row.get("origin")
    if origin is None:
        return None
    if isinstance(origin, float) and math.isnan(origin):
        return None
    text = str(origin).strip()
    return text or None


def _spoken_text(text):
    return re.sub(r"\s+", "", TAG_PATTERN.sub("", str(text or "")))


def _validate_emotion_tagged(original, tagged):
    if not isinstance(tagged, str):
        return False
    tagged = tagged.strip()
    if not tagged:
        return False
    for match in TAG_PATTERN.finditer(tagged):
        if match.group(0).lower() not in ALLOWED_TAGS:
            return False
    return _spoken_text(original) == _spoken_text(tagged)


def _has_emotion_tags(text):
    for match in TAG_PATTERN.finditer(str(text or "")):
        if match.group(0).lower() in ALLOWED_TAGS:
            return True
    return False


def _tag_one_line(text, number=None, task_df=None):
    """Ask LLM for emotion tags. Fail open to original text. Skip if already tagged."""
    source = str(text or "").strip()
    if not source:
        return text
    if _has_emotion_tags(source):
        return text

    speaker = _task_speaker(task_df, number)
    origin = _task_origin(task_df, number)
    prompt = get_qwen_emotion_tag_prompt(source, speaker=speaker, origin=origin)
    try:
        result = ask_gpt(prompt, resp_type="json", log_title="qwen_emotion_tag")
        tagged = (result or {}).get("text", "")
    except Exception as error:
        print(f"Warning: Qwen emotion tagging failed, using original text: {error}")
        return text

    if not _validate_emotion_tagged(source, tagged):
        print("Warning: invalid Qwen emotion tags, using original text")
        return text
    tagged = tagged.strip()
    if tagged != source:
        print(f"Qwen emotion tags #{number}: {tagged}")
    return tagged


def _emotion_tags_enabled():
    try:
        method = load_key("tts_method")
    except KeyError:
        method = None
    if method != "qwen_tts":
        return False
    return _cfg("emotion_tags", True) is not False


def _set_lines_cell(df, row_index, value):
    if "lines" not in df.columns:
        df["lines"] = None
    if df["lines"].dtype != object:
        df["lines"] = df["lines"].astype(object)
    df.at[row_index, "lines"] = value


def tag_audio_tasks_emotions(task_path=None):
    """
    Stage-1 hook: LLM-tag every audio-task line and write back text/lines.
    No-op unless tts_method is qwen_tts and qwen_tts.emotion_tags is on.
    Must run after gen_dub_chunks so SRT line matching is not broken by tags.
    """
    import pandas as pd
    from core.utils.models import _8_1_AUDIO_TASK

    if not _emotion_tags_enabled():
        return {"changed": 0, "total": 0, "skipped": True}

    path = Path(task_path) if task_path else Path(_8_1_AUDIO_TASK)
    if not path.is_file():
        print(f"Warning: audio task not found for emotion tagging: {path}")
        return {"changed": 0, "total": 0, "skipped": True}

    df = pd.read_excel(path)
    if df.empty or "text" not in df.columns:
        return {"changed": 0, "total": 0, "skipped": True}

    changed = 0
    for idx, row in df.iterrows():
        number = row.get("number")
        source = str(row.get("text") or "").strip()
        if not source:
            continue
        tagged = _tag_one_line(source, number=number, task_df=df)
        tagged = str(tagged or "").strip()
        if not tagged or tagged == source:
            continue
        df.at[idx, "text"] = tagged
        _set_lines_cell(df, idx, [tagged])
        changed += 1

    if changed:
        df.to_excel(path, index=False)
        print(f"Qwen emotion tags written to {changed}/{len(df)} audio tasks")
    else:
        print("Qwen emotion tags: no task text changed")
    return {"changed": changed, "total": len(df), "skipped": False}


def _parse_source_numbers(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return []
        if isinstance(parsed, (list, tuple)):
            return [int(item) for item in parsed]
    return []


def _candidate_numbers(number, task_df):
    """Prefer current/source/same-speaker refers, then numeric neighbors. No looping."""
    number = int(number)
    ordered = [number]
    seen = {number}

    row = _task_row(task_df, number)
    if row is not None:
        for item in _parse_source_numbers(row.get("source_numbers")):
            if item not in seen:
                ordered.append(item)
                seen.add(item)

    # Only same-speaker refers may be pooled; never borrow another role's audio.
    speaker = _task_speaker(task_df, number)
    if speaker and task_df is not None:
        same = []
        for _, item in task_df.iterrows():
            other = item.get("speaker")
            if other is None or (isinstance(other, float) and math.isnan(other)):
                continue
            if str(other).strip() != speaker:
                continue
            same.append(int(item["number"]))
        same.sort(key=lambda n: (abs(n - number), n))
        for item in same:
            if item not in seen:
                ordered.append(item)
                seen.add(item)
    return ordered


def _resolve_qwen_clone_source(number, task_df=None):
    """
    Qwen-only refer builder: concatenate real neighboring speech.
    Unlike Noiz/ElevenLabs, never loop a short clip to fake duration.
    """
    refers_dir = _ensure_refers_dir()
    combined = None
    used = []
    for candidate in _candidate_numbers(number, task_df):
        try:
            path, _ = _sentence_ref_path(refers_dir, candidate)
        except FileNotFoundError:
            continue
        duration = _audio_duration_seconds(path)
        if duration <= 0.05:
            continue
        clip = AudioSegment.from_file(path)
        combined = clip if combined is None else combined + clip
        used.append(candidate)
        if len(combined) / 1000.0 >= MIN_QWEN_REF:
            break

    if combined is None:
        raise FileNotFoundError(f"No usable reference audio for Qwen clone #{number}")

    total = len(combined) / 1000.0
    if total > MAX_QWEN_REF:
        combined = combined[: int(MAX_QWEN_REF * 1000)]
        total = MAX_QWEN_REF

    out_path = refers_dir / f"_qwen_ref_{int(number)}.wav"
    _atomic_export(combined, out_path)
    print(
        f"Qwen clone refer #{number}: {total:.2f}s from tasks {used} "
        f"(neighbor concat, no loop)"
    )
    return {"type": "file", "path": out_path, "source": "pooled", "used": used}


def _upload_refer(ref_path):
    """
    Upload refer audio to DashScope OSS and return an oss:// URL.

    create_voice rejects plain oss:// unless the request carries
    X-DashScope-OssResourceResolve: enable (handled by _voice_service).
    This stays inside Aliyun and avoids GCS download failures from Beijing.
    """
    from dashscope.utils.oss_utils import OssUtils

    api_key = _get_api_key()
    ref_path = Path(ref_path)
    with tempfile.TemporaryDirectory(prefix="qwen_tts_ref_") as tmp:
        unique_name = f"vl_{uuid.uuid4().hex[:10]}.wav"
        upload_path = Path(tmp) / unique_name
        shutil.copyfile(ref_path, upload_path)
        print(f"Uploading reference audio for Qwen TTS: {ref_path.name}")
        file_url, _ = OssUtils.upload(
            model="voice-enrollment",
            file_path=str(upload_path),
            api_key=api_key,
        )
    if not file_url or not str(file_url).startswith("oss://"):
        raise RuntimeError(f"DashScope OSS upload failed, got: {file_url}")
    print(f"Reference uploaded: {file_url}")
    return file_url


def _voice_service():
    from dashscope.audio.tts_v2 import VoiceEnrollmentService

    # Let DashScope resolve private oss:// objects during create_voice.
    return VoiceEnrollmentService(
        api_key=_get_api_key(),
        headers={"X-DashScope-OssResourceResolve": "enable"},
    )


def _wait_voice_ready(service, voice_id, timeout_s=90):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        output = service.query_voice(voice_id)
        status = None
        if isinstance(output, dict):
            status = output.get("status")
        elif hasattr(output, "get"):
            status = output.get("status")
        if status == "OK":
            return
        if status == "UNDEPLOYED":
            raise RuntimeError(f"Qwen voice clone rejected: {voice_id} ({output})")
        print(f"Waiting for Qwen voice {voice_id}: {status or 'pending'}")
        time.sleep(1.5)
    raise TimeoutError(f"Qwen voice {voice_id} not ready after {timeout_s}s")


def _create_clone_voice(number, task_df=None):
    source = _resolve_qwen_clone_source(number, task_df=task_df)
    ref_url = _upload_refer(source["path"])
    model = _model_name()
    prefix = f"vl{int(number)}"[:10].lower()
    service = _voice_service()

    create_kwargs = {
        "target_model": model,
        "prefix": prefix,
        "url": ref_url,
        "language_hints": _language_hints(),
        "max_prompt_audio_length": float(_cfg("max_prompt_audio_length", 10.0) or 10.0),
    }
    enable_preprocess = _cfg("enable_preprocess", False)
    if enable_preprocess is not None:
        create_kwargs["enable_preprocess"] = bool(enable_preprocess)

    _wait_rps(_ENROLL_TIMES, _ENROLL_LOCK, VOICE_ENROLL_RPS)
    voice_id = service.create_voice(**create_kwargs)
    if not voice_id:
        raise RuntimeError("Qwen voice clone response missing voice_id")
    print(f"Qwen temporary voice created for task #{number}: {voice_id}")
    try:
        _wait_voice_ready(service, voice_id)
    except Exception:
        _delete_voice(voice_id)
        raise
    return voice_id


def _delete_voice(voice_id):
    if not voice_id:
        return
    try:
        _wait_rps(_ENROLL_TIMES, _ENROLL_LOCK, VOICE_ENROLL_RPS)
        _voice_service().delete_voice(voice_id)
        print(f"Deleted Qwen temporary voice: {voice_id}")
    except Exception as error:
        print(f"Warning: failed to delete Qwen voice {voice_id}: {error}")


def _synthesize(text, save_path, voice):
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    _configure_dashscope()
    model = _model_name()
    speech_rate = float(_cfg("speech_rate", 1.0) or 1.0)
    instruction = _cfg("instruction", "") or None
    if isinstance(instruction, str):
        instruction = instruction.strip() or None

    kwargs = {
        "model": model,
        "voice": voice,
        "format": AudioFormat.WAV_24000HZ_MONO_16BIT,
        "speech_rate": speech_rate,
        "language_hints": _language_hints(),
    }
    if instruction:
        kwargs["instruction"] = instruction

    _wait_rps(_TTS_TIMES, _TTS_LOCK, TTS_RPS)
    synthesizer = SpeechSynthesizer(**kwargs)
    audio = synthesizer.call(text)
    if not audio:
        raise RuntimeError("Qwen TTS returned empty audio")

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(audio, (bytes, bytearray)):
        save_path.write_bytes(audio)
    else:
        save_path.write_bytes(bytes(audio))
    print(f"Qwen TTS audio saved to {save_path}")

    try:
        from core.utils.api_usage import record_qwen_tts_usage

        recorded = record_qwen_tts_usage(model, text=text)
        if recorded:
            print(
                f"Qwen TTS usage +{recorded['characters']} chars "
                f"(¥{recorded['cost_cny']:.4f})"
            )
    except Exception as error:
        print(f"Warning: failed to record Qwen TTS usage: {error}")


def qwen_tts(text, save_path, number=None, task_df=None):
    """
    Qwen-Audio-3.0-TTS backend.
    mode=clone: pool neighboring real refers (no loop), synthesize, then delete
    mode=preset: use a fixed system / custom voice id
    Clone ASR failures fall back to preset voice so one bad refer does not kill the job.
    Emotion tags are applied in stage 1 (tag_audio_tasks_emotions); synth uses text as-is.
    """
    _qwen_tts_synth(text, save_path, number=number, task_df=task_df)


@except_handler("Failed to generate audio using Qwen TTS", retry=2, delay=1)
def _qwen_tts_synth(text, save_path, number=None, task_df=None):
    _configure_dashscope()
    mode = str(_cfg("mode", "clone") or "clone")
    preset = _preset_voice()

    if mode == "preset":
        if not preset:
            raise ValueError("Qwen TTS preset mode requires qwen_tts.voice")
        _synthesize(text, save_path, preset)
        return

    if number is None:
        raise ValueError("Qwen TTS clone mode requires sentence number for refer audio.")

    try:
        voice_id = _create_clone_voice(number, task_df=task_df)
    except Exception as error:
        allow_fallback = _cfg("fallback_preset_on_clone_fail", True)
        if allow_fallback is False or not _is_recoverable_clone_error(error):
            raise
        if not preset:
            raise
        print(
            f"Qwen clone failed for #{number}, falling back to preset {preset}: {error}"
        )
        _synthesize(text, save_path, preset)
        return

    try:
        _synthesize(text, save_path, voice_id)
    finally:
        _delete_voice(voice_id)


if __name__ == "__main__":
    qwen_tts("This is a Qwen Audio TTS test.", "qwen_tts_test.wav", number=1)
