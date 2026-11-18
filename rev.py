#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rev.py - 单文件逆向侦察工具（纯标准库，Termux / Alpine / Linux / Windows 通用）

不依赖 readelf / objdump / binutils，也不需要 root。
手机 Termux 上直接 python3 rev.py ... 就能跑。

用法:
  python3 rev.py triage  <file>                      一屏摘要：类型/大小/哈希/熵/内部结构
  python3 rev.py strings <file> [--min 6] [--grep RE] [--limit 200] [--utf16]
                                    默认同时扫 ASCII 与 UTF-16LE；--utf16 只扫 UTF-16LE
  python3 rev.py hexdump <file> [--off 0] [--len 256]
  python3 rev.py elf     <file>                      ELF 头 + 节表 + 依赖库 + 符号采样
  python3 rev.py pe      <file>                      PE 头 + 节表 + 导入 DLL
  python3 rev.py dex     <file>                      DEX 头统计 + 类名采样
  python3 rev.py apk     <file>                      APK 结构 + 包名/权限 + so 清单
  python3 rev.py zip     <file>                      任意 zip/jar/apk 条目列表
  python3 rev.py carve   <file> [--limit 20]         从镜像里切出内嵌 ZIP/ELF/DEX/PE
  python3 rev.py r2      <file> <r2 命令...>         透传给 radare2（若已安装）

退出码: 0 正常 / 2 参数或文件错误
"""

import sys
import os
import re
import math
import struct
import hashlib
import zipfile
import argparse
import shutil
import subprocess

MAXLINES_DEFAULT = 60


# ---------------------------------------------------------------- 基础工具

def read_file(path):
    with open(path, "rb") as f:
        return f.read()


def entropy(b):
    if not b:
        return 0.0
    cnt = [0] * 256
    for x in b:
        cnt[x] += 1
    n = float(len(b))
    e = 0.0
    for c in cnt:
        if c:
            p = c / n
            e -= p * math.log2(p)
    return e


def fmt_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%.0f %s" % (n, u)) if u == "B" else ("%.2f %s" % (n, u))
        n /= 1024.0
    return str(n)


def clip(lines, limit):
    if limit and len(lines) > limit:
        return lines[:limit] + ["... (%d 行省略，用 --limit 调大)" % (len(lines) - limit)]
    return lines


MAGICS = [
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE/DOS"),
    (b"PK\x03\x04", "ZIP"),
    (b"PK\x05\x06", "ZIP(empty)"),
    (b"dex\n", "DEX"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "RAR"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"%PDF", "PDF"),
    (b"SQLite format 3\x00", "SQLite"),
    (b"\xca\xfe\xba\xbe", "JavaClass/MachO-fat"),
    (b"\xcf\xfa\xed\xfe", "MachO64"),
    (b"!<arch>\n", "ar"),
    (b"OggS", "Ogg"),
    (b"RIFF", "RIFF(avi/wav/webp)"),
    (b"\x00asm", "WebAssembly"),
]


def sniff(data):
    for m, name in MAGICS:
        if data.startswith(m):
            return name
    if data[:4] == b"\x03\x00\x08\x00":
        return "Android binary XML"
    return "unknown"


# ---------------------------------------------------------------- strings

def extract_strings(data, minlen=6, utf16_only=False, grep=None, limit=200):
    out = []
    pat = re.compile(rb"[\x20-\x7e]{%d,}" % minlen)
    seen = set()
    if not utf16_only:
        for m in pat.finditer(data):
            s = m.group().decode("ascii", "replace")
            if grep and not re.search(grep, s, re.I):
                continue
            if s not in seen:
                seen.add(s)
                out.append("0x%08x  %s" % (m.start(), s))
            if len(out) >= limit * 4:
                break
    upat = re.compile((r"(?:[\x20-\x7e]\x00){%d,}" % minlen).encode())
    for m in upat.finditer(data):
        try:
            s = m.group().decode("utf-16-le", "replace")
        except Exception:
            continue
        if grep and not re.search(grep, s, re.I):
            continue
        if s not in seen:
            seen.add(s)
            out.append("0x%08x  %s" % (m.start(), s))
        if len(out) >= limit * 4:
            break
    return clip(out, limit)


# ---------------------------------------------------------------- hexdump

def hexdump(data, off=0, length=256):
    chunk = data[off:off + length]
    lines = []
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hexs = " ".join("%02x" % b for b in row)
        hexs = hexs[:23] + " " + hexs[23:] if len(hexs) > 23 else hexs
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append("%08x  %-48s  |%s|" % (off + i, hexs, asc))
    return lines


# ---------------------------------------------------------------- ELF

EM = {3: "x86", 8: "MIPS", 20: "PowerPC", 40: "ARM", 62: "x86-64",
      183: "AArch64", 243: "RISC-V", 258: "LoongArch"}
ET = {0: "NONE", 1: "REL", 2: "EXEC", 3: "DYN(PIE/.so)", 4: "CORE"}
SHT = {1: "PROGBITS", 2: "SYMTAB", 3: "STRTAB", 4: "RELA", 5: "HASH",
       6: "DYNAMIC", 8: "NOBITS", 9: "REL", 11: "DYNSYM", 14: "INIT_ARRAY"}


def parse_elf(data):
    if len(data) < 52:
        raise ValueError("文件太小，不是完整 ELF")
    cls = data[4]
    order = "<" if data[5] == 1 else ">"
    is64 = cls == 2
    out = []
    if is64:
        (e_type, e_machine, _v, e_entry, e_phoff, e_shoff, _fl, _eh,
         e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
            order + "HHIQQQIHHHHHH", data, 16)
    else:
        (e_type, e_machine, _v, e_entry, e_phoff, e_shoff, _fl, _eh,
         e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
            order + "HHIIIIIHHHHHH", data, 16)

    out.append("ELF%d  %s  %s  entry=0x%x" % (
        64 if is64 else 32, "LE" if order == "<" else "BE",
        EM.get(e_machine, "machine=%d" % e_machine), e_entry))
    out.append("type=%s  sections=%d  program headers=%d" % (
        ET.get(e_type, str(e_type)), e_shnum, e_phnum))

    # 节表 + 节名
    secs = []
    shstr = b""
    if e_shoff and e_shnum and e_shentsize:
        try:
            if is64:
                shfmt = order + "IIQQQQIIQQ"
            else:
                shfmt = order + "IIIIIIIIII"
            for i in range(e_shnum):
                off = e_shoff + i * e_shentsize
                if off + struct.calcsize(shfmt) > len(data):
                    break
                v = struct.unpack_from(shfmt, data, off)
                secs.append({"name_off": v[0], "type": v[1], "addr": v[3],
                             "offset": v[4], "size": v[5]})
            if e_shstrndx < len(secs):
                st = secs[e_shstrndx]
                shstr = data[st["offset"]:st["offset"] + st["size"]]
        except Exception:
            pass

    def secname(s):
        if not shstr or s["name_off"] >= len(shstr):
            return ""
        end = shstr.find(b"\x00", s["name_off"])
        if end < 0:
            end = len(shstr)
        if end <= s["name_off"]:
            return ""
        return shstr[s["name_off"]:end].decode("utf-8", "replace")

    # .dynamic 里的 NEEDED（放在节表之前，方便手机上一屏看到）
    for s in secs:
        if SHT.get(s["type"]) == "DYNAMIC":
            try:
                step = 16 if is64 else 8
                dfmt = order + ("qQ" if is64 else "iI")
                needed = []
                strtab_addr = None
                entries = []
                for i in range(min(s["size"] // step, 200)):
                    tag, val = struct.unpack_from(dfmt, data, s["offset"] + i * step)
                    if tag == 0:
                        break
                    entries.append((tag, val))
                    if tag == 5 and strtab_addr is None:
                        strtab_addr = val
                if strtab_addr is not None:
                    # DT_STRTAB 是虚拟地址，映射回文件偏移
                    for sec in secs:
                        if sec["addr"] and sec["addr"] <= strtab_addr < sec["addr"] + max(sec["size"], 1):
                            base = sec["offset"] + (strtab_addr - sec["addr"])
                            for tag, val in entries:
                                if tag == 1:
                                    e = data.find(b"\x00", base + val)
                                    needed.append(data[base + val:e].decode("utf-8", "replace"))
                            break
                if needed:
                    out.append("")
                    out.append("NEEDED: " + ", ".join(needed))
            except Exception:
                pass
            break

    if secs:
        out.append("")
        out.append("%-18s %-11s %10s %9s" % ("section", "type", "addr", "size"))
        shown = 0
        for s in secs[1:]:
            nm = secname(s)
            if not nm:
                continue
            if shown >= 25:
                out.append("... (共 %d 个非空节)" % (len(secs) - 1))
                break
            out.append("%-18s %-11s 0x%08x %9s" % (
                nm[:18], SHT.get(s["type"], str(s["type"]))[:11],
                s["addr"], fmt_size(s["size"])))
            shown += 1
    return out


# ---------------------------------------------------------------- PE

PE_MACH = {0x14c: "x86", 0x8664: "x86-64", 0x1c0: "ARM", 0xaa64: "ARM64"}
PE_SUB = {1: "NATIVE", 2: "GUI", 3: "CUI", 9: "WINDOWS_CE", 10: "EFI_APP"}


def parse_pe(data):
    if data[:2] != b"MZ":
        raise ValueError("不是 MZ 文件")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError("找不到 PE 签名")
    p = e_lfanew + 4
    machine, nsec, _ts, _pst, _nsym, optsize, chars = struct.unpack_from("<HHIIIHH", data, p)
    opt = p + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    is64 = magic == 0x20b
    subsystem = struct.unpack_from("<H", data, opt + 68)[0]
    entry = struct.unpack_from("<I", data, opt + 16)[0]
    image_base = struct.unpack_from("<Q" if is64 else "<I", data, opt + 24 if is64 else opt + 28)[0]

    out = ["PE32%s  %s  subsystem=%s  entry=0x%x  imagebase=0x%x" % (
        "+" if is64 else "", PE_MACH.get(machine, hex(machine)),
        PE_SUB.get(subsystem, str(subsystem)), entry, image_base)]
    out.append("sections=%d  characteristics=0x%04x%s" % (
        nsec, chars, "  DLL" if chars & 0x2000 else ""))

    secs = []
    st = opt + optsize
    out.append("")
    out.append("%-10s %10s %10s %10s" % ("section", "vaddr", "rawptr", "rawsize"))
    for i in range(min(nsec, 30)):
        off = st + i * 40
        name = data[off:off + 8].rstrip(b"\x00").decode("latin-1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
        secs.append({"vaddr": vaddr, "vsize": vsize, "rawptr": rawptr, "rawsize": rawsize})
        out.append("%-10s 0x%08x 0x%08x %10s" % (name, vaddr, rawptr, fmt_size(rawsize)))

    def rva2off(rva):
        for s in secs:
            if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rawsize"]):
                return s["rawptr"] + (rva - s["vaddr"])
        return None

    # 导入表
    try:
        ddir = opt + (112 if is64 else 96)
        imp_rva, imp_size = struct.unpack_from("<II", data, ddir + 8)
        dlls = []
        if imp_rva:
            o = rva2off(imp_rva)
            while o and o + 20 <= len(data):
                name_rva = struct.unpack_from("<I", data, o + 12)[0]
                if name_rva == 0:
                    break
                no = rva2off(name_rva)
                if no is None:
                    break
                end = data.find(b"\x00", no)
                dlls.append(data[no:end].decode("latin-1", "replace"))
                o += 20
                if len(dlls) > 40:
                    break
        if dlls:
            out.append("")
            out.append("IMPORTS: " + ", ".join(dlls))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- DEX

def uleb128(data, off):
    result = 0
    shift = 0
    while off < len(data):
        b = data[off]
        off += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
        if shift > 35:
            break
    return result, off


def dex_strings(data, maxn=4000):
    """返回 DEX 字符串表（前 maxn 个）"""
    try:
        size, off = struct.unpack_from("<II", data, 56)
    except Exception:
        return []
    out = []
    for i in range(min(size, maxn)):
        try:
            sid_off = struct.unpack_from("<I", data, off + i * 4)[0]
            _ln, p = uleb128(data, sid_off)
            end = data.find(b"\x00", p)
            if end < 0:
                continue
            out.append(data[p:end].decode("utf-8", "replace"))
        except Exception:
            break
    return out


def parse_dex(data):
    if not data.startswith(b"dex\n"):
        raise ValueError("不是 DEX")
    ver = data[4:7].decode("ascii", "replace")
    file_size = struct.unpack_from("<I", data, 32)[0]
    str_n, str_off = struct.unpack_from("<II", data, 56)
    type_n, type_off = struct.unpack_from("<II", data, 64)
    proto_n, _ = struct.unpack_from("<II", data, 72)
    field_n, _ = struct.unpack_from("<II", data, 80)
    meth_n, _ = struct.unpack_from("<II", data, 88)
    cls_n, cls_off = struct.unpack_from("<II", data, 96)

    out = ["DEX %s  size=%s  checksum=0x%08x" % (ver, fmt_size(file_size),
                                                 struct.unpack_from("<I", data, 8)[0])]
    out.append("strings=%d  types=%d  protos=%d  fields=%d  methods=%d  classes=%d" % (
        str_n, type_n, proto_n, field_n, meth_n, cls_n))
    out.append("sha1(signature)=%s" % data[12:32].hex())

    strs = dex_strings(data)
    classes = [s for s in strs if s.startswith("L") and s.endswith(";")]
    out.append("")
    out.append("classes (first 25 of %d):" % len(classes))
    for c in classes[:25]:
        out.append("  " + c[1:-1].replace("/", "."))
    interesting = [s for s in strs if any(k in s.lower() for k in
                   ("http://", "https://", "password", "token", "secret", "api_key",
                    "root", "frida", "xposed", "emulator", "debug"))]
    if interesting:
        out.append("")
        out.append("interesting strings (first 25):")
        for s in interesting[:25]:
            out.append("  " + s[:120])
    return out


# ---------------------------------------------------------------- AXML / APK

def _read_pool(data, p, hsize):
    """解析 RES_STRING_POOL_TYPE"""
    out = []
    try:
        scount, _st, flags, sstart, _ss = struct.unpack_from("<IIIII", data, p + 8)
        utf8 = bool(flags & 0x100)
        idx = p + hsize
        base = p + sstart
        for i in range(min(scount, 8000)):
            q = base + struct.unpack_from("<I", data, idx + i * 4)[0]
            if utf8:
                n1 = data[q]
                q += 2 if n1 & 0x80 else 1
                n2 = data[q]
                if n2 & 0x80:
                    n2 = ((n2 & 0x7F) << 8) | data[q + 1]
                    q += 2
                else:
                    q += 1
                out.append(data[q:q + n2].decode("utf-8", "replace"))
            else:
                ln = struct.unpack_from("<H", data, q)[0]
                q += 2
                if ln & 0x8000:
                    ln = ((ln & 0x7FFF) << 16) | struct.unpack_from("<H", data, q)[0]
                    q += 2
                out.append(data[q:q + ln * 2].decode("utf-16-le", "replace"))
    except Exception:
        pass
    return out


def parse_axml(data):
    """解析 Android 二进制 XML，返回 {'strings': [...], 'elements': [(tag, {attr: val})]}"""
    res = {"strings": [], "elements": []}
    if len(data) < 16 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        return res
    p = 8
    while p + 8 <= len(data):
        ctype, hsize, csize = struct.unpack_from("<HHI", data, p)
        if ctype == 0x0001:
            res["strings"] = _read_pool(data, p, hsize)
            break
        if csize <= 0 or p + csize > len(data):
            break
        p += csize

    ss = res["strings"]
    p = 8
    while p + 8 <= len(data):
        ctype, _hsize, csize = struct.unpack_from("<HHI", data, p)
        if csize <= 0 or p + csize > len(data):
            break
        if ctype == 0x0102:  # START_ELEMENT
            base = p + 16  # ResXMLTree_attrExt
            try:
                _ns, name_i = struct.unpack_from("<II", data, base)
                a_start, a_size, a_count = struct.unpack_from("<HHH", data, base + 8)
                tag = ss[name_i] if name_i < len(ss) else "?"
                attrs = {}
                abase = base + (a_start or 20)
                for i in range(a_count):
                    ao = abase + i * (a_size or 20)
                    _ansi, aname_i, raw_i, _vs, _r0, dtype, dval = struct.unpack_from(
                        "<IIIHBBI", data, ao)
                    aname = ss[aname_i] if aname_i < len(ss) else "?"
                    if raw_i != 0xFFFFFFFF and raw_i < len(ss):
                        val = ss[raw_i]
                    elif dtype == 0x03 and dval < len(ss):
                        val = ss[dval]
                    elif dtype == 0x12:
                        val = "true" if dval else "false"
                    elif dtype == 0x10:
                        val = str(dval)
                    elif dtype == 0x11:
                        val = "0x%x" % dval
                    else:
                        val = ""
                    attrs[aname] = val
                res["elements"].append((tag, attrs))
            except Exception:
                pass
        p += csize
    return res


def parse_apk(path, data):
    out = []
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        raise ValueError("不是合法 zip: %s" % e)
    names = z.namelist()
    dex = [n for n in names if re.match(r"classes\d*\.dex$", n)]
    sos = [n for n in names if n.startswith("lib/") and n.endswith(".so")]
    assets = [n for n in names if n.startswith("assets/")]
    res = [n for n in names if n.startswith("res/")]
    out.append("APK entries=%d  size=%s" % (len(names), fmt_size(len(data))))
    out.append("dex=%d  so=%d  assets=%d  res=%d" % (len(dex), len(sos), len(assets), len(res)))

    # 签名
    sig = [n for n in names if n.startswith("META-INF/") and
           (n.endswith(".RSA") or n.endswith(".DSA") or n.endswith(".EC"))]
    v2 = b"APK Sig Block 42" in data
    out.append("signature: v1=%s v2/v3=%s" % ("yes" if sig else "no", "yes" if v2 else "no"))

    if sos:
        out.append("")
        out.append("native libs:")
        for s in sos[:20]:
            out.append("  " + s)

    if dex:
        out.append("")
        try:
            d = z.read(dex[0])
            di = parse_dex(d)
            out.extend(["  " + x for x in di[:4]])
            strs = dex_strings(d, 20000)
            classes = [x for x in strs if x.startswith("L") and x.endswith(";")]
            pkgs = {}
            skip = ("android/", "java/", "javax/", "dalvik/", "kotlin/", "kotlinx/",
                    "org/intellij/", "org/jetbrains/", "androidx/", "com/google/android/")
            for c in classes:
                body = c[1:-1]
                if "[" in body or ";" in body or "(" in body:
                    continue
                parts = body.split("/")
                if len(parts) < 2:
                    continue
                k = "/".join(parts[:-1])   # 去掉类名，聚合到包
                if k.startswith(skip) or not re.match(r"^[A-Za-z_$][\w$]*(/[\w$]+)*$", k):
                    continue
                pkgs[k] = pkgs.get(k, 0) + 1
            top = sorted(pkgs.items(), key=lambda kv: -kv[1])[:10]
            if top:
                out.append("  top packages: " + ", ".join("%s(%d)" % (k, v) for k, v in top))
            urls = sorted(set(x for x in strs if re.match(r"^https?://.+", x)))
            if urls:
                out.append("  urls (%d):" % len(urls))
                for u in urls[:8]:
                    out.append("    " + u[:100])
        except Exception as e:
            out.append("  dex parse failed: %s" % e)

    # manifest
    if "AndroidManifest.xml" in names:
        out.append("")
        try:
            info = manifest_info(z)
            out.append("manifest: package=%s" % info["package"])
            if info["versions"]:
                out.append("versions: " + "  ".join(info["versions"]))
            if info["flags"]:
                out.append("flags   : " + ", ".join(info["flags"]))
            if info["permissions"]:
                out.append("permissions (%d):" % len(info["permissions"]))
                for p in info["permissions"][:18]:
                    out.append("  " + p)
            if info["components"]:
                out.append("components (%d):" % len(info["components"]))
                for c in info["components"][:15]:
                    out.append("  " + c[:110])
        except Exception as e:
            out.append("  manifest parse failed: %s" % e)
    return out


def manifest_info(z):
    """从 APK 的二进制 AndroidManifest.xml 提取结构化信息"""
    ax = parse_axml(z.read("AndroidManifest.xml"))
    els = ax["elements"]
    info = {"package": "?", "versions": [], "permissions": [], "components": [], "flags": []}
    for tag, a in els:
        if tag == "manifest":
            if a.get("package"):
                info["package"] = a["package"]
            for k in ("versionName", "versionCode"):
                if a.get(k):
                    info["versions"].append("%s=%s" % (k, a[k]))
        elif tag == "uses-sdk":
            for k in ("minSdkVersion", "targetSdkVersion"):
                if a.get(k):
                    info["versions"].append("%s=%s" % (k, a[k]))
        elif tag == "uses-permission":
            n = a.get("name")
            if n and n not in info["permissions"]:
                info["permissions"].append(n)
        elif tag in ("activity", "service", "receiver", "provider"):
            n = a.get("name") or "?"
            if n.startswith("."):
                n = info["package"] + n
            elif "." not in n:
                n = info["package"] + "." + n
            ex = a.get("exported")
            info["components"].append("%-8s %s%s" % (tag, n, "  exported=" + ex if ex else ""))
        elif tag == "application":
            if a.get("debuggable") == "true":
                info["flags"].append("debuggable=true")
            if a.get("allowBackup") == "true":
                info["flags"].append("allowBackup=true")
            if a.get("usesCleartextTraffic") == "true":
                info["flags"].append("cleartextTraffic=true")
    return info


# ---------------------------------------------------------------- zip

def parse_zip(path):
    z = zipfile.ZipFile(path)
    out = ["entries=%d" % len(z.namelist())]
    rows = []
    for i in z.infolist():
        rows.append("%10s  %s" % (fmt_size(i.file_size), i.filename))
    return out + rows


# ---------------------------------------------------------------- carve

CARVE = [(b"PK\x03\x04", "ZIP"), (b"\x7fELF", "ELF"), (b"dex\n035", "DEX"),
         (b"MZ", "PE"), (b"\x1f\x8b\x08", "gzip")]


def carve(data, limit=20):
    hits = []
    for magic, name in CARVE:
        start = 0
        while len(hits) < limit * 5:
            i = data.find(magic, start)
            if i < 0:
                break
            hits.append((i, name))
            start = i + 1
    hits.sort()
    return ["0x%08x  %s" % (o, n) for o, n in hits[:limit]]


# ---------------------------------------------------------------- triage

def triage(path):
    data = read_file(path)
    out = []
    out.append("file     : %s" % os.path.basename(path))
    out.append("size     : %s (%d bytes)" % (fmt_size(len(data)), len(data)))
    out.append("sha256   : %s" % hashlib.sha256(data).hexdigest())
    out.append("md5      : %s" % hashlib.md5(data).hexdigest())
    t = sniff(data)
    ent = entropy(data[:2 * 1024 * 1024])
    hint = ""
    if ent > 7.2 and t not in ("ZIP", "ZIP(empty)"):
        hint = "   <-- 高熵：可能加壳/加密/压缩"
    out.append("entropy  : %.2f / 8.00%s" % (ent, hint))
    out.append("type     : %s" % t)

    if t == "ZIP" or path.lower().endswith((".apk", ".jar", ".zip", ".xapk")):
        try:
            z = zipfile.ZipFile(path)
            names = z.namelist()
            out.append("zip      : %d entries" % len(names))
            if "AndroidManifest.xml" in names:
                try:
                    mi = manifest_info(z)
                    out.append("apk      : pkg=%s  dex=%d  perm=%d" % (
                        mi["package"], len([n for n in names if re.match(r"classes\d*\.dex$", n)]),
                        len(mi["permissions"])))
                except Exception:
                    out.append("apk      : yes")
        except Exception:
            pass
    elif t == "ELF":
        try:
            h = parse_elf(data)[0]
            out.append("elf      : " + h)
        except Exception:
            pass
    elif t == "PE/DOS":
        try:
            out.append("pe       : " + parse_pe(data)[0])
        except Exception:
            pass
    elif t == "DEX":
        try:
            out.append("dex      : " + parse_dex(data)[0])
        except Exception:
            pass

    # 结尾特征
    tail = data[-64:]
    out.append("tail     : " + "".join(chr(b) if 32 <= b < 127 else "." for b in tail))
    return out


# ---------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(prog="rev.py", add_help=True,
                                 description="单文件逆向侦察工具")
    ap.add_argument("action", choices=["triage", "strings", "hexdump", "elf", "pe",
                                       "dex", "apk", "zip", "carve", "r2"])
    ap.add_argument("target", help="目标文件；r2 模式下是附加的 r2 命令")
    ap.add_argument("rest", nargs="*", help="r2 命令的剩余参数")
    ap.add_argument("--min", type=int, default=6)
    ap.add_argument("--grep", default=None)
    ap.add_argument("--limit", type=int, default=MAXLINES_DEFAULT)
    ap.add_argument("--utf16", action="store_true")
    ap.add_argument("--off", type=lambda x: int(x, 0), default=0)
    ap.add_argument("--len", type=lambda x: int(x, 0), default=256)
    a = ap.parse_args(argv)

    if a.action == "r2":
        r2 = shutil.which("radare2") or shutil.which("r2")
        if not r2:
            print("ERROR: 未安装 radare2。Termux: pkg install radare2")
            return 2
        binary = a.target
        cmds = " ; ".join(a.rest) if a.rest else "ij"
        p = subprocess.run([r2, "-q", "-e", "scr.color=0", "-c", cmds, binary],
                           capture_output=True, text=True, timeout=120)
        print((p.stdout or "")[-6000:] or (p.stderr or "(no output)"))
        return 0

    if not os.path.exists(a.target):
        print("ERROR: 文件不存在: %s" % a.target)
        return 2
    if os.path.isdir(a.target):
        print("ERROR: 这是目录，需要一个文件")
        return 2

    try:
        if a.action == "triage":
            lines = triage(a.target)
        elif a.action == "strings":
            data = read_file(a.target)
            lines = extract_strings(data, a.min, a.utf16, a.grep, a.limit)
            if not lines:
                lines = ["(没有匹配的字符串，试试 --min 4 或 --utf16)"]
        elif a.action == "hexdump":
            lines = hexdump(read_file(a.target), a.off, a.len)
        elif a.action == "elf":
            lines = clip(parse_elf(read_file(a.target)), a.limit)
        elif a.action == "pe":
            lines = clip(parse_pe(read_file(a.target)), a.limit)
        elif a.action == "dex":
            lines = clip(parse_dex(read_file(a.target)), a.limit)
        elif a.action == "apk":
            lines = clip(parse_apk(a.target, read_file(a.target)), a.limit)
        elif a.action == "zip":
            lines = clip(parse_zip(a.target), a.limit)
        elif a.action == "carve":
            lines = carve(read_file(a.target), a.limit)
        else:
            lines = ["unknown"]
    except Exception as e:
        print("ERROR: %s: %s" % (type(e).__name__, e))
        return 2

    print("\n".join(str(x) for x in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
