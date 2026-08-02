# YouTube 字幕提取 SOP (youtube_transcript_sop)

触发: 提取YouTube字幕 / 字幕 / 转录 / youtube subtitles

## 关键前置
- 依赖包: `youtube-transcript-api` (≥1.2) + `defusedxml`，需自行准备
- Android 端 pip 常因 `dalvik-cache ownership` 权限装不了包 → 用 pypi.org JSON API 查 wheel → urllib 下载 → zipfile 解压到项目目录 → `sys.path.insert` 引用

## 成功路径 (已验证 2026-08-01, 3475段/2:11覆盖)
```python
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import SRTFormatter, TextFormatter
api = YouTubeTranscriptApi()
data = api.list(VIDEO_ID).find_transcript(['en']).fetch()  # 自动字幕 is_generated=True
srt = SRTFormatter().format_transcript(data)
```
- 校验: `data[-1].start + data[-1].duration` ≈ 官方时长
- 自动字幕英文轨用 `['en']`；中文轨不存在时可 `translate('zh-Hans')` 再 fetch

## 易踩坑 (忘=高成本重试)
- ⚠ `fetch()` 返回的是 `FetchedTranscriptSnippet` 对象，**必须用属性访问** `.text/.start/.duration`，不能 `data[0]['text']` (TypeError)
- ⚠ 直连 `timedtext` URL 会 200 空响应(被反爬)；`youtubei/v1/get_transcript` 直接构造易 400；webcdp 转录面板可被反爬(CDP断连/面板无段) —— 三者均不可靠，直接用本包
- ⚠ pip 因 `dalvik-cache ownership : Permission denied` 装不了包：pypi.org JSON API 查 wheel → urllib 下载 → zipfile 解压到 project/ 下目录 → sys.path.insert

## 产出
- 输出到项目目录 `../project/<task>/`，格式 .srt(带时间戳) + .txt(纯文本, 供LLM阅读)
