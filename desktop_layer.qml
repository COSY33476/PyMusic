import QtQuick 2.15
import org.kde.layershell 1.0 as LayerShell

// 桌面歌词 QML（Wayland 层模式，KDE layer-shell）。
//
// 与 desktop.qml 的关系：同样渲染 DesktopContent.qml 的歌词 UI，但窗口
// 本体不再是普通 xdg 窗口，而是合成器的 layer surface（wlr-layer-shell
// 协议，KDE 提供 org.kde.layershell 的 Qt 实现）：
//   - layer = Overlay：位于所有普通窗口之上，天然置顶，无需窗口规则；
//   - anchors = Bottom | Left：位置由 margins 决定（wlr-layer-shell 里
//     只有"锚定边 + 边距"这套定位模型，没有绝对坐标）。desktop.py 把
//     用户拖动换算成 marginLeft/marginBottom 的增减，KWin 收到
//     marginsChanged 后重新排布窗口（scheduleRearrange），从而实现
//     拖动。初始位置（底部居中）也由 desktop.py 换算成 marginLeft；
//   - keyboardInteractivity = None：不抢键盘焦点；
//   - activateOnShow = false：显示时不主动激活。
// 点击穿透由 Python 侧 Qt.WindowTransparentForInput 控制（QtWayland 会
// 把它翻译成 wl_surface 的空 input region，层窗口同样生效）。
//
// marginLeft/marginBottom 是给 desktop.py 用的接口：Python 通过
// setProperty 修改这两个属性，绑定链（LayerShell.Window.margins.*）把
// 变化同步到合成器。窗口可见性由 desktop.py 的 show()/hide() 控制，
// visible 初始为 false，避免 engine.load 时窗口抢先显示。
Window {
    id: root
    visible: false
    width: 900
    height: 120
    color: "transparent"

    // 与层表面的相对位置（desktop.py 读写）
    property int marginLeft: 0
    property int marginBottom: 0

    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorBottom | LayerShell.Window.AnchorLeft
    LayerShell.Window.margins.left: root.marginLeft
    LayerShell.Window.margins.bottom: root.marginBottom
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.activateOnShow: false
    LayerShell.Window.wantsToBeOnActiveScreen: true

    DesktopContent {
        anchors.fill: parent
    }
}
