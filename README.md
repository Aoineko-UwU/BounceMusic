# Q弹音乐 / BounceMusic

全体保持Q弹！

Windows 11 便携桌面动画程序，监听指定应用进程或播放设备，根据音频中的节奏驱动自定义图片进行压扁与回弹。

纯AI项目，仅供自用和参考，请谅解

## 下载和使用

`packages/QBounceMusic-v7-portable.zip` 为 Windows x64 便携包，解压后运行 `BounceMusic.exe`；请保留 `_internal` 文件夹。仓库使用 Git LFS 管理压缩包，克隆时请先安装 Git LFS 并执行 `git lfs install`；已有克隆可以执行 `git lfs pull`。

网易云音乐：先播放音乐，点击“自动查找网易云”，找到进程后点击“开始监听”。也可以选择其他进程或播放设备。导入透明 PNG 后可以拖动图片、滚轮缩放、设置置顶、帧率、动画幅度和节奏偏移。右键图片或托盘图标可打开设置。

节奏为实时估算，高速音乐会限制视觉触发频率。BPM 可能出现半拍或倍拍；有歌词的复杂混音、受保护音频和某些特殊播放器可能影响识别或捕获。负偏移在当前版本中只是调整已检测到的事件时间，无法真正提前预测未来的鼓点。可选反馈使用静音检测推测结束，并非识别歌曲元数据。

## 从源码运行和构建

需要 Windows x64、Python 3.12 以及可以访问 PyPI 的网络。PowerShell 中运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python src\app.py
```

构建便携文件夹：`powershell -ExecutionPolicy Bypass -File .\build.ps1`。输出位于 `dist/BounceMusic`，移动或分发时请保留整个文件夹。

运行设置保存在程序目录的 `设置.json`；该文件、本机图片和构建产物不会加入 Git。Portable 包不含个人设置。

## 第三方组件

进程音频捕获使用 ProcTap（MIT），许可证见 `third_party/ProcTap-LICENSE.txt`。其余依赖及各自许可证随相应 Python 包分发；便携包中的 `_internal` 保留 PyInstaller 收集的许可证文件。
