#!/usr/bin/env sh
# android-agent-kit 一键更新（Termux / Linux 通用，POSIX sh，无第三方依赖）
#
#   sh update.sh                更新全部脚本
#   sh update.sh ocr.py         只更新一个（可写多个）
#   sh update.sh --list         只看本地/远端版本，不下载
#   sh update.sh --self         更新 update.sh 自身
#   BASE=... sh update.sh       换镜像
#
# 设计原则：
#   1. 先下到临时文件，校验通过才替换 —— 下载失败绝不破坏能用的旧文件
#   2. .py 替换前做语法检查，坏了直接拒绝
#   3. 内容没变就不写盘，不产生多余 .bak

SELF_VER=1
KIT_FILES="rev.py webchat.py adui.py ocr.py"
DEFAULT_BASE="https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main"
# BASES 可直接用环境变量指定（多个用换行分隔），指定后不再追加默认镜像
if [ -n "${BASES:-}" ]; then
    :
elif [ -n "${BASE:-}" ]; then
    BASES="$BASE"
else
    BASES="$DEFAULT_BASE
https://gh-proxy.com/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main
https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main"
fi

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    G=$(printf '\033[32m'); Y=$(printf '\033[33m'); R=$(printf '\033[31m')
    D=$(printf '\033[90m'); B=$(printf '\033[1m');  N=$(printf '\033[0m')
else
    G=; Y=; R=; D=; B=; N=
fi

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %-13s %s\n' "$G" "$N" "$1" "$2"; }
skip() { printf '  %s=%s %-13s %s\n' "$D" "$N" "$1" "$2"; }
upd()  { printf '  %s↑%s %-13s %s\n' "$Y" "$N" "$1" "$2"; }
bad()  { printf '  %s✗%s %-13s %s\n' "$R" "$N" "$1" "$2"; }

fsize() { wc -c < "$1" 2>/dev/null | tr -d ' \t'; }

same() {
    python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys
a = open(sys.argv[1], 'rb').read()
b = open(sys.argv[2], 'rb').read()
sys.exit(0 if a == b else 1)
PY
}

pysyntax() {
    python3 - "$1" <<'PY'
import sys
p = sys.argv[1]
try:
    compile(open(p, 'rb').read(), p, 'exec')
except SyntaxError as e:
    sys.stderr.write("第 %s 行：%s\n" % (e.lineno, e.msg))
    sys.exit(1)
PY
}

# 依次尝试镜像，成功返回 0
fetch() {  # $1=文件名  $2=落地路径
    _name="$1"; _dst="$2"
    for _b in $BASES; do
        [ -z "$_b" ] && continue
        rm -f "$_dst"
        if [ "$HAVE_CURL" = 1 ]; then
            curl -fsSL --retry 2 --connect-timeout 10 -m 180 -o "$_dst" "$_b/$_name" 2>/dev/null
        else
            wget -q -O "$_dst" --timeout=20 --tries=2 "$_b/$_name" 2>/dev/null
        fi
        if [ -s "$_dst" ]; then
            MIRROR=$(printf '%s' "$_b" | sed 's#https\?://##; s#/.*##')
            return 0
        fi    done
    rm -f "$_dst"
    return 1
}

remote_size() {  # $1=文件名
    for _b in $BASES; do
        [ -z "$_b" ] && continue
        if [ "$HAVE_CURL" = 1 ]; then
            _s=$(curl -fsSI -m 20 "$_b/$1" 2>/dev/null |
                 tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' | tail -1)
        else
            _s=$(wget -q --spider --server-response -T 20 "$_b/$1" 2>&1 |
                 tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' | tail -1)
        fi
        [ -n "$_s" ] && { printf '%s' "$_s"; return 0; }
    done
    return 1
}

# ------------------------------------------------------------------ 参数

SELF_UPDATE=0
LIST_ONLY=0
TARGETS=""
for a in "$@"; do
    case "$a" in
        --self)  SELF_UPDATE=1 ;;
        --list)  LIST_ONLY=1 ;;
        -h|--help) usage; exit 0 ;;
        -*)      say "未知参数：$a"; usage; exit 2 ;;
        *)       TARGETS="$TARGETS $a" ;;
    esac
done
[ -z "$TARGETS" ] && TARGETS="$KIT_FILES"

if command -v curl >/dev/null 2>&1; then HAVE_CURL=1; else HAVE_CURL=0; fi
if [ "$HAVE_CURL" = 0 ] && ! command -v wget >/dev/null 2>&1; then
    say "${R}curl 和 wget 都没有${N}，先装一个：pkg install curl"
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    say "${R}缺 python3${N}，先装：pkg install python"
    exit 1
fi

# ------------------------------------------------------------------ 只看版本

if [ "$LIST_ONLY" = 1 ]; then
    say "${B}本地 / 远端${N}   $(pwd)"
    printf '  %-13s %10s %10s  %s\n' 文件 本地 远端 状态
    for f in $TARGETS; do
        l="-"
        [ -f "$f" ] && l=$(fsize "$f")
        r=$(remote_size "$f") || r="?"
        if [ "$l" = "-" ]; then
            st="${R}未安装${N}"
        elif [ "$r" = "?" ]; then
            st="${D}远端查不到${N}"
        elif [ "$l" = "$r" ]; then
            st="${G}一致${N}"
        else
            st="${Y}需更新${N}"
        fi
        printf '  %-13s %10s %10s  %b\n' "$f" "$l" "$r" "$st"
    done
    exit 0
fi

# ------------------------------------------------------------------ 更新自身

if [ "$SELF_UPDATE" = 1 ]; then
    SELF_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || SELF_DIR="."
    TMP=$(mktemp -d "${TMPDIR:-/tmp}/kit.XXXXXX") || exit 1
    say "${B}更新 update.sh${N}"
    if fetch "update.sh" "$TMP/update.sh"; then
        if same "$TMP/update.sh" "$SELF_DIR/$(basename "$0")"; then
            skip "update.sh" "已是最新"
        else
            cp "$TMP/update.sh" "$SELF_DIR/$(basename "$0")"
            chmod +x "$SELF_DIR/$(basename "$0")"
            upd "update.sh" "$(fsize "$SELF_DIR/$(basename "$0")") 字节"
        fi
    else
        bad "update.sh" "下载失败，旧的还能用"
    fi
    rm -rf "$TMP"
    exit 0
fi

# ------------------------------------------------------------------ 主流程

TMP=$(mktemp -d "${TMPDIR:-/tmp}/kit.XXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM

FIRST=$(printf '%s\n' "$BASES" | head -1)
FIRST_HOST=$(printf '%s' "$FIRST" | sed 's#https\?://##; s#/.*##')
say "${B}android-agent-kit 更新${N}"
say "${D}目录  $(pwd)"
say "镜像  $FIRST_HOST（失败自动换下一个）${N}"
say ""

CHANGED=""
FAILED_DL=""
FAILED_CHK=""

for f in $TARGETS; do
    got=0
    if fetch "$f" "$TMP/$f"; then
        got=1
    fi
    if [ "$got" = 0 ]; then
        bad "$f" "下载失败，旧文件保留"
        FAILED_DL="$FAILED_DL $f"
        continue
    fi

    # 内容一致就不写盘
    if [ -f "$f" ] && same "$TMP/$f" "$f"; then
        skip "$f" "$(fsize "$f") 已是最新"
        continue
    fi

    # .py 先过语法检查
    case "$f" in
        *.py)
            if ! err=$(pysyntax "$TMP/$f" 2>&1); then
                bad "$f" "语法错误，拒绝写入：$err"
                FAILED_CHK="$FAILED_CHK $f"
                continue
            fi
            ;;
    esac

    if [ -f "$f" ]; then
        old=$(fsize "$f")
        cp "$f" "$f.bak" 2>/dev/null
        mv "$TMP/$f" "$f" || { bad "$f" "写入失败"; FAILED_CHK="$FAILED_CHK $f"; continue; }
        upd "$f" "$old → $(fsize "$f")  (旧的存为 $f.bak)"
    else
        mv "$TMP/$f" "$f" || { bad "$f" "写入失败"; FAILED_CHK="$FAILED_CHK $f"; continue; }
        ok "$f" "新增 $(fsize "$f")"
    fi
    chmod 644 "$f" 2>/dev/null
    CHANGED="$CHANGED $f"
done

say ""
if [ -n "$CHANGED" ]; then
    say "${G}已更新${N}：$CHANGED"
    case " $CHANGED " in
        *" ocr.py "*|*" adui.py "*)
            say "建议复查：${B}python3 ocr.py doctor${N}   ${B}python3 adui.py doctor${N}" ;;
    esac
elif [ -z "$FAILED_DL$FAILED_CHK" ]; then
    say "${G}全部已是最新${N}，没有写盘"
fi
if [ -n "$FAILED_DL" ]; then
    say "${R}下载失败${N}：$FAILED_DL"
    say "  换镜像重试：${B}BASE=https://gh-proxy.com/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main sh $0${N}"
fi
if [ -n "$FAILED_CHK" ]; then
    say "${R}校验不通过${N}：$FAILED_CHK"
    say "  这几个文件没写入，本机原文件没动。稍后再跑一次，或 ${B}sh $0 --list${N} 看远端大小是否正常。"
fi
[ -n "$FAILED_DL$FAILED_CHK" ] && exit 1
exit 0
exit 0
