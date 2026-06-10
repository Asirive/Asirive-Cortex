"""Convert Textual SVG screenshot to PNG using resvg-py."""
import resvg_py
import sys

svg_path = r'C:\Users\Haziq\Documents\ProjectCortex\scripts\cortex_full_screenshot.svg'
png_path = r'C:\Users\Haziq\Documents\ProjectCortex\scripts\cortex_full_screenshot.png'

with open(svg_path, 'rb') as f:
    svg_bytes = f.read()
try:
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_bytes.decode('utf-8'))
    with open(png_path, 'wb') as f:
        f.write(bytes(png_bytes))
    print(f'Wrote {png_path} ({len(png_bytes)} bytes)')
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
