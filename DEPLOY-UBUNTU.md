# 在 Ubuntu 上部署 agent webchat

适用 Ubuntu 20.04 / 22.04 / 24.04，Debian 11+ 同理。1 核 1G 的小机器就够——模型不在本地跑，跑的是个 Python 进程。

整体就三件事：**装 Python → 放代码 → 用 systemd 常驻**。没有数据库要装，没有依赖要编译，`webchat.py` 只用标准库。

---

## 一、一键部署（推荐）

SSH 登进 Ubuntu，依次执行：

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/dengxiancao/agent-kit.git ~/agent-kit-src
sudo sh ~/agent-kit-src/deploy-ubuntu.sh
```

没有 git 也行：

```bash
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/dengxiancao/agent-kit/main/deploy-ubuntu.sh
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
sudo curl -fL -o update.sh https://raw.githubusercontent.com/dengxiancao/agent-kit/main/update.sh
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
ExecStart=/usr/bin/python3 -B /opt/agent-kit/webchat.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
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

## 七、排错手册

下面这些坑都是真实踩过的。先按报错在表里找，再跳到对应小节。

| 报错 / 现象 | 真正的原因 | 看哪节 |
|---|---|---|
| `Unit file agent-kit.service does not exist` | 部署时 systemd 没开，脚本跳过了服务注册 | 7.1 |
| `Active: failed`，日志写 `缺少 DEEPSEEK_KEY` | 不是没填，是 key 没进到进程环境里 | 7.2 |
| `status=217/USER` | `agent` 用户不存在 | 7.1 |
| `status=203/EXEC` | `ExecStart` 里的 python 路径不对 | 7.1 |
| 手动运行报 `Permission denied` | `/etc/agent-kit.env` 是 `600 root`，普通用户读不了 | 7.3 |
| 连 `sudo` 都读不了 `/opt/agent-kit` 里的文件 | WSL 导入版，rootfs 放在 Windows 盘上（9p） | 7.4 |
| `OSError: [Errno 98] Address already in use` | 8765 被旧进程或反复重启的服务占着 | 7.5 |
| 能改的文件特别少 | `ProtectSystem=strict` 沙箱，故意的 | 7.6 |
| `update.sh` 报"写入失败"，或反复问"是否替换" | 目标目录不可写（`/tmp` 与 `/opt` 跨设备，改名删不掉旧文件） | 7.7 |
| 页面白屏 / 静态文件 404 | `static/` 没下全 | 7.8 |

### 7.1 服务起不来

**`Unit file agent-kit.service does not exist.`**

单元文件根本没写进 `/etc/systemd/system/`。最常见的原因是：第一次跑部署脚本时 WSL 还没启用 systemd，脚本走了「跳过服务注册」分支，只复制了代码和配置。后来开了 systemd，但没重跑脚本。

```bash
# 1. 确认 systemd 真的在跑（输出 systemd 才算）
ps -p 1 -o comm=

# 2. 确认单元文件在不在
ls -l /etc/systemd/system/agent-kit.service

# 3. 不在就重跑脚本，它是幂等的，不会删你的 key
sudo sh /tmp/deploy.sh
```

`/tmp/deploy.sh` 可能已被 WSL 重启清掉了，重新下载：

```bash
curl -fsSL -o /tmp/deploy.sh https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/agent-kit/main/deploy-ubuntu.sh
sudo sh /tmp/deploy.sh
```

**`status=217/USER`**

unit 里写了 `User=agent`，但这个用户不存在——说明脚本只跑了一半。

```bash
getent passwd agent || sudo useradd -r -m -d /home/agent -s /bin/bash agent
sudo systemctl daemon-reload && sudo systemctl restart agent-kit
```

**`status=203/EXEC`**

`ExecStart` 里的解释器路径不对：

```bash
which python3            # 一般是 /usr/bin/python3
systemctl cat agent-kit  # 对照看 ExecStart 那一行
```

### 7.2 key 明明填了，还说缺少

先做一次验证，不要猜：

```bash
sudo -u agent -H bash -c 'set -a; . ~/.config/webchat/env; set +a; echo "长度=${#DEEPSEEK_KEY} 开头=${DEEPSEEK_KEY:0:6} url=$DEEPSEEK_URL"'
```

正常输出是 `长度=35 开头=sk- url=https://api.deepseek.com/chat/completions`。不符合就是下面三种之一。

**原因一：程序读的文件不是你以为的那个**

这是最容易踩的。程序**只读 `~/.config/webchat/env`**；`/etc/agent-kit.env` 是给 systemd 的 `EnvironmentFile=` 用的，手动运行永远读不到它。

改哪个取决于你怎么跑：

| 怎么跑 | 读哪份 | 改哪份 |
|---|---|---|
| `systemctl start agent-kit` | `/etc/agent-kit.env`（root 读，降权执行） | `/etc/agent-kit.env` |
| 手动 `python3 webchat.py` | `~/.config/webchat/env` | 该用户家目录那份 |

两份都维护最省心：

```bash
sudo cp /home/agent/.config/webchat/env /etc/agent-kit.env
sudo chown root:root /etc/agent-kit.env && sudo chmod 600 /etc/agent-kit.env
```

**原因二：文件是 Windows 上编辑的，带了 BOM 或 CRLF**

变量名会变成 `\ufeffDEEPSEEK_KEY` 或值尾多一个 `\r`，等于没配。

```bash
head -c 8 ~/.config/webchat/env | xxd        # 开头出现 efbb bf 就是 BOM
cat -A ~/.config/webchat/env | head -3       # 行尾 ^M$ 就是 CRLF，正常应该是 $
```

一次修好：

```bash
sudo sed -i '1s/^\xEF\xBB\xBF//; s/\r$//' /home/agent/.config/webchat/env
```

**原因三：等号两边多了空格**

`DEEPSEEK_KEY = sk-xxx` 会被 shell 当成命令执行，变量根本不设置。必须是**紧贴的 `KEY=VALUE`**。

正确的配置长这样，整段覆盖最稳：

```bash
sudo tee /home/agent/.config/webchat/env >/dev/null <<'EOF'
DEEPSEEK_KEY=sk-你的key
DEEPSEEK_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-flash
AGENT_WORK=/home/agent/work
HOST=127.0.0.1
PORT=8765
EOF
sudo chown agent:agent /home/agent/.config/webchat/env
sudo chmod 600 /home/agent/.config/webchat/env
```

> `DEEPSEEK_URL` 必须带 `/chat/completions`。只写到 `https://api.deepseek.com` 会返回 404，报错看起来像 key 不对。

### 7.3 手动运行报 Permission denied

`/etc/agent-kit.env` 权限是 `600 root`，里面存着 key，故意不让别的用户读。所以：

```bash
# ✗ 普通用户读不了
cd /opt/agent-kit && set -a; . /etc/agent-kit.env; set +a; python3 webchat.py
# sh: .: cannot open /etc/agent-kit.env: Permission denied
```

正确姿势是以 `agent` 身份跑，并让它读自己家目录的配置（无 systemd 时部署脚本会自动做这一步）：

```bash
sudo mkdir -p /home/agent/.config/webchat
sudo cp /etc/agent-kit.env /home/agent/.config/webchat/env
sudo chown -R agent:agent /home/agent/.config

sudo -u agent -H python3 -B /opt/agent-kit/webchat.py --port 8765
```

`-H` 让 `~` 指向 `/home/agent`，不加的话程序会去读 `/root/.config/webchat/env`。

### 7.4 WSL 导入版的坑（rootfs 在 Windows 盘上）

如果你是用 `wsl --import` 装的自定义发行版，`/` 可能不是 ext4，而是挂在 Windows 某个盘上：

```bash
findmnt -no FSTYPE,OPTIONS /
# 正常：ext4  rw,relatime
# 异常：9p    rw,...,aname=drvfs;path=H:\;uid=1000,gid=1000,...
```

看到 `9p` 和 `path=H:\` 就是这种情况。后果是一串看起来毫无道理的报错：

| 现象 | 原因 |
|---|---|
| `sudo` 也打不开自己的文件，报 `Errno 13` | root 被映射成 Windows 侧身份，Unix 权限位只是装饰 |
| `ls -la` 要几十秒 | 9p 协议跨层访问 NTFS，比 ext4 慢一个数量级 |
| 启动报 `PermissionError: .../__pycache__` | Windows 拒绝创建缓存目录 |
| `chmod`/`chown` 改了没效果 | 权限由 Windows ACL 决定 |
| 数据库偶发 `database is locked` | 9p 上的文件锁不可靠 |

三招应对，按推荐程度排：

**① 换官方发行版（根治）**

```powershell
# Windows PowerShell
wsl --install -d kali-linux
```

rootfs 在 vhdx（ext4）里，权限、性能、systemd 全部正常。导入版留着当试验田就行。

**② 加 `-B` 避开写缓存**

```bash
sudo -u agent -H python3 -B /opt/agent-kit/webchat.py --port 8765
```

写进 unit 就永久生效：`ExecStart=/usr/bin/python3 -B /opt/agent-kit/webchat.py`。

**③ 放在 Windows 侧确定可写的目录**

```bash
mkdir -p /mnt/h/wsl/agent-work
# 然后改配置里的 AGENT_WORK
```

只能缓解，权限问题依旧，只是换了个位置。

### 7.5 端口被占用

```
OSError: [Errno 98] Address already in use
```

说明 8765 上已经有一个进程。常见于三种情况：

- 之前手动启动过，进程还在后台
- `nohup` 留在运行
- systemd 服务因为 key 不对在**反复重启**，每次启动都去抢端口

```bash
sudo ss -lntp | grep 8765      # 看 pid 和进程名
sudo ps -o pid,user,cmd -p <PID>
```

| 查到的是 | 处理 |
|---|---|
| `python3 ... webchat.py` | `sudo kill <PID>` |
| systemd 的 `agent-kit` | `sudo systemctl stop agent-kit`（先别 enable，等配置修好） |
| 分不清 | `sudo pkill -f webchat.py`，一次清干净 |

想先看到界面，换个端口最快：

```bash
sudo -u agent -H python3 -B /opt/agent-kit/webchat.py --port 8766
# 浏览器开 http://127.0.0.1:8766
```

### 7.6 能改的文件特别少

这是**两层限制叠加**，都是故意的。

| 层 | 在哪 | 限制什么 | 报错 |
|---|---|---|---|
| 代码层 | `webchat.py` 的 `safe()` | `read_file`/`write_file`/`list_dir` 只能在 `AGENT_WORK` 内 | `路径越界，只能访问工作目录` |
| 系统层 | unit 的 `ProtectSystem=strict` | 整个文件系统只读，只有 `ReadWritePaths` 里的目录可写 | `Permission denied` / `Read-only file system` |

`run_shell` 不受代码层限制（能 `cat /etc/passwd`），但写仍然被系统层挡住。

默认能写的只有 `/home/agent/work` 和 `/var/lib/agent-kit`。要放开哪个：

```bash
# 1. 扩大文件工具的可视范围（代码层）
sudo sed -i 's|^AGENT_WORK=.*|AGENT_WORK=/home/agent|' /etc/agent-kit.env

# 2. 同步放行系统层
sudo systemctl edit agent-kit
# [Service]
# ReadWritePaths=/home/agent
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart agent-kit
```

**为什么不默认全放开**：它手里是一个能执行任意命令的 shell，全盘可写意味着一句 `rm -rf /` 或改坏 `/etc/fstab` 就完了。限制的是爆炸半径。

真要全放开（只建议在一次性环境里）：

```bash
sudo systemctl edit agent-kit
# [Service]
# ProtectSystem=no
# ProtectHome=no
# PrivateTmp=no
```

⚠️ WSL 的 `/mnt/c` 就是你的 Windows C 盘。全放开之后，agent 能直接改写桌面文件。至少保留一条只读：

```ini
ReadOnlyPaths=/mnt/c
```

### 7.7 `update.sh` 报"写入失败"或"是否替换"

这两种提示经常一起出现：

```
mv: 是否替换 'adui.py'，而忽略模式 0644 (rw-r--r--)？
  ✗ adui.py       写入失败
```

或者连脚本本身都下不来：

```
Warning: Failed to open the file update.sh.new: 权限不够
curl: (23) client returned ERROR on write of 8192 bytes
```

**根因只有一个：目标目录当前用户不可写。** 和网络、镜像、HTTP 代理都没关系。

先判断：

```bash
ls -ld /opt/agent-kit
touch /opt/agent-kit/.wtest && echo 可写 || echo 不可写
df -h /opt                      # 排除磁盘满
findmnt -no OPTIONS /opt        # 排除 ro 只读挂载
```

| 结果 | 处理 |
|---|---|
| `touch` 报权限不够，目录属主是 root | `sudo chown -R kali:kali /opt/agent-kit`（`kali` 换成你的用户名） |
| `findmnt` 的 OPTIONS 里带 `ro` | 换目录：`cp -a /opt/agent-kit ~/agent-kit && cd ~/agent-kit` |
| `df -h` 显示 100% | 清空间：`journalctl --vacuum-size=50M`，删 `~/.cache` |

**为什么还会问"是否替换"**：`/tmp` 是 tmpfs，`/opt` 在另一个挂载点，`mv` 跨设备时不能 rename，只能"删掉目标 → 复制过去"。目录不可写就删不掉，这一步于是退化成交互确认；回车就等于放弃，脚本判定写入失败。所以重跑一百次结果都一样。

改好属主后，重新取脚本再跑：

```bash
cd /opt/agent-kit
curl -fL -o update.sh.new "https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/agent-kit/main/update.sh"
chmod +x update.sh.new && mv -f update.sh.new update.sh
sh update.sh
```

判断是否换上了新脚本：第一行打印 `agent-kit 更新` 是新版，`android-agent-kit 更新` 是旧版。新版（10025 字节起）会在写盘前检查目录权限，并把"跨设备 mv"改成"同目录中转 + 截断写入兜底"，不会再出现这个报错。

### 7.8 其他

**页面能开但白屏 / 静态文件 404**

`static/` 没下全：

```bash
ls /opt/agent-kit/static/          # 应该有 app.html / app.css / app.js
cd /opt/agent-kit && sudo sh update.sh
```

**能聊天，一调工具就报错**

看右栏「最近工具」，点开失败那条。多数是工作目录里没那个文件，或者命令在 Ubuntu 上不存在（`adb`、`termux-*`、`pkg` 这些是手机专用的）。

**改了配置不生效**

```bash
sudo systemctl restart agent-kit    # systemd
# 或 Ctrl+C 后重新执行启动命令（手动跑）
```

配置只在进程启动时读一次。

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

## 九、让 Ubuntu 连上安卓手机（adb）

`adui.py` 看屏幕、点屏幕都靠 adb。**优先插 USB 线**，别一上来折腾无线调试。

### 9.1 USB（推荐，跟 WiFi 无关）

手机端：

1. 设置 → 关于手机 → 连点「MIUI 版本」7 次，开出开发者选项
2. 打开「USB 调试」
3. 小米还要打开「**USB 调试（安全设置）**」——这个开关决定 `input tap` 能不能真的点到屏幕上。它要求登录小米账号并插着 SIM 卡，没有就一直是灰的

Ubuntu 端：

```bash
sudo apt install -y android-tools-adb
adb devices
```

手机这时会弹「允许 USB 调试吗」，勾「一律允许」再确定。`adb devices` 出现 `xxxxx device` 就成了：

```bash
adb shell input keyevent 3      # 按一下 Home，手机有反应就通了
```

报 `no permissions` 或 `unauthorized`：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2717", MODE="0666", GROUP="plugdev"' | sudo tee /etc/udev/rules.d/51-android.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# 拔掉重插一次，再 adb devices
```

`2717` 是小米的厂商 ID。别的牌子换 ID（三星 `04e8`、OPPO `22d9`、vivo `2d95`），或者直接 `lsusb` 看。

### 9.2 无线调试为什么没 WiFi 就开不了

Android 11 起，无线调试**强制要求手机已连接 WLAN**，4G/5G 不算。设置页会直接置灰，显示「请连接到 WLAN 网络」。这不是 MIUI 的 bug，是系统行为——它默认 adb 客户端在同一个局域网里。

而且截图里那个 `10.42.99.191` 是运营商的**内网地址**，就算强行开了端口，电脑也路由不过去。

想无线，先让手机和电脑进同一个局域网：

- 笔记本开热点（Windows：设置 → 网络和 Internet → 移动热点），手机连上
- 或者旧手机、随身 WiFi 开热点

然后在手机上：开发者选项 → 无线调试 → 打开 → 「使用配对码配对设备」：

```bash
adb pair 192.168.137.23:37105      # 端口和六位码照手机屏幕抄
adb connect 192.168.137.23:41234   # 连接用的是另一个端口
adb devices
```

两个坑：

- Android 11+ 的端口是**随机**的，每次重开无线调试都会变，不是 5555
- 配对端口和连接端口不是同一个，都写在手机屏幕上

### 9.3 已经 root 的话

```bash
su -c 'setprop service.adb.tcp.port 5555; stop adbd; start adbd'
adb connect 手机IP:5555
```

这条不看 WiFi 状态。但小米 10S 得先解 BL 锁才能 root，为这个去解不值当。

### 9.4 手机自己连自己（Termux 控制本机，不需要 WiFi）

想让手机上的 Termux / proot 里的 agent 控制本机屏幕，可以走本地回环。但**要先借一次电脑**，把 adbd 拉到 TCP 上：

```bash
# 电脑上，USB 连着手机
adb devices            # 先确认能看到手机并已授权
adb tcpip 5555         # 让手机里的 adbd 开始监听 TCP
# 拔掉 USB
```

手机上（Termux 或 proot）：

```bash
pkg install android-tools        # proot 里用 apt install adb
adb connect 127.0.0.1:5555
adb devices                      # 应出现 127.0.0.1:5555  device
adb shell input keyevent 3       # 能回桌面就通了
```

为什么这样能行：`adb tcpip` 是让**手机里的 adbd** 监听 5555，跟 WiFi 无关，监听地址是 `0.0.0.0`，所以回环也通。那个灰掉的「无线调试」开关干的其实是同一件事，只是它非要先连上 WLAN 才肯做。

限制：

- 手机重启后失效，得重新插一次线跑 `adb tcpip 5555`
- 端口开着时同网段设备也能尝试连（仍需你点授权），不用了发 `adb usb` 切回 USB 模式
- MIUI 上 `input tap` 要生效，仍需打开「USB 调试（安全设置）」

**开热点为什么不管用**：Android 11 起，热点不算「已连接 WLAN」，无线调试照样是灰的。热点只在配合 `adb tcpip` 时有用——给电脑一个能路由到手机的网段。

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

### 觉得"能力不如手机上"时先看这里

v2.3 之前，提示词是写死给 Termux 的，模型在 Ubuntu 上会一直以为自己在手机上，去调 `adui.py`、`ui look` 这些这儿根本没有的东西，撞墙之后反复重试，最后耗到步数上限——看起来就是"什么都干不了"。

v2.3 起会自动识别环境，服务器上换成 Linux 版提示词，并且：

| 限制 | 默认值 | 怎么调 |
|---|---|---|
| 单条命令超时 | 120 秒 | `AGENT_CMD_TIMEOUT=300` 写进 `/etc/agent-kit.env` |
| 连续失败熔断 | 4 次 | `AGENT_FAIL_LIMIT=8`，或设 0 关掉 |
| 可写的目录 | `/home/agent/work`、`/var/lib/agent-kit` | `systemctl edit agent-kit` 里加 `ReadWritePaths=/你的/目录` |
| 文件工具的可视范围 | `AGENT_WORK` 之内 | 改 `/etc/agent-kit.env` 的 `AGENT_WORK` |

判断"是不是被沙箱挡了"很简单，看报错：

- `路径越界，只能访问工作目录` → 代码层的 `safe()`，改 `AGENT_WORK`
- `Permission denied` / `Read-only file system` → systemd 的 `ProtectSystem`，改 `ReadWritePaths`
- `超过 120 秒没返回` → 命令本身太慢，拆小或 `nohup` 放后台

改完都要 `sudo systemctl restart agent-kit`。
