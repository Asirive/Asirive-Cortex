#!/usr/bin/env python3
"""
Project Cortex v2.0 - Model Benchmarking Framework

Benchmark YOLO models across different formats (PyTorch, NCNN, ONNX, OpenVINO)
to validate 4-5x speedup claims and determine optimal models for Layers 0 & 1.

CRITICAL VALIDATION:
- YOLO11n-NCNN should achieve ~94ms (meets <100ms Layer 0 target!)
- YOLO11s-NCNN should achieve ~222ms (4.9x faster than PyTorch)
- YOLOE-11s-NCNN should achieve ~220ms (4.5x faster than PyTorch)

Usage:
    # Run all benchmarks
    python3 tests/benchmark_models.py --all
    
    # Run specific model
    python3 tests/benchmark_models.py --model yolo11n --format ncnn
    
    # Compare formats for a model
    python3 tests/benchmark_models.py --compare yolo11n
    
    # Export results
    python3 tests/benchmark_models.py --export results.json

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: December 31, 2025
"""

import os
import sys
import time
import json
import platform
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

try:
    from ultralytics import YOLO
    from ultralytics import YOLOE
except ImportError:
    print("❌ Error: ultralytics not installed. Run: pip install --break-system-packages ultralytics")
    sys.exit(1)

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ===== MODELS TO BENCHMARK =====
BENCHMARK_MODELS = {
    # Layer 0: Guardian (Safety-Critical Detection)
    "yolo11n": {
        "path": "models/yolo11n.pt",
        "description": "YOLO11n - Fastest (target <100ms)",
        "layer": "Layer 0: Guardian",
        "target_ms": 100,
        "is_yoloe": False,
        "priority": "HIGH"
    },
    "yolo11s": {
        "path": "models/yolo11s.pt",
        "description": "YOLO11s - Balanced",
        "layer": "Layer 0: Guardian",
        "target_ms": 100,
        "is_yoloe": False,
        "priority": "MEDIUM"
    },
    "yolo11x": {
        "path": "models/yolo11x.pt",
        "description": "YOLO11x - Most Accurate (currently used)",
        "layer": "Layer 0: Guardian",
        "target_ms": 100,
        "is_yoloe": False,
        "priority": "LOW"
    },
    
    # Layer 1: Learner (Adaptive Context Detection)
    "yoloe-11s-seg": {
        "path": "models/yoloe-11s-seg.pt",
        "description": "YOLOE-11s Text/Visual Prompts",
        "layer": "Layer 1: Learner",
        "target_ms": 500,  # More lenient for Layer 1
        "is_yoloe": True,
        "priority": "HIGH"
    },
    "yoloe-11m-seg": {
        "path": "models/yoloe-11m-seg.pt",
        "description": "YOLOE-11m Text/Visual Prompts (more accurate)",
        "layer": "Layer 1: Learner",
        "target_ms": 500,
        "is_yoloe": True,
        "priority": "MEDIUM"
    },
}

# Expected benchmarks from Ultralytics (RPi 5, 640x640, FP32)
EXPECTED_RESULTS = {
    "yolo11n": {"pytorch": 388, "ncnn": 94, "openvino": 85},
    "yolo11s": {"pytorch": 1085, "ncnn": 222, "openvino": None},
    "yolo11x": {"pytorch": 1200, "ncnn": 280, "openvino": None},
    "yoloe-11s-seg": {"pytorch": 1000, "ncnn": 220, "openvino": None},
    "yoloe-11m-seg": {"pytorch": 1400, "ncnn": 310, "openvino": None},
}


class ModelBenchmark:
    """Benchmark a single model in a specific format."""
    
    def __init__(self, model_name: str, model_format: str, resolution=(640, 640), device='cpu'):
        self.model_name = model_name
        self.format = model_format  # 'pytorch', 'ncnn', 'onnx', 'openvino'
        self.resolution = resolution
        self.device = device
        self.model = None
        self.model_info = BENCHMARK_MODELS.get(model_name)
        
        if not self.model_info:
            raise ValueError(f"Unknown model: {model_name}")
        
        # Determine model path based on format
        base_path = self.model_info["path"]
        if model_format == "pytorch":
            self.model_path = base_path
        elif model_format == "ncnn":
            self.model_path = base_path.replace(".pt", "_ncnn_model")
        elif model_format == "onnx":
            self.model_path = base_path.replace(".pt", ".onnx")
        elif model_format == "openvino":
            self.model_path = base_path.replace(".pt", "_openvino_model")
        else:
            raise ValueError(f"Unknown format: {model_format}")
    
    def load_model(self):
        """Load model and measure load time."""
        if not os.path.exists(self.model_path):
            logger.error(f"Model not found: {self.model_path}")
            logger.info(f"    Run conversion script first: python3 convert_models_to_ncnn.py")
            return None
        
        logger.info(f"📦 Loading {self.format.upper()} model from {self.model_path}...")
        start = time.time()
        
        try:
            if self.model_info["is_yoloe"]:
                self.model = YOLOE(self.model_path)
            else:
                self.model = YOLO(self.model_path)
            
            load_time = time.time() - start
            logger.info(f"    Loaded in {load_time:.2f}s")
            return load_time
        except Exception as e:
            logger.error(f"❌ Error loading model: {e}")
            return None
    
    def benchmark(self, num_frames=100, warmup_frames=10):
        """Run inference benchmark."""
        results = {
            "model_name": self.model_name,
            "format": self.format,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "device": self.device,
            "load_time_s": 0,
            "avg_inference_ms": 0,
            "min_inference_ms": 0,
            "max_inference_ms": 0,
            "std_inference_ms": 0,
            "fps": 0,
            "memory_mb": 0,
            "target_ms": self.model_info["target_ms"],
            "meets_target": False,
            "speedup_vs_pytorch": None,
            "layer": self.model_info["layer"],
            "description": self.model_info["description"]
        }
        
        # Load model
        load_time = self.load_model()
        if load_time is None:
            return results
        
        results["load_time_s"] = load_time
        
        # Create dummy frame
        dummy_frame = np.random.randint(0, 255, (*self.resolution, 3), dtype=np.uint8)
        
        # Warm-up
        logger.info(f"🔥 Warming up ({warmup_frames} frames)...")
        for _ in range(warmup_frames):
            try:
                _ = self.model(dummy_frame, verbose=False)
            except Exception as e:
                logger.error(f"❌ Warmup failed: {e}")
                return results
        
        # Benchmark
        logger.info(f"⚡ Benchmarking ({num_frames} frames)...")
        latencies = []
        
        for i in range(num_frames):
            start = time.time()
            try:
                _ = self.model(dummy_frame, verbose=False)
                latency_ms = (time.time() - start) * 1000
                latencies.append(latency_ms)
                
                if (i + 1) % 25 == 0:
                    logger.info(f"    Progress: {i + 1}/{num_frames} frames")
            except Exception as e:
                logger.error(f"❌ Inference failed at frame {i}: {e}")
                break
        
        if not latencies:
            logger.error("❌ No successful inferences!")
            return results
        
        # Calculate statistics
        results["avg_inference_ms"] = np.mean(latencies)
        results["min_inference_ms"] = np.min(latencies)
        results["max_inference_ms"] = np.max(latencies)
        results["std_inference_ms"] = np.std(latencies)
        results["fps"] = 1000 / results["avg_inference_ms"]
        results["meets_target"] = results["avg_inference_ms"] < results["target_ms"]
        
        # Calculate speedup vs PyTorch
        if self.format != "pytorch" and self.model_name in EXPECTED_RESULTS:
            pytorch_time = EXPECTED_RESULTS[self.model_name].get("pytorch")
            if pytorch_time:
                results["speedup_vs_pytorch"] = pytorch_time / results["avg_inference_ms"]
        
        # Memory usage
        try:
            import psutil
            process = psutil.Process()
            results["memory_mb"] = process.memory_info().rss / (1024 * 1024)
        except ImportError:
            logger.warning("⚠️  psutil not installed, memory usage unavailable")
        
        return results
    
    def print_results(self, results: Dict):
        """Print benchmark results."""
        print(f"\n{'='*70}")
        print(f"📊 BENCHMARK RESULTS: {self.model_name.upper()} - {self.format.upper()}")
        print(f"{'='*70}")
        print(f"Model: {results['description']}")
        print(f"Layer: {results['layer']}")
        print(f"Resolution: {results['resolution']}")
        print(f"Device: {results['device']}")
        print(f"\n⏱️  PERFORMANCE:")
        print(f"  Load Time: {results['load_time_s']:.2f}s")
        print(f"  Avg Inference: {results['avg_inference_ms']:.1f}ms")
        print(f"  Min Inference: {results['min_inference_ms']:.1f}ms")
        print(f"  Max Inference: {results['max_inference_ms']:.1f}ms")
        print(f"  Std Deviation: {results['std_inference_ms']:.1f}ms")
        print(f"  FPS: {results['fps']:.1f}")
        if results['memory_mb'] > 0:
            print(f"  Memory Usage: {results['memory_mb']:.0f}MB")
        
        # Target comparison
        target = results['target_ms']
        actual = results['avg_inference_ms']
        meets = results['meets_target']
        status = "✅ PASS" if meets else "❌ FAIL"
        print(f"\n🎯 TARGET: {target}ms | ACTUAL: {actual:.1f}ms | {status}")
        
        # Speedup comparison
        if results['speedup_vs_pytorch']:
            speedup = results['speedup_vs_pytorch']
            print(f"⚡ SPEEDUP vs PyTorch: {speedup:.1f}x faster!")
        
        # Expected comparison (if available)
        if self.model_name in EXPECTED_RESULTS:
            expected = EXPECTED_RESULTS[self.model_name].get(self.format)
            if expected:
                diff = abs(actual - expected)
                percent_diff = (diff / expected) * 100
                print(f"\n📋 EXPECTED: {expected}ms | DIFF: {diff:.1f}ms ({percent_diff:.1f}%)")
                if percent_diff > 10:
                    print(f"⚠️  WARNING: Result differs from Ultralytics benchmark by {percent_diff:.1f}%")
        
        print(f"{'='*70}\n")


def benchmark_model_all_formats(model_name: str, formats: List[str] = None):
    """Benchmark a model in all available formats."""
    if formats is None:
        formats = ["pytorch", "ncnn"]  # Default to PyTorch and NCNN
    
    results = []
    for fmt in formats:
        logger.info(f"\n{'='*70}")
        logger.info(f"🚀 Benchmarking {model_name} in {fmt.upper()} format")
        logger.info(f"{'='*70}")
        
        try:
            benchmark = ModelBenchmark(model_name, fmt)
            result = benchmark.benchmark(num_frames=100, warmup_frames=10)
            benchmark.print_results(result)
            results.append(result)
        except Exception as e:
            logger.error(f"❌ Error benchmarking {model_name} ({fmt}): {e}")
    
    return results


def export_results(results: List[Dict], output_file: str):
    """Export benchmark results to JSON file."""
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
        },
        "benchmarks": results
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"✅ Results exported to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark YOLO models")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks")
    parser.add_argument("--model", type=str, help="Model name (e.g., yolo11n)")
    parser.add_argument("--format", type=str, help="Format (pytorch, ncnn, onnx, openvino)")
    parser.add_argument("--compare", type=str, help="Compare all formats for a model")
    parser.add_argument("--export", type=str, help="Export results to JSON file")
    
    args = parser.parse_args()
    
    all_results = []
    
    if args.all:
        # Benchmark all models in PyTorch and NCNN
        logger.info("🚀 Running ALL benchmarks (PyTorch and NCNN)")
        for model_name in BENCHMARK_MODELS.keys():
            results = benchmark_model_all_formats(model_name, formats=["pytorch", "ncnn"])
            all_results.extend(results)
    
    elif args.compare:
        # Compare all formats for a specific model
        results = benchmark_model_all_formats(args.compare, formats=["pytorch", "ncnn"])
        all_results.extend(results)
    
    elif args.model and args.format:
        # Benchmark specific model in specific format
        benchmark = ModelBenchmark(args.model, args.format)
        result = benchmark.benchmark(num_frames=100, warmup_frames=10)
        benchmark.print_results(result)
        all_results.append(result)
    
    else:
        parser.print_help()
        return
    
    # Export results if requested
    if args.export and all_results:
        export_results(all_results, args.export)


if __name__ == "__main__":
    main()
