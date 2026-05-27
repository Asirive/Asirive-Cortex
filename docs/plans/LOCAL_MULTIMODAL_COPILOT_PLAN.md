# Local Multimodal Copilot Plan
## Hailo 8L Audio+Video -> Audio Model Architecture

**Objective:** Build a fully custom audio+video -> audio generative model that runs natively on the Hailo 8L NPU (13 TOPS INT8) inside Asirive Cortex. This model acts as a **local offline fallback** for Gemini Live, providing conversational scene understanding when cloud connectivity is unavailable (MRT tunnels, underground malls, weak signal areas).

**Constraint:** Hailo 8L is INT8-only, has a fixed DFC operator whitelist, and no native transformer support. The architecture must be designed *for* the silicon, not adapted to it.

---

## 0. Scope & Team Split

> **This document is a cross-team contract. Each team owns their deliverables.**

| Team | Agent | Deliverables |
|:---|:---|:---|
| **Model Training** | *Other agent* | Dataset curation, PyTorch training, QAT, ONNX export, Hailo `.hef` compilation, SoundStream codec trainer |
| **RPi5 Software** | *This agent* | Audio/video preprocessing, Hailo runtime wrapper, audio decoder integration, `main.py` fallback state machine, threading architecture |

**Interface Contract:**
- Training team delivers a single file: `models/hailo/copilot_av2a.hef`
- Training team delivers a single file: `models/soundstream_tiny_decoder.pt` (or `.onnx`)
- RPi5 team provides the runtime that loads and runs these files
- **No code sharing** — RPi5 team does not touch training code; training team does not touch RPi5 runtime code

**What this document covers:**
- Architecture design (both teams must agree on shapes and ops)
- RPi5 runtime integration plan and interfaces
- Data formats and tensor contracts between subsystems
- Deployment checklist

**What this document does NOT cover:**
- PyTorch training loops, loss functions, optimizer configs (training team)
- Datacenter GPU allocation, dataset scraping, labeling pipelines (training team)
- Hailo DFC compilation commands beyond the interface contract (training team)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INFERENCE PIPELINE (RPi5)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐    ┌──────────────┐                                      │
│   │  1kHz Audio  │    │  2 FPS Video │                                      │
│   │   Stream     │    │   224x224    │                                      │
│   └──────┬───────┘    └──────┬───────┘                                      │
│          │                   │                                              │
│          ▼                   ▼                                              │
│   ┌──────────────┐    ┌──────────────┐                                      │
│   │  Mel Spectr. │    │  Normalize   │                                      │
│   │  [80, 100]   │    │  [3,224,224] │                                      │
│   └──────┬───────┘    └──────┬───────┘                                      │
│          │                   │                                              │
│          ▼                   ▼                                              │
│   ┌──────────────────────────────────────┐                                  │
│   │         HAILO 8L NPU (INT8)          │                                  │
│   │  ┌──────────┐      ┌──────────┐      │                                  │
│   │  │ Audio    │      │ Video    │      │                                  │
│   │  │ Encoder  │      │ Encoder  │      │                                  │
│   │  │ [1,80,100│      │[3,224,224│      │                                  │
│   │  │ -> 128   │      │ -> 128   │      │                                  │
│   │  └────┬─────┘      └────┬─────┘      │                                  │
│   │       │                 │            │                                  │
│   │       └────────┬────────┘            │                                  │
│   │                ▼                     │                                  │
│   │         ┌──────────┐                 │                                  │
│   │         │ Concat   │                 │                                  │
│   │         │ [1, 320] │                 │                                  │
│   │         └────┬─────┘                 │                                  │
│   │              ▼                       │                                  │
│   │         ┌──────────┐                 │                                  │
│   │         │ 2-Layer  │                 │                                  │
│   │         │ Bi-GRU   │                 │                                  │
│   │         │ 256 dim  │                 │                                  │
│   │         └────┬─────┘                 │                                  │
│   │              ▼                       │                                  │
│   │         ┌──────────┐                 │                                  │
│   │         │ Token    │                 │                                  │
│   │         │ Heads    │                 │                                  │
│   │         │ [K, N]   │                 │                                  │
│   │         └────┬─────┘                 │                                  │
│   └──────────────┼───────────────────────┘                                  │
│                  │                                                          │
│                  ▼                                                          │
│   ┌──────────────────────────────────────┐                                  │
│   │         RPi5 CPU (float32)           │                                  │
│   │  ┌──────────┐    ┌──────────────┐    │                                  │
│   │  │ Argmax   │ -> │ Codebook     │    │                                  │
│   │  │ per book │    │ Lookup       │    │                                  │
│   │  └────┬─────┘    └──────┬───────┘    │                                  │
│   │       │                 │            │                                  │
│   │       └────────┬────────┘            │                                  │
│   │                ▼                     │                                  │
│   │         ┌──────────────┐             │                                  │
│   │         │ SoundStream  │             │                                  │
│   │         │ Decoder      │             │                                  │
│   │         │ (1.5MB tiny) │             │                                  │
│   │         └──────┬───────┘             │                                  │
│   │                ▼                     │                                  │
│   │         ┌──────────────┐             │                                  │
│   │         │ 24kHz PCM    │             │                                  │
│   │         │ Audio Out    │             │                                  │
│   │         └──────────────┘             │                                  │
│   └──────────────────────────────────────┘                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Details

### 2.1 Video Encoder: MobileNetV3-Small

**Why:** All depthwise-separable convolutions, no attention, Hailo DFC compiles cleanly. Pretrained ImageNet weights give strong visual priors.

**Input:** `[1, 3, 224, 224]` (RGB frame, 2 FPS)
**Output:** `[1, 128]` visual embedding

```python
class VideoEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        backbone = mobilenet_v3_small(pretrained=True)
        # Remove classifier, keep features
        self.features = backbone.features  # [1, 576, 7, 7] at end
        self.pool = nn.AdaptiveAvgPool2d(1)  # [1, 576, 1, 1]
        self.proj = nn.Linear(576, 128)      # [1, 128]

    def forward(self, x):
        x = self.features(x)
        x = self.pool(x).flatten(1)
        x = self.proj(x)
        return x
```

**Hailo Notes:**
- `hardswish` activations in MobileNetV3 are supported natively by Hailo DFC v3.28+
- If older Hailo suite, replace with `ReLU6` in training and re-export

---

### 2.2 Audio Encoder: Lightweight Mel-CNN

**Why:** We need a 1-second audio context window. Mel spectrogram is the standard audio representation and maps naturally to 2D convolutions (Hailo's strongest operator).

**Preprocessing (CPU, ~2ms on RPi5):**
```python
import librosa
import numpy as np

def preprocess_audio(pcm_16khz: np.ndarray) -> np.ndarray:
    """Convert 1-second PCM chunk to mel spectrogram."""
    mel = librosa.feature.melspectrogram(
        y=pcm_16khz.astype(np.float32) / 32768.0,
        sr=16000,
        n_mels=80,
        n_fft=512,
        hop_length=160,   # 10ms hop -> 100 frames per second
        win_length=400,   # 25ms window
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)  # [80, 100]
    # Normalize to [-1, 1] for INT8 calibration
    mel_norm = np.clip(mel_db / 80.0, -1.0, 1.0)
    return mel_norm[np.newaxis, ...]  # [1, 80, 100]
```

**Encoder Architecture:**
```python
class AudioEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        # Input: [1, 80, 100]
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, stride=(2, 2), padding=1),   # [32, 40, 50]
            nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=(2, 2), padding=1),  # [64, 20, 25]
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, stride=(2, 2), padding=1), # [128, 10, 12]
            nn.ReLU(),
        )
        self.pool = nn.AdaptiveAvgPool2d(1)  # [128, 1, 1]
        self.proj = nn.Linear(128, 128)       # [128]

    def forward(self, x):
        x = self.conv(x)
        x = self.pool(x).flatten(1)
        x = self.proj(x)
        return x
```

**Hailo Notes:**
- All standard Conv2D + ReLU + AvgPool2d. Zero exotic ops.
- Input is fixed at `[1, 1, 80, 100]`.

---

### 2.3 Fusion Core: Bi-GRU (Stateful)

**Why:** Hailo supports GRU natively. Transformers (self-attention) are **not** in the Hailo DFC operator whitelist for 8L. GRU gives temporal memory across 1-second audio chunks without needing KV-cache.

**Architecture:**
```python
class FusionGRU(nn.Module):
    def __init__(self, input_dim=256, hidden_dim=256, num_layers=2):
        super().__init__()
        self.gru = nn.GRU(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=False,  # Unidirectional for streaming
        )
        # Hidden state is managed ON CPU, not inside the model

    def forward(self, x, h_prev):
        """
        x: [1, 1, 256]  (concatenated audio+video embedding)
        h_prev: [num_layers, 1, 256] (carried from previous chunk)
        Returns: output [1, 1, 256], h_next [num_layers, 1, 256]
        """
        out, h_next = self.gru(x, h_prev)
        return out, h_next
```

**Key Design Decision:**
- The hidden state `h_prev` is **not** part of the Hailo model graph.
- After each inference, RPi5 CPU extracts `h_next` from the Hailo output tensor.
- Before the next inference, CPU feeds `h_prev` back as an additional input tensor.
- This gives the model **infinite temporal context** with fixed NPU memory.

**Hailo Stateful Inference:**
```python
# Hailo runtime (pseudo-code)
input_tensors = {
    'audio': mel_buffer,      # [1, 1, 80, 100]
    'video': frame_buffer,    # [1, 3, 224, 224]
    'h_prev': hidden_state,   # [2, 1, 256] - state from last chunk
}
output_tensors = model.run(input_tensors)
token_logits = output_tensors['tokens']   # [K, N]
hidden_state = output_tensors['h_next']     # [2, 1, 256] - save for next chunk
```

---

### 2.4 Output Head: RVQ Token Prediction

**Why:** Generating raw audio waveforms on NPU is impossible (high output dimension, autoregressive). Predicting discrete tokens from a small codebook is a classification problem — perfect for INT8.

**Audio Codec: Tiny SoundStream (1.5MB decoder)**
- Encoder (training only): Compresses 24kHz waveform to latent vectors
- RVQ Quantizer: Maps latents to K codebooks of N entries each
- Decoder (RPi5 CPU): Maps codebook indices back to 24kHz waveform

**Recommended RVQ config:**
| Parameter | Value | Rationale |
|---|---|---|
| Codebooks (K) | 4 | 4-step residual refinement |
| Entries per book (N) | 256 | Small enough for INT8 softmax |
| Latent dim | 32 | Compact representation |
| Frame rate | 50 Hz | 20ms per frame, 50 tokens/sec |

**Output Head Architecture:**
```python
class TokenHead(nn.Module):
    def __init__(self, hidden_dim=256, num_codebooks=4, codebook_size=256):
        super().__init__()
        self.num_codebooks = num_codebooks
        self.codebook_size = codebook_size
        # One FC per codebook (no shared weights — each book specializes)
        self.heads = nn.ModuleList([
            nn.Linear(hidden_dim, codebook_size) for _ in range(num_codebooks)
        ])

    def forward(self, x):
        """
        x: [1, 256] (final GRU output)
        Returns: [num_codebooks, codebook_size] logits
        """
        logits = torch.stack([head(x) for head in self.heads], dim=0)
        return logits  # [K, N]
```

**Training Target:**
For each 20ms audio frame, the SoundStream encoder produces K discrete indices `[c1, c2, c3, c4]`. The model learns to predict these indices from audio+video context.

**Loss:** Sum of cross-entropy losses across codebooks
```python
loss = sum(F.cross_entropy(logits[i], targets[i]) for i in range(K))
```

---

## 3. Full Model Specification

| Component | Parameters | Hailo Ops | Input Shape | Output Shape |
|---|---|---|---|---|
| Video Encoder (MobileNetV3-small) | ~2.5M | Conv2D, DWConv, ReLU, AvgPool | `[1, 3, 224, 224]` | `[1, 128]` |
| Audio Encoder (Mel-CNN) | ~150K | Conv2D, ReLU, AvgPool | `[1, 1, 80, 100]` | `[1, 128]` |
| Concat | - | Concat | `[1, 128] + [1, 128]` | `[1, 256]` |
| Fusion GRU (2 layers) | ~400K | GRU | `[1, 1, 256]` + `[2, 1, 256]` | `[1, 1, 256]` + `[2, 1, 256]` |
| Token Heads (4x FC) | ~260K | FC | `[1, 256]` | `[4, 256]` logits |
| **Total** | **~3.3M** | | | |

**INT8 Model Size:** ~3.3 MB (fits easily in Hailo 8L SRAM)
**Expected NPU Latency:** ~25-45ms per inference
**Audio Generation Rate:** 50 tokens/sec -> ~1 second of audio generated per 20ms of NPU compute (with overlapping windows)

---

## 4. Training Pipeline (Datacenter GPUs)

### 4.1 Dataset Construction Strategy

**Primary Method: Teacher Distillation from Gemini Live**

We use the existing Cortex system to generate training triplets at scale:

```
Triplet = (1-sec audio prompt, 2 FPS video clip, 1-sec audio response)
```

**Data Collection Protocol:**
1. Record 500+ hours of first-person walking video with stereo audio (or mono + lavalier)
2. For each 10-second segment, feed into Gemini Live API with the prompt:
   ```
   "You are assisting a blind person. Describe what you see and hear.
   Respond naturally in under 15 words."
   ```
3. Capture Gemini's audio response as the **target**
4. The user's natural speech (or synthetic prompts) is the **audio prompt**
5. Synchronized video frames are the **visual context**

**Dataset Augmentation:**
- **Acoustic:** Add reverb, background noise (MRT, street, mall), pitch shift
- **Visual:** Random brightness/contrast, simulated motion blur, occlusions
- **Temporal:** Random chunk alignment offsets (-200ms to +200ms) to teach robustness
- **Prompt diversity:** Synthetic text-to-speech prompts in Singlish, Mandarin, Malay

**Expected Dataset Size:**
| Phase | Hours | Triplets | Storage |
|---|---|---|---|
| Bootstrap (synthetic) | 100h | 3.6M | ~500 GB |
| Real-world capture | 500h | 18M | ~2.5 TB |
| Augmented (10x) | 6000h | 216M | ~25 TB |

---

### 4.2 Training Stages

#### Stage 1: Pretrain Audio-Only (Audio -> Audio Tokens)
**Goal:** Learn the audio representation and token prediction before adding video.
**Data:** Librispeech + VoxCeleb + Cortex audio recordings (no video)
**Duration:** 3-5 days on 4x A100
**Loss:** Cross-entropy on RVQ tokens
**Checkpoint:** `ckpt_audio_only.pt`

#### Stage 2: Add Video Encoder (Audio+Video -> Audio Tokens)
**Goal:** Fuse visual context into the audio generation.
**Data:** Full triplets from teacher distillation
**Duration:** 5-7 days on 4x A100
**LR:** 1e-4 with cosine decay
**Loss:** Cross-entropy (primary) + KL divergence from teacher (auxiliary)
**Checkpoint:** `ckpt_av_fusion.pt`

#### Stage 3: Quantization-Aware Training (QAT)
**Goal:** Make the model robust to INT8 quantization noise.
**Method:** Fake quantization nodes inserted during training (PyTorch `torch.quantization` or `bitsandbytes`)
**Duration:** 2-3 days on 4x A100
**LR:** 1e-5 (very slow, fine-tuning only)
**Checkpoint:** `ckpt_int8_qat.pt`

#### Stage 4: Knowledge Distillation from Gemini (Optional but Recommended)
**Goal:** The small model should match Gemini's behavior, not just the audio tokens.
**Method:** Run Gemini on held-out set. Train the small model with:
- **Token loss:** Match SoundStream RVQ indices
- **Feature loss:** L2 between GRU hidden states and Gemini's intermediate features (if extractable)
- **Text loss:** Whisper transcription of generated audio should match Gemini's transcript

---

### 4.3 Training Config

```yaml
# config/train_copilot.yaml
model:
  video_encoder: mobilenet_v3_small
  audio_encoder:
    channels: [1, 32, 64, 128]
    kernels: [3, 3, 3]
    strides: [2, 2, 2]
  fusion:
    type: gru
    hidden_dim: 256
    num_layers: 2
    bidirectional: false
  token_head:
    num_codebooks: 4
    codebook_size: 256

audio:
  sample_rate: 24000          # Target output rate (matches Gemini Live)
  prompt_sample_rate: 16000   # Input microphone rate
  n_mels: 80
  hop_length: 160
  win_length: 400
  n_fft: 512
  chunk_duration: 1.0         # 1-second context window

video:
  resolution: [224, 224]
  fps: 2
  normalize_mean: [0.485, 0.456, 0.406]
  normalize_std: [0.229, 0.224, 0.225]

soundstream:
  encoder_rates: [2, 2, 2, 2]     # 24kHz -> 1.5kHz latent
  decoder_rates: [2, 2, 2, 2]
  latent_dim: 32
  num_codebooks: 4
  codebook_size: 256

training:
  batch_size: 128
  num_workers: 16
  max_epochs: 50
  learning_rate: 1e-3
  weight_decay: 1e-4
  warmup_steps: 5000
  gradient_clip: 1.0
  mixed_precision: true
  compile: true               # torch.compile for A100

qat:
  enabled: true
  observer: moving_average_minmax
  quant_scheme: symmetric
  backend: fbgemm             # Stand-in for Hailo INT8 behavior
```

---

## 5. Hailo Deployment Pipeline

### 5.1 ONNX Export (Fixed Shapes)

```python
import torch
import torch.onnx

model = load_model("ckpt_int8_qat.pt")
model.eval()

# Dummy inputs with EXACT shapes Hailo will see
dummy_audio = torch.randn(1, 1, 80, 100)
dummy_video = torch.randn(1, 3, 224, 224)
dummy_h_prev = torch.randn(2, 1, 256)

torch.onnx.export(
    model,
    (dummy_audio, dummy_video, dummy_h_prev),
    "copilot_av2a.onnx",
    input_names=["audio", "video", "h_prev"],
    output_names=["tokens", "h_next"],
    dynamic_axes=None,  # CRITICAL: Hailo requires static shapes
    opset_version=11,
    do_constant_folding=True,
)
```

### 5.2 Hailo Dataflow Compiler

```bash
# Run on x86 Linux workstation with Hailo SW Suite installed

# 1. Parse ONNX
hailo parser onnx copilot_av2a.onnx --output copilot.hailo

# 2. Optimize (operator fusion, memory layout)
hailo optimize copilot.hailo --output copilot_opt.hailo

# 3. Quantization Calibration
# Use 1000 representative samples from training set
hailo quantize copilot_opt.hailo \
    --calib-set ./calibration_data/ \
    --output copilot_quant.hailo

# 4. Compile to HEF (Hailo Execution Format)
hailo compile copilot_quant.hailo \
    --output copilot_av2a.hef \
    --performance-calibration

# Expected output: copilot_av2a.hef (~4 MB)
```

### 5.3 RPi5 Runtime Integration

```python
"""
copilot_hailo_runtime.py
Runs inside rpi5/main.py as a fallback when Gemini Live is offline.
"""
import numpy as np
import librosa
import torch
from hailo_platform import VDevice, InferModel

class LocalCopilot:
    def __init__(self, hef_path: str = "models/hailo/copilot_av2a.hef"):
        self.vdevice = VDevice()
        self.model = InferModel(self.vdevice, hef_path)

        # State management (CPU-side)
        self.hidden_state = np.zeros((2, 1, 256), dtype=np.float32)
        self.audio_buffer = np.zeros(16000, dtype=np.int16)  # 1-second ring buffer
        self.last_video_frame = None

        # Tiny SoundStream decoder (runs on CPU, ~5ms)
        self.audio_decoder = TinySoundStreamDecoder(
            checkpoint="models/soundstream_tiny_decoder.pt"
        )

        # Token history for smoothing (avoid audio glitches)
        self.token_history = []

    def ingest_audio(self, pcm_chunk: np.ndarray):
        """Feed 16kHz PCM chunk (e.g., 512 samples = 32ms)."""
        self.audio_buffer = np.roll(self.audio_buffer, -len(pcm_chunk))
        self.audio_buffer[-len(pcm_chunk):] = pcm_chunk

    def ingest_video(self, frame: np.ndarray):
        """Feed latest BGR frame [H, W, 3] from camera."""
        # Resize + normalize (CPU, ~1ms)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (224, 224))
        frame_norm = (frame_resized / 255.0 - np.array([0.485, 0.456, 0.406])) \
                     / np.array([0.229, 0.224, 0.225])
        self.last_video_frame = frame_norm.transpose(2, 0, 1)[np.newaxis, ...]  # [1, 3, 224, 224]

    def generate_audio(self) -> np.ndarray:
        """
        Run inference and decode to 24kHz PCM.
        Call every 20ms for continuous audio generation.
        Returns: 480 samples of 24kHz int16 PCM (20ms)
        """
        # 1. Preprocess audio (CPU, ~2ms)
        mel = self._compute_mel(self.audio_buffer)

        # 2. Hailo inference (~30ms)
        outputs = self.model.run({
            "audio": mel[np.newaxis, ...],        # [1, 1, 80, 100]
            "video": self.last_video_frame,       # [1, 3, 224, 224]
            "h_prev": self.hidden_state,          # [2, 1, 256]
        })

        token_logits = outputs["tokens"]           # [4, 256] logits
        self.hidden_state = outputs["h_next"]      # [2, 1, 256]

        # 3. Argmax to get codebook indices (CPU, negligible)
        token_indices = np.argmax(token_logits, axis=-1)  # [4]

        # 4. Decode to waveform (CPU, ~5ms)
        pcm_24khz = self.audio_decoder.decode(token_indices)  # [480] samples

        return (pcm_24khz * 32767).astype(np.int16)

    def _compute_mel(self, pcm: np.ndarray) -> np.ndarray:
        mel = librosa.feature.melspectrogram(
            y=pcm.astype(np.float32) / 32768.0,
            sr=16000, n_mels=80, n_fft=512,
            hop_length=160, win_length=400,
        )
        mel_db = librosa.power_to_db(mel, ref=np.max)
        return np.clip(mel_db / 80.0, -1.0, 1.0)[np.newaxis, ...]  # [1, 80, 100]
```

---

## 6. Integration with Cortex

### 6.1 Fallback Logic in `main.py`

```python
class CortexSystem:
    def __init__(self, ...):
        self.gemini_live = GeminiLiveManager(...)  # Primary (cloud)
        self.local_copilot = LocalCopilot(...)     # Fallback (Hailo)
        self.active_audio_source = "gemini"        # "gemini" or "local"

    def _on_audio_tick(self):
        """Called every 20ms by the audio thread."""
        if self.gemini_live.is_connected and self.gemini_live.is_receiving:
            # Gemini is active and streaming audio — use it
            self.active_audio_source = "gemini"
            pcm = self.gemini_live.dequeue_audio()
            self.speaker.play(pcm)
        else:
            # Gemini offline or not responding — switch to local
            if self.active_audio_source == "gemini":
                self.tts.speak("Switching to offline mode.")
                self.active_audio_source = "local"

            pcm = self.local_copilot.generate_audio()
            self.speaker.play(pcm)
```

### 6.2 Graceful Handoff

When connectivity drops:
1. Gemini WebSocket detects disconnect
2. `main.py` sets `active_audio_source = "local"`
3. Local copilot starts generating from the **same** hidden state context
4. User hears: *"I'm switching to offline mode. I can still guide you."* (pre-recorded TTS)
5. When Gemini reconnects, hidden state is **not** carried over — audio seamlessly switches back

---

## 7. Development Milestones

| Milestone | Duration | Deliverable | Success Criteria |
|---|---|---|---|
| **M0: SoundStream Trainer** | 2 weeks | Working RVQ audio codec | Reconstruct 24kHz speech at >3.5 MOS |
| **M1: Audio-Only Baseline** | 3 weeks | Audio -> Tokens model | <50ms inference on A100, BLEU vs transcript >0.4 |
| **M2: Add Video Fusion** | 2 weeks | Audio+Video -> Tokens | Video improves token accuracy by >10% over audio-only |
| **M3: QAT + ONNX Export** | 1 week | INT8 QAT model + ONNX | <1% accuracy drop vs float32 |
| **M4: Hailo Compilation** | 1 week | `.hef` file | Successful compilation, no unsupported ops |
| **M5: RPi5 Integration** | 2 weeks | End-to-end runtime | <100ms end-to-end latency, continuous audio output |
| **M6: Teacher Distillation** | 3 weeks | Fine-tuned on Gemini data | Blind test: users can't tell local vs Gemini 70% of time |
| **M7: Cortex Integration** | 1 week | PR to `rpi5/` | Graceful fallback, no crashes, SAVH-validated |

**Total Timeline:** ~15 weeks (3.5 months) with 1 ML engineer + 1 embedded engineer

---

## 8. Risk Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| GRU performance on Hailo worse than expected | High | Fallback to unidirectional LSTM (also supported). Reduce hidden dim to 128. |
| SoundStream decoder too slow on RPi5 CPU | High | Pre-distill to HiFi-GAN-tiny (~1MB). Or use non-neural vocoder (Griffin-Lim, ~15ms). |
| Dataset quality poor (synthetic distillation) | Medium | Budget 2 weeks for real-world capture with SAVH volunteers. Use data filtering (Whisper confidence >0.9). |
| Hailo compilation fails on GRU state I/O | Medium | Export GRU as separate subgraph. Run GRU on RPi5 CPU (~5ms) and only Conv/FC on Hailo. |
| Audio latency >100ms target | High | Overlap-add: generate 40ms of audio per 20ms tick. Pre-buffer 2 frames. |

---

## 9. Cost Estimate

| Item | Cost |
|---|---|
| Datacenter GPU rental (4x A100, 3 months) | ~$8,000 |
| Hailo 8L dev kit (if not already owned) | ~$250 |
| Data storage (25TB) | ~$500 |
| SAVH volunteer recording sessions | ~$1,000 (honorariums) |
| **Total** | **~$9,750** |

---

## 10. Appendix: Why This Architecture?

### Why not a Transformer?
Hailo 8L DFC does **not** support Multi-Head Attention (MHA) natively. You would need to decompose attention into Conv1D + MatMul ops, which is inefficient on Hailo's systolic array. GRU gives 90% of the temporal modeling at 10% of the op complexity.

### Why not WaveRNN / WaveNet for audio?
Autoregressive waveform generation requires thousands of sequential steps per second. On RPi5 CPU, WaveRNN runs at ~2kHz — far below real-time. Predicting discrete tokens and using a parallel decoder (SoundStream) is **50x faster**.

### Why 2 FPS video?
Scene understanding does not need 30 FPS. 2 FPS reduces PCIe bandwidth by 15x and gives the model temporal stability (less flicker in embeddings). Audio is the high-rate modality; video is the low-rate context.

### Why 1-second audio chunks?
Shorter = less latency but less context. Longer = more context but higher latency. 1 second balances:
- Enough to capture a short phrase
- Fits within 100ms target when overlapped
- 100 mel frames is a clean power-of-2 friendly shape for Conv2D

---

*Document Version: 1.0*
*Author: AI Planning Agent*
*Date: May 2026*
*Next Review: After M0 (SoundStream trainer) completion*
