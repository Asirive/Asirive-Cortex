# CortexLocal v2 Plan
## Asirive Cortex Offline Multimodal Copilot

**Objective:** Build a fully offline, multimodal (audio+video → text) AI copilot that runs natively on Raspberry Pi 5, serving as a graceful fallback when Gemini Live cloud connectivity is unavailable (MRT tunnels, underground malls, weak signal areas).

**Constraint:** RPi5 has 4GB RAM. Target model size is 95M parameters INT8 (~100 MB). Latency target: <500 ms on CPU fallback, <200 ms on Hailo NPU when available.

**Key Design Decision:** Output text tokens fed to existing Kokoro TTS instead of raw audio tokens. This dramatically improves trainability, debuggability, and deployment robustness while reusing the existing offline voice stack.

**Author:** Haziq (@IRSPlays) + AI Planning Agent  
**Date:** May 2026  
**Status:** Active Development  
**Supersedes:** `docs/plans/LOCAL_MULTIMODAL_COPILOT_PLAN.md`

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                       CortexLocal v1 (Final Design)                    │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  INPUTS                                                                │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Video stream:    BGR 1080p @ 30 FPS -> resize 224x224 -> 2 FPS │    │
│  │ Audio (ambient): 16 kHz int16 PCM    -> mel-spec [80, 100]     │    │
│  │ User query:      Whisper-tiny text (already available offline)│    │
│  │ Conversation:    ConversationManager history                  │    │
│  │ Tool registry:   14 functions (mirror Gemini Live tools)      │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  ENCODERS                                                              │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Vision Tower:  MobileCLIP-S2 (Apple, 35M, CLIP-aligned)        │    │
│  │   Per-frame 224x224 -> [196, 384] patch tokens                 │    │
│  │   Pretrained on 1B image-text pairs                            │    │
│  │   Drop CLS, project to 512 dim -> [196, 512]                   │    │
│  │                                                                │    │
│  │ Audio Tower:   Mel-CNN (5M, environmental sound classifier)    │    │
│  │   [1, 80, 100] -> [12, 512] audio tokens                       │    │
│  │   Pretrained on AudioSet                                       │    │
│  │                                                                │    │
│  │ Text Embedder: SmolLM2-360M tokenizer (32k BPE)                │    │
│  │   Query + history -> text tokens -> [N_text, 512]              │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  FUSION CORE                                                           │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Mamba-2 Decoder                                                │    │
│  │   12 layers, d_model=512, d_state=64, d_conv=4, expand=2       │    │
│  │   ~55M params                                                  │    │
│  │   Input: [vision_tokens; audio_tokens; text_tokens]            │    │
│  │   Causal masked (autoregressive)                               │    │
│  │   State [12, B, 512, 64] carried in CPU between turns        │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  HEADS                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ LM Head:       Linear(512, 32_000) -> softmax over BPE vocab   │    │
│  │ Mode Head:     Linear(512, 4) -> [<speak>, <silence>, ...]     │    │
│  │ Tool Head:     Linear(512, 14) -> tool ID (when mode=<tool>)   │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  OUTPUTS                                                               │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Generated text   -> Kokoro TTS -> StreamingAudioPlayer         │    │
│  │ Tool calls       -> CortexSystem._handle_gemini_tool_call()  │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  Total: ~95M params  |  INT8 size: ~100 MB  |  Target: 300 ms         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 Vision Tower: MobileCLIP-S2

**Why:** Apple-trained 35M parameter CLIP model with vision-language alignment built-in. Conv-based, Hailo-friendly. Strong zero-shot open-vocabulary recognition without us needing to pretrain.

**Input:** `[3, 224, 224]` RGB frame (from 2 FPS rolling buffer of camera frames)  
**Output:** `[196, 512]` patch embeddings (no CLS token; we use all spatial patches)

**Hailo Notes:**  
- MobileCLIP uses standard Conv2D + BN + ReLU + SE (squeeze-excite) blocks. SE is element-wise and Hailo-DFC v3.28+ supports it natively.  
- If SE is problematic on current Hailo suite, we can replace SE with depthwise conv + 1x1 bottleneck during QAT stage.

```python
# training/models/vision_tower.py (stub)
from mobileclip import create_model_and_transforms

class VisionTower(nn.Module):
    def __init__(self, model_name="mobileclip_s2", proj_dim=512):
        super().__init__()
        self.model, _, _ = create_model_and_transforms(
            model_name, pretrained=True
        )
        # Remove text tower; keep vision backbone + projector
        self.vision = self.model.image_encoder
        self.proj = nn.Linear(384, proj_dim)  # S2 hidden dim -> 512

    def forward(self, x):
        # x: [B, 3, 224, 224]
        feats = self.vision(x, return_all_features=True)
        # feats: [B, 196, 384] (patch tokens)
        feats = self.proj(feats)  # [B, 196, 512]
        return feats
```

---

### 2.2 Audio Tower: Lightweight Mel-CNN

**Why:** We need ambient sound context (traffic, alarms, voices) beyond what Whisper ASR provides. AudioSet-pretrained mel-spectrogram CNN is lightweight and maps naturally to Hailo Conv2D operators.

**Preprocessing (CPU, ~2 ms on RPi5):**
```python
def preprocess_audio(pcm_16khz: np.ndarray) -> np.ndarray:
    """Convert 1-second PCM chunk to mel spectrogram."""
    mel = librosa.feature.melspectrogram(
        y=pcm_16khz.astype(np.float32) / 32768.0,
        sr=16000,
        n_mels=80,
        n_fft=512,
        hop_length=160,   # 10 ms hop -> 100 frames per second
        win_length=400,   # 25 ms window
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)  # [80, 100]
    mel_norm = np.clip(mel_db / 80.0, -1.0, 1.0)
    return mel_norm[np.newaxis, ...]  # [1, 80, 100]
```

**Encoder Architecture:**
```python
class AudioTower(nn.Module):
    def __init__(self, proj_dim=512):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, 3, stride=(2, 2), padding=1),   # [32, 40, 50]
            nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=(2, 2), padding=1),  # [64, 20, 25]
            nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 128, 3, stride=(2, 1), padding=1), # [128, 10, 25]
            nn.BatchNorm2d(128), nn.ReLU(),
        )
        self.pool = nn.AdaptiveAvgPool2d((3, 1))  # [128, 3, 1]
        self.proj = nn.Linear(128, proj_dim)       # [3, 512]

    def forward(self, x):
        # x: [B, 1, 80, 100]
        x = self.conv(x)
        x = self.pool(x).squeeze(-1)  # [B, 128, 3]
        x = x.permute(0, 2, 1)        # [B, 3, 128]
        x = self.proj(x)              # [B, 3, 512]
        return x
```

**Hailo Notes:**  
- All standard Conv2D + BN + ReLU + AvgPool2d. Zero exotic ops.  
- BatchNorm will be folded into Conv weights during ONNX export / Hailo parse.

---

### 2.3 Fusion Core: Mamba-2 SSM (Stateful)

**Why:** Mamba-2 is the only architecture that gives us (a) attention-equivalent quality, (b) linear-time streaming, (c) constant-memory state, and (d) Hailo NPU deployability (Conv1D + element-wise + selective scan). It natively supports streaming video frames one-by-one without recomputation. VideoMamba (ICML 2024) proved it beats Vision Transformers at 1/4 compute on video-language tasks.

**Architecture:**
```python
class MambaFusionCore(nn.Module):
    def __init__(self, d_model=512, d_state=64, d_conv=4, expand=2, n_layer=12):
        super().__init__()
        from mamba_ssm import Mamba2
        self.layers = nn.ModuleList([
            nn.ModuleDict({
                "norm": nn.RMSNorm(d_model),
                "mamba": Mamba2(
                    d_model=d_model,
                    d_state=d_state,
                    d_conv=d_conv,
                    expand=expand,
                ),
            })
            for _ in range(n_layer)
        ])
        self.norm_f = nn.RMSNorm(d_model)

    def forward(self, x, conv_state=None, ssm_state=None):
        """
        x: [B, L, d_model]  (concatenated vision+audio+text tokens)
        conv_state: list of [B, d_model, d_conv] per layer (CPU-managed)
        ssm_state:  list of [B, d_model, d_state] per layer (CPU-managed)
        Returns: logits [B, L, d_model], next_conv_state, next_ssm_state
        """
        next_conv_state = []
        next_ssm_state = []
        for i, layer in enumerate(self.layers):
            x = layer["norm"](x)
            cs = conv_state[i] if conv_state is not None else None
            ss = ssm_state[i] if ssm_state is not None else None
            x, cs_out, ss_out = layer["mamba"].step(x, conv_state=cs, ssm_state=ss)
            next_conv_state.append(cs_out)
            next_ssm_state.append(ss_out)
        x = self.norm_f(x)
        return x, next_conv_state, next_ssm_state
```

**Key Design Decision:**  
- The `conv_state` and `ssm_state` are **NOT** part of the Hailo model graph.  
- After each inference, RPi5 CPU extracts states from output tensors (or via ONNX `I/OBinding` / Hailo tensor extraction).  
- Before next inference, CPU feeds previous states as additional input tensors.  
- This gives the model **infinite temporal context** with fixed NPU memory.

**Hailo Stateful Inference:**  
```python
# Pseudo-code for Hailo runtime
input_tensors = {
    'tokens':    token_ids,      # [1, L, 512] (pre-embedded)
    'conv_state': prev_conv,    # [12, 1, 512, 4]
    'ssm_state':  prev_ssm,     # [12, 1, 512, 64]
}
output_tensors = model.run(input_tensors)
logits = output_tensors['logits']        # [1, L, 512]
next_conv = output_tensors['conv_state']  # [12, 1, 512, 4]
next_ssm = output_tensors['ssm_state']    # [12, 1, 512, 64]
# save next_conv, next_ssm for next tick
```

---

### 2.4 Output Heads

**LM Head:** Standard language modeling over 32k BPE vocabulary.  
**Mode Head:** 4-way classifier: `<speak>`, `<silence>`, `<tool>`, `<eos>`.  
**Tool Head:** 14-way classifier matching the 14 Gemini Live tools.

```python
class OutputHeads(nn.Module):
    def __init__(self, d_model=512, vocab_size=32000, num_tools=14):
        super().__init__()
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        self.mode_head = nn.Linear(d_model, 4)
        self.tool_head = nn.Linear(d_model, num_tools)

    def forward(self, hidden):
        # hidden: [B, L, d_model]
        return {
            "logits": self.lm_head(hidden),
            "mode_logits": self.mode_head(hidden[:, -1, :]),
            "tool_logits": self.tool_head(hidden[:, -1, :]),
        }
```

**Mode Token Semantics:**
| Token | Behavior |
|---|---|
| `<speak>` | Model will generate text response → Kokoro TTS → speaker |
| `<silence>` | Model decides nothing to say. No audio output. |
| `<tool>` | Model emits tool call. No audio. Tool result may trigger follow-up `<speak>`. |
| `<eos>` | Turn complete. Reset states for next user query. |

---

## 3. Full Model Specification

| Component | Parameters | Hailo Ops | Input Shape | Output Shape |
|---|---|---|---|---|
| Vision Tower (MobileCLIP-S2) | ~35M | Conv2D, BN, ReLU, SE | `[B, 3, 224, 224]` | `[B, 196, 512]` |
| Audio Tower (Mel-CNN) | ~5M | Conv2D, BN, ReLU, AvgPool | `[B, 1, 80, 100]` | `[B, 3, 512]` |
| Text Embedder (Embedding) | ~16M | Embedding | `[B, L_text]` | `[B, L_text, 512]` |
| Mamba-2 Core (12 layers) | ~55M | Conv1D, Linear, SiLU, Element-wise | `[B, L_total, 512]` + states | `[B, L_total, 512]` + states |
| LM Head | ~16M | Linear | `[B, L, 512]` | `[B, L, 32000]` |
| Mode + Tool Heads | ~0.01M | Linear | `[B, 512]` | `[B, 4]`, `[B, 14]` |
| **Total** | **~95M** | | | |

**INT8 Model Size:** ~100 MB  
**Expected NPU Latency:** ~100-200 ms per token generation step  
**Expected CPU Latency:** ~400-800 ms per step (ONNXRuntime, 4 threads)

---

## 4. Training Pipeline (Datacenter GPUs)

### 4.1 Dataset Construction Strategy

**Primary Method: Teacher Distillation from Gemini Live**

We use the existing Cortex system to generate training quadruplets at scale:

```
Quadruplet = (
    1-sec audio prompt (Whisper transcript + ambient mel),
    2 FPS video clip (4 frames),
    1-sec audio response (Gemini transcript),
    tool_calls (JSON array or null)
)
```

**Data Collection Protocol:**
1. Record 500+ hours of first-person walking video with stereo audio.
2. For each 10-second segment, feed into Gemini Live API with the prompt:  
   `"You are assisting a blind person. Describe what you see and hear. Respond naturally in under 15 words."`
3. Capture Gemini's audio response, transcribe with Whisper as the **text target**.
4. The user's natural speech (or synthetic prompts) is the **audio prompt**.
5. Synchronized video frames are the **visual context**.
6. Capture any tool calls Gemini makes (navigation, bus, memory) as **structured targets**.

**Dataset Augmentation:**
- **Acoustic:** Add reverb, background noise (MRT, street, mall), pitch shift
- **Visual:** Random brightness/contrast, simulated motion blur, occlusions
- **Temporal:** Random chunk alignment offsets (-200 ms to +200 ms)
- **Prompt diversity:** Synthetic TTS prompts in Singlish, Mandarin, Malay
- **Negative samples:** Scenes where Gemini responds with silence — teach `<silence>` token

**Expected Dataset Size:**
| Phase | Hours | Quadruplets | Storage |
|---|---|---|---|
| Bootstrap (synthetic VQA) | 100h | 3.6M | ~500 GB |
| Real-world capture | 500h | 18M | ~2.5 TB |
| Augmented (10x) | 6000h | 216M | ~25 TB |

---

### 4.2 Training Stages

#### Stage 1: Multimodal Pretraining (Image-Text Captioning)
**Goal:** Train the Mamba core and vision projector from scratch on vision-language alignment.
**Data:** LAION-400M (filtered, English + Asian images) + WebVid-10M (short clips)
**Duration:** 2 weeks on 8x H100
**Loss:** Cross-entropy on caption tokens
**Checkpoint:** `ckpt_pretrain.pt`

#### Stage 2: Video Extension (Temporal Video Clips)
**Goal:** Extend to temporal video (4-8 frames) and ambient audio.
**Data:** Ego4D + HowTo100M + WebVid long clips
**Duration:** 1 week on 8x H100
**LR:** 1e-4 with cosine decay
**Loss:** Cross-entropy on caption tokens + next-frame prediction auxiliary loss
**Checkpoint:** `ckpt_video.pt`

#### Stage 3: Instruction Tuning (Multimodal Q/A)
**Goal:** Teach the model to follow instructions, answer questions, and emit mode tokens.
**Data:** LLaVA-Instruct-150k, ShareGPT4V, VideoChatGPT-100k, M3IT, MagicLM-Vision, Singlish/Malay/Mandarin code-switch corpus
**Duration:** 5 days on 8x H100
**LR:** 1e-4 with cosine decay
**Loss:** CE on text tokens + CE on mode tokens + CE on tool tokens (where applicable)
**Checkpoint:** `ckpt_instruct.pt`

#### Stage 4: Cortex Teacher Distillation (The Unique Stage)
**Goal:** The small model should match Gemini's behavior on first-person blind-assistance data.
**Method:** Run Gemini on held-out set. Train the small model with:
- **Token loss:** Cross-entropy on generated text tokens vs Gemini transcript
- **Mode loss:** Cross-entropy on mode tokens (silence vs speak vs tool)
- **Tool loss:** F1-weighted cross-entropy on tool calls
- **KL loss:** KL divergence vs Gemini API logprobs (if available)
**Duration:** 2 weeks on 4x H100
**Checkpoint:** `ckpt_cortex.pt`

#### Stage 5: Quantization-Aware Training (QAT)
**Goal:** Make the model robust to INT8 quantization noise.
**Method:** Fake quantization nodes inserted during training (PyTorch `torch.ao.quantization` with `fbgemm` backend as Hailo INT8 proxy).
**Duration:** 3 days on 4x H100
**LR:** 1e-5 (very slow, fine-tuning only)
**Checkpoint:** `ckpt_int8_qat.pt`

---

### 4.3 Training Config

```yaml
# training/configs/stage1.yaml
model:
  vision_tower: "mobileclip_s2"
  audio_tower:
    channels: [1, 32, 64, 128]
    kernels: [3, 3, 3]
    strides: [[2,2], [2,2], [2,1]]
  fusion:
    type: mamba2
    d_model: 512
    d_state: 64
    d_conv: 4
    expand: 2
    n_layer: 12
  text_embedder:
    tokenizer: "HuggingFaceTB/SmolLM2-360M"
    vocab_size: 32000
    proj_dim: 512
  mode_head:
    num_modes: 4
  tool_head:
    num_tools: 14

audio:
  sample_rate: 16000
  n_mels: 80
  hop_length: 160
  win_length: 400
  n_fft: 512
  chunk_duration: 1.0

video:
  resolution: [224, 224]
  fps: 2
  num_frames: 4
  normalize_mean: [0.485, 0.456, 0.406]
  normalize_std: [0.229, 0.224, 0.225]

training:
  batch_size: 256
  num_workers: 16
  max_epochs: 5
  learning_rate: 1e-3
  weight_decay: 1e-4
  warmup_steps: 5000
  gradient_clip: 1.0
  mixed_precision: true
  compile: true               # torch.compile for H100

qat:
  enabled: true
  observer: moving_average_minmax
  quant_scheme: symmetric
  backend: fbgemm
```

---

## 5. Deployment Pipeline

### 5.1 ONNX Export (Fixed Shapes)

```python
import torch

model = load_model("ckpt_int8_qat.pt")
model.eval()

dummy_tokens = torch.randint(0, 32000, (1, 256))      # [B, L]
dummy_conv = torch.randn(12, 1, 512, 4)              # [n_layer, B, d_model, d_conv]
dummy_ssm = torch.randn(12, 1, 512, 64)               # [n_layer, B, d_model, d_state]

torch.onnx.export(
    model,
    (dummy_tokens, dummy_conv, dummy_ssm),
    "cortex_local.onnx",
    input_names=["tokens", "conv_state", "ssm_state"],
    output_names=["logits", "mode_logits", "tool_logits", "next_conv", "next_ssm"],
    dynamic_axes={"tokens": {1: "seq_len"}},  # sequence length dynamic
    opset_version=17,
    do_constant_folding=True,
)
```

### 5.2 Hailo Dataflow Compiler

```bash
# Run on x86 Linux workstation with Hailo SW Suite installed

# 1. Parse ONNX
hailo parser onnx cortex_local.onnx --output cortex_local.hailo

# 2. Optimize (operator fusion, memory layout)
hailo optimize cortex_local.hailo --output cortex_local_opt.hailo

# 3. Quantization Calibration
hailo quantize cortex_local_opt.hailo \
    --calib-set ./calibration_data/ \
    --output cortex_local_quant.hailo

# 4. Compile to HEF (Hailo Execution Format)
hailo compile cortex_local_quant.hailo \
    --output cortex_local.hef \
    --performance-calibration

# Expected output: cortex_local.hef (~100 MB)
```

### 5.3 RPi5 Runtime Integration

```python
"""
CortexLocal runtime. Plugs into rpi5/main.py as offline fallback.
"""
import numpy as np
import onnxruntime as ort
from typing import Optional, List, Dict

class CortexLocal:
    def __init__(self, onnx_path: str = "models/cortex_local/cortex_local.onnx"):
        self.session = ort.InferenceSession(
            onnx_path,
            providers=["CPUExecutionProvider"],  # Phase 0
        )

        # State management (CPU-side)
        self.conv_state = np.zeros((12, 1, 512, 4), dtype=np.float32)
        self.ssm_state = np.zeros((12, 1, 512, 64), dtype=np.float32)

        # Buffers
        self.audio_buffer = np.zeros(16000, dtype=np.int16)  # 1-second ring
        self.last_video_frame = None
        self.tokenizer = load_tokenizer("models/cortex_local/tokenizer/")

    def ingest_audio(self, pcm_chunk: np.ndarray):
        """Feed 16kHz PCM chunk."""
        self.audio_buffer = np.roll(self.audio_buffer, -len(pcm_chunk))
        self.audio_buffer[-len(pcm_chunk):] = pcm_chunk

    def ingest_video(self, frame: np.ndarray):
        """Feed latest BGR frame. Resize + normalize on CPU."""
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (224, 224))
        self.last_video_frame = normalize(frame_resized)

    def generate_response(self, query_text: str) -> Dict[str, any]:
        """
        Run one autoregressive generation step.
        Returns: {"text": str, "mode": str, "tool_call": Optional[dict]}
        """
        # Embed query + history into token IDs
        token_ids = self.tokenizer.encode(query_text, return_tensors="np")

        # TODO: embed vision + audio tokens into the sequence
        # For now: text-only CPU fallback
        outputs = self.session.run(
            None,
            {
                "tokens": token_ids,
                "conv_state": self.conv_state,
                "ssm_state": self.ssm_state,
            }
        )
        logits, mode_logits, tool_logits, self.conv_state, self.ssm_state = outputs
        # ... decode ...
        return {"text": "", "mode": "<silence>", "tool_call": None}
```

---

## 6. Integration with Cortex

### 6.1 Fallback Logic in `main.py`

```python
class CortexSystem:
    def __init__(self, ...):
        self.gemini_live = GeminiLiveManager(...)   # Primary (cloud)
        self.local_copilot = CortexLocal(...)      # Fallback (CPU/Hailo)
        self.active_audio_source = "gemini"         # "gemini" or "local"

    async def handle_voice_command(self, query):
        if self.gemini_live.is_connected:
            # Primary: cloud
            self.active_audio_source = "gemini"
            await self.gemini_live.send_text(query)
        elif self.local_copilot and self.local_copilot.is_available:
            # Fallback: local
            if self.active_audio_source == "gemini":
                await self.tts_router.speak("Switching to offline mode.")
                self.active_audio_source = "local"
            response = self.local_copilot.generate_response(query)
            if response["mode"] == "<speak>":
                await self.kokoro.speak(response["text"])
            elif response["mode"] == "<tool>":
                await self._handle_gemini_tool_call(response["tool_call"])
            # <silence> -> nothing
        else:
            # Degraded
            await self.tts_router.speak("One moment, I'm reconnecting.")
```

### 6.2 Graceful Handoff

When connectivity drops:
1. Gemini WebSocket detects disconnect.
2. `main.py` sets `active_audio_source = "local"`.
3. Local copilot starts generating from the **same** conversation context (ConversationManager history).
4. User hears: *"I'm switching to offline mode. I can still guide you."* (pre-recorded TTS)
5. When Gemini reconnects, Mamba states are **not** carried over — audio seamlessly switches back.

---

## 7. Development Milestones

| Milestone | Duration | Deliverable | Success Criteria |
|---|---|---|---|
| **M0: Training Infra + Data Loaders** | 2 wk | LAION + WebVid loaders working | 1 train step on 1 GPU |
| **M1: Pretrain** | 2 wk | `ckpt_pretrain.pt` | Caption BLEU within 15% of LLaVA-1.5 |
| **M2: Video Extension** | 2 wk | `ckpt_video.pt` | VideoChatGPT eval >2.5/5 |
| **M3: Instruction Tuning** | 2 wk | `ckpt_instruct.pt` | LLaVA-Bench >75% Gemini-3.5 |
| **M4: Data Capture Protocol** | 1 wk | 50h pilot dataset | Whisper confidence >0.9, BLEU vs Gemini >0.6 |
| **M5: Teacher Distillation** | 3 wk | `ckpt_cortex.pt` | Blind test: local indistinguishable from Gemini in >30% of cases |
| **M6: QAT + ONNX Export** | 1 wk | `cortex_local.onnx` + calibration set | <2% accuracy drop vs float32 |
| **M7: RPi5 CPU Runtime** | 2 wk | End-to-end on RPi5 | <1s latency, continuous audio output |
| **M8: Hailo Compilation** | 2 wk | `cortex_local.hef` | <200ms latency, 8h soak test |
| **M9: Full Integration** | 1 wk | PR to `rpi5/` | No regressions, SAVH-validated |

**Total Timeline:** ~17 weeks with 1 ML engineer + 1 embedded engineer

---

## 8. Risk Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Mamba-2 ops not in Hailo DFC whitelist | High | Pre-flight with dummy 1-layer Mamba. Fallback to RWKV-v7 if fails. |
| 95M INT8 exceeds Hailo SRAM | High | Layer-by-layer PCIe streaming. Shrink to 50M (8 layers) if needed. |
| Teacher distillation data quality poor | Medium | Filter with Whisper conf >0.9 and BLEU >0.6. Budget 3 weeks for real capture. |
| Hailo compilation fails on state I/O | Medium | Export Mamba as separate subgraph. Run Mamba on CPU (~50 ms) and only Encoders on Hailo. |
| Audio latency >500 ms target on CPU | High | Overlap-add: generate 2 tokens per step. Pre-buffer with Kokoro. |
| Tool calling accuracy <0.8 vs Gemini | Medium | Add explicit tool-F1 metric. Increase tool-call examples in stage 4. |
| Hailo DKMS still broken at M8 | High | Path A (CPU) ships M7 regardless. NPU is a bonus, not a blocker. |

---

## 9. Cost Estimate

| Item | Cost |
|---|---|
| Datacenter GPU rental (8x H100, ~6 weeks active) | ~$10,000 |
| Dataset storage (50 TB raw + processed) | ~$1,000 |
| SAVH volunteer recording sessions | ~$2,000 |
| Hailo SW Suite / dev kit (if not owned) | ~$300 |
| **Total** | **~$13,300** |

---

## 10. Appendix: Why This Architecture?

### Why text output instead of audio tokens?
We already have Kokoro TTS at <50 ms locally. Predicting text is:
- Easier to train (any VQA dataset works)
- Easier to debug (read the text; diff with Gemini transcripts)
- Easier to quantize (vocab size 32k vs codebook 256×4)
- Consistent voice (Kokoro voice is same as existing offline TTS)
- Tool-callable (audio tokens can't invoke `start_navigation`)

### Why Mamba-2 instead of Transformer or GRU?
| Property | Mamba-2 | Transformer | GRU |
|---|---|---|---|
| Long-range quality | SOTA | SOTA | Poor |
| Streaming frames one-by-one | Native | Must recompute | Native |
| Memory at inference | Constant | KV-cache grows | Constant |
| Hailo compileability | Conv1D + element-wise | No (no MHA) | Native |
| Video-language results | VideoMamba beats ViT | Best if compute free | Not competitive |

### Why MobileCLIP-S2 for vision?
- 35M params (fits Hailo)
- CLIP-aligned (open-vocabulary, no need to pretrain vision-language from scratch)
- Conv-based (Hailo-friendly)
- Apple-trained on 1B pairs (strong priors)

### Why not pure CPU forever?
95M INT8 on RPi5 4-core ARM runs at ~400-800 ms per token. For a 15-word response (~20 tokens), that's 8-16 seconds of compute before audio starts. Hailo brings this to <200 ms per token, making the UX viable. The CPU path exists as a graceful degraded fallback ("I can still guide you, slowly").

---

*Document Version: 2.0*  
*Author: Haziq (@IRSPlays) + AI Planning Agent*  
*Date: May 2026*  
*Next Review: After M0 (training infra) completion*
