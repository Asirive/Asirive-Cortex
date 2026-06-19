#!/usr/bin/env python3
"""
Scan the working tree for hardcoded secrets. Exit non-zero if any are found.

Patterns detected (all configured via env to keep them up to date without
touching code):
  - SSH password  : the historic 'REDACTED-RPI-PASSWORD' (also covers variants)
  - API keys      : AIzaSy[20+], sk-[A-Za-z0-9]{20+}, sk_car_[A-Za-z0-9]+
  - Bearer token  : sb_publishable_[A-Za-z0-9_]+

Usage:
    python scripts/check_no_secrets.py              # scan entire tree
    python scripts/check_no_secrets.py --staged     # only staged (for pre-commit)

Allowlist:
    .env (gitignored anyway, but never scanned)
    .env.template (placeholders like 'your_xxx_here' are OK)
    .claude/, .opencode/, .agent/, .agents/  (local agent state)
    Version_1/  (legacy archive, frozen on purpose)
    docs/       (docs may mention keys in passing — review flag)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns that should NEVER appear in tracked source.
PATTERNS = [
    ("hardcoded ssh password", re.compile(r"REDACTED-RPI-PASSWORD")),
    ("gemini key (AIzaSy...)", re.compile(r"AIzaSy[A-Za-z0-9_-]{20,}")),
    ("openai key (sk-...)",     re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("cartesia key (sk_car_)",  re.compile(r"sk_car_[A-Za-z0-9]{10,}")),
    ("supabase publishable",    re.compile(r"sb_publishable_[A-Za-z0-9_]{10,}")),
]

# Files that may legitimately contain these patterns.
ALLOWLIST = {
    ".env",  # gitignored, just to be safe
    ".env.template",  # placeholders
    "AGENTS.md",  # personal handoff, gitignored anyway
    "ContextHistory.md",  # personal handoff
    "scripts/check_no_secrets.py",  # self
}

# Directory prefixes to skip entirely.
SKIP_DIRS = (
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    "node_modules",
    "models",  # large model weights
    "memory_storage",
    "memory_images",
    "tts_recordings",
    "recordings",
    "outputs",
    "runs",
    "logs",
    "Version_1",  # legacy archive (frozen on purpose)
    ".claude",  # local Claude Code state (deny-rules may reference the password)
    ".opencode",  # local OpenCode state
    ".agent",  # local agent state
    ".agents",  # local agent state
)

# File extensions to scan.
EXTS = {
    ".py", ".sh", ".md", ".txt", ".yml", ".yaml", ".json", ".toml",
    ".cfg", ".ini", ".env", ".ts", ".js", ".tsx", ".jsx",
}


def is_tracked(path: Path) -> bool:
    """True if path is tracked by git (used to skip untracked + large ignored dirs)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True,
        )
        return out.returncode == 0
    except Exception:
        return False


def collect_files(staged_only: bool) -> list[Path]:
    if staged_only:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return [ROOT / line for line in out.stdout.splitlines() if line.strip()]
    # Scan the whole tree (tracked only — untracked ignored dirs are not in
    # the scan target by design).
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ROOT / line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    staged = "--staged" in sys.argv
    files = collect_files(staged)
    findings: list[tuple[Path, str, str]] = []
    for p in files:
        # Skip allowlist
        if p.name in ALLOWLIST or any(part in ALLOWLIST for part in p.parts):
            continue
        # Skip skip-dirs
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        # Skip non-target extensions
        if p.suffix.lower() not in EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for label, pat in PATTERNS:
            for m in pat.finditer(text):
                # Compute line number
                line_no = text.count("\n", 0, m.start()) + 1
                findings.append((p, label, f"line {line_no}: {m.group(0)[:40]}…"))

    if not findings:
        print(f"[OK] No hardcoded secrets found ({len(files)} files scanned).")
        return 0

    print(f"[FAIL] Found {len(findings)} potential secret(s):")
    for path, label, detail in findings:
        rel = path.relative_to(ROOT) if path.is_absolute() else path
        print(f"  - {rel}: {label} — {detail}")
    print(
        "\nFix: move the secret to .env (gitignored) and load via "
        "`scripts/_rpi_ssh.py` for SSH, or via `os.environ` / `python-dotenv` "
        "for API keys."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
