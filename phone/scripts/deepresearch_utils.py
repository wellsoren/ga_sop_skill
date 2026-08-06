"""DeepResearch helpers for Android GA (SOP: DeepResearch_sop_android).
Path: ga/deepresearch_utils.py (same level as douyin_download.py).

Usage in code_run:
  from deepresearch_utils import (
      try_url, fetch_with_fallback, mirror_candidates,
      extract_text_from_html, extract_conclusion, parallel_fetch, parse_dag)
"""
from __future__ import annotations

import re
import urllib.request
from typing import Optional, Tuple, List, Callable

UA = "Mozilla/5.0 (compatible; DeepResearch/1.0; Android)"


def try_url(url: str, timeout: float = 6) -> Optional[Tuple[str, str]]:
    """Try one URL; return (body, url) or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return (body, url)
    except Exception:
        return None


def mirror_candidates(url: str) -> List[Tuple[str, float]]:
    """Build mirror list at call-time (fixes SOP bug of capturing free-var u at def-time)."""
    cands: List[Tuple[str, float]] = []
    if "github.com" in url and "api.github.com" not in url and "ghproxy" not in url:
        # ghproxy style: https://ghproxy.com/https://github.com/...
        cands.append(("https://ghproxy.com/" + url, 6))
    if "huggingface.co" in url and "hf-mirror" not in url:
        path = url.split("huggingface.co", 1)[-1]
        cands.append(("https://hf-mirror.com" + path, 6))
    return cands


_mirror_candidates = mirror_candidates  # 兼容旧名


def fetch_with_fallback(url: str, timeout: float = 15) -> Optional[Tuple[str, str]]:
    """Origin first, then mirrors, then longer origin retry."""
    result = try_url(url, min(timeout, 6))
    if result:
        return result
    for mirror_url, mirror_timeout in _mirror_candidates(url):
        result = try_url(mirror_url, mirror_timeout)
        if result:
            return result
    return try_url(url, timeout)


def extract_text_from_html(html: str, max_chars: int = 8000) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def extract_conclusion(output_txt_content: str, max_chars: int = 4000) -> str:
    content = output_txt_content or ""
    if "[结论]" in content:
        content = content.split("[结论]", 1)[1]
    # drop trailing debug-ish sections lightly
    content = re.sub(r"\n#{1,3}\s+调试.*", "", content, flags=re.S)
    content = content.strip()
    if not content:
        return "[结论] ERROR: empty output"
    return content[:max_chars]


def parallel_fetch(urls: List[str], join_timeout: float = 30) -> dict:
    """Micro parallel urllib fetch with join timeout (Android-safe, no Popen)."""
    import threading

    results = {}
    lock = threading.Lock()

    def worker(u):
        r = fetch_with_fallback(u)
        with lock:
            if r:
                body, used = r
                results[u] = {
                    "ok": True,
                    "used_url": used,
                    "chars": len(body),
                    "preview": extract_text_from_html(body, 200),
                }
            else:
                results[u] = {"ok": False, "error": "unreachable"}

    threads = []
    for u in urls:
        t = threading.Thread(target=worker, args=(u,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=join_timeout)
    return results


# --- dag helpers ---
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
