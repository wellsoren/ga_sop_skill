---
skill: douyin_download
domain: media
version: "2.2"
tags: [douyin, download, video, ttwid, webcdp, android]
cc_quick: "抖音无水印下载: ttwid→detail→SSR→后台webcdp→play; 封装 douyin_download.py; 默认无前台浏览器"
cc_keywords: ["抖音下载", "抖音无水印", "douyin", "v.douyin.com", "抖音视频", "download_douyin_video"]
tools: [code_run]
forbidden_tools: []
tools_mode: lax
---
# 抖音无水印视频下载 SOP (douyin_download)

> 公开分享链 → 无水印 MP4。**2026-08 v2.2**：默认**无前台浏览器**——HTTP 注册 `ttwid` → detail API 为主；SSR 次选；webcdp **background** 仅兜底。

## 一、前置条件

| 依赖 | 说明 |
|------|------|
| `ga/douyin_download.py` | 已封装主通道 + 下载校验 |
| `requests` | HTTP（ttwid 注册 / detail / play / SSR） |
| `webcdp` | **可选兜底**：ttwid+SSR 失败时离屏刷 cookie（`background=True`，不抢主屏） |
| 网络 | 可访问 `ttwid.bytedance.com` / `www.douyin.com` / `aweme.snssdk.com` |

可选：调用方预置 cookie dict（`cookies=`）；或 `use_webcdp=False` 完全禁用浏览器兜底。

## 二、能力总览

| 能力 | 入口 | 说明 |
|------|------|------|
| 一键下载 | `download_douyin_video(url)` | 解析+下载，返回 path/元数据 |
| 只解析 | `resolve_video_info(url)` | 拿 `video_id`/标题/作者，不落盘 |
| 注册 ttwid | `fetch_ttwid()` | HTTP 无 UI，主通道 cookie |
| 取 cookie | `fetch_douyin_cookies(aweme_id)` | webcdp **后台**开完整页，进程内缓存 |

**主链路**（默认无前台）:
```
分享链接/文案
  → _extract_share_url 抽出纯链（整段「复制打开抖音…」杂讯必须先抽）
  → 提取 aweme_id（短链 302 或正则）
  → [1] fetch_ttwid() HTTP 注册 → detail API → play_addr.uri = video_id
  → [2] 失败则 SSR 分享页正则 "uri" / video_id=
  → [3] 再失败才 webcdp.open_url(..., background=True) 刷 cookie → detail
  → https://aweme.snssdk.com/aweme/v1/play/?video_id=...&ratio=720p&line=0
  → .part 写入 → Content-Length 校验 → rename .mp4
```

**说明**: 实测 **仅 ttwid** 即可调通 detail；`__ac_signature` 不再是硬依赖。SSR 不稳，勿单独当唯一通道。
## 三、快速参考

```python
from douyin_download import download_douyin_video

result = download_douyin_video("https://v.douyin.com/xxxx/")
# 或带分享文案的整段字符串；或完整 https://www.douyin.com/video/{aweme_id}

if result["ok"]:
    print(result["path"], result["size_mb"], result["author"], result.get("source"))
else:
    print(result["error"])
```

默认保存目录：脚本同级 `downloads/`（`DEFAULT_SAVE_DIR`，公开版便携路径；本机可改系统相册目录）。

常用参数：`save_dir=` / `filename=` / `ratio="720p"|"1080p"|"540p"` / `cookies={...}` / `use_webcdp=True|False` / `force_cookie_refresh=True`。

返回成功字段：`ok, path, size_mb, title, author, aweme_id, video_id, source`（`source`=`detail_api` 或 `ssr_page`）。

## 四、执行流程

### 4.1 推荐：一键

见「快速参考」。模块会自动：抽链 → aweme_id → **ttwid→detail**（必要时 SSR / 后台 webcdp）→ play 下载。**默认不弹前台浏览器**。

### 4.2 主通道分步（debug）

```python
from douyin_download import (
    _extract_share_url, _extract_aweme_id, _resolve_short_url,
    fetch_ttwid, fetch_douyin_cookies,
    _detail_api, _info_from_detail, _download_play, _extract_video_info_ssr,
)

share = _extract_share_url("复制打开抖音… https://v.douyin.com/xxxx/ 杂讯")
aweme_id = _extract_aweme_id(share) or _extract_aweme_id(_resolve_short_url(share) or "")

# ① 无 UI：HTTP 注册 ttwid（主通道）
ttwid = fetch_ttwid()
detail = _detail_api(aweme_id, {"ttwid": ttwid})
info = _info_from_detail(detail, aweme_id) if detail else None

# ② 失败再 SSR
if not info:
    page = _resolve_short_url(share) or share
    info = _extract_video_info_ssr(page)

# ③ 仍失败才后台 webcdp（不抢主屏；禁开短链）
if not info:
    cookies = fetch_douyin_cookies(aweme_id, force_refresh=True, background=True)
    detail = _detail_api(aweme_id, cookies)
    info = _info_from_detail(detail, aweme_id)

# ④ 无水印下载
_download_play(info["video_id"], save_dir="/path", filename=aweme_id,
               title=info.get("title",""), author=info.get("author",""), aweme_id=aweme_id)
```

detail 请求要点（已写死在模块内）：

- URL: `https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={id}&aid=1128&device_platform=webapp&channel=channel_pc_web&version_code=190500&version_name=19.5.0&os_version=10&screen_width=1290&screen_height=2796`
- Headers: `User-Agent`=Chrome PC；`Cookie` **至少 `ttwid`**（有 `__ac_*` 更好）；`Referer=https://www.douyin.com/video/{aweme_id}`
- 元数据：`desc`→title，`author.nickname`→author，`video.play_addr.uri`→video_id

play 下载 Headers（与旧版一致）：手机 UA + `Referer: https://www.iesdouyin.com/`。

### 4.3 关键禁令 ⚠️

| 禁令 | 说明 |
|------|------|
| ❌ `playwm` | 带水印；必须 `play` |
| ❌ 裸请求无 Headers | play 需手机 UA+ies Referer；detail 需 PC UA+Cookie+视频页 Referer |
| ❌ 直接落盘不校验 | 先 `.part`，对齐 `Content-Length` 再 rename |
| ❌ 把 aweme_id 当 video_id | 短链数字是作品 ID，播放 ID 形如 `v2800fgi...` |
| ❌ webcdp 开短链 | `v.douyin.com` 在手机 webcdp 常「网页无法打开」；只开 `www.douyin.com/video/{aweme_id}` |
| ❌ 默认前台开浏览器 | 兜底必须 `background=True`；主通道用 ttwid，勿一上来就 open_url |
| ❌ 受保护/付费内容 | 仅公开可分享作品 |

### 4.4 典型坑

| 现象 | 原因 | 处理 |
|------|------|------|
| `无法提取 aweme_id` 且输入是整段分享文案 | 未先抽 `https://v.douyin.com/...`，把杂讯当 URL 去 302 | 模块入口已 `_extract_share_url`；手工 debug 也先抽链再 `_resolve_short_url` |
| detail 空 / 无 aweme_detail | 无 cookie 或 ttwid 失效 | `fetch_ttwid(force_refresh=True)`；再失败才后台 webcdp |
| SSR 无 video_id | 分享页已改版 | 走 ttwid→detail，勿死磕正则 |
| 几 KB 文件 | 非 video Content-Type | 查是否误用 playwm/错误 URL |
| webcdp 失败 | 浏览器/虚拟屏未就绪 | 主通道不依赖 webcdp；或外部传入 `cookies=` |
| 500/403 on play | UA/Referer 不对 | 用模块内 `PLAY_HEADERS` |
| 仍弹前台浏览器 | 旧代码/旧进程未 reload | 确认 `fetch_douyin_cookies` 调 `open_url(..., background=True)`；清模块缓存重导 |

### 4.5 已知变化

- 2026-08：ies 分享页 SSR 常「抱歉出错了」；主通道改为 detail API。
- **2026-08 v2.2**：主通道改为 **HTTP ttwid → detail**；webcdp 改为 **background 兜底**，默认不抢前台。
- CDN 域名会变，`play` 入口相对稳定；`allow_redirects=True`。
- cookie/ttwid 进程内缓存；跨进程或失效时 `force_cookie_refresh=True`（当前无磁盘持久化）。

## 五、验证

1. **解析**：`resolve_video_info(url)` → `ok` 且 `source=="detail_api"`，`video_id` 以 `v` 开头。
2. **无 webcdp**：清空 `_COOKIE_CACHE` 后 resolve，打桩 `webcdp.open_url` 应 **0 次调用** 仍成功（ttwid 通道）。
3. **下载**：`download_douyin_video` → `ok`，`size_mb`>0，路径可读。
4. **分享文案**：整段「复制打开抖音… https://v.douyin.com/xxx/ 杂讯」也能解析出同一 `aweme_id`。
5. **对照样本**（曾验证）：
   - aweme `7596191036051117177` → video_id `v2800fgi0000d5lhdsvog65he5al3490`，约 20.32MB
   - aweme `7668275618820656826`（`m_n6VX0Y8-c`）→ `v2800fgi0000d9lit2fog65ho84gtsag`，约 42.68MB，ttwid 无 UI 成功

```python
from douyin_download import resolve_video_info, _extract_share_url, _COOKIE_CACHE

assert _extract_share_url(
    "0.53 复制打开抖音… https://v.douyin.com/XYCSgw7xlLI/ 11/13 b@A.te"
) == "https://v.douyin.com/XYCSgw7xlLI/"

_COOKIE_CACHE.clear()
info = resolve_video_info("https://v.douyin.com/m_n6VX0Y8-c/", use_webcdp=False)
assert info["ok"] and info["video_id"].startswith("v") and info["source"] == "detail_api"
```

## 尊重规则

- 仅下载**公开分享**作品；个人收藏/合理引用，不二次分发盗用；遵守平台规则与版权。
