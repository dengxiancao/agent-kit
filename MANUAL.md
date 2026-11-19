# 手机 Agent 工具集

> 部署与使用手册

**2026.11.19** · 适用于 Termux（Android 11+）与 Alpine Linux 虚拟机

这套东西的目标：在手机上跑一个**能真正动手**的 AI——聊天、执行命令、分析 APK、操控手机屏幕。七个脚本加三个前端文件，两块环境，彼此独立，坏一个不影响其他。


## 零、先看这张图

很多人第一次装完会混淆：`ui.py` 和 `adui.py` 都是操控屏幕，为什么是两个文件？因为它们操控的是**两种完全不同的屏幕**，技术路线不同，不能合并。

| 文件 | 运行环境 | 操控什么 | 技术路线 |
|---|---|---|---|
| `agent.py` | 手机 + 虚拟机 | ——（对话入口） | DeepSeek function calling |
| `webchat.py` | 手机 + 虚拟机 | ——（图形界面） | http.server + 内嵌页面 |
| `rev.py` | 手机 + 虚拟机 | 文件（APK/ELF/PE） | 纯标准库二进制解析 |
| `adui.py` | **手机** | **安卓屏幕** | ADB + uiautomator |
| `ocr.py` | 手机 + 虚拟机 | 图片/PDF 里的字 | Tesseract 5 |
| `ui.py` | **虚拟机** | **X11 桌面** | xdotool + 截图 OCR |
| `patch_ui.py` | 虚拟机 | ——（补丁脚本） | 改 agent.py 加工具 |

> 一句话记住：**手机用 adui，虚拟机用 ui。** 装错环境不会报错，只会一直说“找不到 adb”或“DISPLAY 为空”。


## 一、文件清单

所有文件都在仓库 github.com/dengxiancao/android-agent-kit。下载有三种方式，按你的网络选一种就行。

**方式 A：整仓克隆（推荐，墙内可用）**

```
git clone --depth 1 https://ghfast.top/https://github.com/dengxiancao/android-agent-kit ~/work-kit
```

`ghfast.top/` 是 GitHub 的镜像前缀，原地址整段接在后面即可。以后更新：

```
cd ~/work-kit && git pull
```

不想每次手写前缀，配一次全局替换，之后 git 命令照原样敲：

```
git config --global url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"
```

**方式 B：单文件（镜像 raw）**

只要一两个文件时用这个。前缀和方式 A 是同一个镜像，只是后面的地址不同：

```
BASE=https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main
cd ~/work
curl -fL -o adui.py.part $BASE/adui.py && mv adui.py.part adui.py
```

> ⚠️ **别用 `wget -O 目标文件`。** 下载失败时它会先把目标文件清空，留下 0 字节的残骸，把原来能用的版本一起毁掉（这个坑踩一次就够）。`curl -f` 遇到非 2xx 直接失败、不落盘；先写 `.part` 再 `mv`，半截文件永远覆盖不了好文件。

**方式 C：备用入口**

jsDelivr 有国内 CDN，通常是三者里最快的，但**内容会缓存几个小时**——刚更新的版本可能还是旧的，拿新版别用它：

```
BASE=https://cdn.jsdelivr.net/gh/dengxiancao/android-agent-kit@main
```

`raw.githubusercontent.com` 直连在部分网络下会报 `Read error (Connection timed out) in headers` —— 域名能解析、TCP 也连得上，但响应被中途掐断。**这种断法改 DNS 没用**：

```
BASE=https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main
```

| 文件 | 字节数 | 干什么 | 装在哪 |
|---|---|---|---|
| `rev.py` | 28616 | 逆向侦察 | 手机 + 虚拟机 |
| `webchat.py` | 45068 | 浏览器聊天界面（服务 + agent 循环） | 手机 + 虚拟机 |
| `static/app.html` | 5110 | 界面结构 | 手机 + 虚拟机 |
| `static/app.css` | 22706 | 界面样式（含深色模式） | 手机 + 虚拟机 |
| `static/app.js` | 35216 | 界面逻辑（会话、流式渲染、Markdown） | 手机 + 虚拟机 |
| `adui.py` | 47304 | 安卓控屏（含 doctor、ocr） | 手机 |
| `ocr.py` | 33777 | 本地 OCR（图片/PDF → 文字+坐标） | 手机 + 虚拟机 |
| `ui.py` | 16329 | Linux 桌面控屏 | 虚拟机 |
| `patch_ui.py` | 2708 | 把 ui 注入 agent.py | 虚拟机 |
| `MANUAL.html` | — | 这份手册 | 手机 + 虚拟机 |

下完校验大小，对不上就是没下完：

```
wc -c rev.py webchat.py adui.py ocr.py static/app.html static/app.css static/app.js
```

> **`webchat.py` 必须和 `static/` 目录放在同一层。** 只拷 `webchat.py` 过来，打开页面会看到「缺少 static 目录」的提示页——不是程序坏了，是少了三个前端文件。

手机上看这份手册不用下载，直接开在线版：https://dengxiancao.github.io/android-agent-kit/MANUAL.html

> 仓库是长期地址，不会像临时粘贴站那样过期。改完代码 `git commit` 回自己仓库，换手机也不用重找链接。

仍然建议定期备份：`tar czf ~/backup.tgz ~/work`。


### 1.1 一键更新

仓库里带了一个 `update.sh`，以后换新版不用记文件地址、不用逐个 curl。下面用 `~/work` 举例，**你的脚本放在哪个目录就换成哪个**（有人放在 `~/work-kit`）：

**第一次：取脚本并更新全部**

```
cd ~/work
curl -fL -o update.sh.part https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main/update.sh
mv update.sh.part update.sh && chmod +x update.sh
sh update.sh
```

以后只要一句：

```
sh ~/work/update.sh
```

它做的事：

| 行为 | 为什么重要 |
|---|---|
| 先下临时文件 | 断网、下到一半、镜像返回半截内容，都**不会**覆盖你正在用的文件 |
| 内容比对 | 跟本地一模一样就跳过，不写盘、不产生 `.bak` |
| 语法预检 | `.py` 先编译一遍，坏了直接拒绝写入，旧文件原样保留 |
| 自动换镜像 | ghfast 不通就试 gh-proxy，再试 raw |

三种用法：

```
sh update.sh --list      # 只看本地和远端的版本差，不下载
sh update.sh ocr.py      # 只更新一个，可写多个
sh update.sh --self      # 更新 update.sh 自己
```

> 更新完它会提示跑 `python3 ocr.py doctor` 和 `python3 adui.py doctor` 复查。

`.bak` 是上一次的版本，确认新版没问题后可以删：`rm -f *.bak`。


## 二、手机线部署（Termux）

手机是主战场：既能聊天，又能操控屏幕。全套约 15 分钟，其中配对占一半时间。


### 2.1 一次性准备

**① Termux 来源要对。** Google Play 那个版本 2020 年就停止更新了，`pkg` 仓库连不上，装什么都失败。从 F-Droid 或 GitHub Releases（`termux/termux-app`，选 `arm64-v8a`）安装。

**② 换国内源。** 默认源在国外，几十 KB/s。

```
termux-change-repo
```

依次选 `Mirror group` → `Mirrors in Chinese` → 回车。或者直接写死清华源：

```
printf 'deb https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main stable main\n' > $PREFIX/etc/apt/sources.list
pkg update -y
```

**③ 装依赖。** 只装必需的，不要跑 `pkg upgrade`（那是几百 MB 的全量升级，用不上）。

```
pkg install -y python wget android-tools
```

`android-tools` 提供 `adb`，约 10MB。装完执行 `adb version` 检查，版本低于 1.0.41 的话，配对时可能报 `unknown command`。

**④ 保活设置（关键）。** 不做这步，agent 一执行命令就被系统杀掉。

```
termux-wake-lock
```

再去系统设置里给它开绿灯（小米/华为/OPPO 尤其严）：

- 设置 → 应用管理 → Termux → **省电策略**：无限制
- 同一页面 → **自启动**：允许
- 同一页面 → **后台弹出界面**：允许

> ⚠️ `termux-wake-lock` 每次开机都要重新执行一次。它是防休眠锁，不是永久配置。


### 2.2 下载与校验

见第一章。手机端需要 `rev.py`、`webchat.py`、`adui.py`、`ocr.py` 四个，外加 `static/` 里的 `app.html`、`app.css`、`app.js` 三个前端文件；不装 OCR 也能控屏，只是遇到自绘界面就没辙。


### 2.3 启动

两种入口，二选一，也可以同时跑（互不影响）。

|  | `agent.py` | `webchat.py` |
|---|---|---|
| 形态 | 终端里对 `you>` 说话 | 浏览器聊天页 |
| 启动 | `python3 agent.py` | `python3 webchat.py` |
| 退出 | 输入 `exit` 或 Ctrl+C | Ctrl+C |
| 适合 | 脚本化、SSH 里用 | 手机上点着用 |

**界面版**启动后终端会一直占用、不回到提示符——这是正常的，它在跑 HTTP 服务。切到浏览器打开：

```
http://127.0.0.1:8765
```

> 必须带 `http://`。只输 `127.0.0.1:8765` 会被 Chrome 当成搜索词。

想先看界面长什么样、不消耗 API 额度，加 `--mock`：

```
python3 webchat.py --mock
```

端口被占了就换一个：

```
python3 webchat.py --port 8800
```

**让 agent 知道有这些工具。** 不用改代码，它看到文件就懂，但你第一句话点明更保险：

```
~/work 下有 rev.py（逆向分析）和 adui.py（操作手机屏幕），需要时直接用 python3 调用。
```


### 2.4 控屏准备（ADB 无线调试）

这一步是全套里最容易卡住的地方。**Android 11 以上才有无线调试**，10 及以下需要先用电脑 USB 连一次。

**① 打开开发者选项**：设置 → 我的设备 → 全部参数 → 连续点「MIUI 版本」7 次。然后 设置 → 更多设置 → 开发者选项 → **无线调试** 打开。

**② 配对（只需一次，重启不丢）。** 点「使用配对码配对设备」，会弹窗显示两组东西：

| 位置 | 显示的内容 | 用途 |
|---|---|---|
| 「无线调试」**主页面** | IP 地址和端口，如 `192.168.1.102:39549` | **connect** |
| 「与设备配对」**弹窗** | IP 地址和端口 + 6 位配对码 | **pair** |

> ⚠️ **这两个端口不一样，是本流程 90% 失败的原因。** 拿主页面那个端口去 pair，必定报 `protocol fault (couldn't read status message)`。

**配对端口有效期约 2 分钟**，切换应用、锁屏都会让它提前失效。所以用**分屏**操作，让设置和 Termux 同时可见：最近任务 → 长按 Termux → 分屏 → 上半屏选「设置」。

**不想肉眼抄端口**，直接扫（推荐，Termux 里唯一可靠的办法）：

```
python3 adui.py scan
```

Termux 和 adbd 跑在同一台手机上，所以它扫的是 `127.0.0.1` 的 30000–65535，找到端口就顺手连上：

```
扫描 127.0.0.1 的 30000-65535 端口（共 35536 个，约 5-20 秒）…
  6s，发现 2 个开放端口：
    39549
    42361

  127.0.0.1:39549  -> 连接成功

设备就绪：127.0.0.1:39549
接下来：python3 adui.py info   然后  python3 adui.py look
```

> `python3 adui.py ports` 走的是 `adb mdns services`，而 **Termux 的 `android-tools` 编译时没带 mDNS**，一定报 `adb mdns is not supported by this version of adb`。这不是手机的问题，也不是配置错，改用 `scan` 就行。

配对弹窗打开的那 2 分钟里，`scan` 也会把弹窗端口一起扫出来（多出来的那个就是 pair 端口）。弹窗关掉后它就消失，这也是判断哪个是 pair 端口的小技巧。

配对命令写成 `IP:端口 6位码` 最不容易出错：

**端口和码都从弹窗里抄，2 分钟内执行完**

```
python3 adui.py pair 192.168.1.102:42361 570100
```

成功标志：

```
Successfully paired to 192.168.1.102:42361

配对完成（这东西只做一次，重启也不会丢）。
配对后调试端口会换一个，正在自动找…

  127.0.0.1:39549  -> 连接成功
```

配对成功会自动接着扫端口并连上，不用你再抄第二次。

**③ 连接（每次重启后都要做）。** 用**主页面**那个端口：

```
python3 adui.py connect 192.168.1.102:39549
adb devices
```

`devices` 下面出现这一行才算通：

```
192.168.1.102:39549	device
```

> 显示 `unauthorized` 是没点手机上的「允许调试吗」弹窗；显示 `offline` 就 `adb kill-server` 后重连。

报 `Connection refused` 只有一个意思：**这个端口上没有服务在监听**，端口已经变了（开关一次无线调试、打开一次配对弹窗，端口都可能换）。直接 `python3 adui.py scan`，它会找到当前端口并重连。

**④ 验证工具。**

```
python3 adui.py info
```

预期：

```
adb      : adb
device   : 默认  (M2102J2SC / Android 13)
screen   : 1080x2340
foreground: com.termux
```


### 2.5 中文输入（一条命令，之后自动）

`adb shell input text` **只支持 ASCII**，中文会丢字，所以必须装一个能被 adb 调用的输入法。这套流程已经封装好，一条命令做完：

```
cd ~/work
python3 adui.py ime-install
```

它会依次做四件事：**下载 17KB 的 apk → `adb install` → `ime enable` → 打印结果**。不需要 root，也不需要你自己去设置里翻输入法列表。成功时输出：

```
== 下载 ADBKeyBoard（约 17KB，3 个源依次尝试）
  已保存 ~/work/ADBKeyboard.apk（17374 字节）
== 安装 ~/work/ADBKeyboard.apk
  Success
ADBKeyBoard 已启用（不抢你的默认输入法，text 时会临时切换再切回）
```

之后中文直接输入：

```
python3 adui.py text "你好，世界"
```

输出 `输入（ADBKeyBoard）：你好，世界` 就成了。**它只在输入中文的那一瞬间切到 ADB Keyboard，输完立刻切回你原来的输入法**，所以不会出现「键盘不弹了」。

> 如果手机弹出「禁止通过 USB 安装应用」，是 MIUI 拦的：apk 已被推到 下载/ADBKeyboard.apk，点一下手动装，再执行 `python3 adui.py ime-enable`。想以后都能让 adb 装，去 开发者选项 打开「USB 安装」。

三个排障命令：

```
python3 adui.py ime           # 看当前输入法、ADBKeyBoard 装没装/启用没
python3 adui.py ime adb       # 手动切到 ADB Keyboard（它没有可见键盘）
python3 adui.py ime restore   # 切回你原来的输入法
```

想确认字真的落进输入框了（多花 1~2 秒，会回读界面）：

```
python3 adui.py text "你好" --verify
```


## 三、虚拟机线（Alpine + icewm）

虚拟机这条路适合需要完整 Linux 环境的场景：装包、编译、跑桌面程序。它的屏幕操控靠 `xdotool`，走 X11 协议，比安卓那套稳定得多。


### 3.1 装依赖

```
apk add xdotool imagemagick tesseract-ocr tesseract-ocr-data-chi_sim wmctrl
```

约 80MB。中文语言包报找不到的话，先加 community 源：

```
echo 'https://mirrors.aliyun.com/alpine/community' >> /etc/apk/repositories
apk update && apk add tesseract-ocr-data-chi_sim
```


### 3.2 自检

```
cd ~/work
python3 ui.py info
```

```
DISPLAY   : :0
screen    : 1280x800
xdotool  : OK
tesseract: OK
ocr langs : chi_sim,eng
```

> ⚠️ `DISPLAY` 是空的话，说明当前终端不在图形会话里。补一句 `export DISPLAY=:0` 再试。agent 通过 `run_shell` 调用时同样要有这个变量，否则 `look` 会失败。


### 3.3 接入 agent

让 `ui` 成为 agent 的一个正式工具（而不是每次拼 shell 命令），跑一次补丁：

```
python3 patch_ui.py
```

它做三件事，改前自动备份成 `agent.py.bak`：

- 在工具清单里加 `ui`
- 在执行分支里接上 `ui.py`
- 把命令超时从 10 秒提到 30 秒（`apk add`、解压这类操作 10 秒根本不够）

> 补丁是幂等的，重复执行会打印「已经加过了」。想回滚就 `cp agent.py.bak agent.py`。


## 四、日常使用


### 4.1 界面版怎么用

界面分三块：左边会话列表、中间对话、右边运行详情。手机上侧栏收成抽屉（左上 ☰），运行详情变底部弹层（顶部图表按钮）。

| 操作 | 位置 | 说明 |
|---|---|---|
| 发消息 | 底部输入框，回车或 ↑ | Shift+回车换行；中文输入法选词时按回车不会误发 |
| 新对话 | 左上「新对话」，或 ⌘K / Ctrl+K | 旧对话不清空，随时切回去 |
| 切换对话 | 左侧列表 | 按今天 / 昨天 / 7 天内 / 更早分组 |
| 搜索 | 左侧搜索框 | 同时搜标题和消息正文 |
| 改名 / 置顶 / 删除 | 列表项右侧 ⋯ | 手机上 ⋯ 常驻，不用悬停 |
| 看工具细节 | 点工具卡 | 展开完整输出和耗时；失败的自动展开并标红 |
| 看思考过程 | 点「思考 · N 字」 | 折叠的推理内容，不回传给模型 |
| 看用量 | 每条回复下方的页脚 | `4 步 · 18.6s · 512 tokens` |
| 看上下文 | 顶部 chip / 右栏 | `上下文 5.1k / 64k`，超 85% 变黄 |
| 停止 | 顶部 ■ | 只停当前轮，已生成的内容保留 |
| 导出 | 顶部 ↓ | 存成 `.md` |

**对话不会丢。** 每接一条消息就写进 `~/.local/share/webchat/sessions.db`。关终端、重启虚拟机、进程被 kill，下次打开还是原样，接着聊。任务跑到一半刷新页面，进度会自己接上。

**工具卡片是核心。** agent 每执行一次命令就弹一张卡。它说"我做了"不算数，卡片上的 ✓ 和输出才算。

**key 别每次 export。** `export` 只活在当前终端会话里，虚拟机一重启就是全新的 shell，变量自然没了 —— 于是每次都得重来一遍，看起来像「key 失效了」。写进配置文件就一劳永逸：

```
mkdir -p ~/.config/webchat
cat > ~/.config/webchat/env <<'EOF'
DEEPSEEK_KEY=sk-你的key
AGENT_WORK=/root/work-kit
HOST=0.0.0.0
EOF
chmod 600 ~/.config/webchat/env
```

之后 `python3 webchat.py` 直接启动，不用任何 export。启动信息里会多一行 `配置 ~/.config/webchat/env`，用来确认读到了。

| 文件里的键 | 作用 |
|---|---|
| `DEEPSEEK_KEY` | API key |
| `AGENT_WORK` | agent 的工作目录，默认 `~/work`；脚本放在 `work-kit` 就填那 |
| `HOST` | `0.0.0.0` 才允许端口映射 / 局域网访问，默认 `127.0.0.1` |
| `PORT` | 端口，默认 8765 |
| `AGENT_MAX_TURNS` | 单条消息最多几步，默认 100 |

环境变量优先级高于文件 —— 临时换 key 或端口直接 `DEEPSEEK_KEY=sk-xxx python3 webchat.py` 覆盖，不用改文件。

文件里是明文 key，权限务必 600，也别放进仓库目录 —— `git add .` 会把它带上。


### 4.2 逆向分析（rev.py）

```
python3 rev.py triage 目标.apk      # 类型/大小/哈希/熵，先判断值不值得看
python3 rev.py apk 目标.apk         # 包名、版本、权限、组件、so、URL
python3 rev.py elf libxxx.so        # 架构、入口、依赖库、节表
python3 rev.py pe 目标.exe          # 架构、子系统、导入 DLL
python3 rev.py dex classes.dex      # 类/方法数量、包结构
python3 rev.py strings 目标 --grep http --limit 30
python3 rev.py hexdump 目标 --off 0x3c --len 64
python3 rev.py carve mem.dump       # 从内存镜像里切出内嵌 ZIP/ELF/DEX
```

对它说人话即可，不用背语法：

```
用 python3 rev.py 分析 ~/work/xxx.apk，先 triage 再 apk，重点看包名、权限和导出的组件
```

> ⚠️ `rev.py` 做**静态侦察**：包名、权限、组件、依赖库、可疑域名。它**不反编译 Java 源码**（那需要 jadx + JVM，手机上装不下），也不做动态调试（需要 frida + root）。


### 4.3 操控屏幕

**手机（adui.py）**——先看再动，这是铁律：

```
python3 adui.py look                 # 列出当前界面所有文字 + 坐标 + 序号
python3 adui.py tap 4                # 点第 4 个元素（不用算坐标）
python3 adui.py tap-text 设置         # 按文字点，支持模糊
python3 adui.py text "你好 hello"     # 输入文字，中英文都行
python3 adui.py key back             # 返回；还有 home/enter/appswitch
python3 adui.py longpress 8          # 长按
python3 adui.py scroll down 3        # 往下翻 3 屏
python3 adui.py wait 登录 --timeout 15   # 等文字出现再返回坐标
python3 adui.py scan                 # 扫无线调试端口并自动连接（推荐）
python3 adui.py ports                # 走 mDNS，Termux 的 adb 不支持，会报错
python3 adui.py start com.android.settings
python3 adui.py apps chrome          # 列第三方应用
python3 adui.py shot                 # 存截图
```

`look` 的真实输出长这样，`可点(父)` 表示文字本身不可点，但点它的父容器就对了：

```
screen 1080x2340  当前应用 com.tencent.mm  可见元素 14
[ 1] 微信                    ( 190, 115)            com.tencent.mm/kh
[ 2] 搜索                    ( 980, 115) 可点         com.tencent.mm/j_
[ 4] 文件传输助手               ( 540, 266) 可点(父)      com.tencent.mm/kb
[ 6] 张三                    ( 540, 446) 可点(父)      com.tencent.mm/kb
[11] 微信                    ( 108,2325) 可点         com.tencent.mm/icon
```

**虚拟机（ui.py）**：

```
python3 ui.py look                   # 截图 + 窗口列表 + 屏幕文字（带坐标）
python3 ui.py find 确定              # 找文字，直接给坐标
python3 ui.py click 330 303
python3 ui.py type "张三 hello"
python3 ui.py key ctrl+l
python3 ui.py scroll down 3
python3 ui.py region 100 200 400 300 # 只看局部并放大识别（小字用这个）
python3 ui.py win activate chromium
```


### 4.4 OCR 识别（ocr.py）

`look` 读的是控件自报的文字。遇到这几种就没辙：游戏和 Flutter 自绘界面、聊天记录截图、商品图上的文字、验证码、PDF。这时候才需要 OCR。

**为什么是 Tesseract**：PaddleOCR / RapidOCR / EasyOCR 全都依赖 onnxruntime 或 torch，这两个在 Android Bionic aarch64 上没有预编译 wheel，Termux 里根本装不上。Tesseract 是官方仓库里唯一能 `pkg install` 的成熟方案。

**装（手机）**：

```
pkg install -y tesseract python-pillow poppler
cd $PREFIX/share/tessdata
B=https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main
curl -fL -O $B/chi_sim.traineddata
curl -fL -O $B/chi_sim_vert.traineddata
curl -fL -O $B/eng.traineddata
chmod 644 *.traineddata
tesseract --list-langs          # 要看到 chi_sim
```

`chi_sim_vert` 看着多余，但少了它会一直报 `Failed loading language 'chi_sim_vert'`。

**自检**：

```
python3 ocr.py doctor
```

```
ocr.py 自检
----------------------------------------------------
tesseract : OK  5.5.0  (/data/data/com.termux/files/usr/bin/tesseract)
语言包    : chi_sim, eng, osd
中文      : OK
模型目录  : /data/data/com.termux/files/usr/share/tessdata/
中文模型  : chi_sim.traineddata  2.4 MB
Pillow    : OK  10.2.0  (JPEG/WebP/自动旋转)
pdftoppm  : OK  (PDF 输入)
----------------------------------------------------
可以用了：python3 ocr.py 截图.png
```

**四个用法覆盖全部场景**：

| 命令 | 用途 |
|---|---|
| `python3 ocr.py shot.png` | 纯文本，一行一句 |
| `python3 ocr.py shot.png --boxes` | 带坐标，能直接点 |
| `python3 ocr.py shot.png --json` | 给程序 / agent 用 |
| `python3 ocr.py doc.pdf --dpi 200` | PDF 逐页 |

```
$ python3 ocr.py shot.png --boxes
   42,   44   180x44     91.1  无线调试
   40,  120   304x32     95.2  使用配对码配对设备
   42,  178   445x27     92.5  IP地址和端口192.168.1.102:39549
   42,  240   166x32     96.6  已连接设备
```

坐标是**原图坐标**（哪怕内部放大过、裁剪过，也都换算回来了），可以直接喂给 `adui.py tap x y`。

**和 adui 连起来**——截屏、识别、点击，一条命令：

```
python3 adui.py ocr                          # 截屏 + OCR，输出「文字 (x,y)」
python3 adui.py ocr --crop 0,300,1080,900    # 只认中间一条，快且准
python3 adui.py ocr --keep a.png             # 顺便留截图
python3 adui.py ocr --json                   # 给 agent 解析
```

```
屏幕 1080x2340  OCR 识别到 6 行（截图 /tmp/adui_ocr.png）
[ 1] 无线调试                           ( 540,  120)   93
[ 2] 使用配对码配对设备                 ( 540,  310)   95
[ 3] IP地址和端口192.168.1.102:39549    ( 540,  430)   92
[ 4] 取消配对                           ( 540, 1800)   96

点击：python3 adui.py tap <x> <y>     例如 python3 adui.py tap 540 120
```

**实测效果**（1080×2400 合成截图，最差的那种：小字、深色模式、彩色气泡混在一起）：

| 场景 | 结果 |
|---|---|
| 白底黑字 UI | 8 行全对 |
| 深色模式 | 5 行全对（自动反色） |
| 低对比灰字 | 5 行全对（自动拉伸对比度） |
| 微信绿气泡 | 10 条消息全出，个别字有错 |
| 12px 小字 | 能认，但建议 `--crop` 出那一块单独识别 |

**两个真实的坑**，代码里已经处理，但你得知道为什么，出问题时才不慌：

**坑一：彩色气泡整段消失。** 微信绿气泡在灰度图里是 236，和白底 255 只差 19，可 tesseract 的版面分析会把这块颜色判成「图片区域」整块跳过——那些消息不是认错了，是根本没进识别。解法是把灰度换成 max(R,G,B)：绿色通道顶到 236≈白，色块消失，里面的黑字留下。`ocr.py` 检测到彩色像素超过 4% 会自动切换，不用你管。

**坑二：放大不等于更准。** 最初我给 1080 宽的截图放大 1.5 倍，结果比不放大还差：tesseract 对整幅图做行分割，放大后行高与字高比例变了，反而把行切碎。现在的规则是宽度 ≥1000 不放大，640–1000 放大 1.5 倍，更小的放大 2 倍。小字要放大就用 `--crop` 只截那一块，别整图放大。

**fast 还是 best 模型**：

| 模型 | 大小 | 特点 |
|---|---|---|
| fast（默认） | 2.4 MB | 快，多数截图够用；个别界面词会整行漏掉 |
| best | 13 MB | 慢约 2 倍，漏行明显少；但个别字反而更容易错 |

差异很具体：同一张深色设置页，fast 把「无线调试」整行丢了，best 认得出来；换一张白底聊天图，best 丢了「这么强，」三个字，fast 倒认对了。**没有绝对赢家——漏行了就换另一个试。**

装 best（放进 `~/.tessdata` 就自动优先使用，不用每次带参数）：

```
mkdir -p ~/.tessdata && cd ~/.tessdata
B=https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main
curl -fL -O $B/chi_sim.traineddata
curl -fL -O $B/eng.traineddata
chmod 644 *.traineddata

python3 ~/work/ocr.py shot.png      # 自动用 ~/.tessdata
```

> 要指定别的目录用 `--tessdata /path`，或设环境变量 `OCR_TESSDATA`。`doctor` 会打印当前到底用的哪个模型。

**什么时候别用 OCR**：界面能用 `look` 就用 `look`。uiautomator 拿到的是控件自报的文字，100% 准确、零延迟；OCR 是猜，永远有错字。它只用来兜底。


### 4.5 对 agent 说的原话

直接复制这几句，比自己摸索快得多。

**手机控屏**

```
你现在可以操作这台手机的屏幕，工具是 python3 adui.py，在 ~/work 下。
命令：look 看屏幕、tap-text 文字 点按钮、tap 序号、text 输入、key back/home/enter。
规矩：每次操作前先 look，操作完再 look 确认，不要凭记忆猜坐标。
如果报「没有可用的安卓设备」，先执行 adb connect <ip>:<端口>。

现在开始：打开设置，找到「显示」，把亮度调到最低。
```

**虚拟机控屏**

```
用 python3 ui.py 操作桌面。先 look 看屏幕上有什么文字和窗口，再按坐标点。
改完再 look 确认。不要连续盲点。
```

**逆向分析**

```
分析 ~/work 下的 xxx.apk：先 triage，再 apk，列出包名、版本、危险权限、
导出的 Activity/Service/Receiver，以及里面出现的所有 http 地址。
```


## 五、命令速查

| 我要… | 命令 |
|---|---|
| 启动界面 | `cd ~/work && python3 webchat.py` |
| 界面演示模式 | `python3 webchat.py --mock` |
| 换端口 | `python3 webchat.py --port 8800` |
| 启动终端版 | `python3 agent.py` |
| 连接手机 | `python3 adui.py scan`（自动找端口并连接） |
| 手机断了 / 连不上 | `python3 adui.py doctor`（自动排查并修复） |
| 识别屏幕文字 | `python3 adui.py ocr`（截图 + OCR + 坐标） |
| 识别图片 / PDF | `python3 ocr.py 文件` |
| OCR 自检 | `python3 ocr.py doctor` |
| 更新全部脚本 | `sh ~/work/update.sh` |
| 看是否连上 | `adb devices` |
| 断开 | `adb disconnect` |
| 看手机屏幕 | `python3 adui.py look` |
| 看桌面 | `DISPLAY=:0 python3 ui.py look` |
| 分析 APK | `python3 rev.py apk 目标.apk` |
| 防休眠 | `termux-wake-lock` |
| 急停 | `Ctrl+C` 或 `pkill -f adui.py` |


## 六、故障排查


### 6.1 常见症状对照表

按症状查，不用从头读。

| 症状 | 原因 | 解决 |
|---|---|---|
| `No command Python3 found` | Linux 区分大小写，`P` 不能大写 | 改成 `python3` |
| `Address already in use` | 端口被占 | `--port 8800` 换一个 |
| 浏览器「连接失败」 | 后端进程被系统杀了 | 回 Termux 重启；先 `termux-wake-lock` |
| `adb devices` 列表空 | 没 connect，或无线调试关了 | `python3 adui.py doctor` |
| `adb devices` 显示 `offline` | 本地 adb 服务状态脏了 | `adb kill-server` → `python3 adui.py scan` |
| 下载卡在 `Read error (Connection timed out)` | `raw.githubusercontent.com` 被拦 | 换 jsDelivr 或 ghfast 镜像（见第一章） |
| `unauthorized` | 手机上没点「允许」 | 看通知栏，点允许；不行就撤销授权重配对 |
| `protocol fault (couldn't read status message)` | **配对端口用错**，或端口已超时（2 分钟） | 分屏操作，用弹窗里那个端口，30 秒内完成 |
| `failed to connect` / `Connection refused` | 端口已失效（开关无线调试、开配对弹窗都会换端口） | `python3 adui.py scan` |
| `pair` 报 `arguments are required: code` | 端口写成了 `IP:端口` 却又漏了配对码 | `python3 adui.py pair IP:端口 6位码` |
| 配对报 `unknown command` | adb 版本太老 | `pkg upgrade android-tools` |
| `input tap` 没报错但没反应 | **小米的「USB 调试（安全设置）」没开** | 开发者选项里打开它（需登录小米账号+插卡） |
| `uiautomator dump` 连续失败 | 界面一直在动（动画/视频） | 工具已重试 4 次；回桌面或静止页面再试 |
| `look` 一个元素都没有 | 游戏/视频/Flutter 自绘界面 | `look --all` 看坐标盲点，或放弃该界面 |
| 中文输入报「还没配好」 | 没装 ADBKeyBoard | `python3 adui.py ime-install`（见 2.5） |
| `termux-clipboard-set` 卡几十秒 | 装了 termux-api 包但没装 Termux:API 应用 | 新版已跳过该检测，直接走 ime-install |
| `text` 说输入成功但框里没字 | 输入框没聚焦 | 先 `tap-text 搜索框` 再 `text`，或加 `--verify` 看结果 |
| `ui.py` 报 `DISPLAY` 为空 | 不在图形会话里 | `export DISPLAY=:0` |
| `ui.py` 认不出小字 | OCR 对 12~14px 字不灵 | `ui.py region x1 y1 x2 y2` 放大识别 |
| `rev.py` 报 Permission denied | 文件在被保护目录 | `cp` 到 `~/work` 再分析 |
| `write_file → path escapes work dir` | 路径护栏拦住了越界写入 | 改用 `run_shell` 配合 `tee` 写 |
| 重启后提示「缺少 DEEPSEEK_KEY」 | `export` 只对当前会话有效，重启就没了 | 写进 `~/.config/webchat/env`（见 4.1） |
| agent 跑十几步就停，像卡死 | 旧版 `MAX_TURNS` 默认 12，且撞上限不提示 | 换新版（默认 100，会提示）；更久用 `AGENT_MAX_TURNS=300` |
| OCR 一个字都认不出 | tesseract 或中文包没装 | `python3 ocr.py doctor` |
| OCR 整段文字消失 | 彩色背景被当成图片区域 | 已自动处理；仍丢就换 best 模型 |
| OCR 小字认不准 | 整图放大反而更差 | `--crop` 只截那一块再识别 |


### 6.2 无线调试断了怎么救

90% 的「连不上」只是端口变了，配对记录还在。按下面的顺序来，从便宜到贵，通常第 1 步就结束。

**① 一条命令先试**

```
cd ~/work && python3 adui.py doctor
```

它依次做四件事：查 adb 版本 → 看设备状态（含 `offline` / `unauthorized`）→ 重启本地 adb 服务 → 扫端口并连接。能自己修的当场修好；修不了会直接打印下一步该点哪里。

**② 关一次再开「无线调试」**

设置 → 开发者选项 → 无线调试，关掉再打开。端口会换新的，**配对记录不会掉**。然后重跑 `doctor`。

**③ 重新配对（只有配对记录丢了才需要）**

点「使用配对码配对设备」，趁弹窗开着，30 秒内执行：

```
python3 adui.py pair 127.0.0.1 <弹窗端口> <6位码>
```

配对成功会自动接着扫端口并连上，不用再抄主页面端口。

**④ 兜底：USB 线接电脑**

```
adb devices          # 电脑上能认到手机
adb tcpip 5555
# 拔线，回手机执行
python3 adui.py connect 127.0.0.1:5555
```

> **什么时候必须重新配对**：撤销过 USB 调试授权、恢复出厂、清除「设置」数据、在无线调试里点过「取消配对」。**哪些不需要**：重启手机、开关无线调试、换 WiFi、飞行模式、换 IP —— 配对密钥在 /data/misc/adb/adb_keys，跟网络无关。

顺带一个天然优势：Termux 和 adbd 跑在同一台手机上，走的是 `127.0.0.1`。所以路由器换 IP、换 WiFi、连热点全都不影响，真正会变的只有端口号 —— 这就是「断了先 scan / 先 doctor」的原因。


### 6.3 跑到一半不动了

先分清是「步数用完」还是「真的挂了」，两者表现很像，处理完全不同。

| 现象 | 判断 | 处理 |
|---|---|---|
| 输出停住，底部显示「N 步 · Xs」，没有报错 | 步数上限用完了 | 新版会明说「到单次上限就停了」，回一句「继续」接着跑 |
| 输出停住，底部显示「N 步 · Xs · 已达上限」 | 同上，且已确认撞的是上限 | 回「继续」，或加大上限重开 |
| 转圈不结束、没有任何新输出，超过 2 分钟 | 多半卡在某个工具上（adb 无响应、下载超时） | 聊天页按 Esc 或重启 webchat；先跑 `python3 adui.py doctor` 看手机 |
| 整页无响应、刷不出来 | webchat 进程死了 | 看终端有没有报错；重启 `python3 webchat.py` |

**为什么以前像卡死**：旧版 `MAX_TURNS` 默认 12，循环用完就 `break`，前端只更新了一行小字（`37 步 · 82s`），正文没有任何提示 —— 从用户角度看就是「它突然不说话了」。

**现在的行为**：

```
（已连续执行 100 步，到单次上限 100 步就停了。任务没完的话，回一句「继续」接着跑；
想一次跑更长：AGENT_MAX_TURNS=300 python3 webchat.py）
```

底部状态栏也会标出 `· 已达上限`，一眼能区分「正常结束」和「被截断」。

想永久改大，不用改代码，环境变量优先：

```
export AGENT_MAX_TURNS=300        # 写进 ~/.bashrc 就永久生效
python3 webchat.py
```

> 步数不是越大越好：每一步都是一次 API 调用，100 步的极端情况（模型反复试错）会烧掉可观的 token。日常 100 够用，只有批量处理文件、长时间扫屏这类任务才需要往上调。


## 七、每天开机后的三分钟

这套工具不会自启动，每次开机要手动拉起来。三条命令，或者用一个脚本。

```
# 1. 防休眠
termux-wake-lock

# 2. 连手机（端口每次重启可能变，去设置里看主页面）
adb connect 192.168.1.102:39549

# 3. 启动界面
cd ~/work && python3 webchat.py
```

嫌麻烦就存成 `~/up.sh`，以后一句 `bash ~/up.sh`：

```
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd ~/work || exit 1

# 没连上就扫端口（Termux 的 adb 没有 mDNS，只能用扫的）
if ! adb devices | grep -qw device; then
  python3 adui.py scan || echo "扫不到端口：设置→开发者选项→无线调试 打开后重试"
fi

adb devices
exec python3 webchat.py
```

**首次使用先加执行权限**

```
chmod +x ~/up.sh && bash ~/up.sh
```

> `adb mdns services` 依赖 mDNS 广播，Termux 的 `android-tools` 根本没编译这块，一定报 `not supported`。所以开机自连脚本里用 `scan`，不要用 `ports`。


## 八、安全边界

这套工具的能力已经到了「能替你操作手机」的程度，代价是风险也是真实的。

> ⚠️ **`adui.py` 拥有 adb shell 权限，等于能点屏幕上任何按钮**：发微信、转账、卸载应用、同意隐私授权——都会真实发生，没有撤销。第一次请用「设置 → 显示 → 亮度」这类改得回来的任务试手，不要一上来对着微信和支付类应用。

| 做法 | 原因 |
|---|---|
| 工作目录固定 `~/work` | agent 的路径护栏只保护这里，越界写入会被拒 |
| **不要**随手 `termux-setup-storage` | 它会把整个 `/sdcard` 挂进来，agent 从此能删你的相册 |
| API key 写 `~/.bashrc` 要心里有数 | 明文存储，任何能读这个文件的东西都能看到 |
| `--host 0.0.0.0` 别乱加 | 等于把命令执行权限开给同网段所有设备，默认只听 127.0.0.1 |
| 重要操作前先 `look` | 它可能认错文字、点错位置，确认一步再做下一步 |
| 会话库存着全部历史 | `~/.local/share/webchat/sessions.db` 是你在这台机器上干过的所有事的记录，默认没有密码，别把端口开到公网 |

**急停方式**：终端里 `Ctrl+C`，或另开一个 Termux 窗口 `pkill -f adui.py`、`pkill -f webchat.py`。


## 九、附录：两套环境的能力对照

| 能力 | 手机（Termux） | 虚拟机（Alpine） |
|---|---|---|
| 聊天界面 | ✅ 浏览器 | ✅ 浏览器 |
| 执行 shell | ✅ 无 root，限应用沙箱 | ✅ root |
| 逆向分析 | ✅ 静态侦察 | ✅ 静态侦察 |
| 操控屏幕 | ✅ adui.py（uiautomator） | ✅ ui.py（xdotool） |
| 看屏幕文字 | ✅ 控件树直接给，准确 | ⚠️ OCR 识别，小字要放大 |
| 点纯图标按钮 | ✅ 有 content-desc 就能定位 | ❌ 没文字就找不到 |
| 反编译 Java | ❌ 装不下 JVM | ⚠️ 可装 jadx，但很慢 |
| 动态调试 Hook | ❌ 无 root | ⚠️ 需另外配置 |
| 速度 | 原生 ARM64，快 | QEMU 翻译，慢 3~10 倍 |

**推荐分工**：日常对话、操控手机 → 手机；批量分析、需要 root 或完整 Linux → 虚拟机。两个环境共享同一套 `rev.py`，分析结果可以直接对照。
