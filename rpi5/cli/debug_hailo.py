"""
Hailo NPU Diagnostic v3 — Focused Tests
Tests: create_infer_model API + activated raw vstreams

Run on RPi5: python ~/ProjectCortex/rpi5/cli/debug_hailo.py
"""
import numpy as np
import sys
import os
import time
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
HEF_PATH = str(PROJECT_ROOT / "models" / "hailo" / "fast_depth.hef")

print("=" * 60)
print("HAILO NPU DIAGNOSTIC v3")
print("=" * 60)
print(f"  HEF path:   {HEF_PATH}")
print(f"  HEF exists: {os.path.isfile(HEF_PATH)}")

from hailo_platform import (
    HEF, VDevice, ConfigureParams, HailoStreamInterface,
    InputVStreamParams, OutputVStreamParams, FormatType,
    HailoSchedulingAlgorithm, InferVStreams,
    InputVStreams, OutputVStreams,
)

# ================================================================
# TEST 1: create_infer_model API (modern approach)
# ================================================================
print("\n" + "=" * 60)
print("[TEST 1] create_infer_model API")
print("=" * 60)
try:
    vd = VDevice()
    print(f"  VDevice methods: {[m for m in dir(vd) if not m.startswith('_')]}")

    infer_model = vd.create_infer_model(HEF_PATH)
    print(f"  InferModel created: {type(infer_model)}")
    print(f"  InferModel methods: {[m for m in dir(infer_model) if not m.startswith('_')]}")

    # Explore input/output info
    inp = infer_model.input()
    out = infer_model.output()
    print(f"  Input:  name='{inp.name}', shape={inp.shape}, format={getattr(inp, 'format_type', 'N/A')}")
    print(f"  Input methods: {[m for m in dir(inp) if not m.startswith('_')]}")
    print(f"  Output: name='{out.name}', shape={out.shape}, format={getattr(out, 'format_type', 'N/A')}")
    print(f"  Output methods: {[m for m in dir(out) if not m.startswith('_')]}")

    # Configure
    infer_model.set_batch_size(1)
    infer_model.input().set_format_type(FormatType.FLOAT32)
    infer_model.output().set_format_type(FormatType.FLOAT32)
    print("  Configured: batch=1, input=FLOAT32, output=FLOAT32")

    with infer_model.configure() as configured:
        print(f"  ConfiguredInferModel type: {type(configured)}")
        print(f"  ConfiguredInferModel methods: {[m for m in dir(configured) if not m.startswith('_')]}")

        bindings = configured.create_bindings()
        print(f"  Bindings type: {type(bindings)}")
        print(f"  Bindings methods: {[m for m in dir(bindings) if not m.startswith('_')]}")

        b_inp = bindings.input()
        print(f"  Binding input methods: {[m for m in dir(b_inp) if not m.startswith('_')]}")

        # Create float32 input
        dummy = np.random.rand(224, 224, 3).astype(np.float32)
        dummy = np.ascontiguousarray(dummy)
        print(f"  Input data: shape={dummy.shape}, dtype={dummy.dtype}, nbytes={dummy.nbytes}")

        bindings.input().set_buffer(dummy)
        print("  Buffer set on input binding")

        # Run inference
        t0 = time.time()
        configured.run(bindings, timeout_ms=10000)
        elapsed = time.time() - t0
        print(f"  Inference ran in {elapsed*1000:.1f}ms")

        output = bindings.output().get_buffer()
        print(f"  SUCCESS! Output: shape={output.shape}, dtype={output.dtype}, "
              f"min={output.min():.4f}, max={output.max():.4f}, mean={output.mean():.4f}")

    del vd
    print("  [TEST 1 PASSED]")

except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        del vd
    except:
        pass

# ================================================================
# TEST 2: create_infer_model with UINT8 input (native HW format)
# ================================================================
print("\n" + "=" * 60)
print("[TEST 2] create_infer_model + UINT8 input")
print("=" * 60)
try:
    vd = VDevice()
    infer_model = vd.create_infer_model(HEF_PATH)
    infer_model.set_batch_size(1)
    infer_model.input().set_format_type(FormatType.UINT8)
    infer_model.output().set_format_type(FormatType.FLOAT32)

    with infer_model.configure() as configured:
        bindings = configured.create_bindings()
        dummy = (np.random.rand(224, 224, 3) * 255).astype(np.uint8)
        dummy = np.ascontiguousarray(dummy)
        print(f"  Input data: shape={dummy.shape}, dtype={dummy.dtype}, nbytes={dummy.nbytes}")

        bindings.input().set_buffer(dummy)
        t0 = time.time()
        configured.run(bindings, timeout_ms=10000)
        elapsed = time.time() - t0
        print(f"  Inference ran in {elapsed*1000:.1f}ms")

        output = bindings.output().get_buffer()
        print(f"  SUCCESS! Output: shape={output.shape}, dtype={output.dtype}, "
              f"min={output.min():.4f}, max={output.max():.4f}, mean={output.mean():.4f}")

    del vd
    print("  [TEST 2 PASSED]")

except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        del vd
    except:
        pass

# ================================================================
# TEST 3: create_infer_model — async run (if available)
# ================================================================
print("\n" + "=" * 60)
print("[TEST 3] create_infer_model + async_infer (if available)")
print("=" * 60)
try:
    vd = VDevice()
    infer_model = vd.create_infer_model(HEF_PATH)
    infer_model.set_batch_size(1)
    infer_model.input().set_format_type(FormatType.FLOAT32)
    infer_model.output().set_format_type(FormatType.FLOAT32)

    with infer_model.configure() as configured:
        if hasattr(configured, 'run_async'):
            print("  run_async is available!")
            # test it
            bindings = configured.create_bindings()
            dummy = np.random.rand(224, 224, 3).astype(np.float32)
            dummy = np.ascontiguousarray(dummy)
            bindings.input().set_buffer(dummy)

            result_ready = threading.Event()
            async_output = {}

            def callback(bindings, status):
                async_output['status'] = status
                async_output['output'] = bindings.output().get_buffer()
                result_ready.set()

            job = configured.run_async(bindings, callback)
            result_ready.wait(timeout=10)
            if result_ready.is_set():
                out = async_output.get('output')
                print(f"  SUCCESS! Output: shape={out.shape}, dtype={out.dtype}")
            else:
                print("  TIMEOUT waiting for async result")
        else:
            print("  run_async NOT available")

    del vd
    print("  [TEST 3 DONE]")

except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        del vd
    except:
        pass

# ================================================================
# TEST 4: Raw send/recv WITH ng.activate() 
# ================================================================
print("\n" + "=" * 60)
print("[TEST 4] Raw InputVStreams + OutputVStreams WITH activate()")
print("=" * 60)
try:
    vd = VDevice()
    hef = HEF(HEF_PATH)
    cp = ConfigureParams.create_from_hef(hef=hef, interface=HailoStreamInterface.PCIe)
    ng = vd.configure(hef, cp)[0]

    in_params = InputVStreamParams.make(ng, format_type=FormatType.FLOAT32)
    out_params = OutputVStreamParams.make(ng, format_type=FormatType.FLOAT32)

    dummy = np.random.rand(224, 224, 3).astype(np.float32)
    dummy = np.ascontiguousarray(dummy)
    print(f"  Input data: shape={dummy.shape}, dtype={dummy.dtype}, nbytes={dummy.nbytes}")

    recv_result = {}

    def recv_thread(out_vs):
        """Receive in a separate thread (recv blocks until data available)."""
        try:
            out_layer = out_vs.get()
            output = out_layer.recv()
            recv_result['output'] = output
            recv_result['success'] = True
        except Exception as e:
            recv_result['error'] = str(e)
            recv_result['success'] = False

    with ng.activate():
        print("  Network group activated")
        with InputVStreams(ng, in_params) as in_vs, \
             OutputVStreams(ng, out_params) as out_vs:

            in_layer = in_vs.get()
            print(f"  InputVStream: name='{in_layer.name}', "
                  f"shape={in_layer.shape}, dtype={in_layer.dtype}")

            # Start receiver thread first (recv blocks)
            t = threading.Thread(target=recv_thread, args=(out_vs,))
            t.start()

            # Send data
            t0 = time.time()
            in_layer.send(dummy)
            print(f"  Data sent in {(time.time()-t0)*1000:.1f}ms")

            # Wait for recv
            t.join(timeout=10)
            elapsed = time.time() - t0

            if recv_result.get('success'):
                output = recv_result['output']
                print(f"  SUCCESS! Output: shape={output.shape}, dtype={output.dtype}, "
                      f"min={output.min():.4f}, max={output.max():.4f}, "
                      f"elapsed={elapsed*1000:.1f}ms")
            else:
                print(f"  RECV FAILED: {recv_result.get('error', 'timeout')}")

    del ng, vd
    print("  [TEST 4 DONE]")

except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        del ng, vd
    except:
        pass

# ================================================================
# TEST 5: Multi-model on shared VDevice (ROUND_ROBIN) via create_infer_model
# ================================================================
print("\n" + "=" * 60)
print("[TEST 5] Shared VDevice (ROUND_ROBIN) + create_infer_model")
print("=" * 60)
OCR_HEF_PATH = str(PROJECT_ROOT / "models" / "hailo" / "paddle_ocr_v3_recognition.hef")
print(f"  OCR HEF exists: {os.path.isfile(OCR_HEF_PATH)}")
try:
    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
    vd = VDevice(params)
    print("  Shared VDevice created (ROUND_ROBIN)")

    # Load depth model
    depth_model = vd.create_infer_model(HEF_PATH)
    depth_model.set_batch_size(1)
    depth_model.input().set_format_type(FormatType.FLOAT32)
    depth_model.output().set_format_type(FormatType.FLOAT32)
    print(f"  Depth model: input={depth_model.input().shape}, output={depth_model.output().shape}")

    # Load OCR model
    ocr_model = vd.create_infer_model(OCR_HEF_PATH)
    ocr_model.set_batch_size(1)
    ocr_model.input().set_format_type(FormatType.FLOAT32)
    ocr_model.output().set_format_type(FormatType.FLOAT32)
    print(f"  OCR model:   input={ocr_model.input().shape}, output={ocr_model.output().shape}")

    # Run depth inference
    with depth_model.configure() as depth_cfg:
        bindings = depth_cfg.create_bindings()
        dummy_depth = np.random.rand(224, 224, 3).astype(np.float32)
        bindings.input().set_buffer(np.ascontiguousarray(dummy_depth))
        t0 = time.time()
        depth_cfg.run(bindings, timeout_ms=10000)
        d_out = bindings.output().get_buffer()
        print(f"  Depth inference: {(time.time()-t0)*1000:.1f}ms, "
              f"output={d_out.shape}, range=[{d_out.min():.3f}, {d_out.max():.3f}]")

    # Run OCR inference
    with ocr_model.configure() as ocr_cfg:
        bindings = ocr_cfg.create_bindings()
        ocr_shape = tuple(ocr_model.input().shape)
        dummy_ocr = np.random.rand(*ocr_shape).astype(np.float32)
        bindings.input().set_buffer(np.ascontiguousarray(dummy_ocr))
        t0 = time.time()
        ocr_cfg.run(bindings, timeout_ms=10000)
        o_out = bindings.output().get_buffer()
        print(f"  OCR inference:   {(time.time()-t0)*1000:.1f}ms, "
              f"output={o_out.shape}, range=[{o_out.min():.3f}, {o_out.max():.3f}]")

    del vd
    print("  [TEST 5 PASSED — MULTI-MODEL WORKS]")

except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        del vd
    except:
        pass

# ================================================================
print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
