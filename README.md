# 手机 Agent 工具集

在 **Termux（安卓手机）** 和 **Linux 虚拟机** 上跑一个自己的 agent：能聊天、能读代码、能逆向看包，也能直接操作屏幕。

全部脚本只用 Python 标准库，装好 Python 就能跑，不需要 pip install。
OCR 依赖系统的 Tesseract（`pkg install tesseract`），Pillow 可选。

## 文件

| 文件 | 干什么 | 跑在哪 |
|---|---|---|
| `webchat.py` | 浏览器聊天界面：多会话、跨重启记忆、三栏布局、运行详情、换模型、压缩、分支、清理 | 手机 / 虚拟机 |
| `static/` | 界面本体（`app.html` / `app.css` / `app.js`），`webchat.py` 启动时读取 | 手机 / 虚拟机 |
| `rev.py` | 逆向侦察：ELF / PE / DEX / APK 结构、字符串、熵、carve | 手机 / 虚拟机 |
| `adui.py` | 安卓控屏：adb + uiautomator，看屏幕、点按钮、输中文、截屏 OCR | 手机 |
| `ocr.py` | 本地 OCR：图片 / PDF → 文字 + 坐标，彩色背景和深色模式都能认 | 手机 / 虚拟机 |
| `ui.py` | Linux 桌面控屏：xdotool + OCR | 虚拟机 |
| `patch_ui.py` | 把 `ui` 工具注入已有的 `agent.py` | 虚拟机 |
| `START.html` | **零基础版手册**：从装 Termux 开始，含 Python 环境搭建 | — |
| `MANUAL.html` | 速查版手册（单文件，手机浏览器直接打开） | — |
| `MANUAL.md` | 速查版的 Markdown 版 | — |
| `update.sh` | 一键更新全部脚本：先下临时文件、校验语法、失败不覆盖 | 手机 / 虚拟机 |

## 更新

```bash
curl -fL -o update.sh.part https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main/update.sh
mv update.sh.part update.sh && chmod +x update.sh
sh update.sh
```

之后每次只要 `sh update.sh`。**从 v1 升到 v2 要多一步**（老版本不知道有 `static/` 目录）：

```bash
sh update.sh --self    # 先换更新器
sh update.sh           # 再拉全部文件（含 static/ 三个）
```

更新器本身也没变过的话，直接 `sh update.sh` 就行。它先下到临时文件、比对内容、对 `.py` 做语法预检，
任一步不过就保留原文件；镜像不通会自动换。`--list` 只看版本差，`sh update.sh ocr.py` 只更一个。

## 30 秒开始

```bash
# 国内直连 github.com 常超时，走镜像前缀（原地址整段接在后面）
git clone https://ghfast.top/https://github.com/dengxiancao/android-agent-kit ~/work-kit
cd ~/work-kit
python3 webchat.py --mock        # 不用 API key，先看界面能不能起来
```

真实使用：

```bash
export OPENAI_API_KEY=sk-xxx      # 或你自己的 endpoint
python3 webchat.py --port 8080
```

浏览器打开 `http://127.0.0.1:8080`。

左侧是会话列表，聊过的都在，关掉终端、重启虚拟机再打开还是那些对话。
每条回复下面有步数 / 耗时 / token，右栏能看到上下文占用和工具时间线。
手机上侧栏收成抽屉（左上角 ☰），运行详情是底部弹层（顶部图表按钮）。

### v2.1 / v2.2 加了什么

| 能力 | 怎么用 |
|---|---|
| **换模型** | 点顶部的模型名（手机上点输入框左下角的模型），会列出 `WEBCHAT_MODELS` 里的模型；选中后写进这个会话，下一轮生效 |
| **重新生成** | 悬停最后一条回复 → ↻。会砍掉最后一轮再重跑，不是追加 |
| **分支** | 悬停任意回复 → ⑂。从这条回复分叉出一个新会话，原会话不动，适合「换个思路再问一遍」 |
| **上下文压缩** | 估算 token 超过 `AGENT_CTX_LIMIT`（默认 48000）时自动把老消息揉成摘要，界面上有一条「上下文已压缩」的分隔线；右栏也能手动点「压缩上下文」。原始消息不删，往上翻还在 |
| **库清理** | 左下角 🗑 → 看占用、预览、按天数删掉没动过的会话，顺手 `VACUUM` 收空间。置顶的不会删 |
| **网络容错** | 接口抖动（DNS 失败、连接重置、5xx、429）自动重试 2 次；真失败时给一句能照做的中文提示，并在消息流里留一个「重试这一轮」按钮（v2.2） |
| **访问口令** | `--host 0.0.0.0` 时自动生成，存在 `~/.config/webchat/token`。本机浏览器不用口令；局域网设备第一次要打开启动时打印的 `?k=` 地址，之后靠 cookie 记住。`--no-auth` 可关 |

```bash
# 想加自己的模型（逗号分隔）
WEBCHAT_MODELS="deepseek-chat,deepseek-reasoner" python3 webchat.py

# 压缩阈值调小一点，长会话更省 token
AGENT_CTX_LIMIT=24000 AGENT_CTX_KEEP=8 python3 webchat.py
```

> `deepseek-reasoner` 对 function calling 的支持随版本变化，纯问答没问题；要它跑工具（看屏幕、改文件）
> 建议留在 `deepseek-chat`，否则可能收到「模型不支持 tools」的报错。

> **单条消息最多跑 100 步**（模型 → 工具 → 模型 算一步）。到上限会明确提示，回一句「继续」接着跑；
> 想调大用环境变量 `AGENT_MAX_TURNS=300 python3 webchat.py`，不用改代码。

`export` 只对当前会话有效，重启就没了。想一劳永逸，把配置写进文件：

```bash
mkdir -p ~/.config/webchat
cat > ~/.config/webchat/env <<'EOF'
DEEPSEEK_KEY=sk-xxx
AGENT_WORK=/root/work-kit
HOST=0.0.0.0
EOF
chmod 600 ~/.config/webchat/env
```

`webchat.py` 启动时自动读取（环境变量优先级更高）。文件里可写 `DEEPSEEK_KEY` / `AGENT_WORK` /
`HOST` / `PORT` / `AGENT_MAX_TURNS` / `WEBCHAT_MODELS` / `AGENT_CTX_LIMIT` / `WEBCHAT_TOKEN`；
启动信息会显示 `配置 ~/.config/webchat/env` 确认读到了。

> 完整流程（Termux 环境、API 配置、ADB 无线调试配对、中文输入、保活、开机自启、断线补救）见手册，
> 里面每一步都有预期输出和失败对照表。**建议先读手册再动手**，尤其是 ADB 那一节。
>
> 在线看：
> - 没接触过命令行：<https://dengxiancao.github.io/android-agent-kit/START.html>
> - 已经会用终端：<https://dengxiancao.github.io/android-agent-kit/MANUAL.html>
>
> 两份都是单文件，手机浏览器直接打开，排版自适应。

## 对话记在哪

会话和消息存在一个 SQLite 文件里：

```
~/.local/share/webchat/sessions.db
```

- **备份 / 换机**：`cp` 这一个文件走就行，消息、标题、置顶全在里面。
- **清空历史**：删掉它，下次启动会重建。
- **换位置**：`WEBCHAT_DB=/path/to/my.db python3 webchat.py`
- **不要落盘**：`python3 webchat.py --no-db`，退回早先的单会话内存模式。

进程被杀、断电、虚拟机重启都不会丢正在跑的对话：每接一条消息就写库，
崩在半路的那一轮会在下次打开时补一条「任务被中断」，点「继续」能接着跑。

## 手机控屏速查

```bash
python3 adui.py doctor        # 断了/连不上：自动重启 adb 服务 + 扫端口 + 连接
python3 adui.py scan          # 扫无线调试端口并自动连接（Termux 的 adb 没有 mDNS，只能扫）
python3 adui.py info          # 确认设备 / 分辨率 / 前台应用
python3 adui.py look          # 看屏幕上有哪些文字和按钮，带序号
python3 adui.py tap-text 设置  # 点文字
python3 adui.py text "你好"    # 输入中文（需先 ime-install）
python3 adui.py key back
```

## OCR

`look` 读的是控件文字，遇到 Canvas / 游戏 / 图片里的字就没了。这时用 `ocr.py`：

```bash
pkg install -y tesseract python-pillow poppler   # Termux
python3 ocr.py doctor                            # 自检，会告诉你缺什么、怎么装
python3 ocr.py shot.png                          # 纯文本
python3 ocr.py shot.png --boxes                  # 带坐标，能直接点
python3 adui.py ocr                              # 截屏 + 识别 + 给出可点坐标
```

彩色背景（微信绿气泡）默认会被 tesseract 当成图片整块跳过，`ocr.py` 会自动改用 max(R,G,B)
灰度规避；深色模式自动反色；1080 宽的截图默认不放大（放大反而更差）。

## 安全边界

这些脚本的能力是「替你操作机器」，风险也是真的：

- `adui.py` 拥有 adb shell 权限，能点任何按钮、读任何界面 —— 包括支付确认页。
- `webchat.py --host 0.0.0.0` 会把命令执行权开给同一网段的设备。v2.1 起这种情况会自动启用访问口令
  （`~/.config/webchat/token`，启动时打印带 `?k=` 的地址），本机访问免口令。但口令只是防误闯，
  **不是加密**：流量仍是明文 HTTP。真要暴露到公网，请套一层 HTTPS 反代。
- 会话库 `sessions.db` 等于一份「你在这台机器上干过的所有事」的记录，口令只挡 HTTP 入口，
  拿到文件的人照样能读。别把它同步到公开网盘。
- `termux-setup-storage` 会把整个 `/sdcard` 暴露给脚本。
- 不要把 `OPENAI_API_KEY` 提交进仓库，也不要贴到聊天里。

## 许可

未附许可协议，代码归作者所有。要复用请先联系。
