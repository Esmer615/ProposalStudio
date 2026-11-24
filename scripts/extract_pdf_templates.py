# -*- coding: utf-8 -*-
"""从 `docs/03-合同三份-脱敏版等9个文件/05-历史销售提案样本/饮用水客户-销售提案样本.pdf`
提取新云传媒品牌图片素材到 `server/templates/assets/`，供 PDF 模板复用。

纯标准库实现（re + zlib + struct），无需额外第三方 PDF/图像依赖。
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = (
    PROJECT_ROOT
    / "docs"
    / "03-合同三份-脱敏版等9个文件"
    / "05-历史销售提案样本"
    / "饮用水客户-销售提案样本.pdf"
)
ASSETS_DIR = PROJECT_ROOT / "server" / "templates" / "assets"

# 已核对的样本 PDF 图像对象映射
OBJECT_MAP: Dict[int, str] = {
    5: "logo-red.png",               # 红底/浅底页眉 FLAIR MEDIA 新云传媒 Logo
    48361: "logo-gold.png",          # 深色封面/封底 金白 FLAIR MEDIA 新云传媒 Logo
    7: "cover-wave.jpg",             # 封面/封底 深色立体波浪纹背景
    4664: "hq-building.jpg",         # 01 新云简介 总部大楼图
    6965: "about-icon-1.png",        # 关于我们 图标 1
    6977: "about-icon-2.png",        # 关于我们 图标 2
    6979: "about-icon-3.png",        # 关于我们 图标 3
    6981: "about-icon-4.png",        # 关于我们 图标 4
    11720: "divider-cubes.jpg",      # 02 媒体资源 / 03 发布推荐 分隔页蓝白方块图
    16367: "media-icon-1.png",       # 七类户外媒体线稿 1
    16370: "media-icon-2.png",       # 七类户外媒体线稿 2
    16372: "media-icon-3.png",       # 七类户外媒体线稿 3
    16374: "media-icon-4.png",       # 七类户外媒体线稿 4
    16376: "media-icon-5.png",       # 七类户外媒体线稿 5
    16378: "media-icon-6.png",       # 七类户外媒体线稿 6
    16380: "media-icon-7.png",       # 七类户外媒体线稿 7
    20987: "bus-bridge.jpg",         # 巴士媒体 外白渡桥/陆家嘴实景
    23326: "shanghai-network.jpg",   # 上海公交网络底图
    23360: "bus-circle-1.jpg",       # 巴士实景圆图 1
    23371: "bus-circle-2.jpg",       # 巴士实景圆图 2
    23368: "bus-circle-3.jpg",       # 巴士实景圆图 3
    23364: "bus-circle-4.jpg",       # 巴士实景圆图 4
    34932: "divider-gift.jpg",       # 04 赠送媒体展示 分隔页图
    37232: "gift-sanxin-led.jpg",    # 陆家嘴第一八佰伴商圈三鑫大厦LED
    39537: "gift-raffles-led.jpg",   # 人民广场商圈来福士商厦LED
    41842: "gift-swfc-led.jpg",      # 陆家嘴环球金融中心LED
    44147: "gift-double-bus.jpg",    # 市中心内环内稀缺资源双层观光巴士
}


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def _encode_png(width: int, height: int, rgb: bytes, alpha: Optional[bytes] = None) -> bytes:
    if alpha is not None and len(alpha) == width * height:
        color_type = 6  # RGBA
        rows = bytearray()
        for y in range(height):
            rows.append(0)
            r_off = y * width * 3
            a_off = y * width
            for x in range(width):
                p = r_off + x * 3
                rows.extend(rgb[p : p + 3])
                rows.append(alpha[a_off + x])
    else:
        color_type = 2  # RGB
        rows = bytearray()
        stride = width * 3
        for y in range(height):
            rows.append(0)
            rows.extend(rgb[y * stride : (y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _parse_stream_objects(data: bytes) -> Dict[int, Tuple[bytes, bytes]]:
    objs: Dict[int, Tuple[bytes, bytes]] = {}
    pat = re.compile(rb"(\d+)\s+0\s+obj\s*<<(.*?)>>\s*stream\r?\n", re.S)
    for m in pat.finditer(data):
        oid = int(m.group(1))
        hdr = m.group(2)
        start = m.end()
        length_m = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", hdr)
        if length_m:
            length = int(length_m.group(1))
            stream = data[start : start + length]
        else:
            end = data.find(b"endstream", start)
            if end < 0:
                continue
            stream = data[start:end].rstrip(b"\r\n")
        objs[oid] = (hdr, stream)
    return objs


def extract_assets() -> None:
    if not SAMPLE_PDF.is_file():
        raise FileNotFoundError(f"未找到样本 PDF：{SAMPLE_PDF}")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    raw = SAMPLE_PDF.read_bytes()
    objs = _parse_stream_objects(raw)

    extracted = 0
    for oid, filename in OBJECT_MAP.items():
        if oid not in objs:
            print(f"[WARN] object {oid} not found for {filename}")
            continue
        hdr, stream = objs[oid]
        out_path = ASSETS_DIR / filename
        if b"/DCTDecode" in hdr:
            out_path.write_bytes(stream)
            extracted += 1
            print(f"[JPG] {filename} ({len(stream):,} bytes)")
            continue
        if b"/FlateDecode" in hdr:
            w = int(re.search(rb"/Width\s+(\d+)", hdr).group(1))
            h = int(re.search(rb"/Height\s+(\d+)", hdr).group(1))
            rgb = zlib.decompress(stream)
            alpha: Optional[bytes] = None
            sm = re.search(rb"/SMask\s+(\d+)\s+0\s+R", hdr)
            if sm:
                sm_id = int(sm.group(1))
                if sm_id in objs:
                    _, sm_stream = objs[sm_id]
                    try:
                        alpha = zlib.decompress(sm_stream)
                    except Exception:
                        alpha = None
            png_bytes = _encode_png(w, h, rgb, alpha)
            out_path.write_bytes(png_bytes)
            extracted += 1
            print(f"[PNG] {filename} ({w}x{h}, alpha={alpha is not None}, {len(png_bytes):,} bytes)")
    print(f"Done: extracted {extracted}/{len(OBJECT_MAP)} assets to {ASSETS_DIR}")


if __name__ == "__main__":
    extract_assets()
