# GA SOP & Skill 资源库

> 手机版 GA（GAndroid Agent）的通用 SOP 文档、配套脚本与 Agent Skill 资源库，供其他手机 GA 用户下载使用。

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

## 前置条件

- 一台 **安卓手机**
- 已安装 **GA App**（[下载地址](https://app.gaagent.ai/)）
- 电脑已安装**GenericAgent**（[下载地址](https://github.com/lsdefine/GenericAgent)）
## 快速开始

> ⚠️ 手机版 GA 为 Android 嵌入式运行环境：**无 `git`、无 `pip`、无终端 `python` 命令**，请按平台选择下方方式。

### 📱 手机版 GA（Android）

手机 GA 的全部操作在对话中完成，无需命令行：

1. **获取资源**：直接对 GA 说"下载 ga_sop_skill 仓库资源到对应目录"（GA 内置文件下载能力，无需 git），按类型存放：
   - SOP 文档 → `ga/memory/`（GA 的 SOP 所在目录）
   - 配套脚本 → `ga/` 根目录（放入后即可被 `import` 使用）
   - Agent Skill → `ga/skills/`
2. **依赖**：下载类脚本仅需 `requests`（GA 已内置，无需安装）
   - 若某 SOP 需额外纯 Python 包（如 youtube-transcript-api）：GA 会自动按纯 Python 包离线方式安装（从 pypi.org 获取 wheel 解压到 `project/<lib>/`，再 `sys.path.insert` 导入），无需 pip
3. **注册**：对GA说：`注册登记×××_sop到GA系统`（例如：注册登记douyin_download_sop到GA系统）
3. **使用**：对 GA 说"下载这个抖音视频：https://v.douyin.com/xxxx/"，GA 会按对应 SOP 执行下载

### 💻 电脑版 GA（PC）

```bash
# 下载仓库
git clone https://github.com/wellsoren/ga_sop_skill.git

# 安装依赖（脚本仅需 requests）
pip install -r requirements.txt

# 示例：下载抖音无水印视频
python phone/scripts/douyin_download.py "https://v.douyin.com/xxxx/"

# 示例：下载 B 站视频
python phone/scripts/bilibili_download.py "https://b23.tv/xxxx"
```

## SOP 目录（当前版本）

### 📥 下载类

| SOP | 说明 | 配套脚本 |
|-----|------|---------|
| [douyin_download_sop.md](phone/sop/douyin_download_sop.md) | 抖音无水印视频下载（play API 取流、.part 校验） | `phone/scripts/douyin_download.py` |
| [bilibili_download_sop.md](phone/sop/bilibili_download_sop.md) | B 站视频下载（view/playurl API、qn 清晰度） | `phone/scripts/bilibili_download.py` |
| [x_twitter_video_download_sop.md](phone/sop/x_twitter_video_download_sop.md) | X/Twitter 视频下载（fxtwitter 直链） | - |
| [youtube_transcript_sop.md](phone/sop/youtube_transcript_sop.md) | YouTube 字幕提取（youtube-transcript-api） | - |

### 🔍 搜索类

| SOP | 说明 | 配套脚本 |
|-----|------|---------|
| [xiaohongshu_hot_search_sop.md](phone/sop/xiaohongshu_hot_search_sop.md) | 小红书热搜/热门话题（App GUI：今日热搜榜+话题榜AI总结） | - |

### 🧭 规划/模式类

| SOP | 说明 | 配套脚本 |
|-----|------|---------|
| [plan_sop.md](phone/sop/plan_sop.md) | 复杂任务规划模式（8 条件触发、官方 6 步探索、多方案权衡、用户确认门、独立评委验证） | - |
| [goal_mode_sop.md](phone/sop/goal_mode_sop.md) | Goal Mode 目标模式（开放目标+时间预算，后台自治推进至收口，支持暂停/恢复） | `phone/scripts/goal_mode.py` |
| [session_resume_sop.md](phone/sop/session_resume_sop.md) | 会话恢复（L4 存档/压缩/fullset 恢复/轮换 sid） | - |

### 🔬 深度研究类

| SOP | 说明 | 配套脚本 |
|-----|------|---------|
| [DeepResearch_sop_android.md](phone/sop/DeepResearch_sop_android.md) | Android 端深度研究（DAG 分解+混合并行+镜像回退+SYNTH 综合） | `phone/scripts/deepresearch_utils.py` |

> 更多类别（内容制作、手机操作等）陆续补充中。

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

## 🙏 致谢

- [GA App](https://app.gaagent.ai/) — app应用及相关代码支持
- [GenericAgent](https://github.com/lsdefine/GenericAgent) — 提供应用及相关代码支持
- 所有贡献者和用户
