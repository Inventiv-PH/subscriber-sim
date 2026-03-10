#!/usr/bin/env python3
"""Audit training data for archetype label mismatches.

Loads each per-archetype JSONL file, re-classifies every session using
the same heuristic classifier from parse_chats.py, and flags sessions
where the file label disagrees with the re-classification.

Output: data/audit_report.jsonl — one line per flagged session.

Usage:
    python scripts/audit_data.py
"""

import json
import sys
from pathlib import Path

# Allow importing parse_chats from the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_chats import classify_archetype

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ARCHETYPE_FILES = [
    "horny.jsonl", "cheapskate.jsonl", "casual.jsonl",
    "troll.jsonl", "whale.jsonl", "cold.jsonl", "simp.jsonl",
]

# Cross-archetype keyword checks — strong signals that a session belongs
# to a *different* archetype than what the file says.
_CROSS_SIGNALS = {
    "troll":  {
        "simp":  r"(?i)(i love you|miss you|you're perfect|beautiful|gorgeous|🥰|❤️|💕)",
        "horny": r"(?i)(i'm so hard|send nudes|cum for|fuck me|🍆|💦)",
        "casual": r"(?i)(how's your day|how are you doing|tell me about yourself)",
    },
    "cold":   {
        "simp":  r"(?i)(i love you|you're beautiful|gorgeous|❤️|💕)",
        "horny": r"(?i)(send nudes|fuck|cum|🍆|💦)",
    },
    "casual": {
        "horny": r"(?i)(i'm so hard|send nudes|cum for|fuck me|suck|🍆|💦)",
        "simp":  r"(?i)(i love you|you're perfect|think about you all the time)",
    },
}


def audit():
    import re

    report = []
    totals = {"checked": 0, "flagged": 0}

    for fname in ARCHETYPE_FILES:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            print(f"⚠️  Skipping {fname} — not found")
            continue

        file_archetype = fname.replace(".jsonl", "")
        sessions = [json.loads(line) for line in fpath.read_text().splitlines() if line.strip()]

        for session in sessions:
            totals["checked"] += 1
            messages = session.get("messages", [])
            session_id = session.get("session_id", "unknown")
            source = session.get("source_file", "unknown")
            confidence = session.get("source_confidence", "unknown")

            # Re-classify using the same heuristic
            suggested = classify_archetype(messages)
            label_mismatch = suggested != file_archetype

            # Check for strong cross-archetype signals in subscriber messages
            sub_msgs = " ".join(
                m["content"] for m in messages if m["role"] == "assistant"
            )
            cross_flags = []
            for other_arch, pattern in _CROSS_SIGNALS.get(file_archetype, {}).items():
                if re.search(pattern, sub_msgs):
                    cross_flags.append(other_arch)

            if not label_mismatch and not cross_flags:
                continue

            # Extract sample subscriber messages for manual review
            samples = [
                m["content"][:120]
                for m in messages
                if m["role"] == "assistant"
            ][:3]

            entry = {
                "session_id": session_id,
                "source_file": source,
                "source_confidence": confidence,
                "current_label": file_archetype,
                "suggested_label": suggested,
                "label_mismatch": label_mismatch,
                "cross_archetype_signals": cross_flags,
                "sample_messages": samples,
            }
            report.append(entry)
            totals["flagged"] += 1

    # Write report
    out_path = DATA_DIR / "audit_report.jsonl"
    with open(out_path, "w") as f:
        for entry in report:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Audit complete: {totals['checked']} sessions checked, {totals['flagged']} flagged")
    print(f"Report written to {out_path}")

    # Summary by archetype
    from collections import Counter
    mismatches = Counter(
        (e["current_label"], e["suggested_label"])
        for e in report if e["label_mismatch"]
    )
    if mismatches:
        print(f"\nTop label mismatches:")
        for (curr, sugg), count in mismatches.most_common(15):
            print(f"  {curr} → {sugg}: {count}")

    cross_counts = Counter(
        (e["current_label"], sig)
        for e in report
        for sig in e["cross_archetype_signals"]
    )
    if cross_counts:
        print(f"\nCross-archetype signal detections:")
        for (curr, sig), count in cross_counts.most_common(15):
            print(f"  {curr} contains {sig} signals: {count}")


if __name__ == "__main__":
    audit()
