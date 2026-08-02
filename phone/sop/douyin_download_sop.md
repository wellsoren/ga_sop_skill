# 抖音无水印视频下载 SOP (douyin_download)

> 📦 配套脚本: 本仓库 `phone/scripts/douyin_download.py`（或 GA 根目录 `ga/douyin_download.py`）

**链路**: `分享链接 → 短链接解析 → 页面提取video_id → play(非playwm)API → .part临时文件 → 校验Content-Length → 改名保存`

## 前置依赖

- `douyin_download.py` (位于 `ga/douyin_download.py`，已封装核心流程)
- `requests` (标准库自带)

## 核心流程

```
用户提供分享链接
    ↓
Step 1: 解析短链接 (v.douyin.com → iesdouyin.com/share/video/{aweme_id}/)
    ↓
Step 2: 提取 video_id + 作品信息 (从页面HTML/JSON中)
    ↓
Step 3: 构造无水印播放地址
         https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=0
         ↑ 用 play，不用 playwm（playwm带水印）
    ↓
Step 4: 携带手机UA + Referer 下载MP4
         User-Agent: Mozilla/5.0 (Android Chrome)
         Referer: https://www.iesdouyin.com/
    ↓
Step 5: 写入 .part 临时文件 → 校验Content-Length → 改名保存
```

## 执行步骤

### 方案A：一键调用（推荐）
```python
from douyin_download import download_douyin_video

result = download_douyin_video("https://v.douyin.com/xxx/")
if result["ok"]:
    print(f"✅ 下载成功: {result['path']} ({result['size_mb']}MB)")
    print(f"   作者: {result['author']}")
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
| `title` | str | 视频标题/描述 |
| `author` | str | 作者昵称 |
| `aweme_id` | str | 作品ID |
| `video_id` | str | 视频ID |

### 方案B：手动分步（debug/定制用）

#### Step 1-2: 解析链接 + 提取 video_id
```python
import re, requests

MOBILE_UA = "Mozilla/5.0 (Linux; Android 13; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
HEADERS = {"User-Agent": MOBILE_UA, "Referer": "https://www.iesdouyin.com/"}

# 解析短链接
resp = requests.get("https://v.douyin.com/xxx/", headers=HEADERS, allow_redirects=True, timeout=15)
page_url = resp.url  # 如 https://www.iesdouyin.com/share/video/7662971854834896170/

# 从页面提取 video_id
m = re.search(r'"uri"\s*:\s*"([a-zA-Z0-9]+)"', resp.text)
video_id = m.group(1)  # 如 v0d00fg10000d9c5gkfog65ue1jgolpg
```

#### Step 3: 构造播放地址
```python
play_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=0"
# ⚠️ play 无水印 | playwm 带水印
```

#### Step 4-5: 下载 + 校验
```python
resp = requests.get(play_url, headers=HEADERS, stream=True, timeout=30, allow_redirects=True)
content_length = resp.headers.get("Content-Length")

# 写入 .part
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

## 关键禁令 ⚠️

| 禁令 | 说明 |
|------|------|
| ❌ 禁用 `playwm` | `playwm` 返回的URL带水印；务必用 `play` |
| ❌ 禁裸调无Headers | 不携带手机UA或Referer=空会被拦截/降质 |
| ❌ 禁直接保存 | 必须先写 `.part` 临时文件，校验 `Content-Length` 后再 rename |
| ❌ 禁从URL直接猜 video_id | 短链接URL中的数字是 `aweme_id`(作品ID)，**不是** `video_id`(播放ID) |
| ❌ 禁下载受保护/付费内容 | 仅下载有权查看和分享的公开作品 |
| ❌ 禁 webcdp 打开抖音短链 | 手机端webcdp浏览器打不开抖音短链(显示"网页无法打开")，必须用Python requests |

## 典型坑 & 排查

| 现象 | 原因 | 解决 |
|------|------|------|
| 下载的文件无法播放 | 可能带水印(用了playwm) | 检查URL是 `play` 还是 `playwm` |
| 500/403 错误 | Referer或UA不对 | 设置 `Referer=https://www.iesdouyin.com/` + 手机UA |
| 找到 aweme_id 但找不到 video_id | 页面结构变化 | 搜索 `"uri":` 或 `"play_addr"` 附近找video_id |
| 下载只有几KB | 返回的是错误页面/JSON | 检查Content-Type，应返回 `video/mp4` |
| 短链接打不开 | 抖音短链接需要302跟随 | `allow_redirects=True` |

## 已知变化 & 适配

- 抖音的CDN域名会变（douyinvod.com / snssdk.com 等），但 `play` API 入口不变
- `play` API 返回302重定向到实际CDN，`requests.get(allow_redirects=True)` 自动跟随
- 如 `aweme.snssdk.com` 不通，可尝试 `api.douyin.com` 或 `www.iesdouyin.com` 的同路径
- `ratio` 参数控制分辨率: `720p` / `1080p` / `540p`

## 尊重规则

- 仅下载**公开分享**的抖音作品
- 仅用于个人收藏或合理引用，不用于二次分发/盗用
- 尊重作者版权，遵守平台规则
