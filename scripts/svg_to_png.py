"""Convert Textual SVG screenshot to PNG using resvg-py.
Usage: python scripts/svg_to_png.py <svg_path> <png_path>
"""
import resvg_py
import sys
from pathlib import Path

svg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'C:\Users\Haziq\Documents\ProjectCortex\scripts\cortex_full_screenshot.svg')
png_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r'C:\Users\Haziq\Documents\ProjectCortex\scripts\cortex_full_screenshot.png')

if not svg_path.exists():
    print(f'SVG not found: {svg_path}', file=sys.stderr)
    sys.exit(1)

svg_bytes = svg_path.read_bytes()
try:
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_bytes.decode('utf-8'))
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(bytes(png_bytes))
    print(f'Wrote {png_path} ({len(png_bytes)} bytes)')
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
