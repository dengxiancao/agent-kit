# 手机 Agent 工具集

在 **Termux（安卓手机）** 和 **Linux 虚拟机** 上跑一个自己的 agent：能聊天、能读代码、能逆向看包，也能直接操作屏幕。

全部脚本只用 Python 标准库，装好 Python 就能跑，不需要 pip install。
OCR 依赖系统的 Tesseract（`pkg install tesseract`），Pillow 可选。

## 文件

| 文件 | 干什么 | 跑在哪 |
|---|---|---|
| `webchat.py` | 浏览器里的聊天界面，流式输出 + 工具调用卡片 | 手机 / 虚拟机 |
| `rev.py` | 逆向侦察：ELF / PE / DEX / APK 结构、字符串、熵、carve | 手机 / 虚拟机 |
| `adui.py` | 安卓控屏：adb + uiautomator，看屏幕、点按钮、输中文、截屏 OCR | 手机 |
| `ocr.py` | 本地 OCR：图片 / PDF → 文字 + 坐标，彩色背景和深色模式都能认 | 手机 / 虚拟机 |
| `ui.py` | Linux 桌面控屏：xdotool + OCR | 虚拟机 |
| `patch_ui.py` | 把 `ui` 工具注入已有的 `agent.py` | 虚拟机 |
| `MANUAL.html` | 完整部署手册（单文件，手机浏览器直接打开） | — |
| `MANUAL.md` | 同一份手册的 Markdown 版 | — |
| `update.sh` | 一键更新全部脚本：先下临时文件、校验语法、失败不覆盖 | 手机 / 虚拟机 |

## 更新

```bash
curl -fL -o update.sh.part https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/android-agent-kit/main/update.sh
mv update.sh.part update.sh && chmod +x update.sh
sh update.sh
```

之后每次只要 `sh update.sh`。它先下到临时文件、比对内容、对 `.py` 做语法预检，
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
`HOST` / `PORT` / `AGENT_MAX_TURNS`；启动信息会显示 `配置 ~/.config/webchat/env` 确认读到了。

> 完整流程（Termux 环境、API 配置、ADB 无线调试配对、中文输入、保活、开机自启、断线补救）见手册，
> 里面每一步都有预期输出和失败对照表。**建议先读手册再动手**，尤其是 ADB 那一节。
>
> 在线看：<https://dengxiancao.github.io/android-agent-kit/MANUAL.html> （手机浏览器直接打开，排版自适应）

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
- `webchat.py --host 0.0.0.0` 会把命令执行权开给同一网段的任何设备。
- `termux-setup-storage` 会把整个 `/sdcard` 暴露给脚本。
- 不要把 `OPENAI_API_KEY` 提交进仓库，也不要贴到聊天里。

## 许可

未附许可协议，代码归作者所有。要复用请先联系。
