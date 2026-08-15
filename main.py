#!/usr/bin/env python3
"""MusicPlayer2 - PySide6 + QML 音频播放器"""

import os
import signal
import subprocess
import tempfile
from pathlib import Path

import re
import json
import time
import hashlib
import threading
from api import search_songs, save_lyric_file, save_cover_file

from PySide6.QtCore import (
    QObject, Signal, Slot, Property, QTimer, QProcess
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtQml import QQmlApplicationEngine


MUSIC_DIR = Path("~/Music").expanduser()
SUPPORTED_AUDIO = (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".wma", ".ape")
SUPPORTED_IMAGE = (".jpg", ".jpeg", ".png", ".bmp")

# AppImage 打包时自带的 ffmpeg/ffplay/ffprobe 位于 <app>/bin/，
# 把它们放到 PATH 最前面，保证优先使用与程序一起打包的版本；
# 目录不存在（源码运行）时不做任何改动，回退到系统 PATH。
_BUNDLED_BIN = Path(__file__).parent / "bin"
if _BUNDLED_BIN.is_dir():
    os.environ["PATH"] = str(_BUNDLED_BIN) + os.pathsep + os.environ.get("PATH", "")


def _to_path(path_str):
    """Normalize a path string to a Path object with cross-platform support.
    Converts Windows backslashes to forward slashes so paths from any OS
    are parsed correctly regardless of the host platform."""
    if isinstance(path_str, Path):
        return path_str
    return Path(str(path_str).replace("\\", "/"))


def find_matching_image(song_path, dir_images=None):
    """Find an image file that matches the song filename.

    dir_images: 可选，该目录下已列好的图片文件列表（由 scan_music 缓存传入，
    避免同一目录下每首歌都重复 iterdir 一遍，加快扫描速度）。
    """
    song_path = _to_path(song_path)
    song_dir = song_path.parent
    song_name = song_path.name
    song_base = song_path.stem

    candidates = []

    # 1. Exact match: song_base.jpg/png
    for ext in SUPPORTED_IMAGE:
        candidate = song_dir / (song_base + ext)
        if candidate.is_file():
            candidates.append(candidate)

    # 2. Audio_ext.jpg match: song_base.mp3.jpg / song_base.wav.jpg
    for ext in SUPPORTED_IMAGE:
        candidate = song_dir / (song_name + ext)
        if candidate.is_file():
            candidates.append(candidate)

    # 3. Partial match: image base name is a substring of song base name or vice versa
    if dir_images is None:
        try:
            dir_images = [
                f for f in song_dir.iterdir()
                if any(f.name.lower().endswith(ext) for ext in SUPPORTED_IMAGE)
            ]
        except (FileNotFoundError, OSError):
            dir_images = []

    for img_path in dir_images:
        if img_path in candidates:
            continue
        img_base = img_path.stem
        # Remove trailing .mp3/.wav from image base if present
        for aext in SUPPORTED_AUDIO:
            if img_base.lower().endswith(aext):
                img_base = img_base[:-len(aext)]
                break
        # Check if one contains the other
        if img_base and (img_base in song_base or song_base in img_base):
            candidates.append(img_path)

    return str(candidates[0]) if candidates else ""


def find_matching_lyrics(song_path):
    """Find an LRC file that matches the song filename."""
    song_path = _to_path(song_path)
    song_dir = song_path.parent
    song_name = song_path.name
    song_base = song_path.stem

    # 1. Exact match: song_base.lrc
    candidate = song_dir / (song_base + ".lrc")
    if candidate.is_file():
        return str(candidate)

    # 2. Audio_ext.lrc match: song_name.lrc
    candidate = song_dir / (song_name + ".lrc")
    if candidate.is_file():
        return str(candidate)

    # 3. Fuzzy match: find .lrc file whose base name contains or is contained in song_base
    try:
        dir_entries = list(song_dir.iterdir())
    except (FileNotFoundError, OSError):
        dir_entries = []
    for f in dir_entries:
        if f.name.lower().endswith(".lrc"):
            lrc_base = f.stem
            if lrc_base and (lrc_base in song_base or song_base in lrc_base):
                return str(f)

    return ""


def _looks_like_jpeg(path):
    """检查文件是否以 JPEG 魔数 (FF D8) 开头"""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"\xff\xd8"
    except OSError:
        return False


def extract_embedded_image(song_path):
    """Extract embedded cover art from audio file using ffmpeg.

    缓存文件名由「文件绝对路径 + mtime + 大小」哈希而来：
    - 旧实现只按文件名 stem 命名（mp2_<stem>.jpg），不同目录下同名歌曲
      会命中同一缓存文件，导致封面互相串图；
    - 音频被重新打标签（内嵌封面变化）后 mtime/大小会变，自动重新提取。

    先尝试 -vcodec copy 无损拷贝：内嵌封面是 JPEG 时速度最快。
    如果拷贝结果不是有效 JPEG（内嵌的是 PNG/BMP 时，copy 会把原始
    字节流直接塞进 .jpg 容器，生成损坏文件），回退为重新编码成 JPEG。
    """
    song_path = _to_path(song_path)
    try:
        st = song_path.stat()
        key = f"{song_path.resolve()}:{st.st_mtime}:{st.st_size}"
    except OSError:
        key = str(song_path.resolve())
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]

    temp_dir = Path(tempfile.gettempdir())
    output_path = temp_dir / f"mp2_{digest}.jpg"

    # Return cached if already extracted
    if output_path.is_file() and output_path.stat().st_size > 0:
        return str(output_path)

    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", song_path, "-an", "-vcodec", "copy", str(output_path)],
            capture_output=True, timeout=15
        )
        copied_ok = (
            proc.returncode == 0
            and output_path.is_file()
            and output_path.stat().st_size > 0
            and _looks_like_jpeg(output_path)
        )
        if not copied_ok:
            # 非 JPEG 内嵌封面：重新编码为 JPEG（mjpeg 编码器）
            subprocess.run(
                ["ffmpeg", "-y", "-i", song_path, "-an", "-vcodec", "mjpeg",
                 "-q:v", "3", str(output_path)],
                capture_output=True, timeout=15
            )
        if output_path.is_file() and output_path.stat().st_size > 0:
            return str(output_path)
    except Exception:
        pass
    return ""


def parse_lrc(filepath):
    """Parse an LRC file into a list of (time_seconds, text) tuples."""
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
        return parse_lrc_text(text)
    except Exception:
        return []


def _is_inline_bilingual(text):
    """判断歌词行是否为"原文/译文"内联双语格式。

    只拆分两侧至少有一侧含非 ASCII 字符的行：内联双语（如"日本語/中文翻译"）
    至少一侧是中文/日文等非 ASCII 文本；而 "he/she"、"R&B/Rap" 这类英文
    歌词里的斜杠两侧都是纯 ASCII，不应被误拆成两行。
    """
    if "/" not in text:
        return False
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) < 2:
        return False
    return any(any(ord(c) > 127 for c in p) for p in parts)


def parse_lrc_text(text):
    """Parse LRC lyrics from a string instead of a file."""
    lyrics = []
    pattern = r"\[(\d+):(\d+(?:\.\d+)?)\]"
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        matches = re.findall(pattern, line)
        if not matches:
            continue
        text_part = re.sub(pattern, "", line).strip()
        if not text_part:
            continue
        if text_part.startswith("ti:") or text_part.startswith("ar:") \
           or text_part.startswith("al:") or text_part.startswith("by:") \
           or text_part.startswith("offset:") or text_part.startswith("re:"):
            continue
        for m in matches:
            minutes = int(m[0])
            seconds = float(m[1])
            total_seconds = minutes * 60 + seconds
            lyrics.append((total_seconds, text_part))
    lyrics.sort(key=lambda x: x[0])
    # Split bilingual lyrics (text containing "/") into separate entries
    split_lyrics = []
    for time_sec, text in lyrics:
        if _is_inline_bilingual(text):
            parts = [p.strip() for p in text.split("/") if p.strip()]
            for part in parts:
                split_lyrics.append((time_sec, part))
        else:
            split_lyrics.append((time_sec, text))
    return split_lyrics


def extract_embedded_lyrics(song_path):
    """Extract embedded lyrics from audio file metadata.
    Tries multiple tag names: 'lyrics', 'lyrics-XXX' (ID3v2 USLT frames), etc."""
    song_path = str(_to_path(song_path))

    def _try_parse(text):
        lyrics = parse_lrc_text(text)
        if lyrics:
            return lyrics
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            return [(float(i), line) for i, line in enumerate(lines)]
        return []

    try:
        # First try the exact 'lyrics' tag (most common)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=lyrics",
             "-of", "default=noprint_wrappers=1:nokey=1", song_path],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            parsed = _try_parse(result.stdout.strip())
            if parsed:
                return parsed

        # Fallback: get all format tags and search for any lyrics-* key
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags",
             "-of", "json", song_path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        for key, value in tags.items():
            if key.lower().startswith("lyrics") and value.strip():
                parsed = _try_parse(value.strip())
                if parsed:
                    return parsed
    except Exception:
        pass
    return []


def extract_song_metadata(song_path):
    """Extract embedded title and artist from audio file using ffprobe.
    Returns (title, artist) tuple. Empty strings if not found."""
    song_path = str(_to_path(song_path))
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format_tags=title,artist",
             "-of", "json", song_path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        title = tags.get("title", "").strip()
        artist = tags.get("artist", "").strip()
        return title, artist
    except Exception:
        return "", ""


def scan_music(dir_path=None):
    """Scan the music directory for audio files and images.

    注意：这里只做快速文件扫描，不调用 ffprobe 提取元数据——元数据提取
    由 AudioPlayer._start_metadata_enrichment 在后台线程异步完成，
    避免大曲库启动扫描时长时间卡死 UI。
    """
    if dir_path is None:
        dir_path = MUSIC_DIR

    # 每个目录只列一次图片文件，避免同目录下每首歌都重复 iterdir
    image_cache = {}

    def _dir_images(directory):
        if directory not in image_cache:
            try:
                entries = list(directory.iterdir())
            except (FileNotFoundError, OSError):
                entries = []
            image_cache[directory] = [
                f for f in entries
                if any(f.name.lower().endswith(ext) for ext in SUPPORTED_IMAGE)
            ]
        return image_cache[directory]

    songs = []
    try:
        entries = sorted(dir_path.iterdir())
    except (FileNotFoundError, OSError):
        entries = []
    for fpath in entries:
        # 扩展名不区分大小写（.MP3/.Flac 等也要能扫到）
        if not fpath.name.lower().endswith(SUPPORTED_AUDIO):
            continue
        if not fpath.is_file():
            continue
        try:
            st = fpath.stat()
        except OSError:
            # 文件在扫描期间被删除/权限变化等情况，跳过而不是崩溃
            continue
        songs.append({
            "path": str(fpath),
            "name": fpath.stem,
            "image": find_matching_image(str(fpath), _dir_images(fpath.parent)),
            "mtime": st.st_mtime,
        })
    return songs


def build_song_name(song_path):
    """优先使用内嵌元数据作为歌曲显示名（"标题 - 作者"），否则回退到文件名 stem。"""
    song_path = _to_path(song_path)
    title, artist = extract_song_metadata(str(song_path))
    if title and artist:
        return f"{title} - {artist}"
    if title:
        return title
    return song_path.stem


class _TaskSignals(QObject):
    """后台任务完成信号：finished(task_id, ok, result)。"""
    finished = Signal(int, bool, object)


class AudioPlayer(QObject):
    """音频播放控制后端"""

    # saveSetting 的类型转换只针对这些已知的键：
    # 布尔键按 "true"/"false" 转换，数值键尝试转 int/float，
    # 其它键（musicDir 等路径，可能包含纯数字目录名）一律保持字符串。
    _BOOL_SETTING_KEYS = {"darkMode", "hideControlBackgrounds", "autoSwitchToLyric", "closeToTray"}
    _NUMERIC_SETTING_KEYS = {"volume", "sortMode", "blurRadius", "panelOpacity",
                             "rowSpacing", "lastPosition"}

    # Signals emitted to QML
    positionChanged = Signal(float)  # current position in seconds
    durationChanged = Signal(float)  # total duration in seconds
    stateChanged = Signal(str)       # "playing", "paused", "stopped"
    songChanged = Signal(int)        # current song index
    songListChanged = Signal()
    lyricIndexChanged = Signal(int)  # current lyric line index
    lyricsChanged = Signal()         # lyrics list changed
    musicDirChanged = Signal()       # music directory changed
    sortModeChanged = Signal()       # sort mode changed
    downloadStatusChanged = Signal()  # download status text changed
    searchResultModelChanged = Signal()  # search results changed
    volumeChanged = Signal(int)          # volume changed
    coverFileUpdated = Signal(str)       # 封面文件内容已更新（路径不变），用于刷新 QML 图片缓存

    def __init__(self, parent=None):
        super().__init__(parent)

        # 后台任务调度：网络请求/元数据提取都在线程中执行，避免阻塞 UI。
        # 线程里 emit 的信号会因接收者（本对象，位于 GUI 线程）自动排队投递，
        # 所以回调 _on_task_finished 一定在主线程执行。
        self._task_signals = _TaskSignals(self)
        self._task_signals.finished.connect(self._on_task_finished)
        self._task_counter = 0
        self._task_callbacks = {}

        # 音乐目录与歌曲列表
        self._music_dir = MUSIC_DIR
        self._songs = scan_music(self._music_dir)
        self._sort_mode = 0  # 0=name asc, 1=name desc, 2=time asc, 3=time desc
        self._current_index = -1
        self._song_list_model_cache = None
        self._sort_songs()

        # 播放状态
        self._state = "stopped"  # playing, paused, stopped
        self._volume = 50
        self._position = 0.0
        self._duration = 0.0

        # ffplay 子进程管理
        self._process = None  # QProcess for ffplay
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(250)
        self._position_timer.timeout.connect(self._update_position)

        # 歌词数据
        self._lyrics = []  # list of (time_seconds, text) tuples
        self._current_lyric_index = -1

        # 暂停/续播计时
        self._paused_position = 0.0
        self._play_start_time = 0.0
        self._pause_time = 0.0
        self._total_paused_duration = 0.0
        self._playlist_visible = True
        self._seek_base = 0.0
        self._volume_dirty = False  # 暂停期间是否有未应用到 ffplay 的音量变更（用于 resume 时补偿）
        # 进度条拖动开始前是否处于播放中（松手时据此决定恢复播放还是保持暂停）
        self._seek_drag_was_playing = False

        # PulseAudio 探测与 sink-input 查找缓存：
        # - _pa_available：pactl 可用性只探测一次（每次切歌/seek 都同步 spawn
        #   pactl info 会阻塞 GUI 线程）；
        # - _sink_id_cache：同一 ffplay 进程的 sink-input index 在其生命周期内
        #   不变，按 pid 缓存可避免每次音量调节/重试都跑一遍 pactl list。
        self._pa_available = None
        self._sink_id_cache = {}

        # 最近一次启动的 ffplay 子进程 pid（供 SIGSEGV 处理器做最小化清理）
        self._last_child_pid = None

        # 下载面板数据
        self._search_results = []
        self._download_status = ""
        # 搜索请求代数：连续搜索时旧请求晚到会覆盖新结果，用代数丢弃过期回调
        self._search_seq = 0

        # 内嵌封面异步提取缓存（避免 ffmpeg 阻塞 GUI 线程）
        self._embedded_cover_cache = {}
        self._pending_cover_extract = set()
        self._embedded_cover_failed = set()

        # 配置文件路径
        self._config_dir = Path.home() / ".config" / "PyMusic"
        self._config_file = self._config_dir / "PyMusic.config"
        self._ensure_config_dir()

        # 从配置文件加载音量
        try:
            settings = self.loadSettings()
            if "volume" in settings:
                self._volume = max(0, min(100, int(settings["volume"])))
        except Exception:
            pass

        # 启动后台元数据补全（文件名先建列表，ffprobe 结果异步回填）
        self._start_metadata_enrichment()

    # ========== 歌曲信息查询 ==========

    @Slot(int, result=str)
    def songName(self, index):
        """返回指定索引的歌曲显示名称（歌曲名 - 作者）"""
        if 0 <= index < len(self._songs):
            return self._songs[index]["name"]
        return ""

    @Slot(int, result=str)
    def songPath(self, index):
        """返回指定索引的歌曲文件路径"""
        if 0 <= index < len(self._songs):
            return self._songs[index]["path"]
        return ""

    @Slot(int, result=str)
    def songImage(self, index):
        """返回指定索引的歌曲封面图片路径"""
        if 0 <= index < len(self._songs):
            return self._songs[index]["image"]
        return ""

    @Property(int, notify=songListChanged)
    def songCount(self):
        """返回歌曲总数（QML 可绑定）"""
        return len(self._songs)

    @Property("QVariantList", notify=songListChanged)
    def songListModel(self):
        """返回歌曲列表模型数据，每次排序/变更时重建列表"""
        if self._song_list_model_cache is None:
            self._song_list_model_cache = [
                {"name": s["name"], "path": s["path"], "image": s["image"]}
                for s in self._songs
            ]
        return self._song_list_model_cache

    # ========== 音乐目录管理 ==========

    @Property(str, notify=musicDirChanged)
    def musicDir(self):
        """返回当前音乐目录路径（QML 可绑定）"""
        return str(self._music_dir)

    @Slot(str, result=bool)
    def setMusicDir(self, path):
        """切换音乐目录并重新扫描歌曲，返回是否成功（路径无效返回 False）"""
        path = _to_path(path).expanduser()
        if not path.is_dir():
            return False
        if path != self._music_dir:
            self._music_dir = path
            self._songs = scan_music(path)
            self._sort_songs()
            self._current_index = -1
            self._song_list_model_cache = None
            self.songListChanged.emit()
            self.songChanged.emit(-1)
            self.musicDirChanged.emit()
            self._start_metadata_enrichment()
        return True

    # ========== 当前播放索引 ==========

    @Property(int, notify=songChanged)
    def currentIndex(self):
        """返回当前播放歌曲的索引（QML 可绑定）"""
        return self._current_index

    @currentIndex.setter
    def currentIndex(self, index):
        """设置当前播放歌曲索引，重置播放进度"""
        if index != self._current_index and 0 <= index < len(self._songs):
            self._current_index = index
            self._position = 0.0
            self.songChanged.emit(index)

    # ========== 播放状态属性 ==========

    @Property(str, notify=stateChanged)
    def state(self):
        """返回播放状态：playing / paused / stopped（QML 可绑定）"""
        return self._state

    @Property(float, notify=positionChanged)
    def position(self):
        """返回当前播放进度（秒，QML 可绑定）"""
        return self._position

    @Property(float, notify=durationChanged)
    def duration(self):
        """返回当前歌曲总时长（秒，QML 可绑定）"""
        return self._duration

    # ========== 音量控制 ==========

    @Property(int, notify=volumeChanged)
    def volume(self):
        """返回当前音量（0-100，QML 可绑定）"""
        return self._volume

    @volume.setter
    def volume(self, vol):
        """设置音量（0-100），优先使用 PulseAudio 无缝调节，失败时回退到重启 ffplay

        注意：暂停状态下 ffplay 进程处于 SIGSTOP 挂起态，此时既不应该
        通过 pactl 去调整（进程已挂起，sink-input 可能仍在但调整意义不大），
        也绝不能走"重启 ffplay 再 SIGSTOP"的回退分支——那样会在每次拖动
        滑块时都同步重启子进程并阻塞等待，造成 UI 卡顿。
        暂停时只记录新音量，标记为 dirty，等 resume() 或下次 play() 时
        再统一应用，避免频繁重启进程。
        """
        self._volume = max(0, min(100, vol))
        self.volumeChanged.emit(self._volume)
        # 自动持久化音量（参考其他设置项的 onChange 持久化模式）
        self.saveSetting("volume", str(self._volume))

        if self._state == "paused":
            # 暂停中：不触碰子进程，留到恢复播放时统一应用
            self._volume_dirty = True
            return

        # 优先尝试 PulseAudio/PipeWire 无缝调节（不中断播放，也不阻塞）
        if self._adjust_volume_pa():
            self._volume_dirty = False
            return

        # 回退方案：重启 ffplay 以应用新音量（仅在正在播放且没有 PA 时才需要）
        # ffplay -nodisp 模式无法通过 stdin 按键调音量，只能重启
        if self._state == "playing" and 0 <= self._current_index < len(self._songs):
            # 重启前精确计算当前位置，减少进度回退
            elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
            pos = max(0.0, self._seek_base + elapsed)
            # 时长未知（异步 ffprobe 还没返回）时不能按 0 clamp，否则会从头播放
            if self._duration > 0:
                pos = min(pos, self._duration)

            filepath = self._songs[self._current_index]["path"]
            self._start_ffplay(filepath, pos, use_pa=False)
            self._state = "playing"
            self.stateChanged.emit("playing")
            self._volume_dirty = False

    # ========== 排序模式 ==========

    @Property(int, notify=sortModeChanged)
    def sortMode(self):
        return self._sort_mode

    @sortMode.setter
    def sortMode(self, mode):
        mode = mode % 4
        if mode != self._sort_mode:
            self._sort_mode = mode
            self._sort_songs()
            self.sortModeChanged.emit()

    # ========== 下载面板：搜索 & 下载 ==========

    @Property("QVariantList", notify=searchResultModelChanged)
    def searchResultModel(self):
        """返回网易云搜索结果的模型列表（QML 可绑定）"""
        return self._search_results

    @Property(str, notify=downloadStatusChanged)
    def downloadStatus(self):
        """返回下载/搜索状态文字（QML 可绑定）"""
        return self._download_status

    @Slot(str)
    def searchNetEase(self, keywords):
        """搜索网易云歌曲（后台线程执行，不阻塞 UI）"""
        if not keywords.strip():
            self._download_status = "请输入搜索关键词"
            self.downloadStatusChanged.emit()
            return
        self._download_status = f"正在搜索: {keywords}..."
        self.downloadStatusChanged.emit()
        # 递增代数：连续搜索 A→B 时，若 A 的结果晚于 B 到达，
        # _on_search_done 会凭代数丢弃 A 的过期结果，避免列表回退
        self._search_seq += 1
        seq = self._search_seq
        self._run_task(
            lambda: search_songs(keywords),
            lambda ok, res: self._on_search_done(seq, ok, res),
        )

    def _on_search_done(self, seq, ok, result):
        """搜索完成回调（GUI 线程）"""
        if seq != self._search_seq:
            return  # 期间发起了新的搜索，丢弃过期结果
        if ok:
            self._search_results = result
            self._download_status = f"找到 {len(result)} 首歌曲"
        else:
            self._search_results = []
            self._download_status = f"搜索失败: {result}"
        self.searchResultModelChanged.emit()
        self.downloadStatusChanged.emit()

    @Slot(int, str)
    def downloadLyric(self, song_id, current_path):
        """下载歌词到当前歌曲目录（后台线程执行，不阻塞 UI）"""
        if not current_path:
            self._download_status = "没有当前播放歌曲"
            self.downloadStatusChanged.emit()
            return
        target_path = str(_to_path(current_path))
        self._download_status = "正在下载歌词..."
        self.downloadStatusChanged.emit()
        self._run_task(
            lambda: save_lyric_file(song_id, target_path),
            lambda ok, res: self._on_lyric_downloaded(ok, res, target_path),
        )

    def _on_lyric_downloaded(self, ok, result, target_path):
        """歌词下载完成回调（GUI 线程）"""
        if ok and result:
            self._download_status = f"歌词已保存: {Path(result).name}"
            # 下载期间可能已切歌，仅当目标仍是当前播放歌曲时才重载歌词
            if 0 <= self._current_index < len(self._songs) \
                    and self._songs[self._current_index]["path"] == target_path:
                self._load_lyrics()
        elif ok:
            self._download_status = "未找到歌词"
        else:
            self._download_status = f"下载歌词失败: {result}"
        self.downloadStatusChanged.emit()

    @Slot(str, str, int)
    def downloadCover(self, pic_url, current_path, song_id=0):
        """下载封面图片到当前歌曲目录（后台线程执行，不阻塞 UI）"""
        if not current_path:
            self._download_status = "没有当前播放歌曲"
            self.downloadStatusChanged.emit()
            return
        target_path = str(_to_path(current_path))
        self._download_status = "正在下载封面..."
        self.downloadStatusChanged.emit()
        self._run_task(
            lambda: save_cover_file(song_id, pic_url, target_path),
            lambda ok, res: self._on_cover_downloaded(ok, res, target_path),
        )

    def _on_cover_downloaded(self, ok, result, target_path):
        """封面下载完成回调（GUI 线程）"""
        if ok and result:
            self._download_status = f"封面已保存: {Path(result).name}"
            # 按路径匹配目标歌曲（下载期间可能已切歌，不能只依赖 currentIndex）
            for i, song in enumerate(self._songs):
                if song["path"] == target_path:
                    song["image"] = result
                    self.songChanged.emit(i)
                    # 重新下载会覆盖同路径的旧封面：路径字符串不变，QML 的
                    # Image source 绑定不会重算，Qt 图片缓存也不会重载。
                    # 这里发出专门信号，让 QML 提升版本号强制刷新。
                    self.coverFileUpdated.emit(result)
                    break
        elif ok:
            self._download_status = "未找到封面"
        else:
            self._download_status = f"下载封面失败: {result}"
        self.downloadStatusChanged.emit()

    # ========== 后台任务调度 ==========

    def _run_task(self, fn, on_done):
        """在守护线程中执行 fn（阻塞式 I/O/网络操作），完成后在 GUI 线程回调 on_done(ok, result)。

        线程中 emit 的 Qt 信号因接收者（_task_signals 的父对象，即本播放器）
        位于 GUI 线程而自动排队投递，因此 on_done 一定在主线程执行，
        可以安全操作 UI 状态。
        """
        self._task_counter += 1
        task_id = self._task_counter
        self._task_callbacks[task_id] = on_done

        def worker():
            try:
                result = fn()
                ok = True
            except Exception as e:
                ok, result = False, e
            # 应用退出时 AudioPlayer 可能先于线程被销毁，此时 emit 会抛
            # RuntimeError: Signal source has been deleted（实测可复现）。
            # 守护线程随进程结束，直接忽略即可，避免退出时刷 traceback。
            try:
                self._task_signals.finished.emit(task_id, ok, result)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_finished(self, task_id, ok, result):
        """后台任务完成（GUI 线程）：取出并执行对应回调。"""
        cb = self._task_callbacks.pop(task_id, None)
        if cb is not None:
            cb(ok, result)

    # ========== 内部排序 ==========

    def _sort_songs(self):
        """根据当前排序模式对歌曲列表排序，保持当前播放歌曲索引"""
        current_path = None
        if 0 <= self._current_index < len(self._songs):
            current_path = self._songs[self._current_index]["path"]

        if self._sort_mode == 0:
            self._songs.sort(key=lambda s: s["name"].lower())
        elif self._sort_mode == 1:
            self._songs.sort(key=lambda s: s["name"].lower(), reverse=True)
        elif self._sort_mode == 2:
            self._songs.sort(key=lambda s: s["mtime"])
        elif self._sort_mode == 3:
            self._songs.sort(key=lambda s: s["mtime"], reverse=True)

        # 先通知列表已变更，让 ListView 重建模型
        self._song_list_model_cache = None
        self.songListChanged.emit()

        # 再恢复当前播放歌曲的索引
        if current_path:
            for i, song in enumerate(self._songs):
                if song["path"] == current_path:
                    if i != self._current_index:
                        self._current_index = i
                        self.songChanged.emit(i)
                    break

    def _start_metadata_enrichment(self):
        """后台异步提取所有歌曲的标题/作者元数据，完成后回填列表并重新排序。

        启动时同步跑 ffprobe 会导致大曲库长时间卡死 UI，所以先快速建列表，
        再在后台线程批量补全元数据。回写时按路径匹配，即使期间切换了目录
        或排序，也不会把结果错填到别的歌曲上。
        """
        snapshot = [(i, s["path"]) for i, s in enumerate(self._songs)]
        if not snapshot:
            return

        def work():
            return [(i, path, build_song_name(path)) for i, path in snapshot]

        self._run_task(work, self._on_metadata_enriched)

    def _on_metadata_enriched(self, ok, result):
        """元数据补全完成回调（GUI 线程）"""
        if not ok:
            return
        changed = False
        for i, path, name in result:
            if 0 <= i < len(self._songs) and self._songs[i]["path"] == path \
                    and name and self._songs[i]["name"] != name:
                self._songs[i]["name"] = name
                changed = True
        if changed:
            self._sort_songs()

    # ========== ffplay 进程管理 ==========

    def _kill_process(self):
        """终止当前 ffplay 进程并清理资源"""
        old_process = self._process
        if old_process:
            # Disconnect the finished signal to prevent side effects
            try:
                old_process.finished.disconnect(self._on_ffplay_finished)
            except Exception:
                pass
            if old_process.state() == QProcess.Running:
                pid = old_process.processId()
                if pid > 0:
                    # 先恢复进程（如果被 SIGSTOP 暂停了），确保 SIGTERM 能送达
                    try:
                        os.kill(pid, signal.SIGCONT)
                    except Exception:
                        pass
                old_process.terminate()
                if not old_process.waitForFinished(500):
                    old_process.kill()
                    old_process.waitForFinished(300)
            # QProcess 没有 parent：引用一旦被替换就只有 Python 侧回收，
            # 显式 deleteLater 让 Qt 事件循环确定性地销毁 C++ 对象
            old_process.deleteLater()
        self._process = None
        # 进程已死，pid 缓存随之失效
        self._sink_id_cache.clear()
        self._last_child_pid = None

    def _check_pa_available(self):
        """检查系统是否有可用的 PulseAudio/PipeWire

        结果缓存：pactl 探测只在第一次需要时同步执行一次，之后直接返回
        缓存值，避免每次切歌/seek 都 spawn 一个 pactl 进程阻塞 GUI 线程。
        """
        if self._pa_available is None:
            try:
                result = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=3)
                self._pa_available = result.returncode == 0
            except Exception:
                self._pa_available = False
        return self._pa_available

    def _find_sink_input_id(self, pid):
        """查找指定 pid 对应的 PulseAudio sink-input index，找不到返回 None

        结果按 pid 缓存（_kill_process 时清空）：同一 ffplay 进程的
        sink-input index 在其生命周期内不变，缓存可避免重试音量纠正时
        反复执行开销不小的 pactl list。

        注意区分两种"找不到"：sink-input 尚未注册（正常，重试即可）和
        pactl 本身失败（PA 服务挂了）。后者要把 _pa_available 缓存置回
        None，让下次 _check_pa_available 重新探测，避免 PA 挂掉后所有
        新歌都按"有 PA"路径启动 100% 音量而音量纠正又永远失败。
        """
        cached = self._sink_id_cache.get(pid)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                ["pactl", "-f", "json", "list", "sink-inputs"],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            self._pa_available = None
            return None
        if result.returncode != 0:
            self._pa_available = None
            return None
        try:
            inputs = json.loads(result.stdout) if result.stdout.strip() else []
        except ValueError:
            self._pa_available = None
            return None
        for inp in inputs:
            props = inp.get("properties", {})
            if props.get("application.process.id") == str(pid):
                self._sink_id_cache[pid] = inp["index"]
                return inp["index"]
        return None

    def _adjust_volume_pa(self):
        """通过 PulseAudio/PipeWire pactl 无缝调节音量（不重启 ffplay）。成功返回 True。

        单次非阻塞查找：ffplay 刚启动时 sink-input 可能还没在 PulseAudio
        中注册完成，此时查不到对应 pid 会返回 False。调用方
        （_start_ffplay 通过 _retry_pa_volume）负责在失败时异步重试，
        这里不做阻塞式 sleep，避免卡住 UI 线程。
        """
        if not self._process or self._process.state() != QProcess.Running:
            return False
        pid = self._process.processId()
        if not pid:
            return False

        sink_id = self._find_sink_input_id(pid)
        if sink_id is None:
            return False

        try:
            # PulseAudio 音量范围 0-65536 对应 0%-100%（0dB，无增益）
            pa_vol = int(self._volume / 100.0 * 65536)
            result = subprocess.run(
                ["pactl", "set-sink-input-volume", str(sink_id), str(pa_vol)],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
            # 设置失败（PA 服务异常）：使可用性缓存失效，下次重新探测
            self._pa_available = None
            return False
        except Exception:
            self._pa_available = None
            return False

    def _retry_pa_volume(self, process_ref, attempt):
        """异步、不阻塞地重试将 PA 音量纠正到当前设置值。

        ffplay 启动初期 sink-input 尚未在 PulseAudio 中注册是正常现象，
        所以第一次尝试失败很常见。只要 process_ref 仍是当前正在播放的
        进程（用户没有切歌/停止），就按递增间隔继续尝试，直到成功或
        达到最大次数为止，从而避免"音量条50%实际播放100%"的问题。
        """
        # 进程已经被切换/停止，放弃重试
        if process_ref is not self._process:
            return
        # Starting 状态视为可重试：ffplay 可能还没完成启动（不再有
        # waitForStarted 兜底），只有 NotRunning 才彻底放弃
        if process_ref.state() == QProcess.NotRunning:
            return

        if self._adjust_volume_pa():
            return  # 成功，音量已纠正

        max_attempts = 8
        if attempt >= max_attempts:
            return

        delay_ms = min(50 * (attempt + 1), 400)
        QTimer.singleShot(delay_ms, lambda: self._retry_pa_volume(process_ref, attempt + 1))

    def _start_ffplay(self, filepath, seek_to=0.0, use_pa=None):
        """启动 ffplay 进程播放指定音频文件，支持从指定位置开始播放

        Args:
            use_pa: None=自动检测, True=强制使用 PA, False=不使用 PA
        """
        self._kill_process()
        self._process = QProcess()
        self._process.setProcessChannelMode(QProcess.ForwardedErrorChannel)

        if use_pa is None:
            use_pa = self._check_pa_available()

        if use_pa:
            # 有 PulseAudio 时，ffplay 固定 100% 音量，由 PA 直接控制
            vol = 100
        else:
            vol = self._volume

        args = [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-volume", str(vol),
            "-ss", str(seek_to),
            filepath,
        ]
        self._process.start("ffplay", args[1:])
        # 不调用 waitForStarted()：它会阻塞 GUI 线程最多 500ms，
        # 正是切歌时"轻微卡顿"的来源之一。进程启动交给事件循环处理，
        # PA 音量纠正本来就是异步重试，不受影响。
        self._process.finished.connect(self._on_ffplay_finished)
        self._process.started.connect(self._on_process_started)

        if use_pa:
            # ffplay 以 100% 启动，需要靠 PA 把音量纠正到用户设置的值。
            # sink-input 在 ffplay 打开音频设备前不会出现在 pactl 列表里，
            # 单次同步尝试常常因为这个时序问题而失败，之前失败后就不再重试，
            # 导致 ffplay 一直用启动时的 100% 音量播放，而界面滑块显示的却是
            # 用户设置的音量（比如 50%）——这就是"滑块50%等于实际100%"的原因。
            # 这里改为异步、多次、递增间隔地重试，直到成功把 PA 音量纠正过来，
            # 且不阻塞 UI 线程。
            this_process = self._process
            self._retry_pa_volume(this_process, attempt=0)

        # 异步获取时长与歌词，避免 ffprobe 阻塞 UI
        self._duration = 0.0
        self.durationChanged.emit(self._duration)
        self._async_load_metadata(filepath)
        self._load_lyrics()

        self._seek_base = seek_to
        self._play_start_time = self._get_current_time()
        self._total_paused_duration = 0.0
        self._position_timer.start()

    def _on_process_started(self):
        """记录 ffplay 子进程 pid（供 SIGSEGV 处理器做最小化清理）"""
        if self._process and self._process.state() != QProcess.NotRunning:
            pid = self._process.processId()
            if pid > 0:
                self._last_child_pid = pid

    def _async_load_metadata(self, filepath):
        """后台线程加载歌曲时长（ffprobe），完成后在 GUI 线程回调。

        旧实现虽然名字叫 async，实际是在 GUI 线程同步 subprocess.run，
        ffprobe 冷启动 50~200ms，正是切歌卡顿的主因。
        """
        self._run_task(
            lambda: self._get_duration(filepath),
            lambda ok, res: self._on_duration_loaded(filepath, ok, res),
        )

    def _on_duration_loaded(self, filepath, ok, duration):
        """时长加载完成（GUI 线程）：仅当仍是当前歌曲时才应用"""
        if ok and 0 <= self._current_index < len(self._songs) \
                and self._songs[self._current_index]["path"] == filepath:
            self._duration = float(duration) if duration else 0.0
            self.durationChanged.emit(self._duration)

    def _get_current_time(self):
        """获取当前时间戳（用于计算播放进度）。

        用 time.monotonic() 而不是 time.time()：播放进度是相对时长计算，
        系统时钟被 NTP 校准/手动修改时 time.time() 会跳变，导致进度条
        和暂停时长补偿出现瞬间前跳/回退；monotonic 不受系统时钟影响。
        """
        return time.monotonic()

    def _get_duration(self, filepath):
        """通过 ffprobe 获取音频文件时长"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 filepath],
                capture_output=True, text=True, timeout=10
            )
            if result.stdout.strip():
                return float(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return 0.0

    def _update_position(self):
        """定时更新播放进度位置，触发信号通知 QML"""
        if self._state == "playing":
            elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
            # 时长未知（异步 ffprobe 还没返回）时先不 clamp，避免进度条卡在 0
            if self._duration > 0:
                self._position = min(self._seek_base + elapsed, self._duration)
            else:
                self._position = self._seek_base + elapsed
            self.positionChanged.emit(self._position)
            self._update_lyric_index()

    def _on_ffplay_finished(self, exit_code, exit_status):
        """ffplay 进程结束时自动切换到下一曲"""
        self._position_timer.stop()
        # 只处理自然退出（我们自己杀进程切歌时已提前断开本信号）
        if self._state == "stopped":
            return

        # 退出码非 0 / 非正常退出：ffplay 启动失败（ffplay 不存在）、文件损坏、
        # 解码失败或被外部杀死。此时若继续自动切歌，会在坏文件之间无限循环；
        # 之前这里直接 return，UI 会永远停留在"播放中"而实际没有进程在放。
        # 改为转入 stopped 状态并通知 UI，让播放键回到可重新播放的状态。
        if exit_status != QProcess.NormalExit or exit_code != 0:
            self._state = "stopped"
            self.stateChanged.emit("stopped")
            return

        # 时长已知时按播放进度判断是否接近结尾；时长未知（异步 ffprobe 还没
        # 返回，_duration 为 0）时按实际播放时长判断——否则
        # "position >= duration - 1.0" 在 duration 为 0 时恒成立，
        # 会在一开始播放就误触发切歌。
        if self._duration > 0:
            near_end = self._position >= self._duration - 1.0
        else:
            elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
            near_end = elapsed >= 1.0
        if near_end:
            self.next()
            return

        # 正常退出（exit 0）却没到结尾：ffplay 遇到损坏/截断文件会静默正常退出
        # （实测 exit code 仍为 0），此时若不做处理，UI 会永远停在"播放中"、
        # 进度条冻结且没有声音。转入 stopped 让播放键恢复可用。
        self._state = "stopped"
        self.stateChanged.emit("stopped")

    @Slot()
    def play(self):
        """开始播放当前歌曲"""
        if len(self._songs) == 0:
            return
        if self._current_index < 0:
            self._current_index = 0
            self.songChanged.emit(0)

        filepath = self._songs[self._current_index]["path"]
        self._start_ffplay(filepath, self._position)
        self._state = "playing"
        self.stateChanged.emit("playing")

    @Slot()
    def pause(self):
        """暂停当前播放（通过 SIGSTOP 暂停 ffplay 进程）

        ffplay 可能仍处于 Starting 状态（启动中）：此时直接 SIGSTOP 无效。
        把暂停动作挂到 started 信号上，进程真正起来后再立刻挂起；
        _pause_time 也在真正挂起的那一刻记录，保证 resume() 计算的
        暂停时长准确。
        """
        if self._state != "playing":
            return
        if self._process and self._process.state() == QProcess.Running:
            pid = self._process.processId()
            if pid > 0:
                os.kill(pid, signal.SIGSTOP)
            self._pause_time = self._get_current_time()
        elif self._process and self._process.state() == QProcess.Starting:
            self._process.started.connect(self._pause_new_process)
        self._state = "paused"
        self.stateChanged.emit("paused")
        self._position_timer.stop()

    @Slot()
    def resume(self):
        """恢复播放（通过 SIGCONT 继续 ffplay 进程）"""
        if self._state != "paused":
            return
        # 进程已挂起时才 SIGCONT 并补偿暂停时长；
        # 进程还在启动中（Starting，_pause_new_process 尚未触发）时跳过补偿。
        if self._process and self._process.state() == QProcess.Running:
            pid = self._process.processId()
            if pid > 0:
                os.kill(pid, signal.SIGCONT)
            self._total_paused_duration += self._get_current_time() - self._pause_time
        self._state = "playing"
        self.stateChanged.emit("playing")
        self._position_timer.start()

        # 应用暂停期间累积但未生效的音量变更
        if self._volume_dirty:
            if not self._adjust_volume_pa():
                elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
                pos = max(0.0, self._seek_base + elapsed)
                # 时长未知（异步 ffprobe 还没返回）时不能按 0 clamp，否则会从头播放
                if self._duration > 0:
                    pos = min(pos, self._duration)
                filepath = self._songs[self._current_index]["path"] if 0 <= self._current_index < len(self._songs) else None
                if filepath:
                    self._start_ffplay(filepath, pos, use_pa=False)
                    self._state = "playing"
                    self.stateChanged.emit("playing")
            self._volume_dirty = False

    @Slot()
    def playPause(self):
        """播放/暂停切换（QML 播放按钮绑定）"""
        if self._state == "playing":
            self.pause()
        elif self._state == "paused":
            self.resume()
        else:
            self.play()

    @Slot()
    def stop(self):
        """停止播放并重置进度"""
        self._kill_process()
        self._position_timer.stop()
        self._position = 0.0
        self._state = "stopped"
        self.stateChanged.emit("stopped")
        self.positionChanged.emit(0.0)

    @Slot()
    def next(self):
        """切换到下一首歌曲"""
        self._switch_song(1)

    @Slot()
    def previous(self):
        """切换到上一首歌曲"""
        self._switch_song(-1)

    def _switch_song(self, delta):
        """按 delta 切换歌曲（+1 下一首 / -1 上一首），并在非停止状态下自动播放"""
        if len(self._songs) == 0:
            return
        if self._current_index < 0:
            # 尚未选择歌曲：下一首从第一首开始，上一首从最后一首开始
            # （(-1 + -1) % n 会得到 n-2，直接取模是错的）
            self._current_index = len(self._songs) - 1 if delta < 0 else 0
        else:
            self._current_index = (self._current_index + delta) % len(self._songs)
        self.songChanged.emit(self._current_index)
        self._position = 0.0
        self.positionChanged.emit(0.0)  # 立即刷新进度条，不必等下一次 250ms 定时器
        if self._state != "stopped":
            filepath = self._songs[self._current_index]["path"]
            self._start_ffplay(filepath, 0.0)
            self._state = "playing"
            self.stateChanged.emit("playing")

    @Slot(float)
    def seek(self, pos_seconds):
        """跳转到指定播放位置（秒）"""
        if self._current_index < 0:
            return
        # 时长未知时不按 0 clamp，否则进度会被错误压到 0
        if self._duration > 0:
            self._position = max(0.0, min(pos_seconds, self._duration))
        else:
            self._position = max(0.0, pos_seconds)
        # 立即同步 UI，不必等下一次 250ms 定时器
        self.positionChanged.emit(self._position)
        self._update_lyric_index()
        if self._state != "stopped":
            filepath = self._songs[self._current_index]["path"]
            was_playing = (self._state == "playing")
            self._start_ffplay(filepath, self._position)
            if was_playing:
                self._state = "playing"
                self.stateChanged.emit("playing")
            else:
                self._state = "paused"
                self.stateChanged.emit("paused")
                self._position_timer.stop()
                # ffplay 一启动就挂起（SIGSTOP）。不用 waitForStarted 阻塞等待，
                # 改由 started 信号触发，避免拖拽进度条时 UI 卡顿。
                if self._process:
                    self._process.started.connect(self._pause_new_process)

    @Slot()
    def seekDragStarted(self):
        """拖动进度条开始：停止播放进程，精确冻结当前位置。

        拖动期间不再按旧逻辑每次 mousemove 杀启一次 ffplay（拖一次
        进度条 = 几十次进程重启，是拖动卡顿的主因），改为开始拖动时
        停一次、松手时在目标位置起一次。
        """
        self._seek_drag_was_playing = (self._state == "playing")
        self._position_timer.stop()
        # 用单调时钟精确结算一次当前位置，此后位置完全由 UI 预览驱动
        if self._state == "playing":
            elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
            pos = self._seek_base + elapsed
            if self._duration > 0:
                pos = min(pos, self._duration)
            self._position = max(0.0, pos)
            self.positionChanged.emit(self._position)
        if self._process:
            self._kill_process()
        if self._state != "stopped":
            self._state = "paused"
            self.stateChanged.emit("paused")

    @Slot(float)
    def seekPreview(self, pos):
        """拖动进度条过程中：只精确更新显示位置与歌词索引，不触碰播放进程"""
        if self._duration > 0:
            self._position = max(0.0, min(pos, self._duration))
        else:
            self._position = max(0.0, pos)
        self.positionChanged.emit(self._position)
        self._update_lyric_index()

    @Slot(float)
    def seekCommit(self, pos):
        """拖动结束：在目标位置恢复播放（拖动前在播）或保持暂停（拖动前暂停）"""
        resume_playing = self._seek_drag_was_playing
        self._seek_drag_was_playing = False
        if resume_playing and 0 <= self._current_index < len(self._songs):
            # 先切到"播放中"再走 seek() 的 was_playing 分支：
            # 重启进程并直接处于播放态，用 -ss 精确定位到松手位置
            self._state = "playing"
            self.stateChanged.emit("playing")
        self.seek(pos)

    def _pause_new_process(self):
        """seek/启动即暂停场景：ffplay 启动完成即刻挂起。仅当仍处于暂停态时生效，
        防止用户在 started 到达前点了播放导致误停新进程。

        挂起成功时同步记录 _pause_time——漏掉这一步的话，resume() 会用
        seek 之前旧的 _pause_time 累加 _total_paused_duration（该值已在
        _start_ffplay 里清零），造成暂停时长被重复计入、进度回跳。
        """
        if self._state != "paused" or not self._process:
            return
        if self._process.state() == QProcess.NotRunning:
            return
        pid = self._process.processId()
        if pid > 0:
            os.kill(pid, signal.SIGSTOP)
            self._pause_time = self._get_current_time()

    @Slot(int)
    def setVolume(self, vol):
        """设置音量（QML 滑块绑定）"""
        self.volume = vol

    @Slot(int, result=str)
    def formatTime(self, seconds):
        """将秒数格式化为 mm:ss 格式"""
        if seconds < 0:
            seconds = 0
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    @Property(str, notify=songChanged)
    def currentSongImage(self):
        """返回当前歌曲的封面图片路径（QML 可绑定）

        内嵌封面提取（ffmpeg，50~300ms）不再同步执行：首次访问时发起
        后台提取，完成后通过 songChanged 通知 QML 重新求值。提取失败
        的歌曲会被记住，避免反复空跑 ffmpeg。
        """
        if 0 <= self._current_index < len(self._songs):
            song = self._songs[self._current_index]
            if song["image"]:
                return song["image"]
            cached = self._embedded_cover_cache.get(song["path"], "")
            if cached:
                return cached
            # Lazy extract embedded image on demand (后台线程)
            self._request_embedded_cover(song["path"])
        return ""

    def _request_embedded_cover(self, song_path):
        """发起后台内嵌封面提取（同一首歌只发起一次）"""
        if song_path in self._pending_cover_extract \
                or song_path in self._embedded_cover_failed:
            return
        self._pending_cover_extract.add(song_path)
        self._run_task(
            lambda: extract_embedded_image(song_path),
            lambda ok, res: self._on_cover_extracted(song_path, ok, res),
        )

    def _on_cover_extracted(self, song_path, ok, result):
        """内嵌封面提取完成（GUI 线程）"""
        self._pending_cover_extract.discard(song_path)
        if not ok or not result:
            self._embedded_cover_failed.add(song_path)
            return
        self._embedded_cover_cache[song_path] = result
        if 0 <= self._current_index < len(self._songs) \
                and self._songs[self._current_index]["path"] == song_path:
            self.songChanged.emit(self._current_index)

    @Property(str, notify=songChanged)
    def currentSongName(self):
        """返回当前歌曲的显示名称（QML 可绑定）"""
        if 0 <= self._current_index < len(self._songs):
            return self._songs[self._current_index]["name"]
        return ""

    # ========== 播放列表折叠 ==========

    playlistVisibleChanged = Signal()

    @Property(bool, notify=playlistVisibleChanged)
    def playlistVisible(self):
        """返回播放列表是否可见（QML 可绑定）"""
        return self._playlist_visible

    @playlistVisible.setter
    def playlistVisible(self, visible):
        """设置播放列表折叠/展开状态"""
        if visible != self._playlist_visible:
            self._playlist_visible = visible
            self.playlistVisibleChanged.emit()

    # ========== 歌词相关 ==========

    def _load_lyrics(self):
        """加载当前歌曲的歌词（后台线程执行）。

        内嵌歌词需要跑 ffprobe（每次 50~200ms），旧实现在 GUI 线程同步
        调用，是切歌卡顿的主因之一。现在先立刻清空旧歌词（避免新歌显示
        上一首的歌词），再后台加载，完成后回填。
        """
        self._lyrics = []
        self._current_lyric_index = -1
        self.lyricsChanged.emit()
        self.lyricIndexChanged.emit(-1)
        if 0 <= self._current_index < len(self._songs):
            song_path = self._songs[self._current_index]["path"]
            self._run_task(
                lambda: self._read_lyrics(song_path),
                lambda ok, res: self._on_lyrics_loaded(song_path, ok, res),
            )

    def _read_lyrics(self, song_path):
        """后台线程：优先读取外部 LRC 文件，其次读取内嵌元数据"""
        lrc_path = find_matching_lyrics(song_path)
        if lrc_path:
            return parse_lrc(lrc_path)
        return extract_embedded_lyrics(song_path)

    def _on_lyrics_loaded(self, song_path, ok, lyrics):
        """歌词加载完成（GUI 线程）：仅当仍是当前歌曲时才应用，避免快速
        切歌时旧歌词错填到新歌上。"""
        if ok and 0 <= self._current_index < len(self._songs) \
                and self._songs[self._current_index]["path"] == song_path:
            self._lyrics = lyrics or []
            self._current_lyric_index = -1
            self.lyricsChanged.emit()
            self.lyricIndexChanged.emit(-1)

    @Property(int, notify=lyricsChanged)
    def lyricCount(self):
        """返回歌词行数（QML 可绑定）"""
        return len(self._lyrics)

    @Property(int, notify=lyricIndexChanged)
    def currentLyricIndex(self):
        """返回当前播放位置对应的歌词索引（QML 可绑定）"""
        return self._current_lyric_index

    @Property(float, notify=lyricIndexChanged)
    def currentLyricTime(self):
        """当前歌词行的时间戳，用于 QML 绑定追踪依赖。"""
        if 0 <= self._current_lyric_index < len(self._lyrics):
            return self._lyrics[self._current_lyric_index][0]
        return 0.0

    @Slot(int, result=str)
    def lyricText(self, index):
        """返回指定索引的歌词文本"""
        if 0 <= index < len(self._lyrics):
            return self._lyrics[index][1]
        return ""

    @Slot(int, result=float)
    def lyricTime(self, index):
        """返回指定索引的歌词时间戳"""
        if 0 <= index < len(self._lyrics):
            return self._lyrics[index][0]
        return 0.0

    def cleanup(self):
        """应用退出时清理资源，保存上次播放位置"""
        # 保存上次播放位置
        if self._current_index >= 0 and self._state != "stopped":
            song_path = self._songs[self._current_index]["path"]
            self.saveSetting("lastFile", song_path)
            self.saveSetting("lastPosition", str(self._position))
        self._kill_process()
        self._position_timer.stop()

    @Slot(result=bool)
    def restoreLastPosition(self):
        """恢复上次播放位置，返回是否成功找到歌曲"""
        settings = self.loadSettings()
        last_file = settings.get("lastFile", "")
        last_position = settings.get("lastPosition", 0.0)
        if not last_file or not _to_path(last_file).is_file():
            return False
        for i, song in enumerate(self._songs):
            if song["path"] == last_file:
                self._current_index = i
                self.songChanged.emit(i)
                self._position = float(last_position)
                # 恢复的位置立刻同步给 UI（此时播放尚未开始，定时器不运行）
                self.positionChanged.emit(self._position)
                self._load_lyrics()
                return True
        return False

    def _update_lyric_index(self):
        """根据当前播放位置更新歌词索引（二分查找）"""
        if not self._lyrics:
            if self._current_lyric_index != -1:
                self._current_lyric_index = -1
                self.lyricIndexChanged.emit(-1)
            return
        # Binary search for the last lyric whose time <= current position
        pos = self._position
        lo, hi = 0, len(self._lyrics) - 1
        idx = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._lyrics[mid][0] <= pos:
                idx = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if idx != self._current_lyric_index:
            self._current_lyric_index = idx
            self.lyricIndexChanged.emit(idx)

    # ========== 配置持久化 ==========

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self._config_dir.mkdir(parents=True, exist_ok=True)

    @Slot(result="QVariantMap")
    def loadSettings(self):
        """从配置文件加载所有设置"""
        defaults = {
            "darkMode": True,
            "customAccent": "",
            "customDarkBg": "",
            "customLightBg": "",
            "customLyricColor": "",
            "customLyricPlayedColor": "",
            "customLyricUnplayedColor": "",
            "customBtnBg": "",
            
            "blurRadius": 80,
            "panelOpacity": 0.45,
            "hideControlBackgrounds": False,
            "lastFile": "",
            "lastPosition": 0.0,
            "sortMode": 0,
            "musicDir": str(MUSIC_DIR),
            "rowSpacing": 48,
            "customFontFamily": "",
            "volume": 50,
            "closeToTray": True,
        }
        try:
            if self._config_file.exists():
                with open(self._config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
        return defaults

    @Slot(str, str)
    def saveSetting(self, key, value):
        """保存单个设置项到配置文件"""
        self._ensure_config_dir()
        settings = {}
        try:
            if self._config_file.exists():
                with open(self._config_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
        except Exception:
            pass
        # 类型转换：按已知键白名单转换，避免把路径等任意字符串
        # 误转成数字（例如纯数字目录名的音乐路径被存成 int）
        if key in self._BOOL_SETTING_KEYS:
            settings[key] = value.lower() == "true"
        elif key in self._NUMERIC_SETTING_KEYS:
            try:
                settings[key] = float(value) if "." in value else int(value)
            except ValueError:
                settings[key] = value
        else:
            settings[key] = value
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


# ========== 应用入口 ==========


def _setup_signal_handlers(player):
    """注册信号处理器，确保在异常退出时清理 ffplay 子进程。

    当进程收到 SIGINT (Ctrl+C)、SIGTERM (kill) 时，先调用 player.cleanup()
    终止 ffplay 子进程，再退出。

    SIGSEGV 单独处理：段错误发生时进程内存可能已损坏，处理器里调用任何
    Python/Qt 方法（cleanup 含 waitForFinished 等复杂逻辑）都极不安全，
    可能造成二次崩溃或死锁。这里只做最小化处理：直接 os.kill 向记录的
    ffplay 子进程 pid 发 SIGTERM（纯系统调用），然后恢复默认处理，
    让进程按正常方式 core dump。
    """
    def _signal_handler(signum, frame):
        player.cleanup()
        # 恢复默认信号处理并重新发送信号，让进程以正常方式退出
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _signal_handler)

    def _segv_handler(signum, frame):
        pid = getattr(player, "_last_child_pid", None)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGSEGV, _segv_handler)


class AppBridge(QObject):
    """桥接对象，向 QML 暴露 Python 侧的退出等功能"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quit_callback = None
        self._tray_available = True

    def setQuitCallback(self, callback):
        self._quit_callback = callback

    def setTrayAvailable(self, available):
        """记录系统托盘是否可用。不可用时 QML 关闭窗口应直接退出，
        否则窗口藏起来后没有任何入口能恢复（托盘图标不存在）。"""
        self._tray_available = bool(available)

    @Property(bool, constant=True)
    def trayAvailable(self):
        return self._tray_available

    @Slot()
    def quitApp(self):
        if self._quit_callback:
            self._quit_callback()


def main():
    """启动 PySide6 QML 应用"""
    app = QApplication([])
    app.setApplicationName("MusicPlayer2 - Py")
    # 关闭主窗口时不退出程序，改为最小化到系统托盘
    app.setQuitOnLastWindowClosed(False)

    # 设置窗口图标和系统托盘图标
    icon_path = str(Path(__file__).parent / "icons" / "LOGO.png")
    app.setWindowIcon(QIcon(icon_path))
    tray = QSystemTrayIcon(QIcon(icon_path), app)
    tray.setToolTip("MusicPlayer2 - Py")
    tray.show()

    engine = QQmlApplicationEngine()
    player = AudioPlayer()

    # 注册信号处理器，确保异常退出时清理子进程
    _setup_signal_handlers(player)

    engine.rootContext().setContextProperty("player", player)
    app.aboutToQuit.connect(player.cleanup)
    engine.load(str(Path(__file__).parent / "main.qml"))

    if not engine.rootObjects():
        print("错误: 无法加载 QML 文件")
        return -1

    window = engine.rootObjects()[0]

    def show_window():
        """恢复并激活主窗口（双击托盘图标 / 菜单中"显示主窗口"触发）"""
        window.show()
        window.raise_()
        window.requestActivate()

    def quit_app():
        """真正退出程序：先清理子进程，再关闭托盘图标，最后退出事件循环"""
        player.cleanup()
        tray.hide()
        app.quit()

    # 桥接对象：向 QML 暴露 quitApp()
    bridge = AppBridge()
    bridge.setQuitCallback(quit_app)
    bridge.setTrayAvailable(QSystemTrayIcon.isSystemTrayAvailable())
    engine.rootContext().setContextProperty("appBridge", bridge)

    # 托盘右键菜单：显示主窗口 / 退出
    tray_menu = QMenu()
    show_action = tray_menu.addAction("显示主窗口")
    show_action.triggered.connect(show_window)
    tray_menu.addSeparator()
    quit_action = tray_menu.addAction("退出")
    quit_action.triggered.connect(quit_app)
    tray.setContextMenu(tray_menu)

    # 双击托盘图标恢复窗口
    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            show_window()

    tray.activated.connect(on_tray_activated)

    return app.exec()


if __name__ == "__main__":
    import sys
    sys.exit(main())
