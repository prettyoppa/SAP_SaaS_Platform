#!/usr/bin/env python3
"""Extract ko/en pairs from app/static/js/i18n.js → docs/i18n_glossary.tsv (UTF-8, tab-separated)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_PATH = ROOT / "app" / "static" / "js" / "i18n.js"
OUT_PATH = ROOT / "docs" / "i18n_glossary.tsv"


def extract_block(text: str, label: str) -> str | None:
    m = re.search(rf"\b{label}\s*:\s*\{{", text)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
        i += 1
    return None


def parse_pairs(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    # "key": "value" with escapes
    for km in re.finditer(r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', block):
        key = km.group(1)
        val = km.group(2).replace("\\n", "\n").replace('\\"', '"')
        out[key] = val
    return out


def main() -> int:
    text = I18N_PATH.read_text(encoding="utf-8")
    en_block = extract_block(text, "en")
    ko_block = extract_block(text, "ko")
    if not en_block or not ko_block:
        print("Could not find en/ko blocks", file=sys.stderr)
        return 1
    en = parse_pairs(en_block)
    ko = parse_pairs(ko_block)
    keys = sorted(set(en) | set(ko))

    def esc_cell(s: str) -> str:
        return s.replace("\t", " ").replace("\r", "").replace("\n", "⏎")

    lines = ["key\tko\ten"]
    for k in keys:
        lines.append(f"{k}\t{esc_cell(ko.get(k, ''))}\t{esc_cell(en.get(k, ''))}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(keys)} keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
