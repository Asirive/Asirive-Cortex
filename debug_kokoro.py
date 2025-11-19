from kokoro import KPipeline
import numpy as np

pipeline = KPipeline(lang_code='a')
audio_gen = pipeline('Test', voice='af_alloy')
chunks = list(audio_gen)

print(f'Chunks: {len(chunks)}')
print(f'First chunk type: {type(chunks[0])}')
print(f'First chunk: {chunks[0]}')

if len(chunks) > 0:
    arr = np.array(chunks[0], dtype=np.float32)
    print(f'Converted shape: {arr.shape}')
    print(f'Converted dtype: {arr.dtype}')
