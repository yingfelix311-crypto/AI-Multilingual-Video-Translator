import json
from pathlib import Path

from pydub import AudioSegment


def test_merge_audio_segments_keeps_48k_lossless_timeline(tmp_path, monkeypatch):
    from core import _11_merge_audio as merge_audio

    first = tmp_path / "1.wav"
    second = tmp_path / "2.wav"
    AudioSegment.silent(duration=500, frame_rate=48000).export(first, format="wav")
    AudioSegment.silent(duration=400, frame_rate=48000).export(second, format="wav")
    monkeypatch.setattr(merge_audio, "check_cancel", lambda: None)

    merged = merge_audio.merge_audio_segments(
        [str(first), str(second)],
        [[0.1, 0.6], [0.8, 1.2]],
        48000,
    )

    assert merged.frame_rate == 48000
    assert merged.channels == 1
    assert 1195 <= len(merged) <= 1205


def test_mastering_filter_ducks_background_and_uses_48k(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    values = {
        "audio_mastering.target_lufs": -16,
        "audio_mastering.voice_lufs": -18,
        "audio_mastering.true_peak": -1,
        "audio_mastering.loudness_range": 11,
        "audio_mastering.crossfade_ms": 50,
        "audio_mastering.background_ducking": True,
        "audio_mastering.ducking_threshold": 0.03,
        "audio_mastering.ducking_ratio": 6,
        "audio_mastering.ducking_attack_ms": 20,
        "audio_mastering.ducking_release_ms": 250,
    }
    monkeypatch.setattr(dub_to_vid, "load_key", values.__getitem__)

    audio_filter = dub_to_vid._build_audio_filter([])

    assert "sidechaincompress=" in audio_filter
    assert "threshold=0.03:ratio=6.0" in audio_filter
    assert "aresample=48000[a]" in audio_filter
    assert "44100" not in audio_filter


def test_mastering_filter_passes_gap_vocals_only_inside_given_windows(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    values = {
        "audio_mastering.target_lufs": -16,
        "audio_mastering.voice_lufs": -18,
        "audio_mastering.true_peak": -1,
        "audio_mastering.loudness_range": 11,
        "audio_mastering.crossfade_ms": 50,
        "audio_mastering.background_ducking": True,
        "audio_mastering.ducking_threshold": 0.03,
        "audio_mastering.ducking_ratio": 6,
        "audio_mastering.ducking_attack_ms": 20,
        "audio_mastering.ducking_release_ms": 250,
        "audio_mastering.gap_vocals_gain": 0.8,
    }
    monkeypatch.setattr(dub_to_vid, "load_key", values.__getitem__)

    audio_filter = dub_to_vid._build_audio_filter(
        [],
        gap_vocal_intervals=[[2.0, 6.0]],
        preserve_gap_vocals=True,
    )

    assert "[3:a]aresample=48000" in audio_filter
    assert "volume='0.8*(max(0,if(between(t,2.000,2.050)" in audio_filter
    assert "between(t,2.050,5.950),1" in audio_filter
    assert "[base][gap_vocals]amix=" in audio_filter


def test_mastering_filter_skips_gap_vocals_when_no_window_qualifies(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    values = {
        "audio_mastering.target_lufs": -16,
        "audio_mastering.voice_lufs": -18,
        "audio_mastering.true_peak": -1,
        "audio_mastering.loudness_range": 11,
        "audio_mastering.crossfade_ms": 50,
        "audio_mastering.background_ducking": True,
        "audio_mastering.ducking_threshold": 0.03,
        "audio_mastering.ducking_ratio": 6,
        "audio_mastering.ducking_attack_ms": 20,
        "audio_mastering.ducking_release_ms": 250,
    }
    monkeypatch.setattr(dub_to_vid, "load_key", values.__getitem__)

    audio_filter = dub_to_vid._build_audio_filter(
        [],
        gap_vocal_intervals=[],
        preserve_gap_vocals=True,
    )

    assert "[3:a]" not in audio_filter
    assert "gap_vocals" not in audio_filter


def test_gap_windows_guard_speech_edges_and_drop_short_fragments(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    values = {
        "audio_mastering.gap_vocals_guard_ms": 250,
        "audio_mastering.gap_vocals_merge_ms": 400,
        "audio_mastering.gap_vocals_min_duration_ms": 700,
    }
    monkeypatch.setattr(dub_to_vid, "load_key", values.__getitem__)
    monkeypatch.setattr(dub_to_vid, "_load_alignment_mode", lambda: "conservative")

    gaps = dub_to_vid._gap_vocal_intervals(
        [(2.0, 4.0), (4.3, 5.0), (8.0, 9.0)], 12.0, mode="conservative"
    )

    assert gaps == [[0.0, 1.75], [5.25, 7.75], [9.25, 12.0]]


def test_aligned_gap_guard_uses_smaller_pad(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    values = {
        "audio_mastering.gap_vocals_guard_ms": 250,
        "audio_mastering.gap_vocals_aligned_guard_ms": 60,
        "audio_mastering.gap_vocals_merge_ms": 400,
        "audio_mastering.gap_vocals_min_duration_ms": 200,
    }
    monkeypatch.setattr(dub_to_vid, "load_key", values.__getitem__)

    gaps = dub_to_vid._gap_vocal_intervals(
        [(2.0, 4.0)], 6.0, mode="aligned"
    )

    assert gaps == [[0.0, 1.94], [4.06, 6.0]]


def test_forced_gap_vocals_load_from_preserve_file(tmp_path, monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    path = tmp_path / "preserve_original_intervals.json"
    path.write_text(
        json.dumps({"intervals": [[8.36, 8.44], [1.0, 1.0], "bad"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(dub_to_vid, "_PRESERVE_ORIGINAL_INTERVALS_FILE", str(path))

    assert dub_to_vid._load_forced_gap_vocal_intervals() == [[8.36, 8.44]]


def test_zero_crossfade_still_builds_valid_gap_window_expression():
    from core import _12_dub_to_vid as dub_to_vid

    expression = dub_to_vid._keep_only_intervals([[1.0, 2.0]], 0)

    assert expression == "max(0,between(t,1.000,2.000))"
    assert "/0.000" not in expression


def test_conservative_speech_intervals_cover_subtitle_windows(tmp_path, monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    src_srt = tmp_path / "src.srt"
    src_srt.write_text(
        "1\n00:00:02,000 --> 00:00:05,000\nhello\n\n"
        "2\n00:00:08,000 --> 00:00:09,500\nworld\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dub_to_vid, "SRC_SUBS_FOR_AUDIO_FILE", str(src_srt))
    monkeypatch.setattr(
        dub_to_vid, "TRANS_SUBS_FOR_AUDIO_FILE", str(tmp_path / "missing.srt")
    )
    monkeypatch.setattr(dub_to_vid, "_load_tts_intervals", lambda: [[2.0, 3.5]])

    assert dub_to_vid._load_original_speech_intervals("conservative") == [
        [2.0, 5.0],
        [8.0, 9.5],
    ]


def test_aligned_speech_intervals_use_char_alignment(monkeypatch):
    from core import _12_dub_to_vid as dub_to_vid

    monkeypatch.setattr(
        dub_to_vid,
        "_load_char_speech_intervals",
        lambda: [[0.24, 0.96], [1.28, 2.24]],
    )
    assert dub_to_vid._load_original_speech_intervals("aligned") == [
        [0.24, 0.96],
        [1.28, 2.24],
    ]


def test_audio_paths_use_lossless_intermediates():
    from core import _11_merge_audio as merge_audio
    from core import _12_dub_to_vid as dub_to_vid
    from core.utils import models

    assert Path(merge_audio.DUB_VOCAL_FILE).suffix == ".wav"
    assert Path(dub_to_vid.DUB_AUDIO).suffix == ".wav"
    assert Path(models._VOCAL_AUDIO_FILE).suffix == ".wav"
    assert Path(models._BACKGROUND_AUDIO_FILE).suffix == ".wav"
