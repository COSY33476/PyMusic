import QtQuick 2.15

// 桌面歌词 QML（普通窗口模式）。窗口由 desktop.py 的 QQuickView 提供
// （无边框/透明/置顶等在 Python 侧设置），根元素用 Item（QQuickView
// 不允许 Window 作根对象）。层模式（Wayland + KDE layer-shell）见
// desktop_layer.qml。
Item {
    id: root
    width: 900
    height: 120

    DesktopContent {
        anchors.fill: parent
    }
}
