---
skill: session_resume
domain: agent_core
version: "2.0"
tags: [session, resume, restore, L4, compress]
cc_quick: "会话恢复 — L4 存档/压缩/fullset 恢复/W1 空写防护/W2 换 sid"
cc_keywords: ["会话恢复", "L4", "resume", "rotate_session", "compress_messages", "清空对话"]
---
# 会话状态恢复机制 · 操作 SOP
> 维护级别：L3 | 代码根：`../agentmain.py` | Android 挂钩：`../android_entry.py` | 存储：`memory/L4_raw_sessions/`

## 一、概述

**用途**：断连/重启后恢复上下文（messages + key_info + llm_no），并防止同 sid 空写覆盖、clear 误删历史。

**工作流**：
```
每轮有料 → _save_l4（压缩后写盘，W1 空跳过）
启动/首条 → 可选 /resume* → 否则 _load_l4_once（P_full，仅 bh 空）
成功 full/key → S1+ 换新 sid（旧文件保留）
新会话/clear → 清 history+handler + rotate_session（禁自动 P_full；不删 L4）
```

## 二、存储层 L4

| 项 | 值 |
|----|-----|
| 目录 | `memory/L4_raw_sessions/`（常量 `L4_SESSION_DIR`） |
| 文件名 | `session_{YYYYMMDD_HHMMSS}_{8位hex}.json`（`_gen_sid`） |
| 保留数 | **`L4_SESSION_LIMIT = 100`**；超出按 mtime 删最旧；**不扫 `.tmp.*`**（D42） |
| 字段 | `date`, `summary`（压缩前算）, `messages`（压缩后）, `key_info`, `llm_no` |
| images | **不进 L4**（D46）；摘要/正文用 `_msg_text` 抽文本 |

**原子写（D42）**：写 `session_*.json.tmp.<pid>` → `os.replace`；中断后清本 pid tmp；>24h 孤儿 tmp 可清。

## 三、保存（W1 / D43 / 交叉⑩）

入口：`_save_session(sid, messages, key_info='', llm_no=0)`；Agent 侧 `_save_l4`。

| 规则 | 说明 |
|------|------|
| W1 跳过 | `messages` 空 **且** key 无效 → `print('[L4] skip empty save')`，不 `os.replace` |
| 有效 key | `_key_info_effective`：非空 strip；含 stash `_resume_key_info` |
| key 来源 | handler.working['key_info'] → 回退 `_resume_key_info`（D43）；**禁止** handler 空时用空 key 盖好包 |
| 消息源 | `_coalesce_msgs`：**仅 primary is None 才回退**（D39）；`[]` 不回落脏 bh |
| 压缩 | 先 `_build_summary(raw)`，再 `compress_messages` 写入 messages |
| llm_no | 传参，不依赖保存瞬间全局 agent 是否已定义 |

## 四、压缩 `compress_messages`

| 参数 | 默认 |
|------|------|
| head_rounds | `_HEAD_ROUNDS = 3`（最早 3 轮） |
| tail_rounds | `_TAIL_ROUNDS = 5`（最近 5 轮） |

- **轮（R1）**：以真实 user 消息切分（D33）；混块 user（text+tool_result）计真实 user。
- **工具（T3）**：折叠 tool 正文，**不拆** tool_use/result 对。
- **标记（M3′）**：中间省略插 `[SYSTEM_NOTE][session_compress]…`；附着 head 末条（str 或 list text）；恰 1 处；无 text 则 append。
- **D20**：`_build_summary` / 展示摘要 **不含** `session_compress` 噪音。
- **D24**：内部 deepcopy，不改调用方原 list。
- 总轮 ≤ head+tail 或无真实 user：只 fold；二次 compress 先 peel 再必要时 re-attach。

## 五、恢复 fullset / P_full

统一入口：`GenericAgent._apply_resume(target='latest', mode='full', display_queue=None, auto=False)`。

| mode | 行为 |
|------|------|
| `none` | 不灌；`_resume_loaded=True`；通知已跳过 |
| `list` | 列盘；摘要 **现场** `_build_summary`（D36）；坏包占位（D35） |
| `key` | 只恢复 key_info（handler 在则立刻 `working['key_info']`，D26）；S1+ 换 sid |
| `full` | 灌 messages + key + llm；**in-place** 写 backend.history / self.history（D9/D22/D25/D41/D44）；S1+ |

**P_full 自动**（`_load_l4_once`，`auto=True`）：

- 门闩：**`len(bh)==0` 或 bh is None** 才自动 full（D28 / 交叉⑧）；**不**因 `session_msgs` 假非空误判。
- 显式 `/resume …` **忽略** `_resume_loaded`（D17），可覆盖。
- 成功/失败均 `_notify_resume` → `display_queue`（D40）。
- **恢复过程不立即 save**（D37）。

**S1+**：full/key 成功后 `rotate_session` 换新 sid；旧 path 文件保留。

**坏包**：

- 自动路径：坏 JSON / messages 非 list → 跳过取次新，**不自动删**（D34）。
- `/resume N`（1-based 与 list 行一致）命中坏包 → **报错不静默跳**（D35）。

**history 边界（D13/D27/D41/D44/D45）**：

- full：in-place 替换内容，主路径 **不** `bh = new_list`；`id` 保持。
- `self.history` / `backend.history`：`is not None` 才写；**`[]` 仍写回**（D45）。
- 灌入 L4 中非 slash user；纯 `/resume` user 不进 history；无 compress 标记噪音。

## 六、斜杠命令

```
/resume              → list（或实现约定的默认 list）
/resume list
/resume none
/resume full | key
/resume N | N full | N key     # N 为 list 的 1-based 序号
/resume <sid> | <sid> full|key
```

**时序（D-crit）**：`/resume*` 必须在自动 P_full **之前**处理，保证 none/手动优先。

## 七、W2 `rotate_session` 与 clear（D30 / D38）

```python
def rotate_session(self):
    # 新 _sid；session_msgs=[]；清 _resume_key_info；_resume_loaded=True
    # 不清 self.history / handler / backend.history（D30）
    # 不删任何 L4 文件（D38）
```

| 场景 | 行为 |
|------|------|
| 单独 rotate | 只换 sid + 空 session_msgs + 禁自动 P_full；**history 仍在** |
| clear / 新会话 | 调用方：`history=[]`、`handler=None`（及 bh 若需要）**再** `rotate_session()` |
| 有 snap 恢复会话 | **禁止** rotate（android：有 snap 不调用）；**不**从 snap 恢复 `_sid`（D23②） |
| 空 snap 新会话 | android 调 `rotate_session` |

### 🔴 清空对话 ≠ 删除 L4（D38）

- UI「清空」/ `/clear` / `clearAllConvos`：**只清内存态**（history、handler、session_msgs）+ rotate。
- **禁止** `rmtree` / 批量删除 `session_*.json`。
- 用户可见表述：清空当前对话不会删除 `L4_raw_sessions` 历史存档；要用 `/resume list` 再选。

## 八、Android 挂钩（`android_entry.py`）

| 点 | 动作 |
|----|------|
| `_convo_restore(a, None)` / 无 snap | `rotate_session()` → 新 sid，禁首条自动 P_full |
| 有 snap | **不** rotate；按 snap 恢复 vars；**D23②** `_sid` ∈ `_CONVO_SPECIAL`（snap 不存/不恢复 `_sid`，旧 snap 也滤掉） |
| clear / `_reset_convos` / clearAllConvos | `history=[]`；`handler=None`；必要时清 bh；**然后** `rotate_session()`；**不删 L4** |

## 九、函数索引（符号名，少绑行号）

| 符号 | 职责 |
|------|------|
| `L4_SESSION_LIMIT` / `L4_SESSION_DIR` | 容量与目录 |
| `_msg_text` | 统一抽文本（list-block 安全，D31）；Titles/summary/D13 共用（交叉④） |
| `_build_summary` | 摘要；滤 compress 标记（D20）；可吃 key_info |
| `compress_messages` | head3+tail5 + fold + M3′ |
| `_coalesce_msgs` | 仅 None 回退（D39） |
| `_key_info_effective` | W1 有效 key |
| `_save_session` / `_save_l4` | 有料写盘 |
| `_load_last_session` | 自动扫盘，跳坏包 |
| `_gen_sid` | 时间戳+hex |
| `rotate_session` | W2 |
| `_apply_resume` | fullset 统一恢复 |
| `_load_l4_once` | P_full 门闩 |
| `_notify_resume` | D40 反馈 |
| `_handle_slash_cmd` | `/resume*` 解析 |

## 十、避坑清单

| 坑 | 正确做法 |
|----|----------|
| 同 sid 空 `[]` 覆盖好包 | W1 + rotate 换 sid（S1+/W2） |
| `session_msgs or bh` 假非空 | D39：只 None 回退；D28：自动 full 只看 bh |
| clear 删光 L4 | **禁止**；D38 |
| rotate 当 clear | D30：rotate 不动 history/handler |
| 摘要出现 session_compress | D20 过滤 |
| 改 content 原地污染 | D24 deepcopy |
| handler 空丢 key | D43 stash `_resume_key_info` |
| 自动 full 盖正在跑的会话 | D28 仅 bh 空；显式 resume 用 D17 |
| 恢复后立刻再 save 新文件 | D37 恢复路径不 save |
| 双套消息解析 | 一律 `_msg_text` |
| 依赖旧占位过滤列表 | 已去除；靠 compress/resume 语义 |

## 十一、相关文件

| 路径 | 作用 |
|------|------|
| `../agentmain.py` | L4 存取/压缩/resume/rotate |
| `../android_entry.py` | 空 snap / clear 挂钩 |
| `memory/L4_raw_sessions/` | 存档目录 |
| `memory/memory_management_sop.md` | L0 分层 |
| `plan_session_resume/plan_session_resume.md` | 决策全集 D-crit～D46 |

## 十二、回归入口

进程内（Android 无独立 `python` CLI）：

```text
plan_session_resume/test_summary_compress.py  # step10 回归；code_run exec
```

判据摘要：LIMIT=100；compress 不拆对；W1+D43；D28/D38/D39；S1+；in-place；坏包 D34/D35；D40 反馈。

> 修改 `agentmain.py` / 本 SOP 前：备份；改代码后 `del sys.modules` 再 import 验证。
