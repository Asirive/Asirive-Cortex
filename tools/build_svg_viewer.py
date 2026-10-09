"""Build an HTML viewer for an SVG file (base64-embedded) and a PNG snapshot path.
Run with: python build_svg_viewer.py <svg_path> <html_out>"""
import base64
import sys

def main(svg_path: str, html_out: str) -> None:
    svg = open(svg_path, "rb").read()
    b64 = base64.b64encode(svg).decode()
    html = (
        '<!doctype html><html><head><style>'
        'body{margin:0;background:#000}'
        'img{display:block;width:100vw;height:auto}'
        '</style></head><body>'
        f'<img src="data:image/svg+xml;base64,{b64}">'
        '</body></html>'
    )
    open(html_out, "w", encoding="utf-8").write(html)
    print(f"OK wrote {html_out} ({len(html)} bytes)")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
