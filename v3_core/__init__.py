"""
Asirive Cortex — core package (the 5-layer AI brain + safety + voice pipeline)

Layers:
- v3_core.layer0_guardian: Safety-Critical YOLO Detection
- v3_core.layer1_learner: Adaptive YOLOE Detection
- v3_core.layer2_thinker: Gemini Live API Conversational AI
- v3_core.layer3_guide: Navigation and Transit
- v3_core.layer4_memory: SQLite + Supabase Storage

Usage:
    from v3_core import CortexSystem
    system = CortexSystem()
    system.start()

Exports are lazy (PEP 562) so light submodules (e.g. v3_core.live_dashboard)
can be imported without pulling in cv2/torch and the full system graph.

Author: Haziq (@IRSPlays)
"""

__version__ = "2.0.0"
__author__ = "Haziq (@IRSPlays)"

__all__ = [
    "CortexSystem",
    "load_config",
    "get_config",
    "__version__",
    "__author__",
]


def __getattr__(name):
    if name == "CortexSystem":
        from v3_core.system import CortexSystem
        return CortexSystem
    if name in ("load_config", "get_config"):
        from v3_core.config.config import get_config, load_config
        return {"load_config": load_config, "get_config": get_config}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
