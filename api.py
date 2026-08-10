'''网易云音乐 API 模块'''

import urllib.parse
from pathlib import Path

import requests


_NETEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://music.163.com/",
}


# ========== 底层 API 函数 ==========


def search_netease(keywords, limit=10):
    """搜索歌曲，返回 [{id, name, ar, al}, ...]"""
    encoded = urllib.parse.quote(keywords)
    url = f"http://music.163.com/api/search/get/?s={encoded}&limit={limit}&type=1&offset=0"
    resp = requests.post(url, headers=_NETEASE_HEADERS, timeout=10)
    data = resp.json()
    if data.get("code") == 200:
        return data.get("result", {}).get("songs", [])
    return []


def _parse_lrc(lrc_text):
    """解析 LRC 文本，返回 [(时间戳秒数, 歌词文本, 原始行), ...]"""
    lines = []
    for line in lrc_text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        close_bracket = line.find("]")
        if close_bracket == -1:
            continue
        time_str = line[1:close_bracket]
        if ":" not in time_str:
            continue
        try:
            minutes, seconds = time_str.split(":")
            timestamp = int(minutes) * 60 + float(seconds)
            text = line[close_bracket + 1:].strip()
            lines.append((timestamp, text, line))
        except ValueError:
            continue
    return lines


def _merge_bilingual_lyric(lrc_text, tlyric_text):
    """合并原歌词和翻译歌词为双语 LRC（相同时间戳交替排列）"""
    if not tlyric_text:
        return lrc_text

    lrc_lines = _parse_lrc(lrc_text)
    tlyric_lines = _parse_lrc(tlyric_text)

    if not tlyric_lines:
        return lrc_text

    result = []
    ti = 0
    for ts, text, orig_line in lrc_lines:
        result.append(orig_line)
        while ti < len(tlyric_lines) and tlyric_lines[ti][0] < ts - 0.05:
            ti += 1
        if ti < len(tlyric_lines) and abs(tlyric_lines[ti][0] - ts) < 0.05:
            result.append(tlyric_lines[ti][2])
            ti += 1

    return "\n".join(result)


def get_netease_lyric(song_id):
    """获取歌词文本，有翻译时自动合并为双语 LRC"""
    url = f"http://music.163.com/api/song/lyric?os=osx&id={song_id}&lv=-1&kv=-1&tv=-1"
    resp = requests.get(url, headers=_NETEASE_HEADERS, timeout=10)
    data = resp.json()
    if data.get("code") != 200:
        return None
    lrc_text = data.get("lrc", {}).get("lyric", "")
    tlyric_text = data.get("tlyric", {}).get("lyric", "")
    if tlyric_text:
        return _merge_bilingual_lyric(lrc_text, tlyric_text)
    return lrc_text or None


def get_netease_detail(song_id):
    """获取歌曲详情，返回封面 URL"""
    encoded_id = urllib.parse.quote(f"[{song_id}]")
    url = f"http://music.163.com/api/song/detail/?id={song_id}&ids={encoded_id}&csrf_token="
    resp = requests.get(url, headers=_NETEASE_HEADERS, timeout=10)
    data = resp.json()
    for s in data.get("songs", []):
        return s.get("album", {}).get("picUrl", "")
    return None


def _fetch_cover_data(pic_url):
    """下载封面图片，返回图片二进制数据"""
    resp = requests.get(pic_url, headers=_NETEASE_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.content


# ========== 高层便捷函数（供 UI 调用） ==========


def search_songs(keywords, limit=10):
    """搜索歌曲并返回格式化结果列表（供 UI 直接使用）"""
    results = search_netease(keywords, limit)
    return [
        {
            "id": s.get("id", 0),
            "name": s.get("name", ""),
            "artist": ", ".join(a.get("name", "") for a in s.get("ar", [])),
            "album": s.get("al", {}).get("name", ""),
            "picUrl": s.get("al", {}).get("picUrl", ""),
        }
        for s in results
    ]


def save_lyric_file(song_id, save_path):
    """下载歌词并保存到文件，返回保存路径，失败返回 None"""
    lyric_text = get_netease_lyric(song_id)
    if not lyric_text:
        return None
    save_path = Path(save_path)
    lrc_path = save_path.with_suffix(".lrc")
    lrc_path.write_text(lyric_text, encoding="utf-8")
    return str(lrc_path)


def save_cover_file(song_id, pic_url, save_path):
    """下载封面并保存到文件，返回保存路径，失败返回 None"""
    if not pic_url and song_id:
        pic_url = get_netease_detail(song_id)
    if not pic_url:
        return None
    img_data = _fetch_cover_data(pic_url)
    save_path = Path(save_path)
    cover_path = save_path.with_suffix(".jpg")
    cover_path.write_bytes(img_data)
    return str(cover_path)
