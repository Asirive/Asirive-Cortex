"""Builds conversation.wav: room noise 2 s + question1 + noise 2 s + question2 + noise 1.5 s (16 kHz s16)."""
import sys
import wave

import numpy as np

d = sys.argv[1]


def rd(n):
    with wave.open(f"{d}/{n}") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


noise, q1, q2 = rd("room_noise.wav"), rd("question1.wav"), rd("question2.wav")
pcm = np.concatenate([noise[:32000], q1, noise[32000:64000], q2, noise[56000:80000]])
with wave.open(f"{d}/conversation.wav", "wb") as w:
    w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
    w.writeframes(pcm.astype("<i2").tobytes())
print("conversation.wav", len(pcm) / 16000, "s; q1 at 2.0 s, q2 at", (32000 + len(q1) + 32000) / 16000, "s")
