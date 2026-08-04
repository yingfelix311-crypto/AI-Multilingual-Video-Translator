import hashlib
import json
from pathlib import Path

from core.utils import ask_gpt, load_key, rprint


SPEAKER_TAGS_FILE = "output/audio/speaker_tags.json"


def _parse_srt(content):
    cues = []
    for block in content.replace("\r\n", "\n").strip().split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = [part.strip() for part in lines[1].split("-->")]
        cues.append({
            "cue": int(lines[0]),
            "start": start,
            "end": end,
            "text": " ".join(lines[2:]),
        })
    return cues


def _source_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_response(response, expected_cues):
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        return {"status": "error", "message": "Response must contain an items array"}

    items = response["items"]
    actual_cues = [item.get("cue") for item in items if isinstance(item, dict)]
    if actual_cues != expected_cues:
        return {
            "status": "error",
            "message": f"Cue IDs mismatch: expected {expected_cues}, got {actual_cues}",
        }

    for item in items:
        if not isinstance(item.get("speaker"), str) or not item["speaker"].strip():
            return {"status": "error", "message": f"Missing speaker for cue {item.get('cue')}"}
        if not isinstance(item.get("merge_with_previous"), bool):
            return {
                "status": "error",
                "message": f"Invalid merge_with_previous for cue {item.get('cue')}",
            }
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            return {"status": "error", "message": f"Invalid confidence for cue {item.get('cue')}"}

    return {"status": "success", "message": ""}


def _build_prompt(cues):
    cue_text = "\n".join(
        f"[{cue['cue']}] {cue['start']} --> {cue['end']} | {cue['text']}"
        for cue in cues
    )
    return f"""
You are labeling dialogue subtitles for video dubbing.

For every cue:
1. Infer a stable speaker label from dialogue context. Reuse exactly the same
   label whenever the same character speaks. Prefer character names when known;
   otherwise use stable labels such as woman_1, man_1, child_1, narrator.
2. Set merge_with_previous=true ONLY when this cue and the immediately previous
   cue are spoken by the same character AND form one continuous utterance that
   should be synthesized in a single TTS request.
3. Do not merge merely because the same speaker talks twice. A completed thought,
   a response turn, a noticeable pause, or uncertainty must remain separate.
4. Give confidence from 0 to 1. Use low confidence for ambiguous short lines.
5. Never omit, reorder, or renumber cues.

Return JSON only:
{{
  "items": [
    {{
      "cue": 1,
      "speaker": "narrator",
      "merge_with_previous": false,
      "confidence": 0.95,
      "reason": "brief reason"
    }}
  ]
}}

Subtitles:
{cue_text}
""".strip()


def load_speaker_tags(srt_path="output/trans.srt", tags_path=SPEAKER_TAGS_FILE):
    srt_file = Path(srt_path)
    tags_file = Path(tags_path)
    if not srt_file.is_file() or not tags_file.is_file():
        return {}

    content = srt_file.read_text(encoding="utf-8")
    data = json.loads(tags_file.read_text(encoding="utf-8"))
    if data.get("source_hash") != _source_hash(content):
        return {}
    return {item["cue"]: item for item in data.get("items", [])}


def tag_srt_speakers(srt_path="output/trans.srt", tags_path=SPEAKER_TAGS_FILE, force=False):
    srt_file = Path(srt_path)
    if not srt_file.is_file():
        raise FileNotFoundError(f"SRT not found: {srt_path}")

    content = srt_file.read_text(encoding="utf-8")
    cues = _parse_srt(content)
    if not cues:
        raise ValueError("No valid SRT cues found for speaker tagging")

    if not force:
        cached = load_speaker_tags(srt_path, tags_path)
        if cached and len(cached) == len(cues):
            rprint(f"[blue]Using cached LLM speaker tags: {tags_path}[/blue]")
            return cached

    expected_cues = [cue["cue"] for cue in cues]

    def validate(response):
        return _validate_response(response, expected_cues)

    response = ask_gpt(
        _build_prompt(cues),
        resp_type="json",
        valid_def=validate,
        log_title="speaker_tagging",
    )

    items = []
    for item in response["items"]:
        items.append({
            "cue": item["cue"],
            "speaker": item["speaker"].strip(),
            "merge_with_previous": item["merge_with_previous"],
            "confidence": float(item["confidence"]),
            "reason": str(item.get("reason", "")).strip(),
        })

    result = {
        "source_hash": _source_hash(content),
        "model": load_key("api.model"),
        "items": items,
    }
    tags_file = Path(tags_path)
    tags_file.parent.mkdir(parents=True, exist_ok=True)
    tags_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rprint(f"[green]LLM speaker tags saved: {tags_path} ({len(items)} cues)[/green]")
    return {item["cue"]: item for item in items}
