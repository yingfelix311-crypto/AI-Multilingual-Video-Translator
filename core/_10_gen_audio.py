import os
import re
import time
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

import pandas as pd
from pydub import AudioSegment
from rich.console import Console
from rich.progress import Progress
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.utils import *
from core.utils.models import *
from core.asr_backend.audio_preprocess import get_audio_duration
from core.tts_backend.tts_main import tts_main

console = Console()

TEMP_FILE_TEMPLATE = f"{_AUDIO_TMP_DIR}/{{}}_temp.wav"
OUTPUT_FILE_TEMPLATE = f"{_AUDIO_SEGS_DIR}/{{}}.wav"
WARMUP_SIZE = 0

def parse_df_srt_time(time_str: str) -> float:
    """Convert SRT time format to seconds"""
    hours, minutes, seconds = time_str.strip().split(':')
    seconds, milliseconds = seconds.split('.')
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000

def adjust_audio_speed(input_file: str, output_file: str, speed_factor: float) -> None:
    """Adjust audio speed and handle edge cases"""
    # If the speed factor is close to 1, directly copy the file
    if abs(speed_factor - 1.0) < 0.001:
        shutil.copy2(input_file, output_file)
        return
        
    atempo = speed_factor
    cmd = ['ffmpeg', '-i', input_file, '-filter:a', f'atempo={atempo}', '-y', output_file]
    input_duration = get_audio_duration(input_file)
    max_retries = 2
    for attempt in range(max_retries):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            output_duration = get_audio_duration(output_file)
            expected_duration = input_duration / speed_factor
            diff = output_duration - expected_duration
            # If the output duration exceeds the expected duration, but the input audio is less than 3 seconds, and the error is within 0.1 seconds, truncate to the expected length
            if output_duration >= expected_duration * 1.02 and input_duration < 3 and diff <= 0.1:
                audio = AudioSegment.from_wav(output_file)
                trimmed_audio = audio[:(expected_duration * 1000)]  # pydub uses milliseconds
                trimmed_audio.export(output_file, format="wav")
                print(f"✂️ Trimmed to expected duration: {expected_duration:.2f} seconds")
                return
            elif output_duration >= expected_duration * 1.02:
                raise Exception(f"Audio duration abnormal: input file={input_file}, output file={output_file}, speed factor={speed_factor}, input duration={input_duration:.2f}s, output duration={output_duration:.2f}s")
            return
        except subprocess.CalledProcessError as e:
            if attempt < max_retries - 1:
                rprint(f"[yellow]⚠️ Audio speed adjustment failed, retrying in 1s ({attempt + 1}/{max_retries})[/yellow]")
                time.sleep(1)
            else:
                rprint(f"[red]❌ Audio speed adjustment failed, max retries reached ({max_retries})[/red]")
                raise e

def process_row(row: pd.Series, tasks_df: pd.DataFrame) -> Tuple[int, float]:
    """Helper function for processing single row data"""
    number = row['number']
    lines = eval(row['lines']) if isinstance(row['lines'], str) else row['lines']
    real_dur = 0
    for line_index, line in enumerate(lines):
        temp_file = TEMP_FILE_TEMPLATE.format(f"{number}_{line_index}")
        tts_main(line, temp_file, number, tasks_df)
        real_dur += get_audio_duration(temp_file)
    return number, real_dur

def generate_tts_audio(tasks_df: pd.DataFrame) -> pd.DataFrame:
    """Generate TTS audio sequentially and calculate actual duration"""
    tasks_df['real_dur'] = 0
    rprint("[bold green]🎯 Starting TTS audio generation...[/bold green]")
    
    with Progress() as progress:
        task = progress.add_task("[cyan]🔄 Generating TTS audio...", total=len(tasks_df))
        
        # warm up for first 5 rows
        warmup_size = min(WARMUP_SIZE, len(tasks_df))
        for _, row in tasks_df.head(warmup_size).iterrows():
            try:
                check_cancel()
                number, real_dur = process_row(row, tasks_df)
                tasks_df.loc[tasks_df['number'] == number, 'real_dur'] = real_dur
                progress.advance(task)
            except Exception as e:
                rprint(f"[red]❌ Error in warmup: {str(e)}[/red]")
                raise e
        
        # GPT-SoVITS is local and stateful. Noiz custom_tts supports bounded concurrency.
        tts_method = load_key("tts_method")
        if tts_method == "gpt_sovits":
            max_workers = 1
        elif tts_method == "custom_tts":
            max_workers = load_key("noiz_tts.max_workers")
        elif tts_method == "elevenlabs_tts":
            max_workers = load_key("elevenlabs_tts.max_workers")
        else:
            max_workers = load_key("max_workers")
        # parallel processing for remaining tasks
        if len(tasks_df) > warmup_size:
            remaining_tasks = tasks_df.iloc[warmup_size:].copy()
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(process_row, row, tasks_df.copy())
                    for _, row in remaining_tasks.iterrows()
                ]
                
                try:
                    for future in as_completed(futures):
                        check_cancel()
                        try:
                            number, real_dur = future.result()
                            tasks_df.loc[tasks_df['number'] == number, 'real_dur'] = real_dur
                            progress.advance(task)
                        except Exception as e:
                            rprint(f"[red]❌ Error: {str(e)}[/red]")
                            raise e
                except BaseException:
                    for f in futures:
                        f.cancel()
                    raise

    rprint("[bold green]✨ TTS audio generation completed![/bold green]")
    return tasks_df

def process_chunk(chunk_df: pd.DataFrame, accept: float, min_speed: float) -> tuple[float, bool]:
    """Process audio chunk and calculate speed factor"""
    chunk_durs = chunk_df['real_dur'].sum()
    tol_durs = chunk_df['tol_dur'].sum()
    durations = tol_durs - chunk_df.iloc[-1]['tolerance']
    all_gaps = chunk_df['gap'].sum() - chunk_df.iloc[-1]['gap']
    
    keep_gaps = True
    speed_var_error = 0.1

    if (chunk_durs + all_gaps) / accept < durations:
        speed_factor = max(min_speed, (chunk_durs + all_gaps) / (durations-speed_var_error))
    elif chunk_durs / accept < durations:
        speed_factor = max(min_speed, chunk_durs / (durations-speed_var_error))
        keep_gaps = False
    elif (chunk_durs + all_gaps) / accept < tol_durs:
        speed_factor = max(min_speed, (chunk_durs + all_gaps) / (tol_durs-speed_var_error))
    else:
        speed_factor = chunk_durs / (tol_durs-speed_var_error)
        keep_gaps = False
        
    return round(speed_factor, 3), keep_gaps

def _task_window(tasks_df, index, row):
    start = parse_df_srt_time(row["start_time"])
    end = parse_df_srt_time(row["end_time"])
    tolerance = max(0.0, float(row.get("tolerance", 0) or 0))
    window_end = end + tolerance
    if index < len(tasks_df) - 1:
        next_start = parse_df_srt_time(tasks_df.iloc[index + 1]["start_time"])
        window_end = min(window_end, next_start)
    return start, window_end


MAX_SHORTEN_ROUNDS = 1


def measure_temp_duration(temp_dir, number, line_count):
    real_dur = 0.0
    for line_index in range(line_count):
        temp_file = os.path.join(temp_dir, f"{number}_{line_index}_temp.wav")
        real_dur += get_audio_duration(temp_file)
    return max(0.001, real_dur)


def fit_task_to_window(tasks_df, index, row, temp_dir, seg_dir, number=None, write_segs=True):
    """Fit one task's temp WAV files into its anchored subtitle window.

    Never trims speech. Speed is capped at ``speed_factor.max``; if audio still
    overflows the window, segments are written anyway (forced merge).
    """
    number = int(row["number"] if number is None else number)
    start, window_end = _task_window(tasks_df, index, row)
    available = max(0.1, window_end - start)
    max_speed = float(load_key("speed_factor.max"))
    lines = eval(row["lines"]) if isinstance(row["lines"], str) else row["lines"]
    line_count = len(lines)
    real_dur = measure_temp_duration(temp_dir, number, line_count)

    usable = max(0.1, available - 0.05)
    required_speed = real_dur / usable
    fits = required_speed <= max_speed + 1e-6
    speed_factor = min(max_speed, max(1.0, required_speed))
    overflow = max(0.0, real_dur / max_speed - usable) if not fits else 0.0
    new_sub_times = []

    if write_segs:
        os.makedirs(seg_dir, exist_ok=True)
        cur_time = start
        for line_index in range(line_count):
            temp_file = os.path.join(temp_dir, f"{number}_{line_index}_temp.wav")
            output_file = os.path.join(seg_dir, f"{number}_{line_index}.wav")
            adjust_audio_speed(temp_file, output_file, speed_factor)
            ad_dur = get_audio_duration(output_file)
            new_sub_times.append([cur_time, cur_time + ad_dur])
            cur_time += ad_dur

    status = "fitted" if fits else "forced_merge"
    if not fits:
        rprint(
            f"[yellow]Task #{number} exceeds its window by {overflow:.3f}s "
            f"even at max speed {max_speed:.2f}x; forcing merge without trim[/yellow]"
        )

    rprint(
        f"[cyan]Task #{number} anchored at {start:.3f}s, "
        f"window={available:.3f}s, required={required_speed:.3f}x, "
        f"speed={speed_factor:.3f}, status={status}[/cyan]"
    )

    return {
        "number": number,
        "real_dur": real_dur,
        "new_sub_times": new_sub_times,
        "speed_factor": speed_factor,
        "required_speed": required_speed,
        "available": available,
        "max_speed": max_speed,
        "fits": fits,
        "overflow": overflow,
        "line_count": line_count,
        "status": status,
    }


def merge_chunks(tasks_df: pd.DataFrame) -> pd.DataFrame:
    """Fit every TTS task into its own anchored subtitle window.

    The previous chunk scheduler packed short TTS output toward the start of a
    chunk. A long merged task could therefore pull every following task several
    seconds earlier. Each row now starts at its original ``start_time``; unused
    room becomes silence and can never move the next task. Tasks that still
    overflow after max speed are force-merged (may overlap the next gap).
    """
    rprint("[bold blue]🔄 Anchoring TTS audio to original subtitle timestamps...[/bold blue]")
    # Object dtype is required: assigning nested lists via .at into a missing/
    # numeric column raises "Must have equal len keys and value...".
    tasks_df["new_sub_times"] = pd.Series([None] * len(tasks_df), dtype=object)
    overflows = []

    for index, row in tasks_df.iterrows():
        check_cancel()
        number = int(row["number"])
        result = fit_task_to_window(
            tasks_df, index, row, _AUDIO_TMP_DIR, _AUDIO_SEGS_DIR, number=number
        )
        tasks_df.at[index, "real_dur"] = result["real_dur"]
        # Store as string so Excel round-trips keep every row (None/NaN breaks merge).
        tasks_df.at[index, "new_sub_times"] = str(result["new_sub_times"])
        if not result["fits"]:
            overflows.append(number)

    if overflows:
        rprint(
            f"[bold yellow]⚠️ Forced merge for tasks exceeding max speed window: "
            f"{overflows}[/bold yellow]"
        )

    rprint("[bold green]✅ Timestamp-anchored audio processing completed![/bold green]")
    return tasks_df


def _parse_source_numbers(row):
    source = row.get("source_numbers")
    if isinstance(source, str):
        try:
            source = eval(source)
        except Exception:
            source = [row["number"]]
    if not isinstance(source, (list, tuple)) or not source:
        source = [row["number"]]
    return [int(n) for n in source]


def _task_cue_payload(row, available):
    """Build per-cue shorten inputs from the current translated SRT."""
    from webui.workspace import SRC_SRT, TRANS_SRT, parse_srt

    source_numbers = _parse_source_numbers(row)
    trans_by_cue = {cue["cue"]: cue for cue in parse_srt(TRANS_SRT)}
    src_by_cue = {cue["cue"]: cue["text"] for cue in parse_srt(SRC_SRT)}
    missing = [n for n in source_numbers if n not in trans_by_cue]
    if missing:
        raise ValueError(f"Task cues missing from translated SRT: {missing}")

    task_text = " ".join(str(row.get("text") or "").split()).strip()
    srt_task_text = " ".join(trans_by_cue[n]["text"] for n in source_numbers)
    srt_task_text = re.sub(r"\([^)]*\)|（[^）]*）", "", srt_task_text)
    srt_task_text = " ".join(srt_task_text.replace("-", "").split()).strip()
    manual_flag = row.get("manual_text_override", False)
    manual_override = (
        manual_flag is True
        or str(manual_flag).strip().lower() == "true"
        or task_text != srt_task_text
    )
    if manual_override:
        return [{
            "cue": int(row["number"]),
            "text": task_text,
            "origin": str(row.get("origin") or ""),
            "budget": round(available, 3),
            "writeback": False,
        }]

    cues = []
    total_budget = 0.0
    for number in source_numbers:
        cue = trans_by_cue[number]
        start = parse_df_srt_time(cue["start"].replace(",", "."))
        end = parse_df_srt_time(cue["end"].replace(",", "."))
        budget = max(0.05, end - start)
        total_budget += budget
        cues.append({
            "cue": number,
            "text": cue["text"],
            "origin": src_by_cue.get(number, ""),
            "budget": budget,
            "writeback": True,
        })

    if total_budget > 0:
        scale = available / total_budget
        for cue in cues:
            cue["budget"] = round(cue["budget"] * scale, 3)
    return cues


def _validate_shortened_cues(previous, response):
    if not isinstance(response, dict) or not isinstance(response.get("cues"), list):
        raise ValueError("LLM shorten response missing cues list")
    previous_by_cue = {item["cue"]: item for item in previous}
    expected = [item["cue"] for item in previous]
    actual = []
    cleaned = []
    for raw in response["cues"]:
        if not isinstance(raw, dict):
            raise ValueError("Each shortened cue must be an object")
        cue = int(raw["cue"])
        text = " ".join(str(raw.get("text") or "").split()).strip()
        if not text:
            raise ValueError(f"Shortened cue {cue} is empty")
        prior = previous_by_cue.get(cue)
        if prior is None:
            raise ValueError(f"Unexpected shortened cue id: {cue}")
        if len(text) > len(prior["text"]):
            raise ValueError(f"Shortened cue {cue} is longer than previous text")
        actual.append(cue)
        cleaned.append({
            "cue": cue,
            "text": text,
            "origin": prior.get("origin", ""),
            "budget": prior.get("budget", 0),
            "writeback": prior.get("writeback", True),
        })
    if actual != expected:
        raise ValueError(f"Shortened cue ids mismatch: expected {expected}, got {actual}")
    if [item["text"] for item in cleaned] == [item["text"] for item in previous]:
        raise ValueError("LLM did not shorten any cue")
    return cleaned


def shorten_task_cues(cues, available, real_dur, max_speed, round_index):
    from core.prompts import get_cue_shorten_prompt

    prompt = get_cue_shorten_prompt(
        cues, available, real_dur, max_speed, round_index, MAX_SHORTEN_ROUNDS
    )

    def valid_shorten(response):
        try:
            _validate_shortened_cues(cues, response)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        return {"status": "success", "message": ""}

    response = ask_gpt(prompt, resp_type="json", log_title="cue_shorten", valid_def=valid_shorten)
    return _validate_shortened_cues(cues, response)


def _lines_from_cues(row, cues):
    texts = [item["text"] for item in cues]
    if "speaker" in row and pd.notna(row.get("speaker")):
        return [" ".join(texts)]
    return texts


def generate_task_candidate(task_number, candidate_id=None, force_shorten=False):
    """Generate a non-destructive candidate for one task.

    Writes temp audio under ``regeneration_candidates/<number>/``. When the
    spoken audio exceeds the max-speed window, LLM-shortens cues at most once
    and regenerates. If it still overflows, segments are force-written at max
    speed (no speech trim).
    """
    import json

    number = int(task_number)
    tasks_df = pd.read_excel(_8_1_AUDIO_TASK)
    matches = tasks_df.index[tasks_df["number"] == number].tolist()
    if not matches:
        raise ValueError(f"Unknown task number: {number}")
    index = matches[0]
    row = tasks_df.loc[index].copy()

    task_root = Path(_AUDIO_CANDIDATES_DIR) / str(number)
    candidate_id = str(candidate_id).strip() if candidate_id is not None else None
    candidate_root = task_root / candidate_id if candidate_id else task_root
    temp_dir = candidate_root / "tmp"
    seg_dir = candidate_root / "segs"
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    temp_dir.mkdir(parents=True)
    seg_dir.mkdir(parents=True)

    start, window_end = _task_window(tasks_df, index, row)
    available = max(0.1, window_end - start)
    original_cues = _task_cue_payload(row, available)
    current_cues = [dict(item) for item in original_cues]
    lines = _lines_from_cues(row, current_cues)
    row["lines"] = lines
    row["text"] = " ".join(item["text"] for item in current_cues)

    rprint(f"[bold magenta]♻️ Generating candidate for task #{number}[/bold magenta]")
    fit = None
    rounds_used = 0
    for round_index in range(MAX_SHORTEN_ROUNDS + 1):
        check_cancel()
        for path in temp_dir.glob(f"{number}_*_temp.wav"):
            path.unlink(missing_ok=True)
        for path in seg_dir.glob(f"{number}_*.wav"):
            path.unlink(missing_ok=True)

        for line_index, line in enumerate(lines):
            check_cancel()
            temp_file = str(temp_dir / f"{number}_{line_index}_temp.wav")
            tts_main(line, temp_file, number, tasks_df)

        fit = fit_task_to_window(
            tasks_df, index, row, str(temp_dir), str(seg_dir), number=number, write_segs=True
        )
        force_this_round = bool(force_shorten) and round_index == 0
        if fit["fits"] and not force_this_round:
            break
        if round_index >= MAX_SHORTEN_ROUNDS:
            break

        rounds_used = round_index + 1
        rprint(
            f"[yellow]Task #{number} shorten round {rounds_used}/{MAX_SHORTEN_ROUNDS}[/yellow]"
        )
        current_cues = shorten_task_cues(
            current_cues,
            fit["available"],
            fit["real_dur"],
            fit["max_speed"],
            rounds_used,
        )
        lines = _lines_from_cues(row, current_cues)
        row["lines"] = lines
        row["text"] = " ".join(item["text"] for item in current_cues)

    text_changed = [item["text"] for item in current_cues] != [item["text"] for item in original_cues]
    manifest = {
        "number": number,
        "candidate_id": candidate_id,
        "force_shorten": bool(force_shorten),
        "line_count": fit["line_count"],
        "real_dur": round(float(fit["real_dur"]), 3),
        "available": round(float(fit["available"]), 3),
        "required_speed": round(float(fit["required_speed"]), 3),
        "speed_factor": round(float(fit["speed_factor"]), 3),
        "new_sub_times": fit["new_sub_times"],
        "fits": bool(fit["fits"]),
        "status": fit["status"],
        "overflow": round(float(fit["overflow"]), 3),
        "shorten_rounds": rounds_used,
        "text_changed": text_changed,
        "original_text": " ".join(item["text"] for item in original_cues),
        "candidate_text": " ".join(item["text"] for item in current_cues),
        "original_cues": original_cues,
        "candidate_cues": current_cues,
        "writeback_subtitles": all(
            item.get("writeback", True) for item in current_cues
        ),
        "source_numbers": _parse_source_numbers(row),
        "created_at": time.time(),
        "failure_reason": None if fit["fits"] else (
            f"After {rounds_used} shorten round(s), audio still exceeds the "
            f"{fit['max_speed']:.2f}x window by {fit['overflow']:.3f}s; "
            f"forced merge at max speed"
        ),
    }
    (candidate_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if fit["fits"]:
        rprint(f"[bold green]Candidate ready for task #{number}[/bold green]")
    else:
        rprint(
            f"[bold yellow]Candidate for task #{number} force-merged "
            f"(still over window)[/bold yellow]"
        )
    return manifest

def _clear_task_temps(tasks_df, numbers=None):
    """Delete temp TTS files for the given task numbers (or all tasks)."""
    target = set(int(n) for n in numbers) if numbers is not None else None
    cleared = 0
    for _, row in tasks_df.iterrows():
        number = int(row["number"])
        if target is not None and number not in target:
            continue
        lines = eval(row["lines"]) if isinstance(row["lines"], str) else row["lines"]
        for line_index in range(len(lines)):
            temp_file = TEMP_FILE_TEMPLATE.format(f"{number}_{line_index}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
                cleared += 1
    return cleared


def regenerate_tasks(task_numbers):
    """Regenerate TTS for selected tasks, then rebuild the full timeline.

    Selected temps are force-cleared. Any other tasks that already lost their
    cache (e.g. after a speaker rebuild) are filled back in too — ``tts_main``
    skips existing files, so untouched caches never hit the TTS API.
    """
    numbers = sorted({int(n) for n in task_numbers})
    if not numbers:
        raise ValueError("No task numbers provided for regeneration")

    rprint(f"[bold magenta]♻️ Regenerating TTS for tasks: {numbers}[/bold magenta]")
    os.makedirs(_AUDIO_TMP_DIR, exist_ok=True)
    os.makedirs(_AUDIO_SEGS_DIR, exist_ok=True)

    tasks_df = pd.read_excel(_8_1_AUDIO_TASK)
    available = set(int(n) for n in tasks_df["number"].tolist())
    missing = [n for n in numbers if n not in available]
    if missing:
        raise ValueError(f"Unknown task numbers: {missing}")

    cleared = _clear_task_temps(tasks_df, numbers)
    rprint(f"[yellow]Cleared {cleared} cached TTS files for selected tasks[/yellow]")

    # generate_tts_audio only calls the API when a temp file is missing.
    tasks_df = generate_tts_audio(tasks_df)
    tasks_df = merge_chunks(tasks_df)
    tasks_df.to_excel(_8_1_AUDIO_TASK, index=False)
    rprint(f"[bold green]Selected TTS regeneration complete ({len(numbers)} forced)[/bold green]")
    return {"regenerated": numbers}


def gen_audio(force=False):
    """Main function: Generate audio and process timeline"""
    rprint("[bold magenta]🚀 Starting audio generation process...[/bold magenta]")
    
    # 🎯 Step1: Create necessary directories
    os.makedirs(_AUDIO_TMP_DIR, exist_ok=True)
    os.makedirs(_AUDIO_SEGS_DIR, exist_ok=True)
    
    # 📝 Step2: Load task file
    tasks_df = pd.read_excel(_8_1_AUDIO_TASK)
    rprint("[green]📊 Loaded task file successfully[/green]")

    if force:
        cleared = _clear_task_temps(tasks_df)
        rprint(f"[yellow]♻️ Existing TTS cache cleared for forced regeneration ({cleared} files)[/yellow]")
    
    # 🔊 Step3: Generate TTS audio
    tasks_df = generate_tts_audio(tasks_df)
    
    # 🔄 Step4: Merge audio chunks
    tasks_df = merge_chunks(tasks_df)
    
    # 💾 Step5: Save results
    tasks_df.to_excel(_8_1_AUDIO_TASK, index=False)
    rprint("[bold green]🎉 Audio generation completed successfully![/bold green]")

if __name__ == "__main__":
    gen_audio()
