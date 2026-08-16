# PyMusic 缺失功能清单 & 桌面歌词 Wayland 置顶方案

## 一、缺失功能（按优先级）

### 第一梯队（播放器基本盘）
4. **歌单管理** —— 创建/删除歌单、收藏夹、导入导出 `.m3u/.pls`

### 第二梯队（体验增强）
5. **本地曲库搜索/过滤** —— 歌单顶部搜索框（按歌名/歌手过滤）
6. **浏览视图** —— 按专辑/艺术家分组浏览
7. **歌词偏移调整** —— 一键 ±0.5s 微调并持久化（offset 标签或存配置）
8. **播放速率** —— ffplay `-af atempo` 即可
10. **迷你模式** —— 悬浮小窗（封面 + 进度 + 控制），QML 第二窗口成本低

### 第三梯队（进阶）
11. **均衡器/音效** —— ffplay `-af equalizer=...` 10 段 EQ + 低音增强
12. **睡眠定时器** —— 播 N 分钟后自动停止
13. **播放历史/最爱/统计** —— 播放次数、最近播放、常听
14. **桌面歌词**（见下文详细方案）
15. **标签编辑** —— 改 ID3/FLAC 标题/歌手/封面
16. **输出设备选择** —— pactl set-default-sink
17. **文件增量监听** —— QFileSystemWatcher/inotify 自动刷新曲库
18. **快捷键自定义 + 多语言（i18n）**

### 建议顺序
播放模式 → MPRIS → 播放队列 → 歌单；之后按需做 5、7、10、14。

---

## 二、桌面歌词：Qt6 + Wayland 置顶解决方案

### 0. 结论速览（KDE Plasma 6 Wayland + Qt 6.11 实测/资料）

| 方案 | 置顶 | 点击穿透 | 依赖 | 适用范围 |
|---|---|---|---|---|
| **① LayerShellQt（layer-shell）** | ✅ 真置顶（Overlay 层） | ✅ 原生 | C++ 编译 `layer-shell-qt` | **KDE 首选**；wlroots 系可用 |
| **② XWayland 辅助进程** | ✅（`_NET_WM_STATE_ABOVE`） | ✅（`WindowTransparentForInput`） | 纯 Python | **跨桌面保底**（KDE/GNOME 通用） |
| **③ `Qt.WindowStaysOnTopHint`** | ❌ 原生 Wayland **无效** | — | 无 | 仅 X11 会话可用，Wayland 下弃用 |
| **④ KWin 手动置顶**（右键 Keep Above / 窗口规则） | ✅ | — | 无 | 用户侧操作，程序无法控制 |

### 1. 方案①：LayerShellQt —— KDE 原生正解（推荐）

**原理**：KWin 实现了 `wlr-layer-shell` 协议（koverlay 在 KDE Plasma Wayland 实测通过；
KDE 开发者推荐 `layer-shell-qt`）。layer-shell 窗口由合成器放入指定"层"，
Overlay 层天然位于所有普通窗口之上，不受 xdg-shell 限制。

**关键 API**（C++，Qt 6）：

```cpp
// 在 QQuickWindow 创建后挂接 layer-shell：
auto shell = LayerShellQt::Shell::getLayerShell(window);
shell->setLayer(LayerShellQt::Shell::LayerOverlay);   // 置顶（非 KWin 可退 LayerTop）
shell->setAnchors(AnchorLeft | AnchorRight | AnchorBottom); // 锚定到屏幕底边
shell->setKeyboardInteractivity(LayerShellQt::Shell::KeyboardInteractivityNone); // 不抢键盘
// 点击穿透：窗口级 flag
window->setFlags(window->flags() | Qt::WindowTransparentForInput);
// 多屏：setScreenName / setOutput 指定输出
```

**本项目落地形式**（LayerShellQt 无 PySide6 绑定）：
- 新增一个小的 C++ 歌词窗口程序（koverlay 同款：QML + LayerShellQt）
- 主进程（Python）→ 歌词进程：`QLocalSocket` 推送 `{当前行文本, 前后行, 位置}`
- 优点：KDE 原生真置顶、真穿透、多屏/锚定原生支持、无 XWayland 缩放劣化
- 缺点：需要编译一次 C++ 辅助程序（打包进 AppImage 或作为可选组件）

### 2. 方案②：XWayland 辅助进程 —— 跨桌面保底（纯 Python）

**原理**：X11 的 `_NET_WM_STATE_ABOVE` 置顶状态被 KWin 与 GNOME Mutter 都遵守；
辅助进程用 `QT_QPA_PLATFORM=xcb` 启动即走 XWayland。

```python
# 歌词辅助进程（独立进程, QT_QPA_PLATFORM=xcb 启动）
window.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
window.setAttribute(Qt.WA_TranslucentBackground)  # 或 QML color:"transparent"
# 穿透:
window.setFlag(Qt.WindowTransparentForInput)
# 与主进程: QLocalSocket 传歌词数据
```

- 优点：纯 Python 零编译、KDE/GNOME 通吃
- 缺点：双进程同步、XWayland 缩放模糊风险、GNOME 下置顶可靠性一般

### 3. 合成器检测与按钮适配

```python
@Property(bool, constant=True)
def isKde(self):
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")

@Property(bool, constant=True)
def isGnome(self):
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "")
```

- **GNOME 原生 Wayland：隐藏置顶按钮**（layer-shell 与 hint 都无效，
  按钮存在只会误导）；仅当走方案②（xcb）时按钮可见
- KDE：方案①下置顶按钮始终可用；方案②下也可用

### 4. 输入穿透要点
- `Qt.WindowTransparentForInput` → QtWayland 映射 `wp_input_region`
  （输入区域为空 = 点击穿透），KWin 支持
- 默认穿透不挡操作；托盘菜单"锁定/解锁"切换（解锁时可拖动换位置）

### 5. 自定义顶栏右键菜单（KDE 风格"置顶"等）

**需求**：KDE 原生顶栏右键有"More Actions → Keep Above Others"，本应用是
无边框自定义顶栏——在自定义顶栏右键弹出同等菜单（QtQuick.Controls `Menu`）：
最小化 / 最大化 / **置顶（勾选态）** / 关闭。

**置顶 toggle 的分环境实现**（KWin 公共 DBus 无 keepAbove 方法，已实测；
PySide6 不提供 QtWaylandClient，无法纯 Python 绑 plasma-window-management）：

| 环境 | 实现方式 | 生效 |
|---|---|---|
| X11 / XWayland | `window.flags` 切换 `Qt.WindowStaysOnTopHint`（先 hide 再 show 应用 flags） | ✅ 即时（_NET_WM_STATE_ABOVE） |
| **KDE Wayland（原生）** | 引导式：菜单点击 → 提示框 → 一键打开 `systemsettings kcm_kwinrules`，指导添加规则 `Keep above others: Force`；程序在配置中记忆"置顶请求"状态用于勾选显示 | ✅ 规则生效后永久 |
| KDE Wayland（进阶） | 编译小 C++ 扩展（QWaylandClientExtension 绑 `org_kde_plasma_window_management`，`request_state(KEEP_ABOVE)`） | ✅ 即时（与 LayerShellQt 同技术栈） |
| GNOME Wayland | 置顶菜单项**隐藏**（无任何可用接口） | — |

> 说明：KWin 的"右键置顶"是 KWin 内部状态；公共 DBus（org.kde.KWin）只暴露
> 桌面/窗口信息查询，无 keepAbove 方法（已在本机实测）。程序内真正即时置顶
> 只有两条路：X11 flags（X 会话）、或 C++ 扩展走 plasma-window-management 协议。

### 6. 落地建议
1. **首选方案①**（KDE 原生 LayerShellQt，C++ 辅助进程）
2. 不愿引入 C++ → 方案②（xcb 纯 Python）
3. 都加：穿透 + 托盘锁定切换 + 位置记忆（多屏 x/y）+ 样式
   （圆角半透明条 + 文字阴影，复用本项目透明/圆角经验）
4. 渲染简化：仅"当前行高亮 + 前后行淡色"，不做弹簧动画
5. 顶栏右键菜单：X11 走 flags；KDE Wayland 走"引导窗口规则"；
   GNOME 隐藏置顶项

> 参考资料：
> - KDE Discuss 3106 — KDE 开发者确认 xdg-shell 不支持置顶，正解 layer-shell-qt
> - github.com/erik96/koverlay — Qt6+QML+LayerShellQt 在 KDE Plasma Wayland 的完整实现
> - JetBrains/compose-multiplatform#4518 — 确认 KWin 实现 wlr-layer-shell
> - QTBUG-73456 — Qt Wayland WindowStaysOnTopHint 相关

