---
name: goal_mode
skill: goal_mode
domain: agent_core
version: "1.4.0"
description: "Goal Mode 目标模式：用户给开放目标+时间预算（如'花1小时持续优化X'、'没事也找事干'）时，后台自治推进直到预算/轮次耗尽，自动收口。触发词: 开放目标/长时间任务/后台自主跑/持续优化X小时/没事也找事干/goal mode/目标模式"
tags: [mode, autonomous, background, goal]
cc_quick: "Goal Mode v1.4.0：start_goal→auto_tick(_goal_elapsed)墙钟；pause/resume/update；report_goal_done；turn%5保真注入；exit恢复max_turns；禁nohup/禁覆盖state"
cc_keywords: ["开放目标", "长时间任务", "后台自主跑", "持续优化", "没事也找事干", "goal mode", "目标模式", "start_goal", "goal_mode", "pause_goal", "report_goal_done"]
tools: [code_run, file_read, file_patch, file_write, ask_user, update_working_checkpoint]
forbidden_tools: []
tools_mode: lax
---

# Goal Mode SOP

## Android 最小启动卡
```python
handler = android_entry.agent.handler  # ⚠ 不是 agent
gm.start_goal(..., handler=handler)
# 收口: gm.finalize('摘要','success'); 确认 handler.max_turns 已恢复(非 120)
# 禁: nohup / 覆盖已有 state / 改 agentmain 全局 max_turns
```
> v1.4.0：`pause_goal`/`resume_goal`/`update_goal_objective`；`report_goal_done` 工具；turn%5 保真注入；`_goal_elapsed` 扣 paused；`done_blocked` 终态。v1.3.1 起：误传 agent 会 unwrap 到 handler；finalize/stop 有 path 泄漏守卫。

## 何时用
用户给开放目标 + 时间预算（如"花1小时持续优化X"、"没事也找事干"），非一次性闭环任务。

## 状态文件
推荐由 `goal_mode.start_goal(...)` 原子创建；也可手写后 `init`/`enter`（兼容）。
默认路径：模块缺省为 **cwd 下 `goal_state.json`**（**不再**默认 `temp/goal_state.json`）。cwd 常为 `temp/` 时文件落在 `temp/goal_state.json`；桌面 reflect 需要 `temp/...` 时请**显式**传 `state_path` / `--GOAL_STATE`。
```json
{
  "objective": "用户原话目标",
  "budget_seconds": 3600,
  "start_time": 0,
  "turns_used": 0,
  "agent_turns": 0,
  "max_turns": 200,
  "status": "running",
  "done_prompt": "",
  "last_agent_turn": 0,
  "last_interrupt_reason": "",
  "last_summary": "",
  "last_checkpoint_at": 0.0,
  "session_max_turns": 120,
  "paused_at": 0.0,
  "paused_seconds": 0.0,
  "objective_version": 1,
  "objective_updated_at": 0.0
}
```
- `budget_seconds` 默认 3600（1小时），以用户明示为准；`start_goal` **拒绝** `<600`（`_MIN_BUDGET=600`）。
- **`max_turns`（外层协议）**：goal 协议轮次预算，默认 200；防空转。**框架硬写检查点禁止改此字段**。`start_goal` 要求 `>=1` 且非 bool。
- **`turns_used` vs `agent_turns`**：`turns_used` 仅由 `on_done` 递增（reflect/桌面主路径）；`agent_turns` 仅由每轮 `auto_tick` +1（Android 会话观测）。**禁止**用 `agent_turns` 触发 `done_turns`。
- **`session_max_turns`（会话硬顶）**：`enter_goal_mode` 后 agent 会话 `handler.max_turns`（B1=**120**）；仅记录/同步，不等于改写协议 `max_turns`。`exit_goal_mode` **恢复** enter 前的 `handler.max_turns`。
- `status`：`running` | `paused` | `done_budget` | `done_turns` | `done_manual` | `done_success` | `done_blocked`。仅 `running` 可被 `auto_tick` 推进；硬检查点**永不**写 `done_*`。
- **暂停字段**：`paused_at`（当前暂停起点，running 时为 0）；`paused_seconds`（累计已暂停秒，resume 累加）。墙钟用 `_goal_elapsed` = now−start−paused_seconds（若 paused_at>0 再扣当前段）。
- **目标版本**：`objective_version` 自 1 起；`update_goal_objective` 每次 +1 并写 `objective_updated_at`；注入用 version 差强制重贴目标。
- `last_*`：会话中断/耗尽时由 `_goal_checkpoint` 或 `auto_tick` 写入；续跑时可读 `last_summary` 恢复上下文。
- 🚫 **禁止覆盖**已有 state 文件开新 goal；应换路径。暂停后续跑用 **`resume_goal()`**（勿手改 JSON status）。

## 统一入口（推荐：lifecycle facade）
> 实现：`ga/goal_mode.py`（Android facade **第一**；`init/check/on_done` reflect 兼容为桌面次路径）。
> ⚠ Android 无独立 python 进程 / 无 `nohup python`；会话内 `code_run` 驱动。仅**绑定/传入**的 handler 会被 facade 自动 exit；旧「手写 enter」须改用 facade，否则收口可能漏 exit。

### Android 会话内（主路径 · v1.4）
```python
import goal_mode as gm
# Android: 取真正会话 handler（⚠ 不是 android_entry.agent）
handler = android_entry.agent.handler
r = gm.start_goal(
    '用户原话目标',
    state_path='/abs/path/to/goal_state.json',  # 推荐 abs；默认 cwd/goal_state.json
    budget_seconds=3600,   # >=600
    max_turns=200,         # >=1（协议顶；Android 主路径几乎不靠它自动停）
    handler=handler,       # 绑定后 stop/finalize 可安全 exit（误传 agent 会一层 unwrap）
)
# 每轮：框架 turn_end → auto_tick(path, turn, summary_hint) 写 last_*/agent_turns；
#       墙钟耗尽 → done_budget + should_stop → exit + clear_binding
# 可选：gm.heartbeat(summary='...') 只刷 last_*（不写 done_*、不 +agent_turns）
# 暂停：gm.pause_goal() → status=paused + exit + clear_binding（预算冻结）
# 恢复：gm.resume_goal(handler=handler) → running + re-enter；累计 paused_seconds
# 改目标：gm.update_goal_objective('新目标') → version+1；不重置 budget/turns
# 成功收口：gm.finalize('摘要', 'success') 或工具 report_goal_done(status=complete)
# 阻塞收口：finalize(..., 'blocked') / report_goal_done(status=blocked) → done_blocked
# 手动停：gm.stop_goal('manual'| 'budget_exhausted'|...) → 映射终态 + exit + 清绑定
# 收口后检查：handler.max_turns 不得仍为 120；若 out['exit_skipped'] 非空须处理
print(gm.status())  # 只读；缺文件 missing=True
```
- **主路径自动收口 = 墙钟**（`_goal_elapsed > budget` → `done_budget`）。**RES-5**：Android 几乎不调 `on_done` → `turns_used` 常为 0 → `turns_used>=max_turns` 几乎不触发；**勿把协议 `max_turns` 当 Android 主路径唯一停条件**。
- `status()` 返回形状（⚠ 协议字段在 **`state` 子字典**，勿当顶层读）：
  - 顶层：`state_path` / `handler_bound` / `handler_active` / `missing` / `budget_remaining` / `turns_remaining` / **`agent_turns`**
  - `state`：完整 goal JSON（`status`/`objective`/`turns_used`/`agent_turns`/`max_turns`/`done_prompt`/`last_*`/`paused_*`/`objective_version`…）
  - 文件缺失：`missing=True`，无 `state` 键；不抛异常
- `start_goal`：原子写 running（含 `agent_turns=0` + `last_*` + `paused_*=0` + `objective_version=1`）；模块 `GOAL_STATE`→abs；已 bound **拒绝**二次 start。
- 公开 API：`auto_tick` / `heartbeat` / `finalize` / `pause_goal` / `resume_goal` / `update_goal_objective` / `clear_binding` / `stop_goal` / `check` / `on_done`。
- `pause_goal(reason='user')`：running→paused；**必须** exit_goal + clear_binding；幂等（已 paused 只确保 exit）。
- `resume_goal(handler=...)`：paused→running；累加 paused_seconds；清 paused_at；可选 re-enter + `goal_force_fidelity=True`。done_* 可强制拉回 running（清 done_prompt）。
- `update_goal_objective(obj)`：仅 running|paused；version+1；**不**重置 start_time/turns/budget；设 force_fidelity。
- `stop_goal(reason)`：`_map_done_status`（`blocked`→`done_blocked`；`budget_exhausted`→`done_budget`；`success`→`done_success`；默认 `done_manual`）；已终态**不覆盖** status（幂等）；无条件 `clear_binding`。
- `clear_binding(path=None)`：`path is None` 无条件清；给定 path 仅当 `GOAL_STATE==path` 才清，否则 no-op。
- 安全 exit：path 与模块 abs 一致才 `exit_goal_mode`；**exit 会恢复** enter 前 `handler.max_turns`。

### 桌面 / 无 handler 降级
```python
import goal_mode as gm
gm.start_goal('obj', state_path='goal_xxx.json')  # handler_bound=False
# 仅状态机；check/on_done 驱动 turns_used；收口只写文件，无自动 exit。
```
桌面 reflect 兼容：`agentmain --reflect goal_mode.py --GOAL_STATE temp/goal_xxx.json`（须**显式**路径；**desktop-only**，Android 禁 nohup）。

## 启动（Android 端主路径：会话内自主循环）
> ⚠ 环境事实：Android 端 GA 的 agent 是 android_entry.py in-process import 的 GenericAgent 实例，
> sh 无 python 命令，`agentmain --reflect` 独立进程模式不可用。
1. 🔴 **推荐** `goal_mode.start_goal(objective, state_path=abs, handler=handler, ...)`（见上「统一入口」）。
   兼容手写：写 state 文件后 `handler.enter_goal_mode(abs_path)` + `goal_mode.init({'GOAL_STATE': abs})`。
   > ⚠ code_run 内须用**绝对路径**（cwd 常是 temp/；相对 `temp/goal_state.json` 会错位成 `temp/temp/...`）。
2. enter 效果（facade 或手写相同）：
   - `working['in_goal_mode']` = **abspath**；保存原 `max_turns` 后抬升 `handler.max_turns = 120`（`agentmain` 全局 80 **禁止**改）。
   - `exit_goal_mode` **恢复** enter 前 `max_turns`；**不**由 enter/exit 改写 goal_state 本体。
   - 未 enter → 仍 75 软闸 / 默认硬顶，长 goal **会**被打断。
3. 在本会话内自主循环（v1.4 主路径）：
   > 💡 框架每轮 `auto_tick` 已刷 `agent_turns`/墙钟闸（扣 paused）；agent 用 `heartbeat`/`finalize`/`report_goal_done`/`pause_goal`，避免手写 JSON 收口。
   - 每轮：推进目标；可选 `heartbeat(summary=...)`；**勿**手改 objective/budget/max_turns/status。
   - 墙钟耗尽：`auto_tick`（`_goal_elapsed`）→`done_budget`→turn_end exit+`clear_binding`。
   - 成功：`finalize`/`report_goal_done(complete)`→`done_success`；阻塞→`done_blocked`；手动：`stop_goal(...)`。
   - 暂停/恢复/改目标：`pause_goal` / `resume_goal` / `update_goal_objective`。
4. 收口 / 停止后：facade/turn_end 已 exit+清绑定；若曾手写 enter 而未走 facade，**必须**自行 `handler.exit_goal_mode()`，防幽灵豁免 75 闸。
5. 🔴 CHECKPOINT：启动前向用户复述并确认（**仅此 1 次**；通过后不再为方向/改稿请示）：
   - **目标**（objective 原话）
   - **预算**（`budget_seconds` / 协议 `max_turns`）与收口条件（到时/到轮/`finalize` 成功）
   - **`allowed_paths`**：本 goal 内可直接 patch 的路径清单（例：`memory/sophub_sop.md`；可含配套 `skills/darwin-skill/results.tsv` 等产出）。未列出的 memory/ 系统文件仍红线。
   - 确认话术示例：「确认启动：目标=…；预算=20min；可改=memory/xxx.md；到时自动收口。」
   - 此后不再等待用户；每 3-5 轮单向推送进度（见「自主推进原则」）。

## 预算闸与检查点（方案 R · v1.4）
> 实现：`goal_mode.auto_tick`（path 中心写 `done_*`）+ `ga_android.turn_end_callback`（lazy import、should_stop→exit+clear_binding、保真注入）+ `_goal_checkpoint`（永不 `done_*`）。**不**改 `agent_loop.py`。

### 双 max_turns + 双计数
| 字段 | 含义 | 谁改 / 触发 |
|------|------|-------------|
| `goal_state["max_turns"]` | 协议轮次顶（常 200） | agent/SOP；**硬检查点禁改**；`turns_used>=max_turns`→`done_turns`（主靠 on_done/reflect） |
| `handler.max_turns` / `session_max_turns` | 会话硬顶（goal 活跃 **120**） | enter 设 120；**exit 恢复**原值；触顶 H1b 只 exit，**不**自动写 `done_turns`（RES-2） |
| `agent_turns` | 会话轮观测 | **仅** `auto_tick` 在 **status==running** 时 +1；**禁止**用它触发 `done_turns`（RES-5） |
| `turns_used` | 协议轮 | **仅** `on_done` +1 |

### 墙钟主收口（auto_tick）
- **非 running early-return**：`status != 'running'`（含 `paused` / 一切 `done_*`）→ `should_stop=True`，`reason=stale_status`，**不** +agent_turns、**不**改 last_*。
- 墙钟：`elapsed = _goal_elapsed(data)` = `now - start_time - paused_seconds`（若 `paused_at>0` 再扣当前暂停段）；**严格** `elapsed > budget` → `done_budget` + `should_stop`。
- 每轮（仅 running）刷新 `last_summary` / `last_agent_turn` / `last_checkpoint_at` / `agent_turns`。
- path 中心：`auto_tick(path=A)` **不**假设 `GOAL_STATE==A`；不污染 path=B。
- turn_end：`should_stop` → `exit_goal_mode` + `clear_binding(path=path)`（禁止用 `status()` 推断是否清绑定）。

### report_goal_done 工具（v1.4）
- schema：`tools_schema.json` + `tools_schema_cn.json`；`status` enum=`complete`|`blocked`；必填 `status`+`result`；可选 `evidence`。
- handler：`do_report_goal_done` → 非 goal 模式报错；`complete`→`finalize(result,'success')`；`blocked`→`finalize(result,'blocked')`→`done_blocked`。
- **禁止**用本工具做 pause；pause 用 `pause_goal` API。
- 新会话才加载 schema；已开会话可能看不到新工具（可 `code_run` 调 `gm.finalize`）。

### 保真注入（turn_end · v1.4）
- 仅 `status==running` 且 path 有效时注入。
- 触发：`turn==1` **或** `turn%5==0` **或** `goal_force_fidelity` **或** `objective_version != goal_injected_obj_ver`。
- 常规 → `[GOAL-FIDELITY]` + `<objective>` + 剩余预算 + 完成/阻塞审计纪律（含 report_goal_done）。
- 目标变更/强制 → `[GOAL-UPDATED]` + `<untrusted_objective>`。
- objective **>500 字截断**；注入后清 `goal_force_fidelity`，写 `goal_injected_obj_ver`。

### 75 软闸豁免
- `turn % 75 == 0 and (not _plan) and (not _goal)` 才注入「必须 ask_user」。
- **仅** `in_goal_mode` 活跃时豁免；未 enter / 已 exit / path 失效后**恢复** 75 闸。
- `turn % 7` 弱提醒在 goal 下**仍可出现**。

### B2-soft（提醒，非收口）
- 条件：goal 活跃 **且** 无 `exit_reason` **且** `turn < max_turns` **且** (`turn >= max_turns-3` 或 `turn % 15 == 0`)。
- 注入 `[GOAL-CP]`：可 `heartbeat(summary=...)` 或 patch **last_summary** / `last_checkpoint_at`；保持 `status=running`；**禁止**当唯一耗尽手段。

### B2-hard / H1b（强制落盘）
- `exit_reason` 非空 → `_goal_checkpoint`；**或** `turn >= handler.max_turns`。
- 只写：`last_*` / `session_max_turns`。
- **禁止改**：`objective` / `turns_used` / `status→done_*` / `max_turns`。
- `done_*` **仅**由 `auto_tick` / `check` / `on_done` / `stop_goal` / `finalize` 写入。
- 写盘成功后 hard/exit 类 → `exit_goal_mode`（恢复 max_turns）；path 缺失或 `status≠running` → auto-exit。
- 失败全降级：log，不抛垮 loop。
## 自主推进原则（🔴 核心：汇报 ≠ 询问）
- ✅ **自主决策**（直接做，不询问）：选工具 / 查资料 / 重试 / 换子任务 / 调整执行细节 / 安排轮次顺序 / **对启动确认中 `allowed_paths` 内文件的读写与 patch** / 按目标推进的修改方案与计划（不再逐步请示）。
- ✅ **汇报 = 单向通知**：每 3-5 轮推送进度摘要（飞书或会话消息），**不等用户回复，继续推进**。
- ❌ **仅以下情况才停下来等用户**（标 🔴 者 = 必须等人确认后才能继续）：
  1. 🔴 CHECKPOINT 启动前 1 次确认（目标 + 预算 + 收口条件 + **`allowed_paths` 授权清单**，见「启动」第 5 步）
  2. 预算/轮次耗尽 → 直接收口并汇报结果（**不**询问、**不**等确认）
  3. 🔴 CHECKPOINT 目标理解冲突（无法确定 objective 含义）→ 复述歧义点，等人澄清
  4. 🔴 CHECKPOINT 真红线（**执行前必须停**）：支付 / 不可逆删除（非目标产出清理）/ 对外发消息（进度飞书推送除外）/ 安装应用 / 账号登录·登出·改密 / **修改 `allowed_paths` 之外的 memory/ 或系统文件** → 展示将做什么 + 影响面，等人明确同意
  5. 🔴 CHECKPOINT 连续 3 次失败且无替代方案 → 汇报失败轨迹，等人给新方向或停
  6. 用户主动插话给新指令（响应并继续；插话本身即授权，无需再二次确认方向）
- ⚠ 禁止为"确认方向"而每轮询问；**用户不回复 = 默许继续**（仅适用于非 🔴 项）。
- ⚠ **已删除的冲突项**（实跑证伪，勿恢复）：「修改系统文件（memory/ 一律请示）」「执行修改方案」「执行计划」——会把优化类 goal 卡成逐步审批，与「有事没事都推进」矛盾。替代机制 = 启动时路径授权 + 越权仍停。
- 💡 与全局 RULES「改 memory 须确认」的关系：goal 启动确认中用户同意的 `allowed_paths` = **本 goal 生命周期内**对该清单的一次性授权；清单外仍遵守全局红线。

## 进度推送（飞书异步，方案B）
- 每 3-5 轮把进度摘要推送到飞书群（chat_id 需替换为你自己的飞书群，形如 `oc_` 开头）。
- 方式：`from lark_bot.feishu_api.im import InstantMessagingAPI; im.send_card(CHAT_ID, {...})`（见 lark_push_sop），token 全自动，无需手动凭证。
- 推送内容：当前轮次/总轮次、完成事项摘要、剩余预算/轮次、下一步方向。
- 🔴 推送是**单向通知**，不等用户回复；用户回复 = 新指令 → 响应并继续。

## 停止 / 观察
- 墙钟耗尽 → `auto_tick`（`_goal_elapsed`）写 `done_budget` + turn_end exit + `clear_binding`（Android 主路径）。
- 协议轮耗尽 → `check`/`on_done`/`auto_tick(turns_used)` 写 `done_turns`（reflect/显式 on_done 更常见）。
- 成功：`finalize(result, 'success')` 或 `report_goal_done(status=complete)` → `done_success`。
- 阻塞：`finalize(result, 'blocked')` 或 `report_goal_done(status=blocked)` → `done_blocked`。
- 暂停：`pause_goal()` → `paused` + exit + clear_binding（预算冻结，不写 done_*）。
- 恢复：`resume_goal(handler=...)` → `running` + 可选 re-enter；**勿**手改 JSON。
- 手动停：`stop_goal('manual'|'budget_exhausted'|'blocked'|...)` → 映射终态（幂等不覆盖已终态）+ exit + 清绑定。
- 观察：`status()` 顶层含 `budget_remaining`/`turns_remaining`/`agent_turns`/`handler_bound`/`missing`；协议字段在 `state` 子字典。
- 续跑：优先 `resume_goal`；done_* 强制拉回也可 `resume_goal`；新任务须**新文件**，禁止覆盖已有 state 开新 goal。

## 失败模式

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| `goal_state.json` 不存在 | 按「状态文件」节写入后再启动 | 🔴 向用户报告缺失字段，请用户提供目标/预算 |
| `budget_seconds` 缺失/低于 600 或 `max_turns` 缺失 | 按默认值修正（3600/200）或以用户明示为准 | 🔴 与用户确认预算上限后再启动 |
| 会话内循环中状态文件损坏/JSON 错误 | 从 `done_prompt` 重建状态，或重新写入；硬检查点跳过不抛 | 🔴 报告用户，确认是否重置轮次 |
| `status` 非 running 且任务早停 | 读状态：`paused`→`resume_goal`；`done_*`→确认是否真结束；auto_tick 对非 running early-return | `resume_goal(handler=...)` 或用户确认后强制 resume；勿手改 JSON |
| 会话中断 / 手机重启 | 重读 state + `last_*`；`running`→重新 `enter_goal_mode(abs)`；`paused`→`resume_goal` | 🔴 向用户汇报进度，确认是否继续 |
| `turns_used` 异常增长 / 空转 | 核对 `done_prompt` / `last_summary` 是否有实质推进 | 🔴 请示用户是否提前收口 |
| **未 enter 仍 75 闸**（turn%75 强制 ask_user） | 启动后立刻 `enter_goal_mode(abs_path)` | 查 `working['in_goal_mode']` 是否 abspath 且文件存在 |
| **会话 75 软闸误伤长 goal** | 确认已 enter 且未过早 exit；path/status 有效 | 读 turn_end 条件是否含 `not _goal` |
| **硬顶 80→120 未生效** | 确认 `enter_goal_mode` 后 `handler.max_turns==120`（中途抬升；非改 agentmain 全局） | 禁止改 agentmain L1074；查是否被后续 enter_plan 覆盖 |
| **耗尽未写 last_*** | 依赖 H1b：`turn>=max_turns` 或 exit_reason 均 checkpoint | 仅当 H1b 实测仍漏才考虑 agent_loop H2（默认不做） |
| Android 端误用 `nohup python agentmain --reflect` | 提示改用「会话内自主循环」 | 无（环境不支持独立进程） |

## 黑名单
- 🚫 禁止修改用户原话目标（objective），除非用户明确变更（用 `update_goal_objective`）；框架硬检查点亦禁改 objective。
- 🚫 禁止无限轮次或静默越过 budget / 协议 `max_turns` / 会话 `session_max_turns`。
- 🚫 禁止覆盖已收口（done_*）的状态文件用于新任务，应新建文件。
- 🚫 Android 端禁止使用 `nohup python agentmain --reflect`（无 python 命令，走会话内自主循环）。
- 🚫 **75 豁免仅 `in_goal_mode` 旗标活跃时有效**；禁止假定“跑 goal 协议就自动免 75”——必须 enter。
- 🚫 禁止改 `agentmain` 全局 `max_turns=80` 来抬 goal；只用 `enter_goal_mode` 会话级 120。
- 🚫 硬检查点禁止把 `status` 写成 `done_*`，禁止改写协议字段 `max_turns`（只写 `session_max_turns` / `last_*`）。
- 🚫 禁止用手改 JSON `status=running` 代替 `resume_goal`（会漏算 `paused_seconds` / 不 re-enter）。
- 🚫 禁止用 `report_goal_done` 做暂停；暂停必须 `pause_goal`（exit+clear_binding）。
- 🚫 禁止在 `paused` 状态下指望 `auto_tick` 推进（early-return `should_stop`）。
