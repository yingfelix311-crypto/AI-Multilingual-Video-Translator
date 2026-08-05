"""
Accumulate real API usage returned by Gemini and Qwen, then price it.

Amounts come from vendor usage fields (tokens / audio seconds). Dollar and yuan
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
            "cost_cny": 0.0,
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
    for key in ("gemini", "qwen"):
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
        qwen["cost_cny"] = round(float(qwen["cost_cny"]) + cost, 6)
        bucket = qwen["by_model"].setdefault(
            str(model),
            {"calls": 0, "seconds": 0.0, "cost_cny": 0.0},
        )
        bucket["calls"] += 1
        bucket["seconds"] = round(float(bucket["seconds"]) + seconds, 3)
        bucket["cost_cny"] = round(float(bucket["cost_cny"]) + cost, 6)
        if task_id:
            qwen.setdefault("last_task_id", str(task_id))
        _save(payload)
    return {"seconds": seconds, "cost_cny": cost}


def clear_usage():
    with LOCK:
        if USAGE_FILE.is_file():
            USAGE_FILE.unlink()


def read_usage_summary():
    payload = _load()
    gemini = payload["gemini"]
    qwen = payload["qwen"]
    gemini_usd = float(gemini.get("cost_usd") or 0)
    qwen_cny = float(qwen.get("cost_cny") or 0)
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
            "cost_cny": round(qwen_cny, 4),
            "cost_label": f"¥{qwen_cny:.4f}",
            "by_model": qwen.get("by_model") or {},
        },
        "total_cny_approx": round(gemini_usd * USD_TO_CNY + qwen_cny, 4),
        "updated_at": payload.get("updated_at"),
        "note": "用量来自 API 返回；金额按官方标价估算（Gemini USD / Qwen 北京站 CNY）",
    }
