#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adui.py — 用 ADB 操控安卓手机屏幕（Termux 可用，无需 root）

与 ui.py 的区别：
  ui.py  走 X11（xdotool + OCR），用于 Linux 桌面
  adui.py 走 ADB + uiautomator，用于 Android 手机
  Android 有 uiautomator，能直接拿到控件文字和坐标，不用 OCR，准确得多。

用法：python3 adui.py <action> [...]
"""

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

ADB = os.environ.get("ADB_BIN", "adb")
SERIAL = os.environ.get("ADB_SERIAL", "").strip()
TIMEOUT = int(os.environ.get("ADUI_TIMEOUT", "60"))
DUMP_PATH = "/sdcard/adui_dump.xml"

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

KEYS = {
    "back": 4, "home": 3, "enter": 66, "tab": 61, "del": 67, "backspace": 67,
    "menu": 82, "power": 26, "volup": 24, "voldown": 25, "appswitch": 187,
    "esc": 111, "up": 19, "down": 20, "left": 21, "right": 22, "space": 62,
    "paste": 279, "search": 84, "camera": 27, "mute": 164,
}


# ---------------------------------------------------------------- adb 底
class AdbError(RuntimeError):
    pass


def adb(*args, timeout=None, binary=False):
    cmd = [ADB]
    if SERIAL:
        cmd += ["-s", SERIAL]
    cmd += [str(a) for a in args]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout or TIMEOUT)
    except FileNotFoundError:
        raise AdbError("找不到 adb。Termux 里执行：pkg install android-tools")
    except subprocess.TimeoutExpired:
        raise AdbError("adb 执行超时（%ss）：%s" % (timeout or TIMEOUT, " ".join(cmd[1:])))
    out = p.stdout if binary else p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    return p.returncode, out, err


def sh(*args, timeout=None):
    rc, out, err = adb("shell", *args, timeout=timeout)
    return out.strip(), err.strip()


def require_device():
    """确认有且只有一个可用设备，否则给出能直接照做的提示"""
    rc, out, err = adb("devices")
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    devs = [l for l in lines[1:] if "\t" in l or " " in l]
    state = {}
    for l in devs:
        parts = l.split()
        if len(parts) >= 2:
            state[parts[0]] = parts[1]
    ok = [k for k, v in state.items() if v == "device"]
    bad = {k: v for k, v in state.items() if v != "device"}
    if not ok:
        msg = ["没有可用的安卓设备。"]
        if "unauthorized" in bad.values():
            msg.append("手机显示「允许 USB 调试吗」时点了拒绝 —— 到"
                       " 开发者选项 → 撤销 USB 调试授权，然后重新连接/配对。")
        elif "offline" in bad.values():
            msg.append("设备处于 offline，执行：adb kill-server 后重连")
        else:
            msg += ["先找设备（自动扫端口并连接，推荐）：",
                    "  python3 adui.py scan",
                    "还没配对过的话，先配对一次：",
                    "  python3 adui.py pair 127.0.0.1 <弹窗端口> <6位配对码>",
                    "两个端口都在 设置 → 开发者选项 → 无线调试 里。"]
        raise AdbError("\n".join(msg))
    if len(ok) > 1:
        raise AdbError("检测到多个设备：%s\n用环境变量指定：export ADB_SERIAL=%s"
                       % (", ".join(ok), ok[0]))
    return ok[0]


# ---------------------------------------------------------------- UI 树
def dump_ui(tries=4, compressed=False, call_timeout=45):
    """拿 uiautomator 的 UI 层级 XML。界面在动时会失败，所以重试。"""
    cmd = ["uiautomator", "dump"]
    if compressed:
        cmd.append("--compressed")
    cmd.append(DUMP_PATH)
    last = ""
    for _ in range(tries):
        rc, out, err = adb("shell", *cmd, timeout=call_timeout)
        blob = out + err
        if "dumped to" in blob:
            rc2, raw, _ = adb("exec-out", "cat", DUMP_PATH, binary=True, timeout=40)
            if b"<hierarchy" in raw:
                return raw.decode("utf-8", "replace")
            last = "读取 dump 文件失败"
        else:
            last = blob.strip() or "无输出"
            if "idle" in blob or "ERROR" in blob:
                time.sleep(0.5)
            else:
                time.sleep(0.3)
    raise AdbError("uiautomator dump 连续失败 %d 次：%s\n"
                   "（界面一直在动时容易这样；先回到桌面重试）" % (tries, last[:200]))


def parse_nodes(xml_text):
    """解析成扁平节点列表，把「文字在子节点、点击区域在父节点」的情况补全"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise AdbError("UI XML 解析失败：%s" % e)

    res = []

    def walk(n, click_box):
        # 根节点 hierarchy 没有 bounds，但必须继续往下走
        m = BOUNDS_RE.match(n.get("bounds") or "")
        box = None
        if m:
            x1, y1, x2, y2 = (int(v) for v in m.groups())
            if x2 > x1 and y2 > y1:
                box = (x1, y1, x2, y2)
        clickable = n.get("clickable") == "true"
        target = box if (clickable and box) else click_box
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        cls = (n.get("class") or "").rsplit(".", 1)[-1]
        if box and (text or desc or clickable):
            res.append({
                "text": text,
                "desc": desc,
                "label": text or desc,
                "cls": cls,
                "id": (n.get("resource-id") or "").replace(":id/", "/"),
                "box": box,
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                "click_center": (((target[0] + target[2]) // 2, (target[1] + target[3]) // 2)
                                 if target else ((x1 + x2) // 2, (y1 + y2) // 2)),
                "clickable": clickable,
                "click_box": target,
                "enabled": n.get("enabled") != "false",
                "checked": n.get("checked") == "true",
                "focused": n.get("focused") == "true",
                "scrollable": n.get("scrollable") == "true",
                "password": n.get("password") == "true",
            })
        for ch in n:
            walk(ch, target)

    walk(root, None)
    return sort_rows(res)


def sort_rows(nodes):
    """按视觉行排序：先纵向聚成行，行内按 x。单纯按 y 排会把同一行打乱。"""
    nodes = sorted(nodes, key=lambda r: (r["center"][1], r["center"][0]))
    rows, cur, last = [], [], None
    for n in nodes:
        cy = n["center"][1]
        h = n["box"][3] - n["box"][1]
        tol = max(18, min(h, 70) // 2)
        if last is None or abs(cy - last) <= tol:
            cur.append(n)
            last = cy if last is None else (last + cy) / 2.0
        else:
            rows.append(cur)
            cur, last = [n], cy
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        r.sort(key=lambda n: n["center"][0])
        out.extend(r)
    return out


def screen_size():
    out, _ = sh("wm", "size")
    m = re.search(r"(\d+)x(\d+)", out.replace("Override size:", ""))
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)


def android_version():
    out, _ = sh("getprop", "ro.build.version.release")
    return out.strip() or "?"


def current_package(nodes=None):
    if nodes:
        for n in nodes:
            if n["id"] or n["label"]:
                break
        return ""
    out, _ = sh("dumpsys", "window")
    for line in out.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            m = re.search(r"([a-zA-Z][\w.]+)/[\w.$]+", line)
            if m:
                return m.group(1)
    return ""


# ---------------------------------------------------------------- 动作
def pick(nodes, all_nodes=False, grep=None):
    """look 与 tap N 必须用同一套过滤，否则序号会错位"""
    out = []
    for n in nodes:
        if not all_nodes and not n["label"]:
            continue
        if grep and grep.casefold() not in (n["label"] or "").casefold():
            continue
        out.append(n)
    return out


def find_node(nodes, needle, nth=1, clickable_only=True):
    """先精确匹配，再忽略大小写，再包含匹配。返回第 nth 个。"""
    pool = [n for n in nodes if n["label"]]
    if clickable_only:
        hit = [n for n in pool if n["click_box"]]
        pool = hit or pool
    key = needle.casefold()
    stages = [
        [n for n in pool if n["label"].casefold() == key],
        [n for n in pool if key in n["label"].casefold()],
        [n for n in pool if key in (n["id"] or "").casefold()],
    ]
    for stage in stages:
        if stage:
            return stage[nth - 1] if len(stage) >= nth else stage[-1]
    cands = sorted({n["label"] for n in nodes if n["label"]})[:12]
    raise AdbError("屏幕上找不到「%s」。当前可见文字：%s" % (needle, " | ".join(cands) or "(无)"))


def do_tap_point(x, y):
    sh("input", "tap", x, y)
    return "tap (%d,%d)" % (x, y)


def do_tap_box(box):
    x = (box[0] + box[2]) // 2
    y = (box[1] + box[3]) // 2
    return do_tap_point(x, y)


IME_PKG = "com.android.adbkeyboard"
IME_ID = "com.android.adbkeyboard/.AdbIME"
IME_STATE = os.path.join(os.path.expanduser("~"), ".adui_ime")
SHELL_SPECIAL = set("&|;<>$`\\\"'()*?~[]{}#!")

APK_MIRRORS = [
    "https://cdn.jsdelivr.net/gh/senzhk/ADBKeyBoard@master/ADBKeyboard.apk",
    "https://ghproxy.net/https://raw.githubusercontent.com/senzhk/ADBKeyBoard/master/ADBKeyboard.apk",
    "https://raw.githubusercontent.com/senzhk/ADBKeyBoard/master/ADBKeyboard.apk",
]
APK_SIZE = 17374


def _q(t):
    """给设备端 shell 用的单引号包裹"""
    return "'" + t.replace("'", "'\\''") + "'"


def _device_input_text(t):
    """input text 的约定：空格写成 %s"""
    return _q(t.replace(" ", "%s"))


def _pm_has(pkg, timeout=25):
    out, _ = sh("pm", "list", "packages", pkg, timeout=timeout)
    return ("package:" + pkg) in out


def imes_enabled():
    out, _ = sh("ime", "list", "-s", timeout=25)
    return [x.strip() for x in out.splitlines() if "/" in x]


def ime_current():
    out, _ = sh("settings", "get", "secure", "default_input_method", timeout=25)
    out = out.strip()
    return out if "/" in out else ""


def ime_set(target):
    sh("ime", "enable", target, timeout=25)
    out, err = sh("ime", "set", target, timeout=25)
    blob = (out + err)
    if "Error" in blob or "Unknown" in blob or "Exception" in blob:
        raise AdbError("切换输入法被系统拒绝：%s\n"
                       "手动切换：设置 → 系统 → 语言和输入法 → 当前输入法" % blob.strip()[:160])
    time.sleep(0.3)
    return ime_current()


def ime_save(cur):
    if cur and not cur.startswith(IME_PKG):
        try:
            with open(IME_STATE, "w") as f:
                f.write(cur)
        except Exception:
            pass


def ime_saved():
    try:
        with open(IME_STATE) as f:
            v = f.read().strip()
        return v if "/" in v else ""
    except Exception:
        return ""


def text_visible(s, tries=2):
    """输入后回读界面，确认文字真的落到了控件里"""
    key = s.strip()[:8]
    if not key:
        return False
    for _ in range(tries):
        try:
            nodes = parse_nodes(dump_ui(tries=1, call_timeout=25))
        except AdbError:
            return False
        pool = "".join(n["label"] for n in nodes if n["label"])
        if key in pool:
            return True
        time.sleep(0.4)
    return False


def do_text(s, restore=True, verify=False):
    """输入文字。ASCII 直发；中文走 ADBKeyBoard（临时切换输入法，输完自动切回）"""
    if not s:
        raise AdbError("没有内容可输入")

    if s.isascii() and not (set(s) & SHELL_SPECIAL):
        sh("input", "text", _device_input_text(s), timeout=30)
        return "输入（直发）：%s" % s

    # ---- 方案 1：ADBKeyBoard（中文唯一稳的路）
    if _pm_has(IME_PKG):
        enabled = [i for i in imes_enabled() if i.startswith(IME_PKG)]
        if not enabled:
            sh("ime", "enable", IME_ID, timeout=25)
            enabled = [i for i in imes_enabled() if i.startswith(IME_PKG)]
        if enabled:
            target = enabled[0]
            prev = ime_current()
            switched = not prev.startswith(IME_PKG)
            if switched:
                ime_save(prev)
                if not ime_set(target).startswith(IME_PKG):
                    switched = False
            b64 = base64.b64encode(s.encode("utf-8")).decode()
            out, err = sh("am", "broadcast", "-a", "ADB_INPUT_B64", "-p", IME_PKG,
                          "--es", "msg", b64, timeout=35)
            ok = "Broadcast completed" in out and "result=0" in out
            if not ok:
                out, err = sh("am", "broadcast", "-a", "ADB_INPUT_TEXT", "-p", IME_PKG,
                              "--es", "msg", _q(s), timeout=35)
                ok = "Broadcast completed" in out
            time.sleep(0.45)
            if switched and restore:
                try:
                    ime_set(prev)
                except AdbError:
                    pass
            if ok:
                note = "" if not verify else (
                    "，已在界面上确认" if text_visible(s) else "，但界面上没看到，可能输入框没聚焦")
                return "输入（ADBKeyBoard）：%s%s" % (s, note)

    # ---- 方案 2：Termux:API 剪贴板（必须先确认应用装了，否则客户端会一直等）
    if _pm_has("com.termux.api", timeout=20) and shutil.which("termux-clipboard-set"):
        try:
            r = subprocess.run(["termux-clipboard-set", s], capture_output=True, timeout=6)
            if r.returncode == 0:
                time.sleep(0.4)
                sh("input", "keyevent", 279, timeout=30)
                return "输入（剪贴板粘贴）：%s" % s
        except Exception:
            pass

    raise AdbError(
        "中文输入还没配好。一条命令解决：\n"
        "  cd ~/work && python3 adui.py ime-install\n"
        "它会下载 ADBKeyBoard 并自动启用（不用 root，不用手动点设置）。\n"
        "如果手机弹出「禁止通过 USB 安装应用」，就手动装：\n"
        "  apk 已放在 ~/work/ADBKeyboard.apk，在文件管理器里点一下安装即可。\n"
        "现阶段可先用英文/数字代替中文。")


def do_key(name):
    k = KEYS.get(name.lower())
    if k is None:
        k = int(name) if name.isdigit() else None
    if k is None:
        raise AdbError("未知按键 %s。可用：%s" % (name, ", ".join(sorted(KEYS))))
    sh("input", "keyevent", k)
    return "key %s (%d)" % (name, k)


# ---------------------------------------------------------------- 命令
def cmd_info():
    require_device()
    w, h = screen_size()
    ver = android_version()
    model, _ = sh("getprop", "ro.product.model")
    pkg = current_package()
    print("adb      : %s" % ADB)
    print("device   : %s  (%s / Android %s)" % (SERIAL or "默认", model.strip() or "?", ver))
    print("screen   : %dx%d" % (w, h))
    print("foreground: %s" % (pkg or "?"))
    print("dump path: %s" % DUMP_PATH)
    print("tip      : 先用 look 看屏幕，拿到文字和坐标再操作")


def split_host_port(x):
    if x and ":" in x:
        h, p = x.rsplit(":", 1)
        return h, p
    return x, None


def cmd_connect(host="127.0.0.1", port=None):
    host, p2 = split_host_port(host)
    port = port or p2
    if not port:
        raise AdbError("用法：python3 adui.py connect 192.168.1.102:39549\n"
                       "（端口在 设置 → 开发者选项 → 无线调试 的「IP 地址和端口」那一行）")
    rc, out, err = adb("connect", "%s:%s" % (host, port), timeout=25)
    blob = (out + err).strip()
    print(blob or "已发起连接")
    low = blob.lower()
    if "refused" in low:
        raise AdbError(
            "端口 %s 上没有服务在监听 —— 这个端口已经失效了。\n"
            "无线调试每次开关、每次开配对弹窗，端口都会变（这是系统的随机端口）。\n"
            "不用肉眼抄了，直接扫：\n"
            "  python3 adui.py scan\n"
            "它会找到当前端口并连上。" % port)
    try:
        require_device()
        print("连接成功：%s" % (SERIAL or "默认设备"))
    except AdbError as e:
        print("仍未就绪：%s" % e)


def cmd_pair(host, port, code, auto=True):
    host, p2 = split_host_port(host)
    if code is None:
        raise AdbError("用法：python3 adui.py pair 127.0.0.1:42361 570100\n"
                       "     或：python3 adui.py pair 127.0.0.1 42361 570100\n"
                       "端口和 6 位码都在「使用配对码配对设备」的弹窗里，2 分钟内有效。")
    port = port or p2
    if not port:
        raise AdbError("缺端口。弹窗里写的是 IP:端口，一起抄下来。")
    rc, out, err = adb("pair", "%s:%s" % (host, port), code, timeout=40)
    blob = (out + err).strip()
    print(blob or "已发起配对")
    low = blob.lower()
    if "successfully paired" in low:
        print("")
        print("配对完成（这东西只做一次，重启也不会丢）。")
        if auto:
            print("配对后调试端口会换一个，正在自动找…")
            print("")
            try:
                cmd_scan()
            except AdbError as e:
                print("自动没找到：%s" % e)
                print("手动：回 无线调试 主页面，看「IP 地址和端口」那一行，然后 connect。")
    elif "protocol fault" in low or "unable to connect" in low or "failed" in low:
        raise AdbError(
            "配对失败。两个原因最常见：\n"
            "  1) 端口用错了 —— 弹窗里的端口是 pairing 端口，主页面那个是 connect 端口，不能混用\n"
            "  2) 超过 2 分钟 —— 弹窗关掉/锁屏就失效\n"
            "重开弹窗拿一组新的，用分屏让 Termux 和设置同时可见，30 秒内敲完。\n"
            "不确定端口时：python3 adui.py scan （扫出来的多半就是弹窗端口）")


def cmd_ports():
    """从 mDNS 找配对/调试端口，省得肉眼抄"""
    rc, out, err = adb("mdns", "services", timeout=25)
    blob = (out + err)
    pairing, connect = None, None
    for line in blob.splitlines():
        parts = line.split()
        if not parts:
            continue
        if "_adb-tls-pairing" in line:
            pairing = parts[-1]
        elif "_adb-tls-connect" in line:
            connect = parts[-1]
    if "not supported" in blob.lower():
        raise AdbError(
            "这个 adb 是 Termux 的 android-tools，编译时没带 mDNS，所以 ports 用不了（不是你的错，也不是手机的问题）。\n"
            "改用扫描，效果一样：\n"
            "  python3 adui.py scan\n"
            "它会扫本机 30000-65535，把无线调试的端口直接找出来并连上。\n"
            "只有配对那一瞬间才需要肉眼看端口（配对弹窗里的 IP:端口 + 6 位码）。")
    if not pairing and not connect:
        raise AdbError(
            "mDNS 没发现任何服务。可能原因：\n"
            "  - 无线调试没打开\n"
            "  - 手机的 mDNS 被系统拦了（部分 MIUI 会）\n"
            "直接扫端口更快：python3 adui.py scan\n\n"
            "adb 原始输出：%s" % blob.strip()[:300])
    print("pairing 端口（只能在弹窗打开时用，2 分钟内有效）:")
    print("  %s" % (pairing or "(没发现)"))
    if pairing:
        print("  -> python3 adui.py pair %s <6位配对码>" % pairing)
    print("connect 端口（配对完成后用这个）:")
    print("  %s" % (connect or "(没发现，回设置主页面看)"))
    if connect:
        print("  -> python3 adui.py connect %s" % connect)


# ---------------------------------------------------------------- 找端口
def local_ip():
    """拿到本机 wlan 地址（拿不到就返回空串）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return "" if ip.startswith("127.") else ip
    except OSError:
        return ""


def _probe(host, port, timeout):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def scan_open(host, start, end, timeout=0.3, workers=256):
    open_ports = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe, host, p, timeout): p for p in range(start, end + 1)}
        for f in as_completed(futs):
            try:
                if f.result():
                    open_ports.append(futs[f])
            except Exception:
                pass
    return sorted(open_ports)


def _try_connect(host, port, timeout=8):
    rc, out, err = adb("connect", "%s:%s" % (host, port), timeout=timeout)
    blob = (out + err).strip()
    return blob, "connected to" in blob.lower() or "already connected" in blob.lower()


def cmd_scan(host=None, start=30000, end=65535, timeout=0.3, do_connect=True):
    """无线调试的端口是随机的，adb mdns 又在 Termux 里不可用 —— 直接扫。

    Termux 和 adbd 跑在同一台手机上，所以扫 127.0.0.1 就是扫手机自己，
    不用碰局域网，也不会被路由器/防火墙影响。
    """
    if start > end:
        raise AdbError("端口范围反了：start 要比 end 小")

    targets = []
    if host:
        targets = [host]
    else:
        targets = ["127.0.0.1"]
        ip = local_ip()
        if ip:
            targets.append(ip)

    total = end - start + 1
    for t in targets:
        print("扫描 %s 的 %d-%d 端口（共 %d 个，约 5-20 秒）…" % (t, start, end, total))
        t0 = time.time()
        found = scan_open(t, start, end, timeout=timeout)
        cost = time.time() - t0
        if not found:
            print("  %.0fs，没发现开放端口。" % cost)
            continue
        print("  %.0fs，发现 %d 个开放端口：" % (cost, len(found)))
        for p in found:
            print("    %d" % p)

        if not do_connect:
            return found

        print("")
        for p in found[:3]:
            try:
                blob, ok = _try_connect(t, p, timeout=6)
            except AdbError as e:
                print("  %s:%d  -> 无响应，跳过（%s）" % (t, p, str(e).splitlines()[0]))
                continue
            if ok:
                print("  %s:%d  -> 连接成功" % (t, p))
                time.sleep(0.6)
                try:
                    dev = require_device()
                    print("")
                    print("设备就绪：%s" % dev)
                    print("接下来：python3 adui.py info   然后  python3 adui.py look")
                    return found
                except AdbError:
                    print("  但设备还没就绪，再等一下或重跑一次 scan")
            else:
                print("  %s:%d  -> %s" % (t, p, blob.splitlines()[-1][:80]))

    raise AdbError(
        "没扫到能连的调试端口。逐个排查：\n"
        "  1) 设置 → 开发者选项 → 无线调试，确认开关是开的（关一次再开）\n"
        "  2) 如果还没配对过，先点「使用配对码配对设备」，然后：\n"
        "       python3 adui.py pair 127.0.0.1 <弹窗里的端口> <6位码>\n"
        "  3) MIUI/澎湃 可能限制后台，把 Termux 加到「无限制」再试\n"
        "  4) 端口被系统改了的话，范围放大：python3 adui.py scan --range 10000-65535")


def device_states():
    """{serial: state} ，state 是 device / offline / unauthorized"""
    rc, out, err = adb("devices", timeout=20)
    d = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            d[parts[0]] = parts[1]
    return d


def cmd_doctor():
    """断了以后的一键排查：能自动修的自己修，修不了的告诉你去点哪里"""
    print("① 检查 adb")
    rc, out, err = adb("version", timeout=10)
    first = out.strip().splitlines()[0] if out.strip() else (err.strip()[:80] or "无输出")
    print("   %s" % first)

    print("② 看当前设备")
    st = device_states()
    ok = [k for k, v in st.items() if v == "device"]
    if ok:
        print("   已连接：%s" % ", ".join(ok))
        print("   不用修。确认能用：python3 adui.py info")
        return
    if not st:
        print("   一个设备都没有")
    for k, v in st.items():
        print("   %s -> %s" % (k, v))
    if "unauthorized" in st.values():
        print("   unauthorized = 手机上「允许 USB 调试吗」没点同意，或者授权被撤销了")
        print("   去 无线调试 页面「撤销 USB 调试授权」，然后重新 pair 一次")

    print("③ 重启本地 adb 服务（一半的假死是它）")
    adb("kill-server", timeout=15)
    time.sleep(1)
    adb("start-server", timeout=40)
    print("   done")

    print("④ 扫端口并连接")
    try:
        cmd_scan()
        return
    except AdbError as e:
        print("")
        for ln in str(e).splitlines():
            print("   " + ln)
        print("")

    print("")
    print("⑤ 以上都不行，只剩两种可能：")
    print("   1) 配对记录丢了 → 点「使用配对码配对设备」，30 秒内")
    print("      python3 adui.py pair 127.0.0.1 <弹窗端口> <6位码>")
    print("   2) 系统把无线调试整个禁了 → USB 接电脑 adb tcpip 5555，")
    print("      再 python3 adui.py connect 127.0.0.1:5555")
    print("")
    raise AdbError("没修好，见上面 ⑤。")


def cmd_look(all_nodes=False, as_json=False, grep=None):
    require_device()
    xml = dump_ui()
    nodes = parse_nodes(xml)
    w, h = screen_size()
    m = re.search(r'package="([^"]+)"', xml)
    pkg = m.group(1) if m else ""

    picked = pick(nodes, all_nodes, grep)

    if as_json:
        print(json.dumps({"package": pkg, "screen": [w, h],
                          "nodes": [{"i": i + 1, "label": n["label"], "cls": n["cls"],
                                     "id": n["id"], "box": n["box"],
                                     "center": n["click_center"], "clickable": n["clickable"]}
                                    for i, n in enumerate(picked)]}, ensure_ascii=False, indent=1))
        return

    print("screen %dx%d  当前应用 %s  可见元素 %d" % (w, h, pkg or "?", len(picked)))
    for i, n in enumerate(picked, 1):
        label = n["label"] or "-"
        label = clip(label, 34)
        flags = []
        if n["clickable"]:
            flags.append("可点")
        elif n["click_box"]:
            flags.append("可点(父)")
        if n["scrollable"]:
            flags.append("可滚")
        if n["checked"]:
            flags.append("已选")
        if n["password"]:
            flags.append("密码")
        cx, cy = n["click_center"]
        extra = ("  " + n["id"][:34]) if n["id"] else ""
        print("[%2d] %s (%4d,%4d) %s%s" % (
            i, pad(label, 34), cx, cy, pad(",".join(flags), 9), extra))
    if not picked:
        print("（没有可见元素。可能是纯 Canvas/游戏画面，只能靠坐标盲点）")
    print("提示：tap N 直接点第 N 个；tap-text 文字 也行")


def resolve_target(idx=None, x=None, y=None):
    """把「序号」或「坐标」统一成 (x, y, 描述)"""
    if idx is not None:
        picked = pick(parse_nodes(dump_ui()))
        if not 1 <= idx <= len(picked):
            raise AdbError("序号 %d 超出范围（当前共 %d 个元素，先跑 look 看看）"
                           % (idx, len(picked)))
        n = picked[idx - 1]
        box = n["click_box"] or n["box"]
        return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2, n["label"] or n["cls"]
    if x is None or y is None:
        raise AdbError("用法：adui.py tap <序号>  或  adui.py tap <x> <y>")
    return x, y, ""


def cmd_tap(idx=None, x=None, y=None):
    require_device()
    px, py, label = resolve_target(idx, x, y)
    sh("input", "tap", px, py)
    print("tap (%d,%d)%s" % (px, py, ("  ->  " + label) if label else ""))


def cmd_longpress(idx=None, x=None, y=None, ms=900):
    require_device()
    px, py, label = resolve_target(idx, x, y)
    # input 没有 longpress，用起点=终点的 swipe 实现
    sh("input", "swipe", px, py, px, py, ms)
    print("longpress (%d,%d) %dms%s" % (px, py, ms, ("  ->  " + label) if label else ""))


def cmd_tap_text(text, nth=1):
    require_device()
    nodes = parse_nodes(dump_ui())
    n = find_node(nodes, text, nth)
    box = n["click_box"] or n["box"]
    print("%s  ->  「%s」" % (do_tap_box(box), n["label"]))


def cmd_text(content, restore=True, verify=False):
    require_device()
    print(do_text(content, restore=restore, verify=verify))


def cmd_key(name):
    require_device()
    print(do_key(name))


def cmd_swipe(x1, y1, x2, y2, ms=300):
    require_device()
    sh("input", "swipe", x1, y1, x2, y2, ms)
    print("swipe (%d,%d)->(%d,%d) %dms" % (x1, y1, x2, y2, ms))


def cmd_scroll(direction="down", times=1):
    require_device()
    w, h = screen_size()
    for _ in range(max(1, times)):
        if direction == "down":
            sh("input", "swipe", w // 2, int(h * 0.72), w // 2, int(h * 0.32), 260)
        elif direction == "up":
            sh("input", "swipe", w // 2, int(h * 0.32), w // 2, int(h * 0.72), 260)
        else:
            raise AdbError("方向只能是 up 或 down")
        time.sleep(0.35)
    print("scroll %s x%d" % (direction, times))


def cmd_wait(text, timeout=15, interval=1.0):
    require_device()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            nodes = parse_nodes(dump_ui(tries=1))
            n = find_node(nodes, text)
            cx, cy = n["click_center"]
            print("出现「%s」 (%d,%d)  用时 %.1fs" % (n["label"], cx, cy, time.time() - t0))
            return
        except AdbError:
            time.sleep(interval)
    raise AdbError("等了 %ss 没等到「%s」" % (timeout, text))


def cmd_shot(path=None):
    require_device()
    path = path or os.path.join(os.getcwd(), "shot.png")
    rc, raw, err = adb("exec-out", "screencap", "-p", binary=True, timeout=60)
    if not raw.startswith(b"\x89PNG"):
        raise AdbError("截图失败：%s" % (err.strip() or "返回的不是 PNG"))
    with open(path, "wb") as f:
        f.write(raw)
    print("截图已保存 %s  (%d KB)" % (path, len(raw) // 1024))


def cmd_apps(grep=None):
    require_device()
    out, _ = sh("pm", "list", "packages", "-3")
    names = sorted(l.replace("package:", "").strip() for l in out.splitlines() if l.strip())
    if grep:
        names = [n for n in names if grep.casefold() in n.casefold()]
    for n in names:
        print(n)
    print("--- 共 %d 个第三方应用" % len(names))


def cmd_start(pkg):
    require_device()
    out, err = sh("monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    if "No activities found" in out + err or "monkey aborted" in (out + err).lower():
        raise AdbError("启动失败：%s 不存在或没有启动入口。用 apps 看包名。" % pkg)
    print("已启动 %s" % pkg)


def cmd_ime(arg=None):
    require_device()
    cur = ime_current()
    enabled = imes_enabled()
    installed = _pm_has(IME_PKG, timeout=20)
    has_ime = any(i.startswith(IME_PKG) for i in enabled)
    print("当前输入法 : %s" % (cur or "(读不到，可能没解锁)"))
    if not installed:
        print("ADBKeyBoard: 未安装  ->  python3 adui.py ime-install")
    elif not has_ime:
        print("ADBKeyBoard: 已安装但未启用  ->  python3 adui.py ime-enable")
    else:
        print("ADBKeyBoard: 就绪，可以直接 text 中文")
    print("已启用输入法 :")
    for i, x in enumerate(enabled, 1):
        print("  [%d] %s%s" % (i, x, "   <- 当前" if x == cur else ""))

    if not arg:
        return
    if arg in ("adb", "adbkeyboard", "keyboard"):
        if not has_ime:
            raise AdbError("ADBKeyBoard 还没启用，先跑：python3 adui.py ime-install")
        print("已切到 ADBKeyBoard（没有可见键盘，用 text 输入）")
        ime_set(IME_ID)
    elif arg in ("restore", "default", "back"):
        target = ime_saved()
        if not target:
            raise AdbError("没有记录原来的输入法。用 ime set <序号> 手动选一个")
        ime_set(target)
        print("已切回 %s" % target)
    elif arg.isdigit():
        i = int(arg)
        if not 1 <= i <= len(enabled):
            raise AdbError("序号超出范围（共 %d 个）" % len(enabled))
        ime_save(cur)
        ime_set(enabled[i - 1])
        print("已切到 %s" % enabled[i - 1])
    else:
        ime_save(cur)
        ime_set(arg)
        print("已切到 %s" % arg)


def download_apk(dest):
    for url in APK_MIRRORS:
        try:
            print("下载 %s" % url)
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=45) as r:
                blob = r.read()
            if len(blob) < 10000 or not blob.startswith(b"PK"):
                print("  内容不对（%d 字节），换下一个" % len(blob))
                continue
            with open(dest, "wb") as f:
                f.write(blob)
            print("  已保存 %s（%d 字节）" % (dest, len(blob)))
            return True
        except Exception as e:
            print("  失败：%s" % str(e)[:90])
    return False


def cmd_ime_enable():
    require_device()
    if not _pm_has(IME_PKG, timeout=20):
        raise AdbError("还没装 ADBKeyBoard，先跑：python3 adui.py ime-install")
    sh("ime", "enable", IME_ID, timeout=25)
    ok = [i for i in imes_enabled() if i.startswith(IME_PKG)]
    if not ok:
        raise AdbError("启用失败。手动：设置 → 系统 → 语言和输入法 → 管理输入法 → 打开 ADB Keyboard")
    print("ADBKeyBoard 已启用（不抢你的默认输入法，text 时会临时切换再切回）")


def cmd_ime_install(apk=None):
    require_device()
    home_work = os.path.expanduser("~/work")
    if not os.path.isdir(home_work):
        home_work = os.path.dirname(os.path.abspath(__file__))
    dest = apk or os.path.join(home_work, "ADBKeyboard.apk")

    if _pm_has(IME_PKG, timeout=20):
        print("ADBKeyBoard 已经装过了，跳过下载")
    else:
        if apk:
            if not os.path.exists(apk):
                raise AdbError("找不到 %s" % apk)
            dest = apk
        elif not (os.path.exists(dest) and os.path.getsize(dest) > 10000):
            print("== 下载 ADBKeyBoard（约 17KB，3 个源依次尝试）")
            if not download_apk(dest):
                raise AdbError(
                    "三个源都下不动。手动办法：\n"
                    "  1) 手机浏览器打开 https://github.com/senzhk/ADBKeyBoard\n"
                    "  2) 下载 ADBKeyboard.apk 并安装\n"
                    "  3) 回到这里执行：python3 adui.py ime-enable")
        print("== 安装 %s" % dest)
        rc, out, err = adb("install", "-r", "-g", dest, timeout=180)
        blob = (out + err)
        print("  " + blob.strip().splitlines()[-1] if blob.strip() else "  (无输出)")
        if "Success" not in blob:
            if "USER_RESTRICTED" in blob or "INSTALL_FAILED" in blob:
                prc, pout, perr = adb("push", dest, "/sdcard/Download/ADBKeyboard.apk",
                                      timeout=60)
                where = ("手机的 下载/ADBKeyboard.apk" if prc == 0
                         else "本机路径 %s" % dest)
                raise AdbError(
                    "系统拦住了 adb 安装（MIUI 的「USB 安装」限制）。\n"
                    "apk 在 %s，用文件管理器点一下安装，\n" % where +
                    "然后执行：python3 adui.py ime-enable\n"
                    "（想以后都能用 adb 装：设置 → 开发者选项 → USB 安装，打开它）")
            raise AdbError("安装失败：%s" % blob.strip()[:300])

    cmd_ime_enable()
    print("")
    print("现在可以直接：python3 adui.py text \"你好，世界\"")


def cmd_dump():
    require_device()
    print(dump_ui())


def cmd_ocr_help():
    print("优先用 look：Android 有 uiautomator，控件文字和坐标是系统给的，比识别准。")
    print("")
    print("只有这两种情况才需要 OCR：")
    print("  1) 纯 Canvas / 游戏 / Flutter 自绘界面，uiautomator 拿不到文字")
    print("  2) 文字在图片里（聊天记录、商品图、验证码）")
    print("")
    print("用法：")
    print("  python3 adui.py ocr               # 截屏 + 识别，输出「文字 (x,y)」")
    print("  python3 adui.py ocr --json        # 给程序用")
    print("  python3 adui.py ocr --keep a.png  # 顺便留下截图")
    print("  python3 adui.py ocr --crop 0,300,1080,900   # 只认中间一条，快且准")
    print("")
    print("识别质量取决于 ocr.py：python3 ocr.py doctor 自检。")


def find_ocr_py():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "ocr.py"),
             os.path.expanduser("~/work/ocr.py"),
             os.path.expanduser("~/work-kit/ocr.py")]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def dwidth(s):
    """终端显示宽度：中文算两列，不然表格永远对不齐"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - dwidth(s))


def clip(s, n):
    if dwidth(s) <= n:
        return s
    out, w = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if w + cw > n - 1:
            break
        out += c
        w += cw
    return out + "…"


def cmd_ocr(crop=None, as_json=False, keep=None, minconf=None, psm=None, lang=None):
    """截屏 → OCR → 输出带坐标的文字（给 tap x y 用）"""
    require_device()
    ocr_py = find_ocr_py()
    if not ocr_py:
        raise AdbError(
            "找不到 ocr.py。它要和 adui.py 放在一起：\n"
            "  cd ~/work && curl -fL -O https://ghfast.top/https://raw.githubusercontent.com/"
            "dengxiancao/android-agent-kit/main/ocr.py\n"
            "  python3 ocr.py doctor")

    path = keep or os.path.join(tempfile.gettempdir(), "adui_ocr.png")
    rc, raw, err = adb("exec-out", "screencap", "-p", binary=True, timeout=60)
    if not raw.startswith(b"\x89PNG"):
        raise AdbError("截图失败：%s" % (err.strip() or "返回的不是 PNG"))
    with open(path, "wb") as f:
        f.write(raw)

    cmd = [sys.executable, ocr_py, path, "--json", "-q"]
    if crop:
        cmd += ["--crop", crop]
    if minconf is not None:
        cmd += ["--minconf", str(minconf)]
    if psm is not None:
        cmd += ["--psm", str(psm)]
    if lang:
        cmd += ["--lang", lang]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    out = p.stdout.decode("utf-8", "replace").strip()
    if p.returncode != 0 or not out.startswith("["):
        raise AdbError("ocr.py 执行失败：%s" % (p.stderr.decode("utf-8", "replace").strip()[:400] or "无输出"))
    try:
        data = json.loads(out)
    except ValueError:
        raise AdbError("ocr.py 返回的不是合法 JSON：%s" % out[:200])

    page = data[0] if data else {"lines": [], "size": [0, 0]}
    lines = page.get("lines", [])

    if as_json:
        print(json.dumps({"screenshot": path, "size": page.get("size"),
                          "model": page.get("model"),
                          "lines": [{"i": i + 1, "text": L["text"], "box": L["box"],
                                     "center": L["center"], "conf": L["conf"]}
                                    for i, L in enumerate(lines)]},
                         ensure_ascii=False, indent=1))
        return

    w, h = page.get("size") or [0, 0]
    print("屏幕 %dx%d  OCR 识别到 %d 行（截图 %s）" % (w, h, len(lines), path))
    if not lines:
        print("（一个字符都没认出来。检查：python3 ocr.py doctor；"
              "或这张图本来就没有文字）")
        return
    for i, L in enumerate(lines, 1):
        cx, cy = L["center"]
        print("[%2d] %s (%4d,%4d)  %3.0f" % (
            i, pad(clip(L["text"], 34), 34), cx, cy, L["conf"]))
    print("")
    print("点击：python3 adui.py tap <x> <y>     例如 python3 adui.py tap %d %d"
          % tuple(lines[0]["center"]))


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description="ADB 操控安卓屏幕（Termux 可用）")
    sub = ap.add_subparsers(dest="action")

    sub.add_parser("info")
    p = sub.add_parser("connect"); p.add_argument("host", nargs="?", default="127.0.0.1"); p.add_argument("port", nargs="?")
    p = sub.add_parser("pair"); p.add_argument("a"); p.add_argument("b", nargs="?")
    p.add_argument("c", nargs="?")
    sub.add_parser("ports")
    sub.add_parser("doctor", help="断了/连不上时的一键排查")
    p = sub.add_parser("scan", help="扫描无线调试端口（mDNS 不可用时的替代）")
    p.add_argument("--host", help="要扫的地址，默认先扫 127.0.0.1")
    p.add_argument("--range", dest="rng", default="30000-65535", help="端口范围，默认 30000-65535")
    p.add_argument("--timeout", type=float, default=0.3, help="单端口超时秒数，默认 0.3")
    p.add_argument("--no-connect", action="store_true", help="只列端口，不自动连接")
    p = sub.add_parser("look"); p.add_argument("--all", action="store_true"); p.add_argument("--json", action="store_true"); p.add_argument("--grep")
    p = sub.add_parser("tap"); p.add_argument("a"); p.add_argument("b", nargs="?")
    p = sub.add_parser("longpress"); p.add_argument("a"); p.add_argument("b", nargs="?"); p.add_argument("--ms", type=int, default=900)
    p = sub.add_parser("tap-text"); p.add_argument("text"); p.add_argument("--nth", type=int, default=1)
    p = sub.add_parser("text"); p.add_argument("content")
    p.add_argument("--verify", action="store_true", help="输入后回读界面确认")
    p.add_argument("--keep-ime", action="store_true", help="不切回原输入法")
    p = sub.add_parser("key"); p.add_argument("name")
    p = sub.add_parser("swipe"); p.add_argument("x1", type=int); p.add_argument("y1", type=int); p.add_argument("x2", type=int); p.add_argument("y2", type=int); p.add_argument("--ms", type=int, default=300)
    p = sub.add_parser("scroll"); p.add_argument("direction", nargs="?", default="down"); p.add_argument("times", nargs="?", type=int, default=1)
    p = sub.add_parser("wait"); p.add_argument("text"); p.add_argument("--timeout", type=int, default=15)
    p = sub.add_parser("shot"); p.add_argument("path", nargs="?")
    p = sub.add_parser("apps"); p.add_argument("grep", nargs="?")
    p = sub.add_parser("start"); p.add_argument("pkg")
    p = sub.add_parser("ime"); p.add_argument("arg", nargs="?")
    sub.add_parser("ime-enable")
    p = sub.add_parser("ime-install"); p.add_argument("--apk")
    sub.add_parser("dump")
    p = sub.add_parser("ocr", help="截屏 + 本地 OCR，输出可点击的文字坐标")
    p.add_argument("--crop", default=None, help="只识别一块区域 x1,y1,x2,y2")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--keep", default=None, help="保留截图到这个路径")
    p.add_argument("--minconf", type=float, default=None)
    p.add_argument("--psm", type=int, default=None)
    p.add_argument("--lang", default=None)
    sub.add_parser("ocr-help")

    a = ap.parse_args()
    if not a.action:
        ap.print_help()
        print("\n常见流程：scan（自动连） -> look -> tap-text 微信 -> look -> tap 3")
        return 0

    try:
        if a.action == "info":
            cmd_info()
        elif a.action == "connect":
            cmd_connect(a.host, a.port)
        elif a.action == "pair":
            if a.c is None:
                cmd_pair(a.a, None, a.b)
            else:
                cmd_pair(a.a, a.b, a.c)
        elif a.action == "ports":
            cmd_ports()
        elif a.action == "doctor":
            cmd_doctor()
        elif a.action == "scan":
            m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", a.rng or "")
            if not m:
                raise AdbError("--range 要写成 30000-65535 这样")
            cmd_scan(host=a.host, start=int(m.group(1)), end=int(m.group(2)),
                     timeout=a.timeout, do_connect=not a.no_connect)
        elif a.action == "look":
            cmd_look(a.all, a.json, a.grep)
        elif a.action == "tap":
            if a.b is None:
                cmd_tap(idx=int(a.a))
            else:
                cmd_tap(x=int(a.a), y=int(a.b))
        elif a.action == "longpress":
            if a.b is None:
                cmd_longpress(idx=int(a.a), ms=a.ms)
            else:
                cmd_longpress(x=int(a.a), y=int(a.b), ms=a.ms)
        elif a.action == "tap-text":
            cmd_tap_text(a.text, a.nth)
        elif a.action == "text":
            cmd_text(a.content, restore=not a.keep_ime, verify=a.verify)
        elif a.action == "key":
            cmd_key(a.name)
        elif a.action == "swipe":
            cmd_swipe(a.x1, a.y1, a.x2, a.y2, a.ms)
        elif a.action == "scroll":
            cmd_scroll(a.direction, a.times)
        elif a.action == "wait":
            cmd_wait(a.text, a.timeout)
        elif a.action == "shot":
            cmd_shot(a.path)
        elif a.action == "apps":
            cmd_apps(a.grep)
        elif a.action == "start":
            cmd_start(a.pkg)
        elif a.action == "ime":
            cmd_ime(a.arg)
        elif a.action == "ime-enable":
            cmd_ime_enable()
        elif a.action == "ime-install":
            cmd_ime_install(a.apk)
        elif a.action == "dump":
            cmd_dump()
        elif a.action == "ocr":
            cmd_ocr(a.crop, a.as_json, a.keep, a.minconf, a.psm, a.lang)
        elif a.action == "ocr-help":
            cmd_ocr_help()
        return 0
    except AdbError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
