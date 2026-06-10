"""
Keybind registry for the live dashboard.

Single source of truth for which keys do what. Both the 2.4 mode and the
FULL mode read from the same registry. The Textual bindings and the
print-mode key reads both go through `resolve_key()` so behavior is
identical across modes.

Why this exists:
  - The OLD system had only one terminal keybind (`b` for recording).
    We carry that forward.
  - The new system has ~12 keybinds. Keeping them in one place makes
    it easy to add/remove and to render the footer hint consistently.
  - Some keys are FULL-mode-only (e.g. Tab, `1`–`7` for panel focus).
    `is_full_only()` lets a caller no-op gracefully.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Set


class KeyAction(str, Enum):
    """All possible key actions, shared by both UI modes.

    The string value is what callers dispatch on; the enum gives us
    IDE autocomplete and a single point of extension.
    """

    # Universal (work in BOTH 2.4 and FULL modes)
    QUIT = "quit"
    MUTE_TTS = "mute_tts"
    TOGGLE_RECORDING = "toggle_recording"     # preserved from old `b` keybind
    ASK_CORTEX = "ask_cortex"
    SAVE_LOG = "save_log"
    HELP = "help"
    PAUSE = "pause"

    # FULL mode only (Textual UI)
    TOGGLE_LOG_FOLLOW = "toggle_log_follow"
    CYCLE_LOG_LEVEL = "cycle_log_level"
    EXPAND_LOG = "expand_log"
    CYCLE_FOCUS = "cycle_focus"
    TOGGLE_DENSITY = "toggle_density"
    SPARKLINE_WINDOW_UP = "sparkline_window_up"
    SPARKLINE_WINDOW_DOWN = "sparkline_window_down"
    FOCUS_PANEL = "focus_panel"                # with arg: 1..7


# Map: canonical key string -> KeyAction
# Canonical form: lowercase for letters, 'ctrl+x' for control combos,
# 'f1'..'f12' for function keys, 'tab' / 'enter' / 'esc' / 'space'.
KEYBIND_MAP: Dict[str, KeyAction] = {
    # === Universal ===
    "q":         KeyAction.QUIT,
    "ctrl+c":   KeyAction.QUIT,
    "m":         KeyAction.MUTE_TTS,
    "b":         KeyAction.TOGGLE_RECORDING,   # old keybind, preserved
    "r":         KeyAction.ASK_CORTEX,
    "s":         KeyAction.SAVE_LOG,
    "?":         KeyAction.HELP,
    "f1":        KeyAction.HELP,
    "p":         KeyAction.PAUSE,
    # === FULL mode (Textual) ===
    "f":         KeyAction.TOGGLE_LOG_FOLLOW,
    "l":         KeyAction.CYCLE_LOG_LEVEL,
    "e":         KeyAction.EXPAND_LOG,
    "tab":       KeyAction.CYCLE_FOCUS,
    "shift+tab": KeyAction.CYCLE_FOCUS,        # reverse direction
    "[":         KeyAction.TOGGLE_DENSITY,      # or "decrease density" later
    "]":         KeyAction.TOGGLE_DENSITY,      # or "increase density" later
    "+":         KeyAction.SPARKLINE_WINDOW_UP,
    "=":         KeyAction.SPARKLINE_WINDOW_UP,  # shift+= on US keyboard
    "-":         KeyAction.SPARKLINE_WINDOW_DOWN,
    "_":         KeyAction.SPARKLINE_WINDOW_DOWN, # shift+- on US keyboard
    "g":         KeyAction.ASK_CORTEX,         # alias for `r`
    # === FULL mode: panel jump keys (1..7) ===
    "1": KeyAction.FOCUS_PANEL,
    "2": KeyAction.FOCUS_PANEL,
    "3": KeyAction.FOCUS_PANEL,
    "4": KeyAction.FOCUS_PANEL,
    "5": KeyAction.FOCUS_PANEL,
    "6": KeyAction.FOCUS_PANEL,
    "7": KeyAction.FOCUS_PANEL,
}


# Keybinds that only work in FULL (Textual) mode
FULL_ONLY: Set[KeyAction] = {
    KeyAction.TOGGLE_LOG_FOLLOW,
    KeyAction.CYCLE_LOG_LEVEL,
    KeyAction.EXPAND_LOG,
    KeyAction.CYCLE_FOCUS,
    KeyAction.TOGGLE_DENSITY,
    KeyAction.SPARKLINE_WINDOW_UP,
    KeyAction.SPARKLINE_WINDOW_DOWN,
    KeyAction.FOCUS_PANEL,
}


def resolve_key(key: str) -> KeyAction | None:
    """Map a key string to its KeyAction. Returns None for unbound keys.

    Accepts:
      - single character: "q", "Q", "?", "/"
      - ctrl combos: "ctrl+c"
      - function keys: "f1".."f12"
      - special: "tab", "enter", "esc", "space", "backspace"
    Case is normalized to lowercase for letters.
    """
    if not key:
        return None
    k = key.lower()
    return KEYBIND_MAP.get(k)


def is_full_only(action: KeyAction) -> bool:
    return action in FULL_ONLY


# Human-readable hint for the footer / help overlay
FOOTER_HINTS = [
    ("q", "quit"),
    ("b", "rec"),
    ("m", "mute"),
    ("r", "ask"),
    ("s", "save"),
    ("?", "help"),
]

FOOTER_HINTS_FULL = FOOTER_HINTS + [
    ("p", "pause"),
    ("f", "follow"),
    ("L", "level"),
    ("Tab", "focus"),
    ("1-7", "panel"),
]
