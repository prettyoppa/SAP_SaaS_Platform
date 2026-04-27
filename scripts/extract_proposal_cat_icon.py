"""로고에서 SAP 블루·흰 글자 영역을 투명 처리해 고양이만 남긴 PNG 생성 (제안서 생성 화면 아이콘용)."""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "catch_lab_sap_dev_hub_logo.png"
OUT = ROOT / "app" / "static" / "img" / "proposal_generating_cat.png"


def binary_fill_holes(mask: np.ndarray) -> np.ndarray:
    """mask가 True인 영역 안에 막힌 False 구멍을 True로 채운다 (scipy 불필요)."""
    m = np.asarray(mask, dtype=bool)
    inv = ~m
    padded = np.pad(inv, 1, mode="constant", constant_values=True)
    ph, pw = padded.shape
    vis = np.zeros((ph, pw), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    q.append((0, 0))
    while q:
        y, x = q.popleft()
        if vis[y, x] or not padded[y, x]:
            continue
        vis[y, x] = True
        if y:
            q.append((y - 1, x))
        if y + 1 < ph:
            q.append((y + 1, x))
        if x:
            q.append((y, x - 1))
        if x + 1 < pw:
            q.append((y, x + 1))
    hole = inv & ~vis[1:-1, 1:-1]
    return m | hole


def largest_connected_component(mask: np.ndarray) -> np.ndarray:
    """8-이웃 연결로 가장 큰 True 덩어리만 남긴다 (®, 잔여 조각 제거)."""
    m = np.asarray(mask, dtype=bool)
    h, w = m.shape
    visited = np.zeros((h, w), dtype=bool)
    best = np.zeros((h, w), dtype=bool)
    best_n = 0
    nbrs = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    for sy in range(h):
        for sx in range(w):
            if not m[sy, sx] or visited[sy, sx]:
                continue
            stack = [(sy, sx)]
            visited[sy, sx] = True
            pts: list[tuple[int, int]] = []
            while stack:
                y, x = stack.pop()
                pts.append((y, x))
                for dy, dx in nbrs:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            if len(pts) > best_n:
                best_n = len(pts)
                best.fill(False)
                for y, x in pts:
                    best[y, x] = True
    return best


def morph_close_bool(mask: np.ndarray, times: int, size: int) -> np.ndarray:
    im = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    for _ in range(times):
        im = im.filter(ImageFilter.MaxFilter(size))
    for _ in range(times):
        im = im.filter(ImageFilter.MinFilter(size))
    return np.asarray(im) > 0


def zap_sap_colored_fringe(arr: np.ndarray) -> None:
    """고채도 블루·흰 계열 찌꺼기만 제거 (고양이 몸통은 대체로 저채도·저명도)."""
    if not (arr[:, :, 3] > 0).any():
        return
    r = arr[:, :, 0].astype(np.float32)
    gch = arr[:, :, 1].astype(np.float32)
    b = arr[:, :, 2].astype(np.float32)
    mx = np.maximum(np.maximum(r, gch), b)
    mn = np.minimum(np.minimum(r, gch), b)
    chroma = mx - mn
    lu = 0.299 * r + 0.587 * gch + 0.114 * b
    a = arr[:, :, 3]
    zap = (
        (a > 18)
        & (chroma > 58.0)
        & (b > r + 12.0)
        & (lu > 62.0)
    ) | ((a > 18) & (r > 210.0) & (gch > 210.0) & (b > 210.0))
    arr[zap] = [0, 0, 0, 0]


def heal_outline_notches_rgba(arr: np.ndarray) -> None:
    """바운딩 박스 안에서 실루엣 외곽 움푹 파인 노치를 closing으로 메운다 (제자리 수정)."""
    nz = arr[:, :, 3] > 12
    if not nz.any():
        return
    ys, xs = np.where(nz)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    pad = 14
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(arr.shape[0] - 1, y1 + pad)
    x1 = min(arr.shape[1] - 1, x1 + pad)
    patch = arr[y0 : y1 + 1, x0 : x1 + 1].copy()
    rp = patch[:, :, 0].astype(np.float32)
    gp = patch[:, :, 1].astype(np.float32)
    bp = patch[:, :, 2].astype(np.float32)
    mxp = np.maximum(np.maximum(rp, gp), bp)
    mnp = np.minimum(np.minimum(rp, gp), bp)
    chroma_p = mxp - mnp
    lu_p = 0.299 * rp + 0.587 * gp + 0.114 * bp
    # 로고의 중간 명도 회색 ‘판’: 클로징이 여기까지 번지며 직사각형 덩어리가 붙는 것을 막음
    plate = (
        (patch[:, :, 3] > 12)
        & (lu_p > 94.0)
        & (lu_p < 124.0)
        & (chroma_p < 36.0)
    )
    m = (patch[:, :, 3] > 12) & ~plate
    m2 = morph_close_bool(m, 5, 5)
    m2 &= ~plate
    add = m2 & ~m
    if m.any():
        med = np.clip(np.median(patch[m, :3], axis=0), 0, 255).astype(np.uint8)
    else:
        med = np.array([30, 30, 34], dtype=np.uint8)
    patch[m2, 3] = 255
    patch[add, :3] = med
    patch[~m2] = [0, 0, 0, 0]
    arr.fill(0)
    arr[y0 : y1 + 1, x0 : x1 + 1] = patch


def largest_cc_touching_seed(mask: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """seed와 겹치는 연결 요소 중 가장 큰 것만 남긴다 (로고 판·글자 덩어리 분리)."""
    m = np.asarray(mask, dtype=bool)
    s = np.asarray(seed, dtype=bool)
    h, w = m.shape
    visited = np.zeros((h, w), dtype=bool)
    best = np.zeros((h, w), dtype=bool)
    best_n = 0
    nbrs = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    for sy in range(h):
        for sx in range(w):
            if not m[sy, sx] or visited[sy, sx]:
                continue
            stack = [(sy, sx)]
            visited[sy, sx] = True
            pts: list[tuple[int, int]] = []
            hit = False
            while stack:
                y, x = stack.pop()
                pts.append((y, x))
                if s[y, x]:
                    hit = True
                for dy, dx in nbrs:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            if hit and len(pts) > best_n:
                best_n = len(pts)
                best.fill(False)
                for y, x in pts:
                    best[y, x] = True
    if best_n == 0:
        return largest_connected_component(m)
    return best


def repair_interior_holes_rgba(rgba: np.ndarray, thr: float = 36.0) -> np.ndarray:
    """실루엣 내부의 작은 투명 구멍을 메우고 RGB는 본체 중앙색에 맞춘다."""
    a = rgba[:, :, 3]
    solid = a > thr
    filled = binary_fill_holes(solid)
    add = filled & ~solid
    if not filled.any():
        return rgba
    vis_rgb = rgba[solid, :3].astype(np.float32)
    if vis_rgb.size:
        med = np.median(vis_rgb, axis=0)
        fill_rgb = np.clip(med, 0, 255).astype(np.uint8)
    else:
        fill_rgb = np.array([28, 28, 32], dtype=np.uint8)
    out = rgba.copy()
    out[filled, 3] = 255
    out[add, :3] = fill_rgb
    return out


def flat_soft_rim_rgba(rgba: np.ndarray) -> np.ndarray:
    """단색 실루엣 + 팽창·이중 블러 알파로 부드러운 테두리(림). 뜯긴 외곽을 시각적으로 메운다."""
    a0 = rgba[:, :, 3].astype(np.float32)
    thr = 26.0
    m = a0 > thr
    m = binary_fill_holes(m)
    m_u8 = (m.astype(np.uint8) * 255)
    im = Image.fromarray(m_u8, mode="L")
    for _ in range(5):
        im = im.filter(ImageFilter.MaxFilter(7))
    for _ in range(5):
        im = im.filter(ImageFilter.MinFilter(7))
    m2 = np.asarray(im) > 128
    m2 = binary_fill_holes(m2)
    m2 = np.asarray(
        Image.fromarray((m2.astype(np.uint8) * 255), mode="L").filter(ImageFilter.MedianFilter(5))
    ) > 96
    rim = Image.fromarray((m2.astype(np.uint8) * 255), mode="L")
    for _ in range(4):
        rim = rim.filter(ImageFilter.MaxFilter(5))
    for _ in range(2):
        rim = rim.filter(ImageFilter.MaxFilter(3))
    a1 = np.asarray(rim.filter(ImageFilter.GaussianBlur(radius=2.05)), dtype=np.float32)
    a2 = np.asarray(
        Image.fromarray(np.clip(a1, 0, 255).astype(np.uint8), mode="L").filter(
            ImageFilter.GaussianBlur(radius=0.85)
        ),
        dtype=np.float32,
    )
    a_final = np.clip(a2, 0, 255)

    nz = a0 > thr
    if nz.any():
        med = np.median(rgba[nz, :3], axis=0).astype(np.float32)
        v = float(np.clip(np.mean(med), 26.0, 50.0))
        body = np.array([v, v, min(v + 3.0, 52.0)], dtype=np.uint8)
    else:
        body = np.array([34, 34, 36], dtype=np.uint8)

    out = np.zeros_like(rgba)
    out[:, :, 0] = body[0]
    out[:, :, 1] = body[1]
    out[:, :, 2] = body[2]
    out[:, :, 3] = a_final.astype(np.uint8)
    out[out[:, :, 3] < 2] = [0, 0, 0, 0]
    return out


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

    rf = r.astype(np.float32)
    gf = gch.astype(np.float32)
    bf = b.astype(np.float32)
    mx = np.maximum(np.maximum(rf, gf), bf)
    mn = np.minimum(np.minimum(rf, gf), bf)
    chroma = mx - mn
    luma = 0.299 * rf + 0.587 * gf + 0.114 * bf
    # 팽창 SAP 마스크가 저채도 몸통까지 지우는 것을 완화 (로고와 완전 일치 불필요)
    protect = ((chroma < 38.0) & (luma < 118.0)) | (luma < 52.0)

    sap_u8 = (sap_blue.astype(np.uint8) * 255)
    sap_img = Image.fromarray(sap_u8, mode="L")
    for _ in range(3):
        sap_img = sap_img.filter(ImageFilter.MaxFilter(5))
    sap_fat = np.asarray(sap_img) > 0

    kill = (sap_fat & ~protect) | letter_white
    arr[kill] = [0, 0, 0, 0]

    # 어두운 몸통을 씨드로 삼아, 로고 회색 판 등과 붙은 큰 덩어리는 제외
    core = (luma < 78.0) & (a > 35) & ~letter_white
    core_img = Image.fromarray((core.astype(np.uint8) * 255), mode="L")
    core_img = core_img.filter(ImageFilter.MaxFilter(7))
    seed = np.asarray(core_img) > 0

    alive = arr[:, :, 3] > 20
    a_img = Image.fromarray((alive.astype(np.uint8) * 255), mode="L")
    a_img = a_img.filter(ImageFilter.MinFilter(3))
    a_img = a_img.filter(ImageFilter.MaxFilter(3))
    alive = np.asarray(a_img) > 0
    vis = largest_cc_touching_seed(alive, seed)
    arr[~vis] = [0, 0, 0, 0]
    heal_outline_notches_rgba(arr)
    zap_sap_colored_fringe(arr)
    alive = arr[:, :, 3] > 15
    vis = largest_cc_touching_seed(alive, seed)
    arr[~vis] = [0, 0, 0, 0]

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
    cropped = repair_interior_holes_rgba(cropped)
    pil_c = Image.fromarray(cropped, mode="RGBA")
    w0, h0 = pil_c.size
    pil_big = pil_c.resize((w0 * 2, h0 * 2), Image.Resampling.LANCZOS)
    big = flat_soft_rim_rgba(np.asarray(pil_big))

    out_im = Image.fromarray(big, mode="RGBA")
    # 아이콘 크기 상한 (레티나 대비 2x)
    max_side = 160
    w, h = out_im.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        out_im = out_im.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BOX,
        )

    r, g, b, aa = out_im.split()
    aa = aa.filter(ImageFilter.GaussianBlur(radius=0.55))
    out_im = Image.merge("RGBA", (r, g, b, aa))

    out_im.save(OUT, optimize=True)
    print("Wrote", OUT, out_im.size)


if __name__ == "__main__":
    main()
