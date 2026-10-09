"""
Asirive Cortex — core package (the 5-layer AI brain + safety + voice pipeline)

Layers:
- core.layer0_guardian: Safety-Critical YOLO Detection
- core.layer1_learner: Adaptive YOLOE Detection
- core.layer2_thinker: Gemini Live API Conversational AI
- core.layer3_guide: Navigation and Transit
- core.layer4_memory: SQLite + Supabase Storage

Usage:
    from core import CortexSystem
    system = CortexSystem()
    system.start()

Exports are lazy (PEP 562) so light submodules (e.g. core.live_dashboard)
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
        from core.system import CortexSystem
        return CortexSystem
    if name in ("load_config", "get_config"):
        from core.config.config import get_config, load_config
        return {"load_config": load_config, "get_config": get_config}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
