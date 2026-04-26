"""다크모드용 로고: 원본 위에 흰 윤곽을 깔되 SAP 블루 영역 밖의 링만 남기고(고양이 실루엣 위주), SAP 로고 외곽 하이로는 제거."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo.png"
OUT = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo_dark.png"


def _dilate_max(mask: Image.Image, passes: int, size: int = 5) -> Image.Image:
    m = mask
    for _ in range(passes):
        m = m.filter(ImageFilter.MaxFilter(size))
    return m


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    w, h = im.size
    arr = np.asarray(im)
    r = arr[:, :, 0].astype(np.int16)
    gch = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    a = arr[:, :, 3]

    white = (r > 195) & (gch > 195) & (b > 195)
    # SAP 로고 면(블루 + 흰 SAP 글자가 아닌 영역) — 고양이/투명 제외
    sap_blue = (
        (a > 40)
        & ~white
        & (b > r + 22)
        & (b > gch + 6)
        & (r < 145)
        & (r + gch + b < 420)
    )
    sap_letters_white = white & (a > 200)

    # 블루 SAP 덩어리 + 약간의 안티앨리어싱 포함(글자 구멍은 제외하기 어려우면 블루 위주)
    sap_mask = sap_blue | sap_letters_white

    sap_img = Image.fromarray((sap_mask.astype(np.uint8) * 255), mode="L")
    # SAP 마스크를 넉넉히 팽창 → 그 주변 링(로고 박스 외곽 하일라이트) 제거용
    sap_fat = _dilate_max(sap_img, passes=6, size=5)

    alpha = im.split()[3]
    solid = alpha.point(lambda p: 255 if p > 8 else 0)
    expanded = _dilate_max(solid, passes=4, size=5)
    ring = ImageChops.subtract(expanded, solid)

    ring_arr = np.asarray(ring) > 0
    sap_fat_arr = np.asarray(sap_fat) > 0
    # 전체 실루엣 링에서 "SAP 덩어리+여유"와 겹치는 픽셀은 제거 → 박스 윤곽 제거, 고양이 돌출부 링은 유지
    keep_ring = ring_arr & (~sap_fat_arr)

    stroke = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    color = (248, 250, 255, 235)
    sx = stroke.load()
    for y in range(h):
        for x in range(w):
            if keep_ring[y, x]:
                sx[x, y] = color

    stroke = stroke.filter(ImageFilter.GaussianBlur(radius=0.75))
    composed = Image.alpha_composite(stroke, im)
    composed.save(OUT, optimize=True)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
