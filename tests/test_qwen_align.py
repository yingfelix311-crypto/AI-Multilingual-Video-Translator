import json


def test_parse_words_from_transcription_applies_offset():
    from core.qwen_align import parse_words_from_transcription

    transcription = {
        "transcripts": [
            {
                "sentences": [
                    {
                        "begin_time": 0,
                        "end_time": 960,
                        "text": "我叫你一声",
                        "words": [
                            {"begin_time": 240, "end_time": 400, "text": "我"},
                            {"begin_time": 400, "end_time": 640, "text": "叫"},
                            {"begin_time": 880, "end_time": 880, "text": "一"},
                        ],
                    }
                ]
            }
        ]
    }

    words, sentences = parse_words_from_transcription(transcription, time_offset=10.0)
    assert words[0]["start"] == 10.24
    assert words[0]["end"] == 10.4
    assert words[2]["start"] == 10.88
    assert words[2]["end"] == 10.88
    assert sentences[0]["start"] == 10.0
    assert sentences[0]["text"] == "我叫你一声"


def test_char_intervals_merge_nearby_words():
    from core.qwen_align import char_intervals_from_alignment

    alignment = {
        "words": [
            {"start": 0.24, "end": 0.4, "text": "我"},
            {"start": 0.4, "end": 0.64, "text": "叫"},
            {"start": 1.28, "end": 1.44, "text": "你"},
            {"start": 2.0, "end": 2.0, "text": "哈"},
        ]
    }
    intervals = char_intervals_from_alignment(alignment, join_gap=0.2)
    assert intervals == [[0.24, 0.64], [1.28, 1.44], [2.0, 2.04]]


def test_alignment_cache_invalid_when_signature_changes(tmp_path, monkeypatch):
    from core import qwen_align

    audio = tmp_path / "vocal.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 100)
    cache = tmp_path / "char_alignment.json"
    monkeypatch.setattr(qwen_align, "_CHAR_ALIGNMENT_FILE", str(cache))
    monkeypatch.setattr(qwen_align, "_cfg", lambda key, default=None: {
        "model": "qwen3-asr-flash-filetrans",
        "language": "zh",
    }.get(key, default))

    signature = qwen_align._alignment_signature(audio, "zh")
    cache.write_text(
        json.dumps({"signature": signature, "words": []}),
        encoding="utf-8",
    )
    assert qwen_align._cache_valid(audio, "zh")

    audio.write_bytes(b"RIFF" + b"\x01" * 100)
    assert not qwen_align._cache_valid(audio, "zh")
