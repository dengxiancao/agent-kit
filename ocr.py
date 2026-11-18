#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocr.py — 本地 OCR（Tesseract 5），单文件，手机 Termux / Linux 桌面通用

为什么不用 PaddleOCR / RapidOCR / EasyOCR：
    它们全依赖 onnxruntime 或 torch，这两个在 Android Bionic(aarch64) 上没有
    预编译 wheel，Termux 里只能源码编译，实际上装不上。Tesseract 是 Termux
    官方仓库里唯一能直接 pkg install 的成熟 OCR。

它解决什么：
    手机截图字小、深色模式反白、低对比度，直接丢给 tesseract 常常一行都认不出来。
    这里把「裁剪 → 灰度 → 自动反色 → 对比度拉伸 → 放大 → 可选二值化」全做完，
    再做 psm 自适应（6 不行换 11），最后输出带坐标的结果，可直接拿去点击。

用法：
    python3 ocr.py shot.png                     # 纯文本
    python3 ocr.py shot.png --boxes             # 带坐标，给 tap 用
    python3 ocr.py shot.png --json              # 结构化
    python3 ocr.py shot.png --crop 0,300,1080,900   # 只识别中间一条
    python3 ocr.py a.pdf --dpi 200              # PDF 逐页
    python3 ocr.py doctor                       # 自检 + 安装命令

零第三方依赖：Pillow 有就用（快 10 倍、支持 JPEG），没有就内置 PNG 解码顶上。
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

TESSERACT = os.environ.get("TESSERACT_BIN", "tesseract")
NO_PIL = os.environ.get("OCR_NO_PIL", "") == "1"
MINCONF = float(os.environ.get("OCR_MINCONF", "32"))
TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "180"))

CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")


# ---------------------------------------------------------------- 基础工具
class OcrError(Exception):
    pass


def tessdata_dir():
    d = (os.environ.get("OCR_TESSDATA") or os.environ.get("TESSDATA_PREFIX") or "").strip()
    if not d:
        # 用户自己装了更准的模型，放 ~/.tessdata 就自动生效，免得记参数
        home = os.path.expanduser("~/.tessdata")
        if os.path.isdir(home):
            try:
                if any(f.endswith(".traineddata") for f in os.listdir(home)):
                    d = home
            except OSError:
                pass
        if not d:
            return ""
    if os.path.isdir(os.path.join(d, "tessdata")):
        d = os.path.join(d, "tessdata")
    return d


def run(cmd, timeout=None):
    env = dict(os.environ)
    td = tessdata_dir()
    if td:
        env["TESSDATA_PREFIX"] = td
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout or TIMEOUT, env=env)
    except FileNotFoundError:
        raise OcrError("找不到命令：%s" % cmd[0])
    except subprocess.TimeoutExpired:
        raise OcrError("超时（%ds）：%s" % (timeout or TIMEOUT, " ".join(cmd[:3])))
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    return p.returncode, out, err


def tess_bin():
    b = TESSERACT if os.path.isabs(TESSERACT) else shutil.which(TESSERACT)
    if not b:
        raise OcrError(
            "没装 tesseract。\n"
            "  Termux : pkg install -y tesseract\n"
            "  Ubuntu : sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim\n"
            "装完跑 python3 ocr.py doctor 复查。")
    return b


def tess_version():
    rc, out, err = run([tess_bin(), "--version"], 20)
    m = re.search(r"tesseract\s+([\d.]+)", out + err)
    return m.group(1) if m else "?"


def tess_langs():
    rc, out, err = run([tess_bin(), "--list-langs"], 20)
    return [x.strip() for x in (out + err).splitlines()[1:] if x.strip()]


def pick_lang(want=None):
    """want 为 None 表示自动：有中文就 chi_sim+eng，否则 eng"""
    have = tess_langs()
    if want and want != "auto":
        need = [x for x in want.split("+") if x not in have]
        if need:
            raise OcrError("缺语言包 %s。当前可用：%s\n"
                           "装中文：见 python3 ocr.py doctor" % ("+".join(need), ", ".join(have)))
        return want
    if "chi_sim" in have:
        return "chi_sim+eng" if "eng" in have else "chi_sim"
    if "eng" in have:
        return "eng"
    raise OcrError("一个语言包都没有，tessdata 可能是空的。跑 python3 ocr.py doctor")


# ---------------------------------------------------------------- 图像加载
# 统一成 (gray_bytes, w, h)：8 位灰度，逐行排列

def _has_pil():
    if NO_PIL:
        return False
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def load_gray_pil(path):
    from PIL import Image, ImageOps, ImageChops
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    rgb = im.convert("RGB")
    r, g, b = rgb.split()
    # 每个像素取 R/G/B 的最大值当灰度：彩色背景（微信绿、蓝色按钮）会趋近白色，
    # 与白底融成一片，tesseract 就不会把它当成「图片区域」整块丢掉。
    mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mn = ImageChops.darker(ImageChops.darker(r, g), b)
    hist = ImageChops.difference(mx, mn).histogram()
    total = im.size[0] * im.size[1] or 1
    sat = sum(hist[61:]) / float(total)
    return im.convert("L").tobytes(), mx.tobytes(), im.size[0], im.size[1], sat


def _png_chunks(blob):
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise OcrError("不是 PNG")
    pos, out = 8, {}
    idat = []
    while pos + 8 <= len(blob):
        ln, typ = struct.unpack(">I4s", blob[pos:pos + 8])
        data = blob[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        t = typ.decode("latin1")
        if t == "IDAT":
            idat.append(data)
        elif t == "IEND":
            break
        else:
            out[t] = data
    out["IDAT"] = b"".join(idat)
    return out


def load_gray_png(path):
    """纯标准库 PNG 解码，只支持非隔行、8/16 位；覆盖手机截图全部情况"""
    with open(path, "rb") as f:
        blob = f.read()
    ch = _png_chunks(blob)
    if "IHDR" not in ch:
        raise OcrError("PNG 缺 IHDR")
    w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", ch["IHDR"][:13])
    if inter:
        raise OcrError("这张 PNG 用了隔行扫描，内置解码不支持。\n"
                       "装 Pillow 即可：pkg install python-pillow（Termux）")
    if depth not in (8, 16):
        raise OcrError("PNG 位深 %d 暂不支持，装 Pillow 即可" % depth)

    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if chans is None:
        raise OcrError("PNG 颜色类型 %d 不支持" % ctype)
    step = chans * (2 if depth == 16 else 1)      # 每像素字节数
    stride = w * step

    raw = zlib.decompress(ch["IDAT"])
    if len(raw) < h * (stride + 1):
        raise OcrError("PNG 数据不完整（可能没下载完）")

    prev = bytearray(stride)
    rows = []
    p = 0
    for _ in range(h):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += stride + 1
        if ft == 1:
            for i in range(step, stride):
                line[i] = (line[i] + line[i - step]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - step] if i >= step else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - step] if i >= step else 0
                b = prev[i]
                c = prev[i - step] if i >= step else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise OcrError("PNG 行过滤类型 %d 非法" % ft)
        rows.append(line)
        prev = line

    pal = ch.get("PLTE") or b""
    trns = ch.get("TRNS")
    gray = bytearray(w * h)
    gmx = bytearray(w * h)
    satpx = 0
    idx = 0

    if ctype == 3:
        # 调色板先展开成查表，避免逐像素重复算
        tab = []
        for i in range(len(pal) // 3):
            r, g, b = pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]
            a = trns[i] if (trns and i < len(trns)) else 255
            mxv = max(r, g, b)
            mnv = min(r, g, b)
            if a != 255:
                r = (r * a + 255 * (255 - a)) // 255
                g = (g * a + 255 * (255 - a)) // 255
                b = (b * a + 255 * (255 - a)) // 255
                mxv = max(r, g, b)
            tab.append(((r * 77 + g * 150 + b * 29) >> 8, mxv, mxv - mnv > 60 and mxv > 120))
        for line in rows:
            if depth == 16:
                line = line[0::2]
            for x in range(w):
                t = tab[line[x]] if line[x] < len(tab) else (0, 0, False)
                gray[idx] = t[0]
                gmx[idx] = t[1]
                if t[2]:
                    satpx += 1
                idx += 1
    else:
        for line in rows:
            if depth == 16:
                line = line[0::2]
            for x in range(w):
                if ctype == 0:
                    g0 = mxv = line[x]
                elif ctype == 4:
                    g0, a = line[x * 2], line[x * 2 + 1]
                    mxv = g0
                    if a != 255:
                        g0 = mxv = (g0 * a + 255 * (255 - a)) // 255
                else:
                    r, g, b = line[x * 3], line[x * 3 + 1], line[x * 3 + 2]
                    if ctype == 6:
                        a = line[x * 4 + 3]
                        if a != 255:
                            r = (r * a + 255 * (255 - a)) // 255
                            g = (g * a + 255 * (255 - a)) // 255
                            b = (b * a + 255 * (255 - a)) // 255
                    g0 = (r * 77 + g * 150 + b * 29) >> 8
                    mxv = r if r > g else g
                    if b > mxv:
                        mxv = b
                    mnv = r if r < g else g
                    if b < mnv:
                        mnv = b
                    if mxv - mnv > 60 and mxv > 120:
                        satpx += 1
                gray[idx] = g0
                gmx[idx] = mxv
                idx += 1

    return bytes(gray), bytes(gmx), w, h, satpx / float(w * h)


def load_gray(path):
    if not os.path.exists(path):
        raise OcrError("文件不存在：%s" % path)
    if os.path.getsize(path) == 0:
        raise OcrError("文件是 0 字节：%s（下载没完成？）" % path)
    if _has_pil():
        try:
            return load_gray_pil(path)
        except OcrError:
            raise
        except Exception as e:
            if path.lower().endswith(".png"):
                return load_gray_png(path)
            if _has_pil():
                raise OcrError("读不了这张图（不是图片或格式不支持）：%s" % str(e)[:120])
            raise OcrError("没装 Pillow，只能读 PNG。要读 JPEG/WebP：pkg install python-pillow")
    if path.lower().endswith(".png"):
        return load_gray_png(path)
    raise OcrError(
        "没装 Pillow，只能读 PNG（手机截图都是 PNG，够用）。\n"
        "要读 JPEG/WebP 就装：pkg install python-pillow")


# ---------------------------------------------------------------- 预处理
INV = bytes(range(255, -1, -1))


def histogram(data):
    h = [0] * 256
    for v in data:
        h[v] += 1
    return h


def percentile(hist, total, p):
    acc = 0
    for i, c in enumerate(hist):
        acc += c
        if acc * 100 >= total * p:
            return i
    return 255


def is_dark_bg(hist, total):
    """中位数 < 110 认为是深底浅字（深色模式截图）"""
    return percentile(hist, total, 50) < 110


def stretch(data, lo, hi):
    if hi - lo <= 8 or (lo <= 2 and hi >= 250):
        return data
    span = hi - lo
    table = bytes(min(255, max(0, (v - lo) * 255 // span)) for v in range(256))
    return data.translate(table)


def otsu(data, hist, total):
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = w_b = 0
    best, thr = -1.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thr = var, t
    table = bytes(0 if v <= thr else 255 for v in range(256))
    return data.translate(table), thr


def crop(data, w, h, box):
    x1, y1, x2, y2 = box
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    out = bytearray()
    for y in range(y1, y2):
        out += data[y * w + x1: y * w + x2]
    return bytes(out), x2 - x1, y2 - y1


def upscale(data, w, h, scale):
    """双线性放大。scale<=1 原样返回"""
    if scale <= 1.001:
        return data, w, h
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if nw * nh > 26_000_000:
        raise OcrError("放大后 %dx%d 太大（%d 万像素），把 --scale 调小" % (nw, nh, nw * nh // 10000))

    # 预计算坐标映射
    xi = []
    for x in range(nw):
        sx = (x + 0.5) / scale - 0.5
        if sx < 0:
            sx = 0.0
        x0 = int(sx)
        if x0 >= w - 1:
            x0, x1, f = w - 1, w - 1, 0
        else:
            x1, f = x0 + 1, int((sx - x0) * 256)
        xi.append((x0, x1, f))

    out = bytearray(nw * nh)
    o = 0
    for y in range(nh):
        sy = (y + 0.5) / scale - 0.5
        if sy < 0:
            sy = 0.0
        y0 = int(sy)
        if y0 >= h - 1:
            y0 = y1 = h - 1
            fy = 0
        else:
            y1, fy = y0 + 1, int((sy - y0) * 256)
        r0 = y0 * w
        r1 = y1 * w
        for (x0, x1, fx) in xi:
            a = data[r0 + x0]
            b = data[r0 + x1]
            c = data[r1 + x0]
            d = data[r1 + x1]
            top = a + (((b - a) * fx) >> 8)
            bot = c + (((d - c) * fx) >> 8)
            out[o] = top + (((bot - top) * fy) >> 8)
            o += 1
    return bytes(out), nw, nh


def write_pgm(path, data, w, h):
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(data)


# ---------------------------------------------------------------- 识别
def tess_tsv(img_path, lang, psm):
    # 用 -c 直接开 tsv，不依赖 tessdata/configs/tsv（换模型目录时常缺这个文件）
    rc, out, err = run([tess_bin(), img_path, "stdout", "-l", lang,
                        "--psm", str(psm), "-c", "tessedit_create_tsv=1",
                        "-c", "preserve_interword_spaces=1"])
    if rc != 0 and not out.strip():
        raise OcrError("tesseract 失败：%s" % (err or out).strip()[:300])
    words = []
    for ln in out.splitlines():
        f = ln.split("\t")
        if len(f) < 12:
            continue
        try:
            level = int(f[0])
            if level != 5:
                continue
            conf = float(f[10])
            txt = f[11].strip()
            if not txt:
                continue
            x, y, w, h = int(f[6]), int(f[7]), int(f[8]), int(f[9])
        except (ValueError, IndexError):
            continue
        if conf < MINCONF:
            continue
        words.append({"x": x, "y": y, "w": w, "h": h, "c": conf, "t": txt,
                      "key": (f[1], f[2], f[3], f[4])})
    return words


def is_cjk(ch):
    return bool(ch) and bool(CJK_RE.match(ch))


# 中文之间不该有空格，但 tesseract 逐字输出时会插空格（"微 信"）
CJK_GAP = re.compile(r"(?<=[\u3400-\u9fff\u3000-\u303f\uff00-\uffef])"
                     r"[\s\u00a0]+"
                     r"(?=[\u3400-\u9fff\u3000-\u303f\uff00-\uffef])")


def join_words(ts):
    s = ""
    for t in ts:
        if not s:
            s = t
        elif is_cjk(s[-1]) or is_cjk(t[0]):
            s += t
        else:
            s += " " + t
    return CJK_GAP.sub("", s)


def group_lines(words):
    """按 tesseract 的 block/par/line 分组，组内按 x 排序"""
    order, buckets = [], {}
    for w in words:
        k = w["key"]
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(w)
    lines = []
    for k in order:
        ws = sorted(buckets[k], key=lambda w: w["x"])
        x1 = min(w["x"] for w in ws)
        y1 = min(w["y"] for w in ws)
        x2 = max(w["x"] + w["w"] for w in ws)
        y2 = max(w["y"] + w["h"] for w in ws)
        lines.append({"text": join_words([w["t"] for w in ws]),
                      "box": [x1, y1, x2 - x1, y2 - y1],
                      "center": [(x1 + x2) // 2, (y1 + y2) // 2],
                      "conf": round(sum(w["c"] for w in ws) / len(ws), 1),
                      "n": len(ws)})
    # 按纵向位置粗排，同一行内按 x
    lines.sort(key=lambda L: (L["box"][1] // 10, L["box"][0]))
    return lines


def score(lines):
    if not lines:
        return 0.0
    conf = sum(L["conf"] for L in lines) / len(lines)
    chars = sum(len(L["text"]) for L in lines)
    return conf * (1.0 + min(chars, 400) / 400.0) * (0.6 + 0.4 * min(len(lines), 8) / 8.0)


def merge_lines(a, b):
    """合并两轮结果，去重（同一位置、包含关系）"""
    out = list(a)
    for r in b:
        dup = False
        for i, o in enumerate(out):
            close = (abs(o["center"][1] - r["center"][1]) < 18 and
                     abs(o["center"][0] - r["center"][0]) < 80)
            same = o["text"] in r["text"] or r["text"] in o["text"]
            if close and same:
                if len(r["text"]) > len(o["text"]):
                    out[i] = r
                dup = True
                break
        if not dup:
            out.append(r)
    out.sort(key=lambda L: (L["box"][1] // 10, L["box"][0]))
    return out


def auto_scale(w, h, want=None):
    """手机截图 1080 宽本来就够，放大反而会让版面分析出错、行被拆散"""
    if want and want != "auto":
        return float(want)
    if w < 640:
        return 2.0
    if w < 1000:
        return 1.5
    return 1.0


def to_orig(lines, scale, ox, oy):
    for L in lines:
        b = L["box"]
        L["box"] = [int(b[0] / scale) + ox, int(b[1] / scale) + oy,
                    max(1, int(b[2] / scale)), max(1, int(b[3] / scale))]
        L["center"] = [L["box"][0] + L["box"][2] // 2, L["box"][1] + L["box"][3] // 2]
    return lines


def model_label():
    d = tessdata_dir()
    if not d:
        return "system"
    home = os.path.expanduser("~")
    if d.rstrip("/").startswith(home.rstrip("/") + "/"):
        return "~/" + os.path.relpath(d.rstrip("/"), home)
    return os.path.basename(d.rstrip("/")) or d


def ocr_file(path, lang, psm=None, scale=None, box=None, binarize="auto",
             invert="auto", quiet=False, gray="auto"):
    data, data_max, w, h, sat = load_gray(path)
    W0, H0 = w, h

    # 彩色背景（微信绿气泡、蓝色按钮）会让 tesseract 把整块当图片丢掉，
    # 这时改用「通道最大值」灰度：彩色底趋近白色，文字仍是深色。
    use_max = gray == "max" or (gray == "auto" and sat > 0.04)
    if use_max:
        data = data_max

    ox = oy = 0
    if box:
        data, w, h = crop(data, w, h, box)
        ox, oy = box[0], box[1]

    hist = histogram(data)
    if invert == "on" or (invert == "auto" and is_dark_bg(hist, w * h)):
        data = data.translate(INV)
        hist = histogram(data)
        inverted = True
    else:
        inverted = False

    # 对比度拉伸：只在「真的很灰」时做。默认截图的动态范围本来就够，
    # 硬拉反而会把彩色底色压成黑块（见 max 模式注释），得不偿失。
    if not use_max:
        hist = histogram(data)
        lo = percentile(hist, w * h, 0.5)
        hi = percentile(hist, w * h, 99.5)
        if 0 < hi - lo < 60:
            data = stretch(data, lo, hi)
            hist = histogram(data)

    if binarize == "on":
        data, _ = otsu(data, hist, w * h)
        hist = histogram(data)
    elif binarize == "auto" and not use_max:
        # 只有明显低对比（直方图挤在中间）才二值化，否则交给 tesseract 自己判断
        lo, hi = percentile(hist, w * h, 5), percentile(hist, w * h, 95)
        if 0 < hi - lo < 90:
            data, _ = otsu(data, hist, w * h)

    sc = auto_scale(w, h, scale)
    data, w, h = upscale(data, w, h, sc)

    tmp = tempfile.NamedTemporaryFile(suffix=".pgm", delete=False)
    tmp.close()
    try:
        write_pgm(tmp.name, data, w, h)
        if psm:
            lines = group_lines(tess_tsv(tmp.name, lang, psm))
            used = [psm]
        else:
            a = group_lines(tess_tsv(tmp.name, lang, 6))
            used = [6]
            lines = a
            if score(a) < 60 or len(a) < 3:
                b = group_lines(tess_tsv(tmp.name, lang, 11))
                used.append(11)
                if score(b) > score(a) * 1.1:
                    lines = b
                elif b:
                    lines = merge_lines(a, b)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    lines = [L for L in lines if L["text"].strip()]
    lines = to_orig(lines, sc, ox, oy)
    return {"file": path, "size": [W0, H0], "lang": lang, "psm": used,
            "scale": round(sc, 2), "inverted": inverted, "lines": lines,
            "model": model_label(), "color": round(sat, 3), "gray": "max" if use_max else "luma"}


# ---------------------------------------------------------------- 输入展开
def pages_of(path, dpi=200, first=None, last=None):
    """返回 [(标签, 图片路径, 是否临时)]；PDF 用 pdftoppm 拆页"""
    if not path.lower().endswith(".pdf"):
        return [(None, path, False)]
    if not shutil.which("pdftoppm"):
        raise OcrError("PDF 需要 pdftoppm。\n"
                       "  Termux : pkg install -y poppler\n"
                       "  Ubuntu : sudo apt install -y poppler-utils")
    tmpd = tempfile.mkdtemp(prefix="ocr_pdf_")
    cmd = ["pdftoppm", "-r", str(dpi), "-png"]
    if first:
        cmd += ["-f", str(first)]
    if last:
        cmd += ["-l", str(last)]
    cmd += [path, os.path.join(tmpd, "p")]
    rc, out, err = run(cmd, 300)
    if rc != 0:
        raise OcrError("PDF 转图失败：%s" % (err or out).strip()[:200])
    files = sorted(f for f in os.listdir(tmpd) if f.endswith(".png"))
    if not files:
        raise OcrError("PDF 里没解析出页面")
    return [("第 %d 页" % (i + 1), os.path.join(tmpd, f), True)
            for i, f in enumerate(files)]


def cleanup(pages):
    for _, p, tmp in pages:
        if tmp:
            try:
                os.unlink(p)
            except OSError:
                pass
            try:
                os.rmdir(os.path.dirname(p))
            except OSError:
                pass


# ---------------------------------------------------------------- 输出
def render_text(res, boxes=False, quiet=False):
    out = []
    if boxes:
        for L in res["lines"]:
            out.append("%5d,%5d  %4dx%-4d  %5.1f  %s\n" % (
                L["box"][0], L["box"][1], L["box"][2], L["box"][3], L["conf"], L["text"]))
    else:
        for L in res["lines"]:
            out.append(L["text"] + "\n")
    if not quiet:
        conf = (sum(L["conf"] for L in res["lines"]) / len(res["lines"])) if res["lines"] else 0
        mdl = "" if res.get("model", "system") == "system" else "  model=%s" % res["model"]
        sys.stderr.write("[ocr] %s  %dx%d  lang=%s  psm=%s  scale=%s%s%s  %d 行  置信 %.0f\n" % (
            os.path.basename(res["file"]), res["size"][0], res["size"][1], res["lang"],
            "+".join(str(x) for x in res["psm"]), res["scale"],
            "  已反色" if res["inverted"] else "", mdl, len(res["lines"]), conf))
    return "".join(out)


# ---------------------------------------------------------------- doctor
TERMUX_CMDS = """\
pkg install -y tesseract python-pillow poppler

# 中文语言包（Termux 仓库里没有，必须手下）
cd $PREFIX/share/tessdata
curl -fL -o chi_sim.traineddata \\
  https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata
curl -fL -o chi_sim_vert.traineddata \\
  https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim_vert.traineddata
curl -fL -o eng.traineddata \\
  https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata
chmod 644 *.traineddata
tesseract --list-langs"""

DEB_CMDS = """\
sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim poppler-utils
python3 -m pip install --user pillow"""

BEST_NOTE = """\
想更准就换 tessdata_best（中文 13MB，比默认模型准一档，慢约 2 倍）：

  mkdir -p ~/.tessdata && cd ~/.tessdata
  B=https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main
  curl -fL -O $B/chi_sim.traineddata
  curl -fL -O $B/eng.traineddata
  chmod 644 *.traineddata

  # 临时用
  python3 ocr.py 截图.png --tessdata ~/.tessdata
  # 或写进 ~/.bashrc 永久生效
  export OCR_TESSDATA=~/.tessdata
"""


def tess_data_path():
    rc, out, err = run([tess_bin(), "--list-langs"], 20)
    m = re.search(r'in "([^"]+)"', out + err)
    return m.group(1) if m else ""


def cmd_doctor():
    ok = True
    print("ocr.py 自检")
    print("-" * 52)

    tb = shutil.which(TESSERACT) if not os.path.isabs(TESSERACT) else TESSERACT
    if tb and os.path.exists(tb):
        try:
            v = tess_version()
            print("tesseract : OK  %s  (%s)" % (v, tb))
        except OcrError:
            print("tesseract : 装了但跑不起来")
            ok = False
    else:
        print("tesseract : 缺失")
        ok = False

    langs = []
    if tb:
        try:
            langs = tess_langs()
        except OcrError:
            pass
    if langs:
        print("语言包    : %s" % ", ".join(langs))
        if "chi_sim" in langs:
            print("中文      : OK")
        else:
            print("中文      : 缺失  <- 必须补，否则只能认英文")
            ok = False
    else:
        print("语言包    : 读不到（tessdata 路径可能不对）")
        ok = False

    td = tess_data_path()
    if td:
        print("模型目录  : %s" % td)
        p = os.path.join(td, "chi_sim.traineddata")
        if os.path.exists(p):
            mb = os.path.getsize(p) / 1048576.0
            print("中文模型  : chi_sim.traineddata  %.1f MB" % mb)
            if mb < 4:
                print("            ^ 这是 fast 版，快但容易整行漏字，追求准确换 best（见下）")
    elif tessdata_dir():
        print("模型目录  : %s（来自 OCR_TESSDATA）" % tessdata_dir())

    if _has_pil():
        from PIL import __version__ as pv
        print("Pillow    : OK  %s  (JPEG/WebP/自动旋转)" % pv)
    else:
        print("Pillow    : 没装  <- 只影响 JPEG 和速度，PNG 截图照样能认")

    print("pdftoppm  : %s  (PDF 输入)" % ("OK" if shutil.which("pdftoppm") else "缺失（可选）"))
    print("-" * 52)

    if ok:
        print("可以用了：python3 ocr.py 截图.png")
        print("")
        print("默认模型是「能用」级别：字小的界面、细体中文，偶尔会整行漏掉。")
        print(BEST_NOTE)
        return 0

    print("按你的系统执行：")
    print("")
    if os.environ.get("PREFIX", "").find("com.termux") >= 0 or shutil.which("termux-info"):
        print(TERMUX_CMDS)
    else:
        print(DEB_CMDS)
        print("")
        print("# Termux 上用这套：")
        print(TERMUX_CMDS)
    return 1


def cmd_langs():
    print("\n".join(tess_langs()))
    return 0


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("doctor", "check"):
        return cmd_doctor()
    if len(sys.argv) > 1 and sys.argv[1] == "langs":
        return cmd_langs()

    ap = argparse.ArgumentParser(
        description="本地 OCR（Tesseract）。给截图就能出文字，带坐标可点击。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python3 ocr.py shot.png
  python3 ocr.py shot.png --boxes
  python3 ocr.py shot.png --crop 0,300,1080,900 --scale 2
  python3 ocr.py shot.png --json > r.json
  python3 ocr.py doc.pdf --dpi 200 --boxes
  python3 ocr.py doctor
""")
    ap.add_argument("input", nargs="+", help="图片或 PDF，可多个")
    ap.add_argument("--lang", default="auto", help="默认 auto（有中文就 chi_sim+eng）")
    ap.add_argument("--tessdata", default=None,
                    help="模型目录，默认用系统 tessdata。装 tessdata_best 后指过去即生效")
    ap.add_argument("--psm", type=int, default=None,
                    help="版面模式，默认自适应（先 6 不够再 11）。单行文字可试 7")
    ap.add_argument("--scale", default="auto",
                    help="放大倍数，默认按宽度自动（<800 用 2，<1400 用 1.5，否则 1）")
    ap.add_argument("--crop", default=None, help="只识别一块区域：x1,y1,x2,y2")
    ap.add_argument("--bin", dest="binarize", default="auto", choices=["auto", "on", "off"],
                    help="二值化，默认 auto（仅低对比时启用）")
    ap.add_argument("--invert", default="auto", choices=["auto", "on", "off"],
                    help="反色，默认 auto（深色背景自动反）")
    ap.add_argument("--gray", default="auto", choices=["auto", "luma", "max"],
                    help="灰度算法，默认 auto：彩色背景多时用 max，保住彩色气泡里的字")
    ap.add_argument("--boxes", action="store_true", help="输出 x,y 宽x高 置信度 文字")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--minconf", type=float, default=None, help="丢弃低于此置信度的词（默认 32）")
    ap.add_argument("--dpi", type=int, default=200, help="PDF 转图分辨率，默认 200")
    ap.add_argument("--first", type=int, default=None, help="PDF 起始页")
    ap.add_argument("--last", type=int, default=None, help="PDF 结束页")
    ap.add_argument("-o", "--out", default=None, help="写入文件而不是打印")
    ap.add_argument("-q", "--quiet", action="store_true", help="不打印统计行")
    a = ap.parse_args()

    global MINCONF
    if a.minconf is not None:
        MINCONF = a.minconf
    if a.tessdata:
        if not os.path.isdir(a.tessdata):
            print("ERROR: --tessdata 目录不存在：%s" % a.tessdata, file=sys.stderr)
            return 2
        os.environ["OCR_TESSDATA"] = a.tessdata

    box = None
    if a.crop:
        try:
            box = [int(x) for x in re.split(r"[,\s]+", a.crop.strip()) if x]
            if len(box) != 4:
                raise ValueError
        except ValueError:
            print("ERROR: --crop 要四个数：x1,y1,x2,y2", file=sys.stderr)
            return 2

    try:
        lang = pick_lang(a.lang)
    except OcrError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1

    buf = []
    err = 0
    for path in a.input:
        try:
            pages = pages_of(path, a.dpi, a.first, a.last)
        except OcrError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            err = 1
            continue
        try:
            multi_file = len(a.input) > 1
            first = True
            for label, img, _tmp in pages:
                try:
                    res = ocr_file(img, lang, a.psm, a.scale, box,
                                   a.binarize, a.invert, a.quiet, a.gray)
                except OcrError as e:
                    print("ERROR: %s: %s" % (path, e), file=sys.stderr)
                    err = 1
                    continue
                res["file"] = path
                if label:
                    res["page"] = label
                if a.json:
                    buf.append(json.dumps(res, ensure_ascii=False, indent=1))
                else:
                    if multi_file and first:
                        buf.append("\n===== %s =====\n" % path)
                    first = False
                    if label:
                        buf.append("\n--- %s ---\n" % label)
                    buf.append(render_text(res, a.boxes, a.quiet))
        finally:
            cleanup(pages)

    if a.json and buf:
        text = "[" + ",\n".join(buf) + "]\n"
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
    elif buf:
        text = "".join(buf)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
    return err


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OcrError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
