"""Write a data URL to a file from an SVG file (double-base64-wrapped HTML)."""
import base64
import sys


def main(svg_path: str, out_path: str) -> None:
    svg = open(svg_path, "rb").read()
    svg_b64 = base64.b64encode(svg).decode()
    html = (
        '<!doctype html><html><body style="margin:0;background:#000">'
        f'<img src="data:image/svg+xml;base64,{svg_b64}" '
        'style="display:block;width:100vw"></body></html>'
    )
    html_b64 = base64.b64encode(html.encode()).decode()
    data_url = f"data:text/html;base64,{html_b64}"
    open(out_path, "w", encoding="utf-8").write(data_url)
    print(f"OK wrote {out_path} ({len(data_url)} bytes)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
