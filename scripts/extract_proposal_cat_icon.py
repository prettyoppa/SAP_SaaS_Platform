"""로고에서 SAP 블루·흰 글자 영역을 투명 처리해 고양이만 남긴 PNG 생성 (제안서 생성 화면 아이콘용)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo.png"
OUT = ROOT / "app" / "static" / "img" / "proposal_generating_cat.png"


def main() -> None:
    im = Image.open(SRC).convert("RGBA")
    arr = np.asarray(im).copy()
    r = arr[:, :, 0].astype(np.int16)
    gch = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    a = arr[:, :, 3]

    white = (r > 195) & (gch > 195) & (b > 195)
    # SAP 면 블루
    sap_blue = (
        (a > 40)
        & ~white
        & (b > r + 22)
        & (b > gch + 6)
        & (r < 145)
        & (r + gch + b < 420)
    )
    # 등록 마크 등 아주 작은 흰/회색 장식은 유지하고, 큰 덩어리(글자)만 제거하기 어려우므로
    # 순백에 가까운 SAP 글자만 제거 (고양이 눈은 보통 완전 255×3은 아님)
    letter_white = (a > 200) & (r > 248) & (gch > 248) & (b > 248)

    sap_u8 = (sap_blue.astype(np.uint8) * 255)
    sap_img = Image.fromarray(sap_u8, mode="L")
    for _ in range(3):
        sap_img = sap_img.filter(ImageFilter.MaxFilter(5))
    sap_fat = np.asarray(sap_img) > 0

    kill = sap_fat | letter_white
    arr[kill] = [0, 0, 0, 0]

    # 알파 0인 행·열 잘라 내기
    nz = arr[:, :, 3] > 0
    if not nz.any():
        raise SystemExit("No visible pixels after mask")
    ys, xs = np.where(nz)
    y0, y1 = ys.min(), ys.max()
    x0, x1 = xs.min(), xs.max()
    pad = 4
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(arr.shape[0] - 1, y1 + pad)
    x1 = min(arr.shape[1] - 1, x1 + pad)
    cropped = arr[y0 : y1 + 1, x0 : x1 + 1]

    out_im = Image.fromarray(cropped, mode="RGBA")
    # 아이콘 크기 상한 (레티나 대비 2x)
    max_side = 160
    w, h = out_im.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        out_im = out_im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    out_im.save(OUT, optimize=True)
    print("Wrote", OUT, out_im.size)


if __name__ == "__main__":
    main()
