#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webchat.py - agent 的本地图形界面（v2：会话持久化 + 三栏界面）

用法:
  export DEEPSEEK_KEY=sk-xxxx        # 只对当前会话有效
  python3 webchat.py                 # 默认 127.0.0.1:8765

  更省事：把配置写进 ~/.config/webchat/env，重启后不用再 export
      DEEPSEEK_KEY=sk-xxxx
      AGENT_WORK=/root/work-kit
      HOST=0.0.0.0

  python3 webchat.py --port 9000
  python3 webchat.py --mock          # 无 key 也能看界面（假对话）
  python3 webchat.py --no-db         # 不落盘，退回旧的单会话内存模式

数据都存在 ~/.local/share/webchat/sessions.db（可用 WEBCHAT_DB 改）。

只监听 127.0.0.1，同一 WiFi 下的其他人访问不到。
"""

import os
import re
import sys
import json
import time
import uuid
import shlex
import sqlite3
import argparse
import secrets
import socket
import threading
import subprocess
import queue
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs, urlencode


# ------------------------------------------------------------------ 配置

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

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

WORK = os.path.abspath(os.path.expanduser(os.environ.get("AGENT_WORK", "~/work")))

# 跑在手机上还是服务器上，决定了提示词、工具集和超时。以前这里写死成 Termux，
# 搬到 Ubuntu 后模型一直以为自己在手机上，还去调 adui.py / ui.py 这些不存在的脚本。
IS_ANDROID = bool(os.environ.get("TERMUX_VERSION")
                  or "com.termux" in sys.executable
                  or os.path.exists("/system/build.prop"))
# 手机上 45 秒够用（apt/pkg 都慢且不该跑），服务器上装包、编译动辄几分钟，给 120 秒。
CMD_TIMEOUT = int(os.environ.get("AGENT_CMD_TIMEOUT", "45" if IS_ANDROID else "120"))
# 连续几次工具失败就熔断。之前是硬耗到 100 步上限，界面上看就是"卡住乱试"。
FAIL_STREAK_LIMIT = int(os.environ.get("AGENT_FAIL_LIMIT", "4"))


def os_name():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return sys.platform


API_KEY = os.environ.get("DEEPSEEK_KEY", "")
API_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# 单条消息内最多几轮「模型 → 工具 → 模型」。12 太小：稍微复杂的任务（看屏幕、改文件、
# 跑命令、验证）十几步就顶到天花板，停下来又不说，看起来就是"卡死"。
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "100"))
HOST = os.environ.get("WEBCHAT_HOST") or os.environ.get("HOST") or "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
DB_PATH = os.path.expanduser(os.environ.get("WEBCHAT_DB", "~/.local/share/webchat/sessions.db"))

# 可选模型。前端顶部 chip 点一下就能换，存在会话上，下轮生效。
MODELS = [m.strip() for m in os.environ.get(
    "WEBCHAT_MODELS", "deepseek-chat,deepseek-reasoner").split(",") if m.strip()]
if MODEL not in MODELS:
    MODELS.insert(0, MODEL)

# 上下文压缩：估算 token 超过 CTX_LIMIT 就把老消息揉成一段摘要，只保留最近 CTX_KEEP 条。
# 摘要不花 token（本地规则生成），原始消息仍留在库里，界面照常能翻。
CTX_LIMIT = int(os.environ.get("AGENT_CTX_LIMIT", "48000"))
CTX_KEEP = int(os.environ.get("AGENT_CTX_KEEP", "12"))

MOCK = False
USE_DB = True
TOKEN = ""


def load_token(host):
    """访问口令。只监听本机时不需要；一旦 0.0.0.0，必须有，否则同网段的人能看能指挥。

    优先级：WEBCHAT_TOKEN 环境变量 > ~/.config/webchat/token > 自动生成。
    生成后写文件（600），下次启动还是同一个，手机加一次书签就一直能用。
    """
    t = (os.environ.get("WEBCHAT_TOKEN") or "").strip()
    if t:
        return t
    path = os.path.expanduser("~/.config/webchat/token")
    try:
        with open(path, "r", encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    except OSError:
        pass
    if host in ("127.0.0.1", "localhost", "::1"):
        return ""
    t = secrets.token_urlsafe(12)
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(t + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass
    return t


# ------------------------------------------------------------------ 存储层

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  pinned      INTEGER DEFAULT 0,
  archived    INTEGER DEFAULT 0,
  model       TEXT,
  work        TEXT,
  steps       INTEGER DEFAULT 0,
  tokens_in   INTEGER DEFAULT 0,
  tokens_out  INTEGER DEFAULT 0,
  summary     TEXT,
  compact_upto INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  sid          TEXT NOT NULL,
  seq          INTEGER NOT NULL,
  role         TEXT NOT NULL,
  content      TEXT,
  reasoning    TEXT,
  tool_calls   TEXT,
  tool_call_id TEXT,
  name         TEXT,
  meta         TEXT,
  created_at   INTEGER NOT NULL,
  UNIQUE(sid, seq)
);

CREATE INDEX IF NOT EXISTS idx_msg_sid_seq ON messages(sid, seq);
CREATE INDEX IF NOT EXISTS idx_sess_upd    ON sessions(archived, pinned DESC, updated_at DESC);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS msg_fts USING fts5(
  content, sid UNINDEXED, tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS msg_ai AFTER INSERT ON messages BEGIN
  INSERT INTO msg_fts(rowid, content, sid) VALUES (new.id, new.content, new.sid);
END;
CREATE TRIGGER IF NOT EXISTS msg_ad AFTER DELETE ON messages BEGIN
  DELETE FROM msg_fts WHERE rowid = old.id;
END;
"""


def new_sid():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def now():
    return int(time.time())


def one_line(s, n=100):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s[:n] + "…" if len(s) > n else s


def summarize_rows(rows, prev=None, limit=1500):
    """把一批消息压成要点，纯本地规则，不调模型。

    原则：用户的诉求不能丢，助手的结论留首句，工具只留统计和碰过的文件。
    """
    asked, said, tools, files = [], [], {}, []
    for r in rows:
        role, c = r["role"], (r["content"] or "").strip()
        if role == "user" and c:
            asked.append(one_line(c, 110))
        elif role == "assistant" and c:
            said.append(one_line(c, 130))
        elif role == "tool":
            nm = r["name"] or "tool"
            tools[nm] = tools.get(nm, 0) + 1
            for m in re.finditer(r"[\w./-]+\.(?:py|sh|md|json|txt|log|apk|so|elf|png|jpg|db)\b",
                                 c[:600]):
                t = m.group(0)
                if t not in files and len(files) < 8:
                    files.append(t)
    out = []
    if prev:
        out.append("此前摘要：" + one_line(prev, 400))
    def uniq(seq):
        seen, out = set(), []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    if asked:
        out.append("用户提出过：")
        out += ["- " + a for a in uniq(asked)[-10:]]
    if said:
        out.append("已达成的结论：")
        out += ["- " + a for a in uniq(said)[-6:]]
    if tools:
        out.append("用过的工具：" + "、".join("%s×%d" % (k, v) for k, v in tools.items()))
    if files:
        out.append("碰过的文件：" + "、".join(files))
    txt = "\n".join(out)
    if len(txt) > limit:
        txt = txt[:limit] + "\n…（更早的细节已省略）"
    return txt


class Store:
    """会话与消息的持久化。单连接 + 锁，够用且不会 database is locked。"""

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path) if path != ":memory:" else ""
        if d:
            os.makedirs(d, exist_ok=True)
        self.lock = threading.RLock()
        self.repaired = set()
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.con.row_factory = sqlite3.Row
        with self.lock:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=NORMAL")
            self.con.execute("PRAGMA busy_timeout=5000")
            self.con.executescript(SCHEMA)
            # 老库没有这两列，补上（v2.1 的上下文压缩要存摘要和压缩边界）
            cols = {r[1] for r in self.con.execute("PRAGMA table_info(sessions)")}
            for name, ddl in (("summary", "TEXT"), ("compact_upto", "INTEGER DEFAULT 0")):
                if name not in cols:
                    self.con.execute("ALTER TABLE sessions ADD COLUMN %s %s" % (name, ddl))
            try:
                self.con.executescript(FTS_SCHEMA)
                self.fts = True
            except sqlite3.Error:
                self.fts = False
            self.con.commit()

    # ---------- 会话 ----------
    def create(self, title="新对话"):
        sid = new_sid()
        t = now()
        with self.lock:
            self.con.execute(
                "INSERT INTO sessions(id,title,created_at,updated_at,model,work) "
                "VALUES(?,?,?,?,?,?)", (sid, title, t, t, MODEL, WORK))
            self.con.commit()
        return sid

    def list(self, q=None, limit=200):
        with self.lock:
            if q:
                like = "%" + q.replace("%", "").replace("_", "") + "%"
                rows = self.con.execute(
                    "SELECT DISTINCT s.* FROM sessions s "
                    "LEFT JOIN messages m ON m.sid = s.id "
                    "WHERE s.archived = 0 AND (s.title LIKE ? OR m.content LIKE ?) "
                    "ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?",
                    (like, like, limit)).fetchall()
            else:
                rows = self.con.execute(
                    "SELECT * FROM sessions WHERE archived = 0 "
                    "ORDER BY pinned DESC, updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, sid):
        with self.lock:
            r = self.con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    def update(self, sid, **kw):
        allow = {"title", "pinned", "archived", "model", "work",
                 "steps", "tokens_in", "tokens_out", "updated_at"}
        sets, vals = [], []
        for k, v in kw.items():
            if k in allow:
                sets.append(k + "=?")
                vals.append(v)
        if not sets:
            return
        vals.append(sid)
        with self.lock:
            self.con.execute("UPDATE sessions SET " + ",".join(sets) + " WHERE id=?", vals)
            self.con.commit()

    def delete(self, sid):
        with self.lock:
            self.con.execute("DELETE FROM messages WHERE sid=?", (sid,))
            self.con.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.con.commit()

    def bump(self, sid, **delta):
        """累加统计字段。"""
        with self.lock:
            self.con.execute(
                "UPDATE sessions SET updated_at=?, steps=steps+?, "
                "tokens_in=tokens_in+?, tokens_out=tokens_out+? WHERE id=?",
                (now(), delta.get("steps", 0), delta.get("tokens_in", 0),
                 delta.get("tokens_out", 0), sid))
            self.con.commit()

    # ---------- 消息 ----------
    def _seq(self, sid):
        r = self.con.execute("SELECT COALESCE(MAX(seq),0) FROM messages WHERE sid=?", (sid,)).fetchone()
        return int(r[0]) + 1

    def add(self, sid, role, content=None, reasoning=None, tool_calls=None,
            tool_call_id=None, name=None, meta=None):
        with self.lock:
            if not self.con.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
                return -1, -1
            seq = self._seq(sid)
            t = now()
            cur = self.con.execute(
                "INSERT INTO messages(sid,seq,role,content,reasoning,tool_calls,"
                "tool_call_id,name,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sid, seq, role, content, reasoning,
                 json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                 tool_call_id, name,
                 json.dumps(meta, ensure_ascii=False) if meta else None, t))
            self.con.commit()
            return seq, cur.lastrowid

    def messages(self, sid, after_seq=0, limit=None):
        with self.lock:
            sql = ("SELECT * FROM messages WHERE sid=? AND seq>? ORDER BY seq"
                   + (" LIMIT %d" % limit if limit else ""))
            rows = self.con.execute(sql, (sid, after_seq)).fetchall()
        return [dict(r) for r in rows]

    def context(self, sid, limit=None):
        """还原成可以直接送 API 的 messages 数组。

        压缩过的会话只从 compact_upto 之后取消息，并把摘要拼进 system。
        原始消息一条不删，界面还能往上翻。
        """
        self.repair(sid)
        s = self.get(sid) or {}
        upto = int(s.get("compact_upto") or 0)
        rows = self.messages(sid, after_seq=upto)
        if limit and len(rows) > limit:
            rows = rows[-limit:]
            while rows and rows[0]["role"] != "user":
                rows.pop(0)
        sysmsg = SYSTEM
        summ = (s.get("summary") or "").strip()
        if summ:
            sysmsg = (SYSTEM + "\n\n【早期对话摘要】（为省上下文，较早的消息已折叠，"
                      "原始记录仍在本地）\n" + summ)
        out = [{"role": "system", "content": sysmsg}]
        for r in rows:
            role = r["role"]
            if role == "user":
                out.append({"role": "user", "content": r["content"] or ""})
            elif role == "assistant":
                m = {"role": "assistant", "content": r["content"] or None}
                if r["tool_calls"]:
                    m["tool_calls"] = json.loads(r["tool_calls"])
                if m["content"] or m.get("tool_calls"):
                    out.append(m)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": r["tool_call_id"],
                            "content": r["content"] or ""})
        return out

    def ctx_tokens(self, sid):
        """当前真正会发出去的那部分，估算 token。"""
        return sum(est_tokens(m.get("content") or "") for m in self.context(sid))

    def compact(self, sid, keep=None, force=False):
        """把较早的消息折成一段摘要。返回 dict 或 None（不够长就不动）。

        摘要用本地规则生成：只留用户问句首行、助手结论首行、工具调用统计。
        不调模型 = 零成本、零延迟、行为可预测。
        """
        keep = CTX_KEEP if keep is None else max(2, int(keep))
        s = self.get(sid)
        if not s:
            return None
        upto = int(s.get("compact_upto") or 0)
        rows = self.messages(sid, after_seq=upto)
        before = sum(est_tokens(r["content"] or "") + est_tokens(r["reasoning"] or "")
                     for r in rows)
        if not force and before < CTX_LIMIT:
            return None
        # 切点必须落在 user 上，否则会把一轮问答劈开；至少保留最后一轮完整
        users = [i for i, r in enumerate(rows) if r["role"] == "user"]
        if len(users) < 2:
            return None
        target = max(0, len(rows) - keep)
        cut = None
        for i in users:
            if i <= target:
                cut = i
        if cut is None or cut <= 0:
            cut = users[-1]          # 第一轮就撑爆了，只留最后一轮
        if cut <= 0 or cut >= len(rows):
            return None
        old = rows[:cut]
        summ = summarize_rows(old, prev=s.get("summary"))
        boundary = old[-1]["seq"]
        with self.lock:
            self.con.execute(
                "UPDATE sessions SET summary=?, compact_upto=?, updated_at=? WHERE id=?",
                (summ, boundary, now(), sid))
            self.con.commit()
        after = sum(est_tokens(r["content"] or "") + est_tokens(r["reasoning"] or "")
                    for r in rows[cut:])
        return {"removed": len(old), "before": before, "after": after,
                "kept": len(rows) - cut, "summary_chars": len(summ)}

    def truncate(self, sid, seq_from):
        """删掉 seq >= seq_from 的消息（重新生成 / 建分支时用）。"""
        with self.lock:
            n = self.con.execute("SELECT COUNT(*) FROM messages WHERE sid=? AND seq>=?",
                                 (sid, seq_from)).fetchone()[0]
            self.con.execute("DELETE FROM messages WHERE sid=? AND seq>=?", (sid, seq_from))
            self.con.execute(
                "UPDATE sessions SET compact_upto=0, summary=NULL, updated_at=? "
                "WHERE id=? AND compact_upto>=?", (now(), sid, seq_from))
            self.con.commit()
        return n

    def clone(self, sid, upto_seq=None, title=None):
        """从某条消息处分叉：复制会话到新 id，只带走 upto_seq 及其之前的内容。"""
        src = self.get(sid)
        if not src:
            return None
        new_id = self.create((title or src["title"] or "新对话") + " · 分支")
        rows = self.messages(sid)
        if upto_seq:
            rows = [r for r in rows if r["seq"] <= upto_seq]
        cu = int(src.get("compact_upto") or 0)
        summ = src.get("summary")
        if upto_seq and cu > upto_seq:      # 分叉点比压缩边界还早，摘要用不上
            cu, summ = 0, None
        with self.lock:
            for r in rows:
                self.con.execute(
                    "INSERT INTO messages(sid,seq,role,content,reasoning,tool_calls,"
                    "tool_call_id,name,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id, r["seq"], r["role"], r["content"], r["reasoning"],
                     r["tool_calls"], r["tool_call_id"], r["name"], r["meta"],
                     r["created_at"]))
            self.con.execute(
                "UPDATE sessions SET model=?, work=?, steps=0, tokens_in=0, tokens_out=0, "
                "summary=?, compact_upto=? WHERE id=?",
                (src["model"] or MODEL, src["work"] or WORK,
                 summ, cu, new_id))
            self.con.commit()
        return new_id

    def last_user(self, sid):
        with self.lock:
            r = self.con.execute(
                "SELECT * FROM messages WHERE sid=? AND role='user' "
                "ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
        return dict(r) if r else None

    def overview(self):
        """全局用量，库清理面板用。"""
        with self.lock:
            n_sess = self.con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            n_msg = self.con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            n_empty = self.con.execute(
                "SELECT COUNT(*) FROM sessions s WHERE NOT EXISTS "
                "(SELECT 1 FROM messages m WHERE m.sid=s.id)").fetchone()[0]
            rows = self.con.execute(
                "SELECT id,title,updated_at,pinned FROM sessions "
                "ORDER BY updated_at ASC").fetchall()
            tin = self.con.execute("SELECT COALESCE(SUM(tokens_in),0) FROM sessions").fetchone()[0]
            tout = self.con.execute("SELECT COALESCE(SUM(tokens_out),0) FROM sessions").fetchone()[0]
        return {"sessions": n_sess, "messages": n_msg, "empty": n_empty,
                "oldest": rows[0]["updated_at"] if rows else 0,
                "db_size": self.size(), "tokens_in": tin, "tokens_out": tout,
                "old": [dict(r) for r in rows if r["updated_at"] < now() - 30 * 86400][:200]}

    def cleanup(self, days=30, drop_empty=True, vacuum=True, dry=False):
        """库清理：删空会话 + 删 N 天没动过且没置顶的会话，再 VACUUM 收空间。"""
        cutoff = now() - max(1, int(days)) * 86400
        victim = []
        with self.lock:
            if drop_empty:
                victim += [r[0] for r in self.con.execute(
                    "SELECT id FROM sessions WHERE updated_at<? AND pinned=0 AND NOT EXISTS "
                    "(SELECT 1 FROM messages m WHERE m.sid=sessions.id)",
                    (now() - 3600,)).fetchall()]
            victim += [r[0] for r in self.con.execute(
                "SELECT id FROM sessions WHERE updated_at<? AND pinned=0", (cutoff,)).fetchall()]
        victim = [v for v in dict.fromkeys(victim) if v]
        before = self.size()
        if dry:
            return {"would_delete": len(victim), "db_size": before, "dry": True,
                    "ids": victim[:50]}
        for sid in victim:
            self.delete(sid)
        if vacuum:
            with self.lock:
                try:
                    self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self.con.commit()
                    self.con.execute("VACUUM")
                    self.con.commit()
                except sqlite3.Error:
                    pass
        return {"deleted": len(victim), "db_size": self.size(), "before": before,
                "freed": max(0, before - self.size())}

    def repair(self, sid):
        """补掉崩溃时留下的半条消息：assistant 有 tool_calls，但 tool 结果没写回。
        不补的话，下次把这段发出去必定 400。"""
        if sid in self.repaired:
            return
        self.repaired.add(sid)
        with self.lock:
            r = self.con.execute(
                "SELECT * FROM messages WHERE sid=? AND role='assistant' "
                "AND tool_calls IS NOT NULL ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
            if not r:
                return
            try:
                tcs = json.loads(r["tool_calls"])
            except Exception:
                return
            have = {x[0] for x in self.con.execute(
                "SELECT tool_call_id FROM messages WHERE sid=? AND role='tool' "
                "AND seq>?", (sid, r["seq"])).fetchall()}
            for tc in tcs:
                tid = tc.get("id") or ""
                if tid and tid not in have:
                    seq = self._seq(sid)
                    self.con.execute(
                        "INSERT INTO messages(sid,seq,role,content,tool_call_id,created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (sid, seq, "tool", "（任务被中断，没有拿到结果）", tid, now()))
            self.con.commit()

    def first_tool_of(self, sid):
        """给会话列表显示摘要用。"""
        with self.lock:
            r = self.con.execute(
                "SELECT content FROM messages WHERE sid=? AND role='user' "
                "ORDER BY seq LIMIT 1", (sid,)).fetchone()
        return (r[0] or "") if r else ""

    def stats(self, sid):
        with self.lock:
            s = self.get(sid)
            rows = self.con.execute(
                "SELECT role, name, meta, content, reasoning, seq FROM messages WHERE sid=?",
                (sid,)).fetchall()
        chars = sum(len(r["content"] or "") + len(r["reasoning"] or "") for r in rows)
        upto = int((s or {}).get("compact_upto") or 0)
        summ = (s or {}).get("summary") or ""
        # ctx 是「真正发出去的那部分」，压缩后要明显变小，否则进度条没意义
        ctx = est_tokens(summ) + sum(est_tokens(r["content"] or "") + est_tokens(r["reasoning"] or "")
                                     for r in rows if r["seq"] > upto)
        tools = [dict(r) for r in rows if r["role"] == "tool"]
        msgs = len([r for r in rows if r["role"] in ("user", "assistant")])
        return {
            "id": sid,
            "messages": msgs,
            "chars": chars,
            "ctx": ctx,
            "ctx_all": sum(est_tokens(r["content"] or "") + est_tokens(r["reasoning"] or "")
                           for r in rows),
            "compacted": bool(upto),
            "compacted_msgs": len([r for r in rows if r["seq"] <= upto]),
            "summary_chars": len(summ),
            "tokens": s["tokens_in"] + s["tokens_out"] if s else 0,
            "tokens_in": s["tokens_in"] if s else 0,
            "tokens_out": s["tokens_out"] if s else 0,
            "steps": s["steps"] if s else 0,
            "tools": [{"name": t["name"], "meta": json.loads(t["meta"]) if t["meta"] else {}}
                      for t in tools][-8:],
            "work": s["work"] if s else WORK,
            "model": s["model"] if s else MODEL,
        }

    def size(self):
        try:
            n = 0
            for suffix in ("", "-wal", "-shm"):
                p = self.path + suffix
                if os.path.exists(p):
                    n += os.path.getsize(p)
            return n
        except OSError:
            return 0


# ------------------------------------------------------------------ 事件总线

class Bus:
    """一个会话一条事件流。带自增 seq + 环形缓冲，刷新页面能接上正在跑的任务。"""

    def __init__(self, sid):
        self.sid = sid
        self.seq = 0
        self.buf = []
        self.subs = []
        self.lock = threading.Lock()
        self.closed = False

    def reset(self):
        with self.lock:
            self.seq = 0
            self.buf = []

    def pub(self, ev):
        with self.lock:
            self.seq += 1
            ev["seq"] = self.seq
            self.buf.append(ev)
            if len(self.buf) > 2000:
                del self.buf[:500]
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

    def after(self, seq):
        with self.lock:
            return [e for e in self.buf if e.get("seq", 0) > seq]

    def subscribe(self):
        q = queue.Queue(maxsize=4000)
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def close(self):
        with self.lock:
            self.closed = True
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait({"t": "__close__"})
            except queue.Full:
                pass


BUSES = {}
BUSES_LOCK = threading.Lock()
RUNNING = {}          # sid -> {"stop": Event, "started": ts, "bus": Bus}
RUN_LOCK = threading.Lock()
MAX_BUSES = 8


def get_bus(sid):
    with BUSES_LOCK:
        b = BUSES.get(sid)
        if b is None:
            if len(BUSES) >= MAX_BUSES:
                for k in list(BUSES.keys()):
                    if k not in RUNNING:
                        BUSES.pop(k, None)
                        break
            b = Bus(sid)
            BUSES[sid] = b
        return b


def is_running(sid):
    with RUN_LOCK:
        return sid in RUNNING


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
            # stdin 必须断开。命令一旦去读标准输入（git、ssh、某些 grep），
            # 就会一直等到超时——表现就是"连 ls 都超时"。
            try:
                p = subprocess.run(a["cmd"], shell=True, cwd=WORK, capture_output=True,
                                   text=True, timeout=CMD_TIMEOUT,
                                   stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired as e:
                part = e.stdout or ""
                if isinstance(part, bytes):
                    part = part.decode("utf-8", "replace")
                return ("ERROR: 超过 %d 秒没返回，已终止。\n已产生的输出：\n%s\n"
                        "换个做法：拆成几条短命令；或用 nohup 放后台再 tail 日志。"
                        % (CMD_TIMEOUT, part[-1500:] or "(无)"))
            out = (p.stdout or "") + (p.stderr or "")
            if p.returncode:
                out = "[退出码 %d]\n%s" % (p.returncode, out)
            return out[-4000:] or "(无输出)"
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


def visible_tools():
    """只把当前环境真能用的工具交给模型。

    手机版才需要 ui（X11 桌面）和 rev（APK/ELF 侦察）；搬到服务器后这两个脚本
    不一定在，模型却会照着提示词去调，白浪费步数。存在才暴露。
    """
    names = {"run_shell", "list_dir", "read_file", "write_file"}
    # ui 要真的能碰到图形会话才给，服务器上没有 DISPLAY，调了只会报错白耗步数。
    if ui_path() and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        names.add("ui")
    if rev_path():
        names.add("rev")
    return [t for t in TOOLS if t["function"]["name"] in names]


TOOL_SET = visible_tools()


def build_system(work):
    if IS_ANDROID:
        return (
            "你是运行在用户手机 Termux 里的本地助手。\n\n"
            "工作目录：%s\n"
            "所有文件路径都相对于它，越界会被拒绝。\n\n"
            "规则：\n"
            "- 直接用中文回答，简洁，不写客套话。\n"
            "- 需要看文件就先 list_dir / read_file，不要猜。\n"
            "- 分析 APK / .so / 二进制时用 rev 工具，不要 cat 二进制。\n"
            "- 一次只做一件事，做完再说结论。\n"
            "- 命令有 %d 秒超时、输出截断 4000 字符，避免长任务。\n"
            "- 操作图形界面时：ui look 看屏幕 → ui find/click 操作 → 再 ui look 确认。\n"
            "- 操作安卓手机屏幕用：python3 adui.py look / tap-text 文字 / tap 序号 / key back / text 内容。\n"
            "- adui look 看不到内容（游戏、Flutter 自绘界面、图片里的文字）时，用 "
            "python3 adui.py ocr 截图识别，它直接给出「文字 (x,y)」。\n"
            "- 识别图片或 PDF：python3 ocr.py 文件；要坐标加 --boxes；小字先用 --crop x1,y1,x2,y2 截那一块。\n"
            "- 往手机输入框打中文用 python3 adui.py text \"内容\"；若提示未配好，先执行一次 "
            "python3 adui.py ime-install。不要用 termux-clipboard-set，它会挂住。\n"
            "- 每步只做一个动作，失败就换思路，不要连续盲点。\n" % (work, CMD_TIMEOUT)
        )

    try:
        uid = os.getuid()
    except Exception:
        uid = -1
    return (
        "你是运行在 Linux 服务器上的本地助手。\n\n"
        "系统：%s，Python %s，当前 uid=%d（%s）\n"
        "工作目录：%s —— shell 命令都在这里执行，相对路径基于它。\n"
        "read_file / write_file / list_dir 三个文件工具被限制在工作目录内，越界会被拒绝；"
        "run_shell 不受此限制，但仍受系统权限约束。\n\n"
        "规则：\n"
        "- 直接用中文回答，简洁，不写客套话。\n"
        "- 先看再改：用 ls / cat / grep / systemctl status 确认现状，再动手，不要凭猜测敲命令。\n"
        "- 一次只做一件事，做完说结论。\n"
        "- 命令超时 %d 秒，输出截断 4000 字符。apt install、编译、大文件下载这类长任务，"
        "用 nohup ... > /tmp/x.log 2>&1 & 放后台，再 sleep + tail 日志轮询。\n"
        "- 绝对不要执行需要交互输入的命令（nano、vi、passwd、ssh 首次连接、apt 的 y/n 确认）。"
        "改用非交互写法：sed -i、tee、apt-get install -y、ssh -o StrictHostKeyChecking=no。\n"
        "- 改系统配置前先备份：cp 文件 文件.bak。\n"
        "- 同一条命令连续失败两次就停下来，把报错原文告诉用户，不要换个写法反复试。\n"
        "- 不要操作网络和挂载（ip、iptables、umount、mount -o bind），这类操作会把机器自己的网络弄断。\n"
    ) % (os_name(), sys.version.split()[0], uid,
         "root，权限很大，破坏性命令要格外小心" if uid == 0 else "普通用户",
         work, CMD_TIMEOUT)


SYSTEM = build_system(WORK)


# ------------------------------------------------------------------ 模型调用

def stream_chat(msgs, model=None):
    body = json.dumps({"model": model or MODEL, "messages": msgs, "tools": TOOL_SET,
                       "tool_choice": "auto", "stream": True,
                       "stream_options": {"include_usage": True},
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
        if obj.get("usage"):
            yield {"__usage__": obj["usage"]}
        ch = (obj.get("choices") or [{}])[0]
        d = ch.get("delta") or {}
        if d:
            yield d


def est_tokens(s):
    if not s:
        return 0
    cjk = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
    return int(cjk * 1.05 + (len(s) - cjk) / 3.6)


def mock_chat(msgs):
    """无 API key 时演示界面用，走完整的事件序列（思考 / 工具 / 正文 / 用量）。"""
    last = msgs[-1] if msgs else {}
    if last.get("role") == "tool":
        yield {"reasoning_content": "拿到输出了，整理成结论"}
        text = ("目录如下。给它做点事的话，直接说就行：\n\n"
                "| 文件 | 说明 |\n|---|---|\n"
                "| `rev.py` | 逆向侦察工具 |\n"
                "| `ocr.py` | 本地 OCR |\n\n"
                "比如：\n\n```sh\npython3 rev.py apk downloads/wechat.apk\n```\n\n"
                "要我直接跑吗？")
        for ch in text:
            time.sleep(0.008)
            yield {"content": ch}
        yield {"__usage__": {"prompt_tokens": 1180, "completion_tokens": 86}}
        return
    yield {"reasoning_content": "先看看工作目录里有什么，再决定怎么处理。"}
    for ch in "我先看一下工作目录里的文件，再决定怎么处理。":
        time.sleep(0.02)
        yield {"content": ch}
    yield {"tool_calls": [{"index": 0, "id": "call_mock_" + uuid.uuid4().hex[:6],
                           "function": {"name": "list_dir", "arguments": '{"path":"."}'}}]}


# ------------------------------------------------------------------ agent 循环

def trim(msgs, keep=60):
    if len(msgs) <= keep:
        return
    start = len(msgs) - keep
    while start < len(msgs) and msgs[start].get("role") != "user":
        start += 1
    if start < len(msgs):
        msgs[1:] = msgs[start:]


def make_title(text):
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = t.strip("，。,.!?！？：: ")
    return (t[:24] + "…") if len(t) > 24 else (t or "新对话")


def is_net_err(s):
    """判断异常是不是「网络抽了一下」，只有这种才值得自动重试。"""
    low = (s or "").lower()
    for k in ("urlerror", "errno -3", "errno -2", "eai_again", "econnreset",
              "connection reset", "connection aborted", "remote end closed",
              "temporarily unavailable", "http 429", "http 500", "http 502",
              "http 503", "http 504", "timed out", "timeout"):
        if k in low:
            return True
    return False


def human_err(e):
    """把 Python 异常翻成用户能照做的一句话。返回 (文案, 是否值得重试)。"""
    raw = "%s: %s" % (type(e).__name__, e)
    low = raw.lower()
    host = urlparse(API_URL).netloc or API_URL
    if "errno -3" in low or "eai_again" in low:
        return ("连不上模型接口：域名解析失败（DNS 没响应）。\n"
                "多半是这台机器的网络断了，或者 /etc/resolv.conf 被改坏。\n"
                "先在终端手动跑：ping -c1 223.5.5.5；再跑 getent hosts %s" % host), True
    if "errno -2" in low or "name or service not known" in low:
        return ("连不上模型接口：解析不到域名 %s。\n"
                "检查这台机器能不能上网（ping -c1 223.5.5.5），以及 /etc/resolv.conf 里有没有 nameserver。" % host), True
    if "errno 111" in low or "connection refused" in low:
        return ("连不上模型接口：%s 拒绝连接。\n"
                "检查 DEEPSEEK_URL 是不是写错了，或者本地代理/网关没起来。" % host), False
    if "http 401" in low:
        return ("模型接口返回 401：API key 无效或已过期。\n"
                "在 ~/.config/webchat/env 里换掉 DEEPSEEK_KEY，重启 webchat.py。"), False
    if "http 402" in low or "insufficient balance" in low:
        return "模型接口返回 402：账户余额不足。充值后再试。", False
    if "http 429" in low:
        return "模型接口返回 429：请求太频繁，等十几秒再试。", True
    if any(h in low for h in ("http 500", "http 502", "http 503", "http 504")):
        return "模型服务端出错（5xx），通常几分钟内自己恢复，可以重试。", True
    if "timed out" in low or "timeout" in low:
        return "模型接口 5 分钟没返回，已放弃。可能是网络太慢或服务端卡住。", True
    return raw, False


def stream_retry(msgs, model, stop_ev, tries=3):
    """调模型；网络抖动自动重试。已经吐过字就不重试，免得前端出现重复内容。"""
    last = None
    for i in range(tries):
        got = False
        try:
            for d in (mock_chat(msgs) if MOCK else stream_chat(msgs, model)):
                got = True
                yield d
            return
        except RuntimeError as e:
            last = e
            if got or stop_ev.is_set() or not is_net_err(str(e)):
                raise
            time.sleep(1.2 * (i + 1))
        except Exception as e:
            raise RuntimeError("%s: %s" % (type(e).__name__, e))
    raise last or RuntimeError("接口连续失败")


def run_agent(sid, user_text, bus, stop_ev):
    """跑一轮：把每条消息写库，把每个事件发到 bus。客户端断开也不影响它跑完。"""
    emit = bus.pub
    sess = STORE.get(sid) if STORE else None
    model = (sess or {}).get("model") or MODEL
    msgs = STORE.context(sid) if STORE else [{"role": "system", "content": SYSTEM}]
    emit({"t": "user", "v": user_text})
    emit({"t": "model", "v": model})

    steps = 0
    turns = 0
    t_start = time.time()
    used_in = used_out = 0
    all_text = ""
    finished = False
    think_acc = ""
    compacted = 0

    if STORE:
        STORE.add(sid, "user", content=user_text)
        msgs.append({"role": "user", "content": user_text})
        s = STORE.get(sid)
        if s and (not s["title"] or s["title"] == "新对话"):
            title = make_title(user_text)
            STORE.update(sid, title=title, updated_at=now())
            emit({"t": "title", "v": title})
    else:
        msgs.append({"role": "user", "content": user_text})

    def shrink():
        """超预算就把老消息折成摘要，然后把 msgs 整体换掉。"""
        nonlocal msgs, compacted
        if not STORE or compacted >= 2:
            return
        try:
            r = STORE.compact(sid)
        except Exception:
            return
        if not r:
            return
        compacted += 1
        msgs = STORE.context(sid)
        emit({"t": "compact", "removed": r["removed"], "before": r["before"],
              "after": r["after"], "kept": r["kept"]})

    def gen(m):
        return stream_retry(m, model, stop_ev)

    shrink()

    fail_streak = 0
    halted = False
    for turn in range(MAX_TURNS):
        if stop_ev.is_set():
            break
        turns = turn + 1
        text_acc = ""
        calls = {}
        order = []
        turn_in = turn_out = 0

        for d in gen(msgs):
            if stop_ev.is_set():
                break
            if "__usage__" in d:
                u = d["__usage__"] or {}
                turn_in = u.get("prompt_tokens") or 0
                turn_out = u.get("completion_tokens") or 0
                used_in, used_out = turn_in, turn_out
                emit({"t": "usage", "in": turn_in, "out": turn_out})
                continue
            rc = d.get("reasoning_content")
            if rc:
                think_acc += rc
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

        all_text += text_acc
        if not calls:
            if text_acc:
                if STORE:
                    STORE.add(sid, "assistant", content=text_acc,
                              reasoning=think_acc or None,
                              meta={"steps": 0, "ms": int((time.time() - t_start) * 1000),
                                    "tokens": turn_out or est_tokens(text_acc)})
                msgs.append({"role": "assistant", "content": text_acc})
            finished = True
            break

        tcs = []
        for i in order:
            c = calls[i]
            tcs.append({"id": c["id"] or ("call_%d_%d" % (turn, i)), "type": "function",
                        "function": {"name": c["name"], "arguments": c["args"] or "{}"}})
        msgs.append({"role": "assistant", "content": text_acc or None, "tool_calls": tcs})
        if STORE:
            STORE.add(sid, "assistant", content=text_acc or None,
                      reasoning=think_acc or None, tool_calls=tcs)
        think_acc = ""

        for tc in tcs:
            if stop_ev.is_set():
                break
            fn = tc["function"]
            try:
                args = json.loads(fn["arguments"] or "{}")
            except Exception:
                args = {}
            emit({"t": "tool", "id": tc["id"], "name": fn["name"], "args": args})
            t0 = time.time()
            out = handle(fn["name"], args)
            ms = int((time.time() - t0) * 1000)
            ok = not (out.startswith("ERROR:") or out.startswith("[退出码"))
            steps += 1
            emit({"t": "tool_end", "id": tc["id"], "out": out[:3500], "ms": ms, "ok": ok})
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
            fail_streak = 0 if ok else fail_streak + 1
            if STORE:
                STORE.add(sid, "tool", content=out, tool_call_id=tc["id"],
                          name=fn["name"], meta={"ms": ms, "ok": ok})
                STORE.bump(sid, steps=1)
            if FAIL_STREAK_LIMIT > 0 and fail_streak >= FAIL_STREAK_LIMIT:
                # 一直失败还接着试，只会把步数耗光。停下来，把最后的报错留给用户看。
                emit({"t": "notice",
                      "v": "连续 %d 次工具执行失败，已自动停止。最后一个报错见上。" % fail_streak})
                halted = True
                break

        if halted:
            break

        trim(msgs)
        shrink()

    stopped = stop_ev.is_set() or halted
    if not finished and not stopped:
        tip = ("（已连续执行 %d 步，到单次上限 %d 步就停了。任务没完的话，回一句「继续」接着跑；"
               "想一次跑更长：AGENT_MAX_TURNS=300 python3 webchat.py）" % (steps, MAX_TURNS))
        emit({"t": "delta", "v": "\n\n" + tip})
        if STORE:
            STORE.add(sid, "assistant", content=tip, meta={"steps": 0, "hit_limit": True})
        msgs.append({"role": "assistant", "content": tip})

    if not used_out:
        used_out = est_tokens(all_text)
    total_ms = int((time.time() - t_start) * 1000)
    if STORE:
        STORE.update(sid, updated_at=now())
        if used_in or used_out:
            STORE.bump(sid, tokens_in=used_in, tokens_out=used_out)

    emit({"t": "done", "steps": steps, "turns": turns, "ms": total_ms,
          "hit_limit": (not finished and not stopped), "stopped": stopped,
          "compacted": compacted,
          "tokens": {"in": used_in, "out": used_out}})

    with RUN_LOCK:
        RUNNING.pop(sid, None)


def start_run(sid, text):
    """起一个后台线程跑任务，返回 bus。客户端只负责订阅。"""
    with RUN_LOCK:
        if sid in RUNNING:
            return None
        stop_ev = threading.Event()
        bus = get_bus(sid)
        bus.reset()
        RUNNING[sid] = {"stop": stop_ev, "started": time.time(), "bus": bus}

    def target():
        try:
            run_agent(sid, text, bus, stop_ev)
        except Exception as e:
            msg, retryable = human_err(e)
            with RUN_LOCK:
                RUNNING.pop(sid, None)
            bus.pub({"t": "error", "v": msg, "retryable": retryable})
            bus.pub({"t": "done", "steps": 0, "turns": 0, "ms": 0,
                     "hit_limit": False, "stopped": False,
                     "tokens": {"in": 0, "out": 0}})

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return bus


# ------------------------------------------------------------------ HTTP 服务

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "webchat/2.3"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------- 输出 ----------
    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def js(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False))

    def sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def sse_write(self, ev):
        data = json.dumps(ev, ensure_ascii=False)
        sid = ev.get("seq")
        head = ("id: %d\n" % sid) if sid else ""
        self.wfile.write((head + "data: " + data + "\n\n").encode("utf-8"))
        self.wfile.flush()

    # ---------- 鉴权 ----------
    def is_local(self):
        """本机访问不放口令：Termux 里就是同一个手机开的浏览器，多要一次口令纯属添乱。"""
        ip = (self.client_address or ("",))[0]
        return ip in ("127.0.0.1", "::1", "localhost")

    def authed(self):
        if not TOKEN or self.is_local():
            return True
        c = SimpleCookie(self.headers.get("Cookie") or "")
        if "webchat_k" in c and c["webchat_k"].value == TOKEN:
            return True
        if (self.headers.get("X-Token") or "") == TOKEN:
            return True
        if (parse_qs(urlparse(self.path).query).get("k") or [""])[0] == TOKEN:
            return True
        return False

    def auth_fail(self):
        """不带口令时给一页人话，别只甩 401。"""
        body = ("<!doctype html><meta charset=utf-8><title>需要口令</title>"
                "<div style=\"font:15px/1.8 system-ui;padding:48px 26px;max-width:560px;margin:0 auto\">"
                "<h3>这个地址需要口令</h3>"
                "<p>为了不让同一 WiFi 下的其他人看到你的会话和命令记录，"
                "服务开了访问口令。</p>"
                "<p>用启动时打印的那个完整链接（结尾带 <code>?k=…</code>）打开一次即可，"
                "之后浏览器会记住。</p>"
                "<p style=\"color:#888\">口令存在 <code>~/.config/webchat/token</code>，"
                "也可以在启动终端里执行 <code>cat ~/.config/webchat/token</code> 查看。</p></div>")
        self._send(401, "text/html; charset=utf-8", body)

    def cookie_redirect(self):
        """用 ?k= 打开过就种 cookie，然后跳到不带参数的地址，避免口令留在地址栏/历史里。"""
        if not TOKEN or self.is_local():
            return False
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if (q.get("k") or [""])[0] != TOKEN:
            return False
        q.pop("k", None)
        if (u.path or "").startswith("/api/"):
            return False        # 接口直接放行，不必来回跳
        loc = u.path or "/"
        rest = urlencode({k: v[0] for k, v in q.items() if v})
        if rest:
            loc += "?" + rest
        self.send_response(302)
        self.send_header("Set-Cookie",
                         "webchat_k=%s; Path=/; Max-Age=15552000; HttpOnly; SameSite=Lax" % TOKEN)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    # ---------- 路由 ----------
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)

        if self.cookie_redirect():
            return
        if not self.authed():
            return self.auth_fail()

        if p in ("/", "/index.html"):
            return self.serve_static("app.html")
        if p.startswith("/static/"):
            return self.serve_static(p[len("/static/"):])
        if p == "/favicon.ico":
            return self._send(204, "image/x-icon", b"")

        m = re.match(r"^/api/sessions/([^/]+)/messages$", p)
        if m:
            sid = m.group(1)
            after = int((q.get("after_seq") or ["0"])[0])
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            msgs = STORE.messages(sid, after_seq=after)
            return self.js({"session": STORE.get(sid), "messages": msgs,
                            "running": is_running(sid)})

        m = re.match(r"^/api/sessions/([^/]+)/stats$", p)
        if m:
            sid = m.group(1)
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            st = STORE.stats(sid)
            st["running"] = is_running(sid)
            return self.js(st)

        m = re.match(r"^/api/sessions/([^/]+)/stream$", p)
        if m:
            sid = m.group(1)
            last = int((q.get("last_seq") or ["0"])[0])
            if (q.get("dl") or [""])[0] == "1":
                return self.js({"messages": STORE.messages(sid, after_seq=last)})
            return self.stream(sid, last)

        if p == "/api/sessions":
            qq = (q.get("q") or [""])[0].strip()
            if not STORE:
                return self.js({"sessions": []})
            return self.js({"sessions": STORE.list(qq or None)})

        if p == "/api/health":
            return self.js({"ok": True, "model": MODEL, "models": MODELS, "mock": MOCK,
                            "work": WORK, "db": DB_PATH if USE_DB else None,
                            "db_size": STORE.size() if STORE else 0,
                            "max_turns": MAX_TURNS, "ctx_limit": CTX_LIMIT,
                            "ctx_keep": CTX_KEEP, "auth": bool(TOKEN), "version": "2.3",
                            "platform": os_name(), "android": IS_ANDROID,
                            "cmd_timeout": CMD_TIMEOUT,
                            "tools": [t["function"]["name"] for t in TOOL_SET]})

        if p == "/api/models":
            return self.js({"models": MODELS, "default": MODEL})

        if p == "/api/overview":
            if not STORE:
                return self.js({"sessions": 0, "messages": 0, "empty": 0,
                                "db_size": 0, "old": []})
            d = STORE.overview()
            d["unused_days"] = 30
            return self.js(d)

        return self._send(404, "text/plain; charset=utf-8", "not found")

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        if not self.authed():
            return self.auth_fail()
        body = self.body()

        if p == "/api/sessions":
            title = (body.get("title") or "新对话").strip() or "新对话"
            if not STORE:
                return self.js({"error": "db disabled"}, 400)
            sid = STORE.create(title)
            return self.js({"id": sid, "title": title})

        m = re.match(r"^/api/sessions/([^/]+)/chat$", p)
        if m:
            sid = m.group(1)
            text = (body.get("message") or "").strip()
            if not text:
                return self.js({"error": "empty message"}, 400)
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            mdl = (body.get("model") or "").strip()
            if mdl:
                STORE.update(sid, model=mdl)
            bus = start_run(sid, text)
            if bus is None:
                return self.js({"error": "running", "hint": "这个会话正在运行"}, 409)
            return self.stream(sid, 0)

        m = re.match(r"^/api/sessions/([^/]+)/regenerate$", p)
        if m:
            sid = m.group(1)
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            if is_running(sid):
                return self.js({"error": "running"}, 409)
            last = STORE.last_user(sid)
            if not last:
                return self.js({"error": "没有可以重新生成的消息"}, 400)
            # 砍掉最后一轮（用户消息 + 助手回复 + 工具结果），再用原文重跑
            STORE.truncate(sid, last["seq"])
            STORE.update(sid, steps=0, updated_at=now())
            bus = start_run(sid, last["content"] or "")
            if bus is None:
                return self.js({"error": "running"}, 409)
            return self.stream(sid, 0)

        m = re.match(r"^/api/sessions/([^/]+)/branch$", p)
        if m:
            sid = m.group(1)
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            upto = body.get("seq")
            new_id = STORE.clone(sid, int(upto) if upto else None,
                                 title=(STORE.get(sid) or {}).get("title"))
            if not new_id:
                return self.js({"error": "分支失败"}, 500)
            return self.js({"id": new_id, "session": STORE.get(new_id)})

        m = re.match(r"^/api/sessions/([^/]+)/compact$", p)
        if m:
            sid = m.group(1)
            if not STORE or not STORE.get(sid):
                return self.js({"error": "not found"}, 404)
            keep = body.get("keep")
            r = STORE.compact(sid, keep=keep, force=True)
            if not r:
                return self.js({"ok": False, "hint": "消息太少，暂时不用压缩"}, 200)
            r["ok"] = True
            return self.js(r)

        if p == "/api/cleanup":
            if not STORE:
                return self.js({"error": "db disabled"}, 400)
            days = int(body.get("days") or 30)
            dry = bool(body.get("dry"))
            return self.js(STORE.cleanup(days=days,
                                         drop_empty=body.get("empty", True),
                                         vacuum=not dry,
                                         dry=dry))

        m = re.match(r"^/api/sessions/([^/]+)/stop$", p)
        if m:
            sid = m.group(1)
            with RUN_LOCK:
                r = RUNNING.get(sid)
            if r:
                r["stop"].set()
            return self.js({"ok": bool(r)})

        if p == "/api/reset":
            # 兼容旧前端：清掉最近会话，不删库
            return self.js({"ok": True})

        return self._send(404, "text/plain; charset=utf-8", "not found")

    def do_PATCH(self):
        u = urlparse(self.path)
        if not self.authed():
            return self.auth_fail()
        m = re.match(r"^/api/sessions/([^/]+)$", u.path)
        if not m:
            return self._send(404, "text/plain", "not found")
        sid = m.group(1)
        if not STORE or not STORE.get(sid):
            return self.js({"error": "not found"}, 404)
        b = self.body()
        kw = {}
        if "title" in b:
            t = (b.get("title") or "").strip()[:60]
            if t:
                kw["title"] = t
        if "pinned" in b:
            kw["pinned"] = 1 if b["pinned"] else 0
        if "archived" in b:
            kw["archived"] = 1 if b["archived"] else 0
        if "model" in b:
            mdl = (b.get("model") or "").strip()[:40]
            if mdl:
                kw["model"] = mdl
        kw["updated_at"] = now()
        STORE.update(sid, **kw)
        return self.js({"ok": True, "session": STORE.get(sid)})

    def do_DELETE(self):
        u = urlparse(self.path)
        if not self.authed():
            return self.auth_fail()
        m = re.match(r"^/api/sessions/([^/]+)$", u.path)
        if not m:
            return self._send(404, "text/plain", "not found")
        sid = m.group(1)
        with RUN_LOCK:
            r = RUNNING.get(sid)
        if r:
            r["stop"].set()
        if STORE:
            STORE.delete(sid)
        with BUSES_LOCK:
            BUSES.pop(sid, None)
        return self.js({"ok": True})

    # ---------- 工具方法 ----------
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def serve_static(self, name):
        name = name.split("?")[0]
        if "/" in name or "\\" in name or name.startswith("."):
            return self._send(403, "text/plain", "forbidden")
        fp = os.path.join(STATIC, name)
        if not os.path.exists(fp):
            if name == "app.html":
                return self._send(200, "text/html; charset=utf-8", FALLBACK_HTML)
            return self._send(404, "text/plain", "not found")
        ext = os.path.splitext(name)[1].lower()
        with open(fp, "rb") as f:
            data = f.read()
        self._send(200, MIME.get(ext, "application/octet-stream"), data)

    def stream(self, sid, after_seq):
        bus = get_bus(sid)
        self.sse_start()
        q = bus.subscribe()
        sent = after_seq
        done = False
        try:
            for ev in bus.after(after_seq):
                if ev.get("t") == "__close__":
                    continue
                self.sse_write(ev)
                sent = max(sent, ev.get("seq", 0))
                if ev.get("t") in ("done", "error"):
                    done = True
            while not done:
                try:
                    ev = q.get(timeout=12)
                except queue.Empty:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
                    if not is_running(sid):
                        break
                    continue
                if ev.get("t") == "__close__":
                    break
                if ev.get("seq", 0) <= sent:
                    continue
                self.sse_write(ev)
                sent = max(sent, ev.get("seq", 0))
                if ev.get("t") in ("done", "error"):
                    done = True
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            bus.unsubscribe(q)


FALLBACK_HTML = """<!doctype html><meta charset=utf-8>
<body style="font:15px system-ui;padding:40px;line-height:1.7">
<h2>缺少 static 目录</h2>
<p>webchat.py 需要同目录下的 <code>static/app.html</code>、<code>app.css</code>、<code>app.js</code>。</p>
<p>先更新更新器，再全量拉一次：</p>
<p><code>sh update.sh --self &amp;&amp; sh update.sh</code></p>
<p>或者手动补三个文件（BASE 用镜像前缀）：</p>
<p><code>mkdir -p static &amp;&amp; for f in app.html app.css app.js; do
curl -fL -o static/$f "$BASE/static/$f"; done</code></p>
</body>"""


# ------------------------------------------------------------------ 启动

STORE = None


def local_ip():
    """局域网 IP，用来打印手机能直接打开的地址。取不到就返回空。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        s.close()


def main():
    global MOCK, PORT, WORK, SYSTEM, STORE, USE_DB, TOKEN
    ap = argparse.ArgumentParser(description="agent 图形界面")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default=HOST,
                    help="默认 127.0.0.1；改成 0.0.0.0 会暴露到局域网，并自动启用访问口令")
    ap.add_argument("--mock", action="store_true", help="不需要 API key，演示界面")
    ap.add_argument("--no-db", action="store_true", help="不落盘，单会话内存模式")
    ap.add_argument("--no-auth", action="store_true", help="关掉访问口令（0.0.0.0 时别用）")
    a = ap.parse_args()

    MOCK = a.mock
    PORT = a.port
    WORK = os.path.abspath(os.path.expanduser(WORK))
    os.makedirs(WORK, exist_ok=True)
    SYSTEM = build_system(WORK)
    globals()["SYSTEM"] = SYSTEM

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

    USE_DB = not a.no_db
    if USE_DB:
        try:
            STORE = Store(DB_PATH)
        except Exception as e:
            print("数据库打不开（%s），退回内存模式：%s" % (DB_PATH, e))
            USE_DB = False
            STORE = Store(":memory:")
    else:
        STORE = Store(":memory:")
    if not os.path.isdir(STATIC):
        print("")
        print("  警告：找不到 %s" % STATIC)
        print("  界面会显示提示页。请确保 static/ 和 webchat.py 在同一目录。")
        print("")

    srv = ThreadingHTTPServer((a.host, PORT), Handler)
    srv.daemon_threads = True
    TOKEN = "" if a.no_auth else load_token(a.host)
    url = "http://127.0.0.1:%d" % PORT
    print("")
    print("  agent 界面已启动")
    print("  %s%s" % (url, ("/?k=" + TOKEN) if TOKEN else ""))
    print("  工作目录 %s" % WORK)
    print("  模式 %s" % ("MOCK 演示" if MOCK else MODEL))
    if USE_DB:
        n = len(STORE.list())
        print("  会话库 %s（%d 个会话）" % (DB_PATH, n))
    else:
        print("  会话库 未启用（--no-db）")
    if a.host not in ("127.0.0.1", "localhost"):
        ip = local_ip()
        print("  监听 %s:%d（所有网卡，端口映射能进来了）" % (a.host, PORT))
        if ip:
            print("  局域网设备（手机/平板/另一台电脑）打开：")
            print("     http://%s:%d/%s" % (ip, PORT, ("?k=" + TOKEN) if TOKEN else ""))
    if TOKEN:
        print("  访问口令 %s（本机不用，局域网设备第一次要用上面带 ?k= 的地址）" % TOKEN)
        print("  口令来源 WEBCHAT_TOKEN 或 ~/.config/webchat/token（改完重启生效）")
    else:
        print("  访问口令 未启用（只监听本机，无需口令）")
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
