import logging
import os
import re
from collections.abc import Generator

from archetypes import (
    ARCHETYPES,
    _SUBSCRIBER_SYSTEMS,
    get_archetype_mid_convo_reminder,
)

# ── Logging ────────────────────────────────────────────────────────────────────
log = logging.getLogger("subscriber_sim")
if not log.handlers:
    _h = logging.StreamHandler()  # stdout → Docker logs
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    log.addHandler(_h)
    log.setLevel(logging.DEBUG if os.getenv("DEBUG") else logging.INFO)

# ── Backend ────────────────────────────────────────────────────────────────────
# All inference runs on Modal GPU (jasmin-inference app).

# Generation params — defaults (overridden per-archetype below)
_DEFAULT_PARAMS = dict(
    max_tokens=100,
    temperature=0.75,
    top_p=0.85,
    rep_pen=1.05,
    stop=["\n\nJasmin:", "\n\nUser:", "\n\n["],
)

# Per-archetype generation params from subscriber_sim_v2.ipynb
# Tighter params = more consistent archetype adherence
_ARCHETYPE_PARAMS = {
    "horny":      dict(max_tokens=80,  temperature=0.75, top_p=0.85, rep_pen=1.05),
    "cheapskate": dict(max_tokens=100, temperature=0.70, top_p=0.80, rep_pen=1.00),
    "casual":     dict(max_tokens=75,  temperature=0.65, top_p=0.80, rep_pen=1.00),
    "troll":      dict(max_tokens=85,  temperature=0.80, top_p=0.90, rep_pen=1.15),
    "whale":      dict(max_tokens=90,  temperature=0.65, top_p=0.75, rep_pen=1.05),
    "cold":       dict(max_tokens=15,  temperature=0.60, top_p=0.70, rep_pen=1.00),
    "simp":       dict(max_tokens=95,  temperature=0.75, top_p=0.85, rep_pen=1.00),
}

# Keep last 6 messages (3 full exchanges) — matches subscriber_sim_v2 context window
_MAX_HISTORY_TURNS = 6

# ── Response post-processor ────────────────────────────────────────────────────
# Removes OOC (out-of-character) artifacts — mirrors ResponseFilter from v2 notebook.

_META_PATTERNS = [
    r"(?:I'm|I am) (?:an|a) (?:AI|bot|model|language model|assistant)",
    r"(?:As an|As a) (?:AI|bot|model|language model|assistant)",
    r"I (?:should|shouldn't|need to|must|cannot|can't) ",
    r"I (?:can't|cannot) (?:roleplay|pretend)",
    r"^(?:I understand|I realize|I appreciate that)",
    r"^(?:Let me|I'll|I would) roleplay",
    r"I (?:must )?(?:maintain|keep) (?:appropriate|professional)",
]

_MAX_SENTENCES = {
    "horny": 3, "cheapskate": 3, "casual": 3,
    "troll": 2, "whale": 2,     "simp": 4, "cold": 1,
}


def _filter_response(text: str, archetype_key: str) -> str:
    """Post-process model output to strip OOC content and enforce length."""
    if not text or not text.strip():
        return text
    out = text.strip()
    # Strip hallucinated subscriber name prefixes (e.g. "JO ", "Da ", "BP ")
    out = re.sub(r"^[A-Z][A-Za-z]{0,2}\s+(?=[A-Z])", "", out)
    for pat in _META_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    out = out.strip()
    # Strip surrounding quotes
    if (out.startswith('"') and out.endswith('"')) or \
       (out.startswith("'") and out.endswith("'")):
        out = out[1:-1].strip()
    # Enforce max sentence count
    max_s = _MAX_SENTENCES.get(archetype_key, 3)
    sentences = [s.strip() for s in out.split(". ") if s.strip()]
    if len(sentences) > max_s:
        out = ". ".join(sentences[:max_s])
        if not out[-1] in ".!?":
            out += "."
    # Reduce excessive punctuation
    out = re.sub(r"([!?.♥💦🔥])\1{2,}", r"\1\1", out)
    out = re.sub(r"\.\.\.+", "..", out)
    # Strip leading action asterisks
    out = re.sub(r"^\*+\s*", "", out)
    return out.strip() or text.strip()

_health_cache: dict = {}


def _params(archetype_key: str) -> dict:
    return {**_DEFAULT_PARAMS, **_ARCHETYPE_PARAMS.get(archetype_key, {})}


def _trim_history(history: list[dict]) -> list[dict]:
    """Keep the last _MAX_HISTORY_TURNS message pairs to cap prompt tokens."""
    max_msgs = _MAX_HISTORY_TURNS * 2
    return history[-max_msgs:] if len(history) > max_msgs else history


def _normalize_history(history: list[dict]) -> list[dict]:
    """Trim history to cap prompt tokens.

    Training data allows assistant-first sequences (opener is always the first
    assistant turn with no preceding user message). Llama-3 chat template handles
    this natively — no seed injection needed.
    """
    return list(_trim_history(history))



# ── Modal backend ─────────────────────────────────────────────────────────────
def _get_modal_model():
    import modal
    cls = modal.Cls.from_name("jasmin-inference", "JasminModel")
    return cls()


def _inject_mid_convo_reminder(chat: list[dict], archetype_key: str) -> list[dict]:
    """Append an archetype reminder to the last user message after 3+ exchanges."""
    if len(chat) < _MAX_HISTORY_TURNS:
        log.debug("mid-convo reminder skipped (%d msgs < %d threshold)", len(chat), _MAX_HISTORY_TURNS)
        return chat
    reminder = get_archetype_mid_convo_reminder(archetype_key)
    if not reminder:
        return chat
    # Find last user message and append reminder at maximum recency
    for i in range(len(chat) - 1, -1, -1):
        if chat[i]["role"] == "user":
            chat[i] = {**chat[i], "content": chat[i]["content"] + "\n\n" + reminder}
            log.info("injected mid-convo reminder for [%s] at msg index %d", archetype_key, i)
            break
    return chat


def _stream_modal(history: list[dict], archetype_key: str) -> Generator[str, None, None]:
    log.info("── stream_modal [%s] ── history: %d msgs", archetype_key, len(history))
    try:
        model = _get_modal_model()
        normalized = _normalize_history(history)
        chat = [{"role": m["role"], "content": m["content"]} for m in normalized]
        chat = _inject_mid_convo_reminder(chat, archetype_key)
        system = _SUBSCRIBER_SYSTEMS.get(archetype_key, _SUBSCRIBER_SYSTEMS["casual"])
        messages = [{"role": "system", "content": system}] + chat
        p = _params(archetype_key)
        log.info("system prompt: %d chars | msgs to model: %d", len(system), len(messages))
        log.info("params: max_tokens=%s temp=%.2f top_p=%.2f rep_pen=%.2f",
                 p["max_tokens"], p["temperature"], p["top_p"], p["rep_pen"])
        log.debug("last user msg: %.200s", chat[-1]["content"] if chat else "(empty)")
        for token in model.generate.remote_gen(
            messages,
            stop=p["stop"],
            max_tokens=p["max_tokens"],
            temperature=p["temperature"],
            top_p=p["top_p"],
            rep_pen=p["rep_pen"],
        ):
            yield token
    except Exception as e:
        log.error("Modal error: %s", e, exc_info=True)
        yield f"⚠️ Modal error: {e}"


# ── Public API ────────────────────────────────────────────────────────────────
def _static_opener(archetype_key: str) -> str:
    """Return the static opener for the archetype — matches training data."""
    return ARCHETYPES[archetype_key]["opener"]


def stream_opener(archetype_key: str) -> Generator[str, None, None]:
    """Yield the static opener for the archetype.

    Training sessions always started with a fixed opener (no preceding Jasmin
    message). Using the static opener ensures inference starts in the exact same
    distribution as training data.
    """
    opener = _static_opener(archetype_key)
    log.info("── stream_opener [%s] ── static opener: %.80s", archetype_key, opener)
    yield opener


def generate_opener(archetype_key: str) -> str:
    """Return the static opener for the archetype.

    Training data always used fixed openers — dynamic generation introduced
    a distribution mismatch. Static openers are always in-character and instant.
    """
    return ARCHETYPES[archetype_key]["opener"]


def health_check() -> bool:
    """Check Modal backend health. Result is cached for 60s to avoid per-render overhead."""
    import time
    cached = _health_cache.get("modal")
    if cached and time.time() - cached["ts"] < 60:
        return cached["ok"]
    try:
        import modal
        modal.Cls.from_name("jasmin-inference", "JasminModel")
        result = True
    except Exception:
        result = False
    _health_cache["modal"] = {"ok": result, "ts": time.time()}
    return result


def stream_response(history: list[dict], archetype_key: str) -> Generator[str, None, None]:
    """Stream subscriber response tokens, then apply OOC post-processing on the full text."""
    stream = _stream_modal(history, archetype_key)

    # Collect full response then yield filtered text as one chunk.
    # Filtering operates on the complete output — can't filter mid-stream.
    full = "".join(stream)
    log.info("raw model output (%d chars): %.120s", len(full), full)
    filtered = _filter_response(full, archetype_key)
    log.info("filtered response (%d chars): %.120s", len(filtered), filtered)
    yield filtered
