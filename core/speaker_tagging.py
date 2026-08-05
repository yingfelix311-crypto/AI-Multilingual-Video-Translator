import hashlib
import json
from pathlib import Path

from core.utils import ask_gpt, load_key, rprint
from core.utils.models import _2_CLEANED_CHUNKS


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
   should share one reference clip and one TTS request.
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


def save_speaker_tags(items, srt_path="output/trans.srt", tags_path=SPEAKER_TAGS_FILE, model=None):
    """Persist speaker tags for the current SRT. Manual edits set confidence=1.0."""
    srt_file = Path(srt_path)
    if not srt_file.is_file():
        raise FileNotFoundError(f"SRT not found: {srt_path}")

    content = srt_file.read_text(encoding="utf-8")
    cues = _parse_srt(content)
    if not cues:
        raise ValueError("No valid SRT cues found for speaker tagging")

    expected = [cue["cue"] for cue in cues]
    normalized = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each speaker tag must be an object")
        cue = int(raw["cue"])
        speaker = str(raw.get("speaker", "")).strip()
        if not speaker:
            raise ValueError(f"Missing speaker for cue {cue}")
        merge = bool(raw.get("merge_with_previous", False))
        confidence = float(raw.get("confidence", 1.0 if raw.get("manual_override") else 0.0))
        if not 0 <= confidence <= 1:
            raise ValueError(f"Invalid confidence for cue {cue}")
        normalized.append({
            "cue": cue,
            "speaker": speaker,
            "merge_with_previous": merge,
            "force_unmerge": bool(raw.get("force_unmerge", False)) and not merge,
            "confidence": confidence,
            "reason": str(raw.get("reason", "")).strip(),
            "manual_override": bool(raw.get("manual_override", False)),
        })

    actual = [item["cue"] for item in normalized]
    if actual != expected:
        raise ValueError(f"Cue IDs mismatch: expected {expected}, got {actual}")

    # First cue can never merge into a previous one.
    if normalized and normalized[0]["merge_with_previous"]:
        raise ValueError(f"Cue {normalized[0]['cue']} cannot merge with a previous cue")

    for index, item in enumerate(normalized[1:], start=1):
        if not item["merge_with_previous"]:
            continue
        previous = normalized[index - 1]
        if item["speaker"] != previous["speaker"]:
            raise ValueError(
                f"Cue {item['cue']} cannot merge into previous: "
                f"speaker '{item['speaker']}' != '{previous['speaker']}'"
            )

    result = {
        "source_hash": _source_hash(content),
        "model": model if model is not None else load_key("api.model"),
        "items": normalized,
    }
    tags_file = Path(tags_path)
    tags_file.parent.mkdir(parents=True, exist_ok=True)
    tags_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rprint(f"[green]Speaker tags saved: {tags_path} ({len(normalized)} cues)[/green]")
    return {item["cue"]: item for item in normalized}


# ------------
# Acoustic speaker clusters
# ------------
# Dialogue text carries no evidence of who is speaking, so a text-only LLM pass
# happily labels two characters as one. Diarization cluster ids come from the
# audio, so they decide speaker identity; the LLM only supplies readable names.


def _srt_time_to_seconds(value):
    hours, minutes, rest = str(value).strip().split(":")
    seconds, millis = rest.replace(".", ",").split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def _load_acoustic_words_from_chunks(chunks_path):
    path = Path(chunks_path)
    if not path.is_file():
        return []

    import pandas as pd

    df = pd.read_excel(path)
    if "speaker_id" not in df.columns:
        return []
    words = []
    for _, row in df.iterrows():
        speaker = row["speaker_id"]
        if pd.isna(speaker):
            continue
        words.append((float(row["start"]), float(row["end"]), int(speaker)))
    return words


def _load_acoustic_words_from_alignment(alignment_path=None):
    from core.qwen_align import load_char_alignment
    from core.utils.models import _CHAR_ALIGNMENT_FILE

    if alignment_path is not None:
        path = Path(alignment_path)
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    else:
        payload = load_char_alignment()
        if not payload and not Path(_CHAR_ALIGNMENT_FILE).is_file():
            return []
        payload = payload or {}

    words = []
    for item in payload.get("words") or []:
        speaker = item.get("speaker_id")
        if speaker is None:
            continue
        try:
            words.append((float(item["start"]), float(item["end"]), int(speaker)))
        except (KeyError, TypeError, ValueError):
            continue
    return words


def _load_acoustic_words(chunks_path=_2_CLEANED_CHUNKS):
    """Prefer ASR chunk diarization; fall back to char_alignment.json speaker_id."""
    words = _load_acoustic_words_from_chunks(chunks_path)
    if words:
        return words
    return _load_acoustic_words_from_alignment()


def _cue_cluster_ids(cues, words):
    clusters = {}
    if not words:
        return clusters
    for cue in cues:
        start = _srt_time_to_seconds(cue["start"])
        end = _srt_time_to_seconds(cue["end"])
        totals = {}
        for word_start, word_end, speaker in words:
            # Qwen emits zero-length words; give them a floor so they still vote.
            overlap = min(end, max(word_end, word_start + 0.04)) - max(start, word_start)
            if overlap > 0:
                totals[speaker] = totals.get(speaker, 0.0) + overlap
        if totals:
            clusters[cue["cue"]] = max(totals, key=totals.get)
    return clusters


def _build_naming_prompt(cues, clusters, samples_per_cluster=12):
    groups = {}
    for cue in cues:
        cluster = clusters.get(cue["cue"])
        if cluster is None:
            continue
        groups.setdefault(cluster, []).append(cue["text"])

    blocks = []
    for cluster in sorted(groups):
        lines = groups[cluster][:samples_per_cluster]
        rendered = "\n".join(f"  - {line}" for line in lines)
        blocks.append(f"cluster {cluster} ({len(groups[cluster])} lines):\n{rendered}")
    listing = "\n\n".join(blocks)
    ids = ", ".join(str(cluster) for cluster in sorted(groups))

    return f"""
Speaker diarization already grouped these dialogue lines by voice. Each cluster
is one character. Your only job is to name each cluster.

Rules:
1. Give every cluster exactly one stable label. Prefer the character's name when
   the dialogue makes it clear; otherwise use labels like man_1, woman_1, narrator.
2. Labels must be lowercase snake_case and unique across clusters.
3. Do not merge, split, reorder, or re-assign clusters. Name what you are given.
4. Cover exactly these cluster ids: {ids}

Return JSON only:
{{
  "speakers": [
    {{"cluster": 0, "name": "narrator", "reason": "brief reason"}}
  ]
}}

Clusters:
{listing}
""".strip()


def _validate_naming_response(response, expected_clusters):
    if not isinstance(response, dict) or not isinstance(response.get("speakers"), list):
        return {"status": "error", "message": "Response must contain a speakers array"}

    actual = []
    names = []
    for entry in response["speakers"]:
        if not isinstance(entry, dict):
            return {"status": "error", "message": "Each speaker entry must be an object"}
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            return {"status": "error", "message": f"Missing name for cluster {entry.get('cluster')}"}
        actual.append(entry.get("cluster"))
        names.append(name.strip())

    if sorted(actual, key=lambda v: (v is None, v)) != expected_clusters:
        return {
            "status": "error",
            "message": f"Cluster ids mismatch: expected {expected_clusters}, got {actual}",
        }
    if len(set(names)) != len(names):
        return {"status": "error", "message": f"Cluster names must be unique, got {names}"}

    return {"status": "success", "message": ""}


def _name_clusters(cues, clusters):
    expected = sorted({int(value) for value in clusters.values()})

    def validate(response):
        return _validate_naming_response(response, expected)

    response = ask_gpt(
        _build_naming_prompt(cues, clusters),
        resp_type="json",
        valid_def=validate,
        log_title="speaker_naming",
    )
    return {
        int(entry["cluster"]): (entry["name"].strip(), str(entry.get("reason", "")).strip())
        for entry in response["speakers"]
    }


def _tag_from_clusters(cues, clusters):
    """Speaker identity comes from audio; the LLM only names the clusters."""
    names = _name_clusters(cues, clusters)
    rprint(
        f"[green]Acoustic speaker clusters named: "
        f"{ {cluster: name for cluster, (name, _) in names.items()} }[/green]"
    )

    items = []
    previous_cluster = None
    for cue in cues:
        cluster = clusters.get(cue["cue"])
        if cluster is None:
            items.append({
                "cue": cue["cue"],
                "speaker": f"unknown_{cue['cue']}",
                "merge_with_previous": False,
                "confidence": 0.0,
                "reason": "No diarization coverage for this cue",
            })
            previous_cluster = None
            continue
        name, reason = names[int(cluster)]
        items.append({
            "cue": cue["cue"],
            "speaker": name,
            # Only an intent hint; _8_1_audio_task re-decides using speaker + gap.
            "merge_with_previous": cluster == previous_cluster,
            "confidence": 1.0,
            "reason": reason,
            "speaker_cluster": int(cluster),
        })
        previous_cluster = cluster
    return items


def _tag_from_text(cues):
    """Fallback when no diarization is available: infer speakers from text alone."""
    expected_cues = [cue["cue"] for cue in cues]

    def validate(response):
        return _validate_response(response, expected_cues)

    response = ask_gpt(
        _build_prompt(cues),
        resp_type="json",
        valid_def=validate,
        log_title="speaker_tagging",
    )
    return [
        {
            "cue": item["cue"],
            "speaker": item["speaker"].strip(),
            "merge_with_previous": item["merge_with_previous"],
            "confidence": float(item["confidence"]),
            "reason": str(item.get("reason", "")).strip(),
        }
        for item in response["items"]
    ]


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

    clusters = _cue_cluster_ids(cues, _load_acoustic_words())
    if clusters:
        items = _tag_from_clusters(cues, clusters)
    else:
        rprint("[yellow]⚠️ No diarization data, falling back to text-only speaker guessing[/yellow]")
        items = _tag_from_text(cues)

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
