#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成应用图标 icon.png（纯标准库，无需 Pillow）。"""
import os
import struct
import zlib

S = 128          # 输出尺寸
SS = 4           # 超采样倍数
W = H = S * SS

BG1 = (99, 102, 241)     # #6366f1
BG2 = (139, 92, 246)     # #8b5cf6
WHITE = (255, 255, 255)


def in_round_rect(x, y, w, h, r):
    dx = max(r - x, 0.0, x - (w - r))
    dy = max(r - y, 0.0, y - (h - r))
    return dx * dx + dy * dy <= r * r


def sample(x, y):
    """返回 (r,g,b,a)，坐标已归一化到 0..1"""
    # 背景圆角矩形
    if not in_round_rect(x, y, 1.0, 1.0, 0.225):
        return (0, 0, 0, 0)

    t = (x * 0.55 + y * 0.45)
    r = int(BG1[0] + (BG2[0] - BG1[0]) * t)
    g = int(BG1[1] + (BG2[1] - BG1[1]) * t)
    b = int(BG1[2] + (BG2[2] - BG1[2]) * t)
    a = 255

    # 顶部柔光
    if y < 0.5:
        k = (1 - y / 0.5) * 0.16
        r = int(r + (255 - r) * k)
        g = int(g + (255 - g) * k)
        b = int(b + (255 - b) * k)

    # 三根柱子
    base = 0.795
    bars = [
        (0.232, 0.285, 0.108),   # x, 顶部y, 宽
        (0.446, 0.455, 0.108),
        (0.660, 0.215, 0.108),
    ]
    for bx, top, bw in bars:
        if in_round_rect(x - bx, y - top, bw, base - top, 0.030):
            # 柱体白，略带回光
            shade = 1.0 - max(0.0, (y - top) / (base - top)) * 0.06
            r = int(WHITE[0] * shade)
            g = int(WHITE[1] * shade)
            b = int(WHITE[2] * shade)
            a = 255
            break

    return (r, g, b, a)


def render():
    rows = []
    inv = 1.0 / SS
    for py in range(S):
        row = bytearray()
        row.append(0)  # filter: none
        for px in range(S):
            ar = ag = ab = aa = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px * SS + sx + 0.5) * inv / S
                    y = (py * SS + sy + 0.5) * inv / S
                    cr, cg, cb, ca = sample(x, y)
                    ar += cr * ca
                    ag += cg * ca
                    ab += cb * ca
                    aa += ca
            n = SS * SS
            if aa > 0:
                row += bytes((int(ar / aa), int(ag / aa), int(ab / aa), int(aa / n)))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return b"".join(rows)


def chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def main():
    raw = render()
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.png")
    with open(out, "wb") as f:
        f.write(png)
    print("written", out, len(png), "bytes")


if __name__ == "__main__":
    main()
