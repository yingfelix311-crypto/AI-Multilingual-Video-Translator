import os
import json
import torch
from pathlib import Path
from rich.console import Console
from rich import print as rprint
from demucs.pretrained import get_model
from demucs.audio import save_audio
from torch.cuda import is_available as is_cuda_available
from typing import Optional
from demucs.api import Separator
from demucs.apply import BagOfModels
import gc
from core.utils.models import *

DEMUCS_MODEL = "htdemucs"
DEMUCS_SHIFTS = 1
DEMUCS_OVERLAP = 0.25
SEPARATION_META_FILE = Path(_AUDIO_DIR) / "separation.json"


def _separation_signature():
    return {
        "model": DEMUCS_MODEL,
        "shifts": DEMUCS_SHIFTS,
        "overlap": DEMUCS_OVERLAP,
        "format": "wav_pcm_s24le",
    }


def _separation_cache_valid():
    if not (
        os.path.exists(_VOCAL_AUDIO_FILE)
        and os.path.exists(_BACKGROUND_AUDIO_FILE)
        and SEPARATION_META_FILE.is_file()
    ):
        return False
    try:
        return json.loads(
            SEPARATION_META_FILE.read_text(encoding="utf-8")
        ) == _separation_signature()
    except (OSError, ValueError):
        return False


class PreloadedSeparator(Separator):
    def __init__(self, model: BagOfModels, shifts: int = 1, overlap: float = 0.25,
                 split: bool = True, segment: Optional[int] = None, jobs: int = 0):
        self._model, self._audio_channels, self._samplerate = model, model.audio_channels, model.samplerate
        device = "cuda" if is_cuda_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.update_parameter(device=device, shifts=shifts, overlap=overlap, split=split,
                            segment=segment, jobs=jobs, progress=True, callback=None, callback_arg=None)

def demucs_audio():
    if _separation_cache_valid():
        rprint(
            f"[yellow]⚠️ Demucs {_separation_signature()} output already exists, "
            "skip processing.[/yellow]"
        )
        return
    
    console = Console()
    os.makedirs(_AUDIO_DIR, exist_ok=True)
    
    console.print(f"🤖 Loading <{DEMUCS_MODEL}> model...")
    model = get_model(DEMUCS_MODEL)
    separator = PreloadedSeparator(
        model=model,
        shifts=DEMUCS_SHIFTS,
        overlap=DEMUCS_OVERLAP,
    )
    
    console.print("🎵 Separating audio...")
    _, outputs = separator.separate_audio_file(_RAW_AUDIO_FILE)
    
    kwargs = {
        "samplerate": model.samplerate,
        "clip": "rescale",
        "as_float": False,
        "bits_per_sample": 24,
    }
    
    console.print("🎤 Saving vocals track...")
    save_audio(outputs['vocals'].cpu(), _VOCAL_AUDIO_FILE, **kwargs)
    
    console.print("🎹 Saving background music...")
    background = sum(audio for source, audio in outputs.items() if source != 'vocals')
    save_audio(background.cpu(), _BACKGROUND_AUDIO_FILE, **kwargs)
    SEPARATION_META_FILE.write_text(
        json.dumps(_separation_signature(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    # Clean up memory
    del outputs, background, model, separator
    gc.collect()
    
    console.print("[green]✨ Audio separation completed![/green]")

if __name__ == "__main__":
    demucs_audio()
