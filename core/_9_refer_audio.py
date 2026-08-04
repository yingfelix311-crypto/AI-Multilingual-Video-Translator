import ast
import os
from rich.panel import Panel
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from core.utils import *
from core.utils.models import *
import pandas as pd
import soundfile as sf
import numpy as np
console = Console()
from core.asr_backend.demucs_vl import demucs_audio
from core.utils.models import *

SRC_SUBS_FOR_AUDIO_FILE = "output/audio/src_subs_for_audio.srt"

def time_to_samples(time_str, sr):
    """Unified time conversion function"""
    h, m, s = time_str.split(':')
    s, ms = s.split(',') if ',' in s else (s, '0')
    seconds = int(h) * 3600 + int(m) * 60 + float(s) + float(ms) / 1000
    return int(seconds * sr)

def extract_audio(audio_data, sr, start_time, end_time, out_file):
    """Simplified audio extraction function"""
    start = time_to_samples(start_time, sr)
    end = time_to_samples(end_time, sr)
    sf.write(out_file, audio_data[start:end], sr)


def _reference_groups(df):
    """Group adjacent cues only for reference-audio pooling."""
    groups = []
    current = []
    for _, row in df.iterrows():
        merge = bool(row.get("reference_merge_with_previous", False))
        if current and merge:
            current.append(row)
        else:
            if current:
                groups.append(current)
            current = [row]
    if current:
        groups.append(current)
    return groups


def _source_numbers(row):
    value = row.get("source_numbers")
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            value = None
    if isinstance(value, (list, tuple)):
        return [int(number) for number in value]
    return [int(row["number"])]


def _source_segments():
    segments = {}
    with open(SRC_SUBS_FOR_AUDIO_FILE, "r", encoding="utf-8") as file:
        content = file.read()
    for block in content.strip().split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        number = int(lines[0])
        start_time, end_time = lines[1].split(" --> ")
        segments[number] = (start_time, end_time)
    return segments


def extract_refer_audio_main():
    demucs_audio() #!!! in case demucs not run

    # Create output directory
    os.makedirs(_AUDIO_REFERS_DIR, exist_ok=True)
    
    # Read task file and audio data
    df = pd.read_excel(_8_1_AUDIO_TASK)
    data, sr = sf.read(_VOCAL_AUDIO_FILE)
    source_segments = _source_segments()
    for filename in os.listdir(_AUDIO_REFERS_DIR):
        stem, extension = os.path.splitext(filename)
        if extension.lower() == ".wav" and stem.isdigit():
            os.remove(os.path.join(_AUDIO_REFERS_DIR, filename))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Extracting audio segments...", total=len(df))

        for group in _reference_groups(df):
            clips = []
            for row in group:
                for source_number in _source_numbers(row):
                    start_time, end_time = source_segments[source_number]
                    start = time_to_samples(start_time, sr)
                    end = time_to_samples(end_time, sr)
                    clips.append(data[start:end])
            pooled = np.concatenate(clips, axis=0)
            numbers = [int(row["number"]) for row in group]
            for number in numbers:
                out_file = os.path.join(_AUDIO_REFERS_DIR, f"{number}.wav")
                sf.write(out_file, pooled, sr)
                progress.update(task, advance=1)
            if len(numbers) > 1:
                rprint(
                    f"[green]Pooled reference audio for TTS tasks {numbers}[/green]"
                )
            
    rprint(Panel(f"Audio segments saved to {_AUDIO_REFERS_DIR}", title="Success", border_style="green"))

if __name__ == "__main__":
    extract_refer_audio_main()