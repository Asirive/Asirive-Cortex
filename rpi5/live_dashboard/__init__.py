"""Asirive Cortex live dashboard.

Two UI modes over the same CortexSystem:
  - FULL (default): Textual-based TUI with 8 panels, sparklines, animations.
  - 2.4 (`--2.4` flag): plain-print UI for slow SSH / 2.4 GHz WiFi.

Both share the same data layer (state, log_watcher, keybinds).
"""
__version__ = "0.1.0"
