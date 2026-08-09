"""
抖音无水印视频下载 (douyin_download)

主通道(2026-08 起, 默认无前台浏览器):
  短链/分享文案 → aweme_id
    → [1] HTTP 注册 ttwid → detail API
    → [2] SSR 分享页正则（不稳，作次选）
    → [3] webcdp background 刷 cookie → detail（离屏，不抢主屏）
    → play 无水印下载

用法:
    from douyin_download import download_douyin_video
    result = download_douyin_video("https://v.douyin.com/xxxx/")
    # 也支持整段分享文案（自动抽 v.douyin.com / douyin.com / iesdouyin.com 链接）
    result = download_douyin_video("0.53 复制打开抖音… https://v.douyin.com/xxxx/ …")
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

DEFAULT_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# 下载 play 流用手机 UA + iesdouyin Referer（与旧 SOP 一致）
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
IES_REFERER = "https://www.iesdouyin.com/"
PLAY_HEADERS = {"User-Agent": MOBILE_UA, "Referer": IES_REFERER}

# detail API 用 PC Chrome UA（实测成功参数）
PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

COOKIE_NAMES = (
    "s_v_web_id",
    "ttwid",
    "msToken",
    "odin_tt",
    "__ac_nonce",
    "__ac_signature",
    "__ac_referer",
    "sid_tt",
    "sessionid",
    "passport_csrf_token",
    "bd_ticket_guard_client_data",
)

_COOKIE_CACHE: Dict[str, str] = {}


def _extract_share_url(text_or_url: str) -> str:
    """从整段分享文案中抽出抖音 URL；已是纯链则原样返回。

    解决：用户粘贴「复制打开抖音... https://v.douyin.com/xxx/ 杂讯」时，
    _resolve_short_url 把整段当 URL 请求会失败。
    """
    if not text_or_url:
        return text_or_url
    text = text_or_url.strip()
    # 优先匹配常见抖音域名（短链/完整页/ies 分享页）
    pats = (
        r"https?://v\.douyin\.com/[A-Za-z0-9._~-]+/?",
        r"https?://(?:www\.)?douyin\.com/[^\s]+",
        r"https?://(?:www\.)?iesdouyin\.com/[^\s]+",
    )
    for pat in pats:
        m = re.search(pat, text)
        if m:
            return m.group(0).rstrip(".,，。；;）)】]>\"'")
    # 无 http 前缀的 v.douyin.com 短链
    m = re.search(r"(?<![\w./])v\.douyin\.com/[A-Za-z0-9._~-]+/?", text)
    if m:
        return "https://" + m.group(0).rstrip(".,，。；;）)】]>\"'")
    return text


def _resolve_short_url(share_url: str) -> Optional[str]:
    """短链/分享链 302 到最终页，拿 aweme_id 用。"""
    try:
        resp = requests.get(
            share_url,
            headers={"User-Agent": MOBILE_UA, "Referer": IES_REFERER},
            allow_redirects=True,
            timeout=15,
        )
        return resp.url
    except requests.RequestException:
        return None


def _extract_aweme_id(text_or_url: str) -> Optional[str]:
    """从 URL / 分享文案中提取 aweme_id。"""
    if not text_or_url:
        return None
    for pat in (
        r"/video/(\d{6,})",
        r"modal_id=(\d{6,})",
        r"aweme_id=(\d{6,})",
        r"(?:note|share)/(\d{6,})",
        r"(?<!\d)(\d{19})(?!\d)",  # 常见 19 位作品 id
    ):
        m = re.search(pat, text_or_url)
        if m:
            return m.group(1)
    return None


def _filter_douyin_cookies(raw: Any) -> Dict[str, str]:
    """从 webcdp.web_cookies() 列表/字典中筛出 douyin 相关 cookie。"""
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        # 可能是 {name: value} 或 {name: {value, domain...}}
        for k, v in raw.items():
            if isinstance(v, dict):
                name = v.get("name") or k
                val = v.get("value")
                dom = (v.get("domain") or "").lower()
            else:
                name, val, dom = k, v, ""
            if val is None:
                continue
            if (
                "douyin" in dom
                or "iesdouyin" in dom
                or name in COOKIE_NAMES
            ):
                out[str(name)] = str(val)
        return out

    if isinstance(raw, list):
        for c in raw:
            if not isinstance(c, dict):
                continue
            name = c.get("name") or ""
            val = c.get("value")
            dom = (c.get("domain") or "").lower()
            if val is None or not name:
                continue
            if (
                "douyin" in dom
                or "iesdouyin" in dom
                or name in COOKIE_NAMES
            ):
                out[name] = str(val)
    return out


def _cookie_header(cookies: Dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def _merge_cookie_cache(cookies: Dict[str, str]) -> Dict[str, str]:
    """合并进进程缓存并返回完整副本。"""
    global _COOKIE_CACHE
    if cookies:
        _COOKIE_CACHE.update({k: v for k, v in cookies.items() if v})
    return dict(_COOKIE_CACHE)


def fetch_ttwid(*, force_refresh: bool = False) -> Optional[str]:
    """HTTP 注册 ttwid（无浏览器）。实测仅 ttwid 即可调通 detail API。"""
    global _COOKIE_CACHE
    if not force_refresh and _COOKIE_CACHE.get("ttwid"):
        return _COOKIE_CACHE["ttwid"]
    try:
        resp = requests.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            headers={
                "User-Agent": PC_UA,
                "Content-Type": "application/json",
            },
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.ixigua.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True,
            },
            timeout=15,
        )
    except requests.RequestException:
        return None
    ttwid = resp.cookies.get("ttwid") or ""
    if not ttwid:
        m = re.search(r"ttwid=([^;,\s]+)", resp.headers.get("Set-Cookie", "") or "")
        ttwid = m.group(1) if m else ""
    if ttwid:
        _merge_cookie_cache({"ttwid": ttwid})
        return ttwid
    return None


def fetch_douyin_cookies(
    aweme_id: str,
    *,
    force_refresh: bool = False,
    wait_sec: float = 3.5,
    background: bool = True,
) -> Dict[str, str]:
    """用 webcdp 打开完整视频页获取 __ac_*/ttwid 等 cookie。

    禁开短链(v.douyin.com)；必须开 www.douyin.com/video/{aweme_id}。
    默认 background=True：离屏虚拟屏，不抢主屏前台。
    """
    global _COOKIE_CACHE
    if not force_refresh and _COOKIE_CACHE:
        # 至少要有签名相关字段才复用
        if _COOKIE_CACHE.get("__ac_signature") or _COOKIE_CACHE.get("ttwid"):
            return dict(_COOKIE_CACHE)

    import webcdp  # 本机 PATH 已含

    url = f"https://www.douyin.com/video/{aweme_id}"
    # background=True 不占主屏；shot=False 避免多余截图
    webcdp.open_url(url, background=background, shot=False)
    time.sleep(wait_sec)
    raw = webcdp.web_cookies()
    cookies = _filter_douyin_cookies(raw)
    if cookies:
        _COOKIE_CACHE = dict(cookies)
    return cookies


def _detail_api(aweme_id: str, cookies: Dict[str, str]) -> Optional[dict]:
    """调 web detail API，返回 aweme_detail dict 或 None。"""
    if not cookies:
        return None
    detail_url = (
        f"https://www.douyin.com/aweme/v1/web/aweme/detail/"
        f"?aweme_id={aweme_id}"
        f"&aid=1128&device_platform=webapp&channel=channel_pc_web"
        f"&version_code=190500&version_name=19.5.0"
        f"&os_version=10&screen_width=1290&screen_height=2796"
    )
    headers = {
        "User-Agent": PC_UA,
        "Cookie": _cookie_header(cookies),
        "Referer": f"https://www.douyin.com/video/{aweme_id}",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        r = requests.get(detail_url, headers=headers, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    detail = data.get("aweme_detail")
    if not detail:
        return None
    return detail


def _info_from_detail(detail: dict, aweme_id: str) -> Optional[dict]:
    video = detail.get("video") or {}
    play_addr = video.get("play_addr") or {}
    video_id = play_addr.get("uri")
    if not video_id:
        # 兜底 bit_rate
        for br in video.get("bit_rate") or []:
            uri = (br.get("play_addr") or {}).get("uri")
            if uri:
                video_id = uri
                break
    if not video_id:
        return None
    author = (detail.get("author") or {}).get("nickname") or "未知作者"
    title = detail.get("desc") or ""
    return {
        "video_id": video_id,
        "aweme_id": str(detail.get("aweme_id") or aweme_id),
        "author": author,
        "title": title,
        "source": "detail_api",
    }


def _extract_video_info_ssr(page_url: str) -> Optional[dict]:
    """旧通道：分享页 SSR 正则提取（多数已失效，仅 fallback）。"""
    try:
        resp = requests.get(
            page_url,
            headers={"User-Agent": MOBILE_UA, "Referer": IES_REFERER},
            timeout=15,
        )
        text = resp.text
    except requests.RequestException:
        return None

    info: Dict[str, Any] = {}
    m = re.search(r"/video/(\d+)/", page_url)
    if m:
        info["aweme_id"] = m.group(1)

    m = re.search(r'"uri"\s*:\s*"([a-zA-Z0-9]+)"', text)
    if m:
        info["video_id"] = m.group(1)
    if "video_id" not in info:
        m = re.search(r"video_id=([a-zA-Z0-9_]+)", text)
        if m:
            info["video_id"] = m.group(1)

    m = re.search(r'"nickname"\s*:\s*"([^"]+)"', text)
    if m:
        raw = m.group(1)
        info["author"] = (
            raw.encode().decode("unicode_escape") if "\\u" in raw else raw
        )
    m = re.search(r'"desc"\s*:\s*"([^"]+)"', text)
    if m:
        raw = m.group(1)
        info["title"] = (
            raw.encode().decode("unicode_escape") if "\\u" in raw else raw
        )

    if not info.get("video_id"):
        return None
    info["source"] = "ssr_page"
    return info


def resolve_video_info(
    share_url: str,
    *,
    cookies: Optional[Dict[str, str]] = None,
    force_cookie_refresh: bool = False,
    use_webcdp: bool = True,
) -> dict:
    """解析分享链接/分享文案 → video_id/元数据。

    优先级（默认不抢前台）:
      1) 外部 cookies / 缓存 / HTTP ttwid → detail API
      2) SSR 分享页
      3) webcdp background 刷 cookie → detail

    Returns:
        成功: {"ok": True, "video_id", "aweme_id", "author", "title", "source", ...}
        失败: {"ok": False, "error": "..."}
    """
    # 0) 整段分享文案先抽 URL（否则 _resolve_short_url 会把杂讯当 URL）
    share_url = _extract_share_url(share_url)

    # 1) aweme_id
    aweme_id = _extract_aweme_id(share_url)
    page_url = None
    if not aweme_id:
        page_url = _resolve_short_url(share_url)
        if page_url:
            aweme_id = _extract_aweme_id(page_url)
    if not aweme_id:
        # 再试一次 resolve（share_url 已是完整链时）
        page_url = page_url or _resolve_short_url(share_url)
        if page_url:
            aweme_id = _extract_aweme_id(page_url)
    if not aweme_id:
        return {"ok": False, "error": "无法提取 aweme_id（请确认是抖音分享链接）"}

    webcdp_err = None
    ck: Dict[str, str] = {}

    # 2a) 外部 cookies 优先
    if cookies:
        ck = _merge_cookie_cache(dict(cookies))
    # 2b) 进程缓存（含历史 ttwid / webcdp 结果）
    elif _COOKIE_CACHE and (
        _COOKIE_CACHE.get("ttwid") or _COOKIE_CACHE.get("__ac_signature")
    ):
        if force_cookie_refresh:
            ck = {}
        else:
            ck = dict(_COOKIE_CACHE)

    # 2c) HTTP 注册 ttwid（无 UI，主通道）
    if not ck.get("ttwid") or force_cookie_refresh:
        ttwid = fetch_ttwid(force_refresh=force_cookie_refresh)
        if ttwid:
            ck = _merge_cookie_cache({**ck, "ttwid": ttwid})

    # 2d) detail API（ttwid 通常已够）
    detail = _detail_api(aweme_id, ck) if ck else None
    if detail:
        info = _info_from_detail(detail, aweme_id)
        if info:
            info["ok"] = True
            return info

    # 3) SSR 分享页（无 UI）
    if not page_url:
        page_url = _resolve_short_url(share_url) or share_url
    ssr = _extract_video_info_ssr(page_url)
    if ssr and ssr.get("video_id"):
        ssr.setdefault("aweme_id", aweme_id)
        ssr["ok"] = True
        return ssr

    # 4) webcdp 离屏刷 cookie 再试 detail（最后手段，不抢前台）
    if use_webcdp:
        try:
            ck = fetch_douyin_cookies(
                aweme_id,
                force_refresh=True,
                background=True,
            )
            detail = _detail_api(aweme_id, ck) if ck else None
            if detail:
                info = _info_from_detail(detail, aweme_id)
                if info:
                    info["ok"] = True
                    return info
        except Exception as e:
            webcdp_err = str(e)

    err = "detail API 与 SSR 均无法提取 video_id"
    if webcdp_err:
        err += f"（webcdp: {webcdp_err}）"
    if not ck:
        err += "（无有效 douyin cookie；可传 cookies= 或允许 use_webcdp 后台刷新）"
    return {"ok": False, "error": err, "aweme_id": aweme_id}


def _download_play(
    video_id: str,
    *,
    save_dir: str,
    filename: str,
    title: str = "",
    author: str = "",
    aweme_id: str = "",
    ratio: str = "720p",
) -> dict:
    """无水印 play 下载 + .part 校验。"""
    play_url = (
        f"https://aweme.snssdk.com/aweme/v1/play/"
        f"?video_id={video_id}&ratio={ratio}&line=0"
    )
    try:
        resp = requests.get(
            play_url,
            headers=PLAY_HEADERS,
            stream=True,
            timeout=60,
            allow_redirects=True,
        )
    except requests.RequestException as e:
        return {"ok": False, "error": f"视频下载请求失败: {e}"}

    content_type = resp.headers.get("Content-Type", "")
    if "video" not in content_type and "octet-stream" not in content_type:
        return {"ok": False, "error": f"响应不是视频类型: {content_type}"}

    content_length = resp.headers.get("Content-Length")
    save_path = os.path.join(save_dir, f"{filename}.mp4")
    part_path = save_path + ".part"

    downloaded = 0
    try:
        os.makedirs(save_dir, exist_ok=True)
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
    except OSError as e:
        if os.path.exists(part_path):
            os.remove(part_path)
        return {"ok": False, "error": f"文件写入失败: {e}"}

    if content_length and str(downloaded) != content_length:
        os.remove(part_path)
        return {
            "ok": False,
            "error": (
                f"大小校验失败: 下载 {downloaded} 字节, "
                f"声明 {content_length} 字节"
            ),
        }

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


def download_douyin_video(
    share_url: str,
    save_dir: str = DEFAULT_SAVE_DIR,
    filename: Optional[str] = None,
    *,
    ratio: str = "720p",
    cookies: Optional[Dict[str, str]] = None,
    use_webcdp: bool = True,
    force_cookie_refresh: bool = False,
) -> dict:
    """下载抖音无水印视频。

    Args:
        share_url: 分享短链或完整视频 URL / 含链接的分享文案
        save_dir: 保存目录
        filename: 自定义文件名(无后缀)；默认标题前20字或 aweme_id
        ratio: 720p/1080p/540p
        cookies: 可选预置 cookie dict（跳过/减少 webcdp）
        use_webcdp: ttwid+SSR 失败后是否允许 webcdp 后台刷 cookie（默认 True；不抢前台）
        force_cookie_refresh: 强制刷新 ttwid/cookie

    Returns:
        {"ok": True, "path", "size_mb", "title", "author", "aweme_id", "video_id", "source"}
        或 {"ok": False, "error": "..."}
    """
    info = resolve_video_info(
        share_url,
        cookies=cookies,
        force_cookie_refresh=force_cookie_refresh,
        use_webcdp=use_webcdp,
    )
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error", "解析失败")}

    video_id = info["video_id"]
    aweme_id = info.get("aweme_id") or video_id
    author = info.get("author") or "未知作者"
    title = info.get("title") or ""

    if not filename:
        safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[:20] if title else ""
        filename = safe_title or str(aweme_id)

    result = _download_play(
        video_id,
        save_dir=save_dir,
        filename=filename,
        title=title,
        author=author,
        aweme_id=str(aweme_id),
        ratio=ratio,
    )
    if result.get("ok"):
        result["source"] = info.get("source", "unknown")
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        result = download_douyin_video(sys.argv[1])
        if result.get("ok"):
            print("✅ 下载成功!")
            print(f"   路径: {result['path']}")
            print(f"   大小: {result['size_mb']} MB")
            print(f"   作者: {result['author']}")
            print(f"   标题: {result['title']}")
            print(f"   通道: {result.get('source')}")
        else:
            print(f"❌ 下载失败: {result.get('error')}")
    else:
        print("用法: python douyin_download.py <抖音分享链接>")
