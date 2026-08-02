"""
抖音无水印视频下载工具模块 (douyin_download)

用法:
    from douyin_download import download_douyin_video
    result = download_douyin_video("https://v.douyin.com/xxxx/")

返回 dict:
    {"ok": True, "path": "/path/to/video.mp4", "size_mb": 2.65, "title": "...", "author": "..."}
    或 {"ok": False, "error": "错误描述"}
"""

import re
import os
import requests
from typing import Optional

# 默认保存目录
DEFAULT_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# 手机浏览器 UA
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
REFERER = "https://www.iesdouyin.com/"

HEADERS = {
    "User-Agent": MOBILE_UA,
    "Referer": REFERER,
}


def _resolve_short_url(short_url: str) -> Optional[str]:
    """解析抖音短链接，获取真实页面 URL。"""
    try:
        resp = requests.get(short_url, headers=HEADERS, allow_redirects=True, timeout=15)
        if resp.status_code == 200:
            return resp.url
    except requests.RequestException as e:
        return None
    return None


def _extract_video_info(page_url: str) -> Optional[dict]:
    """从页面 URL 提取 video_id 和作品信息。

    返回:
        {"video_id": "xxx", "aweme_id": "xxx", "author": "xxx", "title": "xxx"}
    """
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        text = resp.text
    except requests.RequestException:
        return None

    info = {}

    # 从 URL 提取 aweme_id (作品ID)
    m = re.search(r'/video/(\d+)/', page_url)
    if m:
        info["aweme_id"] = m.group(1)

    # 从页面提取 video_id (播放用)
    # 方式1: play_addr 中的 video_id
    m = re.search(r'"uri"\s*:\s*"([a-zA-Z0-9]+)"', text)
    if m:
        info["video_id"] = m.group(1)

    # 方式2: URL 中的 video_id 参数
    if "video_id" not in info:
        m = re.search(r'video_id=([a-zA-Z0-9_]+)', text)
        if m:
            info["video_id"] = m.group(1)

    # 提取作者昵称
    m = re.search(r'"nickname"\s*:\s*"([^"]+)"', text)
    if m:
        raw = m.group(1)
        # 仅当有 \uXXXX 转义时才用 unicode_escape 解码，否则直接取 UTF-8
        info["author"] = raw.encode().decode("unicode_escape") if "\\u" in raw else raw

    # 提取标题/描述
    m = re.search(r'"desc"\s*:\s*"([^"]+)"', text)
    if m:
        raw = m.group(1)
        # 仅当有 \uXXXX 转义时才用 unicode_escape 解码，否则直接取 UTF-8
        info["title"] = raw.encode().decode("unicode_escape") if "\\u" in raw else raw

    if not info.get("video_id"):
        return None

    return info


def download_douyin_video(
    share_url: str,
    save_dir: str = DEFAULT_SAVE_DIR,
    filename: Optional[str] = None,
) -> dict:
    """下载抖音无水印视频主函数。

    Args:
        share_url: 抖音分享短链接 (如 https://v.douyin.com/xxxx/)
        save_dir: 保存目录
        filename: 自定义文件名 (不含后缀), 默认用 aweme_id

    Returns:
        dict: {"ok": True, "path": "...", "size_mb": ..., "title": "...", "author": "..."}
              或 {"ok": False, "error": "..."}
    """
    # Step 1: 解析短链接
    page_url = _resolve_short_url(share_url)
    if not page_url:
        return {"ok": False, "error": "短链接解析失败，无法获取页面地址"}

    # Step 2: 提取 video_id 等信息
    info = _extract_video_info(page_url)
    if not info or "video_id" not in info:
        return {"ok": False, "error": "无法从页面提取 video_id"}

    video_id = info["video_id"]
    aweme_id = info.get("aweme_id", video_id)
    author = info.get("author", "未知作者")
    title = info.get("title", "")

    # Step 3: 构造无水印播放地址 (play 而非 playwm)
    play_url = (
        f"https://aweme.snssdk.com/aweme/v1/play/"
        f"?video_id={video_id}&ratio=720p&line=0"
    )

    # Step 4: 下载视频
    try:
        resp = requests.get(
            play_url,
            headers=HEADERS,
            stream=True,
            timeout=30,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"ok": False, "error": f"视频下载请求失败: {str(e)}"}

    # 检查 Content-Type
    content_type = resp.headers.get("Content-Type", "")
    if "video" not in content_type and "octet-stream" not in content_type:
        return {"ok": False, "error": f"响应不是视频类型: {content_type}"}

    content_length = resp.headers.get("Content-Length")

    # 确定文件名
    if not filename:
        # 用标题前20字或aweme_id
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title)[:20] if title else aweme_id
        filename = safe_title if safe_title else aweme_id

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
        # 清理
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
        "author": author,
        "aweme_id": aweme_id,
        "video_id": video_id,
    }


if __name__ == "__main__":
    # 命令行测试：python douyin_download.py <share_url>
    import sys
    if len(sys.argv) > 1:
        result = download_douyin_video(sys.argv[1])
        if result["ok"]:
            print(f"✅ 下载成功!")
            print(f"   路径: {result['path']}")
            print(f"   大小: {result['size_mb']} MB")
            print(f"   作者: {result['author']}")
            print(f"   标题: {result['title']}")
        else:
            print(f"❌ 下载失败: {result['error']}")
    else:
        print("用法: python douyin_download.py <抖音分享链接>")
