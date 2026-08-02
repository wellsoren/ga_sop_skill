---
skill: x_twitter_video_download
domain: media_download
version: "1.0"
tags: [x, twitter, video, download, fxtwitter, twimg]
cc_quick: "X/Twitter视频下载 — fxtwitter API取直链 → .part下载 → 校验Content-Length/ftyp/时长 → 写manifest"
cc_keywords: ["X视频下载", "推特视频下载", "下载X视频", "twitter视频", "x.com视频", "fxtwitter", "video.twimg.com"]
---

# X / Twitter 视频下载 SOP (x_twitter_video_download)
> 场景：用户给 X 帖子链接（x.com 或 twitter.com）要求下载其中视频
> 适用：含单视频的公开帖子；实测可下载 2 小时长视频（1.37GB, 1920x1080, 7860s）

## 一、前置条件
- 纯 Python 标准库（urllib/json），无需第三方包
- 网络可达 `api.fxtwitter.com` 与 `video.twimg.com`
- 保存目录：建议 `ga/project/x_post_{post_id}/`（项目隔离，禁 temp/）

## 二、能力总览
| 能力 | 方式 | 说明 |
|------|------|------|
| 帖子→直链 | `api.fxtwitter.com/status/{post_id}` | 免费、无需登录，返回完整 JSON |
| 帖子内容验证 | `publish.twitter.com/oembed` | 公开接口，HTTP 200 交叉确认作者/帖文 |
| 下载 | urllib/curl 流式写 `.part` | 防中断留残 |
| 校验 | Content-Length + ftyp hex + ffprobe | 三重核验 |

## 三、快速参考
```python
import urllib.request, json
tid = '2075281664515739659'
j = json.load(urllib.request.urlopen(f'https://api.fxtwitter.com/status/{tid}', timeout=20))
url = j['media']['all'][0]['url']          # ⚠可能含过期tag，见Step 3
dur = j['media']['all'][0]['duration']     # 秒，用于下载后时长核验
```

## 四、执行流程
### Step 1: 解析帖子 ID
```python
import re
post_id = re.search(r'/status/(\d+)', tweet_url).group(1)
```

### Step 2: 请求 fxtwitter API
- `GET https://api.fxtwitter.com/status/{post_id}`（User-Agent 用 Mozilla 亦可）
- 失败降级：`https://api.vxtwitter.com/status/{post_id}` 或 twitsave.com 类第三方

### Step 3: 提取直链 + HEAD 预检（关键坑）
- `media.all[0].url` 即直链，形如 `https://video.twimg.com/amplify_video/{media_id}/vid/avc1/1920x1080/xxx.mp4?tag=N`
- ⚠️ `tag` 参数可能过期：曾遇 `tag=16` → 404，最新为 `tag=28`
- **下载前必须 HEAD 预检**：`urllib.request.Request(url, method='HEAD')`，确认 HTTP 200 与 Content-Length；404 则重新请求 API 取最新变体

### Step 4: .part 下载 + 校验
```python
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=30) as r, open(part, 'wb') as f:
    while True:
        chunk = r.read(8192)
        if not chunk: break
        f.write(chunk)
# 大小与 Content-Length 一致才 rename；不一致删 .part 重试
```

### Step 5: 校验 + 写 manifest（必做）
- hex 头检查：`00 00 00 18 66 74 79 70 69 73 6f 6d` = `ftyp isom`（Android `file` 命令无 magic 库可能误报 "data"，勿信）
- 时长核验：`ffmpeg_helper.probe()` 或 ffprobe，与 fxtwitter `duration` 比对（曾验证差 0.05s）
- **立即写 `download_manifest.json`**：source_url/post_id/platform、download_tool、download_source_url、downloaded_at、sha256、size、duration、subtitles——否则复盘时来源无法追溯

## 五、验证
- ✅ 本地大小 == Content-Length
- ✅ hex 头含 `ftyp isom`
- ✅ 本地时长 ≈ fxtwitter duration（误差 <1s）
- ✅ `publish.twitter.com/oembed?url=...` HTTP 200，作者/帖文吻合
- ✅ `download_manifest.json` 已生成

## 关键禁令 ⚠️
| 禁令 | 说明 |
|------|------|
| ❌ 禁 webcdp 取 `video.src` | X 页面 `<video>` 不加载 src，必为空 |
| ❌ 禁 Twitter Syndication API | `tweet-result` 响应无 mediaDetails |
| ❌ 禁 pip 装 yt-dlp 失败后放弃 | Android 端 pip 常有权限问题；直接走 fxtwitter |
| ❌ 禁用 `tag=16` 直链 | 旧变体 404；取最新 variant 并 HEAD 预检 |
| ❌ 禁存 temp/ | 易被清理；存 `ga/project/x_post_{id}/` |
| ❌ 禁下载后不写 manifest | 否则复盘无法追溯来源/工具/时间 |

## 典型坑 & 排查
| 现象 | 原因 | 解决 |
|------|------|------|
| 404 | tag 参数过期 | 重新请求 fxtwitter 取最新 variant |
| fxtwitter 403/超时 | 网络或限流 | 重试或降级 vxtwitter/twitsave |
| `file` 报 "data" | Android 无 magic 库 | 用 hex 头检查 `ftyp isom` |
| 下载几KB即完成 | 返回错误页/JSON | 检查 Content-Type 应为 `video/mp4` |
| 视频时长不符 | 帖内多视频取错 | 核对 `media.all` 索引与 duration |

## 尊重规则
- 仅下载**公开分享**的 X 视频，仅个人收藏/合理引用，不二次分发/盗用
