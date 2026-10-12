"""Quick test for the new router."""
import sys
sys.path.insert(0, 'rpi5')
from layer3_guide.router import IntentRouter

r = IntentRouter()

tests = [
    ('Voice command for a navigation assistant.', 'ignore'),
    ('Currently I am at home and I want to go to North Point.', 'layer3'),
    ('I explain what you think.', 'layer2'),
    ('Museum my navigation to now an off point.', 'layer3'),
    ('On screen.', 'layer2'),  # Garbled STT → Gemini handles gracefully
    ('Side.', 'ignore'),
    ('What do you know about me?', 'layer2'),
    ('What do you see?', 'layer1'),
    ('navigate to the bus stop', 'layer3'),
    ('resume navigation to northpoint', 'layer3'),
    ('describe the scene', 'layer2'),
    ('read that sign', 'layer2'),
    ('how many people are there', 'layer1'),
    ('take me to the food court', 'layer3'),
    ('what bus is coming', 'layer3'),
    ('tell me a joke', 'layer2'),
    ('who is that person', 'layer2'),
    ('what time is it', 'layer2'),
    ('stop', 'layer1'),  # Safety command
    ('look', 'layer1'),
]

pass_count = 0
fail_count = 0
for text, expected in tests:
    result = r.route(text)
    status = 'PASS' if result == expected else 'FAIL'
    if status == 'FAIL':
        fail_count += 1
        print(f'  {status}: "{text}" -> {result} (expected {expected})')
    else:
        pass_count += 1
        print(f'  {status}: "{text}" -> {result}')
print(f'\nResults: {pass_count}/{len(tests)} passed, {fail_count} failed')
