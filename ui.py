#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui.py - 让 agent 能"看见"并操作 X11 桌面（xdotool + 截图 + OCR）

前提：和桌面在同一个 X11 会话里（DISPLAY 有效），且有 xdotool。
远程/无头环境可用 Xvfb。

用法:
  python3 ui.py info                      环境自检
  python3 ui.py look [--max 40]           一步到位：截图 + 窗口列表 + OCR（推荐）
  python3 ui.py shot [out.png]            只截图，打印路径和尺寸
  python3 ui.py ocr [img] [--lang ...]    对图片 OCR，输出 (x,y) 文字
  python3 ui.py find <文字> [--lang ...]   在屏幕上找文字，输出中心坐标
  python3 ui.py click <x> <y> [--double]  点击
  python3 ui.py move <x> <y>              移动鼠标
  python3 ui.py drag <x1> <y1> <x2> <y2>  拖拽
  python3 ui.py type <文本> [--enter]     输入文字（支持中文）
  python3 ui.py key <组合键>              如 ctrl+l / Return / alt+F4
  python3 ui.py scroll <up|down> [n]      滚轮
  python3 ui.py region <x1> <y1> <x2> <y2>   只看某块区域并放大识别（小字用这个）
  python3 ui.py win [list|activate N|close N|geom N]

所有坐标都是屏幕绝对像素，原点在左上角。
"""

import os
import sys
import shutil
import argparse
import subprocess

SHOT = "/tmp/ui_shot.png"


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except FileNotFoundError:
        return 127, "", "找不到命令: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "超时: %s" % " ".join(cmd[:3])


def need(binname, hint):
    if not shutil.which(binname):
        print("ERROR: 缺少 %s。%s" % (binname, hint))
        sys.exit(2)


def display():
    d = os.environ.get("DISPLAY")
    if not d:
        print("ERROR: 没有 DISPLAY，说明当前不在图形会话里。")
        print("  本地桌面：export DISPLAY=:0")
        print("  远程/无头：先起 Xvfb 或 x11vnc")
        sys.exit(2)
    return d


def screen_size():
    rc, out, _ = run(["xdotool", "getdisplaygeometry"])
    if rc == 0 and out.strip():
        try:
            w, h = out.split()
            return int(w), int(h)
        except ValueError:
            pass
    return 0, 0


def shot(path=SHOT):
    need("xdotool", "")
    display()
    if shutil.which("import"):
        rc, out, err = run(["import", "-window", "root", path], 40)
    elif shutil.which("scrot"):
        rc, out, err = run(["scrot", "-o", path], 40)
    else:
        print("ERROR: 缺少截图工具。装 imagemagick（import）或 scrot。")
        sys.exit(2)
    if rc != 0 or not os.path.exists(path):
        print("ERROR: 截图失败 %s" % err.strip()[:200])
        sys.exit(2)
    return path


def ocr_lines(img, lang="chi_sim+eng", psm=11, minconf=35):
    if not shutil.which("tesseract"):
        return None
    rc, out, err = run(["tesseract", img, "stdout", "-l", lang,
                        "--psm", str(psm), "tsv"], 90)
    if rc != 0:
        return None
    lines = {}
    rows = out.splitlines()
    for ln in rows[1:]:
        f = ln.split("\t")
        if len(f) < 12:
            continue
        try:
            if int(f[0]) != 5:      # 只要 word 级
                continue
            conf = float(f[10])
            txt = f[11].strip()
            if not txt or conf < minconf:
                continue
            x, y, w, h = int(f[6]), int(f[7]), int(f[8]), int(f[9])
        except Exception:
            continue
        key = (f[1], f[2], f[3], f[4])
        if key not in lines:
            lines[key] = {"x": x, "y": y, "x2": x + w, "y2": y + h, "t": [txt]}
        else:
            L = lines[key]
            L["x"] = min(L["x"], x)
            L["y"] = min(L["y"], y)
            L["x2"] = max(L["x2"], x + w)
            L["y2"] = max(L["y2"], y + h)
            L["t"].append(txt)

    out_lines = []
    for L in lines.values():
        text = "".join(L["t"])
        cx = (L["x"] + L["x2"]) // 2
        cy = (L["y"] + L["y2"]) // 2
        out_lines.append((cy, cx, text, L["x"], L["y"], L["x2"] - L["x"], L["y2"] - L["y"]))
    out_lines.sort(key=lambda r: (r[0] // 12, r[1]))
    return out_lines


def upscale(img):
    if not shutil.which("convert"):
        return None
    out = img.replace(".png", "_2x.png")
    rc, _, _ = run(["convert", img, "-colorspace", "Gray", "-resize", "200%",
                    "-sharpen", "0x1", out], 40)
    return out if rc == 0 and os.path.exists(out) else None


def merge_lines(a, b):
    out = list(a or [])
    for r in (b or []):
        dup = False
        for i, o in enumerate(out):
            same = (o[2] in r[2] or r[2] in o[2])
            if abs(o[0] - r[0]) < 14 and abs(o[1] - r[1]) < 160 and same:
                if len(r[2]) > len(o[2]):
                    out[i] = r
                dup = True
                break
        if not dup:
            out.append(r)
    out.sort(key=lambda r: (r[0] // 12, r[1]))
    return out


def ocr_best(img, lang="chi_sim+eng"):
    """GUI 截图专用：psm6 为主；行数过少时放大重试；仍少才并入 psm11"""
    a = ocr_lines(img, lang, psm=6) or []
    if len(a) >= 3:
        return a
    big = upscale(img)
    if big:
        b = ocr_lines(big, lang, psm=6) or []
        if len(b) > len(a):
            a = b
    if len(a) >= 3:
        return a
    c = ocr_lines(img, lang, psm=11) or []
    return merge_lines(a, c)


def cmd_info():
    print("DISPLAY   : %s" % os.environ.get("DISPLAY", "(未设置)"))
    w, h = screen_size()
    print("screen    : %dx%d" % (w, h))
    for b, why in (("xdotool", "必须，装 xdotool"),
                   ("import", "截图，装 imagemagick"),
                   ("scrot", "截图备选"),
                   ("tesseract", "OCR，装 tesseract-ocr"),
                   ("wmctrl", "窗口管理（可选）")):
        print("%-9s: %s%s" % (b, "OK" if shutil.which(b) else "缺失",
                              "" if shutil.which(b) else "  <- " + why))
    if shutil.which("tesseract"):
        rc, out, _ = run(["tesseract", "--list-langs"])
        langs = [x for x in out.splitlines()[1:] if x.strip()]
        print("ocr langs : %s%s" % (",".join(langs),
                                    "" if "chi_sim" in langs else "  <- 缺中文，装 tesseract-ocr-data-chi_sim"))
    rc, out, _ = run(["xdotool", "getactivewindow"])
    if rc == 0 and out.strip():
        wid = out.strip()
        _, name, _ = run(["xdotool", "getwindowname", wid])
        print("active win: [%s] %s" % (wid, name.strip()[:60]))


def list_windows(limit=12):
    rows = []
    if shutil.which("wmctrl"):
        rc, out, _ = run(["wmctrl", "-lG"])
        if rc == 0:
            for ln in out.splitlines()[:limit]:
                f = ln.split(None, 7)
                if len(f) >= 8:
                    rows.append((f[0], f[7][:50], int(f[2]), int(f[3]), int(f[4]), int(f[5])))
            return rows
    rc, out, _ = run(["xdotool", "search", "--onlyvisible", "--name", ".*"], 20)
    if rc == 0:
        for wid in out.split()[:limit]:
            _, nm, _ = run(["xdotool", "getwindowname", wid])
            _, g, _ = run(["xdotool", "getwindowgeometry", "--shell", wid])
            d = {}
            for ln in g.splitlines():
                if "=" in ln:
                    k, v = ln.split("=", 1)
                    d[k] = v
            try:
                rows.append((wid, (nm or "").strip()[:50], int(d.get("X", 0)),
                             int(d.get("Y", 0)), int(d.get("WIDTH", 0)), int(d.get("HEIGHT", 0))))
            except ValueError:
                continue
    return rows


def cmd_look(maxlines=40, lang="chi_sim+eng", no_ocr=False):
    display()
    need("xdotool", "")
    w, h = screen_size()
    path = shot()
    print("screen %dx%d  shot=%s" % (w, h, path))
    wins = list_windows()
    if wins:
        print("windows:")
        for wid, nm, x, y, ww, hh in wins:
            if ww * hh < 3600:
                continue
            if not nm.strip() and (hh < 60 or (ww, hh) == (w, h)):
                continue
            print("  [%s] %s  (%d,%d %dx%d)" % (wid, nm, x, y, ww, hh))
    if no_ocr:
        return
    lines = ocr_best(path, lang)
    if lines is None:
        print("(未安装 tesseract，只有截图)")
        return
    print("text (x,y 是文字中心):")
    for cy, cx, text, x, y, ww, hh in lines[:maxlines]:
        print("  (%d,%d) %s" % (cx, cy, text[:60]))
    if len(lines) > maxlines:
        print("  ... 共 %d 行，用 --max 调大" % len(lines))


def cmd_find(text, lang="chi_sim+eng"):
    display()
    path = shot()
    lines = ocr_best(path, lang)
    if lines is None:
        print("ERROR: 没有 tesseract，无法定位文字")
        return
    key = text.lower().replace(" ", "")
    best = None
    for cy, cx, t, x, y, ww, hh in lines:
        t2 = t.lower().replace(" ", "")
        if key in t2:
            score = len(key) / max(len(t2), 1)
            if best is None or score > best[0]:
                best = (score, cx, cy, t)
    if best:
        print("found: %s  ->  %d %d" % (best[3], best[1], best[2]))
    else:
        print("not found: %s" % text)
        print("屏幕上的文字（前 15 行）:")
        for cy, cx, t, *_ in lines[:15]:
            print("  (%d,%d) %s" % (cx, cy, t[:50]))


def cmd_click(x, y, double=False, button=1):
    need("xdotool", "")
    display()
    run(["xdotool", "mousemove", "--sync", str(x), str(y)], 10)
    if double:
        run(["xdotool", "click", "--repeat", "2", "--delay", "80", str(button)], 10)
        print("double-click %d,%d" % (x, y))
    else:
        run(["xdotool", "click", str(button)], 10)
        print("click %d,%d" % (x, y))


def cmd_move(x, y):
    need("xdotool", "")
    display()
    run(["xdotool", "mousemove", "--sync", str(x), str(y)], 10)
    print("move %d,%d" % (x, y))


def cmd_drag(x1, y1, x2, y2):
    need("xdotool", "")
    display()
    run(["xdotool", "mousemove", "--sync", str(x1), str(y1)], 10)
    run(["xdotool", "mousedown", "1"], 10)
    run(["xdotool", "mousemove", "--sync", "--delay", "15", str(x2), str(y2)], 15)
    run(["xdotool", "mouseup", "1"], 10)
    print("drag %d,%d -> %d,%d" % (x1, y1, x2, y2))


def cmd_type(text, enter=False, lang=None):
    need("xdotool", "")
    display()
    rc, out, err = run(["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text], 45)
    if rc != 0:
        # 退化：先设剪贴板再 ctrl+v
        if shutil.which("xclip") or shutil.which("xsel"):
            if shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), timeout=10)
            else:
                subprocess.run(["xsel", "-ib"], input=text.encode(), timeout=10)
            run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], 10)
            print("typed (via clipboard): %s" % text[:40])
        else:
            print("ERROR: 输入失败 %s。装 xclip 可走剪贴板方案" % err.strip()[:120])
            return
    else:
        print("typed: %s" % text[:60])
    if enter:
        run(["xdotool", "key", "Return"], 10)


def cmd_key(combo):
    need("xdotool", "")
    display()
    run(["xdotool", "key", "--clearmodifiers", combo], 10)
    print("key %s" % combo)


def cmd_scroll(direction, n=3):
    need("xdotool", "")
    display()
    btn = "4" if direction == "up" else "5"
    run(["xdotool", "click", "--repeat", str(n), "--delay", "40", btn], 15)
    print("scroll %s x%d" % (direction, n))


def cmd_region(x1, y1, x2, y2, zoom=3):
    display()
    path = shot()
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        print("ERROR: 区域无效")
        return
    if not shutil.which("convert"):
        print("ERROR: 需要 imagemagick(convert) 才能裁剪放大")
        return
    out = "/tmp/ui_region.png"
    rc, _, err = run(["convert", path, "-crop", "%dx%d+%d+%d" % (w, h, x1, y1),
                      "+repage", "-colorspace", "Gray", "-resize", "%d%%" % (zoom * 100),
                      "-sharpen", "0x1", out], 40)
    if rc != 0:
        print("ERROR: 裁剪失败 %s" % err[:150])
        return
    if not shutil.which("tesseract"):
        print("已裁剪到 %s，但没有 tesseract" % out)
        return
    best = ""
    for psm in (6, 7, 11):
        rc, txt, _ = run(["tesseract", out, "stdout", "-l", "chi_sim+eng",
                          "--psm", str(psm)], 60)
        if rc == 0 and len(txt.strip()) > len(best.strip()):
            best = txt
    print("region (%d,%d)-(%d,%d):" % (x1, y1, x2, y2))
    print(best.strip() or "(没识别到文字)")


def cmd_win(action="list", arg=None):
    display()
    wins = list_windows(30)
    if action == "list" or not arg:
        for wid, nm, x, y, w, h in wins:
            print("[%s] %s  (%d,%d %dx%d)" % (wid, nm, x, y, w, h))
        return
    target = None
    for wid, nm, x, y, w, h in wins:
        if arg == wid or (arg and arg.lower() in nm.lower()):
            target = (wid, nm, x, y, w, h)
            break
    if not target:
        print("not found: %s" % arg)
        return
    wid, nm, x, y, w, h = target
    if action == "activate":
        if shutil.which("wmctrl"):
            run(["wmctrl", "-i", "-a", wid], 10)
        else:
            run(["xdotool", "windowactivate", "--sync", wid], 10)
        print("activated [%s] %s" % (wid, nm))
    elif action == "close":
        run(["xdotool", "windowclose", wid], 10)
        print("closed [%s] %s" % (wid, nm))
    elif action == "geom":
        print("[%s] %s  (%d,%d %dx%d)" % (wid, nm, x, y, w, h))


def main(argv):
    ap = argparse.ArgumentParser(prog="ui.py", description="X11 桌面操控")
    ap.add_argument("action", choices=["info", "look", "shot", "ocr", "find", "click", "move",
                                       "drag", "type", "key", "scroll", "region", "win"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--lang", default="chi_sim+eng")
    ap.add_argument("--double", action="store_true")
    ap.add_argument("--enter", action="store_true")
    ap.add_argument("--button", type=int, default=1)
    ap.add_argument("--no-ocr", action="store_true")
    a = ap.parse_args(argv)

    if a.action == "info":
        cmd_info()
    elif a.action == "look":
        cmd_look(a.max, a.lang, a.no_ocr)
    elif a.action == "shot":
        display()
        path = shot(a.args[0] if a.args else SHOT)
        w, h = screen_size()
        print("%s  (%dx%d)" % (path, w, h))
    elif a.action == "ocr":
        img = a.args[0] if a.args else SHOT
        if not os.path.exists(img):
            print("ERROR: 图片不存在: %s，先跑 shot" % img)
            return 2
        lines = ocr_lines(img, a.lang)
        if lines is None:
            print("ERROR: tesseract 不可用")
            return 2
        for cy, cx, text, x, y, ww, hh in lines[:a.max]:
            print("(%d,%d) %s" % (cx, cy, text[:60]))
    elif a.action == "find":
        if not a.args:
            print("用法: ui.py find <文字>")
            return 2
        cmd_find(" ".join(a.args), a.lang)
    elif a.action == "click":
        if len(a.args) < 2:
            print("用法: ui.py click <x> <y>")
            return 2
        cmd_click(int(a.args[0]), int(a.args[1]), a.double, a.button)
    elif a.action == "move":
        cmd_move(int(a.args[0]), int(a.args[1]))
    elif a.action == "drag":
        cmd_drag(*[int(x) for x in a.args[:4]])
    elif a.action == "type":
        cmd_type(" ".join(a.args), a.enter, a.lang)
    elif a.action == "key":
        cmd_key(a.args[0])
    elif a.action == "scroll":
        cmd_scroll(a.args[0] if a.args else "down",
                   int(a.args[1]) if len(a.args) > 1 else 3)
    elif a.action == "region":
        if len(a.args) < 4:
            print("用法: ui.py region <x1> <y1> <x2> <y2>")
            return 2
        cmd_region(*[int(x) for x in a.args[:4]])
    elif a.action == "win":
        cmd_win(a.args[0] if a.args else "list",
                a.args[1] if len(a.args) > 1 else None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
