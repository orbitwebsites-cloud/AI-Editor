"""AI service integrations with fallback logic.
- Groq (primary) + Cerebras (fallback) for text tasks
- Groq Whisper for transcription
- Pexels for stock B-roll search
"""
import json
import logging
import re
import httpx
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ---------- MODEL CONFIG ----------
GROQ_BASE = "https://api.groq.com/openai/v1"
CEREBRAS_BASE = "https://api.cerebras.ai/v1"

# Best models per task (Jan 2026)
WHISPER_MODEL = "whisper-large-v3-turbo"
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
GROQ_TEXT_MODEL_FALLBACK = "llama-3.1-8b-instant"
CEREBRAS_TEXT_MODEL = "gpt-oss-120b"
CEREBRAS_TEXT_MODEL_FALLBACK = "zai-glm-4.7"


# ---------- TRANSCRIPTION ----------
async def transcribe_audio(audio_path: str, groq_key: str) -> Dict[str, Any]:
    """Transcribe audio using Groq Whisper with word-level timestamps."""
    if not groq_key:
        raise RuntimeError("Groq API key required for transcription.")

    client = AsyncOpenAI(api_key=groq_key, base_url=GROQ_BASE, timeout=180.0)
    with open(audio_path, "rb") as f:
        resp = await client.audio.transcriptions.create(
            file=(audio_path.split("/")[-1], f, "audio/mpeg"),
            model=WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
    data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    return {
        "text": data.get("text", ""),
        "words": data.get("words", []) or [],
        "segments": data.get("segments", []) or [],
        "duration": data.get("duration", 0),
        "language": data.get("language", "en"),
    }


# ---------- TEXT LLM WITH FALLBACK ----------
async def _call_openai_compat(base_url: str, api_key: str, model: str,
                              messages: list, response_format: Optional[dict] = None) -> str:
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90.0)
    kwargs = {"model": model, "messages": messages, "temperature": 0.2}
    if response_format:
        kwargs["response_format"] = response_format
    res = await client.chat.completions.create(**kwargs)
    return res.choices[0].message.content or ""


async def call_text_llm(prompt: str, keys: dict, system: str = "",
                        want_json: bool = False) -> str:
    """Try Groq primary → Groq fallback → Cerebras primary → Cerebras fallback."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response_format = {"type": "json_object"} if want_json else None

    chain = [
        ("groq", GROQ_BASE, keys.get("groq"), GROQ_TEXT_MODEL),
        ("groq", GROQ_BASE, keys.get("groq"), GROQ_TEXT_MODEL_FALLBACK),
        ("cerebras", CEREBRAS_BASE, keys.get("cerebras"), CEREBRAS_TEXT_MODEL),
        ("cerebras", CEREBRAS_BASE, keys.get("cerebras"), CEREBRAS_TEXT_MODEL_FALLBACK),
    ]

    last_err = None
    for provider, base, key, model in chain:
        if not key:
            continue
        try:
            logger.info(f"LLM call → {provider}/{model}")
            out = await _call_openai_compat(base, key, model, messages, response_format)
            if out:
                return out
        except Exception as e:
            last_err = e
            logger.warning(f"{provider}/{model} failed: {e}")
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")


def _extract_json(text: str) -> Any:
    """Extract JSON from an LLM response that may have code fences or extra text."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    for pattern in [r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"]:
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                continue
    raise ValueError(f"Could not parse JSON from response: {text[:200]}")


# ---------- ANALYSIS ----------
async def analyze_transcript(words: List[Dict], keys: dict) -> Dict[str, Any]:
    """Ask LLM to identify filler segments, emphasis words, and B-roll opportunities."""
    max_words = min(len(words), 1200)
    lines = []
    for i, w in enumerate(words[:max_words]):
        txt = (w.get("word") or "").strip()
        if not txt:
            continue
        lines.append(f"{i}:{txt}")
    numbered = " ".join(lines)

    system = (
        "You are an expert video editor AI. You analyze podcast/vlog transcripts to "
        "produce editing decisions. You reply ONLY with valid JSON, no prose."
    )

    prompt = f"""Analyze this transcript. Each token is formatted `index:word`.

TRANSCRIPT:
{numbered}

Return a JSON object with these keys (use word indices from the transcript):
{{
  "filler_indices": [array of word indices that should be CUT - fillers like 'um','uh','ah','like','you know','so','basically','literally','right','okay' when used as fillers, stutters (repeated words), false-starts],
  "emphasis_indices": [array of word indices that should be visually emphasized (zoom-in/pop) - key words in punchlines, strong statements, hooks],
  "broll_moments": [
    {{"word_index": <int>, "query": "<2-4 word Pexels search query>", "reason": "<brief>"}}
  ],
  "title": "<catchy 3-8 word title for this clip>",
  "summary": "<1-sentence summary>"
}}

Rules:
- Be strict on fillers - only flag actual fillers, not meaningful words.
- Emphasis: 5-15 words max, spread evenly.
- B-roll: 3-8 moments max, pick concrete visual concepts only.
- Return ONLY the JSON. No markdown. No commentary.
"""
    raw = await call_text_llm(prompt, keys, system=system, want_json=True)
    parsed = _extract_json(raw)

    return {
        "filler_indices": [int(i) for i in parsed.get("filler_indices", []) if isinstance(i, (int, str)) and str(i).lstrip("-").isdigit()],
        "emphasis_indices": [int(i) for i in parsed.get("emphasis_indices", []) if isinstance(i, (int, str)) and str(i).lstrip("-").isdigit()],
        "broll_moments": [
            {
                "word_index": int(m.get("word_index", 0)),
                "query": str(m.get("query", ""))[:80],
                "reason": str(m.get("reason", ""))[:200],
            }
            for m in parsed.get("broll_moments", []) if isinstance(m, dict)
        ],
        "title": str(parsed.get("title", "Untitled Clip"))[:120],
        "summary": str(parsed.get("summary", ""))[:400],
    }


# ---------- PEXELS ----------
async def search_pexels_video(query: str, pexels_key: str, per_page: int = 4) -> List[Dict]:
    """Search Pexels for stock video clips."""
    if not pexels_key:
        return []
    headers = {"Authorization": pexels_key}
    url = "https://api.pexels.com/videos/search"
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            logger.warning(f"Pexels error {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
    results = []
    for v in data.get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: f.get("width", 0))
        picked = None
        for f in files:
            if f.get("width", 0) >= 640 and f.get("file_type") == "video/mp4":
                picked = f
                break
        if not picked and files:
            picked = files[len(files) // 2]
        if not picked:
            continue
        results.append({
            "id": v.get("id"),
            "duration": v.get("duration"),
            "thumbnail": v.get("image"),
            "video_url": picked.get("link"),
            "width": picked.get("width"),
            "height": picked.get("height"),
            "user": (v.get("user") or {}).get("name", ""),
        })
    return results


# ---------- CONNECTION TESTS ----------
async def test_groq(api_key: str) -> Dict[str, Any]:
    if not api_key:
        return {"ok": False, "error": "No key"}
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE, timeout=20)
        r = await client.chat.completions.create(
            model=GROQ_TEXT_MODEL_FALLBACK,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return {"ok": True, "model": r.model}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def test_cerebras(api_key: str) -> Dict[str, Any]:
    if not api_key:
        return {"ok": False, "error": "No key"}
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=CEREBRAS_BASE, timeout=20)
        r = await client.chat.completions.create(
            model=CEREBRAS_TEXT_MODEL_FALLBACK,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return {"ok": True, "model": r.model}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def test_pexels(api_key: str) -> Dict[str, Any]:
    if not api_key:
        return {"ok": False, "error": "No key"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": api_key},
                params={"query": "city", "per_page": 1},
            )
        if r.status_code == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
