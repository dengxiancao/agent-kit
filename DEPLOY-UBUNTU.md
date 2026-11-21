# 在 Ubuntu 上部署 agent webchat

适用 Ubuntu 20.04 / 22.04 / 24.04，Debian 11+ 同理。1 核 1G 的小机器就够——模型不在本地跑，跑的是个 Python 进程。

整体就三件事：**装 Python → 放代码 → 用 systemd 常驻**。没有数据库要装，没有依赖要编译，`webchat.py` 只用标准库。

---

## 一、一键部署（推荐）

SSH 登进 Ubuntu，依次执行：

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/dengxiancao/android-agent-kit.git ~/agent-kit-src
sudo sh ~/agent-kit-src/deploy-ubuntu.sh
```

没有 git 也行：

```bash
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main/deploy-ubuntu.sh
sudo sh /tmp/deploy.sh
```

脚本做的事（重复执行安全）：

| 步骤 | 内容 |
|---|---|
| 1 | 装 `python3` `curl`，检查版本 ≥ 3.8 |
| 2 | 建普通用户 `agent`（**没有 sudo**）、目录 `/opt/agent-kit`、工作目录 `/home/agent/work`、数据目录 `/var/lib/agent-kit` |
| 3 | 用 `update.sh` 拉全部代码到 `/opt/agent-kit` |
| 4 | 生成 `/etc/agent-kit.env`（权限 600） |
| 5 | 注册 `agent-kit.service`，开机自启 |
| 6 | 检测到 key 才启动 |

想换位置：

```bash
sudo APP_DIR=/srv/agent PORT=9000 sh ~/agent-kit-src/deploy-ubuntu.sh
```

---

## 二、填 key 并启动

```bash
sudo nano /etc/agent-kit.env
```

只改第一行：

```ini
DEEPSEEK_KEY=sk-你的key
```

存盘（`Ctrl+O` 回车，`Ctrl+X`），然后：

```bash
sudo systemctl start agent-kit
systemctl status agent-kit --no-pager
```

看到 `Active: active (running)` 就成了。启动失败就看日志：

```bash
journalctl -u agent-kit -n 30 --no-pager
```

---

## 三、怎么打开界面

### 情况 A：Ubuntu 有桌面，直接用浏览器

打开 `http://127.0.0.1:8765`。

### 情况 B：Ubuntu 是服务器，从 Windows / Mac 访问（推荐）

不要改监听地址，用 SSH 隧道，流量加密，也不用开口令。

在**你自己的电脑**上开终端（Windows 用 PowerShell）：

```bash
ssh -L 8765:127.0.0.1:8765 你的用户名@服务器IP
```

保持这个窗口别关，然后本地浏览器打开 `http://127.0.0.1:8765`。

### 情况 C：让局域网/手机直接访问

改 `/etc/agent-kit.env`：

```ini
WEBCHAT_HOST=0.0.0.0
WEBCHAT_TOKEN=自己想一串至少12位的口令
```

```bash
sudo systemctl restart agent-kit
```

访问 `http://服务器IP:8765/?k=你的口令`。第一次之后浏览器会记住 cookie。

> ⚠️ 这套东西能执行任意 shell 命令。`0.0.0.0` 等于把服务器交给同网段所有人，口令只是防误闯，**不是加密**。要暴露到公网，前面必须套 HTTPS 反代（nginx + certbot），并且想清楚这台机器上有什么。

---

## 四、日常运维

```bash
systemctl status agent-kit          # 看状态
journalctl -u agent-kit -f          # 实时日志
sudo systemctl restart agent-kit    # 改完配置重启
sudo systemctl stop agent-kit       # 停

cd /opt/agent-kit && sudo sh update.sh && sudo systemctl restart agent-kit   # 更新代码
```

会话存在 `/var/lib/agent-kit/sessions.db`，备份就是拷这个文件：

```bash
sudo cp /var/lib/agent-kit/sessions.db ~/sessions-$(date +%F).db
```

模型能读写的地方只有 `AGENT_WORK`（默认 `/home/agent/work`）。要让它处理某个项目，把项目放进去，或者改配置指过去：

```ini
AGENT_WORK=/srv/my-project
```

改完记得 `sudo systemctl restart agent-kit`。

---

## 五、手动部署（不想用脚本）

```bash
# 1. 用户和目录
sudo apt update && sudo apt install -y python3 curl
sudo useradd --create-home --shell /bin/bash agent
sudo mkdir -p /opt/agent-kit /var/lib/agent-kit /home/agent/work
sudo chown -R agent:agent /var/lib/agent-kit /home/agent/work

# 2. 代码
cd /opt/agent-kit
sudo curl -fL -o update.sh https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main/update.sh
sudo sh update.sh
sudo chown -R agent:agent /opt/agent-kit
ls static/          # 应该有 app.html app.css app.js

# 3. 配置
sudo tee /etc/agent-kit.env >/dev/null <<'EOF'
DEEPSEEK_KEY=sk-你的key
AGENT_WORK=/home/agent/work
WEBCHAT_DB=/var/lib/agent-kit/sessions.db
WEBCHAT_HOST=127.0.0.1
PORT=8765
AGENT_MAX_TURNS=100
AGENT_CTX_LIMIT=48000
EOF
sudo chmod 600 /etc/agent-kit.env

# 4. 服务
sudo tee /etc/systemd/system/agent-kit.service >/dev/null <<'EOF'
[Unit]
Description=agent webchat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=agent
Group=agent
WorkingDirectory=/opt/agent-kit
EnvironmentFile=/etc/agent-kit.env
ExecStart=/usr/bin/python3 /opt/agent-kit/webchat.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/agent/work /var/lib/agent-kit

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now agent-kit
```

---

## 六、换成本地模型（Ollama）

不想付 API 钱、机器又够强，可以接 Ollama。它提供 OpenAI 兼容接口，这套代码直接能用：

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
```

改 `/etc/agent-kit.env`：

```ini
DEEPSEEK_URL=http://127.0.0.1:11434/v1/chat/completions
DEEPSEEK_MODEL=qwen2.5:7b
DEEPSEEK_KEY=ollama
WEBCHAT_MODELS=qwen2.5:7b,qwen2.5:14b
```

```bash
sudo systemctl restart agent-kit
```

模型要支持 function calling（`qwen2.5`、`llama3.1` 可以），否则它不会调工具，只会聊天。7B 跑 1G 内存的机器不够，至少 8G。

---

## 七、常见问题

**`Active: failed`，日志说 `缺少 DEEPSEEK_KEY`**
`/etc/agent-kit.env` 里的 key 没填，或者行首有空格。改完 `sudo systemctl restart agent-kit`。

**`status=203/EXEC`**
`ExecStart` 里的 python 路径不对。`which python3` 看一下，Ubuntu 一般是 `/usr/bin/python3`。

**页面能开但是白屏 / 404**
`static/` 没下全。`cd /opt/agent-kit && sudo sh update.sh` 重跑一次，看有没有 ✗。

**写文件报 `Permission denied`**
服务开了 `ProtectSystem=strict`，只有 `ReadWritePaths` 里的目录可写。要么改 `AGENT_WORK` 指到可写目录，要么在那个 unit 里把目标目录加进 `ReadWritePaths`。

**端口被占用**
`sudo ss -lntp | grep 8765` 看是谁。改 `PORT=8766` 重启即可。

**WSL / Docker 里 `systemctl` 用不了**
脚本会自动跳过服务注册。前台跑：

```bash
cd /opt/agent-kit && set -a; . /etc/agent-kit.env; set +a; python3 webchat.py
```

WSL 想用 systemd，在 `/etc/wsl.conf` 里加 `[boot]\nsystemd=true`，然后 `wsl --shutdown` 重进。

**能聊天但一调工具就报错**
看右栏「最近工具」和时间线，点开失败的那条。多数是工作目录里没有它要的文件，或者命令在 Ubuntu 上不存在（比如 `adb`、`termux-*`）。

---

## 八、卸载

```bash
sudo systemctl disable --now agent-kit
sudo rm /etc/systemd/system/agent-kit.service
sudo systemctl daemon-reload
sudo rm -rf /opt/agent-kit /var/lib/agent-kit /etc/agent-kit.env
sudo userdel -r agent     # 连家目录一起删，里面有 sessions 库的软链的话先备份
```

---

## 附：这套东西在 Ubuntu 上和手机上有什么不一样

| | 手机 Termux | Ubuntu |
|---|---|---|
| 屏幕操作（`adui.py`） | 能用，靠 adb / uiautomator | 基本用不上，除非连了安卓设备 |
| OCR（`ocr.py`） | 装了依赖就能用 | 需要自己 `pip install` 对应库 |
| 反向分析（`rev.py`） | 能用 | 能用，同一份代码 |
| shell 工具 | Termux 环境 | 完整 Linux，命令更全 |
| 常驻 | `nohup` / Termux:Boot | systemd，更省心 |

`adui.py` 在 Ubuntu 上要连真机的话，装 `adb` 并 `adb connect` 即可，但它的路径假设是 Termux 的，不一定开箱能用——这部分按需再折腾。
