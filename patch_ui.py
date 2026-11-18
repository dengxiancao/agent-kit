#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 agent.py 加 ui 工具（操作图形桌面）。改前自动备份。"""
import os, re, shutil, sys

P = os.path.expanduser("~/work/agent.py")
if not os.path.exists(P):
    sys.exit("找不到 %s" % P)

s = open(P).read()
if '"name": "ui"' in s or "name == \"ui\"" in s:
    print("已经加过了，无需重复。")
    sys.exit(0)

shutil.copy(P, P + ".bak")

# 1) TOOLS 末尾追加定义
UI_TOOL = '''    {"type": "function", "function": {
        "name": "ui",
        "description": "Operate the X11 desktop with mouse/keyboard. cmd examples: "
                       "look (screenshot + windows + on-screen text), find OK (find text, returns x y), "
                       "click 330 303, type hello, key ctrl+l, scroll down 3, win list, "
                       "region 100 200 400 300 (zoom into area for small text). "
                       "ALWAYS look first, then act, then look again to verify. Never guess coordinates.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
]

def safe(p):'''

if "]\n\ndef safe(p):" in s:
    s = s.replace("]\n\ndef safe(p):", UI_TOOL, 1)
else:
    sys.exit("锚点 1 失败：TOOLS 结构不符合预期，未修改")

# 2) handle 分支
UI_BRANCH = '''        if name == "ui":
            script = os.path.join(WORK, "ui.py")
            if not os.path.exists(script):
                return "ERROR: ui.py not found, put it in the work dir"
            p = subprocess.run([sys.executable, script] + (a.get("cmd") or "look").split(),
                               capture_output=True, text=True, errors="replace", timeout=90)
            return ((p.stdout or "") + (p.stderr or ""))[-4000:] or "(no output)"
        if name == "list_dir":'''

if '        if name == "list_dir":' in s:
    s = s.replace('        if name == "list_dir":', UI_BRANCH, 1)
else:
    sys.exit("锚点 2 失败：handle 结构不符合预期，未修改")

# 3) 超时 10 -> 30
s2, n = re.subn(r"CMD_TIMEOUT\s*=\s*10\b", "CMD_TIMEOUT = 30", s)

# 4) system prompt 补一句 GUI 守则
old_prompt = 'instead of trying again with different flags."}'
new_prompt = ('instead of trying again with different flags. '
              'To control the GUI, use the ui tool: look first, then click, then look again."}')
if old_prompt in s2:
    s2 = s2.replace(old_prompt, new_prompt, 1)

open(P, "w").write(s2)
import py_compile
try:
    py_compile.compile(P, doraise=True)
except Exception as e:
    shutil.copy(P + ".bak", P)
    sys.exit("语法检查失败，已回滚：%s" % e)
print("完成：加了 ui 工具，CMD_TIMEOUT 改成 30（%d 处），备份 %s.bak" % (n, P))
