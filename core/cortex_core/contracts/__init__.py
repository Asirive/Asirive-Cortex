"""Generated protobuf types (scripts/gen_proto.sh). Services import types from here only.

The generated package imports itself as `cortex.v1`, so its root goes on sys.path once.
"""
import os
import sys

_gen = os.path.join(os.path.dirname(__file__), "gen")
if _gen not in sys.path:
    sys.path.insert(0, _gen)

from cortex.v1 import common_pb2, local_pb2, ota_pb2, session_pb2  # noqa: E402,F401
