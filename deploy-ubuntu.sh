#!/usr/bin/env sh
# deploy-ubuntu.sh —— 在 Ubuntu / Debian 上部署 agent webchat（含 systemd 常驻）
#
#   sudo sh deploy-ubuntu.sh                     默认装到 /opt/agent-kit，端口 8765
#   sudo APP_DIR=/srv/agent PORT=9000 sh deploy-ubuntu.sh
#   sudo DEEPSEEK_KEY=sk-xxx sh deploy-ubuntu.sh  顺手把 key 写进配置
#
# 重复执行是安全的：已存在的用户、目录、配置不会被动，代码走 update.sh 增量更新。

set -u

APP_DIR=${APP_DIR:-/opt/agent-kit}
APP_USER=${APP_USER:-agent}
APP_PORT=${PORT:-8765}
DATA_DIR=${DATA_DIR:-/var/lib/agent-kit}
ENV_FILE=${ENV_FILE:-/etc/agent-kit.env}
UNIT=/etc/systemd/system/agent-kit.service
BASE=${BASE:-https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main}

G=$(printf '\033[32m'); Y=$(printf '\033[33m'); R=$(printf '\033[31m')
D=$(printf '\033[90m'); B=$(printf '\033[1m'); N=$(printf '\033[0m')
[ -t 1 ] || { G=; Y=; R=; D=; B=; N=; }

step() { printf '\n%s▸ %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '\n%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }

# ---------------------------------------------------------------- 0. 前置检查
[ "$(id -u)" = 0 ] || die "需要 root：sudo sh $0"

if [ ! -f /etc/os-release ]; then
    die "认不出系统（没有 /etc/os-release）。这个脚本只适用于 Ubuntu / Debian。"
fi
. /etc/os-release
case "${ID:-}${ID_LIKE:-}" in
    *ubuntu*|*debian*) ;;
    *) die "当前是 ${PRETTY_NAME:-未知系统}，脚本只支持 Ubuntu / Debian。其他系统请照 DEPLOY-UBUNTU.md 手动装。" ;;
esac
ok "系统 ${PRETTY_NAME:-$ID}"

command -v python3 >/dev/null || warn "没装 python3，接下来会装"

# ---------------------------------------------------------------- 1. 依赖
step "安装依赖"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then
    apt-get update -qq || warn "apt update 有报错，继续尝试安装"
    apt-get install -y -qq python3 curl ca-certificates >/dev/null || die "装 python3/curl 失败，先手动跑：sudo apt-get install -y python3 curl ca-certificates"
fi
command -v python3 >/dev/null || die "python3 仍然不可用"
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
python3 - <<'PY' || die "Python 版本太低（需要 3.8+），Ubuntu 20.04 及以上自带 3.8+。"
import sys
sys.exit(0 if sys.version_info >= (3, 8) else 1)
PY
ok "python3 $PYV"

# ---------------------------------------------------------------- 2. 用户
step "准备运行用户与目录"
if [ "$APP_USER" = root ]; then
    warn "以 root 运行：模型执行的命令就是 root 权限，风险自负"
elif id -u "$APP_USER" >/dev/null 2>&1; then
    ok "用户 $APP_USER 已存在"
else
    useradd --create-home --shell /bin/bash "$APP_USER" || die "创建用户 $APP_USER 失败"
    ok "已创建用户 $APP_USER（普通用户，没 sudo）"
fi

mkdir -p "$APP_DIR" "$DATA_DIR" || die "创建目录失败"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR" 2>/dev/null || true
chmod 750 "$DATA_DIR"
ok "$APP_DIR  $DATA_DIR"

WORK_DIR=$(getent passwd "$APP_USER" 2>/dev/null | cut -d: -f6)
[ -n "$WORK_DIR" ] || WORK_DIR=/home/$APP_USER
WORK_DIR="$WORK_DIR/work"
mkdir -p "$WORK_DIR"
chown -R "$APP_USER:$APP_USER" "$WORK_DIR"
ok "工作目录 $WORK_DIR"

# ---------------------------------------------------------------- 3. 代码
step "下载代码"
cd "$APP_DIR" || die "进不去 $APP_DIR"
if [ ! -f update.sh ]; then
    curl -fsSL --retry 3 --connect-timeout 15 "$BASE/update.sh" -o update.sh.part \
        && mv update.sh.part update.sh \
        || die "下载 update.sh 失败，检查这台机器能不能访问 github（curl -I https://raw.githubusercontent.com）"
fi
chmod +x update.sh
sh update.sh || warn "更新过程有文件失败，看看上面的 ✗；已成功的文件可以用"
[ -f webchat.py ] || die "没拿到 webchat.py，代码目录是空的"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" 2>/dev/null || true
ok "代码在 $APP_DIR（$(ls webchat.py static/app.js >/dev/null 2>&1 && echo '含 static' || echo '缺 static，检查上面的下载结果')）"

# ---------------------------------------------------------------- 4. 配置
step "写配置 $ENV_FILE"
if [ -f "$ENV_FILE" ]; then
    ok "已存在，保持不动（要改就编辑这个文件）"
else
    umask 077
    cat > "$ENV_FILE" <<EOF
# agent-kit 配置。改完执行：systemctl restart agent-kit
# 模型接口的 key，必填
DEEPSEEK_KEY=${DEEPSEEK_KEY:-}

# 模型只能在这个目录里读写；换成你想让它干活的目录
AGENT_WORK=$WORK_DIR

# 会话库（重启不丢历史）
WEBCHAT_DB=$DATA_DIR/sessions.db

# 监听地址：127.0.0.1 只有本机能访问；改成 0.0.0.0 会让局域网能访问，务必同时设 WEBCHAT_TOKEN
WEBCHAT_HOST=127.0.0.1
PORT=$APP_PORT

# 单条消息最多跑多少步
AGENT_MAX_TURNS=100
# 上下文压缩阈值（估算 token）
AGENT_CTX_LIMIT=48000

# 访问口令。只有 WEBCHAT_HOST=0.0.0.0 时才需要；随便一串，访问时用 ?k=口令
#WEBCHAT_TOKEN=$(python3 -c 'import secrets;print(secrets.token_hex(8))' 2>/dev/null || echo change-me)
EOF
    chmod 600 "$ENV_FILE"
    ok "已生成（600，只有 root 能读）"
fi

# ---------------------------------------------------------------- 5. systemd
HAS_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    HAS_SYSTEMD=1
fi

if [ "$HAS_SYSTEMD" = 1 ]; then
    step "注册 systemd 服务"
    cat > "$UNIT" <<EOF
[Unit]
Description=agent webchat (android-agent-kit)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/python3 $APP_DIR/webchat.py
Restart=on-failure
RestartSec=3

# 沙箱：系统目录只读，模型最多改家目录和工作目录
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$WORK_DIR $DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable agent-kit >/dev/null 2>&1
    ok "已注册 /etc/systemd/system/agent-kit.service（开机自启）"
else
    step "没有 systemd，跳过服务注册"
    warn "容器/WSL 里常见。手动前台跑："
    printf '    cd %s && set -a; . %s; set +a; python3 webchat.py\n' "$APP_DIR" "$ENV_FILE"
fi

# ---------------------------------------------------------------- 6. 启动
step "启动"
KEY_OK=0
if grep -q '^DEEPSEEK_KEY=sk-' "$ENV_FILE" 2>/dev/null; then
    KEY_OK=1
fi

if [ "$KEY_OK" = 1 ] && [ "$HAS_SYSTEMD" = 1 ]; then
    systemctl restart agent-kit
    sleep 2
    if systemctl is-active --quiet agent-kit; then
        ok "服务已运行"
    else
        warn "服务没起来，看日志：journalctl -u agent-kit -n 30 --no-pager"
    fi
elif [ "$KEY_OK" = 1 ]; then
    warn "没有 systemd，需要你自己前台启动（命令见上）"
else
    warn "还没填 DEEPSEEK_KEY，先不启动"
    printf '    sudo nano %s        # 填 DEEPSEEK_KEY=sk-...\n' "$ENV_FILE"
    [ "$HAS_SYSTEMD" = 1 ] && printf '    sudo systemctl start agent-kit\n'
fi

# ---------------------------------------------------------------- 7. 收尾
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

$(printf '%s部署完成%s' "$G" "$N")

  打开      http://127.0.0.1:$APP_PORT
  从别的机器访问（推荐，走 SSH 隧道，不用开口令）：
      ssh -L $APP_PORT:127.0.0.1:$APP_PORT 用户名@${IP:-这台机器的IP}
      然后本机浏览器打开 http://127.0.0.1:$APP_PORT

  状态      systemctl status agent-kit
  日志      journalctl -u agent-kit -f
  改配置    sudo nano $ENV_FILE && sudo systemctl restart agent-kit
  更新代码  cd $APP_DIR && sudo sh update.sh && sudo systemctl restart agent-kit
  备份会话  sudo cp $DATA_DIR/sessions.db ~/sessions-$(date +%F).db

  模型能读写的地方只有：$WORK_DIR
  把要处理的项目放进去，或者改 $ENV_FILE 里的 AGENT_WORK 指过去。

EOF
