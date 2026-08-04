import platform
import json
import re
import subprocess
from pathlib import Path

import cv2
from rich.console import Console

from core._1_ytdlp import find_video_files
from core.utils import *
from core.utils.models import *

console = Console()

DUB_VIDEO = "output/output_dub.mp4"
DUB_SUB_FILE = 'output/dub.srt'
DUB_AUDIO = 'output/dub.wav'
SRC_SUBS_FOR_AUDIO_FILE = 'output/audio/src_subs_for_audio.srt'
TRANS_SUBS_FOR_AUDIO_FILE = 'output/audio/trans_subs_for_audio.srt'

TRANS_FONT_SIZE = 17
TRANS_FONT_NAME = 'Arial'
if platform.system() == 'Linux':
    TRANS_FONT_NAME = 'NotoSansCJK-Regular'
if platform.system() == 'Darwin':
    TRANS_FONT_NAME = 'Arial Unicode MS'

TRANS_FONT_COLOR = '&H00FFFF'
TRANS_OUTLINE_COLOR = '&H000000'
TRANS_OUTLINE_WIDTH = 1 
TRANS_BACK_COLOR = '&H33000000'

def _load_original_audio_intervals():
    intervals = []
    try:
        configured = load_key("audio_mastering.original_audio_intervals")
    except KeyError:
        return intervals

    for item in configured or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"Invalid original audio interval: {item}")
        start, end = float(item[0]), float(item[1])
        if start < 0 or end <= start:
            raise ValueError(f"Invalid original audio interval: {item}")
        intervals.append((start, end))
    return sorted(intervals)


def _merge_intervals(intervals, join_gap=0.0):
    merged = []
    for start, end in sorted((float(a), float(b)) for a, b in intervals):
        if merged and start - merged[-1][1] <= join_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _parse_srt_intervals(path):
    srt_file = Path(path)
    if not srt_file.is_file():
        return []

    intervals = []
    for block in srt_file.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        for raw, target in zip(lines[1].split("-->"), ("start", "end")):
            match = re.match(r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})", raw.strip())
            if not match:
                break
            hours, minutes, seconds, millis = match.groups()
            value = (
                int(hours) * 3600
                + int(minutes) * 60
                + int(seconds)
                + int(millis.ljust(3, "0")) / 1000
            )
            if target == "start":
                start = value
            else:
                intervals.append((start, value))
    return intervals


def _load_tts_intervals():
    from core._11_merge_audio import load_and_flatten_data

    _, _, intervals = load_and_flatten_data(_8_1_AUDIO_TASK)
    return _merge_intervals(intervals)


def _load_original_speech_intervals():
    """Regions where the source video already has dialogue.

    ASR-aligned subtitle windows are authoritative here: the placed TTS audio is
    often shorter than the line it replaces, so muting only the TTS span leaks
    the tail of the original delivery back into the mix.
    """
    speech = _parse_srt_intervals(SRC_SUBS_FOR_AUDIO_FILE)
    speech += _parse_srt_intervals(TRANS_SUBS_FOR_AUDIO_FILE)
    speech += [tuple(item) for item in _load_tts_intervals()]
    return _merge_intervals(speech)


def _probe_duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _gap_vocal_intervals(speech_intervals, duration):
    """Windows where original vocals may play, i.e. no dialogue is dubbed."""
    guard = float(load_key("audio_mastering.gap_vocals_guard_ms")) / 1000
    join_gap = float(load_key("audio_mastering.gap_vocals_merge_ms")) / 1000
    min_duration = float(load_key("audio_mastering.gap_vocals_min_duration_ms")) / 1000

    padded = _merge_intervals(
        [(max(0.0, start - guard), end + guard) for start, end in speech_intervals],
        join_gap=join_gap,
    )

    gaps = []
    cursor = 0.0
    for start, end in padded:
        if start - cursor >= min_duration:
            gaps.append([cursor, start])
        cursor = max(cursor, end)
    if duration - cursor >= min_duration:
        gaps.append([cursor, duration])
    return gaps


def _keep_only_intervals(intervals, fade):
    """Volume expression that passes audio only inside the given windows."""
    expression = "0"
    for start, end in intervals:
        ramp = min(fade, (end - start) / 2)
        if ramp <= 0:
            window = f"between(t,{start:.3f},{end:.3f})"
        else:
            window = (
                f"if(between(t,{start:.3f},{start + ramp:.3f}),"
                f"(t-{start:.3f})/{ramp:.3f},"
                f"if(between(t,{start + ramp:.3f},{end - ramp:.3f}),1,"
                f"if(between(t,{end - ramp:.3f},{end:.3f}),"
                f"({end:.3f}-t)/{ramp:.3f},0)))"
            )
        expression = f"max({expression},{window})"
    return expression


def _mute_inside_intervals(intervals, fade):
    volume = "1"
    for start, end in intervals:
        if fade <= 0:
            interval_volume = f"if(between(t,{start:.3f},{end:.3f}),0,1)"
        else:
            fade_in_start = max(0, start - fade)
            fade_out_end = end + fade
            interval_volume = (
                f"if(between(t,{fade_in_start:.3f},{start:.3f}),"
                f"({start:.3f}-t)/{fade:.3f},"
                f"if(between(t,{start:.3f},{end:.3f}),0,"
                f"if(between(t,{end:.3f},{fade_out_end:.3f}),"
                f"(t-{end:.3f})/{fade:.3f},1)))"
            )
        volume = f"min({volume},{interval_volume})"
    return volume


def _build_audio_filter(
    intervals,
    gap_vocal_intervals=None,
    preserve_gap_vocals=False,
):
    target_lufs = float(load_key("audio_mastering.target_lufs"))
    voice_lufs = float(load_key("audio_mastering.voice_lufs"))
    true_peak = float(load_key("audio_mastering.true_peak"))
    loudness_range = float(load_key("audio_mastering.loudness_range"))
    fade = float(load_key("audio_mastering.crossfade_ms")) / 1000

    background_ducking = bool(load_key("audio_mastering.background_ducking"))
    ducking_threshold = float(load_key("audio_mastering.ducking_threshold"))
    ducking_ratio = float(load_key("audio_mastering.ducking_ratio"))
    ducking_attack_ms = float(load_key("audio_mastering.ducking_attack_ms"))
    ducking_release_ms = float(load_key("audio_mastering.ducking_release_ms"))

    voice_output = (
        "asplit=2[voice][sidechain]"
        if background_ducking
        else "anull[voice]"
    )
    filters = [
        (
            f"[2:a]loudnorm=I={voice_lufs}:TP={true_peak}:"
            f"LRA={loudness_range},aresample=48000,{voice_output}"
        ),
        "[1:a]aresample=48000[background]",
    ]
    if background_ducking:
        filters.append(
            (
                f"[background][sidechain]sidechaincompress="
                f"threshold={ducking_threshold}:ratio={ducking_ratio}:"
                f"attack={ducking_attack_ms}:release={ducking_release_ms}"
                "[background_ducked]"
            )
        )
    else:
        filters.append("[background]anull[background_ducked]")
    filters.append(
        "[background_ducked][voice]amix=inputs=2:duration=first:normalize=0[base]"
    )
    base_label = "base"

    if preserve_gap_vocals and gap_vocal_intervals:
        gap_vocal_gain = float(load_key("audio_mastering.gap_vocals_gain"))
        gap_vocal_volume = _keep_only_intervals(gap_vocal_intervals, fade)
        filters.extend([
            (
                f"[3:a]aresample=48000,volume='{gap_vocal_gain}*({gap_vocal_volume})':"
                "eval=frame[gap_vocals]"
            ),
            (
                f"[{base_label}][gap_vocals]amix=inputs=2:"
                "duration=first:normalize=0[base_with_gap_vocals]"
            ),
        ])
        base_label = "base_with_gap_vocals"

    if intervals:
        base_volume = _mute_inside_intervals(intervals, fade)
        original_labels = []
        for index, (start, end) in enumerate(intervals):
            duration = end - start
            fade_out_start = max(0, duration - fade)
            delay_ms = round(start * 1000)
            label = f"original_{index}"
            filters.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},"
                "asetpts=PTS-STARTPTS,"
                f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={loudness_range},"
                f"afade=t=in:st=0:d={fade:.3f},"
                f"afade=t=out:st={fade_out_start:.3f}:d={fade:.3f},"
                f"adelay={delay_ms}:all=1[{label}]"
            )
            original_labels.append(f"[{label}]")

        filters.append(
            f"[{base_label}]volume='{base_volume}':eval=frame[base_ducked]"
        )
        inputs = "[base_ducked]" + "".join(original_labels)
        filters.append(
            f"{inputs}amix=inputs={len(original_labels) + 1}:"
            "duration=first:normalize=0[premaster]"
        )
    else:
        filters.append(f"[{base_label}]anull[premaster]")

    filters.append("[premaster]aresample=48000[a]")
    return ";".join(filters)

def _measure_loudness(path):
    target_lufs = float(load_key("audio_mastering.target_lufs"))
    true_peak = float(load_key("audio_mastering.true_peak"))
    loudness_range = float(load_key("audio_mastering.loudness_range"))
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-map", "0:a:0",
            "-af",
            (
                f"loudnorm=I={target_lufs}:TP={true_peak}:"
                f"LRA={loudness_range}:print_format=json"
            ),
            "-f", "null", "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, re.DOTALL)
    if not matches:
        raise RuntimeError("Unable to parse FFmpeg loudness measurement")
    return json.loads(matches[-1])

def _master_audio_two_pass(premaster_path, final_path):
    target_lufs = float(load_key("audio_mastering.target_lufs"))
    true_peak = float(load_key("audio_mastering.true_peak"))
    loudness_range = float(load_key("audio_mastering.loudness_range"))
    audio_bitrate = str(load_key("audio_mastering.audio_bitrate"))
    premaster_path = Path(premaster_path)
    final_path = Path(final_path)
    measurement = _measure_loudness(premaster_path)

    loudnorm = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={loudness_range}:"
        f"measured_I={measurement['input_i']}:"
        f"measured_LRA={measurement['input_lra']}:"
        f"measured_TP={measurement['input_tp']}:"
        f"measured_thresh={measurement['input_thresh']}:"
        f"offset={measurement['target_offset']}:"
        "linear=true:print_format=summary,aresample=48000"
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(premaster_path),
                "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "copy",
                "-af", loudnorm,
                "-c:a", "aac", "-b:a", audio_bitrate,
                str(final_path),
            ],
            check=True,
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    premaster_path.unlink(missing_ok=True)

def merge_video_audio():
    """Merge video and audio, and reduce video volume"""
    from core._1_ytdlp import is_audio_only_input
    if is_audio_only_input():
        rprint("[bold green]🎵 Audio-only input: skipping dubbing video merge. Dubbed audio is in the `output` directory.[/bold green]")
        return

    VIDEO_FILE = find_video_files()
    background_file = _BACKGROUND_AUDIO_FILE
    intervals = _load_original_audio_intervals()
    preserve_gap_vocals = bool(
        load_key("audio_mastering.preserve_original_vocals_in_gaps")
    )
    vocal_file = Path(_VOCAL_AUDIO_FILE)
    if preserve_gap_vocals and not vocal_file.is_file():
        rprint(
            f"[bold yellow]⚠️ Original vocal stem missing: {vocal_file}; "
            "gap vocals will not be preserved.[/bold yellow]"
        )
        preserve_gap_vocals = False
    gap_vocal_intervals = []
    if preserve_gap_vocals:
        speech_intervals = _load_original_speech_intervals()
        gap_vocal_intervals = _gap_vocal_intervals(
            speech_intervals, _probe_duration(vocal_file)
        )
        if not gap_vocal_intervals:
            rprint(
                "[bold yellow]⚠️ No dialogue-free window is long enough; "
                "gap vocals will not be preserved.[/bold yellow]"
            )
            preserve_gap_vocals = False
        else:
            kept = sum(end - start for start, end in gap_vocal_intervals)
            rprint(
                f"[bold blue]Preserving original vocals in "
                f"{len(gap_vocal_intervals)} dialogue-free windows "
                f"({kept:.1f}s).[/bold blue]"
            )
    audio_filter = _build_audio_filter(
        intervals,
        gap_vocal_intervals=gap_vocal_intervals,
        preserve_gap_vocals=preserve_gap_vocals,
    )
    premaster_video = Path(DUB_VIDEO).with_name("output_dub_premaster.mkv")
    premaster_video.unlink(missing_ok=True)

    filter_parts = []
    if load_key("burn_subtitles"):
        video = cv2.VideoCapture(VIDEO_FILE)
        target_width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        target_height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video.release()
        rprint(f"[bold green]Video resolution: {target_width}x{target_height}[/bold green]")

        subtitle_filter = (
            f"subtitles={DUB_SUB_FILE}:force_style='FontSize={TRANS_FONT_SIZE},"
            f"FontName={TRANS_FONT_NAME},PrimaryColour={TRANS_FONT_COLOR},"
            f"OutlineColour={TRANS_OUTLINE_COLOR},OutlineWidth={TRANS_OUTLINE_WIDTH},"
            f"BackColour={TRANS_BACK_COLOR},Alignment=2,MarginV=27,BorderStyle=4'"
        )
        filter_parts.append(
            f"[0:v]scale={target_width}:{target_height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            f"{subtitle_filter}[v]"
        )
    else:
        rprint("[bold blue]Subtitles are not burned; copying the original video stream.[/bold blue]")

    filter_parts.append(audio_filter)
    cmd = [
        'ffmpeg', '-y', '-i', VIDEO_FILE, '-i', background_file, '-i', DUB_AUDIO,
    ]
    if preserve_gap_vocals:
        cmd.extend(['-i', str(vocal_file)])
    cmd.extend(['-filter_complex', ";".join(filter_parts)])

    if load_key("burn_subtitles"):
        if load_key("ffmpeg_gpu"):
            rprint("[bold green]Using GPU acceleration...[/bold green]")
            cmd.extend(['-map', '[v]', '-map', '[a]', '-c:v', 'h264_nvenc'])
        else:
            cmd.extend(['-map', '[v]', '-map', '[a]'])
    else:
        cmd.extend(['-map', '0:v:0', '-map', '[a]', '-c:v', 'copy'])

    cmd.extend([
        '-c:a', 'pcm_s24le',
        '-ar', '48000',
        str(premaster_video),
    ])
    
    subprocess.run(cmd, check=True)
    _master_audio_two_pass(premaster_video, DUB_VIDEO)
    rprint(f"[bold green]Video and audio successfully merged into {DUB_VIDEO}[/bold green]")

if __name__ == '__main__':
    merge_video_audio()
