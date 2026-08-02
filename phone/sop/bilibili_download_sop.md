---
skill: bilibili_download
domain: media_download
version: "1.0"
tags: [bilibili, b23.tv, 视频下载, BV号, 哔哩哔哩]
cc_quick: "B站视频下载 — 短链接/完整URL → view API取cid → playurl API取流 → .part校验保存"
cc_keywords: ["下载B站", "bilibili下载", "哔哩哔哩下载", "b23.tv", "BV号", "下载视频"]
---

# B站(Bilibili)视频下载 SOP (bilibili_download)

> 📦 配套脚本: 本仓库 `phone/scripts/bilibili_download.py`（或 GA 根目录 `ga/bilibili_download.py`）

> 场景：用户提供B站分享链接（短链接 `b23.tv/xxx` 或完整 `bilibili.com/video/BVxxx`），需要下载视频到本地。
> 适用范围：公开视频；清晰度最高1080P（qn=80）。

**链路**: `分享链接 → 解析BVID → view API取cid/标题 → playurl API取视频流 → .part临时文件 → 校验Content-Length → 改名保存`

## 一、前置条件

- `bilibili_download.py` (位于 `ga/bilibili_download.py`，已封装核心流程)
- `requests` (环境自带)

## 二、能力总览

| 能力 | 方式 | 说明 |
|------|------|------|
| 一键下载 | `download_bilibili_video(share_url)` | 短链接/完整URL均可 |
| 指定清晰度 | 参数 `qn` | 80=1080P, 64=720P, 32=480P, 16=360P |
| 自定义文件名 | 参数 `filename` | 不含后缀，默认用标题前30字 |

## 三、快速参考

```python
from bilibili_download import download_bilibili_video

result = download_bilibili_video("https://b23.tv/KbmW45g")
if result["ok"]:
    print(f"✅ 下载成功: {result['path']} ({result['size_mb']}MB)")
    print(f"   标题: {result['title']}")
else:
    print(f"❌ 失败: {result['error']}")
```

返回字段:

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 是否成功 |
| `path` | str | 保存路径 |
| `size_mb` | float | 文件大小(MB) |
| `title` | str | 视频标题 |
| `bvid` | str | 视频BV号 |
| `cid` | int | 视频CID |

## 四、执行流程

### 方案A：一键调用（推荐）

见上方快速参考。

### 方案B：手动分步（debug/定制用）

#### Step 1: 解析短链接 → 提取BVID
```python
import re, requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

# b23.tv 短链接必须跟随302
resp = requests.get("https://b23.tv/xxx/", headers=HEADERS, allow_redirects=True, timeout=15)
m = re.search(r'video/(BV\w+)', resp.url)
bvid = m.group(1)  # 如 BV1Az3p6NE3Y
```

#### Step 2: view API 取 cid + 标题
```python
info_resp = requests.get(
    f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
    headers=HEADERS, timeout=15,
).json()
assert info_resp["code"] == 0
cid = info_resp["data"]["cid"]
title = info_resp["data"]["title"]
```

#### Step 3: playurl API 取视频流地址
```python
play_resp = requests.get(
    f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80&platform=web&otype=json",
    headers=HEADERS, timeout=15,
).json()
video_url = play_resp["data"]["durl"][0]["url"]
size = play_resp["data"]["durl"][0]["size"]
```

#### Step 4-5: 下载 + .part校验
```python
resp = requests.get(video_url, headers=HEADERS, stream=True, timeout=60, allow_redirects=True)
content_length = resp.headers.get("Content-Length")

part_path = "video.part"
downloaded = 0
with open(part_path, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        if chunk:
            f.write(chunk)
            downloaded += len(chunk)

# 校验后改名
if content_length and str(downloaded) != content_length:
    os.remove(part_path)
    raise ValueError(f"大小不匹配: 下载{downloaded} vs 声明{content_length}")
os.rename(part_path, part_path.replace(".part", ".mp4"))
```

## 五、验证

- ✅ 返回 `{"ok": True, ...}` 且 `path` 存在
- ✅ `size_mb` 与 playurl API 返回的 `size` 基本一致（本次实测 6.33MB vs 6.33MB）
- ✅ 文件头为 `ftyp`（MP4格式）：`head -c 12 file.mp4` 含 `ftyp`

## 关键禁令 ⚠️

| 禁令 | 说明 |
|------|------|
| ❌ 禁不用 Referer | B站CDN防盗链，不带 `Referer: https://www.bilibili.com/` 会403 |
| ❌ 禁手机UA调API | 用手机UA请求API可能降质/拒绝，用桌面Chrome UA |
| ❌ 禁直接保存 | 必须先写 `.part` 临时文件，校验 `Content-Length` 后再 rename |
| ❌ 禁从 b23.tv 直接猜BVID | 必须 `allow_redirects=True` 跟随302后从最终URL提取 |
| ❌ 禁下载会员/付费内容 | 仅下载有权查看和分享的公开视频；qn>80(如4K)需登录+大会员 |
| ❌ 禁 webcdp 打开 b23.tv 长链处理 | 直接Python requests 即可，无需GUI浏览器 |

## 典型坑 & 排查

| 现象 | 原因 | 解决 |
|------|------|------|
| API返回 code=-412 | 请求被风控(频率过高/UA异常) | 加Cookie或等待；检查UA是否桌面版 |
| playurl 返回空 durl | 该清晰度需登录/会员 | 降 qn 重试（如 qn=32） |
| 下载403 | CDN防盗链 | 确保下载时也带 Referer 头 |
| 短链接解析失败 | 302未跟随 | `allow_redirects=True` |
| 下载只有几KB | 返回的是错误JSON/页面 | 检查 Content-Type 应为 video/mp4 |
| 只有视频没音频 | B站部分清晰度分离音视频流 | playurl `durl` 为空时改用 `dash` 方案(不在本SOP范围) |

## 已知变化 & 适配

- B站CDN域名会变（upos-sz-mirrorbd / upos-bvc-mirrorpu / upos-sz-mirrorcos 等），但 `playurl` API 入口不变
- `playurl` API 返回的URL带时效签名（`e=`参数），需尽快下载，过期需重新获取
- `qn` 参数对照: 16=360P, 32=480P, 64=720P, 80=1080P, 112=1080P+, 116=1080P60, 120=4K(需登录)
- 分P视频（多P）取 `durl` 列表，本封装默认取第1P；完整P列表在 view API `data.pages` 中

## 尊重规则

- 仅下载**公开分享**的B站视频
- 仅用于个人收藏或合理引用，不用于二次分发/盗用
- 尊重作者版权，遵守平台规则
