# 手机 Agent 工具集

> 部署与使用手册

**2026.11.18** · 适用于 Termux（Android 11+）与 Alpine Linux 虚拟机

这套东西的目标：在手机上跑一个**能真正动手**的 AI——聊天、执行命令、分析 APK、操控手机屏幕。六个文件，两块环境，彼此独立，坏一个不影响其他。


## 零、先看这张图

很多人第一次装完会混淆：`ui.py` 和 `adui.py` 都是操控屏幕，为什么是两个文件？因为它们操控的是**两种完全不同的屏幕**，技术路线不同，不能合并。

| 文件 | 运行环境 | 操控什么 | 技术路线 |
|---|---|---|---|
| `agent.py` | 手机 + 虚拟机 | ——（对话入口） | DeepSeek function calling |
| `webchat.py` | 手机 + 虚拟机 | ——（图形界面） | http.server + 内嵌页面 |
| `rev.py` | 手机 + 虚拟机 | 文件（APK/ELF/PE） | 纯标准库二进制解析 |
| `adui.py` | **手机** | **安卓屏幕** | ADB + uiautomator |
| `ui.py` | **虚拟机** | **X11 桌面** | xdotool + 截图 OCR |
| `patch_ui.py` | 虚拟机 | ——（补丁脚本） | 改 agent.py 加工具 |

> 一句话记住：**手机用 adui，虚拟机用 ui。** 装错环境不会报错，只会一直说“找不到 adb”或“DISPLAY 为空”。


## 一、文件清单

全部文件都在仓库 github.com/dengxiancao/android-agent-kit 的根目录，下面的 raw 链接可以直接 wget，也可以直接 git clone。

| 文件 | 字节数 | raw 路径 | 装在哪 |
|---|---|---|---|
| `rev.py` | 28616 | `/main/rev.py` | 手机 + 虚拟机 |
| `webchat.py` | 35945 | `/main/webchat.py` | 手机 + 虚拟机 |
| `adui.py` | 40248 | `/main/adui.py` | 手机 |
| `ui.py` | 16329 | `/main/ui.py` | 虚拟机 |
| `patch_ui.py` | 2708 | `/main/patch_ui.py` | 虚拟机 |
| `MANUAL.html` | — | `/main/MANUAL.html` | 这份手册 |

前缀统一是 `https://raw.githubusercontent.com/dengxiancao/android-agent-kit`，表里只写后半段，免得撑破屏幕。**大小不对就是没下完，重下即可。**

**手机端：下载三个**

```
BASE=https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main
cd ~/work
wget -O rev.py     $BASE/rev.py
wget -O webchat.py $BASE/webchat.py
wget -O adui.py    $BASE/adui.py
wc -c rev.py webchat.py adui.py
```

**虚拟机端：下载四个**

```
BASE=https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main
cd ~/work
wget -O rev.py      $BASE/rev.py
wget -O webchat.py  $BASE/webchat.py
wget -O ui.py       $BASE/ui.py
wget -O patch_ui.py $BASE/patch_ui.py
wc -c rev.py webchat.py ui.py patch_ui.py
```

预期输出（顺序对应上面）：

```
 28616 rev.py
 35945 webchat.py
 40248 adui.py
 16329 ui.py
  2708 patch_ui.py
```

懒得一个个下，直接整仓克隆（Termux 里要先 `pkg install git`）：

```
git clone https://github.com/dengxiancao/android-agent-kit ~/work-kit
```

> 仓库是**长期地址**，不会再像临时粘贴站那样过期。改完代码 `git commit` 回自己的仓库，换手机也不用重找链接。

仍然建议定期备份：`tar czf ~/backup.tgz ~/work`。


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

见第一章。手机端只需要 `rev.py`、`webchat.py`、`adui.py` 三个。


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

| 操作 | 位置 | 效果 |
|---|---|---|
| 发消息 | 底部输入框，点 ↑ 或回车 | 回车发送，Shift+回车换行 |
| 看工具执行细节 | 点灰色卡片（如 `shell`） | 展开完整输出与耗时 |
| 新对话 | 右上角 ＋ | 清空上下文 |
| 看状态 | 顶部圆点 | 绿=空闲，蓝脉冲=运行中 |
| 看耗时 | 顶部右侧 | `2 步 · 3.4s` |

**工具卡片是核心。** agent 每执行一次命令就弹一张卡，它真正做到什么，看卡片，不要只看它的自述。


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


### 4.4 对 agent 说的原话

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
| 看是否连上 | `adb devices` |
| 断开 | `adb disconnect` |
| 看手机屏幕 | `python3 adui.py look` |
| 看桌面 | `DISPLAY=:0 python3 ui.py look` |
| 分析 APK | `python3 rev.py apk 目标.apk` |
| 防休眠 | `termux-wake-lock` |
| 急停 | `Ctrl+C` 或 `pkill -f adui.py` |


## 六、故障排查

按症状查，不用从头读。

| 症状 | 原因 | 解决 |
|---|---|---|
| `No command Python3 found` | Linux 区分大小写，`P` 不能大写 | 改成 `python3` |
| `Address already in use` | 端口被占 | `--port 8800` 换一个 |
| 浏览器「连接失败」 | 后端进程被系统杀了 | 回 Termux 重启；先 `termux-wake-lock` |
| `adb devices` 列表空 | 没 connect，或无线调试关了 | 重新打开无线调试 → `adb connect` |
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
| agent 12 轮就停 | `MAX_TURNS` 默认 12 | `export AGENT_MAX_TURNS=60` 写进 `.bashrc` |


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
