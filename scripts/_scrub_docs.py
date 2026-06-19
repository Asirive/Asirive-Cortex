"""One-shot doc scrubber — replace hardcoded API keys in docs/*.md with placeholders."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPLACEMENTS = [
    # Gemini
    ("<REDACTED-GEMINI-KEY>", "<REDACTED-GEMINI-KEY>"),
    # Supabase publishable
    ("<REDACTED-SUPABASE-PUBLISHABLE>", "<REDACTED-SUPABASE-PUBLISHABLE>"),
]

# Files to scrub (all under docs/)
TARGETS = [
    "docs/implementation/FULL-IMPLEMENTATION-PLAN.md",
    "docs/implementation/WEEK-1-COMPLETE.md",
    "docs/implementation/WEEK-2-COMPLETE.md",
    "docs/implementation/gemini-tts-integration.md",
    "docs/testing/test-protocol.md",
]


def main() -> int:
    fixed = 0
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"  SKIP (missing): {rel}")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        original = text
        hits = 0
        for old, new in REPLACEMENTS:
            count = text.count(old)
            if count:
                text = text.replace(old, new)
                hits += count
        if text != original:
            p.write_text(text, encoding="utf-8")
            fixed += 1
            print(f"  FIXED ({hits} replacements): {rel}")
    print(f"\nScrubbed {fixed} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
