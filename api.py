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
    url = f"https://music.163.com/api/search/get/?s={encoded}&limit={limit}&type=1&offset=0"
    try:
        resp = requests.post(url, headers=_NETEASE_HEADERS, timeout=10)
        data = resp.json()
    except (requests.RequestException, ValueError):
        # 网络错误或接口被风控返回非 JSON（HTML）时，静默返回空列表
        return []
    if data.get("code") == 200:
        # 注意 .get(key, default) 不防值为 null：result 为 null 时
        # 需要 or {} 兜底，否则 None.get("songs") 会抛 AttributeError
        return (data.get("result") or {}).get("songs") or []
    return []


def _parse_lrc(lrc_text):
    """解析 LRC 文本，返回 [(时间戳秒数, 歌词文本, 原始行), ...]

    - 一行带多个时间标签（如 [00:01.00][00:02.00]text）时，为每个时间戳
      各产出一条记录（此前只取第一个时间戳，其余时间点丢失且残留进文本）；
    - [ti:xxx] 等元数据标签、无法解析的行、空文本行被跳过；
    - 结果按时间戳升序排序（文件本身可能乱序，合并逻辑依赖有序输入）。
    """
    lines = []
    for line in lrc_text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        timestamps = []
        pos = 0
        while pos < len(line) and line[pos] == "[":
            close_bracket = line.find("]", pos)
            if close_bracket == -1:
                timestamps = []
                break
            time_str = line[pos + 1:close_bracket]
            if ":" not in time_str:
                # 元数据标签（[ti:xxx]、[offset:xxx] 等），整行跳过
                timestamps = []
                break
            try:
                minutes, seconds = time_str.split(":")
                timestamps.append(int(minutes) * 60 + float(seconds))
            except ValueError:
                timestamps = []
                break
            pos = close_bracket + 1
        if not timestamps:
            continue
        text = line[pos:].strip()
        if not text:
            continue
        for ts in timestamps:
            lines.append((ts, text, line))
    lines.sort(key=lambda x: x[0])
    return lines


# 翻译行与原文行时间戳的最大允许偏差（秒）。
# 此前用 0.05s：真实翻译歌词常有 0.1~0.3s 的偏差，导致整条翻译被静默丢弃。
_LRC_MATCH_TOLERANCE = 0.5


def _merge_bilingual_lyric(lrc_text, tlyric_text):
    """合并原歌词和翻译歌词为双语 LRC（时间戳接近的行交替排列）"""
    if not tlyric_text:
        return lrc_text

    lrc_lines = _parse_lrc(lrc_text)
    tlyric_lines = _parse_lrc(tlyric_text)

    if not tlyric_lines:
        return lrc_text
    if not lrc_lines:
        # 原文缺失但翻译存在：直接返回翻译文本，避免合并结果为空串
        return tlyric_text

    result = []
    ti = 0
    last_orig = None
    for ts, text, orig_line in lrc_lines:
        # 多时间标签行被 _parse_lrc 展开成多条记录，同一原文行只追加一次
        if orig_line != last_orig:
            result.append(orig_line)
            last_orig = orig_line
        while ti < len(tlyric_lines) and tlyric_lines[ti][0] < ts - _LRC_MATCH_TOLERANCE:
            ti += 1
        if ti < len(tlyric_lines) and abs(tlyric_lines[ti][0] - ts) < _LRC_MATCH_TOLERANCE:
            result.append(tlyric_lines[ti][2])
            ti += 1

    return "\n".join(result)


def get_netease_lyric(song_id):
    """获取歌词文本，有翻译时自动合并为双语 LRC"""
    url = f"https://music.163.com/api/song/lyric?os=osx&id={song_id}&lv=-1&kv=-1&tv=-1"
    try:
        resp = requests.get(url, headers=_NETEASE_HEADERS, timeout=10)
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if data.get("code") != 200:
        return None
    # .get(key, default) 不防值为 null，需要 or {} 兜底
    lrc_text = (data.get("lrc") or {}).get("lyric") or ""
    tlyric_text = (data.get("tlyric") or {}).get("lyric") or ""
    if tlyric_text:
        return _merge_bilingual_lyric(lrc_text, tlyric_text)
    return lrc_text or None


def get_netease_detail(song_id):
    """获取歌曲详情，返回封面 URL"""
    encoded_id = urllib.parse.quote(f"[{song_id}]")
    url = f"https://music.163.com/api/song/detail/?id={song_id}&ids={encoded_id}&csrf_token="
    try:
        resp = requests.get(url, headers=_NETEASE_HEADERS, timeout=10)
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    # songs 为 null 时 for 循环会抛 TypeError，需要 or [] 兜底
    for s in data.get("songs") or []:
        return (s.get("album") or {}).get("picUrl") or ""
    return None


def _fetch_cover_data(pic_url):
    """下载封面图片，返回图片二进制数据"""
    # 网易 CDN 同时支持 http/https，统一走 https 避免明文传输
    if pic_url.startswith("http://"):
        pic_url = "https://" + pic_url[len("http://"):]
    resp = requests.get(pic_url, headers=_NETEASE_HEADERS, timeout=15, stream=True)
    resp.raise_for_status()
    # 限制封面大小（10MB 足够任何封面），防止异常来源拖垮内存
    max_size = 10 * 1024 * 1024
    chunks = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > max_size:
                raise ValueError("cover image too large")
            chunks.append(chunk)
    finally:
        # stream=True 下显式关闭响应，及时归还连接池/释放底层 socket
        resp.close()
    return b"".join(chunks)


# ========== 高层便捷函数（供 UI 调用） ==========


def search_songs(keywords, limit=10):
    """搜索歌曲并返回格式化结果列表（供 UI 直接使用）

    兼容两代接口字段名：新接口 /cloudsearch 返回 ar/al，
    老接口 /api/search/get 返回 artists/album（album 里只有 picId
    没有 picUrl，封面 URL 交给 save_cover_file 用详情接口兜底）。
    """
    results = search_netease(keywords, limit)
    formatted = []
    for s in results:
        artists = s.get("ar") or s.get("artists") or []
        album = s.get("al") or s.get("album") or {}
        formatted.append({
            "id": s.get("id", 0),
            "name": s.get("name") or "",
            "artist": ", ".join((a or {}).get("name") or "" for a in artists),
            "album": album.get("name") or "",
            "picUrl": album.get("picUrl") or "",
            # 网易接口返回毫秒；无该字段时给 0，UI 据此隐藏时长
            "duration": s.get("duration") or 0,
        })
    return formatted


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
    # 按图片魔数决定扩展名，避免把 PNG/BMP/WEBP 封面错误地存成 .jpg
    if img_data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif img_data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif img_data[:2] == b"BM":
        ext = ".bmp"
    elif img_data[:4] == b"RIFF" and img_data[8:12] == b"WEBP":
        ext = ".webp"
    else:
        ext = ".jpg"
    cover_path = save_path.with_suffix(ext)
    # 先写新文件，再清理同名的旧封面（扩展名可能不同，如旧 .jpg 新 .png）：
    # 否则重扫目录时旧文件会按扩展名顺序优先被 find_matching_image 命中，
    # 表现为"封面没更新"。写入失败时不动旧文件。
    cover_path.write_bytes(img_data)
    for old_ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        old_path = save_path.with_suffix(old_ext)
        if old_path != cover_path and old_path.is_file():
            try:
                old_path.unlink()
            except OSError:
                pass
    return str(cover_path)
