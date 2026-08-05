"""
Accumulate API usage for Gemini, Qwen and ElevenLabs, then price it.

Amounts come from vendor usage fields or billed text length. Dollar and yuan
figures use published list prices — APIs do not return invoice amounts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock

USAGE_FILE = Path("output/log/api_usage.json")
LOCK = Lock()

# Official list prices (paid tier). Update when vendors change rates.
# Gemini: USD per 1M tokens — https://ai.google.dev/gemini-api/docs/pricing
# Qwen ASR (Beijing): CNY per audio second — Aliyun Model Studio docs
# Qwen TTS (Beijing): CNY per 10k billable chars — Aliyun Model Studio docs
# ElevenLabs TTS: USD per 1k characters — https://elevenlabs.io/pricing/api
GEMINI_PRICES = {
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50, "cached": 0.15},
    "gemini-3.5-flash": {"input": 0.50, "output": 3.00, "cached": 0.05},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00, "cached": 0.05},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50, "cached": 0.03},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40, "cached": 0.01},
    "default": {"input": 1.50, "output": 7.50, "cached": 0.15},
}

QWEN_ASR_CNY_PER_SECOND = {
    "qwen-audio-3.0-asr-flash-filetrans": 0.00022,
    "qwen3-asr-flash-filetrans": 0.00022,
    "fun-asr": 0.00022,
    "default": 0.00022,
}

QWEN_TTS_CNY_PER_10K_CHARS = {
    "qwen-audio-3.0-tts-plus": 1.4,
    "qwen-audio-3.0-tts-flash": 1.0,
    "default": 1.4,
}

ELEVENLABS_TTS_USD_PER_1K_CHARS = {
    "eleven_flash_v2_5": 0.05,
    "eleven_flash_v2": 0.05,
    "eleven_turbo_v2_5": 0.05,
    "eleven_turbo_v2": 0.05,
    "eleven_multilingual_v2": 0.10,
    "eleven_v3": 0.10,
    "default": 0.10,
}

USD_TO_CNY = 7.2


def _empty():
    return {
        "gemini": {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "by_model": {},
        },
        "qwen": {
            "calls": 0,
            "seconds": 0.0,
            "characters": 0,
            "cost_cny": 0.0,
            "by_model": {},
        },
        "elevenlabs": {
            "calls": 0,
            "characters": 0,
            "cost_usd": 0.0,
            "by_model": {},
        },
        "updated_at": None,
    }


def _load():
    if not USAGE_FILE.is_file():
        return _empty()
    try:
        payload = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    base = _empty()
    for key in ("gemini", "qwen", "elevenlabs"):
        if isinstance(payload.get(key), dict):
            base[key].update(payload[key])
            if not isinstance(base[key].get("by_model"), dict):
                base[key]["by_model"] = {}
    base["updated_at"] = payload.get("updated_at")
    return base


def _save(payload):
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = time.time()
    tmp = USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USAGE_FILE)


def _gemini_rate(model):
    name = str(model or "").strip().lower()
    if name in GEMINI_PRICES:
        return GEMINI_PRICES[name]
    for key, rate in GEMINI_PRICES.items():
        if key != "default" and key in name:
            return rate
    return GEMINI_PRICES["default"]


def _qwen_rate(model):
    name = str(model or "").strip().lower()
    if name in QWEN_ASR_CNY_PER_SECOND:
        return QWEN_ASR_CNY_PER_SECOND[name]
    for key, rate in QWEN_ASR_CNY_PER_SECOND.items():
        if key != "default" and key in name:
            return rate
    return QWEN_ASR_CNY_PER_SECOND["default"]


def _qwen_tts_rate(model):
    name = str(model or "").strip().lower()
    if name in QWEN_TTS_CNY_PER_10K_CHARS:
        return QWEN_TTS_CNY_PER_10K_CHARS[name]
    for key, rate in QWEN_TTS_CNY_PER_10K_CHARS.items():
        if key != "default" and key in name:
            return rate
    return QWEN_TTS_CNY_PER_10K_CHARS["default"]


def _is_cjk_ideograph(ch):
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0x2F800 <= code <= 0x2FA1F
        or code == 0x3007
    )


def qwen_tts_billable_chars(text):
    """
    Aliyun Model Studio TTS character billing:
    one CJK ideograph = 2 chars; other characters = 1 char.
    """
    total = 0
    for ch in str(text or ""):
        total += 2 if _is_cjk_ideograph(ch) else 1
    return total


def _usage_field(usage, *names):
    if usage is None:
        return 0
    if isinstance(usage, dict):
        for name in names:
            if usage.get(name) is not None:
                return usage.get(name)
        return 0
    for name in names:
        value = getattr(usage, name, None)
        if value is not None:
            return value
    return 0


def _cached_tokens(usage):
    details = _usage_field(usage, "prompt_tokens_details", "input_tokens_details")
    if details is None:
        return 0
    if isinstance(details, dict):
        return int(details.get("cached_tokens") or 0)
    return int(getattr(details, "cached_tokens", 0) or 0)


def gemini_cost_usd(model, prompt_tokens, completion_tokens, cached_tokens=0):
    rate = _gemini_rate(model)
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), prompt_tokens))
    billable_prompt = prompt_tokens - cached_tokens
    return (
        billable_prompt / 1_000_000 * rate["input"]
        + cached_tokens / 1_000_000 * rate["cached"]
        + completion_tokens / 1_000_000 * rate["output"]
    )


def qwen_cost_cny(model, seconds):
    return max(0.0, float(seconds or 0)) * _qwen_rate(model)


def qwen_tts_cost_cny(model, characters):
    return max(0.0, float(characters or 0)) / 10000.0 * _qwen_tts_rate(model)


def _elevenlabs_tts_rate(model):
    name = str(model or "").strip().lower()
    if name in ELEVENLABS_TTS_USD_PER_1K_CHARS:
        return ELEVENLABS_TTS_USD_PER_1K_CHARS[name]
    if "flash" in name or "turbo" in name:
        return ELEVENLABS_TTS_USD_PER_1K_CHARS["eleven_flash_v2_5"]
    for key, rate in ELEVENLABS_TTS_USD_PER_1K_CHARS.items():
        if key != "default" and key in name:
            return rate
    return ELEVENLABS_TTS_USD_PER_1K_CHARS["default"]


def elevenlabs_tts_billable_chars(text):
    """ElevenLabs TTS bills each input character (including spaces)."""
    return len(str(text or ""))


def elevenlabs_tts_cost_usd(model, characters):
    return max(0.0, float(characters or 0)) / 1000.0 * _elevenlabs_tts_rate(model)


def record_gemini_usage(model, usage):
    """Record one Gemini chat.completions usage object. Cache hits skip this."""
    prompt = int(_usage_field(usage, "prompt_tokens", "input_tokens") or 0)
    completion = int(_usage_field(usage, "completion_tokens", "output_tokens") or 0)
    total = int(_usage_field(usage, "total_tokens") or (prompt + completion))
    cached = _cached_tokens(usage)
    if prompt <= 0 and completion <= 0 and total <= 0:
        return None

    cost = gemini_cost_usd(model, prompt, completion, cached)
    with LOCK:
        payload = _load()
        gemini = payload["gemini"]
        gemini["calls"] += 1
        gemini["prompt_tokens"] += prompt
        gemini["completion_tokens"] += completion
        gemini["cached_tokens"] += cached
        gemini["total_tokens"] += total
        gemini["cost_usd"] = round(float(gemini["cost_usd"]) + cost, 6)
        bucket = gemini["by_model"].setdefault(
            str(model),
            {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        bucket["cached_tokens"] += cached
        bucket["cost_usd"] = round(float(bucket["cost_usd"]) + cost, 6)
        _save(payload)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "cost_usd": cost}


def extract_qwen_seconds(usage):
    if not usage:
        return 0.0
    if isinstance(usage, (int, float)):
        return float(usage)
    if not isinstance(usage, dict):
        return 0.0
    for key in ("seconds", "duration", "audio_seconds", "input_seconds"):
        if usage.get(key) is not None:
            return float(usage[key])
    models = usage.get("models")
    if isinstance(models, dict):
        total = 0.0
        for item in models.values():
            if isinstance(item, dict):
                total += extract_qwen_seconds(item)
            elif isinstance(item, (int, float)):
                total += float(item)
        if total:
            return total
    return 0.0


def record_qwen_usage(model, usage, task_id=None):
    """Record one DashScope ASR task usage blob."""
    seconds = extract_qwen_seconds(usage)
    if seconds <= 0:
        return None
    cost = qwen_cost_cny(model, seconds)
    with LOCK:
        payload = _load()
        qwen = payload["qwen"]
        qwen["calls"] += 1
        qwen["seconds"] = round(float(qwen["seconds"]) + seconds, 3)
        qwen["characters"] = int(qwen.get("characters") or 0)
        qwen["cost_cny"] = round(float(qwen["cost_cny"]) + cost, 6)
        bucket = qwen["by_model"].setdefault(
            str(model),
            {"calls": 0, "seconds": 0.0, "characters": 0, "cost_cny": 0.0},
        )
        bucket["calls"] += 1
        bucket["seconds"] = round(float(bucket.get("seconds") or 0) + seconds, 3)
        bucket["characters"] = int(bucket.get("characters") or 0)
        bucket["cost_cny"] = round(float(bucket["cost_cny"]) + cost, 6)
        if task_id:
            qwen.setdefault("last_task_id", str(task_id))
        _save(payload)
    return {"seconds": seconds, "cost_cny": cost}


def record_qwen_tts_usage(model, text=None, characters=None):
    """Record one Qwen TTS synthesis call billed by character count."""
    chars = int(characters) if characters is not None else qwen_tts_billable_chars(text)
    if chars <= 0:
        return None
    cost = qwen_tts_cost_cny(model, chars)
    with LOCK:
        payload = _load()
        qwen = payload["qwen"]
        qwen["calls"] += 1
        qwen["seconds"] = round(float(qwen.get("seconds") or 0), 3)
        qwen["characters"] = int(qwen.get("characters") or 0) + chars
        qwen["cost_cny"] = round(float(qwen["cost_cny"]) + cost, 6)
        bucket = qwen["by_model"].setdefault(
            str(model),
            {"calls": 0, "seconds": 0.0, "characters": 0, "cost_cny": 0.0},
        )
        bucket["calls"] += 1
        bucket["seconds"] = round(float(bucket.get("seconds") or 0), 3)
        bucket["characters"] = int(bucket.get("characters") or 0) + chars
        bucket["cost_cny"] = round(float(bucket["cost_cny"]) + cost, 6)
        _save(payload)
    return {"characters": chars, "cost_cny": cost}


def record_elevenlabs_tts_usage(model, text=None, characters=None):
    """Record one ElevenLabs TTS call billed by input character count."""
    chars = int(characters) if characters is not None else elevenlabs_tts_billable_chars(text)
    if chars <= 0:
        return None
    cost = elevenlabs_tts_cost_usd(model, chars)
    with LOCK:
        payload = _load()
        eleven = payload["elevenlabs"]
        eleven["calls"] += 1
        eleven["characters"] = int(eleven.get("characters") or 0) + chars
        eleven["cost_usd"] = round(float(eleven.get("cost_usd") or 0) + cost, 6)
        bucket = eleven["by_model"].setdefault(
            str(model),
            {"calls": 0, "characters": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["characters"] = int(bucket.get("characters") or 0) + chars
        bucket["cost_usd"] = round(float(bucket.get("cost_usd") or 0) + cost, 6)
        _save(payload)
    return {"characters": chars, "cost_usd": cost}


def clear_usage():
    with LOCK:
        if USAGE_FILE.is_file():
            USAGE_FILE.unlink()


def read_usage_summary():
    payload = _load()
    gemini = payload["gemini"]
    qwen = payload["qwen"]
    eleven = payload["elevenlabs"]
    gemini_usd = float(gemini.get("cost_usd") or 0)
    qwen_cny = float(qwen.get("cost_cny") or 0)
    eleven_usd = float(eleven.get("cost_usd") or 0)
    return {
        "gemini": {
            "calls": int(gemini.get("calls") or 0),
            "prompt_tokens": int(gemini.get("prompt_tokens") or 0),
            "completion_tokens": int(gemini.get("completion_tokens") or 0),
            "cached_tokens": int(gemini.get("cached_tokens") or 0),
            "total_tokens": int(gemini.get("total_tokens") or 0),
            "cost_usd": round(gemini_usd, 4),
            "cost_label": f"${gemini_usd:.4f}",
            "by_model": gemini.get("by_model") or {},
        },
        "qwen": {
            "calls": int(qwen.get("calls") or 0),
            "seconds": round(float(qwen.get("seconds") or 0), 3),
            "characters": int(qwen.get("characters") or 0),
            "cost_cny": round(qwen_cny, 4),
            "cost_label": f"¥{qwen_cny:.4f}",
            "by_model": qwen.get("by_model") or {},
        },
        "elevenlabs": {
            "calls": int(eleven.get("calls") or 0),
            "characters": int(eleven.get("characters") or 0),
            "cost_usd": round(eleven_usd, 4),
            "cost_label": f"${eleven_usd:.4f}",
            "by_model": eleven.get("by_model") or {},
        },
        "total_cny_approx": round(
            (gemini_usd + eleven_usd) * USD_TO_CNY + qwen_cny, 4
        ),
        "updated_at": payload.get("updated_at"),
        "note": (
            "用量来自 API 返回或官方计费规则估算；金额按官方标价"
            "（Gemini / ElevenLabs USD，Qwen 北京站 CNY）"
        ),
    }
