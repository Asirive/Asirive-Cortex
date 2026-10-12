"""
Tool Calling F1 Evaluation

Measure how accurately the local model replicates Gemini's tool calls
(navigation, bus, memory recall, etc.).

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
from typing import Dict, List

import torch

logger = logging.getLogger(__name__)

# Mapping from tool name to index (must match training)
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


class ToolF1Evaluator:
    """
    Compute precision, recall, and F1 for tool call predictions.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.tp = {name: 0 for name in TOOL_NAMES}
        self.fp = {name: 0 for name in TOOL_NAMES}
        self.fn = {name: 0 for name in TOOL_NAMES}

    def update(
        self,
        pred_tool: str,
        true_tool: str,
    ):
        """Compare a single prediction vs ground truth."""
        if pred_tool == true_tool and pred_tool in self.tp:
            self.tp[pred_tool] += 1
        elif pred_tool in self.fp:
            self.fp[pred_tool] += 1
            if true_tool in self.fn:
                self.fn[true_tool] += 1

    def compute(self) -> Dict[str, float]:
        """Compute macro F1 across all tools."""
        precisions = []
        recalls = []
        f1s = []
        for name in TOOL_NAMES:
            tp = self.tp[name]
            fp = self.fp[name]
            fn = self.fn[name]
            p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
            precisions.append(p)
            recalls.append(r)
            f1s.append(f1)

        macro = {
            "precision": sum(precisions) / len(precisions),
            "recall": sum(recalls) / len(recalls),
            "f1": sum(f1s) / len(f1s),
        }
        logger.info(f"Tool F1: {macro}")
        return macro
