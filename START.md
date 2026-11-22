# 从零开始：在手机上装一个能自己动手的 AI 助手

<sub>零基础版 · 2026.11.19 · 全程约 40 分钟</sub>

这份文档假设你**什么都不会**：没用过 Linux，不知道 Python 是什么，看到 `pkg install` 这种命令不知道在干什么。

所以它很啰嗦。每一步都写清楚四件事：

- **要你做什么**（照抄那一行）
- **这行命令到底在干什么**（用大白话）
- **成功长什么样**（你应该看到什么字）
- **没成功怎么办**（最常见的三种错，各自怎么修）

已经会 Linux 的人不用看这份，去看 `MANUAL.html`，那是速查版。

> [!NOTE] 全程只用手机，不需要电脑。有电脑的话第 8 章讲怎么在电脑上装第二份。

### 读完你能得到什么

一个在手机里跑的东西，你打字跟它说话，它自己去执行命令、看文件、点屏幕、识别图片，然后把结果告诉你。

它住在你自己的手机里，不经过任何第三方服务器，除了调用 AI 模型那一下。

---

---

## 第 0 章 先搞清楚这是什么东西

### 0.1 一句话

**它把你的话翻译成一串命令，在你手机上执行，再把结果说给你听。**

你说「看看 download 目录里有什么」，它就去执行 `ls ~/download`，然后把输出整理成人话回给你。

和普通 AI 聊天框的区别只有一个：**它真的能动手**。普通 AI 只能告诉你「你可以执行 ls 命令」，这个会直接执行。

### 0.2 它能干什么

下面这些是真实能跑通的，不是演示：

| 你说 | 它做 |
|---|---|
| 「看看我手机还剩多少空间」 | 执行 `df -h`，告诉你哪个分区快满了 |
| 「download 里有个 apk，帮我看看要哪些权限」 | 解析 APK，列出危险权限和用途 |
| 「打开微信，给张三发个消息说我在路上」 | 通过 ADB 点开应用、找到联系人、输入文字、点发送 |
| 「这张截图里写了什么」 | 截图 + OCR，把文字和坐标都给你 |
| 「把这个 PDF 每页的文字提出来，存成 txt」 | 逐页 OCR，写文件 |

它还能组合：你说「去设置里把深色模式打开」，它会先看当前屏幕有什么，再点「显示」，再点「深色」，每步确认一次。

### 0.3 它不能干什么

说清楚边界，省得你怀疑自己装错了：

| 做不到 | 原因 |
|---|---|
| 不解锁手机就能操作 | ADB 需要在开发者选项里授权 |
| 操作非 Android 手机（iPhone） | ADB 只对 Android 有效 |
| 保证每次都点对 | 它靠识别屏幕文字定位，界面改版就可能点偏 |
| 离线使用 | 每句话都要调一次 AI 模型，需要联网 |
| 免费无限用 | 按 token 计费，充 10 元能用挺久，但不是零成本 |
| 装成 App 点图标启动 | 它是命令行程序，靠浏览器界面操作 |

### 0.4 你需要准备什么

| 项目 | 要求 | 说明 |
|---|---|---|
| 手机 | Android 11 或更高 | 无线调试是 Android 11 才有的功能。10 及以下要先用电脑 USB 连一次 |
| 存储 | 留 500 MB | Termux + Python + 依赖大约占 300 MB |
| 网络 | 能上网 | 装依赖、调模型都要 |
| 钱 | 充 10 元 | DeepSeek 按量计费，正常聊天一个月用不完 |
| 时间 | 首次 40 分钟 | 熟悉之后每天启动只要 10 秒 |

Android 版本怎么看：设置 → 关于手机 → Android 版本。

### 0.5 全程路线图

分四段，每段结束都有一个能验证的成果。**卡住了就停在那一段，不要往下走**，后面的步骤都依赖前面的。

| 阶段 | 做什么 | 完成后你能 |
|---|---|---|
| 第一段（第 1-3 章） | 装 Termux + Python + 程序 | 在手机上跑起命令行工具 |
| 第二段（第 4-5 章） | 申请 key + 启动界面 | 在浏览器里跟它聊天 |
| 第三段（第 6 章） | 配对 ADB | 让它点你的屏幕 |
| 第四段（第 7 章） | 装 OCR | 让它读图片里的字 |

只想要聊天功能的话，做到第二段就够了。

### 0.6 术语表（看不懂就回来查）

| 词 | 大白话 |
|---|---|
| **命令行** | 不打字用鼠标点，而是打一行字让电脑做事。像跟机器发微信 |
| **终端 (Terminal)** | 那个黑底白字、能打命令的窗口 |
| **Termux** | 安卓上的一个 App，装上就有一个终端，还能装 Linux 软件 |
| **包 (package)** | 一个装好的软件。`pkg install` 就是「给我装这个软件」 |
| **Python** | 一种编程语言，也是一个程序。你得先有它，才能跑 `.py` 文件 |
| **脚本 (script)** | 一个 `.py` 结尾的文本文件，里面是让 Python 执行的指令 |
| **路径 (path)** | 文件的位置。`~/work/rev.py` 就是「家目录下 work 文件夹里的 rev.py」 |
| **`~`** | 代表你的家目录。Termux 里是 `/data/data/com.termux/files/home` |
| **API key** | 一串密码，证明「这次调用是我付的钱」。形如 `sk-xxxxx` |
| **token** | AI 计费单位，大约 1 个汉字算 1 到 2 个 token |
| **ADB** | Android Debug Bridge，安卓的官方调试通道，能模拟点击和滑动 |
| **端口 (port)** | 一台机器上有很多服务，端口是门牌号。我们的界面在 8765 号门 |

---

## 第 1 章 装 Termux

### 1.1 它是什么

Termux 是一个安卓 App，但打开之后不是图形界面，而是一个**终端**——黑底白字，等你在光标处打命令。

它的价值在于：它自带一整套 Linux 工具（`ls`、`cat`、`curl`、`python`……），装完相当于在手机里塞了一台小电脑，而且不需要 root。

### 1.2 从哪里下载（这里容易装错，看清楚）

**不要从华为应用市场、小米应用商店、应用宝下载。** 那些版本大多停留在 2020 年，目标 API 版本太低，安卓 12 以上直接装不上，或者装上了 `pkg` 命令一跑就报错。

只用下面两个来源之一：

| 来源 | 地址 | 说明 |
|---|---|---|
| F-Droid（推荐） | `f-droid.org/packages/com.termux` | 开源应用商店，页面往下拉有「下载 APK」 |
| GitHub Releases | `github.com/termux/termux-app/releases` | 找文件名里带 `universal` 的那个（形如 `termux-app_v0.118.x-universal.apk`），它适配所有机型 |

下载完点开 APK，系统会提示「未知来源应用」，允许一次即可。装完桌面会出现一个黑底 `>_` 图标的 App。

> [!WARN] 如果你之前装过应用商店版本，**先卸载再装**。两个版本签名不同，覆盖安装会失败，而且旧版本残留的配置会让新版本行为诡异。

### 1.3 第一次打开

点图标进去，你会看到类似这样的一屏：

```
Welcome to Termux!

Docs:       https://termux.dev/docs
Donate:     https://termux.dev/donate
Community:  https://termux.dev/community

Working with packages:
 - Search:  pkg search <query>
 - Install: pkg install <package>
 - Upgrade: pkg upgrade

~
$
```

最后那个 `$` 就是「等你输入」的意思。光标在那儿闪。

**这时候不要急着打命令**，先花两分钟认识键盘。

### 1.4 认识这个界面

手机上没有实体键盘，Termux 的输入方式和普通 App 不一样：

| 你想做 | 怎么做 |
|---|---|
| 输入命令 | 直接点屏幕下方弹出的输入法，和平常打字一样 |
| **粘贴** | 长按屏幕空白处 → 弹出菜单选「Paste」。**不要去点输入法上的粘贴，经常无效** |
| 复制屏幕上的字 | 长按要复制的文字，拖动选择范围 → 点「Copy」 |
| 打出 `Ctrl` 组合键 | 音量减 + 字母键。比如 `Ctrl+C` 就是音量减 + C |
| 上下翻看历史输出 | 手指在屏幕上上下滑 |
| 调出命令历史的上一行 | 音量加 + 方向键（有些机型没反应，直接用 ↑ 更稳） |
| 切换成英文输入法 | 命令必须用英文符号，中文输入法会把 `"` 变成 `”`，导致报错 |

> [!WARN] 这一条踩过的人最多：**命令里的引号、括号、斜杠必须是英文半角**。中文输入法下打出来的 `“”` 和 `（）` 会让命令直接失败，报错信息还很难懂。输入命令前先把输入法切到英文。

**放大字号**（可选，眼睛累的话）：双指在屏幕上捏合放大，和看图片一样。这只影响显示，不影响命令。

### 1.5 必做的三条设置

按顺序执行，一条一条来，等上一条跑完再打下一条。

#### 第一条：换成国内镜像源

```
termux-change-repo
```

**这条命令在干什么**：打开一个文字界面的选择菜单，把「去哪里下载软件」从国外服务器改成国内镜像，下载速度能从 10 KB/s 变成几 MB/s。

执行后会看到这样的选择界面：

```
[*] Mirror groups
[ ] Mirror

< OK >   < Cancel >
```

操作方式**反直觉**，注意看：

1. 用**方向键**（屏幕键盘上的上下箭头）把光标移到 `Mirror groups`
2. 按**回车**（输入法上的回车键，不是屏幕上的换行）
3. 进到下一屏，列出 `Grimler`、`Tsinghua`、`USTC` 等，选 `Tsinghua`（清华）或 `USTC`（中科大）
4. 再按回车确认
5. 出现 `< OK >` 时按回车退出

成功的话不会打印什么，直接回到 `$` 提示符。

> [!NOTE] 这步也可以跳过。跳过的话后面装软件会很慢，但不会失败。网速本来就快（比如连了 WiFi 且能直连国外）就不用改。

#### 第二条：更新软件列表

```
pkg update
```

**这条命令在干什么**：去服务器拉一份「现在有哪些软件、各自什么版本」的清单。它**不装任何东西**，只是刷新目录。

跑起来会刷很多行，中间可能停下来问你：

```
Do you want to continue? [Y/n]
```

打 `y` 然后回车。

**成功的样子**是最后回到 `$`，中间没有大片红色 `E:` 开头的错误。

**失败怎么办**：

| 报错 | 原因 | 怎么修 |
|---|---|---|
| `Unable to locate package` | 源没配好 | 重跑 `termux-change-repo`，选清华 |
| `Some index files failed to download` | 网络断了 | 换个网（WiFi 换流量）重跑 |
| `E: Repository ... is not signed` | 源配置坏了 | 执行 `rm -rf /data/data/com.termux/files/usr/var/lib/apt/lists/*` 再 `pkg update` |
| 卡在 `Reading package lists...` 很久 | 正常，在解压 | 等 1-2 分钟 |

#### 第三条：防止后台被杀

```
termux-wake-lock
```

**这条命令在干什么**：告诉安卓系统「别把我这个 App 睡死，我还在干活」。不执行的话，你一切换到别的 App，Termux 就被系统冻结，正在跑的任务直接中断。

执行成功没有任何输出，回到 `$`。

还要去系统设置里给它开绿灯（**这步不能省，小米/华为/OPPO 尤其严**）：

| 品牌 | 路径 |
|---|---|
| 小米 / Redmi | 设置 → 应用设置 → 应用管理 → Termux → **省电策略**选「无限制」；同页 → **自启动**打开 |
| 华为 / 荣耀 | 设置 → 应用 → 应用启动管理 → Termux → 关掉「自动管理」，手动勾选三项允许 |
| OPPO / 一加 | 设置 → 电池 → 应用耗电管理 → Termux → 允许「后台运行」 |
| vivo | 设置 → 电池 → 后台耗电管理 → Termux → 允许后台高耗电 |
| 三星 | 设置 → 电池 → 后台使用限制 → 从「睡眠应用」里移除 Termux |

> [!WARN] `termux-wake-lock` **每次重启手机都要重新执行一次**。它不是永久设置，是一个临时锁。嫌麻烦可以把它写进启动脚本，但新手先手动执行。

### 1.6 检查点

到这里，Termux 应该满足：

- 输入 `pkg update` 能正常跑完，不报红
- 输入 `termux-wake-lock` 没反应（没反应就是对的）
- 切到微信再切回来，Termux 还在原来的位置，没有重新加载

三条都满足，进第 2 章。

---

## 第 2 章 装 Python 环境

这一章是重点。Python 装不好，后面全部白搭。

### 2.1 Python 是什么，为什么必须装

**大白话**：`rev.py`、`webchat.py` 这些文件不是能直接双击运行的程序，它们是一堆**给 Python 看的指令**。就像一份菜谱，得有厨师才能变成菜。

Python 就是那个厨师。没装它，你输入 `python3 webchat.py` 只会得到「command not found」。

它有两部分：

| 部件 | 作用 | 怎么验证 |
|---|---|---|
| **解释器** `python3` | 读 `.py` 文件并执行 | `python3 --version` |
| **包管理器** `pip` | 给 Python 装第三方库 | `pip --version` |

我们这个项目**只用标准库**，理论上不需要 pip 装任何东西。但 OCR 那一章要装 `pillow`（处理图片），所以 pip 也得能用。

### 2.2 装解释器和 pip

```
pkg install -y python
```

**这条命令在干什么**：从镜像源下载 Python 3 的解释器，顺带把 `pip` 一起装上（Termux 的 python 包自带 pip）。`-y` 表示「所有问我要不要确认的地方，一律回答 yes」，省得你一路打 y。

会看到类似这样的过程：

```
Testing the available space...
Building dependency tree...
The following NEW packages will be installed:
  python
...
Unpacking python (3.12.x) ...
Setting up python (3.12.x) ...
```

**成功的样子**：最后回到 `$`，没有 `E:` 开头的红字。

**失败怎么办**：

| 报错 | 原因 | 怎么修 |
|---|---|---|
| `E: Unable to locate package python` | 软件列表没更新 | 先 `pkg update`，再重试 |
| `E: Sub-process ... returned an error code (1)` | 上次没装干净 | `pkg install -f python` 修复依赖 |
| `No space left on device` | 存储满了 | `df -h` 看哪个分区满，清点空间再来 |
| 卡在 `Unpacking` 一动不动 | 下载中断 | Ctrl+C（音量减+C）中断，重跑同一条命令，它会接着下 |

### 2.3 验证

分两条命令，逐条执行：

```
python3 --version
```

应该看到：

```
Python 3.12.x
```

版本号 **3.8 以上就行**，Termux 现在默认给 3.12。数字不一样没关系，只要不低于 3.8。

接着：

```
pip --version
```

应该看到类似：

```
pip 24.x from /data/data/com.termux/files/usr/lib/python3.12/site-packages/pip (python 3.12)
```

**只要出现 `pip` 和版本号就算成功**，路径不用管。

> [!NOTE] 如果 `python3` 有反应但 `pip` 报 `command not found`，单独装一次：`pkg install -y python-pip`。

### 2.4 装本项目要用的额外依赖

分三组，按需装。**只聊天不控屏、不 OCR 的话，这步可以全部跳过**，程序本身零依赖就能跑。

#### A 组：控屏（必装，如果要让它点屏幕）

```
pkg install -y android-tools
```

**干什么**：装 `adb`，就是让程序能模拟点击、滑动、截屏的那个工具。约 10 MB。

验证：

```
adb version
```

应该看到 `Android Debug Bridge version 1.0.41` 或更高。

> [!WARN] 如果版本低于 1.0.41，配对时会报 `unknown command`，必须 `pkg upgrade android-tools`。Termux 镜像里的版本一般已经是新的。

#### B 组：OCR（要读图片/PDF 才装）

```
pkg install -y tesseract poppler python-pillow
```

**这三个分别是什么**：

| 包 | 作用 | 大小 |
|---|---|---|
| `tesseract` | 识别引擎本体，把图片里的字形变成文字 | 约 30 MB |
| `poppler` | 提供 `pdftoppm`，把 PDF 每一页转成图片再识别 | 约 15 MB |
| `python-pillow` | Python 的图片处理库，`ocr.py` 用它做缩放和裁剪 | 约 8 MB |

> [!WARN] **不要用 `pip install pillow`。** 那会现场编译 C 代码，手机上大概率失败，或者卡 10 分钟。Termux 官方已经把编译好的包命名为 `python-pillow`，用 `pkg install` 一步到位。

#### C 组：其他可选

| 命令 | 什么时候需要 |
|---|---|
| `pkg install -y radare2` | 要用 `rev.py r2` 反汇编 |
| `pkg install -y git` | 想用 `git clone` 拉代码，而不是 curl 下文件 |
| `pkg install -y procps` | 想用 `pkill` 结束进程（Termux 默认没有） |

### 2.5 不要做的事

| 别做 | 为什么 |
|---|---|
| `pkg upgrade` | 全量升级几百 MB，耗时半小时以上，中途断网会把系统搞坏。只装缺的包就够了 |
| `pip install --upgrade pip` | Termux 的 pip 和系统包管理器有绑定，升级后可能装不上任何东西 |
| 从应用商店装「Python 编辑器」类 App | 那些是另一个 App，和 Termux 里的 Python 半毛钱关系没有 |
| `apt install` | Termux 用的就是 `pkg`，`apt` 能用但路径和参数有差异，新手别碰 |

### 2.6 检查点

逐条执行，全部通过再往下：

```
python3 --version
pip --version
adb version
```

前两条必须有输出。第三条如果第 2.4 节 A 组装了才有，没装会报 `command not found`，正常。

再跑一个真正的 Python：

```
python3 -c "print('环境正常')"
```

应该原样输出：

```
环境正常
```

这行不通，说明解释器有问题（不是路径问题就是装坏了），先解决它，别往第 3 章走。
---

## 第 3 章 把程序下载到手机

### 3.1 先搞清楚「装在哪」

Termux 里所有的操作都在一个「当前目录」里发生。你可以用这条命令看看自己在哪：

```
pwd
```

会输出：

```
/data/data/com.termux/files/home
```

这就是 Termux 的**家目录**，等价于 `~`。你每次新开 Termux 都站在这里。

我们要建一个专门放程序的文件夹：

```
mkdir -p ~/work
cd ~/work
```

**这两条在干什么**：

- `mkdir -p ~/work`：创建 `work` 文件夹。`-p` 的意思是「如果已经存在就别报错」
- `cd ~/work`：把当前目录切到 `work` 里。`cd` 是 change directory

再 `pwd` 一次，应该变成：

```
/data/data/com.termux/files/home/work
```

后面的下载、启动，**全部要在这个目录里做**。忘了在哪就先 `pwd`。

> [!NOTE] 目录名叫 `work` 只是习惯，叫 `abc` 也行。但整份手册和你以后看到的教程都用 `~/work`，跟着用省事。

### 3.2 方式 A：一句命令全下（推荐）

这个仓库带了一个更新脚本 `update.sh`，它知道所有文件在哪、下完会校验、失败会自己换镜像。

**第一步，把脚本本身下下来**：

```
curl -fL -o update.sh.part "https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/agent-kit/main/update.sh" && mv update.sh.part update.sh
```

**这行在干什么**：`curl` 是下载工具。`ghfast.top/` 是国内镜像前缀，原地址整段接在它后面。`-f` 表示「服务器返回错误就直接失败」，`-L` 表示「遇到跳转跟着走」。

`-o update.sh.part` 是**先存成临时名字**，`&&` 意思是「前一条成功了才执行后面」，`mv` 再改名。

为什么不直接 `-o update.sh`：万一网络断了，`curl` 会留下一个 0 字节的空文件，把你的旧脚本覆盖成废文件。**这个坑踩一次就够**，所以所有下载都先写 `.part`。

**第二步，跑它**：

```
sh update.sh
```

**这条在干什么**：用 `sh` 解释器执行 `update.sh`，它会去仓库把 `rev.py`、`webchat.py`、`adui.py`、`ocr.py`、手册、`static/` 三件套全部拉下来。

成功会看到：

```
agent-kit 更新
目录  /data/data/com.termux/files/home/work
镜像  ghfast.top（失败自动换下一个）

  ✓ rev.py        新增 28616
  ✓ webchat.py    新增 45068
  ✓ adui.py       新增 47304
  ✓ ocr.py        新增 33777
  ✓ static/app.html 新增 5110
  ✓ static/app.css  新增 22706
  ✓ static/app.js   新增 35216
  ✓ MANUAL.md       新增 38124
  ✓ MANUAL.html     新增 69250
  ✓ update.sh       新增 8559

已更新： rev.py webchat.py ...
```

**看到「新增」就是成功。** 数字是你机器上实际下到的字节数，和上面不完全一致没关系（版本更新会变大小），但**不应该是 0**。

以后换新版，只要在这个目录里执行一句：

```
sh update.sh
```

它自己会比对内容，没变的不写盘，变了的才替换，还会把旧的存成 `.bak`。

### 3.3 方式 B：手动逐个下载（脚本抽风时用）

`update.sh` 也下不下来的时候（镜像全挂），用这段。**整段复制，一次粘贴**：

```
BASE="https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/agent-kit/main"

for f in rev.py webchat.py adui.py ocr.py update.sh; do
  curl -fsSL -o "$f.part" "$BASE/$f" && [ -s "$f.part" ] && mv "$f.part" "$f" && echo "ok $f"
done

mkdir -p static

for f in app.html app.css app.js; do
  curl -fsSL -o "static/$f.part" "$BASE/static/$f" && [ -s "static/$f.part" ] && mv "static/$f.part" "static/$f" && echo "ok static/$f"
done
```

**这段在干什么**：`BASE` 是把镜像前缀存成一个变量，省得写八遍。`for f in ...` 是一个循环，把括号里每个名字依次当成 `f` 执行中间那段。`[ -s "$f.part" ]` 是判断「这个文件存在且不是空的」。

逐行输出 8 个 `ok` 就成功了。

> [!WARN] 单个文件下载失败时，最稳的办法是手动重跑对应那一行。不要用 `wget -O 目标文件`，它在失败时会先把目标文件清空，把好的版本毁掉。

### 3.4 方式 C：整仓克隆（有 git 的话最省事）

```
pkg install -y git
git clone --depth 1 https://ghfast.top/https://github.com/dengxiancao/agent-kit ~/work-kit
```

这会把整个仓库（含手册、原型图）拉到 `~/work-kit`。以后更新：

```
cd ~/work-kit && git pull
```

用这种方式的话，**记住你的目录是 `~/work-kit`**，后面所有命令里的 `~/work` 都要换掉。

### 3.5 校验：数字对不上就是没下完

```
cd ~/work
wc -c rev.py webchat.py adui.py ocr.py static/app.html static/app.css static/app.js
```

输出七行数字。对照下表，**你自己的数字比表里小就说明下截断了**，重下那一个：

| 文件 | 参考字节数 |
|---|---|
| `rev.py` | 28616 |
| `webchat.py` | 45068 |
| `adui.py` | 47304 |
| `ocr.py` | 33777 |
| `static/app.html` | 5110 |
| `static/app.css` | 22706 |
| `static/app.js` | 35216 |

再确认目录结构长这样：

```
ls -R ~/work
```

```
/data/data/com.termux/files/home/work:
adui.py  MANUAL.html  MANUAL.md  ocr.py  rev.py  static  update.sh  webchat.py

/data/data/com.termux/files/home/work/static:
app.css  app.html  app.js
```

**`static` 必须在 `work` 里面，和 `webchat.py` 平级。** 少了它，打开网页会看到一行「缺少 static 目录」。

### 3.6 每个文件是干什么的

| 文件 | 干什么 | 必须吗 |
|---|---|---|
| `webchat.py` | 主体：起网页服务 + 跟 AI 对话 + 执行工具 | **必须** |
| `static/app.html` | 网页的骨架 | **必须** |
| `static/app.css` | 网页的样式（含深色模式） | **必须** |
| `static/app.js` | 网页的交互（流式输出、会话切换） | **必须** |
| `adui.py` | 操作手机屏幕（点击、滑动、截图） | 要控屏就装 |
| `ocr.py` | 识别图片和 PDF 里的文字 | 要读图就装 |
| `rev.py` | 分析 APK、so、exe 等二进制文件 | 做逆向才用 |
| `update.sh` | 一键更新 | 建议留着 |
| `MANUAL.*` | 手册本身 | 可选 |

---

## 第 4 章 申请一个 API key

### 4.1 这个东西是什么

程序本身不会思考，它每说一句话都要把上下文发给远端的 AI 模型，模型算完把结果发回来。

**API key 就是这次调用的身份证 + 付款凭证**：模型服务商靠它认出「这是谁在调用」，然后从那个账户扣钱。

所以：

- 没有 key，程序启动会直接退出，提示「缺少 DEEPSEEK_KEY」
- key 泄露，别人可以用你的 key 花你的钱
- key 一般只显示一次，页面关掉就看不到了

### 4.2 注册和充值

打开 https://platform.deepseek.com ，用手机号注册并登录。

然后**先充值再创建 key**，顺序反了会在第一次对话时收到余额不足的报错：

1. 左侧菜单找「充值」或「账户余额」
2. 充 **10 元**试水。按现在的价格，正常强度聊天一个月用不完
3. 确认余额显示 10 元

> [!NOTE] 计费方式是「按 token 用量扣」。一句话大约消耗几百到几千 token，具体价格随官方调整，看充值页上的实时说明。10 元差不多够你折腾一两个月。

### 4.3 创建 key

1. 左侧菜单进「API keys」
2. 点「创建 API key」，名字随便填（比如 `phone`）
3. **立刻复制弹出来的那串字符**，形如 `sk-` 开头、后面三十多位
4. 存到一个临时地方（记事本、微信文件传输助手都行）

页面关掉之后就再也看不到完整 key 了，只能删了重建。**先复制，再关页面。**

### 4.4 把 key 存到手机里（一次配置，永久生效）

不要把 key 直接写在命令里。那种写法（`DEEPSEEK_KEY=sk-xxx python3 webchat.py`）每次重启手机就失效，而且会留在命令历史里被人翻到。

正确做法是写进配置文件。**三条命令，逐条执行**：

```
mkdir -p ~/.config/webchat
```

```
echo 'DEEPSEEK_KEY=sk-把这里换成你自己的key' > ~/.config/webchat/env
```

```
chmod 600 ~/.config/webchat/env
```

**这三条在干什么**：

- 第一条：建一个隐藏配置目录（`~/.config/webchat`）
- 第二条：把 `DEEPSEEK_KEY=...` 这一行写进 `env` 文件。**把 `sk-把这里换成你自己的key` 整段替换成你复制的 key**，单引号要保留
- 第三条：把文件权限改成「只有你自己能读」。安卓上多用户或装了文件管理器的情况下，别的 App 读不到

验证写对了没有：

```
cat ~/.config/webchat/env
```

应该原样显示你写的那一行。**key 不要发截图到群里**，这一步自己看一眼就行。

### 4.5 这个文件还能写什么

`env` 文件里可以写多行，一行一个设置。常用的四个：

| 键 | 默认值 | 什么时候要改 |
|---|---|---|
| `DEEPSEEK_KEY` | 无 | **必填** |
| `AGENT_WORK` | `~/work` | 程序放在 `~/work-kit` 时改成那 |
| `HOST` | `127.0.0.1` | 想让电脑/平板访问手机上的服务，改成 `0.0.0.0` |
| `PORT` | `8765` | 端口被占用时换一个，比如 `8800` |
| `AGENT_MAX_TURNS` | `100` | 单条消息最多执行几步，一般不用动 |

多行的写法就是多写几行：

```
DEEPSEEK_KEY=sk-xxxxxx
AGENT_WORK=/data/data/com.termux/files/home/work
HOST=0.0.0.0
```

> [!WARN] 这个文件里是明文 key。三件事别做：不要放进 git 仓库、不要截图发人、不要传到网盘。换手机迁移时也不要整个目录打包发给别人。

### 4.6 检查点

```
ls -l ~/.config/webchat/env
```

看到权限是 `-rw-------`（就是刚才 `chmod 600` 的结果），属主是你自己，就对了。

再看一眼内容长度合理（不会只有几个字符）：

```
wc -c ~/.config/webchat/env
```

`sk-` 开头的 key 大概 35 个字符，加上 `DEEPSEEK_KEY=` 一共 48 左右。差太多就是复制漏了。

---

## 第 5 章 第一次运行

### 5.1 先不花钱，看看界面长什么样

```
cd ~/work
python3 webchat.py --mock
```

**这条在干什么**：`--mock` 是「演习模式」。它不调用任何 AI 接口，用预置的假数据回复你，**不消耗一分钱**。用来确认界面能不能打开、文件有没有下全。

会看到：

```
  agent 界面已启动
  http://127.0.0.1:8765
  工作目录 /data/data/com.termux/files/home/work
  模式 MOCK 演示
  会话库 /data/data/com.termux/files/home/.local/share/webchat/sessions.db（0 个会话）
  Ctrl+C 停止
```

**终端到这里就停住了，不回到 `$`**。这是正常的——它在跑一个网页服务，占着这个终端。

现在按**音量减 + 音量加之外**的任意操作都会打断它，注意别误触。切到浏览器：

### 5.2 打开界面

在手机浏览器地址栏输入（**必须带 `http://`**）：

```
http://127.0.0.1:8765
```

只输 `127.0.0.1:8765` 会被浏览器当成搜索词，跳去搜索页。

建议：把这个地址存成书签，以后一点就开。

**看到什么算正常**：

- 左边一列是会话列表（现在是空的，或者有一条「演示会话」）
- 中间是对话区，底部有输入框
- 右上角有几个小按钮（主题、导出）
- 顶上有个 chip 显示「上下文 0 / 64k」

**看不到界面怎么办**：

| 现象 | 原因 | 怎么修 |
|---|---|---|
| `ERR_CONNECTION_REFUSED` | 服务没起来 | 回 Termux 看有没有报错；终端是否已经退回 `$` |
| 页面上写着「缺少 static 目录」 | 前端文件没下 | 回第 3.3 节补下 `static/` 三个文件 |
| 一片空白，控制台有红字 | 用旧版缓存 | 关掉标签页重开；或浏览器设置里清缓存 |
| 转圈很久打不开 | 端口被别的程序占了 | 停掉旧进程，或 `python3 webchat.py --mock --port 8800` |

看完界面，回 Termux 按 **音量减 + C**（等于 Ctrl+C）停掉。

### 5.3 正式启动

```
cd ~/work
python3 webchat.py
```

这次没有 `--mock`，会真的连 DeepSeek。启动信息里会多一行「配置 .../env」，表示 key 读取成功：

```
  agent 界面已启动
  http://127.0.0.1:8765
  工作目录 /data/data/com.termux/files/home/work
  配置 /data/data/com.termux/files/home/.config/webchat/env
  会话库 .../webchat/sessions.db（1 个会话）
  Ctrl+C 停止
```

如果它打印「缺少 DEEPSEEK_KEY」然后退出，说明第 4.4 节没写对，回去检查 `cat ~/.config/webchat/env`。

浏览器还是同一个地址：`http://127.0.0.1:8765`。

### 5.4 界面导览

第一次看到这个界面会有点懵，按这个顺序看一遍：

| 位置 | 是什么 | 怎么用 |
|---|---|---|
| **左上「新对话」** | 开一个新会话 | 一个话题一个会话，别都挤在一个里 |
| **左侧列表** | 历史会话，按今天/昨天/更早分组 | 点一下就切过去，上下文跟着切 |
| **左侧搜索框** | 搜标题和正文 | 找上周问过的东西 |
| **中间空白区** | 对话区 | 这里会滚出你的话和它的回复 |
| **底部输入框** | 打字的地方 | 回车发送，Shift+回车换行 |
| **回复下方小字** | `4 步 · 18.6s · 512 tokens` | 这条回复执行了几步、花了多久、多少 token |
| **右侧面板** | 上下文占用、工具时间线 | 看它到底做了什么 |
| **顶部 chip** | `上下文 1.2k / 64k` | 快满了会变黄，说明该开新会话了 |
| **顶部 ■** | 停止按钮 | 它跑偏了，点这个刹车，已生成的内容保留 |

手机上屏幕窄，左侧列表收成抽屉（点左上角 ☰），右侧面板收成底部弹层（点顶部图表图标）。

### 5.5 第一句话说什么

不要问「你好」，那浪费一次调用。

直接用中文说你想做什么，越具体越好。三个可以直接抄的例子：

```
看看工作目录里有哪些文件，按类型分个类
```

```
我在 ~/work 放了个 apk，帮我分析它申请了哪些危险权限
```

```
查看当前手机屏幕上有哪些可点的文字
```

第三条需要第 6 章配好 ADB 才能用，前两条现在就能跑。

**它干活的节奏**：先说一句「我先看看」，然后弹出一张工具卡（写着执行的命令和输出），再根据输出继续，最后给结论。

工具卡是核心。**它说「我做完了」不算数，卡片上的输出才算**。点开卡片能看到完整的命令和返回内容。

### 5.6 关掉再打开，对话还在

这是这一版区别最大的地方。

按 Ctrl+C 停掉服务，或者直接杀掉 App，甚至重启手机——下次再 `python3 webchat.py`，左侧列表里的对话全都在，点进去上下文完整，可以接着聊。

因为它们存在一个 SQLite 文件里：

```
~/.local/share/webchat/sessions.db
```

| 你想做 | 怎么做 |
|---|---|
| 备份 | `cp ~/.local/share/webchat/sessions.db ~/sessions-备份.db` |
| 换手机 | 把这一个文件拷过去，放到同样的路径 |
| 清空全部历史 | 删掉这个文件，下次启动自动重建 |
| 不想要历史 | 启动时加 `--no-db`，纯内存，关掉就没了 |

### 5.7 检查点

到这一步你应该能：

- 打开 `http://127.0.0.1:8765` 看到界面
- 输入一句话，看到它调用工具并回复
- 关掉终端重新启动，之前的对话还在列表里
- 回复下方有「N 步 · N 秒 · N tokens」

四条都行，说明核心功能已经完全跑通。**到这里已经可以日常用了**，下面两章是加分项。

不想让它碰屏幕、不想读图，可以直接跳到第 9 章。
---

## 第 6 章 让它能操作你的手机屏幕

这一章是全套里最容易卡住的地方。慢一点，一步一验。

### 6.1 原理：它凭什么能点你的屏幕

安卓系统里有个官方调试通道叫 **ADB**（Android Debug Bridge）。本来是给开发者用电脑连手机调试的，因为它能做的事和你的手指一样：点击、滑动、输入文字、截屏、读界面结构。

正常情况下 ADB 要通过 USB 线连电脑。安卓 11 之后加了**无线调试**，同一台手机上的两个 App 也能通过它通信——这就是 Termux 里的 `adb` 能操作本机屏幕的原因。

所以整个链路是：

```
webchat.py  →  adui.py  →  adb  →  安卓系统  →  你的屏幕
```

### 6.2 打开开发者选项

这个菜单默认是隐藏的，要用「连点版本号」的方式解锁。

| 品牌 | 路径 |
|---|---|
| 小米 / Redmi | 设置 → 我的设备 → 全部参数与信息 → 连续点「MIUI 版本」7 次 |
| 华为 / 荣耀 | 设置 → 关于手机 → 连续点「版本号」7 次 |
| OPPO / 一加 / realme | 设置 → 关于本机 → 版本信息 → 连续点「版本号」7 次 |
| vivo / iQOO | 设置 → 系统管理 → 关于手机 → 连续点「软件版本号」7 次 |
| 三星 | 设置 → 关于手机 → 软件信息 → 连续点「编译编号」7 次 |
| 原生 Android | 设置 → 关于手机 → 连续点「版本号」7 次 |

点够次数会提示「你已处于开发者模式」。

然后回到设置主页面找「开发者选项」：

- 小米：设置 → 更多设置 → 开发者选项
- 其他品牌一般在 设置 → 系统 / 关于手机 附近

### 6.3 打开无线调试

在开发者选项里找到 **无线调试**（Wireless debugging），打开它。

打开后会弹一个确认框「要允许通过无线方式调试吗」，点**允许**。

进去之后你会看到这个页面，**记住这一行**：

```
IP 地址和端口
192.168.1.102:39549
```

这个端口（`39549`）是**连接用的端口**，不是配对端口，两者不一样。

> [!WARN] 这个页面上的端口每次重启手机、每次关掉无线调试都会变。所以不要抄下来存着，每次现看。

### 6.4 配对（只需一次）

点页面里的 **「使用配对码配对设备」**，会弹出一个框：

```
使用配对码配对设备

Wi-Fi 配对码
570100

Wi-Fi 配对
IP 地址和端口
192.168.1.102:42361
```

注意这里也有一行 `IP:端口`，**这个端口（42361）和主页面的（39549）不是同一个**。

**90% 的失败都是因为拿错了端口。** 记法：

| 你看到的 | 用途 | 用在哪 |
|---|---|---|
| 主页面上的 `IP:端口` | **连接** | `adb connect` |
| 弹窗里的 `IP:端口` | **配对** | `adb pair` |

#### 关键：这个弹窗只活 2 分钟

锁屏、切到别的应用、把弹窗关掉，它立刻失效。所以**不要抄在纸上再慢慢打**，用分屏：

1. 打开最近任务（多任务键或上滑悬停）
2. 长按 Termux 图标 → 选「分屏」或「分屏显示」
3. 上半屏选「设置」，让设置页面和 Termux 同时可见
4. 在设置里点「使用配对码配对设备」拿到弹窗
5. 在下面一半的 Termux 里直接敲命令

#### 敲这条

把 `42361` 换成你弹窗里的端口，`570100` 换成你的 6 位码：

```
python3 adui.py pair 127.0.0.1:42361 570100
```

**这条在干什么**：让本机的 adb 用这个一次性端口和系统的无线调试服务握手，交换密钥。成功后密钥存在手机里，以后不用再配对。

成功会看到：

```
Successfully paired to 127.0.0.1:42361 [guid=adb-xxxxx]
配对完成（这东西只做一次，重启也不会丢）。
配对后调试端口会换一个，正在自动找…
```

然后它会自动开始扫端口（下一节的内容），等它扫完就行。

**失败的信息长这样，对症下药**：

| 输出 | 原因 | 怎么修 |
|---|---|---|
| `protocol fault (couldn't read status message)` | 端口用错了，拿了连接端口去配对 | 回弹窗看，配对要用弹窗里那个端口 |
| `failed to authenticate to` | 6 位码打错了 | 重新开弹窗，慢慢核对 |
| `Connection refused` | 弹窗已过期 | 重新点「使用配对码配对设备」拿新的一组 |
| `adb: command not found` | 没装 android-tools | `pkg install -y android-tools` |

### 6.5 找到连接端口并连上（推荐用 scan）

配对只解决「你是谁」，还没建立连接。连接需要主页面那个端口。

**别用肉眼抄**，让它自己扫：

```
python3 adui.py scan
```

**这条在干什么**：Termux 和 adbd 跑在同一台手机上，所以它扫 `127.0.0.1` 的 30000 到 65535 端口，找出哪个在说 ADB 协议，找到就顺手 `connect`。

正常会看到：

```
扫描 127.0.0.1 的 30000-65535 端口（共 35536 个，约 5-20 秒）…
发现开放端口：39549
connect 127.0.0.1:39549 → connected
已连接 127.0.0.1:39549
```

看到 `connected` 或 `已连接` 就成了。

> [!NOTE] 为什么不用 `adb mdns services`？Termux 里的 android-tools 在编译时把 mDNS 支持关掉了，这条命令必然报 `not supported`。所以作者改成了端口扫描，这是 Termux 环境下唯一可靠的办法。

**扫不到怎么办**：

| 现象 | 原因 | 怎么修 |
|---|---|---|
| 一个端口都没发现 | 无线调试被关了 | 回设置确认「无线调试」是打开状态 |
| 发现端口但连接失败 | 配对没完成 | 重做 6.4 节 |
| 提示 `device offline` | 连接过期 | `python3 adui.py doctor` |

### 6.6 验证：能不能看见屏幕

```
python3 adui.py info
```

应该输出设备型号、安卓版本、分辨率之类。看到型号就说明通了。

```
python3 adui.py look
```

**这条在干什么**：读当前界面的元素树，列出所有可点的东西，带序号和坐标。

输出长这样：

```
[ 1] 微信                          ( 540,2180)  clickable,text
[ 2] 通讯录                        ( 180,2180)  clickable,text
[ 3] 发现                          ( 540,2180)  clickable,text
[ 4] 我                            ( 900,2180)  clickable,text
提示：tap N 直接点第 N 个；tap-text 文字 也行
```

格式是 `[序号] 文字 (x,y) 标记`。

**然后就能操作了**：

| 命令 | 效果 |
|---|---|
| `python3 adui.py tap 1` | 点第 1 个元素（按序号最省事） |
| `python3 adui.py tap 540 2180` | 点坐标（知道位置时用） |
| `python3 adui.py tap-text 微信` | 按文字找，找到就点 |
| `python3 adui.py key back` | 返回键。还有 `home`、`enter`、`delete` |
| `python3 adui.py swipe 540 1600 540 600` | 从 (540,1600) 滑到 (540,600)，上滑一次 |
| `python3 adui.py scroll down 3` | 向下滚 3 屏 |
| `python3 adui.py shot ~/work/screen.png` | 截屏存文件 |
| `python3 adui.py wait 设置 15` | 等「设置」两个字出现，最多等 15 秒 |

再 `look` 一次，看界面有没有变。变了就说明真的点到了。

### 6.7 往输入框里打中文

`adb input text` 天生不支持中文，打出来是乱码或者直接吞掉。

解决方式是用一个专门的输入法 App。作者写了个安装命令：

```
python3 adui.py ime-install
```

**这条在干什么**：检查手机里有没有装那个输入法，没有就提示你怎么装。装完后：

```
python3 adui.py text "我在路上了，十分钟到"
```

它会临时切到那个输入法、打完字、再切回你原来的输入法。

如果提示「未配好」，按顺序试：

```
python3 adui.py ime-enable
python3 adui.py ime
```

`ime` 不带参数是查看当前输入法状态，带 App 名是手动切。

> [!NOTE] 不想折腾输入法也行：中文内容让 AI 用英文拼音代替，或者直接用 `ocr` 找到输入框坐标后用 `tap` + 系统键盘手动打。不过装了之后确实省事，建议装。

### 6.8 断了怎么办（下次开机必用）

无线调试的连接**重启手机就断**，不是坏了，是安卓的正常行为。

一条命令修：

```
python3 adui.py doctor
```

**这条在干什么**：按顺序做四件事，遇到能解决的就停：

1. 查 `adb version`，确认工具有没有
2. 查 `adb devices`，看是 `offline` 还是 `unauthorized`
3. `kill-server` + `start-server` 重置连接
4. 扫 30000-65535 端口，找到就重新连上

正常输出：

```
[1/4] adb 版本 1.0.41
[2/4] 当前设备：
      127.0.0.1:39549   offline
[3/4] 重启 adb 服务
[4/4] 扫描端口…
      connect 127.0.0.1:41233 → connected
完成
```

**已经连着的会直接跳过**，不会重复扫。

几种情况看起来像坏了，其实不是：

| 现象 | 怎么办 |
|---|---|
| 重启手机后 `look` 报连接失败 | 正常，跑一次 `doctor` |
| 换 WiFi / 开关飞行模式后断 | 跑 `doctor` |
| `unauthorized` | 手机上会弹「允许 USB 调试吗」，点允许并勾「一律允许」 |
| 跑完 `doctor` 还是连不上 | 关掉无线调试再打开，重新 `scan` |
| 配对信息丢了（提示需要重新配对） | 重做 6.4 节，2 分钟的事 |

### 6.9 检查点

```
python3 adui.py doctor
```

最后一行是「完成」或显示已连接，且紧接着：

```
python3 adui.py look
```

能列出元素，就说明控屏链路完全通了。

现在回网页界面，说一句：

```
看看当前屏幕上有哪些可点的文字
```

它会自己调 `adui.py look`，把结果整理成中文告诉你。

---

## 第 7 章 让它能看图片和 PDF

### 7.1 什么时候需要

程序的 `look` 命令读的是安卓的界面元素树。遇到下面这些，元素树是空的：

- 游戏画面
- 用 Flutter 或 Unity 写的 App（树上只有一整块画布）
- 一张图片里印着字（截图、照片、扫描件）
- 别人发来的 PDF

这时候只能靠**看图认字**，也就是 OCR（Optical Character Recognition，光学字符识别）。

### 7.2 确认依赖都装了

第 2.4 节 B 组装过的话跳过这步。没装就补：

```
pkg install -y tesseract poppler python-pillow
```

三个包各自的作用：

| 包 | 提供的命令 | 干什么 |
|---|---|---|
| `tesseract` | `tesseract` | 识别引擎，图片进、文字出 |
| `poppler` | `pdftoppm` | 把 PDF 每页转成 PNG，才能喂给引擎 |
| `python-pillow` | （Python 库） | `ocr.py` 用它做灰度、缩放、裁剪 |

验证：

```
tesseract --version
```

看到 `tesseract 5.x.x` 就行。

### 7.3 装中文语言包

引擎本身只会认英文，中文要单独下模型文件。

先看现在有哪些语言：

```
tesseract --list-langs
```

如果输出里只有 `eng` 和 `osd`，需要补中文：

```
mkdir -p ~/.tessdata
```

```
curl -fL -o ~/.tessdata/chi_sim.traineddata "https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/chi_sim.traineddata"
```

```
curl -fL -o ~/.tessdata/eng.traineddata "https://ghfast.top/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata"
```

**这两条在干什么**：把简体中文和英文的识别模型下载到 `~/.tessdata`，`ocr.py` 启动时会优先读这个目录。

补完再验一次：

```
tesseract --list-langs
```

现在应该能看到 `chi_sim`。

> [!NOTE] `tessdata_fast` 是速度优先的版本，手机上用这个。如果发现某些字总认错，可以换 `tessdata_best`（准确率高但慢 3-5 倍），把地址里的 `tessdata_fast` 改成 `tessdata_best` 重下一次即可。

### 7.4 自检

```
python3 ocr.py doctor
```

**这条在干什么**：查引擎在不在、语言包齐不齐、Pillow 能不能用、临时目录可写。每项打一个勾或叉。

全绿就能用了。有一项是叉，它会直接告诉你缺什么、装哪个包。

### 7.5 三种用法

**第一种：只要文字**

```
python3 ocr.py ~/work/screenshot.png
```

输出一行一句，像这样：

```
微信
通讯录
发现
我
```

**第二种：要坐标（能直接点）**

```
python3 ocr.py ~/work/screenshot.png --boxes
```

```
  0  120  480  60  24  92     微信
  1  120  980  60  24  88     通讯录
```

格式是 `x y 宽 高 置信度 文字`。坐标可以直接喂给 `tap`：

```
python3 adui.py tap 150 492
```

**第三种：给程序用**

```
python3 ocr.py ~/work/screenshot.png --json
```

输出一个 JSON 数组，每项含 `text`、`x`、`y`、`conf`。

### 7.6 认不准怎么调

OCR 不是万能的，尤其手机上字小、背景花。按这个顺序试：

| 问题 | 加这个参数 | 说明 |
|---|---|---|
| 整张图字太小 | `--scale 2` | 先放大两倍再认。默认按宽度自动判断 |
| 只想认中间一块 | `--crop 120,480,900,720` | 四个数是 `左,上,右,下`，单位像素 |
| 一行字被拆成好几段 | `--psm 6` | 告诉引擎「当成一整块文字」，不要按版面切 |
| 深色背景白字 | `--invert on` | 反色 |
| 彩色底（比如微信绿） | 通常自动处理 | 程序会检测饱和度改用亮度通道 |
| 结果里有大量乱码 | `--minconf 50` | 把置信度低于 50 的全丢掉 |

例子，组合使用：

```
python3 ocr.py ~/work/shot.png --crop 80,400,1000,900 --scale 2 --psm 6 --boxes
```

> [!NOTE] 每个参数都能单独试。**先试 `--crop`，收益最大**：只认你需要的那一块，速度和准确率都会明显提升。

### 7.7 截屏直接识别（控屏专用）

`adui.py` 里集成了一条龙：截屏 + 识别 + 输出坐标，不用先存文件再喂给 `ocr.py`。

```
python3 adui.py ocr
```

输出：

```
[ 1] 微信                    ( 540,2180)  92
[ 2] 通讯录                  ( 180,2180)  88
```

序号可以直接 `tap`：

```
python3 adui.py tap 1
```

**这就是 `look` 看不见界面时的备用方案**：`look` 拿元素树，`ocr` 认屏幕上的字，两条路都能定位。

参数和 `ocr.py` 基本一致：

```
python3 adui.py ocr --crop 0,1800,1080,2400
```

只认底部导航栏那一块。

### 7.8 检查点

找一张有字的截图（微信聊天截图最好），执行：

```
python3 ocr.py 你的截图.png --boxes
```

能看到中文文字和坐标，说明这一章通了。

再试 PDF（有的话）：

```
python3 ocr.py 某个文件.pdf --dpi 150
```

它会逐页转图再识别。页数多会很慢，可以只处理前两页：

```
python3 ocr.py 某个文件.pdf --first 1 --last 2
```
---

## 第 8 章 在电脑或虚拟机上再装一份（可选）

手机上已经能用了的话，这章可以跳过。想在更大的屏幕上用、或者要操作 Linux 桌面，才需要看。

### 8.1 为什么要在第二台机器上装

| 理由 | 说明 |
|---|---|
| 屏幕大 | 手机上三栏布局挤，电脑上看得清工具输出和表格 |
| 跑得久 | 手机切后台容易被系统杀，虚拟机不容易 |
| 能控 Linux 桌面 | `ui.py` 靠 X11 截图和 xdotool，只有 Linux 桌面环境能用 |
| 不占用手机 | 一边用手机干别的，一边让它跑在虚拟机里 |

会话库是**各存各的**，两台机器不共享历史。想让两边看到同一份记录，手动拷 `sessions.db`。

### 8.2 装 Python（先确认你是什么系统）

不同发行版的包管理器不一样，`apt` 和 `apk` 不能混用。先查：

```
cat /etc/os-release
```

看开头几行的 `NAME=` 或 `ID=`：

| 看到 | 系统 | 用什么命令 |
|---|---|---|
| `Alpine Linux` | Alpine（HiSH 虚拟机就是这个） | `apk` |
| `Ubuntu` / `Debian` | Ubuntu / Debian | `apt` |

#### A. Alpine

```
apk update
apk add python3 py3-pip
```

**这两条在干什么**：`apk` 是 Alpine 的包管理器。第一条刷新索引，第二条装 Python 3 和 pip。Alpine 精简得厉害，装完体积也就几十 MB。

#### B. Ubuntu / Debian

```
sudo apt update
sudo apt install -y python3 python3-pip
```

#### 两种都验证一下

```
python3 --version
pip3 --version
```

看到 `Python 3.x` 和 pip 的版本号就对了。Linux 上 pip 通常叫 `pip3`。

> [!WARN] 如果 `pip3 install xxx` 报 `error: externally-managed-environment`，这是新版发行版的保护机制，不是坏了。**优先改用系统包**（Alpine 的 `apk add py3-xxx`、Ubuntu 的 `apt install python3-xxx`）。不要加 `--break-system-packages` 硬装，会把系统 Python 搞乱。

### 8.3 装额外依赖

按你的系统选一列：

| 用途 | Alpine | Ubuntu / Debian |
|---|---|---|
| 拉代码 / 下载 | `apk add git curl` | `apt install -y git curl` |
| OCR | `apk add tesseract-ocr poppler-utils py3-pillow` | `apt install -y tesseract-ocr poppler-utils python3-pil` |
| OCR 中文包 | `apk add tesseract-ocr-data-chi_sim` | `apt install -y tesseract-ocr-chi-sim` |
| X11 桌面控屏 | `apk add xdotool imagemagick` | `apt install -y xdotool imagemagick` |
| 反汇编 | `apk add radare2` | `apt install -y radare2` |

装完验证 OCR 能不能用：

```
tesseract --list-langs
```

列表里有 `chi_sim` 就行。**Alpine 如果提示找不到 `tesseract-ocr-data-chi_sim` 这个包**（老版本仓库没有），用第 7.3 节的手动下载方式，把模型放进 `~/.tessdata` 一样能用。

### 8.4 把代码拉下来

git 和 curl 8.3 已经装过了，直接拉：

```
mkdir -p ~/work && cd ~/work
curl -fL -o update.sh.part "https://ghfast.top/https://raw.githubusercontent.com/dengxiancao/agent-kit/main/update.sh" && mv update.sh.part update.sh
sh update.sh
```

流程和手机上一模一样。拉完 `ls` 确认有 `webchat.py` 和 `static/`。

### 8.5 配置和启动

key 的配置方式和手机相同，路径也一样：

```
mkdir -p ~/.config/webchat
echo 'DEEPSEEK_KEY=sk-你的key' > ~/.config/webchat/env
chmod 600 ~/.config/webchat/env
```

启动：

```
cd ~/work
python3 webchat.py
```

浏览器打开 `http://127.0.0.1:8765`。

### 8.6 想让别的设备访问

默认只监听 `127.0.0.1`，也就是只有本机能连。要让手机、平板、宿主机访问，得改成 `0.0.0.0`：

```
python3 webchat.py --host 0.0.0.0
```

或者写进配置文件，省得每次敲：

```
echo 'HOST=0.0.0.0' >> ~/.config/webchat/env
```

改完之后用这台机器的**局域网 IP** 访问，不是 `127.0.0.1`：

```
ip addr | grep "inet 192"
```

假设输出 `192.168.1.50`，那就在浏览器打 `http://192.168.1.50:8765`。

**虚拟机里还要多做一步**：宿主机的浏览器访问虚拟机的端口，需要端口映射（NAT 转发）或把虚拟机网络设成桥接模式。

| 方式 | 怎么做 |
|---|---|
| 桥接 | 虚拟机设置 → 网络 → 桥接网卡。虚拟机会拿到和宿主机同网段的 IP，直接用那个 IP 访问 |
| NAT + 端口转发 | 虚拟机设置 → 网络 → 端口转发 → 添加：主机端口 `8765`，子系统端口 `8765` |

> [!WARN] `--host 0.0.0.0` 等于把这台机器上的**命令执行权**开给整个局域网，而这个界面**没有密码**。同一 WiFi 下的任何人打开浏览器就能让它执行任意命令、看你的会话记录。只在完全信任的网络里这么用，用完改回默认。

### 8.7 控制 Linux 桌面（ui.py）

`ui.py` 是给 X11 桌面用的另一个工具，能力比 `adui.py` 弱（因为 Linux 没有元素树），主要靠截图 + OCR 定位。

依赖在 8.3 已经装过（`xdotool` + `imagemagick`）。确认一下：

```
which xdotool convert
```

两个都有路径输出就能用。然后：

```
python3 ui.py look
```

按它输出的提示操作：`ui.py click 文字`、`ui.py type 内容`、`ui.py key ctrl+t`。

`webchat.py` 会自动检测 `ui.py` 在不在，在的话就能通过对话让它操作桌面。

### 8.8 检查点

| 检查 | 命令 | 期望 |
|---|---|---|
| Python 版本 | `python3 --version` | 3.8 以上 |
| 文件齐全 | `ls ~/work/static` | 三个文件 |
| key 生效 | 启动横幅有「配置 .../env」 | — |
| 界面能开 | 浏览器 `http://127.0.0.1:8765` | 正常显示 |
| 局域网能连 | 另一台设备访问 `http://IP:8765` | 正常显示 |

---

## 第 9 章 日常怎么用

### 9.1 每天启动，三步

```
cd ~/work
termux-wake-lock
python3 webchat.py
```

嫌麻烦就写成一个脚本，以后一句 `sh ~/start.sh`：

```
cat > ~/start.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/work
python3 webchat.py
EOF
chmod +x ~/start.sh
```

**这几条在干什么**：`cat > 文件 <<'EOF' ... EOF` 是把中间那几行原样写进文件（这是终端里写文件的标准做法，`'EOF'` 加引号是为了不让 `$` 被提前替换）。最后 `chmod +x` 给它执行权限。

以后启动：

```
sh ~/start.sh
```

**Linux 上把 shebang 改成** `#!/bin/sh`，其余不变。

### 9.2 让它后台跑（可选）

想一边用手机一边让它跑，可以放后台：

```
cd ~/work && nohup python3 webchat.py > ~/webchat.log 2>&1 &
```

**这行在干什么**：`nohup` 让它在终端关掉后继续跑，`>` 把输出写进日志，`&` 放后台。

看日志：

```
tail -f ~/webchat.log
```

停止：

```
pkill -f webchat.py
```

Termux 里没有 `pkill` 的话先 `pkg install -y procps`。

> [!NOTE] 后台模式有个坑：安卓可能在你不知道的时候杀掉它，而你看不到报错。不确定的时候别放后台，前台跑着，日志一眼就能看见。

### 9.3 更新到新版

```
cd ~/work
sh update.sh
```

一句话。它会：

- 逐个比对远端和本地，内容一样就跳过（不写盘、不产生 `.bak`）
- 变了的文件先下到临时目录，校验非空才替换
- `.py` 和 `.sh` 先做语法检查，坏的直接拒绝写入，旧文件原样保留
- 第一个镜像不通自动换下一个

想先看有什么变化、不下载：

```
sh update.sh --list
```

只更新某一个：

```
sh update.sh webchat.py
```

更新完记得重启服务，不然跑的还是内存里的旧代码。

### 9.4 备份和迁移

| 想备份什么 | 命令 |
|---|---|
| 全部对话 | `cp ~/.local/share/webchat/sessions.db ~/sessions-$(date +%m%d).db` |
| 程序和配置 | `tar czf ~/kit-$(date +%m%d).tgz -C ~ work .config/webchat` |
| 只有代码 | 重新跑 `sh update.sh` 就行，不用备份 |

**换手机**：
1. 新手机装好 Termux、Python、拉好代码
2. 把旧手机的 `sessions.db` 拷到新手机同样的路径
3. 重新写一遍 `~/.config/webchat/env`（key 不要用旧文件传，重打一遍更安全）

### 9.5 目录说明

| 路径 | 是什么 | 能删吗 |
|---|---|---|
| `~/work/` | 程序和 `static/` | 删了要重下 |
| `~/work/static/` | 网页三件套 | **不能删**，删了界面打不开 |
| `~/.config/webchat/env` | key 和配置 | 删了要重配 |
| `~/.local/share/webchat/sessions.db` | 所有对话记录 | 删了历史全没，慎删 |
| `~/.tessdata/` | OCR 语言模型 | 删了中文认不出 |
| `~/webchat.log` | 后台日志 | 可删 |
| `~/work/*.bak` | 更新前的旧版本 | 确认新版没问题后可删 |

---

## 第 10 章 出问题怎么查

### 10.1 三步自检

**遇到任何问题，先跑这三步，八成能自己解决。**

**第一步：看它是死是活**

```
python3 webchat.py --mock
```

`--mock` 不花钱、不依赖 key、不依赖网络。它能起来，说明程序和前端没问题，问题在 key 或网络。

**第二步：看依赖**

```
python3 webchat.py --no-db
```

`--no-db` 跳过数据库。它能起来、加了 `--mock` 又起不来，说明数据库文件坏了（可以改名后重试，程序会重建）。

**第三步：看控屏链路**

```
python3 adui.py doctor
```

只在你用控屏功能时跑。它会把 adb、设备状态、端口扫描全过一遍。

### 10.2 错误信息对照表

按你看到的**原文**查。左边是报错里的一段字，不是全部。

| 你看到的 | 原因 | 怎么办 |
|---|---|---|
| `command not found: python3` | 没装 Python | 第 2 章 |
| `command not found: adb` | 没装 android-tools | `pkg install -y android-tools` |
| `can't open file 'webchat.py'` | 不在对的目录 | `cd ~/work` 再跑。用 `pwd` 看自己在哪 |
| `缺少 static 目录` | 前端文件没下 | 补下 `static/` 三个文件 |
| `缺少 DEEPSEEK_KEY` | key 没配好 | 检查 `~/.config/webchat/env` |
| `Address already in use` | 端口被占 | `pkill -f webchat.py`，或换 `--port 8800` |
| `ERR_CONNECTION_REFUSED` | 服务没起 | 看终端有没有报错，服务是否还活着 |
| 页面一片空白 | 浏览器缓存 | 关标签页重开 |
| `E: Unable to locate package` | 软件列表过期 | `pkg update` 后重试 |
| `No space left on device` | 存储满 | `df -h` 看哪个分区，清理 |
| `Error: externally-managed-environment` | Linux 上的 pip 保护 | 改用 `apt install python3-xxx` |
| `protocol fault (couldn't read...)` | 配对端口用错 | 用弹窗里的端口，不是主页面的 |
| `device offline` | 连接过期 | `python3 adui.py doctor` |
| `unauthorized` | 没授权调试 | 手机上点「允许」，勾「一律允许」 |
| `Connection refused`（配对时） | 弹窗过期（2 分钟） | 重开弹窗，30 秒内敲完 |
| `adb: not supported` | 用了 `adb mdns` | 改用 `python3 adui.py scan` |
| `tesseract: command not found` | 没装 OCR | `pkg install -y tesseract` |
| `Error opening data file ... chi_sim` | 中文模型缺失 | 第 7.3 节下载 |
| `image file is invalid` | 图片路径错或文件坏了 | 用绝对路径，先 `ls` 确认文件在 |
| 回复卡住不动 | 模型接口超时 | 点停止，重发；或换网络 |
| 一直提示「已达上限」 | 单条消息步数用完 | 说「继续」，或新开一条 |
| 中文输入乱码 | 没配输入法 | `python3 adui.py ime-install` |

### 10.3 日志在哪看

| 场景 | 怎么看 |
|---|---|
| 前台运行 | 报错直接打在终端上，往上翻 |
| 后台运行 | `tail -50 ~/webchat.log` |
| 网页出问题 | 浏览器长按页面 → 检查 → 控制台（手机 Chrome 可用 `chrome://inspect` 从电脑看） |
| adb 细节 | `adb devices -l`，或 `python3 adui.py info` |

### 10.4 什么时候该问人

自己排查的顺序建议是：

1. 把报错**原文**复制下来（不要凭印象描述）
2. 在 10.2 的表里搜关键词
3. 搜不到的，把这三样发出来问：**你敲的命令**、**完整报错**、**`python3 --version` 和 `uname -a` 的输出**

只发一句「跑不起来」没人能帮你。三样齐了，基本一眼能定位。

> [!WARN] 发截图或日志前，**先把 key 遮掉**。报错信息里有时会带出 `DEEPSEEK_KEY=sk-...` 那一行。

---

## 附录 A 命令速查

### 安装与更新

| 目的 | 命令 |
|---|---|
| 换镜像源 | `termux-change-repo` |
| 刷新软件列表 | `pkg update` |
| 装 Python | `pkg install -y python` |
| 装 adb | `pkg install -y android-tools` |
| 装 OCR 三件套 | `pkg install -y tesseract poppler python-pillow` |
| 一键更新 | `cd ~/work && sh update.sh` |
| 只看版本差异 | `sh update.sh --list` |

### 启动

| 目的 | 命令 |
|---|---|
| 演习模式（不花钱） | `python3 webchat.py --mock` |
| 正常启动 | `python3 webchat.py` |
| 换端口 | `python3 webchat.py --port 8800` |
| 允许局域网访问 | `python3 webchat.py --host 0.0.0.0` |
| 不存历史 | `python3 webchat.py --no-db` |
| 停止 | Ctrl+C（音量减 + C），或 `pkill -f webchat.py` |

### 控屏（adui.py）

| 目的 | 命令 |
|---|---|
| 一键修复连接 | `python3 adui.py doctor` |
| 扫端口并连接 | `python3 adui.py scan` |
| 配对 | `python3 adui.py pair 127.0.0.1:端口 配对码` |
| 看设备信息 | `python3 adui.py info` |
| 看屏幕元素 | `python3 adui.py look` |
| 点第 N 个 | `python3 adui.py tap 3` |
| 点坐标 | `python3 adui.py tap 540 1200` |
| 按文字点 | `python3 adui.py tap-text 设置` |
| 输入中文 | `python3 adui.py text "内容"` |
| 按键 | `python3 adui.py key back`（back/home/enter/delete） |
| 滑动 | `python3 adui.py swipe 540 1600 540 600` |
| 滚动 | `python3 adui.py scroll down 3` |
| 截屏 | `python3 adui.py shot ~/work/s.png` |
| 截屏识别 | `python3 adui.py ocr` |
| 启动 App | `python3 adui.py start com.tencent.mm` |
| 列 App | `python3 adui.py apps 微信` |
| 装中文输入法 | `python3 adui.py ime-install` |

### OCR（ocr.py）

| 目的 | 命令 |
|---|---|
| 自检 | `python3 ocr.py doctor` |
| 纯文字 | `python3 ocr.py 图.png` |
| 带坐标 | `python3 ocr.py 图.png --boxes` |
| JSON | `python3 ocr.py 图.png --json` |
| 只认一块 | `python3 ocr.py 图.png --crop 80,400,1000,900` |
| 小字放大 | `python3 ocr.py 图.png --scale 2` |
| PDF | `python3 ocr.py 文档.pdf --dpi 150` |
| PDF 指定页 | `python3 ocr.py 文档.pdf --first 1 --last 3` |

### 逆向（rev.py）

| 目的 | 命令 |
|---|---|
| 一屏摘要 | `python3 rev.py triage 文件` |
| 字符串 | `python3 rev.py strings 文件 --grep http` |
| APK 信息 | `python3 rev.py apk 应用.apk` |
| so 文件 | `python3 rev.py elf 库.so` |
| 十六进制 | `python3 rev.py hexdump 文件 --off 0x1000 --len 256` |
| 反汇编 | `python3 rev.py r2 文件 pdf @ main` |

---

## 附录 B 文件清单

| 文件 | 字节 | 干什么 |
|---|---|---|
| `webchat.py` | 45068 | 网页服务 + 对话循环 + 工具执行 |
| `static/app.html` | 5110 | 网页骨架 |
| `static/app.css` | 22706 | 样式，含深色模式 |
| `static/app.js` | 35216 | 前端逻辑：会话、流式渲染、Markdown |
| `adui.py` | 47304 | 安卓控屏 |
| `ocr.py` | 33777 | 本地 OCR |
| `rev.py` | 28616 | 二进制侦察 |
| `ui.py` | 16329 | Linux 桌面控屏（仅虚拟机） |
| `update.sh` | 8559 | 一键更新 |
| `MANUAL.html` | 69250 | 速查版手册 |

---

## 附录 C 安全边界

这套东西的权限**很大**，说清楚它到底能做什么：

| 能力 | 意味着 |
|---|---|
| 执行任意 shell 命令 | 它能删除你的文件、改系统设置、装软件。它不会主动这么干，但你要知道有这个能力 |
| ADB 全权限 | 能点任何界面、读任何屏幕内容、安装卸载应用 |
| 读工作目录所有文件 | 包括你放在 `~/work` 里的 apk、截图、文档 |
| 会话库存明文 | `sessions.db` 是你在这台机器上干过的所有事的完整记录 |
| 网页界面无密码 | `--host 0.0.0.0` 时，同网段任何人打开浏览器就能指挥它 |

几条硬建议：

1. **`HOST` 保持默认的 `127.0.0.1`**，除非你清楚局域网里都有谁
2. **key 不要贴在聊天里、不要提交到 git**，泄露后立刻去后台删掉重建
3. **`sessions.db` 别乱传**，里面有你的目录结构、文件名、命令历史
4. 重要操作前让它先 `look` 确认，别一句「把照片全删了」扔过去

---

<footer>这份手册对应 agent-kit v2（2026.11.19）。命令有变化以 <code>python3 脚本名 --help</code> 为准。</footer>
