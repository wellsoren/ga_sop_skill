# GA SOP & Skill 资源库

> 开源手机版 GA（GAndroid Agent）的通用 SOP 文档、配套脚本与 Agent Skill 资源库，供其他手机 GA 用户下载使用。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 目录结构

```
ga_sop_skill/
├── phone/                  # 手机版 GA 资源（当前主力）
│   ├── sop/                # SOP 操作手册
│   ├── scripts/            # 配套脚本
│   └── skills/             # Agent Skill（规划中）
├── pc/                     # 电脑端 GA 资源（预留，未来扩展）
├── README.md
├── LICENSE                 # MIT
├── requirements.txt        # 通用依赖
└── .gitignore
```

## 快速开始

```bash
# 下载仓库
git clone https://github.com/<your-name>/ga_sop_skill.git

# 安装依赖（脚本仅需 requests）
pip install -r requirements.txt

# 示例：下载抖音无水印视频
python phone/scripts/douyin_download.py "https://v.douyin.com/xxxx/"

# 示例：下载 B 站视频
python phone/scripts/bilibili_download.py "https://b23.tv/xxxx"
```

> 📱 在 Android 端 GA 中使用时，将 `phone/scripts/` 下脚本放入 GA 根目录（`ga/`）即可被 `import`。

## SOP 目录（当前版本）

### 📥 下载类

| SOP | 说明 | 配套脚本 |
|-----|------|---------|
| [douyin_download_sop.md](phone/sop/douyin_download_sop.md) | 抖音无水印视频下载（play API 取流、.part 校验） | `phone/scripts/douyin_download.py` |
| [bilibili_download_sop.md](phone/sop/bilibili_download_sop.md) | B 站视频下载（view/playurl API、qn 清晰度） | `phone/scripts/bilibili_download.py` |
| [x_twitter_video_download_sop.md](phone/sop/x_twitter_video_download_sop.md) | X/Twitter 视频下载（fxtwitter 直链） | - |
| [youtube_transcript_sop.md](phone/sop/youtube_transcript_sop.md) | YouTube 字幕提取（youtube-transcript-api） | - |

> 更多类别（搜索、内容制作、手机操作、元能力等）陆续补充中。

## 如何贡献

1. Fork 本仓库并创建特性分支
2. SOP 文档遵循 `sop_standard_sop` 规范（YAML 头 + 五大章节）
3. 提交前确保：无硬编码密钥、无本机绝对路径、脚本可独立运行
4. 发起 Pull Request

## 安全声明

- 本仓库**不包含任何真实 API Key / Token / 凭证**；涉及密钥处一律使用占位说明"需自行配置"
- 下载类脚本仅支持**公开分享**内容，请尊重版权与平台规则
- 使用时请遵守所在地法律法规

## 路线图

- [ ] 手机端：搜索类 / 内容制作类 SOP
- [ ] 手机端：Agent Skill 入库
- [ ] 电脑端 GA 资源（`pc/` 目录填充）

## 许可证

[MIT](LICENSE) © 2026 ga_sop_skill contributors
