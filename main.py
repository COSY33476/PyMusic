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


def _to_path(path_str):
    """Normalize a path string to a Path object with cross-platform support.
    Converts Windows backslashes to forward slashes so paths from any OS
    are parsed correctly regardless of the host platform."""
    if isinstance(path_str, Path):
        return path_str
    return Path(str(path_str).replace("\\", "/"))


def find_matching_image(song_path):
    """Find an image file that matches the song filename."""
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
    all_images = []
    try:
        dir_entries = list(song_dir.iterdir())
    except (FileNotFoundError, OSError):
        dir_entries = []
    for f in dir_entries:
        f_lower = f.name.lower()
        if any(f_lower.endswith(ext) for ext in SUPPORTED_IMAGE):
            all_images.append(f)

    for img_path in all_images:
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


def extract_embedded_image(song_path):
    """Extract embedded cover art from audio file using ffmpeg."""
    temp_dir = Path(tempfile.gettempdir())
    base = _to_path(song_path).stem
    output_path = temp_dir / f"mp2_{base}.jpg"

    # Return cached if already extracted
    if output_path.is_file() and output_path.stat().st_size > 0:
        return str(output_path)

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", song_path, "-an", "-vcodec", "copy", str(output_path)],
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
        if "/" in text:
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
    """Scan the music directory for audio files and images."""
    if dir_path is None:
        dir_path = MUSIC_DIR
    songs = []
    for ext in SUPPORTED_AUDIO:
        for fpath in sorted(dir_path.glob("*" + ext)):
            img = find_matching_image(str(fpath))

            # 优先使用嵌入元数据作为歌曲名，格式："歌曲名 - 作者"
            title, artist = extract_song_metadata(str(fpath))
            if title and artist:
                name = f"{title} - {artist}"
            elif title:
                name = title
            else:
                name = fpath.stem

            songs.append({
                "path": str(fpath),
                "name": name,
                "image": img,
                "mtime": fpath.stat().st_mtime,
            })
    return songs


class AudioPlayer(QObject):
    """音频播放控制后端"""

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

    def __init__(self, parent=None):
        super().__init__(parent)

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

        # 下载面板数据
        self._search_results = []
        self._download_status = ""

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

    @Slot(str)
    def setMusicDir(self, path):
        """切换音乐目录并重新扫描歌曲"""
        path = _to_path(path).expanduser()
        if path.is_dir() and path != self._music_dir:
            self._music_dir = path
            self._songs = scan_music(path)
            self._sort_songs()
            self._current_index = -1
            self._song_list_model_cache = None
            self.songListChanged.emit()
            self.songChanged.emit(-1)
            self.musicDirChanged.emit()

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
            pos = min(self._seek_base + elapsed, self._duration)

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
        """搜索网易云歌曲"""
        if not keywords.strip():
            self._download_status = "请输入搜索关键词"
            self.downloadStatusChanged.emit()
            return
        self._download_status = f"正在搜索: {keywords}..."
        self.downloadStatusChanged.emit()
        try:
            self._search_results = search_songs(keywords)
            self._download_status = f"找到 {len(self._search_results)} 首歌曲"
        except Exception as e:
            self._search_results = []
            self._download_status = f"搜索失败: {e}"
        self.searchResultModelChanged.emit()
        self.downloadStatusChanged.emit()

    @Slot(int, str)
    def downloadLyric(self, song_id, current_path):
        """下载歌词到当前歌曲目录"""
        if not current_path:
            self._download_status = "没有当前播放歌曲"
            self.downloadStatusChanged.emit()
            return
        self._download_status = "正在下载歌词..."
        self.downloadStatusChanged.emit()
        try:
            result = save_lyric_file(song_id, current_path)
            if result:
                self._download_status = f"歌词已保存: {Path(result).name}"
                self._load_lyrics()
            else:
                self._download_status = "未找到歌词"
        except Exception as e:
            self._download_status = f"下载歌词失败: {e}"
        self.downloadStatusChanged.emit()

    @Slot(str, str, int)
    def downloadCover(self, pic_url, current_path, song_id=0):
        """下载封面图片到当前歌曲目录"""
        if not current_path:
            self._download_status = "没有当前播放歌曲"
            self.downloadStatusChanged.emit()
            return
        self._download_status = "正在下载封面..."
        self.downloadStatusChanged.emit()
        try:
            result = save_cover_file(song_id, pic_url, current_path)
            if result:
                self._download_status = f"封面已保存: {Path(result).name}"
                if 0 <= self._current_index < len(self._songs):
                    self._songs[self._current_index]["image"] = result
                    self.songChanged.emit(self._current_index)
            else:
                self._download_status = "未找到封面"
        except Exception as e:
            self._download_status = f"下载封面失败: {e}"
        self.downloadStatusChanged.emit()

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

    # ========== ffplay 进程管理 ==========

    def _kill_process(self):
        """终止当前 ffplay 进程并清理资源"""
        if self._process:
            # Disconnect the finished signal to prevent side effects
            try:
                self._process.finished.disconnect(self._on_ffplay_finished)
            except:
                pass
            if self._process.state() == QProcess.Running:
                pid = self._process.processId()
                if pid > 0:
                    # 先恢复进程（如果被 SIGSTOP 暂停了），确保 SIGTERM 能送达
                    try:
                        os.kill(pid, signal.SIGCONT)
                    except:
                        pass
                self._process.terminate()
                if not self._process.waitForFinished(500):
                    self._process.kill()
                    self._process.waitForFinished(300)
        self._process = None

    def _check_pa_available(self):
        """检查系统是否有可用的 PulseAudio/PipeWire"""
        try:
            result = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=3)
            return result.returncode == 0
        except:
            return False

    def _find_sink_input_id(self, pid):
        """查找指定 pid 对应的 PulseAudio sink-input index，找不到返回 None"""
        try:
            result = subprocess.run(
                ["pactl", "-f", "json", "list", "sink-inputs"],
                capture_output=True, text=True, timeout=5
            )
            inputs = json.loads(result.stdout) if result.stdout.strip() else []
            for inp in inputs:
                props = inp.get("properties", {})
                if props.get("application.process.id") == str(pid):
                    return inp["index"]
        except Exception:
            pass
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
            subprocess.run(
                ["pactl", "set-sink-input-volume", str(sink_id), str(pa_vol)],
                capture_output=True, timeout=5
            )
            return True
        except Exception:
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
        if process_ref.state() != QProcess.Running:
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
        self._process.waitForStarted(500)
        self._process.finished.connect(self._on_ffplay_finished)

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

        # 异步获取时长，避免阻塞 UI
        self._duration = 0.0
        self.durationChanged.emit(self._duration)
        QTimer.singleShot(0, lambda: self._async_load_metadata(filepath))

        self._seek_base = seek_to
        self._play_start_time = self._get_current_time()
        self._total_paused_duration = 0.0
        self._position_timer.start()

    def _async_load_metadata(self, filepath):
        """异步加载歌曲元数据（时长和歌词），避免阻塞 UI 线程"""
        self._duration = self._get_duration(filepath)
        self.durationChanged.emit(self._duration)
        self._load_lyrics()

    def _get_current_time(self):
        """获取当前系统时间戳（用于计算播放进度）"""
        return time.time()

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
        except:
            pass
        return 0.0

    def _update_position(self):
        """定时更新播放进度位置，触发信号通知 QML"""
        if self._state == "playing":
            elapsed = self._get_current_time() - self._play_start_time - self._total_paused_duration
            self._position = min(self._seek_base + elapsed, self._duration)
            self.positionChanged.emit(self._position)
            self._update_lyric_index()

    def _on_ffplay_finished(self, exit_code, exit_status):
        """ffplay 进程结束时自动切换到下一曲"""
        self._position_timer.stop()
        # If the process was killed by us (switching songs), don't auto-advance
        if exit_status == QProcess.NormalExit and self._state != "stopped":
            if self._position >= self._duration - 1.0:
                self.next()

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
        """暂停当前播放（通过 SIGSTOP 暂停 ffplay 进程）"""
        if self._state != "playing":
            return
        if self._process and self._process.state() == QProcess.Running:
            pid = self._process.processId()
            if pid > 0:
                os.kill(pid, signal.SIGSTOP)
            self._pause_time = self._get_current_time()
            self._state = "paused"
            self.stateChanged.emit("paused")
            self._position_timer.stop()

    @Slot()
    def resume(self):
        """恢复播放（通过 SIGCONT 继续 ffplay 进程）"""
        if self._state != "paused":
            return
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
                    pos = min(self._seek_base + elapsed, self._duration)
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
        self._current_index = (self._current_index + delta) % len(self._songs)
        self.songChanged.emit(self._current_index)
        self._position = 0.0
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
        self._position = max(0.0, min(pos_seconds, self._duration))
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
                # Wait for process to start, then pause
                if self._process:
                    self._process.waitForStarted(500)
                    pid = self._process.processId()
                    if pid > 0:
                        os.kill(pid, signal.SIGSTOP)

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
        """返回当前歌曲的封面图片路径（QML 可绑定）"""
        if 0 <= self._current_index < len(self._songs):
            song = self._songs[self._current_index]
            if song["image"]:
                return song["image"]
            # Lazy extract embedded image on demand
            return extract_embedded_image(song["path"])
        return ""

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
        """加载当前歌曲的歌词，优先加载外部 LRC 文件，其次读取嵌入元数据"""
        self._lyrics = []
        self._current_lyric_index = -1
        if 0 <= self._current_index < len(self._songs):
            song_path = self._songs[self._current_index]["path"]
            # Try external LRC file first
            lrc_path = find_matching_lyrics(song_path)
            if lrc_path:
                self._lyrics = parse_lrc(lrc_path)
            else:
                # Fall back to embedded lyrics
                self._lyrics = extract_embedded_lyrics(song_path)
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
        # 类型转换：字符串 → 正确的类型
        if value.lower() == "true":
            settings[key] = True
        elif value.lower() == "false":
            settings[key] = False
        else:
            try:
                if "." in value:
                    settings[key] = float(value)
                else:
                    settings[key] = int(value)
            except ValueError:
                settings[key] = value
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


# ========== 应用入口 ==========


def _setup_signal_handlers(player):
    """注册信号处理器，确保在异常退出时清理 ffplay 子进程。

    当进程收到 SIGINT (Ctrl+C)、SIGTERM (kill)、SIGSEGV (段错误) 等信号时，
    先调用 player.cleanup() 终止 ffplay 子进程，再退出。
    """
    def _signal_handler(signum, frame):
        player.cleanup()
        # 恢复默认信号处理并重新发送信号，让进程以正常方式退出
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _signal_handler)

    # SIGSEGV 比较特殊：处理函数中不能安全地做太多事，但至少尝试终止子进程
    # 注意：SIGSEGV 处理函数中调用 Python 代码可能不安全，但比什么都不做好
    signal.signal(signal.SIGSEGV, _signal_handler)


class AppBridge(QObject):
    """桥接对象，向 QML 暴露 Python 侧的退出等功能"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quit_callback = None

    def setQuitCallback(self, callback):
        self._quit_callback = callback

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
