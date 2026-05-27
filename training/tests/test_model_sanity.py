"""
Quick sanity test for CortexLocal model on RTX 2050.

Tests:
1. Model instantiation
2. Forward pass with dummy inputs
3. Parameter count
4. Memory footprint
5. ONNX export

Author: Haziq (@IRSPlays)
Date: May 2026
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import torch
from training.models.cortex_local import CortexLocalModel


def test_model():
    print("=" * 60)
    print("CortexLocal Model Sanity Test")
    print("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice: {device}")
    if device.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
        torch.cuda.reset_peak_memory_stats()

    # Build model (using stub Mamba since mamba_ssm not installed)
    print("\n[1/5] Building model...")
    model = CortexLocalModel(
        vocab_size=32000,
        d_model=512,
        n_layer=12,
        d_state=64,
        d_conv=4,
        expand=2,
        num_tools=14,
    ).to(device)

    total_params = model.count_parameters()
    print(f"Total trainable params: {total_params:,}")
    print(f"Expected: ~95,000,000")

    # Dummy inputs
    batch_size = 1
    dummy_video = torch.randn(batch_size, 3, 224, 224, device=device)
    dummy_audio = torch.randn(batch_size, 1, 80, 100, device=device)
    dummy_text = torch.randint(0, 32000, (batch_size, 32), device=device)

    print(f"\n[2/5] Forward pass (batch={batch_size})...")
    with torch.no_grad():
        conv_state, ssm_state = model.init_states(batch_size, device)
        outputs = model(
            video=dummy_video,
            audio=dummy_audio,
            text_tokens=dummy_text,
            conv_state=conv_state,
            ssm_state=ssm_state,
        )

    print(f"  logits shape:       {outputs['logits'].shape}")
    print(f"  mode_logits shape:  {outputs['mode_logits'].shape}")
    print(f"  tool_logits shape:  {outputs['tool_logits'].shape}")
    print(f"  next_conv shape:    {outputs['next_conv_state'][0].shape} x {len(outputs['next_conv_state'])}")
    print(f"  next_ssm shape:     {outputs['next_ssm_state'][0].shape} x {len(outputs['next_ssm_state'])}")

    if device.type == "cuda":
        mem_mb = torch.cuda.max_memory_allocated() / 1e6
        print(f"\n[3/5] Peak VRAM usage: {mem_mb:.1f} MB")

    # Try autoregressive generation for a few steps
    print("\n[4/5] Autoregressive generation (5 steps)...")
    input_ids = dummy_text
    conv_state, ssm_state = model.init_states(batch_size, device)
    for step in range(5):
        with torch.no_grad():
            out = model(
                video=dummy_video,
                audio=dummy_audio,
                text_tokens=input_ids,
                conv_state=conv_state,
                ssm_state=ssm_state,
            )
        conv_state = out["next_conv_state"]
        ssm_state = out["next_ssm_state"]
        next_token = out["logits"][:, -1, :].argmax(dim=-1, keepdim=True)
        input_ids = torch.cat([input_ids, next_token], dim=1)
    print(f"  Generated sequence length: {input_ids.shape[1]} (started at 32)")

    # ONNX export test
    print("\n[5/5] ONNX export test...")
    try:
        dummy_conv = torch.zeros(model.n_layer, batch_size, 512, 4, device=device)
        dummy_ssm = torch.zeros(model.n_layer, batch_size, 512, 64, device=device)

        # Wrapped model for ONNX (flatten dict outputs)
        class Wrapped(torch.nn.Module):
            def __init__(self, inner):
                super().__init__()
                self.inner = inner
            def forward(self, video, audio, tokens, conv_state, ssm_state):
                out = self.inner(
                    video=video, audio=audio, text_tokens=tokens,
                    conv_state=[conv_state[i] for i in range(conv_state.size(0))],
                    ssm_state=[ssm_state[i] for i in range(ssm_state.size(0))],
                )
                next_conv = torch.stack(out["next_conv_state"], dim=0)
                next_ssm = torch.stack(out["next_ssm_state"], dim=0)
                return out["logits"], out["mode_logits"], out["tool_logits"], next_conv, next_ssm

        wrapped = Wrapped(model).cpu().eval()
        torch.onnx.export(
            wrapped,
            (
                dummy_video.cpu(),
                dummy_audio.cpu(),
                input_ids[:, :32].cpu(),
                dummy_conv.cpu(),
                dummy_ssm.cpu(),
            ),
            "cortex_local_test.onnx",
            input_names=["video", "audio", "tokens", "conv_state", "ssm_state"],
            output_names=["logits", "mode_logits", "tool_logits", "next_conv", "next_ssm"],
            dynamic_axes={"tokens": {1: "seq_len"}, "logits": {1: "seq_len"}},
            opset_version=13,
            do_constant_folding=True,
        )
        print("  ONNX export: SUCCESS -> cortex_local_test.onnx")
        # Verify if onnx package available
        try:
            import onnx
            onnx_model = onnx.load("cortex_local_test.onnx")
            onnx.checker.check_model(onnx_model)
            print("  ONNX validation: PASS")
        except ImportError:
            print("  ONNX validation: SKIPPED (onnx package not installed)")
    except Exception as e:
        print(f"  ONNX export: FAILED ({e})")

    print("\n" + "=" * 60)
    print("All tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_model()
