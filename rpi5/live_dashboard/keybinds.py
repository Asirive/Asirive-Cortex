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
    COPY_LOGS = "copy_logs"
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
    # M40 fix: each panel jump key now has its own action so the
    # consumer can dispatch without inspecting the raw key string.
    # Use `panel_index_for(action)` to recover the 1..7 number.
    FOCUS_PANEL_1 = "focus_panel_1"
    FOCUS_PANEL_2 = "focus_panel_2"
    FOCUS_PANEL_3 = "focus_panel_3"
    FOCUS_PANEL_4 = "focus_panel_4"
    FOCUS_PANEL_5 = "focus_panel_5"
    FOCUS_PANEL_6 = "focus_panel_6"
    FOCUS_PANEL_7 = "focus_panel_7"


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
    "k":         KeyAction.COPY_LOGS,
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
    # === FULL mode: panel jump keys (1..7) — M40 fix ===
    "1": KeyAction.FOCUS_PANEL_1,
    "2": KeyAction.FOCUS_PANEL_2,
    "3": KeyAction.FOCUS_PANEL_3,
    "4": KeyAction.FOCUS_PANEL_4,
    "5": KeyAction.FOCUS_PANEL_5,
    "6": KeyAction.FOCUS_PANEL_6,
    "7": KeyAction.FOCUS_PANEL_7,
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
    KeyAction.FOCUS_PANEL_1,
    KeyAction.FOCUS_PANEL_2,
    KeyAction.FOCUS_PANEL_3,
    KeyAction.FOCUS_PANEL_4,
    KeyAction.FOCUS_PANEL_5,
    KeyAction.FOCUS_PANEL_6,
    KeyAction.FOCUS_PANEL_7,
}


# Map: FOCUS_PANEL_N -> N (1..7). Use this when dispatching the focus.
_FOCUS_PANEL_INDEX: Dict[KeyAction, int] = {
    KeyAction.FOCUS_PANEL_1: 1,
    KeyAction.FOCUS_PANEL_2: 2,
    KeyAction.FOCUS_PANEL_3: 3,
    KeyAction.FOCUS_PANEL_4: 4,
    KeyAction.FOCUS_PANEL_5: 5,
    KeyAction.FOCUS_PANEL_6: 6,
    KeyAction.FOCUS_PANEL_7: 7,
}


def panel_index_for(action: KeyAction) -> int | None:
    """Return the 1..7 panel index for a FOCUS_PANEL_N action, else None."""
    return _FOCUS_PANEL_INDEX.get(action)


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
    ("k", "copy"),
    ("?", "help"),
]

FOOTER_HINTS_FULL = FOOTER_HINTS + [
    ("p", "pause"),
]
