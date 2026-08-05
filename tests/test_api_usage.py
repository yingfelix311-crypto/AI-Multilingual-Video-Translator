from core.utils import api_usage


def test_gemini_cost_uses_list_price_for_36_flash():
    cost = api_usage.gemini_cost_usd("gemini-3.6-flash", 1_000_000, 1_000_000)
    assert cost == 1.50 + 7.50


def test_gemini_cached_tokens_use_cheaper_rate():
    cost = api_usage.gemini_cost_usd(
        "gemini-2.5-flash", prompt_tokens=1_000_000, completion_tokens=0, cached_tokens=1_000_000
    )
    assert cost == 0.03


def test_record_gemini_usage_accumulates(tmp_path, monkeypatch):
    path = tmp_path / "api_usage.json"
    monkeypatch.setattr(api_usage, "USAGE_FILE", path)

    api_usage.record_gemini_usage(
        "gemini-3.6-flash",
        {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
    )
    api_usage.record_gemini_usage(
        "gemini-3.6-flash",
        {"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000},
    )

    summary = api_usage.read_usage_summary()
    assert summary["gemini"]["calls"] == 2
    assert summary["gemini"]["prompt_tokens"] == 2000
    assert summary["gemini"]["completion_tokens"] == 500
    assert summary["gemini"]["cost_usd"] > 0


def test_record_qwen_usage_from_seconds(tmp_path, monkeypatch):
    path = tmp_path / "api_usage.json"
    monkeypatch.setattr(api_usage, "USAGE_FILE", path)

    api_usage.record_qwen_usage(
        "qwen-audio-3.0-asr-flash-filetrans",
        {"seconds": 100},
        task_id="task-1",
    )
    summary = api_usage.read_usage_summary()
    assert summary["qwen"]["calls"] == 1
    assert summary["qwen"]["seconds"] == 100
    assert summary["qwen"]["cost_cny"] == 0.022


def test_extract_qwen_seconds_supports_duration_alias():
    assert api_usage.extract_qwen_seconds({"duration": 12.5}) == 12.5
    assert api_usage.extract_qwen_seconds({"models": {"m": {"seconds": 3}}}) == 3


def test_qwen_tts_billable_chars_follow_aliyun_rules():
    assert api_usage.qwen_tts_billable_chars("你好") == 4
    assert api_usage.qwen_tts_billable_chars("中A文123") == 8
    assert api_usage.qwen_tts_billable_chars("中文。") == 5
    assert api_usage.qwen_tts_billable_chars("中 文。") == 6


def test_qwen_tts_cost_uses_plus_list_price():
    # 10000 billable chars * 1.4 CNY / 10k
    assert api_usage.qwen_tts_cost_cny("qwen-audio-3.0-tts-plus", 10000) == 1.4
    assert api_usage.qwen_tts_cost_cny("qwen-audio-3.0-tts-flash", 10000) == 1.0


def test_record_qwen_tts_usage_accumulates(tmp_path, monkeypatch):
    path = tmp_path / "api_usage.json"
    monkeypatch.setattr(api_usage, "USAGE_FILE", path)

    api_usage.record_qwen_tts_usage("qwen-audio-3.0-tts-plus", text="你好")
    api_usage.record_qwen_usage(
        "qwen-audio-3.0-asr-flash-filetrans",
        {"seconds": 100},
    )
    summary = api_usage.read_usage_summary()
    assert summary["qwen"]["calls"] == 2
    assert summary["qwen"]["characters"] == 4
    assert summary["qwen"]["seconds"] == 100
    expected = round(0.022 + 1.4 * 4 / 10000, 4)
    assert summary["qwen"]["cost_cny"] == expected


def test_elevenlabs_tts_cost_uses_v3_list_price():
    assert api_usage.elevenlabs_tts_cost_usd("eleven_v3", 1000) == 0.10
    assert api_usage.elevenlabs_tts_cost_usd("eleven_flash_v2_5", 1000) == 0.05


def test_record_elevenlabs_tts_usage_accumulates(tmp_path, monkeypatch):
    path = tmp_path / "api_usage.json"
    monkeypatch.setattr(api_usage, "USAGE_FILE", path)

    api_usage.record_elevenlabs_tts_usage("eleven_v3", text="Hello")
    summary = api_usage.read_usage_summary()
    assert summary["elevenlabs"]["calls"] == 1
    assert summary["elevenlabs"]["characters"] == 5
    assert summary["elevenlabs"]["cost_usd"] == round(0.10 * 5 / 1000, 4)
    assert summary["total_cny_approx"] > 0


def test_clear_usage(tmp_path, monkeypatch):
    path = tmp_path / "api_usage.json"
    monkeypatch.setattr(api_usage, "USAGE_FILE", path)
    api_usage.record_qwen_usage("qwen3-asr-flash-filetrans", {"seconds": 1})
    assert path.is_file()
    api_usage.clear_usage()
    assert not path.is_file()
