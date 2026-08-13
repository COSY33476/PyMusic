import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    visible: true
    width: 960
    height: 640
    minimumWidth: 720
    minimumHeight: 480
    title: "PyMusic"
    color: darkMode ? "#1a1a2e" : "#f0f0f2"

    // 点击 × 时：根据 closeToTray 决定隐藏到托盘还是退出
    onClosing: function(closeEvent) {
        if (closeToTray) {
            closeEvent.accepted = false
            window.hide()
        } else {
            appBridge.quitApp()
        }
    }

    // ========== 全局字体 ==========
    // 字体族列表按顺序尝试，命中第一个系统里存在、且能覆盖当前文字的即可。
    //
    // 之前只写了 "Noto Sans CJK SC"（SC = Simplified Chinese，简体中文子集）。
    // 打开日文歌词时终端会刷屏 "qt.text.font.db: OpenType support missing for
    // ..., script XX" 这类警告——这条警告本身来自 Qt 字体数据库在做复杂文字
    // 塑形(shaping)时，发现当前尝试的字体缺少某个 script 对应的 OpenType 表，
    // 多数情况下是无害的噪音（只要实际显示的文字不是方框/乱码），但如果系统里
    // 字体数量较多，Qt 为了找到"能正确渲染这段文字"的字体会遍历一遍字体库，
    // 这个过程可能造成明显卡顿——这正是"打开日文歌词时" 触发的原因：CJK SC
    // 子集虽然通常也内置了假名和常用汉字字形，但不是针对日文排版规则优化的，
    // 遇到日文文字时更容易命中这条警告分支。
    //
    // 这里追加 "Noto Sans CJK JP"（日文子集）作为候选，让 Qt 在遇到日文歌词时
    // 能优先匹配到专门支持日文的字体，减少警告刷屏和查找开销。这个改动是安全的
    // 纯追加：如果系统里没有安装这个字体，Qt 会静默跳过、自动尝试列表里下一个
    // 候选，不会报错也不会让现有的中文/英文显示变得更差。
    font.family: "Noto Sans CJK JP, Noto Sans CJK SC, Noto Sans, sans-serif"

    // ========== 深色/亮色模式 ==========
    property bool darkMode: true

    function toggleTheme() {
        darkMode = !darkMode
    }

    // ========== 颜色主题（随 darkMode 切换） ==========
    property color bgDark: darkMode ? (customDarkBg !== "" ? customDarkBg : "#1a1a2e") : (customLightBg !== "" ? customLightBg : "#f0f0f2")
    property color bgPanel: darkMode ? "#16213e" : "#ffffff"
    property color bgCard: darkMode ? "#0f3460" : "#e4e4e8"
    property color accent: customAccent !== "" ? customAccent : "#e94560"
    property color accentHover: "#ff6b81"
    property color textPrimary: darkMode ? "#eaeaea" : "#1a1a2e"
    property color textSecondary: darkMode ? "#8899aa" : "#666677"
    property color textMuted: darkMode ? "#556677" : "#9999aa"
    property color progressBg: darkMode ? "#2a2a4e" : "#d0d0d8"
    property color progressFill: customAccent !== "" ? customAccent : "#e94560"

    // 自定义颜色（空字符串表示使用默认值）
    property string customAccent: ""
    property string customDarkBg: ""
    property string customLightBg: ""
    property string customLyricColor: ""
    property string customLyricPlayedColor: ""
    property string customLyricUnplayedColor: ""
    property string customBtnBg: ""

    // 解析后的颜色属性（string → color，用于 lyrics 等 var 上下文，避免 .r/.g/.b 失效）
    property color _resolvedLyricColor: customLyricColor !== "" ? customLyricColor : accent
    property color _resolvedLyricPlayedColor: customLyricPlayedColor !== "" ? customLyricPlayedColor : textMuted
    property color _resolvedLyricUnplayedColor: customLyricUnplayedColor !== "" ? customLyricUnplayedColor : textSecondary

    // 背景效果
    property real blurRadius: 80
    property real panelOpacity: 0.45

    // 播放列表折叠状态
    property bool playlistVisible: player.playlistVisible

    // 隐藏控件底色
    property bool hideControlBackgrounds: false

    // 显示设置
    property real rowSpacing: 48
    property string customFontFamily: ""

    // 设置面板状态
    property bool settingsVisible: false

    function toggleSettings() {
        settingsVisible = !settingsVisible
    }

    // 下载面板状态
    property bool downloadVisible: false

    function toggleDownload() {
        downloadVisible = !downloadVisible
    }

    // 自动切换到歌词界面（播放键点击 + 歌曲列表点击）
    property bool autoSwitchToLyric: true
    // 点击右上角 × 时隐藏到托盘（true）还是退出程序（false）
    property bool closeToTray: true

    // ===== 封面刷新版本号 =====
    // 重新下载封面会覆盖原文件，路径字符串不变，QML Image 的 source
    // 绑定不会重新求值、Qt 图片缓存也不会重载同 URL 的图片，导致
    // 界面一直显示旧封面。把版本号拼进 file:// URL 的 query
    // （封面 ?c=N、背景 ?b=N、缩略图 ?t=N），换 URL 键强制重新加载。
    // （实测 file:// 带 query 可正常加载，且 query 变化会触发重载）
    property int coverStamp: 0

    function switchToLyric() {
        if (autoSwitchToLyric) {
            player.playlistVisible = false
        }
    }

    // ========== 设置持久化 ==========
    function saveSetting(key, value) {
        player.saveSetting(key, String(value))
    }

    function saveAllSettings() {
        saveSetting("darkMode", darkMode)
        saveSetting("customAccent", customAccent)
        saveSetting("customDarkBg", customDarkBg)
        saveSetting("customLightBg", customLightBg)
        saveSetting("customLyricColor", customLyricColor)
        saveSetting("customLyricPlayedColor", customLyricPlayedColor)
        saveSetting("customLyricUnplayedColor", customLyricUnplayedColor)
        saveSetting("customBtnBg", customBtnBg)
        saveSetting("blurRadius", blurRadius)
        saveSetting("panelOpacity", panelOpacity)
        saveSetting("hideControlBackgrounds", hideControlBackgrounds)
        saveSetting("sortMode", player.sortMode)
        saveSetting("rowSpacing", rowSpacing)
        saveSetting("customFontFamily", customFontFamily)
        saveSetting("autoSwitchToLyric", autoSwitchToLyric)
        saveSetting("closeToTray", closeToTray)
        saveSetting("volume", player.volume)
    }

    Component.onCompleted: {
        var s = player.loadSettings()
        if (s.darkMode !== undefined) darkMode = s.darkMode
        if (s.customAccent !== undefined) customAccent = s.customAccent
        if (s.customDarkBg !== undefined) customDarkBg = s.customDarkBg
        if (s.customLightBg !== undefined) customLightBg = s.customLightBg
        if (s.customLyricColor !== undefined) customLyricColor = s.customLyricColor
        if (s.customLyricPlayedColor !== undefined) customLyricPlayedColor = s.customLyricPlayedColor
        if (s.customLyricUnplayedColor !== undefined) customLyricUnplayedColor = s.customLyricUnplayedColor
        if (s.customBtnBg !== undefined) customBtnBg = s.customBtnBg
        
        if (s.blurRadius !== undefined) blurRadius = s.blurRadius
        if (s.panelOpacity !== undefined) panelOpacity = s.panelOpacity
        if (s.hideControlBackgrounds !== undefined) hideControlBackgrounds = s.hideControlBackgrounds
        if (s.sortMode !== undefined) player.sortMode = s.sortMode
        if (s.rowSpacing !== undefined) rowSpacing = s.rowSpacing
        if (s.customFontFamily !== undefined) customFontFamily = s.customFontFamily
        if (s.autoSwitchToLyric !== undefined) autoSwitchToLyric = s.autoSwitchToLyric
        if (s.closeToTray !== undefined) closeToTray = s.closeToTray
        if (s.volume !== undefined) player.volume = s.volume
        if (s.musicDir !== undefined) player.setMusicDir(s.musicDir)
        if (s.lastFile !== undefined && s.lastFile) player.restoreLastPosition()
        saveAllSettings()
    }

    onDarkModeChanged: saveSetting("darkMode", darkMode)
    onCustomAccentChanged: saveSetting("customAccent", customAccent)
    onCustomDarkBgChanged: saveSetting("customDarkBg", customDarkBg)
    onCustomLightBgChanged: saveSetting("customLightBg", customLightBg)
    onCustomLyricColorChanged: saveSetting("customLyricColor", customLyricColor)
    onCustomLyricPlayedColorChanged: saveSetting("customLyricPlayedColor", customLyricPlayedColor)
    onCustomLyricUnplayedColorChanged: saveSetting("customLyricUnplayedColor", customLyricUnplayedColor)
    onCustomBtnBgChanged: saveSetting("customBtnBg", customBtnBg)
    
    onBlurRadiusChanged: saveSetting("blurRadius", blurRadius)
    onPanelOpacityChanged: saveSetting("panelOpacity", panelOpacity)
    onHideControlBackgroundsChanged: saveSetting("hideControlBackgrounds", hideControlBackgrounds)
    onRowSpacingChanged: {
        saveSetting("rowSpacing", rowSpacing)
        // 行间距一变，歌词区里所有行的目标 y 都会跟着变（因为 groupBaseY/targetY
        // 都实时依赖 itemHeight=rowSpacing）。如果任其走正常的弹簧动画过渡，
        // 拖动滑块调节时会看到歌词区一直在"跳来跳去做动画"，观感很差——
        // 用户在调设置，预期是所见即所得地瞬间看到新间距，而不是过渡动画。
        // 复用之前给"切歌瞬间归位"写的 snapAll()：临时关闭每行的 Behavior，
        // 让新的 targetY 直接、无动画地写入 y。
        if (typeof lyricView !== "undefined" && lyricView.snapAll) {
            Qt.callLater(lyricView.snapAll)
        }
    }
    onCustomFontFamilyChanged: saveSetting("customFontFamily", customFontFamily)
    onAutoSwitchToLyricChanged: saveSetting("autoSwitchToLyric", autoSwitchToLyric)
    onCloseToTrayChanged: saveSetting("closeToTray", closeToTray)

    Connections {
        target: player
        function onSortModeChanged() { saveSetting("sortMode", player.sortMode) }
    }
    // ========== 背景图片层（高斯模糊 + 渐变过渡） ==========
    // 使用双层图片（A/B）实现切换渐变。用 _frontIsA 标记当前哪一层在显示（前景），
    // 另一层作为预加载/新图层。过渡时只切换 opacity，两层各自的 source 除了
    // "预加载新图"这一次赋值之外，绝不会在过渡过程中被清空或腾挪——
    // 这是避免闪烁的关键：一旦某层 source 被清空，它对应的 FastBlur 会因为
    // visible 绑定跟着瞬间消失，没有淡出动画，看起来就是"背景瞬间消失一下"。

    // 防止狂点时动画堆积：标记位
    property bool _bgTransitioning: false
    // true：A 层是当前显示的前景；false：B 层是当前显示的前景
    property bool _frontIsA: true
    // 过渡代数：每次开始/提前结束过渡都自增，旧过渡挂起的定时器
    // 凭代数判断自己是否已失效，避免迟到地翻转前后景标记造成错乱
    property int _bgToken: 0

    // A 层：只作为 FastBlur 的取样源，不直接可见。
    // 本地文件用同步加载（asynchronous: false）：切换歌曲时不会出现
    // "中途被新 source 打断" 的异步加载应答，从根上消除
    // "QQuickPixmap: connectFinished() called when not loading" 警告，
    // 也让下面的 status 判断在赋值后立刻就是最终结果。
    Image {
        id: bgImageA
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        source: ""
        asynchronous: false
        smooth: true
        visible: false
    }

    // B 层：只作为 FastBlur 的取样源，不直接可见
    Image {
        id: bgImageB
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        source: ""
        asynchronous: false
        smooth: true
        visible: false
    }

    // A 层的模糊结果：谁在前景就淡入到 1，谁在后景就淡出到 0
    FastBlur {
        id: bgBlurA
        anchors.fill: parent
        source: bgImageA
        radius: blurRadius
        cached: true
        opacity: 0.0
        visible: bgImageA.source !== ""

        Behavior on opacity {
            NumberAnimation { duration: 600; easing.type: Easing.OutCubic }
        }
    }

    // B 层的模糊结果
    FastBlur {
        id: bgBlurB
        anchors.fill: parent
        source: bgImageB
        radius: blurRadius
        cached: true
        opacity: 0.0
        visible: bgImageB.source !== ""

        Behavior on opacity {
            NumberAnimation { duration: 600; easing.type: Easing.OutCubic }
        }
    }

    // 监听歌曲切换，触发渐变过渡
    Connections {
        target: player
        function onSongChanged(index) {
            if (index < 0) return
            window._startBgTransition()
        }
    }

    // 监听封面文件更新（重新下载覆盖同路径文件时），提升版本号
    // 强制所有图片重新加载。
    // 注意：不能简单地再调一次 _startBgTransition()——onSongChanged 已经
    // 触发过一次过渡，这里再叠加一次会让 A/B 状态机和挂起的 650ms 定时器
    // 互相竞争，正是"下载封面后背景消失"的原因。正确做法是：前景层显示的
    // 就是这张封面时，就地重载（换带新版本号的 URL），不做过渡。
    Connections {
        target: player
        function onCoverFileUpdated(path) {
            window.coverStamp++
            var cur = player.currentSongImage
            var frontImg = window._frontImage()
            // 与本次下载前的 URL 精确比较（url 类型没有 indexOf，
            // 且模糊子串匹配可能误伤路径相近的其它歌曲封面）
            var prevUrl = "file://" + cur + "?b=" + (window.coverStamp - 1)
            if (cur && String(frontImg.source) === prevUrl) {
                frontImg.source = "file://" + cur + "?b=" + window.coverStamp
            } else {
                window._startBgTransition()
            }
        }
    }

    // 当前“前景层”的 Image / FastBlur（只读快捷方式，避免重复三元判断）
    function _frontImage() { return window._frontIsA ? bgImageA : bgImageB }
    function _frontBlur() { return window._frontIsA ? bgBlurA : bgBlurB }
    function _backImage() { return window._frontIsA ? bgImageB : bgImageA }
    function _backBlur() { return window._frontIsA ? bgBlurB : bgBlurA }

    // 开始背景图片渐变过渡
    function _startBgTransition() {
        // 背景层使用独立的 query key（?b=），与封面图（?c=）、底栏缩略图
        // （?t=）不同 URL——三个 Image 各自持有独立的加载应答，避免 Qt
        // 图片缓存共享同一 QQuickPixmap 应答、一层被中止加载时其它层收到
        // "connectFinished() called when not loading" 之类的告警。
        var newSource = player.currentSongImage
            ? "file://" + player.currentSongImage + "?b=" + window.coverStamp : ""

        var frontImg = window._frontImage()
        var frontBlur = window._frontBlur()
        var backImg = window._backImage()
        var backBlur = window._backBlur()

        // 情况 1：正在过渡中 → 立即完成当前过渡（交换前后景标记），再用新图重新开始。
        // 先自增代数：让上一个过渡挂起的 650ms 定时器作废，防止它迟到后
        // 再次翻转标记；同时断开两层的挂起连接，防止串层回调。
        if (window._bgTransitioning) {
            window._bgToken++
            bgImageA.statusChanged.disconnect(window._bgOnLoad)
            bgImageB.statusChanged.disconnect(window._bgOnLoad)
            frontBlur.opacity = 0.0
            backBlur.opacity = 1.0
            window._frontIsA = !window._frontIsA
            window._bgTransitioning = false
            // 递归调用自身，用新图重新开始过渡
            window._startBgTransition()
            return
        }

        // 情况 2：新图与当前前景相同 → 无需过渡
        // 注意必须用 String() 转换再比较：frontImg.source 是 url 类型，
        // url 与 string 用 === 比较永远为 false，会导致同图也重复过渡。
        if (newSource === String(frontImg.source))
            return

        // 确保前景持有旧图（如果是首次启动，前景还没图，直接设置前景）
        if (frontImg.source === "") {
            frontImg.source = newSource
            frontBlur.opacity = 1.0
            return
        }

        // 将新图加载到后景层（后景层此刻必定是空闲的，不会影响当前显示）
        backImg.source = newSource

        // 如果图片已经加载完成/失败，立即处理
        if (backImg.status === Image.Ready) {
            window._doBgFade()
        } else if (backImg.status === Image.Error) {
            // 加载失败，直接更新前景（不经过渡，因为没有可用的新图可淡入）
            frontImg.source = newSource
            backImg.source = ""
        } else {
            // 等待加载完成后触发渐变
            backImg.statusChanged.connect(window._bgOnLoad)
        }
    }

    // 后景层图片加载完成后的回调（一次性）
    function _bgOnLoad() {
        // 无论触发的是哪一层，都先把两层挂起的连接全部断开，
        // 防止历史连接在新过渡里串层触发。
        bgImageA.statusChanged.disconnect(window._bgOnLoad)
        bgImageB.statusChanged.disconnect(window._bgOnLoad)
        var backImg = window._backImage()
        if (backImg.status === Image.Ready) {
            window._doBgFade()
        } else {
            backImg.source = ""
        }
    }

    // 执行渐变：前景（旧图）淡出、后景（新图）淡入
    function _doBgFade() {
        window._bgTransitioning = true
        window._bgToken++
        var token = window._bgToken
        window._frontBlur().opacity = 0.0
        window._backBlur().opacity = 1.0

        // 650ms 后完成过渡（比动画 600ms 稍长）。
        // 定时器回调带上自己的代数，只有仍是最新过渡时才翻转标记。
        var timer = Qt.createQmlObject(
            "import QtQuick; Timer { interval: 650; onTriggered: { window._finishBgTransition(" + token + "); } }",
            window)
        timer.start()
    }

    // 完成过渡：只交换前后景标记，不改动任何 source，不清空任何一层
    function _finishBgTransition(token) {
        if (token !== window._bgToken)
            return  // 这个过渡已被更早完成/替换，忽略迟到的回调
        window._frontIsA = !window._frontIsA
        window._bgTransitioning = false
    }


    // ========== 布局 ==========
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // --- 主内容区 ---
        Item {
            id: mainContentArea
            Layout.fillWidth: true
            Layout.fillHeight: true

            RowLayout {
                anchors.fill: parent
                spacing: 0

                // ===== 左侧：始终显示专辑封面 =====
                Rectangle {
                    id: leftPanel
                    Layout.preferredWidth: playlistVisible ? parent.width * 0.38 : parent.width * 0.5
                    Layout.fillHeight: true
                    color: darkMode ? Qt.rgba(0.09, 0.13, 0.24, panelOpacity) : Qt.rgba(1, 1, 1, panelOpacity)
                    clip: true

                    Behavior on Layout.preferredWidth {
                        NumberAnimation { duration: 250; easing.type: Easing.OutCubic }
                    }

                    // 封面视图
                    ColumnLayout {
                        anchors.centerIn: parent
                        width: parent.width * (playlistVisible ? 0.8 : 0.6)
                        spacing: 16

                        Behavior on width {
                            NumberAnimation { duration: 250; easing.type: Easing.OutCubic }
                        }

                        // 封面图片
                        Rectangle {
                            id: coverFrame
                            Layout.preferredWidth: parent.width
                            Layout.preferredHeight: parent.width
                            radius: playlistVisible ? 12 : 16
                            color: bgCard
                            clip: true

                            Behavior on radius {
                                NumberAnimation { duration: 250 }
                            }

                            Rectangle {
                                anchors.fill: parent
                                visible: coverImage.status !== Image.Ready
                                color: bgDark
                                radius: parent.radius

                                ColumnLayout {
                                    anchors.centerIn: parent
                                    spacing: 8

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: "♫"
                                        font.pixelSize: playlistVisible ? 64 : 80
                                        color: textMuted
                                    }
                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: "暂无封面"
                                        font.pixelSize: 13
                                        color: textMuted
                                    }
                                }
                            }

                            Image {
                                id: coverImage
                                anchors.fill: parent
                                fillMode: Image.PreserveAspectCrop
                                source: player.currentSongImage ? "file://" + player.currentSongImage + "?c=" + window.coverStamp : ""
                                asynchronous: false
                                smooth: true
                                visible: status === Image.Ready
                            }

                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                color: "transparent"
                                border.width: 1
                                border.color: Qt.rgba(1, 1, 1, 0.05)
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: player.currentSongName || "未选择歌曲"
                            color: textPrimary
                            font.pixelSize: playlistVisible ? 16 : 18
                            font.bold: true
                            elide: Text.ElideRight
                            maximumLineCount: 2
                            wrapMode: Text.Wrap

                            Behavior on font.pixelSize {
                                NumberAnimation { duration: 200 }
                            }
                        }

                        Row {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 8
                            visible: player.state !== "stopped"

                            Text {
                                text: player.formatTime(player.position)
                                color: textSecondary
                                font.pixelSize: 12
                            }
                            Text {
                                text: "/"
                                color: textMuted
                                font.pixelSize: 12
                            }
                            Text {
                                text: player.formatTime(player.duration)
                                color: textSecondary
                                font.pixelSize: 12
                            }
                        }
                    }
                }

                // ===== 分割线（折叠时显示，分隔封面和歌词） =====
                Rectangle {
                    id: divider
                    width: 1
                    Layout.fillHeight: true
                    color: Qt.rgba(1, 1, 1, 0.06)
                    visible: !playlistVisible
                }

                // ===== 右侧：播放列表（展开时）/ 歌词（折叠时） =====
                Rectangle {
                    id: rightPanel
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: darkMode ? Qt.rgba(0.1, 0.1, 0.18, panelOpacity) : Qt.rgba(1, 1, 1, panelOpacity)
                    clip: true

                    // ---- 播放列表（展开时显示） ----
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        visible: playlistVisible

                        // 标题栏
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            color: darkMode ? Qt.rgba(0.09, 0.13, 0.24, panelOpacity) : Qt.rgba(1, 1, 1, panelOpacity)

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16

                                Text {
                                    text: "播放列表"
                                    color: textPrimary
                                    font.pixelSize: 15
                                    font.bold: true
                                }

                                // 排序按钮：循环切换 4 种排序模式
                                Rectangle {
                                    width: 28
                                    height: 28
                                    radius: 6
                                    color: sortBtnHovered ? Qt.rgba(accent.r, accent.g, accent.b, 0.2) : "transparent"

                                    property bool sortBtnHovered: false

                                    Image {
                                        anchors.centerIn: parent
                                        width: 18
                                        height: 18
                                        source: {
                                            switch (player.sortMode) {
                                                case 0: return "icons/sort-name-asc.svg"
                                                case 1: return "icons/sort-name-desc.svg"
                                                case 2: return "icons/sort-time-asc.svg"
                                                default: return "icons/sort-time-desc.svg"
                                            }
                                        }
                                        sourceSize.width: 18
                                        sourceSize.height: 18
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: player.sortMode = (player.sortMode + 1) % 4
                                        onEntered: parent.sortBtnHovered = true
                                        onExited: parent.sortBtnHovered = false
                                    }
                                }

                                Item { Layout.fillWidth: true }

                                Text {
                                    text: player.songCount + " 首"
                                    color: textMuted
                                    font.pixelSize: 12
                                }
                            }
                        }

                        // 列表
                        ListView {
                            id: songListView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: player.songListModel
                            currentIndex: player.currentIndex
                            boundsBehavior: Flickable.StopAtBounds
                            flickDeceleration: 3000
                            maximumFlickVelocity: 4000
                            ScrollBar.vertical: ScrollBar {
                                policy: ScrollBar.AlwaysOn
                                width: 12
                                contentItem: Rectangle {
                                    radius: 6
                                    color: accent
                                    opacity: 0.7
                                }
                            }

                            // ===== 居中控制（用户滚动打断，3 秒后自动恢复） =====
                            property real _viewCenter: songListView.height * 0.5
                            property real _itemHeight: rowSpacing
                            property real _centerOffset: _viewCenter - _itemHeight * 0.5

                            // 用户滚动时冻结 header/footer 高度，停止跟随 currentIndex
                            property real _frozenH: 0
                            property real _frozenF: 0
                            property bool _frozen: false

                            // 用户正在手动滚动
                            property bool _userScrolling: dragging || flicking

                            function _freeze() {
                                songListView._frozenH = Math.max(0,
                                    songListView._centerOffset - songListView.currentIndex * songListView._itemHeight)
                                songListView._frozenF = Math.max(0,
                                    songListView.height - songListView._viewCenter - songListView._itemHeight * 0.5
                                    - (player.songCount - 1 - songListView.currentIndex) * songListView._itemHeight)
                                songListView._frozen = true
                                songListResumeTimer.stop()
                            }

                            function _unfreeze() {
                                songListView._frozen = false
                            }

                            onDraggingChanged: {
                                if (dragging) songListView._freeze()
                                else if (!flicking) songListResumeTimer.restart()
                            }
                            onFlickingChanged: {
                                if (flicking) songListView._freeze()
                                else if (!dragging) songListResumeTimer.restart()
                            }

                            Timer {
                                id: songListResumeTimer
                                interval: 3000
                                onTriggered: {
                                    songListView._unfreeze()
                                }
                            }

                            onCurrentIndexChanged: {
                                if (!songListView._userScrolling) {
                                    songListView._unfreeze()
                                    var targetY = songListView.currentIndex * songListView._itemHeight - songListView._centerOffset
                                    songListView.contentY = Math.max(0, targetY)
                                }
                            }

                            headerPositioning: ListView.InlineHeader
                            footerPositioning: ListView.InlineFooter

                            header: Item {
                                height: songListView._frozen
                                    ? songListView._frozenH
                                    : Math.max(0, songListView._centerOffset - songListView.currentIndex * songListView._itemHeight)
                                Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                                clip: true
                                Text {
                                    anchors.centerIn: parent
                                    text: {
                                        var lines = Math.floor(parent.height / rowSpacing)
                                        var s = ""
                                        for (var i = 0; i < lines; i++) s += "—\n"
                                        return s
                                    }
                                    color: textMuted
                                    font.pixelSize: 13
                                    opacity: 0.4
                                    visible: parent.height > rowSpacing * 0.5
                                }
                            }
                            footer: Item {
                                height: songListView._frozen
                                    ? songListView._frozenF
                                    : Math.max(0, songListView.height - songListView._viewCenter - songListView._itemHeight * 0.5
                                                 - (player.songCount - 1 - songListView.currentIndex) * songListView._itemHeight)
                                Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
                                clip: true
                                Text {
                                    anchors.centerIn: parent
                                    text: {
                                        var lines = Math.floor(parent.height / rowSpacing)
                                        var s = ""
                                        for (var i = 0; i < lines; i++) s += "—\n"
                                        return s
                                    }
                                    color: textMuted
                                    font.pixelSize: 13
                                    opacity: 0.4
                                    visible: parent.height > rowSpacing * 0.5
                                }
                            }

                            Component.onCompleted: Qt.callLater(function() {
                                var targetY = songListView.currentIndex * songListView._itemHeight - songListView._centerOffset
                                songListView.contentY = Math.max(0, targetY)
                            })

                            Connections {
                                target: window
                                function onPlaylistVisibleChanged() {
                                    if (playlistVisible) {
                                        Qt.callLater(function() {
                                            songListView._unfreeze()
                                            var targetY = songListView.currentIndex * songListView._itemHeight - songListView._centerOffset
                                            songListView.contentY = Math.max(0, targetY)
                                        })
                                    }
                                }
                            }

                            Connections {
                                target: player
                                function onSortModeChanged() {
                                    songListView._unfreeze()
                                    var targetY = songListView.currentIndex * songListView._itemHeight - songListView._centerOffset
                                    songListView.contentY = Math.max(0, targetY)
                                }
                            }

                            delegate: Rectangle {
                                width: songListView.width
                                height: rowSpacing
                                color: {
                                    if (index === player.currentIndex) return Qt.rgba(0.913, 0.271, 0.376, 0.15)
                                    if (mouseArea.containsMouse) return Qt.rgba(1, 1, 1, 0.04)
                                    return "transparent"
                                }
                                Behavior on color { ColorAnimation { duration: 120 } }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 16
                                    anchors.rightMargin: 16
                                    spacing: 12

                                    // 序号/播放指示
                                    Rectangle {
                                        Layout.preferredWidth: 24
                                        Layout.preferredHeight: 24
                                        radius: 12
                                        color: index === player.currentIndex ? accent : "transparent"
                                        border.width: index === player.currentIndex ? 0 : 1
                                        border.color: textMuted

                                        Text {
                                            anchors.centerIn: parent
                                            text: index === player.currentIndex ? "▶" : (index + 1)
                                            color: index === player.currentIndex ? "#fff" : textMuted
                                            font.pixelSize: index === player.currentIndex ? 10 : 11
                                        }
                                    }

                                    // 歌曲名
                                    Text {
                                        Layout.fillWidth: true
                                        text: player.songName(index) || "未知"
                                        color: index === player.currentIndex ? accent : textPrimary
                                        font.family: customFontFamily !== "" ? customFontFamily : window.font.family
                                        font.pixelSize: 13
                                        font.bold: index === player.currentIndex
                                        elide: Text.ElideRight
                                    }

                                    // 有封面的标记
                                    Text {
                                        visible: player.songImage(index) !== ""
                                        text: "🖼"
                                        color: textMuted
                                        font.pixelSize: 11
                                    }
                                }

                                MouseArea {
                                    id: mouseArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        player.currentIndex = index
                                        window.switchToLyric()
                                        player.play()
                                    }
                                }
                            }
                        }
                    }

                    // ---- 歌词视图（折叠时显示） ----
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0
                        visible: !playlistVisible

                        // 歌词标题
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            color: "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: "歌词"
                                color: textSecondary
                                font.pixelSize: 13
                            }
                        }

                        // 歌词列表
                        // ===== 新版逐行独立动画歌词视图 =====
                        // 不再用 ListView.contentY 整体平移；改为 Repeater 生成每一行，
                        // 每行自己持有一个"目标位置" targetY，用 SpringAnimation 独立地
                        // 追向目标。当 currentIndex 变化时，所有行的 targetY 同时更新，
                        // 但因为每行的弹簧动画是独立运行的实例（不同的当前值/速度），
                        // 视觉上就会出现"上一行先到位，其余行按各自节奏慢慢跟上"的错落感，
                        // 而不是所有行整体在同一时刻同步滑动。
                        //
                        // 高亮 + 放大不再是布尔跳变，而是基于"行中心到高亮区中心的距离"
                        // 连续计算出的 0~1 进度值 highlightProgress，颜色、字号都由它插值，
                        // 所以文字在滑入/滑出高亮区边缘时会平滑地渐变、缩放，而不是一进入
                        // 索引命中就瞬间跳变。
                        Item {
                            id: lyricView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.leftMargin: 32
                            Layout.rightMargin: 32
                            clip: true

                            // ===== 高亮区域中心：基于"歌词所在的主内容区"，而不是整个窗口 =====
                            // 之前的写法 "height * 0.4" 里的 height 是 lyricView 自己的高度——
                            // lyricView 上方还叠着一个"歌词"标题栏（48px），如果只按 lyricView
                            // 自身高度算比例，这个标题栏占的空间会被排除在外，"40%处"实际上是
                            // 相对"去掉标题栏之后剩余区域"的 40%，跟直觉上"整个歌词页面的
                            // 40%"不是同一回事。
                            //
                            // 后来尝试过换成 window.height（整个窗口高度）——但这样又把窗口
                            // 底部的播放控制栏（bottomBar，固定 72px）也算进去了，高亮区的
                            // 定位基准包含了一段跟歌词显示完全无关的区域，不是用户想要的。
                            //
                            // 正确的参照系应该是：mainContentArea——也就是根布局里"主内容区"
                            // 那个 Item，它上包含左侧封面/右侧歌词两栏（含"歌词"标题栏），
                            // 但不包含底部固定 72px 的播放控制栏。用它的高度算 40% 比例，
                            // 高亮区就正好落在"歌词显示窗口"（含标题栏、不含底部控件栏）的
                            // 纵向 40% 处，且不管窗口怎么缩放都保持这个比例不变。
                            //
                            // 重要坑点（已修正）：最初尝试直接把 mapFromItem(...) 的返回值
                            // 写进一个 property 绑定表达式里，想让它自动跟着窗口/布局变化
                            // 重新求值。但 QML 的绑定依赖追踪只认"表达式里直接读取了哪些
                            // 可观察属性"，mapFromItem 内部做的坐标变换并不通过读取这类
                            // 属性完成，引擎完全感知不到它的结果依赖了什么——于是窗口一旦
                            // 被拖拽缩放，这个绑定根本不会重新求值，_topOffset 会停留在
                            // 第一次算出来的旧值上，centerY 也就跟着长期算错，只是平时窗口
                            // 不缩放的话很难注意到。
                            //
                            // 修法：显式地把"所有会影响这个偏移量的几何属性"都在表达式里
                            // 读一遍，哪怕值本身没直接用到——只要读取了，就会被登记为依赖，
                            // 对应的属性一变，这条绑定就会被强制重新求值。
                            property real _topOffset: {
                                // 强制建立依赖：读一遍自身的位置/尺寸和参照容器的尺寸，
                                // 确保它们任意一个变化时这条绑定都会重新求值
                                var _dep1 = lyricView.x
                                var _dep2 = lyricView.y
                                var _dep3 = lyricView.width
                                var _dep4 = lyricView.height
                                var _dep5 = mainContentArea.width
                                var _dep6 = mainContentArea.height
                                var p = mapFromItem(mainContentArea, 0, 0)
                                return -p.y
                            }
                            readonly property real centerY: _topOffset + mainContentArea.height * 0.4
                            // 每行的基准行高（放大时行本身高度不变，只有文字 scale 变大，
                            // 避免因为行高跳变导致相邻行跟着抖动）
                            readonly property real itemHeight: rowSpacing
                            // 高亮时的最大缩放倍数
                            readonly property real maxScale: 1.28

                            // ===== 双语对照行分组 =====
                            // 后端 parse_lrc_text() 会把形如 "[00:12.00]日本語/中文翻译"
                            // 这种带 "/" 的双语行拆成两条独立记录，但拆出来的两条记录
                            // 时间戳完全相同、且在数组里紧挨着（Python sort 是稳定排序，
                            // 同一时间戳的多条记录会保持原始相对顺序不变）。
                            // 于是只需要比较"这一行的时间戳是否和上一行相同"，就能不依赖
                            // 任何额外后端接口，纯前端识别出"哪些行属于同一对原文/译文"。
                            //
                            // groupOf[i]：第 i 行所属的组号（同一对歌词组号相同）
                            // groupBaseOffset[g]：第 g 组相对于"组 0"的基准累积偏移量，
                            // 用组间距 itemHeight 累加而来（不含组内间距）
                            // indexInGroup[i]：第 i 行在其所属组内的序号（0 或 1，理论上
                            // 双语最多两行；如果超过 2 行的极端情况也按顺序往下排）
                            //
                            // 组内两行之间的间距用 groupInnerGap。
                            //
                            // 重要：这里不能写成 "itemHeight * 某系数"——itemHeight 就是
                            // 用户在设置里拖动的 rowSpacing（行间距滑块），如果组内间距跟着
                            // itemHeight 等比例缩放，会导致"调节行间距"这个操作看起来像是在
                            // 调节"原文和译文之间的距离"（因为组内间距的绝对变化量往往比组间
                            // 距的变化更显眼），这正是用户反馈的 bug。
                            //
                            // 正确语义应该是：rowSpacing 只控制"组与组"（也就是句子与句子）
                            // 之间的距离；原文↔译文的贴近程度是排版上的固定观感，不应该被
                            // "行间距"这个设置影响。所以这里用一个不依赖 rowSpacing 的固定
                            // 像素值，且限制在一个合理范围内（不会比 itemHeight 本身还大，
                            // 否则两行看起来反而比组间距更松散，失去"贴近"的效果）。
                            readonly property real groupInnerGap: Math.min(30, itemHeight * 0.75)

                            property var groupOf: []
                            property var indexInGroup: []
                            property var groupSize: []
                            // groupBaseY[g]：第 g 组"组内第 0 行"相对于第 0 组的累积偏移。
                            //
                            // 重要修正：这个值必须是"纯声明式绑定"，不能算好之后存成普通
                            // 数值再也不更新——之前的版本里这个数组是在 rebuildGroups() 这个
                            // 命令式函数内部用当时的 itemHeight 算出来、然后固定存下来的，
                            // 只有 rebuildGroups() 被重新调用（即歌词切换时）才会重算。
                            // 于是拖动"行间距"滑块改变 itemHeight 时，groupBaseY 完全不会
                            // 跟着更新，但 currentTargetBase() 里其它用到 itemHeight 的地方
                            // （比如 centerY - itemHeight * 0.5）却是实时绑定、立刻用新值——
                            // 新旧 itemHeight 在同一个公式里混用，会让所有行的目标位置一起
                            // 产生一个固定的偏移量，而 groupBaseY 数组内部各组之间的相对差值
                            // 还是按旧 itemHeight 算的、彼此间距不变——这正是"整体跟着挪动，
                            // 但相对距离锁死不变"这个 bug 的根源。
                            //
                            // 改成这样的 binding 表达式后，只要 itemHeight 或 groupCount
                            // 变化，QML 会自动重新求值整个数组，永远和当前 itemHeight 同步。
                            readonly property var groupBaseY: {
                                var arr = []
                                var base = 0
                                for (var g = 0; g < groupCount; g++) {
                                    arr.push(base)
                                    base += itemHeight
                                }
                                return arr
                            }
                            // 组的总数，供上面的 groupBaseY 绑定使用（分组数量本身只在
                            // rebuildGroups 里，随歌词内容变化才会变，这里单独存一份）
                            property int groupCount: 0
                            // currentGroupIndex：当前播放行所在的组号，供高亮判断使用
                            readonly property int currentGroupIndex:
                                (groupOf.length > player.currentLyricIndex && player.currentLyricIndex >= 0)
                                    ? groupOf[player.currentLyricIndex] : -1

                            function rebuildGroups() {
                                var count = player.lyricCount
                                var gOf = []
                                var iInG = []
                                var gSize = []
                                var g = -1
                                var lastTime = null
                                var curGroupStart = 0
                                for (var i = 0; i < count; i++) {
                                    var t = player.lyricTime(i)
                                    if (lastTime === null || t !== lastTime) {
                                        g += 1
                                        curGroupStart = i
                                    }
                                    gOf.push(g)
                                    iInG.push(i - curGroupStart)
                                    lastTime = t
                                }
                                // 回填每组的行数 groupSize
                                for (var gi = 0; gi <= g; gi++) gSize.push(0)
                                for (var j = 0; j < count; j++) gSize[gOf[j]] += 1

                                groupOf = gOf
                                indexInGroup = iInG
                                groupSize = gSize
                                // groupCount 只依赖分组结构（歌词内容），不依赖 itemHeight；
                                // 触发 groupBaseY 的 binding 重新求值靠的是它被读取时自动
                                // 建立的依赖关系，这里赋值即可，具体的像素值交给上面的
                                // binding 表达式实时算，不在这里手动拼数组。
                                groupCount = g + 1
                            }

                            // 第 idx 行相对于"第 0 组基准位置"的纵向偏移：
                            // 组间用 itemHeight 累加，组内额外再加 indexInGroup * groupInnerGap，
                            // 因为组内间距更小，两行会明显比"组与组之间"靠得更近。
                            function rowOffsetInStack(idx) {
                                if (idx < 0 || idx >= groupOf.length) return 0
                                return groupBaseY[groupOf[idx]] + indexInGroup[idx] * groupInnerGap
                            }

                            // 手动滚动产生的额外偏移量（在自动居中位置基础上叠加）
                            property real manualOffset: 0
                            // 用户是否正处于"手动浏览歌词"状态（滚轮滚动中，或滚动后
                            // 还没归位的 3 秒等待期）。这段时间内每行的延迟归零，
                            // 保证滚轮手感跟手；只有回到"跟随播放自动滚动"时才启用
                            // 按距离错落延迟的效果。
                            property bool manualScrolling: false

                            function currentTargetBase(idx) {
                                // 第 idx 行的基准 y：让"当前播放行所在组的组内第 0 行"
                                // 居中于高亮区，其余行按 rowOffsetInStack 的相对偏移量
                                // 跟随排布——这样无论 currentLyricIndex 命中的是原文还是
                                // 译文，同一组的两行都会一起移动到高亮区附近。
                                var curIdx = player.currentLyricIndex
                                if (curIdx < 0 || groupOf.length === 0) {
                                    return centerY - itemHeight * 0.5 - (curIdx - idx) * itemHeight
                                }
                                var curGroupBase = groupBaseY.length > groupOf[curIdx] ? groupBaseY[groupOf[curIdx]] : 0
                                return centerY - itemHeight * 0.5 - (curGroupBase - rowOffsetInStack(idx))
                            }

                            // 首次加载时：先建分组表，再让所有行瞬间归位到正确位置。
                            // 注意：这两步必须写在同一个 Component.onCompleted 里——
                            // QML 不允许同一个对象上出现两个 Component.onCompleted
                            // （会报 "Property value set multiple times" 而拒绝加载整个文件）。
                            // 之前误把 rebuildGroups() 和 snapAll() 分别写在了两处
                            // Component.onCompleted 里，就是这个报错的直接原因。
                            Component.onCompleted: {
                                rebuildGroups()
                                Qt.callLater(snapAll)
                            }

                            Timer {
                                id: resumeAutoScrollTimer
                                interval: 3000
                                onTriggered: {
                                    manualOffsetAnim.stop()
                                    manualOffsetAnim.from = lyricView.manualOffset
                                    manualOffsetAnim.to = 0
                                    manualOffsetAnim.start()
                                }
                            }
                            NumberAnimation {
                                id: manualOffsetAnim
                                target: lyricView
                                property: "manualOffset"
                                duration: 400
                                easing.type: Easing.OutCubic
                                // 注意：不能用 "onStopped: if (to === 0) ..." 来判断回中是否
                                // 完成——因为滚轮里的 manualOffsetAnim.stop() 打断动画时也会
                                // 触发 onStopped，且此时 to 很可能残留着上一次设的值（0），
                                // 会被误判成"回中完成"，导致用户还在滚动时延迟错落效果就
                                // 提前被打开、手感发飘。改为动画"自然播放完毕"时才触发的
                                // onFinished（Qt: finished() 不会在 stop() 手动打断时触发，
                                // 只在动画自己跑完时触发），这样能准确区分
                                // "回中动画正常走完" vs "被新的滚动打断"。
                                onFinished: lyricView.manualScrolling = false
                            }

                            // 鼠标滚轮：手动浏览歌词，3 秒无操作后自动回到当前播放行
                            WheelHandler {
                                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                onWheel: (event) => {
                                    lyricView.manualScrolling = true
                                    manualOffsetAnim.stop()
                                    lyricView.manualOffset += event.angleDelta.y / 120 * rowSpacing
                                    resumeAutoScrollTimer.restart()
                                }
                            }

                            Repeater {
                                id: lyricRepeater
                                model: player.lyricCount

                                delegate: Item {
                                    id: lyricRow
                                    width: lyricView.width
                                    height: lyricView.itemHeight
                                    x: 0

                                    // 目标 y：基准位置 + 手动滚动偏移
                                    property real targetY: lyricView.currentTargetBase(index) + lyricView.manualOffset

                                    // 这一行所在的组号 / 组内序号（组号相同 = 同一对原文/译文）。
                                    property int _groupIdx: lyricView.groupOf.length > index ? lyricView.groupOf[index] : index
                                    property int _idxInGroup: lyricView.indexInGroup.length > index ? lyricView.indexInGroup[index] : 0

                                    y: targetY
                                    // ===== 错落跟随的核心：按"离当前播放组的距离"给延迟 =====
                                    // 之前的版本里所有行用完全相同的 SpringAnimation、
                                    // 且在同一 tick 收到新的 targetY，于是所有行的运动轨迹
                                    // 几乎重合，看起来是"整体同步"而不是"一行一行跟上"。
                                    //
                                    // 这里借用 CSS 里 transition-delay 的思路：每一行的动画
                                    // 前面先插入一段 PauseAnimation，暂停时长由"组距离"决定——
                                    // 越靠近当前播放组的组延迟越短（几乎立即跟上），越远的组
                                    // 延迟越长（拖在后面）。
                                    //
                                    // 关键点：延迟必须按"组号距离"算，不能按"行号距离"算——
                                    // 如果按行号算，同一组内原文行和译文行的 index 不同，会算出
                                    // 不同的延迟，导致两行的弹簧动画不同步启动。而
                                    // _groupBaseRowY（下面）是用"当前行的 y 反推组基准行位置"
                                    // 算出来的，一旦两行延迟不一致，动画过程中反推出来的组基准
                                    // 位置会短暂对不上、产生抖动。按组号算延迟，同组两行的
                                    // yDelay 完全相同，弹簧动画会同步启动、同步运动，从而保证
                                    // 整组在动画的每一帧都严格保持"靠在一起、一起高亮"。
                                    property int _distanceFromCurrentGroup: Math.abs(_groupIdx - lyricView.currentGroupIndex)
                                    // 每远一组多延迟的毫秒数；这个系数越大，错落感越明显，
                                    // 但太大会显得"追不上"、观感涣散，30~50 之间比较自然。
                                    //
                                    // 注意：之前用 32ms 这个系数时，实际观感上几乎看不出"一行
                                    // 一行跟上"的错落，看起来像所有行整体同步移动。原因不是
                                    // 延迟机制没生效——延迟值本身确实是按组距离正确算出来的，
                                    // 不同行确实拿到了不同的延迟——而是下面 SpringAnimation
                                    // 的参数（spring:3.2, damping:0.42）收敛速度太快，运动
                                    // 本身可能一两百毫秒就基本走完，这时候几十毫秒的启动时差
                                    // 在整个运动过程里占比太小，视觉上被"弹簧跑得快"盖过了。
                                    // 现在把延迟系数调大、同时把弹簧参数放缓（见下面 spring/
                                    // damping），让整个追赶过程拉长，这样启动时差才能在过程中
                                    // 被明显看出来。
                                    readonly property int perLineDelay: 55
                                    // 延迟设上限，避免离得特别远的组（比如歌词一次滚很多行）
                                    // 要等待过长时间才开始动，看起来像卡住了
                                    property int _rawDelay: Math.min(_distanceFromCurrentGroup * perLineDelay, 380)
                                    // 用户手动滚动歌词时不应该有这种"错落延迟"的观感——那样会
                                    // 显得歌词对滚轮操作的响应发飘、不跟手。只有在跟随播放自动
                                    // 滚动（currentLyricIndex 变化）时才启用延迟；手动滚动
                                    // （lyricView.manualOffset 变化）时延迟归零，所有行同步跟手。
                                    property int yDelay: lyricView.manualScrolling ? 0 : _rawDelay

                                    property alias yBehaviorEnabled: yBehavior.enabled
                                    Behavior on y {
                                        id: yBehavior
                                        SequentialAnimation {
                                            PauseAnimation { duration: lyricRow.yDelay }
                                            // spring 调小、damping 调大：让追赶过程本身拉长、
                                            // 更"软"一些，弹簧收敛不再是几乎瞬间完成，这样
                                            // 上面的启动延迟差才有足够的时间窗口被看出来，
                                            // 而不是被极快的弹簧运动盖过。
                                            SpringAnimation {
                                                spring: 1.8
                                                damping: 0.55
                                                mass: 1.0
                                                epsilon: 0.05
                                            }
                                        }
                                    }

                                    // ===== 线性距离缩放（和"上一行退出"用同一套逻辑） =====
                                    // 之前尝试过"按组距离分三档（1.0/0.5/0）+ 人为延迟"的方案，
                                    // 想借延迟制造"当前行先动、下一行稍后跟上"的层次感——
                                    // 但这是治标不治本：只要两行的目标值在同一时刻更新，
                                    // 不管延迟多短，起步时间点的"错位感"始终是刻意做出来的，
                                    // 而不是自然的物理结果，看起来还是会有"当前行和下一行
                                    // 同时在变"的观感，因为延迟结束后两者又会重新同步推进。
                                    //
                                    // 回到最朴素也最自然的方案：不再区分"进入"和"退出"两套
                                    // 逻辑，统一用"这一行中心到高亮区中心的连续像素距离"来
                                    // 线性插值 highlightProgress——distance 越小，progress 越
                                    // 接近 1；distance 越大，progress 越接近 0。这样当前行
                                    // （distance 几乎是 0）天然比下一行（distance 还有小半个
                                    // itemHeight）progress 更高、放大更多，两者的缩放程度
                                    // 差异完全由"位置差"自然决定，不需要任何延迟或分档去
                                    // 人为制造区分——这正好和"上一行退出高亮区"时的连续渐变
                                    // 是同一套数学关系，进入和退出对称、手感一致。
                                    //
                                    // fadeRange：距离超过这个像素值就完全不高亮了。控件距离
                                    // （即 rowSpacing/itemHeight）越大，理论上这个值也应该
                                    // 适当放大，这样无论行间距怎么调，"当前行→下一行"这段
                                    // 距离占 fadeRange 的比例基本不变，保持一致的视觉手感。
                                    readonly property real fadeRange: lyricView.itemHeight * 1.35
                                    property real highlightProgress: Math.max(0, Math.min(1,
                                        1 - distance / fadeRange))
                                    Behavior on highlightProgress {
                                        NumberAnimation {
                                            duration: 60
                                            easing.type: Easing.OutCubic
                                        }
                                    }

                                    // _groupBaseRowY：用当前行的实际 y 反推出"如果这行是组内
                                    // 第 0 行，它现在应该在哪"，从而让同组的原文行和译文行
                                    // 拿到完全相同的 distance/highlightProgress——只要两行的
                                    // y 动画全程保持组内固定的相对偏移（groupInnerGap），
                                    // 这个反推在数学上就是精确成立的，不依赖两行动画是否
                                    // 同步启动。这一步逻辑保持不变，双语对照行"一起高亮、
                                    // 一起缩放"的效果不受这次改动影响。
                                    property real _groupBaseRowY: y - _idxInGroup * lyricView.groupInnerGap
                                    property real distance: Math.abs(_groupBaseRowY + lyricView.itemHeight * 0.5 - lyricView.centerY)

                                    // 是否正在"接近"高亮区中心（true=放大中，false=缩小中）。
                                    // 用距离的变化方向判断：距离在减小 → 正在进入 → 放大；
                                    // 距离在增大 → 正在离开 → 缩小。用命令式 handler 显式地
                                    // "先比较、再更新缓存"，避免两个 binding 同时监听同一
                                    // 信号时求值顺序不确定的问题。
                                    property real _lastDistance: 999999
                                    property bool growing: true
                                    onDistanceChanged: {
                                        growing = distance < _lastDistance
                                        _lastDistance = distance
                                    }

                                    Text {
                                        id: lyricText
                                        anchors.centerIn: parent
                                        width: parent.width
                                        text: player.lyricText(index)

                                        // 颜色在"未播放色/已播放色"与"高亮色"之间连续插值：
                                        // 已经划过高亮区（所在组在当前组之前）的行以"已播放色"
                                        // 为基底，还没到的以"未播放色"为基底，随 highlightProgress
                                        // 叠加高亮色。
                                        //
                                        // 注意：这里必须比较"组号"而不是原始行号 index——
                                        // 因为 currentLyricIndex 命中的可能是对照组里下标更大的
                                        // 那一条（例如原文在前、译文在后时，二分查找会命中译文行）。
                                        // 如果直接用 index < player.currentLyricIndex 判断，
                                        // 同组内的原文行会因为它的 index 小于 currentLyricIndex
                                        // 而被误判成"已播放"变灰，即使它和译文行其实同属一组、
                                        // 应该一起保持高亮，不应该提前变暗。
                                        color: {
                                            var unplayed = window._resolvedLyricUnplayedColor
                                            var played = window._resolvedLyricPlayedColor
                                            var highlight = window._resolvedLyricColor
                                            var base = (lyricRow._groupIdx < lyricView.currentGroupIndex) ? played : unplayed
                                            return Qt.tint(base, Qt.rgba(highlight.r, highlight.g, highlight.b, lyricRow.highlightProgress * 0.9))
                                        }

                                        font.family: customFontFamily !== "" ? customFontFamily : window.font.family
                                        font.pixelSize: 14
                                        // 注意：这里不用 font.bold 来强调当前行——bold 是一个
                                        // 布尔值，字重要么是常规、要么是加粗，中间没有过渡态，
                                        // Qt/Text 引擎没办法把"变粗"这个动作按帧插值，所以只要
                                        // highlightProgress 跨过某个阈值，字重必然是一次性瞬间
                                        // 跳变，这正是之前"淡出变细很突兀"的根源——并不是曲线或
                                        // 延迟设置得不对，而是这个属性本身不支持连续过渡。
                                        //
                                        // （也考虑过用 font.weight 数值插值，理论上 QML 支持
                                        // 100~900 的连续数值，但大多数系统字体、尤其是中文字体
                                        // 实际只内置了少数几档可用字重，渲染引擎会把中间值就近
                                        // 取整到最近的档位，效果上还是会有台阶感的跳变，只是
                                        // 从一次跳变变成两三次小跳变，没有真正解决问题。）
                                        //
                                        // 当前行的"更醒目"已经完全由下面连续过渡的 scale（放大）
                                        // 和上面连续过渡的 color（颜色渐亮）来体现，不再需要额外
                                        // 叠加一个不连续的加粗效果。

                                        // 用 scale 而不是改 font.pixelSize 来放大：
                                        // font.pixelSize 变化会触发文字重新排版/重新光栅化，
                                        // 连续插值下每帧都变字号开销大也容易抖动；
                                        // scale 是纯合成层变换，GPU 加速，插值完全平滑，
                                        // 且不会影响旁边行的布局位置，能稳定跑在 60fps。
                                        scale: 1.0 + (lyricView.maxScale - 1.0) * lyricRow.highlightProgress
                                        transformOrigin: Item.Center

                                        // 缩放动画曲线：进入时用 OutBack 制造"冲一下再回弹"的
                                        // 弹性观感，退出时更快更干脆地收回去，两个方向手感不同，
                                        // 更接近主流播放器里的那种细节质感。
                                        Behavior on scale {
                                            NumberAnimation {
                                                duration: lyricRow.growing ? 320 : 220
                                                easing.type: lyricRow.growing ? Easing.OutBack : Easing.OutCubic
                                                easing.overshoot: 1.6
                                            }
                                        }
                                        Behavior on color {
                                            ColorAnimation { duration: 200 }
                                        }

                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.Wrap
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                        lineHeight: 1.3
                                    }
                                }
                            }

                            // 首次加载 / 切歌时，让所有行直接跳到目标位置，不要从旧位置弹一遍。
                            // 注意：不能写 row.y = row.targetY ——因为 y 本身是靠
                            // "y: targetY" 这行声明式绑定来跟随的，任何脚本里对 y 的
                            // 直接赋值都会当场摧毁这个绑定，之后 y 就再也不会自动跟随
                            // targetY 变化了。正确做法是只关掉每行的 Behavior，然后
                            // "触发"绑定重新求值——做法是先记下 currentLyricIndex 相关的
                            // 依赖不变，直接调用 Qt.callLater 在下一帧关闭动画期间
                            // 让已经变化的 targetY 直接、无动画地写入 y（绑定本身仍然完整）。
                            function snapAll() {
                                for (var i = 0; i < lyricRepeater.count; i++) {
                                    var row = lyricRepeater.itemAt(i)
                                    if (row) row.yBehaviorEnabled = false
                                }
                                // 关闭 Behavior 后，绑定已经把 y 更新为最新的 targetY
                                // （因为 currentLyricIndex/manualOffset 早已变化，只是之前
                                // 被 Behavior 动画拦下来了；这里 disable 之后，Qt 会在本帧
                                // 把 y 直接同步为绑定表达式的当前值，无过渡）。
                                // 下一帧再恢复 Behavior，后续变化重新走动画。
                                Qt.callLater(function() {
                                    for (var i = 0; i < lyricRepeater.count; i++) {
                                        var row = lyricRepeater.itemAt(i)
                                        if (row) row.yBehaviorEnabled = true
                                    }
                                })
                            }

                            // 注意：切歌时的"瞬间归位"不能挂在 player.songChanged 上触发——
                            // 查看 main.py 可知歌词是在 _async_load_metadata() 里异步加载的
                            // （_load_lyrics() 调用点在 durationChanged.emit() 之后），
                            // 也就是说 songChanged 触发的那一刻，新歌的歌词大概率还没加载完，
                            // 这时候去 rebuildGroups()/snapAll() 用到的还是上一首歌的分组表
                            // 和行数，会整个错位。真正代表"歌词数据已经就绪"的信号是
                            // lyricsChanged（_load_lyrics 末尾发出），所以分组重建和瞬间归位
                            // 都应该挂在 lyricsChanged 上，而不是 songChanged。
                            //
                            // 顺序也很重要：必须先 rebuildGroups() 算出新的分组表，
                            // 再执行 snapAll()——否则 snapAll 触发绑定重新求值时，
                            // currentTargetBase()/rowOffsetInStack() 用到的 groupOf 等数组
                            // 还是旧的，位置会算错。
                            Connections {
                                target: player
                                function onLyricsChanged() {
                                    lyricView.manualOffset = 0
                                    lyricView.rebuildGroups()
                                    Qt.callLater(lyricView.snapAll)
                                }
                            }
                        }

                        // 底部：歌曲名 + 时间
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            color: "transparent"

                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: player.currentSongName || ""
                                    color: textPrimary
                                    font.pixelSize: 14
                                    font.bold: true
                                    elide: Text.ElideRight
                                    maximumLineCount: 1
                                }

                                Row {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 8
                                    visible: player.state !== "stopped"

                                    Text {
                                        text: player.formatTime(player.position)
                                        color: textSecondary
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: "/"
                                        color: textMuted
                                        font.pixelSize: 12
                                    }
                                    Text {
                                        text: player.formatTime(player.duration)
                                        color: textSecondary
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ===== 底部控制栏 =====
        Rectangle {
            id: bottomBar
            Layout.fillWidth: true
            Layout.preferredHeight: 72
            color: darkMode ? Qt.rgba(0.09, 0.13, 0.24, panelOpacity) : Qt.rgba(1, 1, 1, panelOpacity)

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // 进度条
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 4
                    color: progressBg

                    Rectangle {
                        id: progressFillBar
                        height: parent.height
                        width: player.duration > 0 ? (player.position / player.duration) * parent.width : 0
                        color: progressFill
                        radius: 2
                        Behavior on width { NumberAnimation { duration: 200 } }
                    }

                    MouseArea {
                        id: seekMouseArea
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        property bool seeking: false

                        onPressed: {
                            if (player.duration > 0) {
                                seeking = true
                                var pos = mouseX / width * player.duration
                                player.seek(pos)
                            }
                        }
                        onPositionChanged: {
                            if (seeking && player.duration > 0) {
                                var pos = Math.max(0, Math.min(mouseX / width * player.duration, player.duration))
                                player.seek(pos)
                            }
                        }
                        onReleased: {
                            seeking = false
                        }
                    }
                }

                // 控制按钮
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    spacing: 8

                    // 设置按钮
                    Rectangle {
                        id: settingsBtn
                        width: 45
                        height: 45
                        radius: 22
                        color: hideControlBackgrounds ? "transparent" : (settingsBtnMouse.containsPress ? accentHover : accent)
                        Behavior on color { ColorAnimation { duration: 100 } }

                        Text {
                            anchors.centerIn: parent
                            text: "⚙"
                            color: hideControlBackgrounds ? (darkMode ? "#eaeaea" : "#1a1a2e") : "#fff"
                            font.pixelSize: 18
                        }

                        MouseArea {
                            id: settingsBtnMouse
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            hoverEnabled: true
                            onClicked: window.toggleSettings()
                        }

                        ToolTip {
                            visible: settingsBtnMouse.containsMouse
                            text: "设置"
                            delay: 500
                        }
                    }

                    // 下载按钮
                    Rectangle {
                        id: downloadBtn
                        width: 45
                        height: 45
                        radius: 22
                        color: hideControlBackgrounds ? "transparent" : (downloadBtnMouse.containsPress ? accentHover : accent)
                        Behavior on color { ColorAnimation { duration: 100 } }

                        Image {
                            id: downloadIconImg
                            anchors.centerIn: parent
                            width: 20
                            height: 20
                            source: "icons/DownLoad.svg"
                            sourceSize.width: 20
                            sourceSize.height: 20
                            visible: false
                        }

                        ColorOverlay {
                            anchors.fill: downloadIconImg
                            source: downloadIconImg
                            color: window.darkMode ? "#ffffff" : "#000000"
                        }

                        MouseArea {
                            id: downloadBtnMouse
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            hoverEnabled: true
                            onClicked: window.toggleDownload()
                        }

                        ToolTip {
                            visible: downloadBtnMouse.containsMouse
                            text: "在线下载歌词/封面"
                            delay: 500
                        }
                    }

                    // 左侧：当前播放信息
                    RowLayout {
                        Layout.preferredWidth: 200
                        spacing: 8
                        visible: player.state !== "stopped"

                        Rectangle {
                            Layout.preferredWidth: 36
                            Layout.preferredHeight: 36
                            radius: 6
                            color: bgCard
                            visible: coverImage.status === Image.Ready

                            Image {
                                anchors.fill: parent
                                fillMode: Image.PreserveAspectCrop
                                source: player.currentSongImage ? "file://" + player.currentSongImage + "?t=" + window.coverStamp : ""
                                asynchronous: false
                                smooth: true
                            }
                        }

                        Text {
                            text: player.currentSongName || ""
                            color: textPrimary
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }

                    // 下一曲 (居中)
                    Text {
                        text: {
                            if (player.songCount <= 0 || player.currentIndex < 0) return ""
                            var nextIdx = (player.currentIndex + 1) % player.songCount
                            return "下一曲: " + player.songName(nextIdx)
                        }
                        color: textSecondary
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        visible: player.state !== "stopped"
                    }

                    Item { Layout.fillWidth: true; visible: player.state === "stopped" }

                    // 折叠/展开播放列表按钮
                    Rectangle {
                        id: togglePlaylistBtn
                        width: 45
                        height: 45
                        radius: 22
                        color: hideControlBackgrounds ? "transparent" : (toggleBtnMouse.containsPress ? accentHover : accent)
                        Behavior on color { ColorAnimation { duration: 100 } }

                        Text {
                            anchors.centerIn: parent
                            text: "☰"
                            color: hideControlBackgrounds ? (darkMode ? "#eaeaea" : "#1a1a2e") : "#fff"
                            font.pixelSize: 18
                        }

                        MouseArea {
                            id: toggleBtnMouse
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            hoverEnabled: true
                            onClicked: { player.playlistVisible = !player.playlistVisible }
                        }

                        ToolTip {
                            visible: toggleBtnMouse.containsMouse
                            text: playlistVisible ? "收起播放列表" : "展开播放列表"
                            delay: 500
                        }
                    }

                    // 控制按钮组
                    RowLayout {
                        spacing: 4

                        // 上一首
                        Rectangle {
                            id: prevBtn
                            width: 50
                            height: 50
                            radius: 25
                            color: hideControlBackgrounds ? "transparent" : (prevBtnMouse.containsPress ? accentHover : accent)
                            Behavior on color { ColorAnimation { duration: 100 } }

                            Image {
                                id: prevIconImg
                                anchors.centerIn: parent
                                width: 24
                                height: 24
                                source: "icons/left.svg"
                                sourceSize.width: 24
                                sourceSize.height: 24
                                visible: false
                            }

                            ColorOverlay {
                                anchors.fill: prevIconImg
                                source: prevIconImg
                                color: window.darkMode ? "#ffffff" : "#000000"
                            }

                            MouseArea {
                                id: prevBtnMouse
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: player.previous()
                            }
                        }

                        // 播放/暂停
                        Rectangle {
                            id: playBtn
                            width: 52
                            height: 52
                            radius: 26
                            color: hideControlBackgrounds ? "transparent" : (playBtnMouse.containsPress ? accentHover : accent)
                            Behavior on color { ColorAnimation { duration: 100 } }

                            Text {
                                anchors.centerIn: parent
                                text: player.state === "playing" ? "⏸" : "▶"
                                color: hideControlBackgrounds ? (darkMode ? "#eaeaea" : "#1a1a2e") : "#fff"
                                font.pixelSize: 20
                            }

                            MouseArea {
                                id: playBtnMouse
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (playlistVisible && player.state !== "playing") {
                                        window.switchToLyric()
                                    }
                                    player.playPause()
                                }
                            }
                        }

                        // 下一首
                        Rectangle {
                            id: nextBtn
                            width: 50
                            height: 50
                            radius: 25
                            color: hideControlBackgrounds ? "transparent" : (nextBtnMouse.containsPress ? accentHover : accent)
                            Behavior on color { ColorAnimation { duration: 100 } }

                            Image {
                                id: nextIconImg
                                anchors.centerIn: parent
                                width: 24
                                height: 24
                                source: "icons/Right.svg"
                                sourceSize.width: 24
                                sourceSize.height: 24
                                visible: false
                            }

                            ColorOverlay {
                                anchors.fill: nextIconImg
                                source: nextIconImg
                                color: window.darkMode ? "#ffffff" : "#000000"
                            }

                            MouseArea {
                                id: nextBtnMouse
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: player.next()
                            }
                        }
                    }

                    // 右侧：主题切换 + 音量
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignRight
                        spacing: 8

                        // 主题切换按钮
                        Rectangle {
                            id: themeBtn
                            width: 36
                            height: 36
                            radius: 18
                            color: hideControlBackgrounds ? "transparent" : (themeBtnMouse.containsPress ? accentHover : accent)
                            Behavior on color { ColorAnimation { duration: 100 } }

                            Image {
                                id: themeIconImg
                                anchors.centerIn: parent
                                width: 20
                                height: 20
                                source: window.darkMode ? "icons/Moon.svg" : "icons/SUN.svg"
                                sourceSize.width: 20
                                sourceSize.height: 20
                                visible: false
                            }

                            ColorOverlay {
                                anchors.fill: themeIconImg
                                source: themeIconImg
                                color: window.darkMode ? "#ffffff" : "#000000"
                            }

                            MouseArea {
                                id: themeBtnMouse
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: window.toggleTheme()
                            }

                            ToolTip {
                                visible: themeBtnMouse.containsMouse
                                text: window.darkMode ? "切换亮色模式" : "切换深色模式"
                                delay: 500
                            }
                        }

                        // 音量滑块
                        RowLayout {
                            spacing: 6
                            Layout.alignment: Qt.AlignRight

                            Image {
                                id: volumeIconImg
                                source: player.volume === 0 ? "icons/volume_off.svg" : (player.volume < 75 ? "icons/volume-low.svg" : "icons/volume_high.svg")
                                sourceSize.width: 18
                                sourceSize.height: 18
                                Layout.alignment: Qt.AlignVCenter
                                visible: false
                            }

                            ColorOverlay {
                                width: volumeIconImg.width
                                height: volumeIconImg.height
                                Layout.preferredWidth: volumeIconImg.width
                                Layout.preferredHeight: volumeIconImg.height
                                source: volumeIconImg
                                color: hideControlBackgrounds ? (darkMode ? "#eaeaea" : "#1a1a2e") : "#ffffff"
                            }

                            Slider {
                                id: volumeSlider
                                from: 0
                                to: 100
                                value: player.volume
                                stepSize: 1
                                implicitWidth: 100
                                implicitHeight: 22

                                background: Rectangle {
                                    x: volumeSlider.leftPadding
                                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: volumeSlider.availableWidth
                                    height: 4
                                    radius: 2
                                    color: progressBg

                                    Rectangle {
                                        width: volumeSlider.visualPosition * parent.width
                                        height: parent.height
                                        radius: 2
                                        color: accent
                                    }
                                }

                                handle: Rectangle {
                                    x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                                    y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                                    width: 14
                                    height: 14
                                    radius: 7
                                    color: volumeSlider.pressed ? accentHover : (hideControlBackgrounds ? accent : "#ffffff")
                                    border.color: accent
                                    border.width: 2
                                    Behavior on color { ColorAnimation { duration: 100 } }
                                }

                                onMoved: {
                                    // 拖动过程中做防抖：滑块视觉立即跟手，
                                    // 但真正下发给 player.volume（可能触发
                                    // PulseAudio 调用或 ffplay 重启）延迟到
                                    // 停止拖动一小段时间后再执行，避免每个
                                    // 像素都触发一次后端调用导致卡顿。
                                    volumeApplyTimer.pendingValue = value
                                    volumeApplyTimer.restart()
                                }
                                onPressedChanged: {
                                    if (!pressed) {
                                        // 松手时立即应用，不再等待防抖计时器
                                        volumeApplyTimer.stop()
                                        player.volume = value
                                    }
                                }

                                Timer {
                                    id: volumeApplyTimer
                                    interval: 60
                                    repeat: false
                                    property real pendingValue: volumeSlider.value
                                    onTriggered: player.volume = pendingValue
                                }
                            }
                        }

                    }
                }
            }

            
        }
    }

    // ========== 设置面板（左侧滑出，占窗口 1/4 宽度） ==========
    Item {
        id: settingsOverlay
        anchors.fill: parent
        visible: false
        z: 100

        // 半透明遮罩（点击关闭）
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.35)

            MouseArea {
                anchors.fill: parent
                onClicked: settingsVisible = false
            }
        }

        // 设置面板
        Rectangle {
            id: settingsPanel
            width: Math.max(parent.width / 4, 300)
            height: parent.height
            x: settingsVisible ? 0 : -width
            color: Qt.rgba(bgDark.r, bgDark.g, bgDark.b, 0.97)

            Behavior on x {
                NumberAnimation { duration: 300; easing.type: Easing.OutCubic }
            }

            Flickable {
                id: settingsFlickable
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.topMargin: 20
                anchors.bottomMargin: 20
                anchors.rightMargin: 6
                contentWidth: width
                contentHeight: settingsColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick
                interactive: true

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 6
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: accent
                        opacity: 0.6
                    }
                    background: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: "transparent"
                    }
                }

                ColumnLayout {
                    id: settingsColumn
                    width: parent.width - 26
                    spacing: 12

                // 标题
                Text {
                    text: "设置"
                    color: textPrimary
                    font.pixelSize: 20
                    font.bold: true
                }

                // ===== 音乐文件夹 =====
                Text {
                    text: "音乐文件夹"
                    color: textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }

                TextField {
                    id: musicDirInput
                    Layout.fillWidth: true
                    text: player.musicDir
                    placeholderText: "输入音乐文件夹路径..."
                    color: textPrimary
                    font.pixelSize: 12
                    background: Rectangle {
                                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#1a1a3e" : "#e8e8ec")
                                            radius: 6
                                            border.color: darkMode ? "#334466" : "#ccccd0"
                                        }
                                    }
                    
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Button {
                                            text: "浏览"
                        font.pixelSize: 12
                        onClicked: folderDialog.open()
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 6
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Button {
                        text: "应用"
                        font.pixelSize: 12
                        onClicked: {
                            player.setMusicDir(musicDirInput.text)
                            saveSetting("musicDir", musicDirInput.text)
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: accent
                            radius: 6
                        }
                        contentItem: Text {
                            text: parent.text
                            color: "#fff"
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // ===== 分割线 =====
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: textMuted
                    opacity: 0.3
                }

                // ===== 颜色自定义 =====
                Text {
                    text: "颜色自定义"
                    color: textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }

                // 主题色
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "主题色"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: accent
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customAccent", accent)
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // 深色背景
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "深色背景"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customDarkBg !== "" ? customDarkBg : "#1a1a2e"
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customDarkBg", customDarkBg !== "" ? customDarkBg : "#1a1a2e")
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // 亮色背景
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "亮色背景"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customLightBg !== "" ? customLightBg : "#f0f0f2"
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customLightBg", customLightBg !== "" ? customLightBg : "#f0f0f2")
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // 按钮/输入框底色
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "控件底色"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customBtnBg", customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc"))
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // ===== 分割线 =====
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: textMuted
                    opacity: 0.3
                }

                // ===== 歌词颜色 =====
                Text {
                    text: "歌词颜色"
                    color: textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "当前行"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customLyricColor !== "" ? customLyricColor : accent
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customLyricColor", customLyricColor !== "" ? customLyricColor : accent)
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "已播行"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customLyricPlayedColor !== "" ? customLyricPlayedColor : textMuted
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customLyricPlayedColor", customLyricPlayedColor !== "" ? customLyricPlayedColor : textMuted)
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "未播行"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: customLyricUnplayedColor !== "" ? customLyricUnplayedColor : textSecondary
                        border.color: textMuted
                        border.width: 1
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: {
                            openColorDialog("customLyricUnplayedColor", customLyricUnplayedColor !== "" ? customLyricUnplayedColor : textSecondary)
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // 隐藏控件底色
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "隐藏控件底色"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 80
                    }

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        width: 40; height: 22; radius: 11
                        color: hideControlBackgrounds ? accent : (darkMode ? "#3a3a5e" : "#c0c0c8")
                        Behavior on color { ColorAnimation { duration: 150 } }

                        Rectangle {
                            x: hideControlBackgrounds ? 20 : 2
                            y: 2
                            width: 18; height: 18; radius: 9
                            color: "#ffffff"
                            Behavior on x { NumberAnimation { duration: 150 } }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: hideControlBackgrounds = !hideControlBackgrounds
                        }
                    }
                }

                // ===== 分割线 =====
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: textMuted
                    opacity: 0.3
                }

                // ===== 背景效果 =====
                Text {
                    text: "背景效果"
                    color: textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }

                // 模糊程度
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "模糊程度"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Slider {
                        id: blurSlider
                        from: 0
                        to: 140
                        stepSize: 1
                        value: blurRadius
                        Layout.fillWidth: true
                        onValueChanged: blurRadius = value
                        background: Rectangle {
                            x: blurSlider.leftPadding
                            y: blurSlider.topPadding + blurSlider.availableHeight / 2 - height / 2
                            implicitWidth: 200
                            implicitHeight: 4
                            width: blurSlider.availableWidth
                            height: implicitHeight
                            radius: 2
                            color: progressBg
                            Rectangle {
                                width: blurSlider.visualPosition * parent.width
                                height: parent.height
                                color: accent
                                radius: 2
                            }
                        }
                        handle: Rectangle {
                            x: blurSlider.leftPadding + blurSlider.visualPosition * (blurSlider.availableWidth - width)
                            y: blurSlider.topPadding + blurSlider.availableHeight / 2 - height / 2
                            implicitWidth: 14
                            implicitHeight: 14
                            radius: 7
                            color: accent
                        }
                    }

                    Text {
                        text: Math.round(blurRadius)
                        color: textSecondary
                        font.pixelSize: 12
                        Layout.preferredWidth: 30
                        horizontalAlignment: Text.AlignRight
                    }
                }

                // 面板透明度
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "面板透明度"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Slider {
                        id: opacitySlider
                        from: 0
                        to: 1
                        stepSize: 0.01
                        value: panelOpacity
                        Layout.fillWidth: true
                        onValueChanged: panelOpacity = value
                        background: Rectangle {
                            x: opacitySlider.leftPadding
                            y: opacitySlider.topPadding + opacitySlider.availableHeight / 2 - height / 2
                            implicitWidth: 200
                            implicitHeight: 4
                            width: opacitySlider.availableWidth
                            height: implicitHeight
                            radius: 2
                            color: progressBg
                            Rectangle {
                                width: opacitySlider.visualPosition * parent.width
                                height: parent.height
                                color: accent
                                radius: 2
                            }
                        }
                        handle: Rectangle {
                            x: opacitySlider.leftPadding + opacitySlider.visualPosition * (opacitySlider.availableWidth - width)
                            y: opacitySlider.topPadding + opacitySlider.availableHeight / 2 - height / 2
                            implicitWidth: 14
                            implicitHeight: 14
                            radius: 7
                            color: accent
                        }
                    }

                    Text {
                        text: Math.round(panelOpacity * 100) + "%"
                        color: textSecondary
                        font.pixelSize: 12
                        Layout.preferredWidth: 36
                        horizontalAlignment: Text.AlignRight
                    }
                }

                // 恢复默认
                Button {
                    Layout.alignment: Qt.AlignHCenter
                    text: "恢复默认颜色"
                    font.pixelSize: 12
                    onClicked: {
                        customAccent = ""
                        customDarkBg = ""
                        customLightBg = ""
                        customLyricColor = ""
                        customLyricPlayedColor = ""
                        customLyricUnplayedColor = ""
                        customBtnBg = ""
                        
                    }
                    background: Rectangle {
                        color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                        radius: 6
                    }
                    contentItem: Text {
                        text: parent.text
                        color: textSecondary
                        font: parent.font
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                // ===== 分割线 =====
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: textMuted
                    opacity: 0.3
                }

                // ===== 显示设置 =====
                Text {
                    text: "显示设置"
                    color: textPrimary
                    font.pixelSize: 14
                    font.bold: true
                }

                // 行间距
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "行间距"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    Slider {
                        id: rowSpacingSlider
                        from: 36
                        to: 72
                        stepSize: 2
                        value: rowSpacing
                        Layout.fillWidth: true
                        onValueChanged: rowSpacing = value
                        background: Rectangle {
                            x: rowSpacingSlider.leftPadding
                            y: rowSpacingSlider.topPadding + rowSpacingSlider.availableHeight / 2 - height / 2
                            implicitWidth: 200
                            implicitHeight: 4
                            width: rowSpacingSlider.availableWidth
                            height: implicitHeight
                            radius: 2
                            color: progressBg
                            Rectangle {
                                width: rowSpacingSlider.visualPosition * parent.width
                                height: parent.height
                                color: accent
                                radius: 2
                            }
                        }
                        handle: Rectangle {
                            x: rowSpacingSlider.leftPadding + rowSpacingSlider.visualPosition * (rowSpacingSlider.availableWidth - width)
                            y: rowSpacingSlider.topPadding + rowSpacingSlider.availableHeight / 2 - height / 2
                            implicitWidth: 14
                            implicitHeight: 14
                            radius: 7
                            color: accent
                        }
                    }

                    Text {
                        text: Math.round(rowSpacing) + "px"
                        color: textSecondary
                        font.pixelSize: 12
                        Layout.preferredWidth: 36
                        horizontalAlignment: Text.AlignRight
                    }
                }

                // ===== 全局字体 =====
                // 之前 window.font.family 写的是一串逗号分隔的候选列表
                // （"Noto Sans CJK SC, Noto Sans CJK JP, Noto Sans, sans-serif"），
                // 交给 Qt 的字体后端自己按字符集去匹配、回退——这个自动匹配在遇到
                // 日文等复杂文字时可能选不准（比如误用了不完整覆盖日文假名/汉字
                // 变体的字体），表现为乱码或方框，而且匹配过程本身还会触发前面
                // 提到的 "OpenType support missing" 警告刷屏、甚至轻微卡顿。
                //
                // customFontFamily 这个设置项、持久化读写（saveSetting/loadSettings）
                // 和实际生效逻辑（歌词 Text 的 font.family 绑定）在代码里其实早就
                // 存在了，只是设置面板里一直没有对应的输入框，用户没有入口去真正
                // 填一个精确的字体名——这里补上这个入口：直接让用户输入一个具体、
                // 明确的字体族名字（比如系统里安装的 "Noto Sans CJK JP"），一旦
                // 填了非空值，歌词文字会直接用这个字体，完全跳过前面那串"自动
                // 搜索候选"的逻辑，不再依赖 Qt 猜哪个字体支持当前文字。
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "全局字体"
                        color: textPrimary
                        font.pixelSize: 12
                        Layout.preferredWidth: 60
                    }

                    TextField {
                        id: customFontInput
                        Layout.fillWidth: true
                        // 注意：text 初始值绑定到 customFontFamily，但这只在"用户还没有
                        // 手动编辑过"这个输入框时有效——QML 里只要用户在 TextField 里
                        // 打字，这个绑定就会被断开（这是 Text/TextField 的标准行为，
                        // 输入框需要能被自由编辑，不能被外部值不断打回原样）。断开之后，
                        // 如果 customFontFamily 又在别的地方被改动（比如以后新增了别的
                        // 重置入口），这个输入框不会自动跟着刷新——所以下面"清空"按钮
                        // 才需要同时手动设置 customFontInput.text 和 customFontFamily
                        // 两者，而不能只改 customFontFamily 指望输入框自动同步。以后如果
                        // 再加别的会修改 customFontFamily 的入口，也要记得同样处理。
                        text: customFontFamily
                        placeholderText: "留空则自动匹配，如需解决日文乱码可填 Noto Sans CJK JP"
                        color: textPrimary
                        font.pixelSize: 12
                        // 用回车/失焦触发应用，而不是每敲一个字符就立刻生效——
                        // 逐字符生效会导致字体解析在打字过程中反复触发，一来
                        // 没有必要（用户还没打完字），二来容易造成输入过程卡顿。
                        //
                        // 注意：按回车确认后手动 focus = false 会紧接着触发
                        // onActiveFocusChanged，如果两个 handler 都无条件赋值，
                        // customFontFamily 会被设置两次、onCustomFontFamilyChanged
                        // 也会跟着多触发一次 saveSetting（多一次不必要的磁盘写入，
                        // 虽然值相同不会出错，但没必要）。这里加一个"值真的变了
                        // 才赋值"的判断，两处 handler 共享，避免这个重复。
                        function applyIfChanged() {
                            if (customFontFamily !== text) customFontFamily = text
                        }
                        onAccepted: {
                            applyIfChanged()
                            focus = false
                        }
                        onActiveFocusChanged: {
                            if (!activeFocus) applyIfChanged()
                        }
                        background: Rectangle {
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#1a1a3e" : "#e8e8ec")
                            radius: 6
                            border.color: darkMode ? "#334466" : "#ccccd0"
                        }
                    }

                    Button {
                        text: "选择"
                        font.pixelSize: 11
                        onClicked: fontDialog.open()
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 4
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Button {
                        text: "清空"
                        font.pixelSize: 12
                        onClicked: {
                            customFontInput.text = ""
                            customFontFamily = ""
                        }
                        background: Rectangle {
                            implicitWidth: 52
                            implicitHeight: 28
                            color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                            radius: 6
                        }
                        contentItem: Text {
                            text: parent.text
                            color: textPrimary
                            font: parent.font
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // ===== 分割线 =====
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: textMuted
                    opacity: 0.3
                    Layout.topMargin: 8
                    Layout.bottomMargin: 4
                }

                // ===== 自动切换到歌词界面 =====
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "自动切换到歌词"
                        color: textPrimary
                        font.pixelSize: 12
                    }

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        width: 40; height: 22; radius: 11
                        color: autoSwitchToLyric ? accent : (darkMode ? "#3a3a5e" : "#c0c0c8")
                        Behavior on color { ColorAnimation { duration: 150 } }

                        Rectangle {
                            x: autoSwitchToLyric ? 20 : 2
                            y: 2
                            width: 18; height: 18; radius: 9
                            color: "#ffffff"
                            Behavior on x { NumberAnimation { duration: 150 } }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: autoSwitchToLyric = !autoSwitchToLyric
                        }
                    }
                }

                // ===== 关闭行为 =====
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "点击 × 时隐藏到托盘"
                        color: textPrimary
                        font.pixelSize: 12
                    }

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        width: 40; height: 22; radius: 11
                        color: closeToTray ? accent : (darkMode ? "#3a3a5e" : "#c0c0c8")
                        Behavior on color { ColorAnimation { duration: 150 } }

                        Rectangle {
                            x: closeToTray ? 20 : 2
                            y: 2
                            width: 18; height: 18; radius: 9
                            color: "#ffffff"
                            Behavior on x { NumberAnimation { duration: 150 } }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: closeToTray = !closeToTray
                        }
                    }
                }

            }
        }
    }
    }

    // ========== 下载面板（右侧滑出） ==========
    Item {
        id: downloadOverlay
        anchors.fill: parent
        visible: false
        z: 100

        // 半透明遮罩（点击关闭）
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.35)

            MouseArea {
                anchors.fill: parent
                onClicked: downloadVisible = false
            }
        }

        // 下载面板
        Rectangle {
            id: downloadPanel
            width: parent.width / 3
            height: parent.height
            x: downloadVisible ? parent.width - width : parent.width
            color: Qt.rgba(bgDark.r, bgDark.g, bgDark.b, 0.97)

            Behavior on x {
                NumberAnimation { duration: 300; easing.type: Easing.OutCubic }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                // 标题
                Text {
                    text: "在线下载歌词/封面"
                    color: textPrimary
                    font.pixelSize: 16
                    font.bold: true
                }

                // 当前歌曲
                Text {
                    text: "当前歌曲: " + (player.currentSongName || "无")
                    color: textSecondary
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                // 搜索框
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Rectangle {
                        Layout.fillWidth: true
                        height: 36
                        radius: 6
                        color: darkMode ? "#2a2a4e" : "#e0e0e4"
                        border.color: darkMode ? "#3a3a5e" : "#c0c0c8"
                        border.width: 1

                        TextInput {
                            id: searchInput
                            anchors.fill: parent
                            anchors.margins: 8
                            color: textPrimary
                            font.pixelSize: 13
                            clip: true
                            text: player.currentSongName || ""
                        }
                    }

                    Rectangle {
                        width: 60
                        height: 36
                        radius: 6
                        color: accent
                        Behavior on color { ColorAnimation { duration: 100 } }

                        Text {
                            anchors.centerIn: parent
                            text: "搜索"
                            color: "#fff"
                            font.pixelSize: 12
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: player.searchNetEase(searchInput.text)
                        }
                    }
                }

                // 状态提示
                Text {
                    id: downloadStatusText
                    text: player.downloadStatus || ""
                    color: textSecondary
                    font.pixelSize: 12
                    visible: text !== ""
                    Layout.fillWidth: true
                }

                // 搜索结果列表
                ListView {
                    id: searchResultList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: player.searchResultModel

                    delegate: Rectangle {
                        width: ListView.view.width
                        height: 64
                        radius: 8
                        color: darkMode ? "#1a2a4e" : "#e8e8ec"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: modelData.name || ""
                                    color: textPrimary
                                    font.pixelSize: 13
                                    font.bold: true
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                Text {
                                    text: (modelData.artist || "") + (modelData.album ? " · " + modelData.album : "")
                                    color: textSecondary
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                            }

                            // 下载歌词
                            Rectangle {
                                width: 52
                                height: 28
                                radius: 6
                                color: accent
                                Behavior on color { ColorAnimation { duration: 100 } }

                                Text {
                                    anchors.centerIn: parent
                                    text: "歌词"
                                    color: "#fff"
                                    font.pixelSize: 11
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: player.downloadLyric(modelData.id, player.songPath(player.currentIndex))
                                }
                            }

                            // 下载封面
                            Rectangle {
                                width: 52
                                height: 28
                                radius: 6
                                color: accent
                                Behavior on color { ColorAnimation { duration: 100 } }

                                Text {
                                    anchors.centerIn: parent
                                    text: "封面"
                                    color: "#fff"
                                    font.pixelSize: 11
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: player.downloadCover(modelData.picUrl, player.songPath(player.currentIndex), modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ===== 颜色选择对话框（静态共享实例，用 colorDialogTarget 记录本次设置目标） =====
    property string colorDialogTarget: ""

    function openColorDialog(target, currentColor) {
        colorDialogTarget = target
        colorDialog.selectedColor = currentColor
        colorDialog.open()
    }

    ColorDialog {
        id: colorDialog
        onAccepted: {
            switch (colorDialogTarget) {
                case "customAccent": customAccent = selectedColor; break
                case "customDarkBg": customDarkBg = selectedColor; break
                case "customLightBg": customLightBg = selectedColor; break
                case "customLyricColor": customLyricColor = selectedColor; break
                case "customLyricPlayedColor": customLyricPlayedColor = selectedColor; break
                case "customLyricUnplayedColor": customLyricUnplayedColor = selectedColor; break
                case "customBtnBg": customBtnBg = selectedColor; break
                
            }
        }
    }

    // ===== 字体选择对话框（自定义列表，不依赖原生 Dialog） =====
    Dialog {
        id: fontDialog
        title: "选择全局字体"
        modal: true
        width: 380
        height: 480
        padding: 0

        property var allFonts: Qt.fontFamilies()
        property string _selectedFont: ""

        onAccepted: {
            if (_selectedFont) {
                customFontFamily = _selectedFont
                customFontInput.text = _selectedFont
            }
        }

        background: Rectangle {
            color: Qt.rgba(bgDark.r, bgDark.g, bgDark.b, 1)
            radius: 8
        }

        header: Rectangle {
            implicitHeight: 44
            color: "transparent"
            Text {
                anchors.centerIn: parent
                text: "选择全局字体"
                color: textPrimary
                font.pixelSize: 15
                font.bold: true
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "搜索字体..."
                color: textPrimary
                font.pixelSize: 12
                background: Rectangle {
                    color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#1a1a3e" : "#e8e8ec")
                    radius: 6
                    border.color: darkMode ? "#334466" : "#ccccd0"
                }
            }

            ListView {
                id: fontListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                property var _filtered: {
                    var raw = fontDialog.allFonts
                    var q = searchField.text.toLowerCase()
                    if (!q) return raw
                    var out = []
                    for (var i = 0; i < raw.length; i++) {
                        if (raw[i].toLowerCase().indexOf(q) !== -1)
                            out.push(raw[i])
                    }
                    return out
                }

                model: _filtered
                delegate: Rectangle {
                    width: parent.width
                    height: 36
                    radius: 4
                    color: fontDialog._selectedFont === modelData
                        ? accent
                        : (mouseArea.containsMouse ? Qt.rgba(1,1,1,0.08) : "transparent")

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        text: modelData
                        color: fontDialog._selectedFont === modelData ? "#fff" : textPrimary
                        font.family: modelData
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    MouseArea {
                        id: mouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: fontDialog._selectedFont = modelData
                    }
                }

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 6
                    contentItem: Rectangle {
                        implicitWidth: 6
                        radius: 3
                        color: accent
                        opacity: 0.6
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    font.pixelSize: 12
                    onClicked: fontDialog.reject()
                    background: Rectangle {
                        implicitWidth: 60
                        implicitHeight: 28
                        color: customBtnBg !== "" ? customBtnBg : (darkMode ? "#2a2a4e" : "#d8d8dc")
                        radius: 6
                    }
                    contentItem: Text {
                        text: parent.text
                        color: textSecondary
                        font: parent.font
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    text: "确定"
                    font.pixelSize: 12
                    enabled: fontDialog._selectedFont !== ""
                    onClicked: fontDialog.accept()
                    background: Rectangle {
                        implicitWidth: 60
                        implicitHeight: 28
                        color: enabled ? accent : (darkMode ? "#3a3a5e" : "#c0c0c8")
                        radius: 6
                    }
                    contentItem: Text {
                        text: parent.text
                        color: enabled ? "#fff" : textMuted
                        font: parent.font
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }

    // ===== 文件夹选择对话框 =====
    FolderDialog {
        id: folderDialog
        onAccepted: musicDirInput.text = selectedFolder.toString().replace("file://", "")
    }

    

    // ========== 设置面板显示/隐藏控制 ==========
    Timer {
        id: settingsCloseTimer
        interval: 300
        onTriggered: settingsOverlay.visible = false
    }

    // ========== 下载面板显示/隐藏控制 ==========
    Timer {
        id: downloadCloseTimer
        interval: 300
        onTriggered: downloadOverlay.visible = false
    }

    // ========== 全局鼠标滚轮音量调节 ==========
    // 挂在窗口根级、铺满整个窗口，且放在最后声明，保证 z 顺序在最上层，
    // 才能在鼠标位于窗口任意位置时都能捕获滚轮事件。
    // 使用 WheelHandler 而不是 MouseArea：WheelHandler 只处理滚轮事件，
    // 不会拦截/吞掉鼠标点击、拖动等事件，也完全不需要窗口或子控件获得焦点，
    // 不会影响播放列表、按钮等其他控件原有的点击/拖拽交互。
    WheelHandler {
        target: null  // 不需要对某个 Item 做视觉操作，只是监听事件
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

        onWheel: (event) => {
            // 设置面板或下载面板打开时，不拦截滚轮事件，让子级控件
            //（如 Flickable）正常滚动，避免滚动设置项时误调音量。
            if (settingsVisible || downloadVisible) {
                event.accepted = false
                return
            }

            // 每次滚动一格通常对应 120（或其整数倍/分数），换算成音量步进；
            // 一格滚动 = 音量变化 5，可根据手感调整这个系数。
            var steps = event.angleDelta.y / 120

            // 关键点：必须在 wheelVolumeTimer.pendingValue（本次防抖窗口内
            // 已经累积的目标音量）基础上累加，而不能用 player.volume 累加。
            // 因为防抖计时器触发前 player.volume 还没被真正更新，如果这里
            // 用 player.volume 做基准，快速滚动时连续多个滚轮事件会重复读到
            // 同一个"旧"的 player.volume，算出同一个目标值，导致中间的多次
            // 滚动步数互相覆盖、白白丢失——这正是之前"快速滚动时几乎读不到
            // 输入"的原因（并不是阻塞导致的，是防抖窗口内的增量被覆盖了）。
            // 用 pendingValue 做基准就能保证每一格滚动都会被正确累加上去。
            var base = wheelVolumeTimer.running ? wheelVolumeTimer.pendingValue : player.volume
            var newVolume = Math.max(0, Math.min(100, Math.round(base + steps * 5)))

            if (newVolume !== base) {
                // 触控板等设备可能在很短时间内连续发出大量滚轮事件，
                // 这里用一个很短的独立防抖计时器合并这些事件，只在
                // 停止滚动的瞬间才真正下发给后端（PulseAudio/ffplay），
                // 避免连续高频调用导致卡顿；同时又不会像拖动滑块那样
                // 需要等待较长时间，滚动的手感依然是跟手的。
                wheelVolumeTimer.pendingValue = newVolume
                wheelVolumeTimer.restart()
            }
        }
    }

    Timer {
        id: wheelVolumeTimer
        interval: 40
        repeat: false
        property real pendingValue: player.volume
        onTriggered: player.volume = pendingValue
    }

    // ========== 键盘快捷键 ==========
    Shortcut {
        sequence: "Space"
        onActivated: player.playPause()
    }
    Shortcut {
        sequence: "Right"
        onActivated: player.seek(Math.min(player.position + 5, player.duration))
    }
    Shortcut {
        sequence: "Left"
        onActivated: player.seek(Math.max(player.position - 5, 0))
    }

    onSettingsVisibleChanged: {
        if (settingsVisible) {
            settingsOverlay.visible = true
        } else {
            settingsCloseTimer.start()
        }
    }

    onDownloadVisibleChanged: {
        if (downloadVisible) {
            downloadOverlay.visible = true
        } else {
            downloadCloseTimer.start()
        }
    }
}
