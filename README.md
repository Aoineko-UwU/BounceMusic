# BounceMusic（Q弹音乐）

让桌面上的图片跟着音乐节奏“Q弹”起来。播放歌曲后，BounceMusic 会从正在播放的声音里寻找鼓点与节拍，让图片压扁、回弹，也可以选择左右翻转。

![Q弹音乐动态展示](assets/readme-animation.gif)

[下载最新版](https://github.com/Aoineko-UwU/BounceMusic/releases/latest) · [查看各版本更新](CHANGELOG.md) · [查看详细使用说明](使用说明.txt) · [反馈问题](https://github.com/Aoineko-UwU/BounceMusic/issues)

## 它能做什么

- **跟着节奏弹跳**：图片会随音乐压扁、回弹。等待播放时以呼吸闪烁提示，开始分析时显示加载动图，确定 BPM 后可闪色并显示文字；颜色、呼吸频率和文字时长都能调整。
- **选择要听的声音**：Windows 11 可自动查找正在播放声音的进程，也能手动选择软件；Windows 10 可选择扬声器或耳机等播放设备。网易云音乐、QQ 音乐等播放器都可以尝试使用。
- **用自己的图片**：可一次导入多张图片，或直接选用内置图片。非正方形图片导入时会居中裁成正方形；在“我的图片”中右键可删除已导入的副本，原文件不会被删除。
- **同时显示多个 Q弹窗口**：每张图片都能拖动、用滚轮缩放、单独关闭。可以让所有窗口使用同一张图，也可以分别选图；窗口共用同一套节奏。
- **调出喜欢的效果**：可调动画幅度、帧率（最高 144 帧）、最高弹跳速度，以及平面的水平翻转动画。主菜单可调整翻转 BPM 阈值，快歌每压扁两次再翻转；节奏复杂的歌曲不建议启用。右键图片也可启用或禁用翻转。

- **节奏不准时可校正**：可以刷新 BPM、立即对齐节奏、临时提前或延后动画，也能输入已知 BPM。鼠标中键可快速对齐并显示一道光泽；Shift + 左键提前一点，Shift + 右键延后一点，Shift + 中键恢复自动，这些操作也能在右键菜单找到。BPM 旁的 ×2 / ÷2 可修正半速、倍速判断，不写入学习记录。选择“应用并学习”或在歌曲结束时填写真实 BPM，可留下本机校准样本。
- **方便放在桌面上用**：支持图片置顶、浅色/深色界面、系统托盘、关闭窗口行为设置，以及在“关于”中检查并下载更新。

达到翻转阈值后，如果翻转落在了不舒服的拍位，可点“快进一拍”调整翻转分组；BPM 保持不变，也不会写入学习记录。主窗口宽度固定，高度可调；底部运行信息始终可见，不随内容滚动。

## 安装

适用于 **Windows 10/11 64 位**。打开 [Releases 下载页](https://github.com/Aoineko-UwU/BounceMusic/releases/latest)，选择下面一种方式即可：

| 方式 | 下载哪个文件 | 怎么打开 |
| --- | --- | --- |
| 安装版（推荐） | 名称含 `Setup-win64.exe` | 双击安装包，按提示安装，再从桌面或开始菜单打开“Q弹音乐”。以后可以在 Windows 设置中卸载。 |
| 便携版 | 名称以 `-win64.zip` 结尾 | 把 ZIP **完整解压**到一个文件夹，再双击其中的 `BounceMusic.exe`。移动程序时要连同 `_internal` 文件夹一起移动。 |

两种包都附带《使用说明.txt》。便携版无需安装；请不要直接在压缩包里双击运行程序。

### 第一次使用

1. 在音乐软件中播放一首歌。
2. 在 BounceMusic 主页面选择音频来源：Windows 11 可点“自动查找播放进程”，确认选中的确是音乐软件；也可手动选进程。Windows 10 请选“播放设备”，并选正在使用的扬声器或耳机。
3. 点“开始监听”。程序需要一小段音乐来判断节奏；识别稳定后会显示 BPM，图片开始弹跳。
4. 想换图时，先点“导入图片”添加自己的图片，再点“选择图片”使用它；也可以直接选预设图。点“新增Q弹”可多开图片窗口。

建议使用 512×512～768×768 或更低分辨率的图片，过大的原图会增加导入、解码等开销。小屏幕上可滚动主菜单查看下方选项。

如果画面跟拍不准，先试“立即对齐节奏”；BPM 明显不对时点“刷新 BPM”，或在“手动 BPM”中输入已知数值。单首歌确定BPM后可以使用“节奏微调”来细调播放音轨。更多操作见 [使用说明.txt](使用说明.txt)。

> 播放设备模式会听到该设备的**全部输出声音**，包括其他软件的提示音。自动查找也可能选中正在发声的其他程序，请在开始监听前确认来源。

## 工作原理

```mermaid
flowchart LR
    A["音乐软件进程 / 播放设备"] --> B["实时获取音频"]
    B --> C["寻找鼓点等起音"]
    C --> D["估计 BPM 与节拍位置"]
    D --> E["持续检查对齐"]
    E --> F["驱动图片压扁、回弹和翻转"]
```

1. **获取音频**：选进程时使用 ProcTap 捕获该进程的声音；选播放设备时使用 WASAPI 回环捕获设备输出。Windows 10 普通客户端版本不支持当前使用的单进程捕获接口，因此以播放设备模式为主。
2. **寻找节奏**：程序按短时间片分析频谱，关注低频和中频能量的突然变化，从中寻找鼓点等明显的起音；再用自相关和周期性分析估计 BPM，并比较半速、倍速等候选。
3. **对齐动画**：估计节拍位置后，程序按节拍驱动连续的压扁与回弹；播放中可按设置的频率检查 BPM 和节拍偏移。快歌会限制视觉弹跳速度；翻转的两次压扁分组也来自同一音频节拍网格，重新对齐会同步更新。翻面使用横向缩放，呼吸和光泽在保留图片透明通道的前提下处理颜色。
4. **保存设置与校准**：设置和用户填写的真实 BPM 样本保存在本机。主观评分会记录下来；实际用于后续 BPM 候选校准的是用户提供的真实 BPM。捕获到的声音只用于实时分析，不会保存为音频文件。

选择网易云音乐或 QQ 音乐进程时，如果播放器向 Windows 提供媒体会话，程序会参考播放、暂停和曲目变化状态；没有提供时则通过音频静音情况判断。不同歌曲对“主拍”和“半拍”的理解可能不同，歌词或复杂混音也可能干扰鼓点识别，因此自动分析不能保证每首歌都完全准确。

## 更新下载线路

“关于 → 下载线路与测速”及更新弹窗均可选择自动线路、GH-Proxy、GHFast、GHProxy.net 或 GitHub 直连。测速小量读取真实安装包，显示参考速度、响应时间和当前可用性；“自动选择”优先使用实测较快的线路，也可关闭失败自动换线。

下载窗口显示当前线路、速度、进度和预计剩余时间，可暂停、继续、中断或切换线路。换线时尽量续传；服务器不支持时会提示重新下载。失败后可换线路直接重试。版本信息和 SHA-256 仍从 GitHub 官方获取，每个下载包均验证完整性。

## 从源码运行与构建

需要 Windows 10/11 64 位、Python 3.12。在仓库根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\app.py
```

构建便携文件夹与安装器需要 Inno Setup 6：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建结果位于 `dist/`。仅构建便携文件夹可加 `-SkipInstaller`；编译器不在默认位置时可用 `-InnoCompiler` 指定 `ISCC.exe`。仓库 `packages/` 中的便携 ZIP 使用 Git LFS 管理；克隆源码后如需取得历史 ZIP，请安装 Git LFS 并运行 `git lfs pull`。只想使用软件的用户直接从 Releases 下载即可。

| 位置 | 作用 |
| --- | --- |
| [`src/app.py`](src/app.py) | 主界面、音频分析、节拍与图片动画 |
| [`src/animation.py`](src/animation.py) | 翻转节拍分组、平面翻转与保留透明区域的反馈效果 |
| [`src/shortcuts.py`](src/shortcuts.py) | 固定鼠标组合键与对应操作 |
| [`src/media_status.py`](src/media_status.py) | 可用时读取 Windows 媒体会话的播放状态 |
| [`src/updater.py`](src/updater.py)、[`src/updater.ps1`](src/updater.ps1) | 检查更新、下载校验与替换程序 |
| [`src/download_routes.py`](src/download_routes.py)、[`src/update_ui.py`](src/update_ui.py) | 多线路测速、续传、换线及两个版本共用的更新界面 |
| [`assets/`](assets)、[`installer/`](installer) | 内置图片、图标与安装器配置 |
| [`tests/`](tests) | 节奏、界面和更新流程的检查 |

运行时的 `设置.json` 和导入图片的 `图片/` 文件夹位于程序目录，属于个人数据，不会提交到仓库。更新程序时会尽量保留这些数据。

## 参考与第三方组件

- [ProcTap](https://github.com/m96-chan/ProcTap)：按进程捕获音频；项目使用其 Python 包，许可证见 [ProcTap-LICENSE.txt](third_party/ProcTap-LICENSE.txt)。
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)：通过 WASAPI 回环获取播放设备的输出声音。
- [Microsoft Windows 媒体会话 API](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager)：可用时读取播放器的播放状态与曲目信息。
- [librosa 节奏分析教程](https://librosa.org/doc/latest/auto_tutorials/01-intro/06-rhythm.html)：起音、速度与节拍位置分析的思路参考；BounceMusic 采用自己的实时实现，**不依赖** librosa 运行。

项目作者：葵猫猫（[B站](https://space.bilibili.com/200696277) · [GitHub](https://github.com/Aoineko-UwU)）。这是 AI 辅助开发的个人项目；遇到问题或有改进建议，欢迎在 [Issues](https://github.com/Aoineko-UwU/BounceMusic/issues) 反馈。
