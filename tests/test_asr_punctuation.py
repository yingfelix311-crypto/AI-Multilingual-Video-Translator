from core.asr_backend.audio_preprocess import _attach_sentence_punctuation, process_transcription


def _bare_words(chars, step=0.2):
    return [
        {"word": char, "start": round(i * step, 2), "end": round(i * step + step, 2)}
        for i, char in enumerate(chars)
    ]


def test_attaches_punctuation_to_preceding_word():
    words = _bare_words("我叫你一声你敢答应吗")
    enriched = _attach_sentence_punctuation("我叫你一声，你敢答应吗？", words)

    assert [item["word"] for item in enriched] == [
        "我", "叫", "你", "一", "声，", "你", "敢", "答", "应", "吗？",
    ]
    assert enriched[4]["start"] == words[4]["start"]


def test_keeps_words_that_already_carry_punctuation():
    words = [
        {"word": " Hello", "start": 0.0, "end": 0.4},
        {"word": " world,", "start": 0.4, "end": 0.8},
        {"word": " again.", "start": 0.8, "end": 1.2},
    ]
    enriched = _attach_sentence_punctuation("Hello world, again.", words)

    assert [item["word"] for item in enriched] == [" Hello", " world,", " again."]


def test_returns_words_unchanged_when_text_does_not_match():
    words = _bare_words("我叫你")
    enriched = _attach_sentence_punctuation("完全不同的文本", words)

    assert enriched is words


def test_process_transcription_keeps_punctuation_in_dataframe():
    result = {
        "segments": [
            {
                "text": "行者孙，嗯，你那葫芦从哪儿来的？",
                "start": 12.2,
                "end": 14.92,
                "speaker_id": None,
                "words": _bare_words("行者孙嗯你那葫芦从哪儿来的"),
            }
        ]
    }
    df = process_transcription(result)

    assert "".join(df["text"].tolist()) == "行者孙，嗯，你那葫芦从哪儿来的？"
