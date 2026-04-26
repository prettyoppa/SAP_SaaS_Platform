"""One-off: add light outer stroke to logo for dark mode preview. Not imported by app."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo.png"
OUT = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo_dark.png"


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    w, h = im.size
    alpha = im.split()[3]
    # Solid silhouette (cat + SAP graphic)
    mask = alpha.point(lambda p: 255 if p > 8 else 0)

    expanded = mask
    for _ in range(4):
        expanded = expanded.filter(ImageFilter.MaxFilter(5))

    ring = ImageChops.subtract(expanded, mask)

    stroke = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px_ring = ring.load()
    px_stroke = stroke.load()
    # Soft cool-white outline, readable on dark navbar
    color = (248, 250, 255, 235)
    for y in range(h):
        for x in range(w):
            if px_ring[x, y] > 0:
                px_stroke[x, y] = color

    stroke = stroke.filter(ImageFilter.GaussianBlur(radius=0.8))

    # Stroke behind artwork
    composed = Image.alpha_composite(stroke, im)
    composed.save(OUT, optimize=True)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
