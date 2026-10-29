"""Real-time safety service. Depends on local sensors and local outputs ONLY.

Hard rule (core/AGENTS.md section 3): nothing in this package may import the agent,
voice, perception, link, ota, network or phone code. tests/test_safety.py enforces it.
"""
