"""
Tool Adapter

Decodes tool call logits into structured JSON and invokes the existing
Cortex tool callback (shared with Gemini Live).

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Optional, Dict, Any

import numpy as np

logger = logging.getLogger(__name__)

# Must match the training/eval tool name ordering
TOOL_NAMES = [
    "get_navigation_state",
    "report_obstacle",
    "get_gps_accuracy",
    "get_bus_arrival",
    "start_outdoor_navigation",
    "get_directions",
    "start_navigation_with_route",
    "search_places",
    "get_nearby_bus_stops",
    "get_all_services_at_stop",
    "guide_indoor",
    "stop_navigation",
    "search_memory",
    "set_system_mode",
]

# Simple argument schemas for each tool (matches Gemini Live tool declarations)
TOOL_SCHEMAS: Dict[str, Dict] = {
    "get_navigation_state": {},
    "report_obstacle": {"obstacle_type": "string", "distance_m": "number"},
    "get_gps_accuracy": {},
    "get_bus_arrival": {"bus_stop_code": "string", "service_no": "string"},
    "start_outdoor_navigation": {"destination": "string"},
    "get_directions": {"origin": "string", "destination": "string"},
    "start_navigation_with_route": {"route": "object"},
    "search_places": {"query": "string"},
    "get_nearby_bus_stops": {},
    "get_all_services_at_stop": {"bus_stop_code": "string"},
    "guide_indoor": {"destination": "string"},
    "stop_navigation": {},
    "search_memory": {"query": "string"},
    "set_system_mode": {"mode": "string"},
}


class ToolAdapter:
    """
    Bridges local model tool predictions to existing Cortex tool infrastructure.
    """

    def __init__(self, tool_callback=None):
        self.tool_callback = tool_callback

    def decode(self, tool_logits: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Decode tool head logits into a tool call dict.

        Args:
            tool_logits: [num_tools] logits
        Returns:
            {"name": str, "arguments": dict} or None
        """
        tool_idx = int(np.argmax(tool_logits))
        if tool_idx < 0 or tool_idx >= len(TOOL_NAMES):
            return None
        name = TOOL_NAMES[tool_idx]
        # TODO: predict arguments from a secondary arg head or template-fill
        arguments = self._default_args(name)
        return {"name": name, "arguments": arguments}

    def invoke(self, tool_call: Dict[str, Any]) -> Any:
        """
        Invoke the tool via the shared callback.

        Args:
            tool_call: {"name": str, "arguments": dict}
        Returns:
            Tool result (any)
        """
        if self.tool_callback is None:
            logger.warning("No tool_callback registered.")
            return None
        try:
            result = self.tool_callback(tool_call)
            return result
        except Exception as e:
            logger.error(f"Tool invocation failed: {e}")
            return None

    def _default_args(self, name: str) -> Dict[str, Any]:
        """Return empty/default args for a tool."""
        schema = TOOL_SCHEMAS.get(name, {})
        return {k: "" for k in schema}
