#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webchat.py - 给 agent 加一个本地图形界面（单文件，纯标准库）

用法:
  export DEEPSEEK_KEY=sk-xxxx        # 只对当前会话有效
  python3 webchat.py                 # 默认 127.0.0.1:8765

  更省事：把配置写进 ~/.config/webchat/env，重启后不用再 export
      DEEPSEEK_KEY=sk-xxxx
      AGENT_WORK=/root/work-kit
      HOST=0.0.0.0

  python3 webchat.py --port 9000
  python3 webchat.py --mock          # 无 key 也能看界面（假对话）

手机浏览器打开 http://127.0.0.1:8765 即可。
只监听 127.0.0.1，同一 WiFi 下的其他人访问不到。
"""

import os
import sys
import json
import time
import shlex
import argparse
import threading
import subprocess
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def load_env_file(path=None):
    """读 KEY=VALUE 文件补进环境变量，已设置的不覆盖。

    默认 ~/.config/webchat/env。虚拟机/手机重启后环境变量会清空，
    写进这个文件就不用每次 export；里面可以同时放 DEEPSEEK_KEY、
    AGENT_WORK、HOST、PORT、AGENT_MAX_TURNS。
    """
    path = path or os.path.expanduser(os.environ.get("WEBCHAT_ENV", "~/.config/webchat/env"))
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return None
    with fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    return path


ENV_FILE = load_env_file()

WORK = os.path.abspath(os.path.expanduser(os.environ.get("AGENT_WORK", "~/work")))
API_KEY = os.environ.get("DEEPSEEK_KEY", "")
API_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# 单条消息内最多几轮「模型 → 工具 → 模型」。12 太小：稍微复杂的任务（看屏幕、改文件、
# 跑命令、验证）十几步就顶到天花板，停下来又不说，看起来就是"卡死"。
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "100"))
HOST = os.environ.get("WEBCHAT_HOST") or os.environ.get("HOST") or "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
MOCK = False

STATE = {"msgs": [], "events": [], "lock": threading.Lock()}
EVENTS_MAX = 600
EVLOCK = threading.Lock()


# ------------------------------------------------------------------ 工具实现

def safe(p):
    fp = os.path.abspath(os.path.join(WORK, p or "."))
    if os.path.commonpath([fp, WORK]) != WORK:
        raise ValueError("路径越界，只能访问工作目录")
    return fp


def ui_path():
    for c in (os.path.join(WORK, "ui.py"), os.path.expanduser("~/work/ui.py"), "ui.py"):
        if os.path.exists(c):
            return c
    return None


def rev_path():
    for c in (os.path.join(WORK, "rev.py"), os.path.expanduser("~/work/rev.py"), "rev.py"):
        if os.path.exists(c):
            return c
    return None


def handle(name, a):
    try:
        if name == "run_shell":
            p = subprocess.run(a["cmd"], shell=True, cwd=WORK, capture_output=True,
                               text=True, timeout=45)
            return ((p.stdout or "") + (p.stderr or ""))[-4000:] or "(无输出)"
        if name == "list_dir":
            fp = safe(a.get("path", "."))
            rows = []
            for n in sorted(os.listdir(fp))[:120]:
                full = os.path.join(fp, n)
                if os.path.isdir(full):
                    rows.append(n + "/")
                else:
                    rows.append("%s  (%s)" % (n, _sz(os.path.getsize(full))))
            return "\n".join(rows) or "(空目录)"
        if name == "read_file":
            fp = safe(a["path"])
            with open(fp, "rb") as f:
                b = f.read(120000)
            return b.decode("utf-8", "replace")
        if name == "write_file":
            fp = safe(a["path"])
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(a.get("content", ""))
            return "已写入 %s (%d 字节)" % (a["path"], len(a.get("content", "").encode()))
        if name == "ui":
            up = ui_path()
            if not up:
                return "ERROR: 找不到 ui.py，请先放到工作目录"
            c = [sys.executable, up] + shlex.split(a.get("cmd", "look"))
            p = subprocess.run(c, cwd=WORK, capture_output=True, text=True, timeout=90)
            return ((p.stdout or "") + (p.stderr or ""))[-4000:] or "(无输出)"
        if name == "rev":
            rp = rev_path()
            if not rp:
                return "ERROR: 找不到 rev.py，请先放到工作目录"
            cmd = [sys.executable, rp, a.get("action", "triage"), a.get("path", "")]
            if a.get("extra"):
                cmd += shlex.split(a["extra"])
            p = subprocess.run(cmd, cwd=WORK, capture_output=True, text=True, timeout=90)
            return ((p.stdout or "") + (p.stderr or ""))[-4000:] or "(无输出)"
    except Exception as e:
        return "ERROR: %s: %s" % (type(e).__name__, e)
    return "unknown tool: " + name


def _sz(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.0f%s" % (n, u) if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0
    return str(n)


TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "在工作目录执行 shell 命令，返回 stdout+stderr。"
                       "超时 45 秒，输出截断到 4000 字符。不要用它跑 pkg install 这类长任务。",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}},
                       "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出目录内容，路径相对工作目录。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": []}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件内容（最多 120KB）。路径相对工作目录。",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写入文本文件，自动创建父目录，覆盖已有内容。",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "ui",
        "description": "操作 X11 图形桌面（鼠标键盘）。cmd 示例：look(截图+窗口+屏幕文字)、"
                       "find 确定(找文字返回坐标)、click 330 303、type 你好、key ctrl+l、"
                       "scroll down 3、win list、region 100 200 400 300(局部放大识别)。"
                       "铁律：先 look 看屏幕，再按坐标操作，操作完再 look 确认；不要凭感觉猜坐标。",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}},
                       "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "rev",
        "description": "逆向侦察工具。分析 APK/ELF(.so)/PE/DEX/ZIP 的结构，"
                       "不做反编译。action: triage(总览)、apk(包名权限组件)、elf(依赖库节表)、"
                       "pe(导入表)、dex(类统计)、strings(字符串)、carve(切出内嵌文件)。",
        "parameters": {"type": "object",
                       "properties": {"action": {"type": "string"},
                                      "path": {"type": "string"},
                                      "extra": {"type": "string",
                                                "description": "附加参数，如 --grep http --limit 30"}},
                       "required": ["action", "path"]}}},
]

def build_system(work):
    return (
        "你是运行在用户手机 Termux 里的本地助手。\n\n"
        "工作目录：%s\n"
        "所有文件路径都相对于它，越界会被拒绝。\n\n"
        "规则：\n"
        "- 直接用中文回答，简洁，不写客套话。\n"
        "- 需要看文件就先 list_dir / read_file，不要猜。\n"
        "- 分析 APK / .so / 二进制时用 rev 工具，不要 cat 二进制。\n"
        "- 一次只做一件事，做完再说结论。\n"
        "- 命令有 45 秒超时、输出截断 4000 字符，避免长任务。\n"
        "- 操作图形界面时：ui look 看屏幕 → ui find/click 操作 → 再 ui look 确认。\n"
        "- 操作安卓手机屏幕用：python3 adui.py look / tap-text 文字 / tap 序号 / key back / text 内容。\n"
        "- adui look 看不到内容（游戏、Flutter 自绘界面、图片里的文字）时，用 "
        "python3 adui.py ocr 截图识别，它直接给出「文字 (x,y)」。\n"
        "- 识别图片或 PDF：python3 ocr.py 文件；要坐标加 --boxes；小字先用 --crop x1,y1,x2,y2 截那一块。\n"
        "- 往手机输入框打中文用 python3 adui.py text \"内容\"；若提示未配好，先执行一次 "
        "python3 adui.py ime-install。不要用 termux-clipboard-set，它会挂住。\n"
        "- 每步只做一个动作，失败就换思路，不要连续盲点。\n" % work
    )


SYSTEM = build_system(WORK)


# ------------------------------------------------------------------ 模型调用

def stream_chat(msgs):
    body = json.dumps({"model": MODEL, "messages": msgs, "tools": TOOLS,
                       "tool_choice": "auto", "stream": True,
                       "temperature": 0.3}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + API_KEY,
        "Accept": "text/event-stream",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("HTTP %s: %s" % (e.code, detail))
    except Exception as e:
        raise RuntimeError("%s: %s" % (type(e).__name__, e))

    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        ch = (obj.get("choices") or [{}])[0]
        d = ch.get("delta") or {}
        if d:
            yield d


def mock_chat(msgs):
    """无 API key 时演示界面用"""
    last = msgs[-1].get("content", "")
    has_tool = any(m.get("role") == "tool" for m in msgs[-2:])
    if not has_tool:
        yield {"reasoning_content": "先看看工作目录里有什么"}
        for ch in "我先看一下工作目录里的文件，再决定怎么处理。":
            time.sleep(0.025)
            yield {"content": ch}
        yield {"tool_calls": [{"index": 0, "id": "call_mock",
                               "function": {"name": "list_dir", "arguments": '{"path":"."}'}}]}
        return
    text = ("目录里有这几个东西。给你整理一下：\n\n"
            "| 文件 | 说明 |\n|---|---|\n"
            "| `rev.py` | 逆向侦察工具 |\n"
            "| `agent.py` | 原来的命令行 agent |\n\n"
            "启动方式：\n\n```sh\npython3 webchat.py --port 8765\n```\n\n"
            "然后在手机浏览器打开 **http://127.0.0.1:8765** 就能用了。")
    for ch in text:
        time.sleep(0.012)
        yield {"content": ch}


# ------------------------------------------------------------------ agent 循环

def trim(msgs, keep=60):
    if len(msgs) <= keep:
        return
    start = len(msgs) - keep
    while start < len(msgs) and msgs[start].get("role") != "user":
        start += 1
    if start < len(msgs):
        msgs[1:] = msgs[start:]


def log_event(ev):
    with EVLOCK:
        evs = STATE["events"]
        if ev.get("t") == "delta" and evs and evs[-1].get("t") == "delta":
            evs[-1]["v"] += ev["v"]
        else:
            evs.append(ev)
        if len(evs) > EVENTS_MAX:
            del evs[:200]


def run_agent(user_text, emit):
    msgs = STATE["msgs"]
    if not msgs:
        msgs.append({"role": "system", "content": SYSTEM})
    emit({"t": "user", "v": user_text})
    msgs.append({"role": "user", "content": user_text})
    steps = 0
    turns = 0
    finished = False
    gen = mock_chat if MOCK else stream_chat

    for turn in range(MAX_TURNS):
        turns = turn + 1
        text_acc = ""
        calls = {}
        order = []
        for d in gen(msgs):
            rc = d.get("reasoning_content")
            if rc:
                emit({"t": "think", "v": rc})
            c = d.get("content")
            if c:
                text_acc += c
                emit({"t": "delta", "v": c})
            for tc in (d.get("tool_calls") or []):
                i = tc.get("index", 0)
                if i not in calls:
                    calls[i] = {"id": "", "name": "", "args": ""}
                    order.append(i)
                f = tc.get("function") or {}
                if f.get("name"):
                    calls[i]["name"] = f["name"]
                if f.get("arguments"):
                    calls[i]["args"] += f["arguments"]
                if tc.get("id"):
                    calls[i]["id"] = tc["id"]

        if not calls:
            msgs.append({"role": "assistant", "content": text_acc})
            finished = True
            break

        tcs = []
        for i in order:
            c = calls[i]
            tcs.append({"id": c["id"] or ("call_%d_%d" % (turn, i)), "type": "function",
                        "function": {"name": c["name"], "arguments": c["args"] or "{}"}})
        msgs.append({"role": "assistant", "content": text_acc or None, "tool_calls": tcs})

        for tc in tcs:
            fn = tc["function"]
            try:
                args = json.loads(fn["arguments"] or "{}")
            except Exception:
                args = {}
            emit({"t": "tool", "id": tc["id"], "name": fn["name"], "args": args})
            t0 = time.time()
            out = handle(fn["name"], args)
            steps += 1
            emit({"t": "tool_end", "id": tc["id"], "out": out[:3500],
                  "ms": int((time.time() - t0) * 1000)})
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out})

        trim(msgs)

    if not finished:
        tip = ("（已连续执行 %d 步，到单次上限 %d 步就停了。任务没完的话，回一句「继续」接着跑；"
               "想一次跑更长：AGENT_MAX_TURNS=300 python3 webchat.py）" % (steps, MAX_TURNS))
        emit({"t": "delta", "v": "\n\n" + tip})
        msgs.append({"role": "assistant", "content": tip})

    emit({"t": "done", "steps": steps, "turns": turns, "hit_limit": (not finished)})


# ------------------------------------------------------------------ HTTP 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "webchat/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML)
        elif path == "/api/history":
            with EVLOCK:
                body = json.dumps(STATE["events"], ensure_ascii=False)
            self._send(200, "application/json", body)
        elif path == "/api/state":
            n = len([m for m in list(STATE["msgs"]) if m.get("role") in ("user", "assistant")])
            self._send(200, "application/json",
                       json.dumps({"messages": n, "work": WORK, "model": MODEL,
                                   "mock": MOCK}, ensure_ascii=False))
        elif path == "/favicon.ico":
            self._send(204, "image/x-icon", b"")
        else:
            self._send(404, "text/plain; charset=utf-8", "not found")

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}

        if path == "/api/reset":
            with STATE["lock"]:
                STATE["msgs"] = []
            with EVLOCK:
                STATE["events"] = []
            self._send(200, "application/json", '{"ok":true}')
            return

        if path != "/api/chat":
            self._send(404, "text/plain; charset=utf-8", "not found")
            return

        text = (data.get("message") or "").strip()
        if not text:
            self._send(400, "application/json", '{"error":"empty message"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(ev):
            log_event(ev)
            try:
                self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                raise BrokenPipeError()

        try:
            with STATE["lock"]:
                run_agent(text, emit)
        except BrokenPipeError:
            return
        except Exception as e:
            try:
                emit({"t": "error", "v": "%s: %s" % (type(e).__name__, e)})
            except Exception:
                pass
        return


# ------------------------------------------------------------------ 前端

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#16171a" media="(prefers-color-scheme: dark)">
<title>Agent</title>
<style>
:root{
  --bg:#ffffff; --bg2:#f7f7f8; --fg:#191a1c; --muted:#8a8f98; --line:#e9e9ee;
  --accent:#2b6cf6; --code:#f6f7f9; --tool:#fbfbfd; --tool-line:#e6e7eb; --ok:#22a06b; --err:#d93025;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#16171a; --bg2:#1e1f23; --fg:#e9eaee; --muted:#8b909a; --line:#2a2c31;
         --accent:#5b8cff; --code:#111214; --tool:#1b1c20; --tool-line:#2c2e34; --ok:#3ecf8e; --err:#ff6b5e; }
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;height:100%}
body{
  background:var(--bg);color:var(--fg);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
  overscroll-behavior:none;
}
#app{display:flex;flex-direction:column;height:100vh;height:100dvh}
header{
  flex:0 0 auto;display:flex;align-items:center;gap:8px;
  padding:calc(env(safe-area-inset-top) + 10px) 16px 10px;
  border-bottom:1px solid var(--line);background:var(--bg);
  position:sticky;top:0;z-index:5;
}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);flex:0 0 auto}
.dot.busy{background:var(--accent);animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
h1{font-size:14px;font-weight:600;margin:0;letter-spacing:.2px}
.sub{font-size:11.5px;color:var(--muted);margin-left:auto;font-variant-numeric:tabular-nums}
#new{border:1px solid var(--line);background:none;color:var(--muted);width:26px;height:26px;
  border-radius:50%;font-size:15px;line-height:1;display:grid;place-items:center;cursor:pointer;
  padding:0;flex:0 0 auto;margin-left:10px}
#feed{flex:1 1 auto;overflow-y:auto;padding:18px 14px 8px;scroll-behavior:smooth;position:relative}
#empty{position:absolute;left:0;right:0;top:34%;text-align:center;padding:0 28px}
#empty .et{font-size:19px;font-weight:650;letter-spacing:.3px;margin-bottom:7px}
#empty .es{font-size:13px;color:var(--muted);line-height:1.75;margin-bottom:22px}
.chips{display:flex;flex-direction:column;gap:9px;max-width:290px;margin:0 auto}
.chips button{border:1px solid var(--line);background:var(--bg2);color:var(--fg);border-radius:12px;
  padding:11px 13px;font-size:13.5px;text-align:left;cursor:pointer;font-family:inherit}
.chips button:active{background:var(--line)}
.msg{margin:0 0 18px;display:flex;flex-direction:column;max-width:100%}
.msg.user{align-items:flex-end}
.bubble{
  background:var(--bg2);border:1px solid var(--line);border-radius:16px;border-bottom-right-radius:5px;
  padding:9px 13px;max-width:86%;white-space:pre-wrap;word-break:break-word;
}
.md{width:100%;word-break:break-word}
.md p{margin:0 0 10px}
.md p:last-child{margin-bottom:0}
.md h1,.md h2,.md h3,.md h4{margin:16px 0 8px;line-height:1.35;font-weight:650}
.md h1{font-size:17px}.md h2{font-size:16px}.md h3{font-size:15px}.md h4{font-size:14.5px}
.md ul,.md ol{margin:6px 0 10px;padding-left:20px}
.md li{margin:3px 0}
.md hr{border:none;border-top:1px solid var(--line);margin:14px 0}
.md blockquote{margin:8px 0;padding:2px 0 2px 11px;border-left:2.5px solid var(--line);color:var(--muted)}
.md code{font:.88em/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--code);border:1px solid var(--tool-line);border-radius:5px;padding:1px 4px}
.md pre{background:var(--code);border:1px solid var(--tool-line);border-radius:10px;
  padding:11px 12px;overflow-x:auto;margin:8px 0 12px}
.md pre code{background:none;border:none;padding:0;font-size:12.5px;line-height:1.55;white-space:pre}
.md table{border-collapse:collapse;width:100%;margin:8px 0 12px;font-size:13.5px;table-layout:auto}
.md th,.md td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top;word-break:break-word}
.md th{background:var(--bg2);font-weight:600;white-space:nowrap}
.md a{color:var(--accent);text-decoration:none}
.tool{border:1px solid var(--tool-line);background:var(--tool);border-radius:11px;margin:0 0 12px;overflow:hidden}
.tool-head{display:flex;align-items:center;gap:8px;padding:9px 11px;cursor:pointer;user-select:none}
.tool-head .ico{width:16px;text-align:center;color:var(--muted);font-size:13px;flex:0 0 auto}
.tool-head .nm{font-size:11.5px;font-weight:600;font-family:ui-monospace,Menlo,Consolas,monospace;
  flex:0 0 auto;background:var(--code);border:1px solid var(--tool-line);border-radius:5px;padding:0 5px}
.tool-head .ar{font-size:12px;color:var(--muted);font-family:ui-monospace,Menlo,Consolas,monospace;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1 1 auto;min-width:0}
.tool-head .st{font-size:10.5px;color:var(--muted);flex:0 0 auto;font-variant-numeric:tabular-nums}
.tool-head .chev{font-size:12px;color:var(--muted);transition:transform .18s;flex:0 0 auto}
.tool.open .tool-head .chev{transform:rotate(90deg)}
.tool-body{display:none;border-top:1px solid var(--tool-line);padding:10px 11px;
  font:12.2px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  white-space:pre-wrap;word-break:break-all;max-height:340px;overflow:auto;color:#5b616b;
  background:var(--code)}
@media (prefers-color-scheme: dark){.tool-body{color:#a8adb8}}
.tool.open .tool-body{display:block}
.spin{display:inline-block;width:10px;height:10px;border:1.6px solid var(--accent);
  border-right-color:transparent;border-radius:50%;animation:rot .7s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
.think{border-left:2px solid var(--line);padding:2px 0 2px 10px;margin:0 0 12px;
  color:var(--muted);font-size:12.6px;white-space:pre-wrap}
.think .hd{font-size:11px;letter-spacing:.5px;margin-bottom:3px;font-weight:600}
.typing{display:inline-flex;gap:3px;padding:4px 0}
.typing i{width:5px;height:5px;border-radius:50%;background:var(--muted);animation:blink 1.2s infinite}
.typing i:nth-child(2){animation-delay:.2s}.typing i:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,60%,100%{opacity:.25}30%{opacity:1}}
.errbox{border:1px solid var(--err);color:var(--err);border-radius:10px;padding:9px 11px;
  font-size:13px;margin:0 0 14px;white-space:pre-wrap;word-break:break-word}
footer{flex:0 0 auto;padding:8px 12px calc(env(safe-area-inset-bottom) + 10px);
  border-top:1px solid var(--line);background:var(--bg)}
.composer{display:flex;align-items:flex-end;gap:8px;background:var(--bg2);border:1px solid var(--line);
  border-radius:20px;padding:5px 5px 5px 14px}
#ta{flex:1 1 auto;border:none;outline:none;background:none;color:var(--fg);resize:none;
  font:15px/1.5 inherit;max-height:120px;padding:7px 0;margin:0}
#ta::placeholder{color:var(--muted)}
#send{flex:0 0 auto;width:34px;height:34px;border-radius:50%;border:none;background:var(--accent);
  color:#fff;font-size:16px;display:grid;place-items:center;transition:opacity .15s;cursor:pointer}
#send:disabled{opacity:.3;cursor:default}
.hint{text-align:center;font-size:11px;color:var(--muted);margin:6px 0 0;letter-spacing:.2px}
</style>
</head>
<body>
<div id="app">
  <header>
    <span class="dot" id="dot"></span>
    <h1>Agent</h1>
    <span class="sub" id="sub">就绪</span>
    <button id="new" title="新对话">＋</button>
  </header>
  <main id="feed">
    <div id="empty">
      <div class="et">今天做什么？</div>
      <div class="es">它能在手机里执行命令、读写文件、分析 APK 和 .so</div>
      <div class="chips">
        <button>看看工作目录里有什么</button>
        <button>分析一个 APK 的权限和组件</button>
        <button>写个 Python 脚本统计文件大小</button>
      </div>
    </div>
  </main>
  <footer>
    <div class="composer">
      <textarea id="ta" rows="1" placeholder="说点什么，或让它干活…"></textarea>
      <button id="send" disabled>↑</button>
    </div>
    <div class="hint" id="hint"></div>
  </footer>
</div>
<script>
const feed=document.getElementById('feed'), ta=document.getElementById('ta'),
      btn=document.getElementById('send'), dot=document.getElementById('dot'),
      sub=document.getElementById('sub'), hint=document.getElementById('hint');
let busy=false, nearBottom=true, cur=null, curRaw='', raf=null, t0=0;

fetch('/api/state').then(r=>r.json()).then(s=>{
  hint.textContent = (s.mock?'演示模式 · ':'') + s.work + ' · ' + s.model;
}).catch(()=>{});

feed.addEventListener('scroll',()=>{
  nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 90;
},{passive:true});

function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

function inline(s){
  s=esc(s);
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
  s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  s=s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,'$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return s;
}
function cells(l){return l.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(x=>x.trim())}

function mdBlock(t){
  const lines=t.split('\n'); let out=[], i=0;
  while(i<lines.length){
    let ln=lines[i];
    if(/^\s*$/.test(ln)){i++;continue}
    if(/\|/.test(ln)&&i+1<lines.length&&/^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1])&&/-/.test(lines[i+1])){
      const head=cells(ln); i+=2; const rows=[];
      while(i<lines.length&&/\|/.test(lines[i])&&! /^\s*$/.test(lines[i])){rows.push(cells(lines[i]));i++}
      out.push('<table><thead><tr>'+head.map(h=>'<th>'+inline(h)+'</th>').join('')+'</tr></thead><tbody>'
        +rows.map(r=>'<tr>'+r.map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>').join('')+'</tbody></table>');
      continue;
    }
    let m=ln.match(/^(#{1,4})\s+(.*)$/);
    if(m){const n=Math.min(m[1].length+2,6);out.push('<h'+n+'>'+inline(m[2])+'</h'+n+'>');i++;continue}
    if(/^\s*(---|\*\*\*|___)\s*$/.test(ln)){out.push('<hr>');i++;continue}
    if(/^\s*[-*+]\s+/.test(ln)){
      const it=[]; while(i<lines.length&&/^\s*[-*+]\s+/.test(lines[i])){it.push(inline(lines[i].replace(/^\s*[-*+]\s+/,'')));i++}
      out.push('<ul>'+it.map(x=>'<li>'+x+'</li>').join('')+'</ul>'); continue;
    }
    if(/^\s*\d+[.)]\s+/.test(ln)){
      const it=[]; while(i<lines.length&&/^\s*\d+[.)]\s+/.test(lines[i])){it.push(inline(lines[i].replace(/^\s*\d+[.)]\s+/,'')));i++}
      out.push('<ol>'+it.map(x=>'<li>'+x+'</li>').join('')+'</ol>'); continue;
    }
    if(/^\s*>\s?/.test(ln)){
      const q=[]; while(i<lines.length&&/^\s*>\s?/.test(lines[i])){q.push(inline(lines[i].replace(/^\s*>\s?/,'')));i++}
      out.push('<blockquote>'+q.join('<br>')+'</blockquote>'); continue;
    }
    const p=[];
    while(i<lines.length&&!/^\s*$/.test(lines[i])&&!/^\s*(#{1,4}\s|[-*+]\s|\d+[.)]\s|>)/.test(lines[i])){p.push(inline(lines[i]));i++}
    out.push('<p>'+p.join('<br>')+'</p>');
  }
  return out.join('');
}
function md(src){
  const parts=String(src).split(/^```/m);
  let html='';
  for(let i=0;i<parts.length;i++){
    if(i%2===1){
      let body=parts[i], nl=body.indexOf('\n');
      if(nl>=0) body=body.slice(nl+1);
      html+='<pre><code>'+esc(body.replace(/\n$/,''))+'</code></pre>';
    }else{
      html+=mdBlock(parts[i]);
    }
  }
  return html;
}

function scroll(){ if(nearBottom) feed.scrollTop=feed.scrollHeight }

function syncEmpty(){
  const e=document.getElementById('empty');
  if(e) e.style.display = feed.querySelector('.msg') ? 'none' : '';
}
function addUser(text){
  const d=document.createElement('div'); d.className='msg user';
  d.innerHTML='<div class="bubble">'+esc(text)+'</div>';
  feed.appendChild(d); nearBottom=true; scroll(); syncEmpty();
}
function addBot(){
  const d=document.createElement('div'); d.className='msg bot';
  d.innerHTML='<div class="md"><span class="typing"><i></i><i></i><i></i></span></div>';
  feed.appendChild(d); scroll();
  return d.querySelector('.md');
}
function cut(){
  if(cur){
    if(curRaw.trim()) cur.innerHTML=md(curRaw);
    else { const m=cur.closest('.msg'); if(m) m.remove(); }
  }
  cur=null; curRaw='';
}
function pushDelta(v){
  if(!cur){ cur=addBot(); curRaw=''; }
  curRaw+=v; schedule();
}
function addThink(v){
  cut();
  let el=feed.querySelector('.think.live');
  if(!el){
    el=document.createElement('div'); el.className='think live';
    el.innerHTML='<div class="hd">思考</div><div class="tx"></div>';
    feed.appendChild(el);
  }
  el.querySelector('.tx').textContent+=v; scroll();
}
function addTool(ev){
  cut();
  const map={run_shell:'shell',list_dir:'ls',read_file:'read',write_file:'write',rev:'rev'};
  const d=document.createElement('div'); d.className='tool'; d.dataset.id=ev.id;
  const a=ev.args||{};
  let arg=a.cmd||a.path||a.action||'';
  if(a.action&&a.path) arg=a.action+' '+a.path;
  if(a.extra) arg+=' '+a.extra;
  d.innerHTML='<div class="tool-head"><span class="ico"><span class="spin"></span></span>'
    +'<span class="nm">'+esc(map[ev.name]||ev.name)+'</span>'
    +'<span class="ar">'+esc(arg)+'</span>'
    +'<span class="st"></span><span class="chev">›</span></div>'
    +'<pre class="tool-body"></pre>';
  d.querySelector('.tool-head').onclick=()=>d.classList.toggle('open');
  feed.appendChild(d); scroll();
}
function endTool(ev){
  const d=feed.querySelector('.tool[data-id="'+CSS.escape(ev.id)+'"]');
  if(!d) return;
  d.querySelector('.ico').innerHTML='✓';
  d.querySelector('.ico').style.color='var(--ok)';
  d.querySelector('.st').textContent=(ev.ms||0)+'ms';
  d.querySelector('.tool-body').textContent=ev.out||'(无输出)';
  scroll();
}
function addErr(v){
  const d=document.createElement('div'); d.className='errbox'; d.textContent=v;
  feed.appendChild(d); scroll();
}

function flush(){
  raf=null;
  if(!cur) return;
  cur.innerHTML=md(curRaw);
  scroll();
}
function schedule(){
  if(!raf) raf=requestAnimationFrame(flush);
}

let pendingUser=null;
function buildEmpty(){
  const d=document.createElement('div'); d.id='empty';
  d.innerHTML='<div class="et">今天做什么？</div>'
    +'<div class="es">它能在手机里执行命令、读写文件、分析 APK 和 .so</div>'
    +'<div class="chips"><button>看看工作目录里有什么</button>'
    +'<button>分析一个 APK 的权限和组件</button>'
    +'<button>写个 Python 脚本统计文件大小</button></div>';
  d.querySelectorAll('button').forEach(b=>b.onclick=()=>{
    ta.value=b.textContent; ta.dispatchEvent(new Event('input')); send();
  });
  return d;
}
document.querySelectorAll('#empty button').forEach(b=>b.onclick=()=>{
  ta.value=b.textContent; ta.dispatchEvent(new Event('input')); send();
});

function onEvent(ev){
  if(ev.t==='user'){
    if(pendingUser===ev.v){ pendingUser=null; return; }
    cut(); addUser(ev.v);
  }
  else if(ev.t==='delta'){ pushDelta(ev.v); }
  else if(ev.t==='think'){ addThink(ev.v); }
  else if(ev.t==='tool'){ addTool(ev); }
  else if(ev.t==='tool_end'){ endTool(ev); }
  else if(ev.t==='error'){ cut(); addErr(ev.v); }
  else if(ev.t==='done'){
    const s=((Date.now()-t0)/1000).toFixed(1);
    sub.textContent=(ev.steps?ev.steps+' 步 · ':'')+s+'s'+(ev.hit_limit?' · 已达上限':'');
  }
}

fetch('/api/history').then(r=>r.json()).then(list=>{
  if(!Array.isArray(list)||!list.length) return;
  list.forEach(ev=>{ if(ev.t!=='done') onEvent(ev) });
  cut(); sub.textContent='历史 · '+list.filter(e=>e.t==='user').length+' 轮';
}).catch(()=>{});

async function send(){
  const text=ta.value.trim();
  if(!text||busy) return;
  ta.value=''; ta.style.height='auto'; btn.disabled=true;
  busy=true; dot.classList.add('busy'); sub.textContent='运行中'; t0=Date.now();
  addUser(text); pendingUser=text;
  curRaw=''; cur=addBot();

  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text})});
    if(!r.ok){ throw new Error('HTTP '+r.status) }
    const rd=r.body.getReader(), dec=new TextDecoder(); let buf='';
    while(true){
      const {done,value}=await rd.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      let k;
      while((k=buf.indexOf('\n\n'))>=0){
        const chunk=buf.slice(0,k); buf=buf.slice(k+2);
        for(const line of chunk.split('\n')){
          if(!line.startsWith('data:')) continue;
          let ev; try{ ev=JSON.parse(line.slice(5).trim()) }catch(e){ continue }
          onEvent(ev);
        }
      }
    }
  }catch(e){
    addErr('连接失败：'+e.message);
    sub.textContent='出错';
  }finally{
    cut();
    const live=feed.querySelector('.think.live'); if(live) live.classList.remove('live');
    busy=false; dot.classList.remove('busy'); btn.disabled=!ta.value.trim();
    scroll();
  }
}

ta.addEventListener('input',()=>{
  ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,120)+'px';
  btn.disabled=!ta.value.trim()||busy;
});
ta.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); send(); }
});
btn.onclick=send;
document.getElementById('new').onclick=async()=>{
  if(busy) return;
  if(!confirm('清空当前对话？')) return;
  await fetch('/api/reset',{method:'POST',body:'{}'}).catch(()=>{});
  feed.innerHTML=''; feed.appendChild(buildEmpty()); cur=null; curRaw=''; pendingUser=null;
  sub.textContent='就绪'; syncEmpty();
};
ta.focus();
</script>
</body>
</html>
"""


# ------------------------------------------------------------------ 启动

def main():
    global MOCK, PORT, WORK
    ap = argparse.ArgumentParser(description="agent 图形界面")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default=HOST, help="默认 127.0.0.1，改成 0.0.0.0 会暴露到局域网")
    ap.add_argument("--mock", action="store_true", help="不需要 API key，演示界面")
    a = ap.parse_args()

    MOCK = a.mock
    PORT = a.port
    WORK = os.path.abspath(os.path.expanduser(WORK))
    os.makedirs(WORK, exist_ok=True)
    globals()["SYSTEM"] = build_system(WORK)

    if not MOCK and not API_KEY:
        print("缺少 DEEPSEEK_KEY。两种办法，任选一个：")
        print("")
        print("  1) 写进文件（推荐，重启不丢）")
        print("       mkdir -p ~/.config/webchat")
        print("       echo 'DEEPSEEK_KEY=sk-你的key' > ~/.config/webchat/env")
        print("       chmod 600 ~/.config/webchat/env")
        print("     同一份文件里还能写：AGENT_WORK=/root/work-kit  HOST=0.0.0.0")
        print("")
        print("  2) 只对本次会话有效")
        print("       export DEEPSEEK_KEY=sk-你的key")
        print("")
        print("  或者加 --mock，不用 key，只看界面。")
        return 2

    srv = ThreadingHTTPServer((a.host, PORT), Handler)
    url = "http://127.0.0.1:%d" % PORT
    print("")
    print("  agent 界面已启动")
    print("  %s" % url)
    print("  工作目录 %s" % WORK)
    print("  模式 %s" % ("MOCK 演示" if MOCK else MODEL))
    if a.host not in ("127.0.0.1", "localhost"):
        print("  监听 %s:%d（所有网卡，端口映射能进来了）" % (a.host, PORT))
    if ENV_FILE:
        print("  配置 %s" % ENV_FILE)
    print("  Ctrl+C 停止")
    print("")
    sys.stdout.flush()
    if os.environ.get("TERMUX_VERSION") or "com.termux" in sys.executable:
        try:
            subprocess.Popen(["termux-open-url", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
