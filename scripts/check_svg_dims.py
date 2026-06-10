"""Check SVG dimensions of screenshot."""
import re
import sys

path = sys.argv[1]
with open(path, "r") as f:
    content = f.read()
m = re.search(r'<svg[^>]*width="(\d+)"[^>]*height="(\d+)"', content)
if m:
    print(f"SVG dimensions: {m.group(1)} cols x {m.group(2)} rows")
else:
    print("No dimensions found in SVG")
