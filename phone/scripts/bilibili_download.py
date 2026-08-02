"""
B站(Bilibili)视频下载工具模块 (bilibili_download)

用法:
    from bilibili_download import download_bilibili_video
    result = download_bilibili_video("https://b23.tv/xxxx/")

返回 dict:
    {"ok": True, "path": "/path/to/video.mp4", "size_mb": 6.33, "title": "...", "bvid": "...", "cid": ...}
    或 {"ok": False, "error": "错误描述"}
"""

import re
import os
import requests
from typing import Optional

# 默认保存目录
DEFAULT_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# 浏览器 UA (B站API要求桌面UA，手机UA会降质/拒绝)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.bilibili.com/"

HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Referer": REFERER,
}


def _resolve_short_url(short_url: str) -> Optional[dict]:
    """解析B站短链接(b23.tv)，返回页面URL和提取的BVID。"""
    try:
        resp = requests.get(short_url, headers=HEADERS, allow_redirects=True, timeout=15)
        if resp.status_code != 200:
            return None
        page_url = resp.url
        m = re.search(r'video/(BV\w+)', page_url)
        if not m:
            return None
        return {"page_url": page_url, "bvid": m.group(1)}
    except requests.RequestException:
        return None


def _get_video_info(bvid: str) -> Optional[dict]:
    """调用B站 view API 获取视频信息(标题/cid/时长)。"""
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("code") != 0 or "data" not in data:
        return None

    v = data["data"]
    return {
        "title": v.get("title", ""),
        "cid": v.get("cid"),
        "duration": v.get("duration", 0),
    }


def _get_play_url(bvid: str, cid: int, qn: int = 80) -> Optional[dict]:
    """调用B站 playurl API 获取视频流下载地址。

    Args:
        qn: 清晰度, 80=1080P, 64=720P, 32=480P, 16=360P
    """
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}"
            f"&qn={qn}&platform=web&otype=json",
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("code") != 0 or "data" not in data:
        return None

    durls = data["data"].get("durl", [])
    if not durls:
        return None

    return {"url": durls[0]["url"], "size": durls[0].get("size", 0)}


def download_bilibili_video(
    share_url: str,
    save_dir: str = DEFAULT_SAVE_DIR,
    filename: Optional[str] = None,
    qn: int = 80,
) -> dict:
    """下载B站视频主函数。

    Args:
        share_url: B站分享短链接 (如 https://b23.tv/xxxx/) 或完整视频URL
        save_dir: 保存目录
        filename: 自定义文件名 (不含后缀), 默认用 BVID
        qn: 清晰度, 80=1080P, 64=720P, 32=480P, 16=360P

    Returns:
        dict: {"ok": True, "path": "...", "size_mb": ..., "title": "...", "bvid": "...", "cid": ...}
              或 {"ok": False, "error": "..."}
    """
    # Step 1: 解析短链接 → 页面URL + BVID
    if "video/" in share_url and "BV" in share_url:
        m = re.search(r'video/(BV\w+)', share_url)
        if m:
            bvid = m.group(1)
        else:
            return {"ok": False, "error": "无法从URL提取BVID"}
    else:
        resolved = _resolve_short_url(share_url)
        if not resolved:
            return {"ok": False, "error": "短链接解析失败，无法获取BVID"}
        bvid = resolved["bvid"]

    # Step 2: 获取视频信息 (标题/cid)
    info = _get_video_info(bvid)
    if not info or not info.get("cid"):
        return {"ok": False, "error": f"获取视频信息失败 (bvid={bvid})"}
    cid = info["cid"]
    title = info.get("title", "")

    # Step 3: 获取视频流下载地址
    play = _get_play_url(bvid, cid, qn)
    if not play:
        return {"ok": False, "error": f"获取播放地址失败 (bvid={bvid}, cid={cid})"}

    # Step 4: 下载视频
    try:
        resp = requests.get(
            play["url"],
            headers=HEADERS,
            stream=True,
            timeout=60,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"ok": False, "error": f"视频下载请求失败: {str(e)}"}

    content_type = resp.headers.get("Content-Type", "")
    if "video" not in content_type and "octet-stream" not in content_type:
        return {"ok": False, "error": f"响应不是视频类型: {content_type}"}

    content_length = resp.headers.get("Content-Length")

    # 确定文件名
    if not filename:
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title)[:30] if title else ""
        filename = safe_title if safe_title else bvid

    save_path = os.path.join(save_dir, f"{filename}.mp4")
    part_path = save_path + ".part"

    # Step 5: 写入 .part 临时文件
    downloaded = 0
    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
    except IOError as e:
        if os.path.exists(part_path):
            os.remove(part_path)
        return {"ok": False, "error": f"文件写入失败: {str(e)}"}

    # 校验 Content-Length
    if content_length and str(downloaded) != content_length:
        os.remove(part_path)
        return {
            "ok": False,
            "error": (
                f"大小校验失败: 下载 {downloaded} 字节, "
                f"声明 {content_length} 字节"
            ),
        }

    # 校验通过，改名
    os.rename(part_path, save_path)

    return {
        "ok": True,
        "path": save_path,
        "size_mb": round(downloaded / 1024 / 1024, 2),
        "title": title,
        "bvid": bvid,
        "cid": cid,
    }
