"""Reference Silero v4 probabilities from onnxruntime, for the C++ port's test.

usage: gen_golden.py silero_vad.onnx out_dir wav [wav ...]
For each wav (16 kHz mono s16), writes <stem>.vad.f32: one f32 per 512-sample chunk
(state carried across chunks, a trailing partial chunk dropped).
"""
import os
import sys
import wave

import numpy as np
import onnxruntime as ort

sess = ort.InferenceSession(sys.argv[1], providers=["CPUExecutionProvider"])
out_dir = sys.argv[2]
os.makedirs(out_dir, exist_ok=True)
for path in sys.argv[3:]:
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    h = np.zeros((2, 1, 64), np.float32)
    c = np.zeros((2, 1, 64), np.float32)
    sr = np.array(16000, np.int64)
    probs = []
    for i in range(len(pcm) // 512):
        o, h, c = sess.run(None, {"input": pcm[None, i * 512:(i + 1) * 512], "sr": sr, "h": h, "c": c})
        probs.append(float(o[0, 0]))
    p = np.array(probs, np.float32)
    stem = os.path.splitext(os.path.basename(path))[0]
    p.tofile(os.path.join(out_dir, stem + ".vad.f32"))
    print(stem, len(p), "chunks; max %.3f; >0.5: %d" % (p.max(), int((p > 0.5).sum())))
