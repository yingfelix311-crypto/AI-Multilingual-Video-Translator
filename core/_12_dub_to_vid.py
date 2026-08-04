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
DUB_AUDIO = 'output/dub.mp3'

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

def _build_audio_filter(intervals):
    target_lufs = float(load_key("audio_mastering.target_lufs"))
    voice_lufs = float(load_key("audio_mastering.voice_lufs"))
    true_peak = float(load_key("audio_mastering.true_peak"))
    loudness_range = float(load_key("audio_mastering.loudness_range"))
    fade = float(load_key("audio_mastering.crossfade_ms")) / 1000

    filters = [
        (
            f"[2:a]loudnorm=I={voice_lufs}:TP={true_peak}:"
            f"LRA={loudness_range}[voice]"
        ),
        "[1:a][voice]amix=inputs=2:duration=first:normalize=0[base]",
    ]

    if intervals:
        base_volume = "1"
        original_labels = []
        for index, (start, end) in enumerate(intervals):
            fade_in_start = max(0, start - fade)
            fade_out_end = end + fade
            interval_volume = (
                f"if(between(t,{fade_in_start:.3f},{start:.3f}),"
                f"({start:.3f}-t)/{fade:.3f},"
                f"if(between(t,{start:.3f},{end:.3f}),0,"
                f"if(between(t,{end:.3f},{fade_out_end:.3f}),"
                f"(t-{end:.3f})/{fade:.3f},1)))"
            )
            base_volume = f"min({base_volume},{interval_volume})"

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

        filters.append(f"[base]volume='{base_volume}':eval=frame[base_ducked]")
        inputs = "[base_ducked]" + "".join(original_labels)
        filters.append(
            f"{inputs}amix=inputs={len(original_labels) + 1}:"
            "duration=first:normalize=0[premaster]"
        )
    else:
        filters.append("[base]anull[premaster]")

    filters.append("[premaster]aresample=44100[a]")
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

def _master_audio_two_pass(path):
    target_lufs = float(load_key("audio_mastering.target_lufs"))
    true_peak = float(load_key("audio_mastering.true_peak"))
    loudness_range = float(load_key("audio_mastering.loudness_range"))
    audio_bitrate = str(load_key("audio_mastering.audio_bitrate"))
    measurement = _measure_loudness(path)

    final_path = Path(path)
    premaster_path = final_path.with_name(f"{final_path.stem}_premaster{final_path.suffix}")
    premaster_path.unlink(missing_ok=True)
    final_path.replace(premaster_path)

    loudnorm = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={loudness_range}:"
        f"measured_I={measurement['input_i']}:"
        f"measured_LRA={measurement['input_lra']}:"
        f"measured_TP={measurement['input_tp']}:"
        f"measured_thresh={measurement['input_thresh']}:"
        f"offset={measurement['target_offset']}:"
        "linear=true:print_format=summary,aresample=44100"
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
        premaster_path.replace(final_path)
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
    audio_filter = _build_audio_filter(intervals)

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
        '-filter_complex', ";".join(filter_parts),
    ]

    if load_key("burn_subtitles"):
        if load_key("ffmpeg_gpu"):
            rprint("[bold green]Using GPU acceleration...[/bold green]")
            cmd.extend(['-map', '[v]', '-map', '[a]', '-c:v', 'h264_nvenc'])
        else:
            cmd.extend(['-map', '[v]', '-map', '[a]'])
    else:
        cmd.extend(['-map', '0:v:0', '-map', '[a]', '-c:v', 'copy'])

    cmd.extend([
        '-c:a', 'aac',
        '-b:a', str(load_key("audio_mastering.audio_bitrate")),
        DUB_VIDEO,
    ])
    
    subprocess.run(cmd, check=True)
    _master_audio_two_pass(DUB_VIDEO)
    rprint(f"[bold green]Video and audio successfully merged into {DUB_VIDEO}[/bold green]")

if __name__ == '__main__':
    merge_video_audio()
