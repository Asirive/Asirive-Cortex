"""
Latency Benchmark

Measure end-to-end inference latency for CPU (ONNX) and Hailo (HEF) backends.

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import logging
import time
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)


class LatencyBenchmark:
    """
    Benchmark inference latency over N warm-up + M measured runs.
    """

    def __init__(self, warmup_runs: int = 10, measure_runs: int = 100):
        self.warmup_runs = warmup_runs
        self.measure_runs = measure_runs

    def benchmark_onnx(
        self,
        session,
        video: np.ndarray,
        audio: np.ndarray,
        tokens: np.ndarray,
        conv_state: np.ndarray,
        ssm_state: np.ndarray,
    ) -> Dict[str, float]:
        """Benchmark ONNXRuntime inference."""
        inputs = {
            "video": video,
            "audio": audio,
            "tokens": tokens,
            "conv_state": conv_state,
            "ssm_state": ssm_state,
        }

        # Warmup
        for _ in range(self.warmup_runs):
            session.run(None, inputs)

        # Measure
        times = []
        for _ in range(self.measure_runs):
            t0 = time.perf_counter()
            session.run(None, inputs)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)  # ms

        result = {
            "mean_ms": float(np.mean(times)),
            "p50_ms": float(np.median(times)),
            "p99_ms": float(np.percentile(times, 99)),
            "min_ms": float(np.min(times)),
            "max_ms": float(np.max(times)),
        }
        logger.info(f"ONNX latency: {result}")
        return result

    def benchmark_hailo(
        self,
        infer_model,
        video: np.ndarray,
        audio: np.ndarray,
        tokens: np.ndarray,
        conv_state: np.ndarray,
        ssm_state: np.ndarray,
    ) -> Dict[str, float]:
        """Benchmark Hailo NPU inference."""
        # TODO: implement with hailo_platform API
        logger.warning("Hailo benchmark not yet implemented.")
        return {}
