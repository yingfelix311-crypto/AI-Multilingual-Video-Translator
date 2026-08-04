from io import BytesIO
from pathlib import Path
import uuid

import requests
from pydub import AudioSegment

from core.tts_backend.custom_tts import _resolve_clone_source
from core.utils import load_key
from core.utils.config_utils import load_secret


ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"


def _get_api_key():
    api_key = load_secret("elevenlabs_tts.api_key", "ELEVENLABS_API_KEY")
    if not api_key or api_key in ("YOUR_API_KEY", "your_elevenlabs_api_key"):
        raise ValueError(
            "ElevenLabs API key is not set. Put it in ELEVENLABS_API_KEY "
            "or config elevenlabs_tts.api_key."
        )
    return api_key


def _headers():
    return {"xi-api-key": _get_api_key()}


def _raise_api_error(response, action):
    if response.ok:
        return
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    raise RuntimeError(f"ElevenLabs {action} error {response.status_code}: {str(detail)[:500]}")


def _create_clone(number):
    source = _resolve_clone_source(number)
    ref_path = Path(source["path"])
    name = f"videolingo_{number}_{uuid.uuid4().hex[:8]}"

    with open(ref_path, "rb") as audio_file:
        response = requests.post(
            f"{ELEVENLABS_BASE_URL}/voices/add",
            headers=_headers(),
            data={
                "name": name,
                "description": f"Temporary VideoLingo timestamp reference {number}",
                "remove_background_noise": "false",
            },
            files={"files": (ref_path.name, audio_file, "audio/wav")},
            timeout=180,
        )
    _raise_api_error(response, "voice clone")
    voice_id = response.json().get("voice_id")
    if not voice_id:
        raise RuntimeError("ElevenLabs voice clone response did not include voice_id")
    print(f"ElevenLabs temporary voice created for task #{number}")
    return voice_id


def _delete_voice(voice_id):
    try:
        response = requests.delete(
            f"{ELEVENLABS_BASE_URL}/voices/{voice_id}",
            headers=_headers(),
            timeout=60,
        )
        _raise_api_error(response, "voice deletion")
    except Exception as error:
        print(f"Warning: failed to delete ElevenLabs temporary voice {voice_id}: {error}")


def _synthesize(text, save_path, voice_id):
    output_format = load_key("elevenlabs_tts.output_format")
    payload = {
        "text": text,
        "model_id": load_key("elevenlabs_tts.model_id"),
        "voice_settings": {
            "stability": load_key("elevenlabs_tts.stability"),
            "similarity_boost": load_key("elevenlabs_tts.similarity_boost"),
            "style": load_key("elevenlabs_tts.style"),
            "use_speaker_boost": load_key("elevenlabs_tts.use_speaker_boost"),
        },
    }
    response = requests.post(
        f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}",
        params={"output_format": output_format},
        headers={**_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    _raise_api_error(response, "TTS")

    audio = AudioSegment.from_file(BytesIO(response.content), format="mp3")
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(save_path, format="wav")
    print(f"ElevenLabs audio saved to {save_path} (duration: {len(audio) / 1000:.2f}s)")


def elevenlabs_tts(text, save_path, number=None, task_df=None):
    mode = load_key("elevenlabs_tts.mode")
    if mode == "preset":
        voice_id = load_key("elevenlabs_tts.voice_id")
        if not voice_id:
            raise ValueError("ElevenLabs preset mode requires elevenlabs_tts.voice_id")
        _synthesize(text, save_path, voice_id)
        return

    if number is None:
        raise ValueError("ElevenLabs clone mode requires a task number")

    voice_id = _create_clone(number)
    try:
        _synthesize(text, save_path, voice_id)
    finally:
        _delete_voice(voice_id)
