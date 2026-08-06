---
name: DeepResearch_sop_android
skill: DeepResearch_sop_android
domain: research
version: "1.3"
description: "Android端深度研究：DAG分解+混合并行（threading/urllib静态页并行 + webcdp JS串行）+自动镜像回退+SYNTH清洗。触发: DeepResearch/深度研究/ptsd模式/多源整合"
tags: [deepresearch, research, parallel, webcdp, android]
cc_quick: "DeepResearch方案C：Turn1建DAG → Turn2单code_run混合并行 → Turn3 SYNTH；WEB-static优先urllib"
cc_keywords: ["DeepResearch", "深度研究", "ptsd", "多源整合", "混合并行", "DAG研究", "镜像回退"]
tools: [code_run, file_read, file_write, file_patch, update_working_checkpoint]
# 进程内模块（非 tool 名）：webcdp / threading / urllib；utils 见 ga/deepresearch_utils.py
forbidden_tools: [Popen, nohup, subprocess.Popen]
tools_mode: lax
---

# DeepResearch SOP（Android端 · 方案C混合并行版）

> 场景：问题需要多来源信息整合（网页+本地文件+记忆库），单次检索无法完整回答。
> 适用范围：Android 终端 GA（ChaquoPy 进程内 exec，无独立 python3/Popen）。

**触发**：DeepResearch / 深度研究 / ptsd模式 / 多源整合。
**禁用**：单一来源、1-2步可完成的问题，直接做别套此SOP。

### CC 五大章映射（sop_standard）

| 约定章节 | 本文对应 |
|----------|----------|
| 一、前置条件 | §0 本机环境约束 + 资源冲突约束 |
| 二、能力总览 | 核心架构（混合并行）+ webcdp API 参考 |
| 三、快速参考 | 上方「快速参考」+ 工具入口 |
| 四、执行流程 | 阶段1 DAG → 阶段2 混合并行 → 阶段3 SYNTH；动态扩展/降级 |
| 五、验证 | 「验证」+ 失败模式速查 + 黑名单 + 最小落地示例 |

---

## 快速参考

```
1) 建 DAG：标注 WEB-static|WEB-js|LOCAL|MEMORY|CODE|SYNTH → 写 temp/<task>/dag.md + 各节点 context.json
2) 单 code_run 混合并行：WEB-static/LOCAL/MEMORY/CODE 线程池；WEB-js webcdp 串行（≤2）
3) 动态扩展：追加节点 ≤ 原始×2；失败写 [结论] ERROR
4) SYNTH：extract_conclusion 清洗 → 综合输出（禁止 code_run 内硬编码长报告）
```

**工具入口（可选）**：`ga/deepresearch_utils.py` 已封装 `try_url` / `fetch_with_fallback` / `mirror_candidates` / `extract_text_from_html` / `extract_conclusion` / `parallel_fetch` / `parse_dag`（call-time 镜像列表，无闭包 bug）。`code_run` 内直接 `from deepresearch_utils import …`（与 douyin_download 同级），或按下方模板粘贴进同一 code_run。

**🔴 CHECKPOINT · 建 DAG 后**：节点类型/依赖/并行组写完再进 Turn2；不确定 WEB 类型 → 默认 WEB-static，urllib 失败再降级 webcdp。

---

## 0. 本机环境约束

本SOP为 **Android终端 GA 运行环境** 定制，充分利用已验证的并行能力。

| 差异点 | Linux版SOP | Android版SOP（方案C） |
|--------|-----------|---------------------|
| 子进程模型 | `Popen([python3, 'agentmain.py'])` | ❌ `sys.executable`=`app_process64`，无独立python3 |
| 并行执行 | 多subagent Popen | ✅ **threading + urllib 并行**（静态WEB/本地/记忆/代码节点） |
| WEB-JS节点 | webcdp（不限） | webcdp 串行（单例浏览器，每轮最多2个WEB-js节点） |
| webcdp JS执行 | `web_execute_js(js)` | ✅ **`web_eval(js)`** |
| webcdp扫描 | `web_scan()` 返回dict | ✅ `web_scan()` 返回 **list[dict]** |

**关键能力**：
- Python `threading` + `exec(namespace独立)` = 真正并行 ✅ （已验证）
- `urllib` 并行抓网页 = 绕过webcdp单例，无并发限制 ✅ （已验证）
- webcdp 两角色(`fg`+`browser`) = 最多2个浏览器标签并发

---

## 核心架构（混合并行）

```
┌──────────────────────────────────────────────────────┐
│ 同一Agent，单code_run内完成所有子节点（混合并行）       │
│                                                       │
│ Turn 1: Main Agent 建DAG + 标注WEB-static/WEB-js       │
│         → 写入dag.md + 所有context.json + input.txt    │
│                                                       │
│ Turn 2: Main Agent → SubAgent们（单code_run内并行）     │
│         ┌─ WEB-static节点 → threading + urllib (并行)  │
│         ├─ LOCAL/MEMORY/CODE → threading (并行)        │
│         └─ WEB-js节点 → webcdp (串行，逐个)            │
│         全部完成后 → 收集结论 → 内存中判断扩展          │
│                                                       │
│ Turn 3: SYNTH（如有追加节点则先处理）                   │
└──────────────────────────────────────────────────────┘
```

**降级路径**：如并行执行出错或不适合，降级到方案A（code_run接力串行），逐节点执行。

---

## 阶段1：问题分解 → 初始DAG

### 节点类型（方案C新增WEB-static/WEB-js区分）

| 类型 | 触发场景 | 执行方式 | 工具 |
|------|---------|---------|------|
| **WEB-static** | 静态HTML页面（技术文档/PEP/RFC/博客/新闻正文） | 🟢 **并行** | `urllib + threading` |
| **WEB-js** | 需JS渲染（SPA/社交媒体/动态加载/登录墙后） | 🔴 **串行** | `webcdp.open_url → web_eval` |
| LOCAL | 本地PDF/代码/数据文件 | 🟢 **并行** | `file_read / pdftotext` |
| MEMORY | 记忆库/SOP/配置 | 🟢 **并行** | `file_read` |
| CODE | 需执行脚本获取结果 | 🟢 **并行** | `code_run` |
| SYNTH | 汇总（Main Agent自己做） | — | 在对话中直接合成 |

### WEB-static vs WEB-js 判断规则

Main Agent在规划DAG时，必须**预判每个WEB节点的类型**：

| 信号 | → 判断为 |
|------|---------|
| 域名含 `docs.python.org`, `peps.python.org`, `github.com`(README/wiki), `*.readthedocs.io`, `en.wikipedia.org`, `arxiv.org` | WEB-static |
| URL含 `.html` 且非登录墙后 | WEB-static |
| 博客平台(medium/dev.to/掘金/CSDN/博客园)文章页 | WEB-static |
| 域名含 `xiaohongshu.com`, `zhihu.com`, `weibo.com`, `twitter.com`, `bilibili.com` | WEB-js |
| URL含 `spa` / `app.` / 明显单页应用 | WEB-js |
| 不确定 | 默认 WEB-static，执行时urllib失败再降级webcdp |
| --- | --- |
| **🔌 镜像回退** | 本机无代理时，`mirror_candidates(url)` call-time 生成：GitHub→ghproxy | HuggingFace→hf-mirror；原站失败后再镜像、再长超时重试（禁模块级 `MIRROR_FALLBACK` 拼自由变量） |

### 🔍 建 DAG 前：种子 URL 批量可达性预检（1轮，必做）

种子 URL（搜索/推荐收集后）**先做 1 轮可达性批量探测再建 DAG**，区分「全局断网」vs「单点反爬」：

```python
# 对照组 = example.com(国外) + 163.com/baidu.com(国内)
# 结果判定：
#   - 国外对照全失败 + 国内OK   → 全局断网/墙 → 直接切「国内信源兜底」（见失败模式速查）
#   - 仅个别种子失败             → 正常建 DAG，失败节点走镜像/降级
for u in seeds + ['https://example.com/', 'https://www.163.com/']:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=5) as r:
            print('OK  ', u, r.status)
    except Exception as e:
        print('FAIL', u, type(e).__name__)
```

预检结果决定 DAG 信源构成：国外不可达时 **DAG 种子直接用国内可达信源**（见「国内信源兜底清单」），避免 9 节点全废后回头重找（实测代价 5-6 轮）。

### dag.md 格式（标注并行/串行）

```markdown
# DR: {用户问题一句话}
ROOT: {原始问题}

## 节点列表
- [N1] WEB-static | 子问题：Python 3.13文档说什么 | 依赖：无
- [N2] WEB-static | 子问题：PEP 703详情 | 依赖：无
- [N3] WEB-js    | 子问题：社区讨论热帖 | 依赖：N1
- [N4] MEMORY     | 子问题：本地记忆归纳 | 依赖：无
- [N5] SYNTH      | 汇总N1+N2+N3+N4 | 依赖：N1,N2,N3,N4

## 节点状态
N1: [ ] N2: [ ] N3: [ ] N4: [ ] N5: [ ]

## 执行计划
- 并行组1: [N1, N2, N4] （WEB-static + MEMORY，同轮并行）
- 串行组: [N3] （WEB-js，依赖N1，依赖满足后串行执行）
- SYNTH: [N5]
```

---

## 阶段2：混合并行执行

### 整体流程

```
Turn 1 (Main Agent):
  建DAG → 标注类型 → 创建所有节点目录+context.json+input.txt → 输出执行计划

Turn 2 (Main Agent → SubAgent们, 单code_run):
  ① 收集所有"依赖已满足"的节点
  ② 按类型分流：
       WEB-static + LOCAL + MEMORY + CODE → 并行线程池
       WEB-js → 串行队列（webcdp单例）
  ③ join所有线程 → 收集output.txt → dag.md标记完成
  ④ 动态评估：需追加节点？→ 有则追加，回到②
  ⑤ 无追加 → 在内存中准备SYNTH结论

Turn 3 (Main Agent):
  SYNTH → 综合输出最终答案
```

### 并行执行框架（核心代码模板）

以下代码在**单个code_run**中完成所有子节点：

```python
import os, json, threading, re
import urllib.request, urllib.error

AGENT_ROOT = '<GA根目录，如 Android 应用私有目录/files/ga>'  # 需自行配置为本机路径
TASK = 'dr_task'  # 实际任务目录名，如 dr_py313；与 temp/<TASK>/ 一致
TASK_DIR = os.path.join(AGENT_ROOT, 'temp', TASK)

# ============================================================
# 辅助：dag 解析 / 依赖 / 状态（模板最小实现，可按任务改）
# ============================================================
def parse_dag(dag_path):
    """解析 dag.md 节点列表。期望行：- [N1] WEB-static | 子问题：… | 依赖：无|N2,N3
    可选同行 URL：url=https://… 或 context.json 内提供 url。"""
    nodes, done = [], set()
    text = open(dag_path, encoding='utf-8').read()
    for line in text.splitlines():
        m = re.match(
            r'-\s*\[([A-Za-z0-9_]+)\]\s*([A-Za-z0-9_-]+)\s*\|\s*(.+?)'
            r'(?:\s*\|\s*依赖[：:]\s*([^\|]+))?(?:\s*\|\s*url=(\S+))?\s*$',
            line.strip())
        if not m:
            continue
        nid, ntype, rest, dep, url = m.groups()
        deps = []
        if dep and dep.strip() not in ('无', '-', 'None', ''):
            deps = [d.strip() for d in re.split(r'[,，\s]+', dep.strip()) if d.strip()]
        # 子问题字段：去掉前缀「子问题：」
        q = re.sub(r'^子问题[：:]\s*', '', rest.strip())
        nodes.append({'id': nid, 'type': ntype, 'question': q,
                      'deps': deps, 'url': url or ''})
    # 节点状态区：支持同行多标 N1: [ ] N2: [x]
    for line in text.splitlines():
        for sm in re.finditer(r'([A-Za-z0-9_]+)\s*:\s*\[([ xX✓])\]', line):
            if sm.group(2).strip():
                done.add(sm.group(1))
    return {'nodes': nodes, 'done': done}

def dependencies_met(node, done=None):
    done = done if done is not None else set()
    return all(d in done for d in node.get('deps') or [])

def update_all_dag_status(dag, results, dag_path=None):
    """把 results 里 ok 的节点标为完成；若给 dag_path 则回写状态行。"""
    for nid, r in (results or {}).items():
        if isinstance(r, dict) and r.get('ok'):
            dag.setdefault('done', set()).add(nid)
    if not dag_path:
        return
    lines = open(dag_path, encoding='utf-8').read().splitlines()
    out = []
    for line in lines:
        sm = re.match(r'([A-Za-z0-9_]+)\s*:\s*\[', line.strip())
        if sm and sm.group(1) in dag.get('done', set()):
            out.append(re.sub(r'\[\s*\]', '[x]', line, count=1))
        else:
            out.append(line)
    open(dag_path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')

# ============================================================
# 第0步：读取dag.md，获取所有节点信息
# ============================================================
dag = parse_dag(os.path.join(TASK_DIR, 'dag.md'))
# dag = {'nodes': [{'id':'N1','type':'WEB-static','url':'...','deps':[],...}], 'done': set()}

# ============================================================
# 第1步：并行执行 WEB-static + LOCAL + MEMORY + CODE 节点
# ============================================================
results = {}
errors = {}
lock = threading.Lock()

# ============================================================
# 镜像回退（call-time 生成镜像列表，禁止在列表字面量里拼接自由变量 u）
# ============================================================
# ❌ 错误：MIRROR_FALLBACK = [(lambda u: ..., [('原站',4), ('https://ghproxy.com/'+u ...)])]
#    列表在定义时求值，u 未绑定或绑错 → NameError / 错误镜像
# ✅ 正确：在 fetch_with_fallback(url) 内按 url 现算 candidates

def try_url(url, timeout=6):
    """尝试单个URL，成功返回(响应体, url)，失败返回None"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; DeepResearch/1.0; Android)'
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return (body, url)
    except Exception:
        return None

def mirror_candidates(url):
    """按目标 URL 现算镜像（call-time），返回 [(mirror_url, timeout), ...]"""
    cands = []
    if 'github.com' in url and 'api.github.com' not in url and 'ghproxy' not in url:
        cands.append(('https://ghproxy.com/' + url, 6))  # 保留完整 https:// 前缀
    if 'huggingface.co' in url and 'hf-mirror' not in url:
        path = url.split('huggingface.co', 1)[-1]
        cands.append(('https://hf-mirror.com' + path, 6))
    # wikipedia/google：无稳定镜像，依赖原站重试即可
    return cands

def fetch_with_fallback(url, timeout=15):
    """先试原站，不通则镜像，再长超时原站重试"""
    result = try_url(url, min(timeout, 6))
    if result:
        return result
    for mirror_url, mirror_timeout in mirror_candidates(url):
        result = try_url(mirror_url, mirror_timeout)
        if result:
            print(f"    ↪ 镜像命中: {mirror_url[:60]}")
            return result
    return try_url(url, timeout)

def subagent_worker(node):
    """并行子代理：读context.json → 依类型执行 → 写output.txt"""
    ndir = os.path.join(TASK_DIR, node['id'])
    
    # 第一步必须读context.json
    with open(os.path.join(ndir, 'context.json')) as f:
        ctx = json.load(f)
    
    ntype = node['type']
    
    try:
        if ntype == 'WEB-static':
            # urllib并行抓取（绕过webcdp单例限制），自动镜像回退
            fetch_result = fetch_with_fallback(node['url'])
            
            if fetch_result:
                html, used_url = fetch_result
                # 简易正文提取（去标签）
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                text = text[:8000]
                
                conclusion = f"[结论] {text}\n\n[实际来源] {used_url}"
            else:
                # 所有镜像均失败，降级为错误标记
                conclusion = f"[结论] 所有来源均不可达(含镜像)，请检查网络\n[原始URL] {node['url']}"
            
        elif ntype == 'LOCAL':
            with open(node['file_path']) as f:
                content = f.read()
            conclusion = f"[结论] {content[:4000]}"
            
        elif ntype == 'MEMORY':
            with open(node['memory_path']) as f:
                content = f.read()
            conclusion = f"[结论] {content[:4000]}"
            
        elif ntype == 'CODE':
            # 用code_run执行，结果即为结论
            conclusion = f"[结论] 代码执行结果..."
        
        # 写入output.txt
        output_file = ctx['output_file']
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(conclusion)
        
        with lock:
            results[node['id']] = {'ok': True, 'size': len(conclusion)}
            
    except Exception as e:
        with lock:
            errors[node['id']] = str(e)
        # 写错误标记
        with open(ctx['output_file'], 'w') as f:
            f.write(f"[结论] ERROR: {e}")
        results[node['id']] = {'ok': False, 'error': str(e)}

# 分离并行节点和串行节点（依赖用 dag['done']）
_done = dag.get('done') or set()
parallel_nodes = [n for n in dag['nodes']
                  if n['type'] in ('WEB-static', 'LOCAL', 'MEMORY', 'CODE')
                  and dependencies_met(n, _done)]
webjs_nodes = [n for n in dag['nodes']
               if n['type'] == 'WEB-js' and dependencies_met(n, _done)]

# ═══ 启动并行线程 ═══
threads = []
for node in parallel_nodes:
    t = threading.Thread(target=subagent_worker, args=(node,))
    t.start()
    threads.append(t)

# ═══ 并行等待完成（必须带 timeout，防 code_run 提前返回杀线程）═══
JOIN_TIMEOUT = 90  # 整组上限秒；单 URL 超时已在 try_url 内控制
for t in threads:
    t.join(timeout=JOIN_TIMEOUT)
alive = [t for t in threads if t.is_alive()]
if alive:
    print(f"⚠️ {len(alive)} 线程超时未结束，继续收集已写盘 output")

print(f"✅ 并行组完成: {len(results)}/{len(parallel_nodes)}")
# 🔴 CHECKPOINT · 并行组后：确认 results/errors 与 output.txt 一致，再开 WEB-js 串行

# ============================================================
# 第2步：串行执行 WEB-js 节点（webcdp单例）
# ============================================================
for node in webjs_nodes:
    ndir = os.path.join(TASK_DIR, node['id'])
    with open(os.path.join(ndir, 'context.json')) as f:
        ctx = json.load(f)
    
    try:
        import webcdp
        webcdp.open_url(node['url'])
        text = webcdp.web_eval("""
            (() => {
                const main = document.querySelector('article') || document.querySelector('.body') || document.body;
                return main.innerText.substring(0, 8000);
            })()
        """)
        conclusion = f"[结论] {text}"  # 实际需LLM总结
        
        with open(ctx['output_file'], 'w') as f:
            f.write(conclusion)
        results[node['id']] = {'ok': True}
        
    except Exception as e:
        # webcdp失败→降级urllib
        print(f"  ⚠️ webcdp失败({e})，降级urllib")
        subagent_worker(node)

# ============================================================
# 第3步：更新dag.md状态
# ============================================================
update_all_dag_status(dag, results, os.path.join(TASK_DIR, 'dag.md'))

# ============================================================
# 第4步：收集所有output.txt结论
# ============================================================
conclusions = {}
for node in dag['nodes']:
    if node['type'] == 'SYNTH':
        continue
    out = os.path.join(TASK_DIR, node['id'], 'output.txt')
    if os.path.exists(out):
        with open(out) as f:
            conclusions[node['id']] = extract_conclusion(f.read())

print(f"\n📋 收集到 {len(conclusions)} 个子结论")

# ============================================================
# 第5步：动态扩展判断（Main Agent在对话中完成）
# ============================================================
# → 评估conclusions → 是否需追加节点？
# → 如需追加，更新dag.md，回到第1步
# → 如无需追加或已达上限，进入SYNTH
```

### WEB-static 正文提取函数

```python
import re

def extract_text_from_html(html, max_chars=8000):
    """urllib抓取的HTML → 纯文本"""
    # 移除不可见元素
    for tag in ['script', 'style', 'nav', 'footer', 'header', 'noscript']:
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # 去标签
    text = re.sub(r'<[^>]+>', ' ', html)
    # 合并空白
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text[:max_chars]
```

### 完整结论格式辅助

```python
def format_conclusion(sub_question, raw_text):
    """将原始文本格式化为标准结论"""
    # 实际由LLM在对话中总结，此处写文件只是中间产物
    return f"[结论] 针对「{sub_question}」：\n\n{raw_text}"
```

---

## webcdp API 参考（仅用于WEB-js节点）

| 函数 | 说明 |
|------|------|
| `open_url(url)` | 一步到位打开网页并CDP驱动，默认前台可见 |
| `web_eval(js)` | Runtime.evaluate，返回JS值（❌非`web_execute_js`） |
| `web_scan()` | 返回 `list[dict]`，每个dict含 `{tag, role, text, href, type, bbox}` |
| `web_shot()` | 截图存png，返回文件路径 |
| `web_click(sel)` | CSS selector → `querySelector+click` |
| `web_type(text, sel)` | JS设值 + dispatch input/change |
| `web_cookies(domain)` | Network.getAllCookies |

**重要纠正**：
- ❌ `web_execute_js()` → ✅ `web_eval()`
- ❌ `web_scan()`返回dict → ✅ 返回 **list[dict]**

**WEB-js节点标准流程**：
```python
import webcdp
webcdp.open_url('https://example.com/spa-page')
text = webcdp.web_eval("""
    (() => {
        const main = document.querySelector('article') || document.querySelector('.body') || document.body;
        return main.innerText.substring(0, 8000);
    })()
""")
# → 在对话中LLM总结 → 写output.txt
```

---

## 阶段3：综合输出（SYNTH）

所有节点[✓]后，Main Agent执行SYNTH：
1. 读取所有 `output.txt`，**必须清洗**（见清洗规范）
2. 按DAG拓扑顺序综合
3. 报告写入时**禁止code_run内硬编码长字符串**，改用从output.txt拼接
4. 输出最终答案

### output.txt 清洗规范

```python
import re

def extract_conclusion(output_txt_content, max_chars=4000):
    """从output.txt提取纯结论，去除调试内容"""
    content = output_txt_content
    markers = ['[结论]', '---\n\n## 针对', '---\n\n## 一、', '## 针对子问题', '\n##']
    idx = -1
    for m in markers:
        idx = content.find(m)
        if idx >= 0:
            break
    conclusion = content[idx:] if idx >= 0 else content

    conclusion = re.sub(r'\*\*LLM Running.*?\n', '', conclusion)
    conclusion = re.sub(r'<summary>.*?</summary>', '', conclusion, flags=re.DOTALL)
    conclusion = re.sub(r'🛠️.*?(?=\n\n|\Z)', '', conclusion, flags=re.DOTALL)
    conclusion = re.sub(r'````text\n.*?````', '', conclusion, flags=re.DOTALL)
    conclusion = re.sub(r'\[ROUND END\].*', '', conclusion, flags=re.DOTALL)
    conclusion = re.sub(r'\n{3,}', '\n\n', conclusion).strip()

    if len(conclusion) > max_chars:
        cut = conclusion.rfind('\n\n', 0, max_chars)
        cut = cut if cut > 0 else max_chars
        conclusion = conclusion[:cut] + "\n\n> *（内容已截断，完整结论见原始output.txt）*"
    return conclusion
```

**报告过长处理**：
- 动态上限：先统计各节点实际长度，默认不截断
- 总报告超80KB时才压缩次要节点至3000字

---

## SubAgent行为规范

单个subagent_worker线程内：

1. **第一步必须读 `context.json`**，获取绝对路径和上下文
2. 根据节点类型选工具：
   - **WEB-static**：`urllib.request` 抓取 → `extract_text_from_html` → LLM总结
   - **WEB-js**：`webcdp.open_url()` → `web_eval(JS提取)` → LLM总结。失败则降级urllib
   - **LOCAL**：`file_read` → 总结
   - **MEMORY**：`file_read` → 总结
   - **CODE**：`code_run` → 整理输出
3. 结论写入 `context.json` 指定的 `output_file`（绝对路径）
4. **结论格式**：
   ```
   [结论] {针对sub_question的直接回答，≥2-3句，≤500字}
   ```
   - ❌ 禁止只写一句话摘要
   - ✅ 每个要点独立成段展开
5. 异常处理：捕获所有异常，写 `[结论] ERROR: {e}` 到output.txt

---

## 动态扩展判断

Main Agent收集结论后评估：

| 问题 | 行动 |
|------|------|
| 已有结论足以回答根问题？ | → 进入SYNTH |
| 某结论引出新必要子问题？ | → 追加节点到dag.md，类型标注清楚 |
| 某节点结论为空/失败？ | → 检查日志，决定重试或跳过 |
| 关键理论/论文值得深入？ | → 追加深化节点 |
| 结论间存在矛盾？ | → 追加对比分析节点 |

**死循环防护**：追加节点不超过原始节点数的2倍；同一子问题不重复追加。

---

## 资源冲突约束

| 资源 | 并行限制 | 说明 |
|------|---------|------|
| WEB-static (urllib) | ✅ 无限制 | 每线程独立HTTP连接，完全并行 |
| WEB-js (webcdp) | 🔴 最多2并发 | fg+browser两角色，**必须串行**避免tab抢占 |
| LOCAL读 | ✅ 无限制 | 只读，线程安全 |
| MEMORY读 | ✅ 无限制 | 只读，线程安全 |
| CODE | ✅ 无限制 | 各自exec(namespace)，完全隔离 |
| output.txt写 | ✅ 无限制 | 不同文件路径，线程安全 |
| 线程安全 | ✅ | `threading.Lock` 保护共享写操作(dag.md/results dict) |

---

## 方案A降级路径

以下情况启用**方案A（code_run接力串行）**：

| 触发条件 | 处理 |
|---------|------|
| urllib全部失败且无webcdp连接 | 逐节点code_run接力 |
| 线程异常超3个 | 切换串行 |
| Main Agent评估并行收益小（≤2节点） | 直接串行更简单 |
| WEB-js节点超2个且均需精确视觉交互 | 逐节点code_run接力，每轮1个WEB-js |

降级时执行方案A标准流程：每个节点独立code_run → 读context → 执行 → 写output → 标记dag → 下一节点。

---

## 典型坑（Android版）

1. **input.txt禁止塞原文**：大文件给路径，让SubAgent自己读
2. **parent_conclusions精简**：传200字内
3. **不要尝试Popen**：`sys.executable`=`app_process64`，不是python3
4. **web_eval不是web_execute_js**：本机API名不同
5. **web_scan返回list**，不是dict
6. **WEB-static优先urllib**：不必开webcdp，更快且可并行
7. **urllib抓取必须设User-Agent**：部分网站拒绝无UA的请求
8. **WEB-js失败立降级urllib**：不重试webcdp，节省时间
9. **线程join必须设超时或全部join**：防止code_run提前返回杀死线程
10. **SYNTH由Main Agent在对话中完成**：不启动SubAgent
11. **dag.md所有output_file用绝对路径**：线程间通过文件系统通信
12. **Node ID唯一且简短**：N1/N2/N3...，避免特殊字符

---

## 失败模式速查（三段式）

| 失败现象 | 根因 | 处置 |
|---------|------|------|
| urllib 全失败 + 无 webcdp | 无网/TLS/UA 被拒 | 方案A串行；`mirror_candidates(url)` 换镜像；写 ERROR 跳过非关键节点 |
| **全局断网**（example.com 国外对照全失败 + 163/baidu 国内OK） | 网络策略/墙（非单点反爬） | **不要**逐节点镜像/重试（全部无效）；直接按「国内信源兜底清单」重建 DAG，切国内源 |
| 镜像 URL 全错/NameError | 模块级列表拼自由变量 `u` | 改用 call-time `mirror_candidates`；见黑名单 |
| 线程异常 >3 | 共享状态竞态/超时 | 切方案A串行；`lock` 保护 results；join 设 timeout |
| webcdp 打开失败/超时 | 单例忙/登录墙 | **立即**降级 urllib，不重试 webcdp；登录墙请用户顶栏登录 |
| output.txt 空/无 [结论] | SubAgent 未写盘或崩溃 | 读 errors；重试 1 次或标记跳过；SYNTH 注明缺失源 |
| 动态扩展爆炸 | 追问无上限 | 追加 ≤ 原始节点×2；同子问题不重复 |
| code_run 提前返回 | 未 join 线程 | 全部 `t.join(timeout=…)` 后再读 output |
| HTML 噪声过大 | 未抽正文 | 必走 `extract_text_from_html`；结论 ≤500 字要点段 |

**🔴 CHECKPOINT · 降级前**：记录触发条件（上表哪一行）到 `temp/<task>/degrade_log.txt`，再切方案A。

### 🌐 国内信源兜底清单（国外不可达时直接替换 DAG 种子）

2026-08 实测（端侧AI Agent 研究任务验证）可直连、内容真实：

| 信源 | 类型 | 用法/备注 |
|------|------|------|
| aihot API `https://aihot.virxact.com/api/public/items?q=关键词` | AI资讯聚合（中英文+中文summary） | 无需key；多关键词轮询（Agent/智能体/on-device/local/Gemini/推理…）后按 title 去重；外部URL不可达时 `summary` 直接作素材 |
| 网易科技 `https://www.163.com/tech/` + 文章页 `/tech/article/*.html` | 门户新闻 | urllib 可抓，正则提取正文 |
| IT之家 `https://www.ithome.com/` | 科技媒体 | 文章页可抓 |
| InfoQ `https://www.infoq.cn/` | 技术媒体 | 首页含大量 AI/Agent 文章链接，文章页可抓 |
| 华为官网 consumer.huawei.com / 凤凰 tech.ifeng.com | 厂商/门户 | 可抓（注意JS壳/产品页链接多） |

经验：百度搜索间歇性反爬（UA+休息可重试）；量子位 qbitai.com 403；腾讯 news.qq.com 为 JS 壳（链接少）；豆瓣/知乎直连困难。

---

## 黑名单 / GA 红线

| ❌ 禁止 | 原因 |
|--------|------|
| `Popen` / `subprocess` 起 python / `nohup python` | Android 无独立 python3，`sys.executable=app_process64` |
| 把整篇原文塞进 `input.txt` | 撑爆上下文；只传路径+子问题 |
| WEB-js 无上限并发 / 并行抢 tab | webcdp 单例，最多 2，**必须串行** |
| 失败后反复重试同一 webcdp URL | 浪费预算；一次失败立刻 urllib 降级 |
| SYNTH 用 SubAgent / code_run 硬编码长报告 | Main Agent 对话综合；从 output.txt 拼接 |
| 改 `dag.md` 时用相对 `output_file` | 线程靠绝对路径通信 |
| 单一来源/1-2 步问题套本 SOP | 直接检索/回答，勿建 DAG |
| 未 join 就结束 code_run | 子线程被杀，output 残缺 |
| 调用不存在的 `web_execute_js` | 本机 API 为 `web_eval` |
| 无 User-Agent 的 urllib | 易被拒；用 DeepResearch UA |
| 在模块级列表字面量里用自由变量 `u` 拼镜像 | 定义时求值 → NameError/错误 URL；必须 call-time `mirror_candidates(url)` |
| `t.join()` 不设 timeout | 慢节点拖死整轮；用 `join(timeout=…)` 并检查 `is_alive()` |

---

## 验证

| 检查项 | 通过标准 |
|--------|---------|
| DAG 可解析 | 每节点有 type/依赖；并行组与串行组分开 |
| 并行落地 | 单 code_run 内 ≥2 个 WEB-static/LOCAL 线程完成并写 output |
| 结论格式 | 各 `output.txt` 含 `[结论]` 且非空 |
| 失败可观测 | 异常节点为 `[结论] ERROR: …` 或 degrade_log 有记录 |
| SYNTH | 最终答案引用多源，无调试噪声（经 extract_conclusion） |
| 环境红线 | 全程无 Popen/nohup；WEB-js ≤2 且串行 |
| 镜像 call-time | 无模块级 `u` 拼接；微测 `temp/dr_opt_work/micro_test_result.json` pass=true 可作回归参考 |
| join 超时 | 并行组 `t.join(timeout=…)` + `is_alive()` 处理 |

### 回归微测（可选，改抓取/镜像/清洗后跑）

```python
# code_run 内（ga/deepresearch_utils.py，与 douyin_download 同级）：
from deepresearch_utils import (
    parallel_fetch, extract_conclusion, mirror_candidates, parse_dag, dependencies_met)
assert mirror_candidates('https://github.com/a/b')  # call-time 非空
assert not mirror_candidates('https://example.com/')
r = parallel_fetch(['https://example.com/'], join_timeout=20)
assert any(v.get('ok') for v in r.values())
# extract_conclusion 剥掉前缀 [结论]，保留正文；空输出 → ERROR
assert 'ok' in extract_conclusion('[结论] ok\ndebug noise')
assert 'ERROR' in extract_conclusion('')
assert callable(parse_dag) and callable(dependencies_met)
print('regression OK', r)
```

正式路径：`ga/deepresearch_utils.py`。优化期证据可仍写 `temp/dr_opt_work/micro_test_result.json`（期望 `pass: true`, `ok_count >= 1`）。

**🔴 CHECKPOINT · 收口前**：验证表各项自检通过再交付；任一项失败 → 补跑或降级说明，禁止静默交差。

---

## 最小落地示例

### 执行摘要（Python 3.13 vs 3.12新特性研究）

```
Turn 1: Main Agent
  → 建dag.md: N1=WEB-static(python docs), N2=WEB-static(PEP 703), N3=SYNTH
  → 写入所有context.json + input.txt
  → 标注：N1、N2均为WEB-static，可并行

Turn 2: 混合并行执行（单个code_run）
  → 并行组: threading.Thread(N1) + threading.Thread(N2), urllib抓取
  → join等待 ~8s（串行需~15s）
  → 收集2个结论 → 评估无需追加 → 准备SYNTH

Turn 3: SYNTH
  → 读取output.txt → 清洗 → 综合 → 输出最终答案
```

### 产出目录结构

```
temp/dr_test/
  dag.md              ← 规划 + 状态 + 执行计划
  N1/
    context.json      ← 子任务上下文（含绝对路径output_file）
    input.txt         ← 目标+约束
    output.txt        ← SubAgent检索结论
  N2/
    context.json
    input.txt
    output.txt
  N3/
    output.txt        ← SYNTH合成结论
```
