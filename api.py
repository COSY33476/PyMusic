'''网易云音乐 API 模块'''

import urllib.parse
from pathlib import Path

import requests


_NETEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://music.163.com/",
}


class NeteaseAPIError(Exception):
    """网易接口不可用（网络异常/被风控/接口变更）。

    与"正常返回但没有结果"区分开：前者向用户展示明确失败提示，
    而不是静默显示"找到 0 首歌曲"让用户误以为程序坏了。
    """


# ========== 底层 API 函数 ==========


def search_netease(keywords, limit=10):
    """搜索歌曲，返回 [{id, name, ar, al}, ...]"""
    encoded = urllib.parse.quote(keywords)
    url = f"https://music.163.com/api/search/get/?s={encoded}&limit={limit}&type=1&offset=0"
    try:
        resp = requests.post(url, headers=_NETEASE_HEADERS, timeout=10)
        data = resp.json()
    except (requests.RequestException, ValueError):
        # 网络错误或接口被风控返回非 JSON（HTML）时抛明确异常，
        # 由上层展示"搜索失败"而不是静默空列表
        raise NeteaseAPIError("网络异常或接口被限制") from None
    if data.get("code") != 200:
        raise NeteaseAPIError("网络异常或接口被限制")
    # 注意 .get(key, default) 不防值为 null：result 为 null 时
    # 需要 or {} 兜底，否则 None.get("songs") 会抛 AttributeError
    return (data.get("result") or {}).get("songs") or []


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
    # 无效/负 id（如 32 位截断的溢出值）直接返回 None：
    # 网易对未知 id 不报错，而是返回 "[00:00.00]暂无歌词" 占位文本，
    # 不能让它被当作真实歌词
    if not song_id or song_id <= 0:
        return None
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
    if not song_id or song_id <= 0:
        return None
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


def _rotate_backup(path):
    """回退保护：把现有文件轮换进 <文件名>.bak1 / <文件名>.bak2，
    最多保留两个旧版本（bak1=上一次，bak2=再上一次），
    供误下载/误覆盖后改名恢复。"""
    if not path.is_file():
        return
    bak1 = path.with_name(path.name + ".bak1")
    bak2 = path.with_name(path.name + ".bak2")
    try:
        if bak2.is_file():
            bak2.unlink()
    except OSError:
        return
    try:
        if bak1.is_file():
            bak1.rename(bak2)
    except OSError:
        return
    try:
        path.rename(bak1)
    except OSError:
        pass


def save_lyric_file(song_id, save_path):
    """下载歌词并保存到文件，返回保存路径，失败返回 None"""
    lyric_text = get_netease_lyric(song_id)
    if not lyric_text:
        return None
    # 兜底：网易对无效 id 返回 "[00:00.00]暂无歌词" 占位文本，
    # 不能把占位内容存成 .lrc 文件
    lines = [l for l in lyric_text.split("\n") if l.strip()]
    if len(lines) == 1 and "暂无歌词" in lines[0]:
        return None
    save_path = Path(save_path)
    lrc_path = save_path.with_suffix(".lrc")
    # 回退保护：已有歌词先备份为 .lrc.bak，防止误下载覆盖无法恢复
    _rotate_backup(lrc_path)
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
    # 回退保护：旧封面（含其它扩展名）改名 .bak 而不是删除，
    # 误下载后可以改名恢复；同时避免重扫目录时旧文件按扩展名
    # 顺序优先被 find_matching_image 命中导致"封面没更新"。
    # 先备份再写：写入失败时旧封面仍在 .bak 里可恢复。
    for old_ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        old_path = save_path.with_suffix(old_ext)
        if old_path != cover_path and old_path.is_file():
            _rotate_backup(old_path)
    _rotate_backup(cover_path)
    cover_path.write_bytes(img_data)
    return str(cover_path)
