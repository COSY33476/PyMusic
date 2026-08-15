# PyMusic (MusicPlayer2 - Py)

基于 **PySide6 + QML** 的 Linux 本地音乐播放器，内核使用 `ffplay`，支持网易云在线歌词/封面下载、双语歌词、模糊背景与无边框圆角界面。

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-GPLv3-green)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)

## 功能特性

### 播放内核
- `ffplay` 子进程播放：暂停（SIGSTOP）/续播、精确 seek、自动切歌、异常文件保护
- PulseAudio/PipeWire 无缝音量调节（`pactl`），无 PA 时自动回退
- 恢复上次播放位置；时长异步加载，不阻塞 UI

### 歌词
- 本地 `.lrc` 与音频内嵌歌词（ffprobe 提取）
- 双语对照：原文/译文按时间戳分组、贴靠显示
- 弹簧错落滚动动画、行序保护（不交叉不堆叠）、大跳转瞬间归位
- 滚轮手动浏览（3 秒自动回中），行间距可调

### 在线功能（网易云）
- 搜索歌曲、下载歌词（自动合并翻译为双语 LRC）、下载封面
- 下载覆盖保护：歌词/封面/设置均保留 **两级历史备份**（`.bak1`/`.bak2`），设置面板提供"回退上次设置"按钮

### 界面
- 无边框窗口 + 内部顶栏（最小化/退出）+ 圆角（OpacityMask 遮罩，背景图正确裁切）
- 封面模糊背景 + 双层渐变过渡；深色/亮色主题、自定义颜色、面板透明度
- 全局字体（QGuiApplication 级下发，全 UI 生效）
- 系统托盘、关闭到托盘、全局滚轮音量、键盘快捷键

### 其他
- 曲库扫描缓存（`~/.cache/PyMusic`，二次启动毫秒级），root 启动保护
- 单实例：重复启动时直接终止旧实例并接管
- 背景任务线程化（网络/ffprobe 不卡 UI），退出竞态防护

## 依赖

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | |
| PySide6 | Qt for Python |
| requests | 网易云 API |
| ffmpeg / ffplay / ffprobe | 播放、封面/歌词/时长提取（必需） |
| pactl | 可选，PulseAudio/PipeWire 音量 |

```bash
# 对于源码
pip install PySide6 requests
# 或者
pip3 install PySide6 requests
```

## 运行

```bash
python3 /path/to/main.py
# 或者
python /path/to/main.py
```

- X11 / KDE Wayland：无边框圆角界面
- 其他 Wayland 合成器（GNOME 等）：自动回退原生顶栏
- 也可强制 XWayland：`QT_QPA_PLATFORM=xcb python3 main.py`

## 目录与缓存

| 位置 | 内容 |
|---|---|
| `~/.config/PyMusic/PyMusic.config` | 设置（写盘前自动备份 `.bak1`/`.bak2`） |
| `~/.cache/PyMusic/scan_*.json` | 曲库扫描缓存（按目录哈希） |
| `~/.cache/PyMusic/instance.pid` | 单实例 PID |
| 歌曲目录 | 下载的 `.lrc`/封面（覆盖前备份 `.bak1`/`.bak2`） |

## 回退说明

- 设置：设置面板底部"回退上次设置"按钮（最多连续回退两次）
- 歌词/封面：把 `.bak1` 改回原名即可恢复

