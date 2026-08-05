import datetime
import re
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from core.prompts import get_subtitle_trim_prompt
from core.tts_backend.estimate_duration import init_estimator, estimate_duration
from core.speaker_tagging import load_speaker_tags, tag_srt_speakers
from core.utils import *
from core.utils.models import *

console = Console()
speed_factor = load_key("speed_factor")

TRANS_SUBS_FOR_AUDIO_FILE = 'output/audio/trans_subs_for_audio.srt'
SRC_SUBS_FOR_AUDIO_FILE = 'output/audio/src_subs_for_audio.srt'
ESTIMATOR = None

def check_len_then_trim(text, duration):
    global ESTIMATOR
    if ESTIMATOR is None:
        ESTIMATOR = init_estimator()
    estimated_duration = estimate_duration(text, ESTIMATOR) / speed_factor['max']
    
    console.print(f"Subtitle text: {text}, "
                  f"[bold green]Estimated reading duration: {estimated_duration:.2f} seconds[/bold green]")

    if estimated_duration > duration:
        rprint(Panel(f"Estimated reading duration {estimated_duration:.2f} seconds exceeds given duration {duration:.2f} seconds, shortening...", title="Processing", border_style="yellow"))
        original_text = text
        prompt = get_subtitle_trim_prompt(text, duration)
        def valid_trim(response):
            if 'result' not in response:
                return {'status': 'error', 'message': 'No result in response'}
            return {'status': 'success', 'message': ''}
        try:    
            response = ask_gpt(prompt, resp_type='json', log_title='sub_trim', valid_def=valid_trim)
            shortened_text = response['result']
        except Exception:
            rprint("[bold red]🚫 AI refused to answer due to sensitivity, so manually remove punctuation[/bold red]")
            shortened_text = re.sub(r'[,.!?;:，。！？；：]', ' ', text).strip()
        rprint(Panel(f"Subtitle before shortening: {original_text}\nSubtitle after shortening: {shortened_text}", title="Subtitle Shortening Result", border_style="green"))
        return shortened_text
    else:
        return text

def time_diff_seconds(t1, t2, base_date):
    """Calculate the difference in seconds between two time objects"""
    dt1 = datetime.datetime.combine(base_date, t1)
    dt2 = datetime.datetime.combine(base_date, t2)
    return (dt2 - dt1).total_seconds()

def _speaker_tagging_enabled():
    try:
        return bool(load_key("speaker_tagging.enabled"))
    except KeyError:
        return False


def _gap_from_keys(*keys, default=1.0):
    for key in keys:
        try:
            return float(load_key(key))
        except KeyError:
            continue
    return float(default)


def _refer_merge_max_gap():
    """Max silence (seconds) to pool clone reference audio with previous cue."""
    return _gap_from_keys(
        "speaker_tagging.refer_merge_max_gap",
        "speaker_tagging.tts_merge_max_gap",
        "speaker_tagging.max_gap",
        default=1.0,
    )


def _tts_merge_max_gap():
    """Max silence (seconds) to concatenate TTS text with previous cue. 0 = never."""
    return _gap_from_keys(
        "speaker_tagging.tts_merge_max_gap",
        "speaker_tagging.max_gap",
        default=0.0,
    )


def _same_speaker(left, right):
    """Both sides must have a non-empty identical speaker label."""
    a = str((left or {}).get("speaker") or "").strip()
    b = str((right or {}).get("speaker") or "").strip()
    if not a or not b:
        return False
    if a.lower() in {"nan", "none"} or b.lower() in {"nan", "none"}:
        return False
    return a == b


def _decide_merge_with_previous(previous, row, max_gap, min_confidence, today):
    """Same-speaker merge decision for one gap threshold. Different roles never merge."""
    if not previous:
        return False
    if bool(row.get("force_unmerge")):
        return False
    if not _same_speaker(previous, row):
        return False
    gap = time_diff_seconds(previous["end_time"], row["start_time"], today)
    if not (-0.5 <= gap <= max_gap):
        return False
    if row.get("manual_override") or previous.get("manual_override"):
        return True
    return (
        float(row.get("speaker_confidence") or 0) >= min_confidence
        and float(previous.get("speaker_confidence") or 0) >= min_confidence
    )


def _annotate_speaker_cues(df, tags):
    """Attach speaker metadata; resolve refer merge and TTS-text merge separately."""
    min_confidence = float(load_key("speaker_tagging.min_confidence"))
    refer_gap = _refer_merge_max_gap()
    tts_gap = _tts_merge_max_gap()
    today = datetime.date.today()
    rows = []

    for row in df.to_dict("records"):
        tag = tags.get(row["number"], {})
        row["speaker"] = tag.get("speaker", f"unknown_{row['number']}")
        row["speaker_confidence"] = float(tag.get("confidence", 0))
        row["force_unmerge"] = bool(tag.get("force_unmerge", False))
        row["manual_override"] = bool(tag.get("manual_override", False))
        row["source_numbers"] = [row["number"]]

        previous = rows[-1] if rows else None
        refer_merge = _decide_merge_with_previous(
            previous, row, refer_gap, min_confidence, today
        )
        tts_merge = _decide_merge_with_previous(
            previous, row, tts_gap, min_confidence, today
        )
        # UI / speaker-tag field tracks reference pooling intent.
        row["merge_with_previous"] = refer_merge
        row["reference_merge_with_previous"] = refer_merge
        row["tts_merge_with_previous"] = tts_merge
        if refer_merge or tts_merge:
            parts = []
            if refer_merge:
                parts.append(f"refer<={refer_gap:.2f}s")
            if tts_merge:
                parts.append(f"tts-text<={tts_gap:.2f}s")
            rprint(
                f"[green]Merge cue {previous['number']} + {row['number']} "
                f"({row['speaker']}, {', '.join(parts)})[/green]"
            )
        rows.append(row)

    return pd.DataFrame(rows)


def _merge_tts_by_speaker_gap(df):
    """Concatenate TTS text only when same speaker and ``tts_merge_with_previous``.

    Reference pooling stays on ``reference_merge_with_previous`` in ``_9_refer_audio``.
    """
    today = datetime.date.today()
    grouped = []

    for row in df.to_dict("records"):
        previous = grouped[-1] if grouped else None
        should_merge = (
            previous is not None
            and bool(row.get("tts_merge_with_previous"))
            and _same_speaker(previous, row)
        )
        if should_merge:
            gap = time_diff_seconds(previous["end_time"], row["start_time"], today)
            previous["text"] += " " + row["text"]
            previous["origin"] += " " + row["origin"]
            previous["end_time"] = row["end_time"]
            previous["duration"] = time_diff_seconds(
                previous["start_time"],
                previous["end_time"],
                today,
            )
            previous["source_numbers"].extend(row["source_numbers"])
            previous["tts_merge_count"] = len(previous["source_numbers"])
            rprint(
                f"[green]Merging TTS text "
                f"{previous['source_numbers']} ({previous['speaker']}, gap={gap:.3f}s)[/green]"
            )
        else:
            row = dict(row)
            row["source_numbers"] = [int(row["number"])]
            row["tts_merge_count"] = 1
            grouped.append(row)

    return pd.DataFrame(grouped)


def process_srt():
    """Process srt file, generate audio tasks"""
    
    with open(TRANS_SUBS_FOR_AUDIO_FILE, 'r', encoding='utf-8') as file:
        content = file.read()
    
    with open(SRC_SUBS_FOR_AUDIO_FILE, 'r', encoding='utf-8') as src_file:
        src_content = src_file.read()
    
    subtitles = []
    src_subtitles = {}
    
    for block in src_content.strip().split('\n\n'):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue
        
        number = int(lines[0])
        src_text = ' '.join(lines[2:])
        src_subtitles[number] = src_text
    
    for block in content.strip().split('\n\n'):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue
        
        try:
            number = int(lines[0])
            start_time, end_time = lines[1].split(' --> ')
            start_time = datetime.datetime.strptime(start_time, '%H:%M:%S,%f').time()
            end_time = datetime.datetime.strptime(end_time, '%H:%M:%S,%f').time()
            duration = time_diff_seconds(start_time, end_time, datetime.date.today())
            text = ' '.join(lines[2:])
            # Remove content within parentheses (including English and Chinese parentheses)
            text = re.sub(r'\([^)]*\)', '', text).strip()
            text = re.sub(r'（[^）]*）', '', text).strip()
            # Remove '-' character, can continue to add illegal characters that cause errors
            text = text.replace('-', '')

            # Add the original text from src_subs_for_audio.srt
            origin = src_subtitles.get(number, '')

        except ValueError as e:
            rprint(Panel(f"Unable to parse subtitle block '{block}', error: {str(e)}, skipping this subtitle block.", title="Error", border_style="red"))
            continue
        
        subtitles.append({'number': number, 'start_time': start_time, 'end_time': end_time, 'duration': duration, 'text': text, 'origin': origin})
    
    df = pd.DataFrame(subtitles)
    
    tags = load_speaker_tags()
    if not tags and _speaker_tagging_enabled():
        tags = tag_srt_speakers()

    if tags:
        df = _annotate_speaker_cues(df, tags)
        df = _merge_tts_by_speaker_gap(df)
    else:
        i = 0
        MIN_SUB_DUR = load_key("min_subtitle_duration")
        while i < len(df):
            today = datetime.date.today()
            if df.loc[i, 'duration'] < MIN_SUB_DUR:
                if i < len(df) - 1 and time_diff_seconds(df.loc[i, 'start_time'],df.loc[i+1, 'start_time'],today) < MIN_SUB_DUR:
                    rprint(f"[bold yellow]Merging subtitles {i+1} and {i+2}[/bold yellow]")
                    df.loc[i, 'text'] += ' ' + df.loc[i+1, 'text']
                    df.loc[i, 'origin'] += ' ' + df.loc[i+1, 'origin']
                    df.loc[i, 'end_time'] = df.loc[i+1, 'end_time']
                    df.loc[i, 'duration'] = time_diff_seconds(df.loc[i, 'start_time'],df.loc[i, 'end_time'],today)
                    df = df.drop(i+1).reset_index(drop=True)
                else:
                    if i < len(df) - 1:  # Not the last audio
                        rprint(f"[bold blue]Extending subtitle {i+1} duration to {MIN_SUB_DUR} seconds[/bold blue]")
                        df.loc[i, 'end_time'] = (datetime.datetime.combine(today, df.loc[i, 'start_time']) +
                                                datetime.timedelta(seconds=MIN_SUB_DUR)).time()
                        df.loc[i, 'duration'] = MIN_SUB_DUR
                    else:
                        rprint(f"[bold red]The last subtitle {i+1} duration is less than {MIN_SUB_DUR} seconds, but not extending[/bold red]")
                    i += 1
            else:
                i += 1
    
    df['start_time'] = df['start_time'].apply(lambda x: x.strftime('%H:%M:%S.%f')[:-3])
    df['end_time'] = df['end_time'].apply(lambda x: x.strftime('%H:%M:%S.%f')[:-3])

    ##! No longer perform secondary trim
    # check and trim subtitle length, for twice to ensure the subtitle length is within the limit, 允许tolerance
    # df['text'] = df.apply(lambda x: check_len_then_trim(x['text'], x['duration']+x['tolerance']), axis=1)

    return df

@check_file_exists(_8_1_AUDIO_TASK)
def gen_audio_task_main():
    df = process_srt()
    console.print(df)
    df.to_excel(_8_1_AUDIO_TASK, index=False)
    rprint(Panel(f"Successfully generated {_8_1_AUDIO_TASK}", title="Success", border_style="green"))

if __name__ == '__main__':
    gen_audio_task_main()