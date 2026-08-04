import os
import ast
import re
import pandas as pd
from pydub import AudioSegment
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from core.utils import *
from core.utils.models import *
console = Console()

DUB_VOCAL_FILE = 'output/dub.wav'

DUB_SUB_FILE = 'output/dub.srt'
OUTPUT_FILE_TEMPLATE = f"{_AUDIO_SEGS_DIR}/{{}}.wav"

def _parse_list(value):
    """Parse list cells, including legacy np.float64(...) wrappers."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() == "nan":
        return None
    normalized = re.sub(r"np\.float64\(([^()]*)\)", r"\1", text)
    return ast.literal_eval(normalized)


def _row_line_count(row):
    lines = _parse_list(row.get("lines"))
    if isinstance(lines, list) and lines:
        return len(lines)
    text = str(row.get("text") or "").strip()
    return 1 if text else 0


def _normalize_sub_times(value, line_count):
    parsed = _parse_list(value)
    if not isinstance(parsed, list) or len(parsed) != line_count:
        return None
    cleaned = []
    for item in parsed:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        cleaned.append([float(item[0]), float(item[1])])
    return cleaned


def _rebuild_sub_times(row, line_count):
    """Rebuild anchored times from start_time + existing seg WAVs."""
    from core._10_gen_audio import parse_df_srt_time
    from core.asr_backend.audio_preprocess import get_audio_duration

    number = int(row["number"])
    cur = parse_df_srt_time(row["start_time"])
    times = []
    for line_index in range(line_count):
        audio_file = OUTPUT_FILE_TEMPLATE.format(f"{number}_{line_index}")
        if not os.path.exists(audio_file):
            raise ValueError(
                f"Task #{number} missing segment audio for merge: {audio_file}"
            )
        duration = float(get_audio_duration(audio_file))
        times.append([cur, cur + duration])
        cur += duration
    return times


def ensure_new_sub_times(df, persist_path=None):
    """Fill missing/invalid new_sub_times so merge never sees NaN floats."""
    repaired = []
    values = []
    for _, row in df.iterrows():
        line_count = _row_line_count(row)
        if line_count < 1:
            raise ValueError(f"Task #{row.get('number')} has no dubbing lines")
        times = _normalize_sub_times(row.get("new_sub_times"), line_count)
        if times is None:
            times = _rebuild_sub_times(row, line_count)
            repaired.append(int(row["number"]))
        values.append(times)

    df = df.copy()
    # Persist as strings so Excel round-trips do not turn blanks into NaN floats.
    df["new_sub_times"] = pd.Series([str(v) for v in values], dtype=object)
    if repaired and persist_path:
        df.to_excel(persist_path, index=False)
        console.print(
            f"[bold yellow]⚠️ Rebuilt missing new_sub_times for tasks: {repaired}[/bold yellow]"
        )
    return df, values


def load_and_flatten_data(excel_file):
    """Load and flatten Excel data"""
    df = pd.read_excel(excel_file)
    df, per_task_times = ensure_new_sub_times(df, persist_path=excel_file)

    lines = []
    for _, row in df.iterrows():
        parsed = _parse_list(row["lines"])
        if not isinstance(parsed, list) or not parsed:
            parsed = [str(row.get("text") or "")]
        lines.extend(parsed)

    new_sub_times = [item for sublist in per_task_times for item in sublist]
    return df, lines, new_sub_times

def get_audio_files(df):
    """Generate a list of audio file paths"""
    audios = []
    for index, row in df.iterrows():
        number = row['number']
        line_count = _row_line_count(row)
        for line_index in range(line_count):
            temp_file = OUTPUT_FILE_TEMPLATE.format(f"{number}_{line_index}")
            audios.append(temp_file)
    return audios

def process_audio_segment(audio_file):
    """Load a segment losslessly and normalize its merge format."""
    return (
        AudioSegment.from_file(audio_file)
        .set_frame_rate(48000)
        .set_channels(1)
    )

def merge_audio_segments(audios, new_sub_times, sample_rate):
    if len(audios) != len(new_sub_times):
        raise ValueError(
            f"Audio/timestamp count mismatch: {len(audios)} != {len(new_sub_times)}"
        )

    segments = []
    timeline_end_ms = 0
    for audio_file, (start_time, _) in zip(audios, new_sub_times):
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"Missing audio segment: {audio_file}")
        audio_segment = process_audio_segment(audio_file)
        start_ms = max(0, round(float(start_time) * 1000))
        segments.append((audio_segment, start_ms))
        timeline_end_ms = max(timeline_end_ms, start_ms + len(audio_segment))

    merged_audio = AudioSegment.silent(
        duration=timeline_end_ms,
        frame_rate=sample_rate,
    ).set_channels(1)
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn()) as progress:
        merge_task = progress.add_task("🎵 Merging audio segments...", total=len(audios))
        
        for audio_segment, start_ms in segments:
            check_cancel()
            merged_audio = merged_audio.overlay(audio_segment, position=start_ms)
            progress.advance(merge_task)
    
    return merged_audio

def create_srt_subtitle():
    df, lines, new_sub_times = load_and_flatten_data(_8_1_AUDIO_TASK)
    
    with open(DUB_SUB_FILE, 'w', encoding='utf-8') as f:
        for i, ((start_time, end_time), line) in enumerate(zip(new_sub_times, lines), 1):
            start_str = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time*1000)%1000):03d}"
            end_str = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time*1000)%1000):03d}"
            
            f.write(f"{i}\n")
            f.write(f"{start_str} --> {end_str}\n")
            f.write(f"{line}\n\n")
    
    rprint(f"[bold green]✅ Subtitle file created: {DUB_SUB_FILE}[/bold green]")

def merge_full_audio():
    """Main function: Process the complete audio merging process"""
    console.print("\n[bold cyan]🎬 Starting audio merging process...[/bold cyan]")
    
    with console.status("[bold cyan]📊 Loading data from Excel...[/bold cyan]"):
        df, lines, new_sub_times = load_and_flatten_data(_8_1_AUDIO_TASK)
    console.print("[bold green]✅ Data loaded successfully[/bold green]")
    
    with console.status("[bold cyan]🔍 Getting audio file list...[/bold cyan]"):
        audios = get_audio_files(df)
    console.print(f"[bold green]✅ Found {len(audios)} audio segments[/bold green]")
    
    with console.status("[bold cyan]📝 Generating subtitle file...[/bold cyan]"):
        create_srt_subtitle()
    
    if not os.path.exists(audios[0]):
        console.print(f"[bold red]❌ Error: First audio file {audios[0]} does not exist![/bold red]")
        return
    
    sample_rate = 48000
    console.print(f"[bold green]✅ Sample rate: {sample_rate}Hz[/bold green]")

    console.print("[bold cyan]🔄 Starting audio merge process...[/bold cyan]")
    merged_audio = merge_audio_segments(audios, new_sub_times, sample_rate)
    
    with console.status("[bold cyan]💾 Exporting final audio file...[/bold cyan]"):
        merged_audio.export(
            DUB_VOCAL_FILE,
            format="wav",
            parameters=["-acodec", "pcm_s24le", "-ar", str(sample_rate)],
        )
    console.print(f"[bold green]✅ Audio file successfully merged![/bold green]")
    console.print(f"[bold green]📁 Output file: {DUB_VOCAL_FILE}[/bold green]")

if __name__ == "__main__":
    merge_full_audio()