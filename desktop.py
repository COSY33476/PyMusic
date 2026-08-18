#!/usr/bin/env python3
"""desktop.py - 桌面歌词（透明置顶窗口）

独立于 main.py 的桌面歌词层：创建一个小型、无边框、透明的置顶 QML 窗口，
实时显示当前播放歌词，与主窗口共用同一 QApplication。

用法:
  from desktop import DesktopLyrics
  lyrics = DesktopLyrics(player)
  lyrics.show() / lyrics.hide() / lyrics.setEnabled(True/False)
  python3 desktop.py            # 独立自测（内置假歌词）

Wayland 说明:
  Wayland 协议不允许客户端自我置顶/查询或设置自己窗口的全局坐标，
  Qt.WindowStaysOnTopHint / setPosition 在 Wayland 下会被合成器忽略。
  因此：
  - 置顶：不做运行时脚本注入，请引导用户在系统设置 → 窗口管理 →
    窗口规则 里配置"窗口标题 = 桌面歌词 → 在其它窗口之上 = 强制"。
  - 位置（拖动后保存 / 启动恢复）：借道运行在合成器内部的 KWin 脚本，
    通过 org.kde.KWin D-Bus 接口注入一次性脚本，脚本内按标题匹配窗口
    读写 frameGeometry，并用 callDBus 把真实坐标回调给本进程注册的
    org.pymusic.DesktopLyric D-Bus 服务（_PositionReceiver）。
    仅在 KDE + Wayland 且 PySide6.QtDBus 可用时启用，任何一环缺失
    静默降级（位置退回默认摆位），不影响其它功能。

鼠标穿透 + 拖动:
  "锁定歌词"开关（设置面板，持久化 desktopLyricLocked）决定窗口是否
  点击穿透：锁定 = 不可交互不可拖动；取消锁定 = 左键拖动窗口
  （QML 侧 startSystemMove）、右键弹出自绘菜单（置顶开关 / 隐藏）。
"""

import os
import sys
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Signal, Slot, Property, QUrl, Qt, ClassInfo
from PySide6.QtQuick import QQuickView
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu
try:
    from PySide6.QtDBus import QDBusConnection
    _HAVE_QTDBUS = True
except Exception:
    _HAVE_QTDBUS = False

# 加入入口目录，保证能找到同目录的 main.py（自测时才需要）
_HERE = Path(__file__).resolve().parent
_QML_PATH = _HERE / "desktop.qml"

# 供 KWin 窗口规则匹配的窗口类/标题关键词
WINDOW_CLASS_HINT = "desktoplyric"
WINDOW_TITLE_HINT = "桌面歌词"

# 调试日志：默认关闭，设 PYMUSIC_DESKTOP_LYRIC_DEBUG=1 打开
_DEBUG = os.environ.get("PYMUSIC_DESKTOP_LYRIC_DEBUG") == "1"


def _dlog(msg):
    if not _DEBUG:
        return
    ts = time.strftime("%H:%M:%S")
    print("[desktop][%s] %s" % (ts, msg), file=sys.stderr, flush=True)


def _run_qdbus(args, timeout=3.0):
    """执行一条 qdbus 命令，返回 (成功?, stdout)。失败/超时静默降级，
    不打断桌面歌词的正常显示（位置持久化属锦上添花）。"""
    qdbus = shutil.which("qdbus") or shutil.which("qdbus6") or shutil.which("qdbus-qt6")
    if qdbus is None:
        return False, ""
    try:
        r = subprocess.run(
            [qdbus] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception:
        return False, ""


_KWIN_QUERY_POSITION_SCRIPT_TEMPLATE = r"""
// 由 desktop.py 运行时生成：查询标题为 "%(title)s" 的窗口真实坐标，
// 经 callDBus 回调给 org.pymusic.DesktopLyric（Wayland 下客户端拿不到
// 自己窗口的全局坐标，只有合成器内的脚本能读 geometry.x/geometry.y）。
function findAndReport() {
    var list = (typeof workspace.windowList === "function")
        ? workspace.windowList()
        : (workspace.clientList ? workspace.clientList() : []);
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w) continue;
        try {
            if (w.caption === "%(title)s") {
                var g = w.geometry || w.frameGeometry;
                if (g) {
                    callDBus(
                        "org.pymusic.DesktopLyric",
                        "/PositionReceiver",
                        "org.pymusic.DesktopLyric",
                        "reportPosition",
                        Math.round(g.x),
                        Math.round(g.y)
                    );
                }
                return;
            }
        } catch (e) {
            // 忽略：不同 KWin/Qt 版本 Window/Client API 略有差异
        }
    }
}
findAndReport();
"""

_KWIN_SET_POSITION_SCRIPT_TEMPLATE = r"""
// 由 desktop.py 运行时生成：把标题为 "%(title)s" 的窗口移动到 (%(x)d, %(y)d)。
// Wayland 下客户端 setPosition 会被合成器忽略，只能借道脚本直接写
// frameGeometry（KWin 6 中该属性可写，赋值等价于 moveResize）。
// 保持窗口当前尺寸不变，只改位置。
function findAndMove() {
    var list = (typeof workspace.windowList === "function")
        ? workspace.windowList()
        : (workspace.clientList ? workspace.clientList() : []);
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w) continue;
        try {
            if (w.caption === "%(title)s") {
                var g = w.frameGeometry || w.geometry;
                if (g) {
                    w.frameGeometry = {
                        x: %(x)d,
                        y: %(y)d,
                        width: Math.round(g.width),
                        height: Math.round(g.height)
                    };
                }
                return;
            }
        } catch (e) {
            // 忽略：不同 KWin/Qt 版本 Window API 略有差异
        }
    }
}
findAndMove();
"""


class _KWinPinner:
    """通过 KWin D-Bus 脚本接口查询/设置标题匹配窗口的位置（Wayland 专属）。

    Wayland 协议不允许客户端读写自己窗口的全局坐标，只能借道运行在
    合成器内部的 KWin 脚本。置顶不在这里处理——请引导用户用窗口规则
    （标题 = 桌面歌词 → 在其它窗口之上 = 强制）。仅 KDE + Wayland 启用。

    用法：把脚本模板写临时文件 → qdbus loadScript → qdbus start →
    立即 unloadScript，不留常驻脚本。"""

    def __init__(self, title):
        self._title = title
        self._tmp_path = None

    @staticmethod
    def is_kde():
        if QGuiApplication.platformName() != "wayland":
            return False
        return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")

    def query_position(self, timeout=1.5):
        """注入脚本查询窗口真实坐标，经 callDBus 回调 reportPosition。

        Wayland 下 QWindow.x()/y() 在 startSystemMove 拖动后不会更新，
        真实坐标只有合成器内部知道。脚本查到的坐标异步回调到
        _PositionReceiver（几十毫秒），本函数只确认脚本加载/启动成功。"""
        if not self.is_kde():
            _dlog("_KWinPinner.query_position: is_kde()=False，跳过")
            return False
        if not _HAVE_QTDBUS:
            _dlog("_KWinPinner.query_position: PySide6.QtDBus 不可用，跳过"
                  "（可能是 PySide6 打包时没带 QtDBus 模块）")
            return False
        script = _KWIN_QUERY_POSITION_SCRIPT_TEMPLATE % {
            "title": self._title.replace('"', '\\"'),
        }
        try:
            fd, path = tempfile.mkstemp(prefix="pymusic-desktoplyric-qpos-", suffix=".js")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(script)
        except Exception as e:
            _dlog("_KWinPinner.query_position: 写临时脚本文件异常: %r" % (e,))
            return False
        self._tmp_path = path
        script_name = "pymusic-desktoplyric-qpos"

        ok, out = _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
            path, script_name,
        ])
        if not ok:
            _dlog("_KWinPinner.query_position: loadScript 失败")
            self._cleanup_tmp()
            return False

        ok2, _ = _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start",
        ])
        _dlog("_KWinPinner.query_position: loadScript 成功(id=%s)，start() 返回 %s，"
              "等待 KWin 脚本通过 callDBus 回调 org.pymusic.DesktopLyric"
              % (out, ok2))

        _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript",
            script_name,
        ])
        self._cleanup_tmp()
        return ok2

    def set_position(self, x, y):
        """通过 KWin 脚本把标题匹配窗口移动到 (x, y)。

        Wayland 下 QWindow.setPosition() 只更新本地缓存、实际落点由合成器
        决定，恢复位置只能靠脚本直接写 frameGeometry。脚本加载/启动成功
        即认为链路走通；窗口还没被 KWin 注册时脚本静默跳过，调用方应
        延迟重试（见 _schedule_restore）。
        """
        if not self.is_kde():
            _dlog("_KWinPinner.set_position: is_kde()=False，跳过")
            return False
        script = _KWIN_SET_POSITION_SCRIPT_TEMPLATE % {
            "title": self._title.replace('"', '\\"'),
            "x": int(x),
            "y": int(y),
        }
        try:
            fd, path = tempfile.mkstemp(prefix="pymusic-desktoplyric-move-", suffix=".js")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(script)
        except Exception as e:
            _dlog("_KWinPinner.set_position: 写临时脚本文件异常: %r" % (e,))
            return False
        self._tmp_path = path
        # 唯一脚本名：移动脚本可能短时间内连续触发（hide→show），
        # 固定名会导致同名 loadScript 返回 -1 被当成失败。
        script_name = "pymusic-desktoplyric-move-%d" % int(time.monotonic() * 1000)

        ok, out = _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
            path, script_name,
        ])
        if not ok:
            _dlog("_KWinPinner.set_position: loadScript 失败")
            self._cleanup_tmp()
            return False

        ok2, _ = _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start",
        ])
        _dlog("_KWinPinner.set_position: loadScript 成功(id=%s)，start() 返回 %s，"
              "已尝试把窗口移动到 (%d, %d)" % (out, ok2, int(x), int(y)))

        _run_qdbus([
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript",
            script_name,
        ])
        self._cleanup_tmp()
        return ok2

    def _cleanup_tmp(self):
        if self._tmp_path:
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
            self._tmp_path = None


@ClassInfo({"D-Bus Interface": "org.pymusic.DesktopLyric"})
class _PositionReceiver(QObject):
    """会话 D-Bus 服务 org.pymusic.DesktopLyric 的接收端。

    接收 KWin 脚本经 callDBus 回调的窗口真实坐标（query_position 链路）。

    ClassInfo 是链路能走通的关键：registerObject 默认把槽导出到"类名
    命名的 D-Bus 接口"下（_PositionReceiver），与脚本侧 callDBus 指定的
    org.pymusic.DesktopLyric 对不上时会被 Qt 以 UnknownInterface 拒掉，
    且双方都无报错。必须用 ClassInfo 显式指定接口名。
    """

    def __init__(self, on_position, parent=None):
        super().__init__(parent)
        self._on_position = on_position
        self._registered = False
        if not _HAVE_QTDBUS:
            _dlog("_PositionReceiver: PySide6.QtDBus 不可用，D-Bus 服务不会注册，"
                  "拖动后的真实坐标查询这条路完全用不了")
            return
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            _dlog("_PositionReceiver: 无法连接会话 D-Bus，服务不会注册")
            return
        ok_obj = bus.registerObject("/PositionReceiver", self,
                                     QDBusConnection.ExportAllSlots)
        ok_svc = bus.registerService("org.pymusic.DesktopLyric")
        self._registered = bool(ok_obj and ok_svc)
        _dlog("_PositionReceiver: 注册 D-Bus 服务 org.pymusic.DesktopLyric"
              "/PositionReceiver -> registerObject=%s registerService=%s "
              "(最终 registered=%s)" % (ok_obj, ok_svc, self._registered))

    @Slot(int, int)
    def reportPosition(self, x, y):
        """KWin 脚本查到窗口真实坐标后，通过 callDBus 调用这里。"""
        _dlog("_PositionReceiver.reportPosition 收到 KWin 回调坐标 (%d, %d)"
              % (x, y))
        if self._on_position is not None:
            try:
                self._on_position(int(x), int(y))
            except Exception as e:
                _dlog("_PositionReceiver.reportPosition 回调处理异常: %r" % (e,))


class _LyricBridge(QObject):
    """把 AudioPlayer 的歌词/状态接口翻译成 QML 友好的属性/信号/槽。

    QML 通过 setContextProperty("player", bridge) 拿到本对象，使用：
      - count        (property, 歌词行数)
      - curIndex     (property, 当前播放行索引)
      - stateText    (property, "playing"/"paused"/"stopped")
      - lyricText(i) (slot,    返回第 i 行文本)
      - indexChanged (signal,  当前行变化)
      - stateChanged (signal,  播放状态变化)
    """

    indexChanged = Signal(int)
    stateChanged = Signal()
    lyricsChanged = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self._player = player
        self._lyrics = []   # 本地缓存 [(t, text), ...]，避免频繁跨信号取值
        self._groups = []   # 分组缓存 [[(t,text),...], ...]：同时间戳相邻行并为一组
        self._desktop_font = ""   # 桌面歌词字体族（空=默认）
        self._desktop_color = ""  # 桌面歌词当前行颜色（空=默认白）

        if player is not None:
            player.lyricsChanged.connect(self._on_lyrics_changed)
            # 与主播放器使用同一"带提前量"索引，保证两句永远同步
            player.lyricIndexChanged.connect(self._on_index_changed)
            player.stateChanged.connect(self._on_state_changed)
            self._on_lyrics_changed()

    # ---------- 与 AudioPlayer 的同步 ----------

    def _refresh_cache(self):
        """从 AudioPlayer 拉取歌词列表缓存到本地（仅当列表变化时进行）。"""
        p = self._player
        try:
            n = p.lyricCount
        except Exception:
            n = 0
        if n != len(self._lyrics):
            self._lyrics = [(p.lyricTime(i), p.lyricText(i)) for i in range(n)]
        self._rebuild_groups()

    def _rebuild_groups(self):
        """把相邻、时间戳相同的歌词行并成一组（双语"原文/译文"同时间戳）。

        播放器的 parse_lrc_text 会把 "[00:12]原文/译文" 拆成两条时间戳
        相同的记录并保证相邻。这里复用同一约定：连续、且 .0 秒相等到
        毫秒级容差的行视为一组，桌面歌词把整组作为一个块渲染。
        """
        self._groups = []
        for t, text in self._lyrics:
            if self._groups and abs(self._groups[-1][-1][0] - t) < 1e-6:
                self._groups[-1].append((t, text))
            else:
                self._groups.append([(t, text)])

    def _on_lyrics_changed(self):
        self._refresh_cache()
        self.lyricsChanged.emit()

    def _on_index_changed(self, idx):
        self.indexChanged.emit(idx)

    def _on_state_changed(self, state):
        self.stateChanged.emit()

    # ---------- QML 暴露的属性 ----------

    @Property(int, notify=lyricsChanged)
    def count(self):
        return len(self._lyrics)

    # 分组数量（每个双语"原文/译文"块算一组）
    @Property(int, notify=lyricsChanged)
    def groupCount(self):
        return len(self._groups)

    @Property(int, notify=indexChanged)
    def curIndex(self):
        p = self._player
        if p is None:
            return -1
        try:
            return p.currentLyricIndex
        except Exception:
            return -1

    # 当前播放行所在的组号（用于整块高亮/居中）
    @Property(int, notify=indexChanged)
    def curGroup(self):
        i = self.curIndex
        if i < 0:
            return -1
        # 统计已走过的行数，返回"组的下标"（从 0 计），而不是累计行偏移。
        # 早前实现误把累计行数当组号返回，当目标组之前存在被合并的组
        # （如 `[00:00]作词…/编曲…` 拆出的同时间戳多行、或双语同时间戳）时，
        # 会把组号整体 push 后，导致桌面歌词比主界面"快一句"。
        line = 0
        for gi, grp in enumerate(self._groups):
            if i < line + len(grp):
                return gi
            line += len(grp)
        return len(self._groups) - 1

    @Property(str, notify=stateChanged)
    def stateText(self):
        p = self._player
        if p is None:
            return "stopped"
        try:
            return p.state
        except Exception:
            return "stopped"

    # ---------- 桌面歌词样式（字体/当前行颜色，由主面板设置） ----------

    styleChanged = Signal()

    @Property(str, notify=styleChanged)
    def desktopFont(self):
        """当前行歌词字体族；空字符串表示使用默认字体。"""
        return self._desktop_font

    @Property(str, notify=styleChanged)
    def desktopColor(self):
        """当前行歌词颜色（十六进制/颜色名）；空字符串表示默认白。"""
        return self._desktop_color

    @Slot(str, str)
    def setStyle(self, font, color):
        """设置桌面歌词样式（font 可为空串表示默认，color 可为空串表示默认）。"""
        changed = False
        font = font or ""
        color = color or ""
        if font != self._desktop_font:
            self._desktop_font = font
            changed = True
        if color != self._desktop_color:
            self._desktop_color = color
            changed = True
        if changed:
            self.styleChanged.emit()

    @Slot(int, result=str)
    def lyricText(self, index):
        if 0 <= index < len(self._lyrics):
            return self._lyrics[index][1]
        return ""

    @Slot(int, result=int)
    def groupSize(self, g):
        """第 g 组的行数（一般 1 或 2）。"""
        if 0 <= g < len(self._groups):
            return len(self._groups[g])
        return 0

    @Slot(int, int, result=str)
    def groupText(self, g, sub):
        """第 g 组第 sub 行的文本。"""
        if 0 <= g < len(self._groups) and 0 <= sub < len(self._groups[g]):
            return self._groups[g][sub][1]
        return ""

    @Slot(int, result=str)
    def groupTextOnly(self, g):
        """整组的文本（多行用换行拼接），供无分组渲染的 Text 使用。"""
        if 0 <= g < len(self._groups):
            return "\n".join(t for _, t in self._groups[g])
        return ""

    # ---------- 右键菜单（由 desktop.qml 的 MouseArea 触发） ----------
    # 实际弹出逻辑委托给 DesktopLyrics（它持有 QQuickView，方便设置
    # WindowStaysOnTopHint / 隐藏窗口等），这里只是把 QML 的信号转发出去。
    contextMenuRequested = Signal(int, int)

    @Slot(int, int)
    def showContextMenu(self, x, y):
        self.contextMenuRequested.emit(x, y)

    # ---------- 拖动结束通知（由 desktop.qml 的 MouseArea.onReleased 触发） ----------
    # QML 层只负责"告诉 Python 一次拖动结束了"，具体怎么去拿 Wayland 下
    # 客户端本来拿不到的真实窗口坐标（借道 KWin 脚本查询），由 Python
    # 侧的 DesktopLyrics 处理，QML 不需要关心实现细节。
    dragFinishedSig = Signal()

    @Slot()
    def dragFinished(self):
        self.dragFinishedSig.emit()


class DesktopLyrics:
    """桌面歌词窗口控制器：封装一个透明置顶的 QQuickView 并绑定 AudioPlayer。

    交互模型（详见模块 docstring）：
      - "锁定歌词"开启：整窗点击穿透，不可拖动；
      - 取消锁定：左键拖动整窗，右键弹出自绘菜单（置顶开关 / 隐藏）。
      - 置顶仅设 Qt flag（X11 生效）；Wayland 下请配置 KWin 窗口规则。
    """

    def __init__(self, player=None, parent=None):
        # QQuickView 是独立顶层窗口，不进入主 engine 的 rootObjects
        self._view = QQuickView()
        self._view.setResizeMode(QQuickView.SizeRootObjectToView)

        self._stay_on_top = True  # 右键菜单"置顶显示"状态
        self._locked = False      # "锁定歌词"；锁定则点击穿透、不可挪动
        self._save_pos_cb = None  # 由 _DesktopLyricsManager 注入的"保存位置"回调
        self._desired_pos = None  # 上次保存的窗口位置 (x,y)；None 用默认摆位
        self._suppress_pos_tracking = True  # 程序自摆位期间忽略 xChanged/yChanged
        self._kwin_pinner = _KWinPinner(WINDOW_TITLE_HINT)
        self._position_receiver = _PositionReceiver(self._on_kwin_reported_position, self._view)

        # 拖动位置去抖保存：拖动中 x/y 高频触发，停手 400ms 后才写一次配置
        self._pos_timer = QTimer(self._view)
        self._pos_timer.setSingleShot(True)
        self._pos_timer.setInterval(400)
        self._pos_timer.timeout.connect(self._save_position)
        # show 后分几次延迟重试 KWin 脚本恢复位置（窗口需先被 KWin 注册）
        self._restore_pending = False
        self._restore_remaining = 0
        self._view.xChanged.connect(self._on_position_changed)
        self._view.yChanged.connect(self._on_position_changed)

        # 无边框 + 置顶 + 不抢焦点 + 工具窗（不占任务栏）。
        # WindowTransparentForInput 随"锁定歌词"开关决定；置顶 flag 仅 X11 生效。
        self._view.setFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput
            | Qt.Tool
        )
        self._view.setColor("transparent")
        self._view.setTitle(WINDOW_TITLE_HINT)
        self._view.setObjectName(WINDOW_CLASS_HINT)

        # 桥接对象
        self._bridge = _LyricBridge(player, self._view)
        self._bridge.contextMenuRequested.connect(self._on_context_menu_requested)
        self._bridge.dragFinishedSig.connect(self._on_drag_finished)
        self._view.rootContext().setContextProperty("player", self._bridge)
        self._view.setSource(QUrl.fromLocalFile(str(_QML_PATH)))

        # 尺寸跟随 QML (SizeRootObjectToView)
        if self._view.status() == QQuickView.Error:
            print("[desktop] 加载 desktop.qml 失败:",
                  [str(e) for e in self._view.errors()])

        # 默认摆位：主屏幕水平居中、贴近底部。
        # _suppress_pos_tracking 让程序自己的 setPosition 不被当成"用户
        # 拖动"记录/保存，否则去抖定时器可能把默认坐标误写回配置。
        self._place_default()

        # 初始透明度按当前锁定状态应用（默认未锁定可拖动）
        self._apply_lock()

        # 置顶不做运行时脚本注入：Wayland 用窗口规则，X11 用 Qt flag
        _dlog("__init__ 完成，构造期间的默认摆位坐标=(%d,%d)；"
              "_suppress_pos_tracking 仍为 True，manager.ensure() 稍后会在"
              "真正应用完保存的位置之后才关闭它" % (self._view.x(), self._view.y()))

    # ---------- 右键菜单 ----------

    def _on_context_menu_requested(self, x, y):
        """在全局坐标 (x, y) 弹出右键菜单。x/y 来自 QML 的 mapToGlobal，
        单位是设备无关像素（与 QCursor/QPoint 一致）。"""
        menu = QMenu()
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint)

        top_action = menu.addAction("置顶显示")
        top_action.setCheckable(True)
        top_action.setChecked(self._stay_on_top)
        top_action.toggled.connect(self._set_stay_on_top)

        menu.addSeparator()
        hide_action = menu.addAction("隐藏桌面歌词")
        hide_action.triggered.connect(self.hide)

        # 用 exec 而不是 show，保证是模态弹出、点外部自动关闭
        menu.exec(QPoint(int(x), int(y)))

    # ---------- 拖动结束 -> 借道 KWin 脚本查询真实坐标 ----------

    def _on_drag_finished(self):
        """一次左键拖动结束（QML MouseArea.onReleased）。

        Wayland 下 self._view.x()/y() 不会随 startSystemMove 拖动更新，
        直接 _save_position() 存的是旧坐标，必须借道 KWin 脚本查询真实
        坐标（异步回调 _on_kwin_reported_position）。X11 下读数准确，
        直接兜底保存。"""
        _dlog("_on_drag_finished: 收到拖动结束通知，当前 self._view.x/y()="
              "(%d,%d)（Wayland 下这个读数在拖动后大概率是不准的，仅供"
              "参考，真实坐标要等下面 KWin 查询的回调）"
              % (self._view.x(), self._view.y()))
        if not self._kwin_pinner.is_kde():
            self._save_position()
            return
        self._query_position_async()

    def _query_position_async(self):
        """后台线程调 query_position（subprocess 不阻塞 UI）；真实坐标经
        reportPosition 异步回调，不是本函数返回值。"""
        import threading
        t = threading.Thread(
            target=self._kwin_pinner.query_position,
            daemon=True,
        )
        t.start()

    def _on_kwin_reported_position(self, x, y):
        """收到 KWin 回调的真实坐标（Wayland 下唯一权威来源），
        更新 _desired_pos 并落盘。"""
        _dlog("_on_kwin_reported_position: 收到 KWin 回调的真实坐标 "
              "(%d, %d)，与 self._view 读数 (%d, %d) 对比"
              "%s，以 KWin 回调值为准写入配置"
              % (x, y, self._view.x(), self._view.y(),
                 "一致" if (x, y) == (self._view.x(), self._view.y())
                 else "不一致（符合预期，Wayland 下 QWindow 读数本来就不可靠）"))
        # 停掉残留去抖定时器：避免稍后用不可靠的 self._view 读数覆盖权威坐标
        if self._pos_timer.isActive():
            self._pos_timer.stop()
        self._desired_pos = (int(x), int(y))
        if self._save_pos_cb is not None:
            self._save_pos_cb("desktopLyricPosX", str(int(x)))
            self._save_pos_cb("desktopLyricPosY", str(int(y)))
            _dlog("_on_kwin_reported_position: 已写入配置 "
                  "desktopLyricPosX=%d desktopLyricPosY=%d" % (x, y))
        else:
            _dlog("_on_kwin_reported_position: _save_pos_cb 为 None，"
                  "坐标 (%d, %d) 没有写进配置！" % (x, y))

    def _set_stay_on_top(self, on):
        """右键菜单"置顶显示"：设 Qt.WindowStaysOnTopHint 并 raise 一次。
        X11 生效；Wayland 忽略该 flag，置顶请走窗口规则。"""
        self._stay_on_top = bool(on)
        self._view.setFlag(Qt.WindowStaysOnTopHint, self._stay_on_top)
        if self._stay_on_top:
            # 部分 WM（尤其 X11 下少数窗口管理器）需要重新 raise 才真正置顶
            self._view.raise_()

    def _place_default(self):
        """主屏幕底部居中的默认摆位。"""
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            w = self._view.width()
            h = self._view.height()
            x = avail.x() + (avail.width() - w) // 2
            y = avail.y() + avail.height() - h - 48  # 距底部 48px
            _dlog("_place_default: 应用默认摆位 (%d, %d)（窗口尺寸 %dx%d，"
                  "屏幕可用区域 %s）" % (x, y, w, h, avail))
            self._view.setPosition(x, y)
        except Exception as e:
            _dlog("_place_default 异常: %r" % (e,))

    def set_position(self, x, y):
        """记录上次保存的窗口位置并立即尝试应用（窗口未显示时 Wayland
        合成器会忽略 setPosition，真正生效靠 show 后的 _place_desired）。"""
        self._desired_pos = (int(x), int(y))
        _dlog("set_position(%d, %d) 记录目标位置，立即尝试 setPosition "
              "(窗口是否已 show: %s)" % (self._desired_pos[0], self._desired_pos[1],
                                       self._view.isVisible()))
        try:
            self._view.setPosition(*self._desired_pos)
            _dlog("set_position -> setPosition 调用后实际读回 (x=%d, y=%d)"
                  % (self._view.x(), self._view.y()))
        except Exception as e:
            _dlog("set_position -> setPosition 抛出异常: %r" % (e,))

    def _place_desired(self):
        """show 后窗口已映射时补一次 setPosition。"""
        if self._desired_pos is None:
            return
        _dlog("_place_desired: 补一次 setPosition%s，补位前实际坐标 (x=%d, y=%d)"
              % (self._desired_pos, self._view.x(), self._view.y()))
        try:
            self._view.setPosition(*self._desired_pos)
            _dlog("_place_desired: 补位后实际读回 (x=%d, y=%d)"
                  % (self._view.x(), self._view.y()))
        except Exception as e:
            _dlog("_place_desired -> setPosition 抛出异常: %r" % (e,))

    def _on_position_changed(self, *args):
        # 用户拖动时记录最新位置（hide→show 按此恢复），落盘由去抖定时器完成。
        # _suppress_pos_tracking 为 True 时是程序自己在摆位（默认摆位 /
        # 恢复保存位置），忽略——否则会把默认坐标误记进 _desired_pos 并
        # 起一个 400ms 后可能把默认坐标写回配置的定时器。
        if self._suppress_pos_tracking:
            try:
                _dlog("xChanged/yChanged 触发但 _suppress_pos_tracking=True，"
                      "忽略（当前坐标 (%d,%d)，这是程序自己摆位，不是用户拖动）"
                      % (self._view.x(), self._view.y()))
            except Exception:
                pass
            return
        try:
            new_pos = (self._view.x(), self._view.y())
            _dlog("xChanged/yChanged 触发（用户拖动），当前坐标 %s -> 更新 "
                  "_desired_pos，启动/重启 400ms 去抖保存定时器" % (new_pos,))
            self._desired_pos = new_pos
        except Exception as e:
            _dlog("_on_position_changed 读取坐标异常: %r" % (e,))
        self._pos_timer.start()

    def _save_position(self):
        """把当前窗口坐标写入配置（经 manager 注入的 _save_pos_cb）。"""
        try:
            x, y = self._view.x(), self._view.y()
            self._desired_pos = (x, y)
            if self._save_pos_cb is not None:
                self._save_pos_cb("desktopLyricPosX", str(int(x)))
                self._save_pos_cb("desktopLyricPosY", str(int(y)))
                _dlog("_save_position: 去抖到期，写入配置 "
                      "desktopLyricPosX=%d desktopLyricPosY=%d" % (x, y))
            else:
                _dlog("_save_position: 去抖到期，但 _save_pos_cb 是 None，"
                      "本次坐标 (%d, %d) 没有写进配置！" % (x, y))
        except Exception as e:
            _dlog("_save_position 异常: %r" % (e,))

    # ---------- 对外控制 ----------

    def _apply_lock(self):
        """按 _locked 设置点击穿透 flag：锁定 → 穿透（不可拖动/弹菜单）；
        取消锁定 → 可交互（左键拖动，右键弹菜单）。"""
        try:
            self._view.setFlag(Qt.WindowTransparentForInput, self._locked)
        except Exception:
            pass

    def set_locked(self, locked):
        """设置"锁定歌词"状态：locked 为真时窗口点击穿透、不可挪动。"""
        self._locked = bool(locked)
        self._apply_lock()

    @property
    def locked(self):
        return self._locked

    def begin_position_tracking(self):
        """由 manager.ensure() 在"默认摆位 + 恢复保存位置"都处理完之后调用，
        正式打开用户拖动的坐标跟踪/去抖保存。在这之前的所有 setPosition
        （构造函数默认摆位、ensure 里恢复保存坐标）都不应被当成"用户拖动"
        记录下来，否则会有极小概率被 400ms 去抖定时器误当成新位置写回配置，
        参见 _on_position_changed 里的详细说明。"""
        self._suppress_pos_tracking = False
        _dlog("begin_position_tracking: 正式开始跟踪用户拖动，"
              "当前 _desired_pos=%s，当前 view 坐标=(%d,%d)"
              % (self._desired_pos, self._view.x(), self._view.y()))

    def show(self):
        """显示窗口并安排位置恢复（setEnabled(True) 的内部实现）。"""
        _dlog("show() 调用，调用前 _desired_pos=%s，调用前 view 坐标=(%d,%d)"
              % (self._desired_pos, self._view.x(), self._view.y()))
        self._view.show()
        _dlog("show() -> QQuickView.show() 之后坐标=(%d,%d)"
              % (self._view.x(), self._view.y()))
        # Wayland 下客户端 setPosition 只更新本地缓存，真正落位靠
        # _schedule_restore 的 KWin 脚本移动；置顶由窗口规则负责。
        self._place_desired_after_show()
        self._schedule_restore()

    def hide(self):
        _dlog("hide() 调用")
        self._view.hide()

    @property
    def visible(self):
        return self._view.isVisible()

    def setEnabled(self, enabled):
        """开/关桌面歌词窗口：显示时同步置顶 flag/锁定状态并安排位置恢复，
        隐藏时同步穿透状态。不要与 show()/hide() 叠加调用，避免补位
        定时器与位置恢复被重复调度。"""
        _dlog("setEnabled(%s) 调用，调用前 _desired_pos=%s" % (enabled, self._desired_pos))
        if enabled:
            self.show()
        else:
            self._view.hide()
        # 只在"置顶显示"开关为真时才设 flag，避免关掉置顶后又被重新打开
        self._view.setFlag(Qt.WindowStaysOnTopHint, enabled and self._stay_on_top)
        # 切歌/恢复显示时重新 raise（部分 WM 需要）
        if enabled and self._stay_on_top:
            self._view.raise_()
        # 显示/隐藏后重新应用锁定状态（Wayland 下 flag 可能在 show 时重建）
        self._apply_lock()

    def _place_desired_after_show(self, delay_ms=120):
        """延迟 delay_ms 在窗口已映射后补一次 setPosition。"""
        if self._desired_pos is None:
            return
        _dlog("_place_desired_after_show: 安排 %dms 后补位到 %s"
              % (delay_ms, self._desired_pos))
        t = QTimer(self._view)
        t.setSingleShot(True)
        t.setInterval(delay_ms)
        t.timeout.connect(self._place_desired)
        t.start()

    def _schedule_restore(self):
        """show 后分几次延迟调 KWin 脚本，把窗口真正移动到保存的位置。

        Wayland 下客户端 setPosition 会被合成器忽略，唯一可靠的恢复方式
        是脚本直接写 frameGeometry（_KWinPinner.set_position）。窗口 show
        后需几百毫秒才被 KWin 注册（标题匹配才有效），所以 700/1400/2100ms
        各试一次；hide→show 连续触发用 _restore_pending 合并为同一轮。
        """
        if self._desired_pos is None:
            return
        if not self._kwin_pinner.is_kde():
            # X11 下 setPosition 是准的，不需要脚本
            return
        if self._restore_pending:
            return
        self._restore_pending = True
        x, y = self._desired_pos
        self._restore_remaining = 3
        _dlog("_schedule_restore: show 后 700/1400/2100ms 各尝试一次 KWin "
              "脚本移动窗口到 %s" % ((x, y),))
        for delay in (700, 1400, 2100):
            t = QTimer(self._view)
            t.setSingleShot(True)
            t.setInterval(delay)
            t.timeout.connect(lambda: self._on_restore_attempt(x, y))
            t.start()

    def _on_restore_attempt(self, x, y):
        self._restore_remaining -= 1
        if self._restore_remaining <= 0:
            self._restore_pending = False
        self._move_async(x, y)

    def _move_async(self, x, y):
        """后台线程调 set_position（subprocess 不阻塞 UI）。"""
        import threading
        t = threading.Thread(
            target=self._kwin_pinner.set_position,
            args=(x, y),
            daemon=True,
        )
        t.start()

    def raiseWindow(self):
        self._view.raise_()

    # 供 main.py 在退出时调用，归还 QML 资源
    def close(self):
        # 退出前兜底保存一次当前位置（防极端情况如立刻退出丢位置）
        try:
            self._save_position()
        except Exception:
            pass
        self._view.close()


# ========== 模块级管理器（供 main.py / AppBridge 调用） ==========
# 整个进程只存在一个 DesktopLyrics 实例，避免重复创建多个歌词窗口。
_manager = None


class _DesktopLyricsManager:
    """懒创建的单例控制器。

    - ensure(player)：首次调用创建窗口（隐藏），之后复用；
    - set_enabled(on)：显示/隐藏歌词窗并持久化开关。
    """

    def __init__(self):
        self._lyrics = None  # DesktopLyrics or None
        self._player = None  # AudioPlayer 实例（ensure 时设置），用于配置持久化
        self._enabled = False
        self._ever_shown = False  # 本进程内是否已通过 set_enabled 主动 show/hide 过
        self._desktop_font = ""
        self._desktop_color = ""
        self._desktop_locked = False
        self._desktop_pos = None  # (x, y) 或 None；None 表示用默认摆位

    def _load_saved(self, player):
        """从 PyMusic.config 读取桌面歌词的开关/字体/颜色/锁定/位置。"""
        try:
            s = player.loadSettings()
            self._enabled = bool(s.get("desktopLyricsEnabled", False))
            self._desktop_font = s.get("desktopLyricFont", "") or ""
            self._desktop_color = s.get("desktopLyricColor", "") or ""
            self._desktop_locked = str(s.get("desktopLyricLocked", "false")).lower() == "true"
            raw_x = s.get("desktopLyricPosX", "")
            raw_y = s.get("desktopLyricPosY", "")
            try:
                px = int(float(raw_x))
                py = int(float(raw_y))
                self._desktop_pos = (px, py)
            except (TypeError, ValueError):
                self._desktop_pos = None
            _dlog("_load_saved: 从配置读到 desktopLyricsEnabled=%s "
                  "desktopLyricPosX=%r desktopLyricPosY=%r -> 解析出 "
                  "_desktop_pos=%s" % (self._enabled, raw_x, raw_y, self._desktop_pos))
        except Exception as e:
            self._enabled = False
            _dlog("_load_saved: 读取配置异常，全部退回默认值: %r" % (e,))

    def ensure(self, player):
        self._player = player
        created = False
        if self._lyrics is None:
            _dlog("ensure(): 首次创建 DesktopLyrics 实例")
            self._lyrics = DesktopLyrics(player)
            created = True
        elif self._lyrics._bridge._player is not player:
            # 播放器实例变化（一般不会），重建桥接
            _dlog("ensure(): player 实例变化，重建 DesktopLyrics")
            self._lyrics.close()
            self._lyrics = DesktopLyrics(player)
            created = True
        # 把位置持久化回调挂到窗口（用于拖动后保存位置）
        self._lyrics._save_pos_cb = self._save
        # 只在首次创建时读取并应用已保存的样式/锁定/位置；之后的 ensure
        # 绝不能重新套用配置里的旧位置，否则会把用户刚拖动到位、但去抖
        # 保存还没落盘的新位置覆盖回原位。
        if not created:
            _dlog("ensure(): 非首次调用（窗口已存在），直接复用，不重新套用"
                  "配置里的旧位置")
            return self._lyrics
        # 首次 ensure 时读取播放器配置中保存的样式/开关；之后复用已缓存值
        if self._player is not None:
            self._load_saved(self._player)
        # 把已保存的样式下发到桥接对象（重启/app 启动后生效）
        try:
            self._lyrics._bridge.setStyle(self._desktop_font, self._desktop_color)
        except Exception as e:
            _dlog("ensure(): setStyle 异常: %r" % (e,))
        # 把已保存的锁定状态应用到窗口（重启/app 启动后生效）
        try:
            self._lyrics.set_locked(self._desktop_locked)
        except Exception as e:
            _dlog("ensure(): set_locked 异常: %r" % (e,))
        # 恢复已保存的窗口位置（有则用之，无则用默认摆位）。
        # 窗口尚未显示时 Wayland 会忽略 setPosition，真正落位由 show 后的
        # _place_desired_after_show 补一次完成。
        try:
            if self._desktop_pos is not None:
                _dlog("ensure(): 应用已保存的位置 %s" % (self._desktop_pos,))
                self._lyrics.set_position(*self._desktop_pos)
            else:
                _dlog("ensure(): 没有已保存的位置（_desktop_pos 为 None），"
                      "将保持构造函数里算出的默认摆位")
        except Exception as e:
            _dlog("ensure(): set_position 异常: %r" % (e,))
        # 程序自摆位（默认摆位 + 恢复保存位置）到此结束，正式打开用户
        # 拖动跟踪，避免自动摆位被误当成用户拖动记录/保存。
        self._lyrics.begin_position_tracking()
        return self._lyrics

    def _save(self, key, value):
        """通过播放器的 saveSetting 持久化到 PyMusic.config。"""
        try:
            if self._player is not None:
                self._player.saveSetting(key, value)
                _dlog("_save: 写配置 %s=%s" % (key, value))
            else:
                _dlog("_save: self._player 为 None，%s=%s 没有写进去！" % (key, value))
        except Exception as e:
            _dlog("_save: 写配置 %s=%s 异常: %r" % (key, value, e))

    def is_enabled(self):
        # 只有"本进程主动 show/hide 过窗口"之后才信任 visible 来同步
        # _enabled（启动时窗口刚创建未显示，visible 恒 False，会把刚读
        # 到的配置值覆盖掉导致"上次开着"恢复不了）。
        if self._lyrics is not None and self._ever_shown:
            self._enabled = self._lyrics.visible
        return self._enabled

    def set_enabled(self, on, player=None):
        _dlog("set_enabled(%s) 调用" % (on,))
        if player is not None:
            self.ensure(player)
        self._ever_shown = True
        if self._lyrics is None:
            self._enabled = bool(on)
            self._enabled_cache(on)
            return
        if on:
            self._lyrics.setEnabled(True)
        else:
            self._lyrics.setEnabled(False)
        self._enabled = bool(on)
        self._save("desktopLyricsEnabled", "true" if on else "false")

    def _enabled_cache(self, on):
        self._save("desktopLyricsEnabled", "true" if on else "false")

    def close(self):
        if self._lyrics is not None:
            self._lyrics.close()

    def set_style(self, font, color, player=None):
        """设置桌面歌词字体/当前行颜色（空串=默认），更新渲染并持久化。"""
        if player is not None:
            self.ensure(player)
        font = font or ""
        color = color or ""
        self._desktop_font = font
        self._desktop_color = color
        if self._lyrics is not None:
            try:
                self._lyrics._bridge.setStyle(font, color)
            except Exception:
                pass
        self._save("desktopLyricFont", font)
        self._save("desktopLyricColor", color)

    def set_locked(self, locked, player=None):
        """设置"锁定歌词"：锁定则点击穿透、不可挪动，并持久化。"""
        if player is not None:
            self.ensure(player)
        self._desktop_locked = bool(locked)
        if self._lyrics is not None:
            try:
                self._lyrics.set_locked(self._desktop_locked)
            except Exception:
                pass
        self._save("desktopLyricLocked", "true" if self._desktop_locked else "false")


def ensure_desktop_lyrics(player):
    """确保桌面歌词控制器存在并绑定到 player（未启用时也创建，隐藏）。"""
    global _manager
    if _manager is None:
        _manager = _DesktopLyricsManager()
    _manager.ensure(player)
    return _manager


def set_desktop_lyrics_enabled(on, player=None):
    """开关桌面歌词；on 为 True 时显示，False 时隐藏。"""
    global _manager
    if _manager is None:
        _manager = _DesktopLyricsManager()
    _manager.set_enabled(on, player)
    return _manager


def is_desktop_lyrics_enabled():
    """返回桌面歌词当前是否显示。"""
    global _manager
    if _manager is None:
        return False
    return _manager.is_enabled()


def set_desktop_style(font, color, player=None):
    """设置桌面歌词字体/颜色（空串表示用默认值）。"""
    global _manager
    if _manager is None:
        _manager = _DesktopLyricsManager()
    _manager.set_style(font, color, player)
    return _manager


def set_desktop_lyrics_locked(locked, player=None):
    """设置"锁定歌词"；locked 为 True 时窗口不可挪动（点击穿透）。"""
    global _manager
    if _manager is None:
        _manager = _DesktopLyricsManager()
    _manager.set_locked(locked, player)
    return _manager


def close_desktop_lyrics():
    """退出时归还桌面歌词资源。"""
    global _manager
    if _manager is not None:
        _manager.close()


def _selftest_main():
    """独立自测入口：构造一个假"播放器"喂给 DesktopLyrics，验证窗口效果。

    注意：右键菜单用的是 QtWidgets 的 QMenu，因此这里必须用 QApplication
    而不是 QGuiApplication ——否则 QMenu.exec() 会因为找不到 QApplication
    实例而报错/无法弹出。main.py 里本来就用的是 QApplication，不受影响。
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    QGuiApplication.setApplicationName("DesktopLyric Selftest")

    # 假播放器：直接用真 AudioPlayer 会启动完整曲库扫描，太重。
    # 这里用一个最小 QObject 桥代替，暴露出歌词/状态接口。
    class FakePlayer(QObject):
        lyricsChanged = Signal()
        lyricIndexChanged = Signal(int)
        stateChanged = Signal(str)

        def __init__(self):
            super().__init__()
            self._lyrics = [(i * 3.0, "第 %d 句 — 桌面歌词自测" % (i + 1))
                            for i in range(12)]
            self._idx = -1
            self._state = "stopped"
            self._t = 0
            self._timer = QTimer()
            self._timer.setInterval(500)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

        @property
        def lyricCount(self):
            return len(self._lyrics)

        def lyricText(self, i):
            return self._lyrics[i][1] if 0 <= i < len(self._lyrics) else ""

        def lyricTime(self, i):
            return self._lyrics[i][0] if 0 <= i < len(self._lyrics) else 0.0

        @property
        def lyricIndex(self):
            return self._idx

        @property
        def currentLyricIndex(self):
            return self._idx

        @property
        def state(self):
            return self._state

        def _tick(self):
            self._t += 0.5
            if self._t < 5:
                self._state = "playing"
                self._idx += 1
                if self._idx >= len(self._lyrics):
                    self._idx = 0
                self._emit_all()
            elif self._t < 8:
                self._state = "paused"
                self._emit_all()
            elif self._t < 12:
                self._state = "playing"
                self._idx += 1
                if self._idx >= len(self._lyrics):
                    self._idx = 0
                self._emit_all()
            else:
                # 循环
                self._t = 0
                self._idx = -1
                self._state = "stopped"
                self._emit_all()

        def _emit_all(self):
            self.lyricsChanged.emit()
            self.lyricIndexChanged.emit(self._idx)
            self.stateChanged.emit(self._state)

    fake = FakePlayer()
    lyrics = DesktopLyrics(fake)
    lyrics.show()

    QTimer.singleShot(20000, app.quit)
    print("[desktop] 自测：应看到一个透明置顶歌词窗，每 0.5s 换行，"
          "中间暂停淡出。20s 后自动退出。")
    rc = app.exec()
    lyrics.close()
    return rc


if __name__ == "__main__":
    sys.exit(_selftest_main())
