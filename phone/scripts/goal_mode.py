"""goal_mode — Android facade 优先 + reflect 兼容

协议: init(_reflect_args) / check() -> str|None / on_done(result)
Android 主路径: start_goal → 每轮 auto_tick(path) → 可选 heartbeat → finalize/stop_goal
desktop reflect/nohup: 仅桌面；Android 无独立 python 进程，勿 nohup。

lifecycle: start_goal / stop_goal / pause_goal / resume_goal / update_goal_objective /
           status / finalize / heartbeat / auto_tick / clear_binding
"""
import json, os, time, tempfile

INTERVAL = 30          # 空闲时每 30s check 一次
_MAX_DONE = 500        # done_prompt / last_summary 截断
_MIN_BUDGET = 600

GOAL_STATE = 'goal_state.json'
_state = {}
_handler = None        # 模块短期绑定的会话 handler


def init(args):
    """agentmain 启动/热重载时调用; args 来自 --KEY value 传参"""
    global GOAL_STATE
    GOAL_STATE = os.path.abspath(args.get('GOAL_STATE', GOAL_STATE))
    _load()


def _load_from(path):
    """读指定 path 的 state dict；文件不存在 → FileNotFoundError。"""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'goal state not a dict: {path}')
    return data


def _save_to(path, data):
    """原子写盘到 path：同目录临时文件 + os.replace。"""
    path = os.path.abspath(path)
    directory = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.goal_', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # 若 path 即全局 GOAL_STATE，同步缓存
    global _state, GOAL_STATE
    try:
        if GOAL_STATE and os.path.abspath(GOAL_STATE) == path:
            _state = dict(data)
    except Exception:
        pass


def _load():
    global _state
    try:
        _state = _load_from(GOAL_STATE)
    except FileNotFoundError:
        raise RuntimeError(f'goal_state.json 不存在: {GOAL_STATE} 请先按 SOP 写入')


def _save():
    _save_to(GOAL_STATE, _state)


def _clear_handler():
    global _handler
    _handler = None


def clear_binding(path=None):
    """清模块 handler 绑定。path 给定时仅 GOAL_STATE==path 才清，否则 no-op。

    返回 True 表示已清除（或 path is None 时无条件清），False 表示 path 守卫 no-op。
    turn_end 必须用 clear_binding(path=path)，禁止用 status() 推断。
    """
    global _handler, GOAL_STATE
    if path is None:
        _clear_handler()
        return True
    try:
        if not GOAL_STATE:
            return False
        if os.path.abspath(str(GOAL_STATE)) != os.path.abspath(str(path)):
            return False
    except Exception:
        return False
    _clear_handler()
    return True


def _obs_active(handler):
    if handler is None:
        return False
    if not hasattr(handler, '_in_goal_mode'):
        return handler is _handler and _handler is not None
    try:
        v = handler._in_goal_mode()
        return v is not None
    except Exception:
        return False


def _coerce_handler(handler):
    """一层 unwrap：GenericAgent → agent.handler；已有 enter 则原样。None→None。"""
    if handler is None:
        return None
    if hasattr(handler, 'enter_goal_mode'):
        return handler
    inner = getattr(handler, 'handler', None)
    if inner is not None and hasattr(inner, 'enter_goal_mode'):
        print('[goal_mode] unwrap: agent→handler')
        return inner
    raise TypeError(
        'handler needs enter_goal_mode; Android: android_entry.agent.handler (not agent)'
    )


def _leak_guard_session(handler, target_path, reason=''):
    """finalize/stop 后 path 作用域会话泄漏守卫。返回 tag 或 None；异常只 print 不抛。"""
    if handler is None or not target_path:
        return None
    tag = None
    try:
        tp = os.path.abspath(str(target_path))
        working = getattr(handler, 'working', None)
        if not isinstance(working, dict):
            working = None
        active = working.get('in_goal_mode') if working is not None else None
        active_s = str(active).strip() if active is not None else ''

        if active_s:
            try:
                ap = os.path.abspath(active_s)
            except Exception:
                ap = active_s
            if ap == tp:
                # 同 path 仍 active → 再 exit 恢复 prev
                if hasattr(handler, 'exit_goal_mode'):
                    handler.exit_goal_mode(reason=reason or 'leak_guard')
                tag = 'forced_exit'
            else:
                # 外键 goal：不碰
                tag = 'skip_foreign'
            return tag

        # 无 active：orphan prev 仅当 max_turns 仍为 goal 硬顶 120
        if working is not None and '_goal_prev_max_turns' in working:
            try:
                cur = int(getattr(handler, 'max_turns', 0) or 0)
            except Exception:
                cur = 0
            if cur == 120:
                try:
                    prev = working.pop('_goal_prev_max_turns')
                    handler.max_turns = int(prev)
                    tag = 'restored_orphan_prev'
                except Exception as e:
                    print(f'[goal_mode] leak_guard orphan restore failed: {e}')
            else:
                tag = 'skip_orphan_not_goal_cap'

        # 幽灵旗标：键在但值为空
        if working is not None and 'in_goal_mode' in working:
            v = working.get('in_goal_mode')
            if v is None or (isinstance(v, str) and not str(v).strip()):
                working.pop('in_goal_mode', None)
                if tag is None:
                    tag = 'cleared_flag'
    except Exception as e:
        print(f'[goal_mode] leak_guard error: {e}')
    return tag


def _safe_exit(reason='', handler=None):
    """仅路径匹配时 exit；path_mismatch 不误清对方旗标。返回 exit_skipped 或 None。"""
    h = _handler if handler is None else handler
    if h is None:
        return None
    try:
        if hasattr(h, '_in_goal_mode'):
            try:
                active = h._in_goal_mode()
            except Exception:
                active = None
            if active is not None:
                if os.path.abspath(str(active)) != os.path.abspath(GOAL_STATE):
                    return 'path_mismatch'
            h.exit_goal_mode(reason)
        else:
            if _handler is not h:
                return 'path_mismatch'
            h.exit_goal_mode(reason)
    except Exception as e:
        print(f'[goal_mode] exit_goal_mode failed: {e}')
    return None


def _goal_elapsed(data, now=None):
    """与 auto_tick / 注入共用。旧 state 缺字段视为 0。"""
    now = time.time() if now is None else now
    start = float(data.get('start_time') or now)
    paused_seconds = float(data.get('paused_seconds') or 0)
    paused_at = float(data.get('paused_at') or 0)
    extra = (now - paused_at) if paused_at > 0 else 0.0
    return max(0.0, now - start - paused_seconds - extra)


def _map_done_status(reason):
    """reason → 终态 status。优先级 success > blocked > budget > turns > manual。"""
    r = str(reason or '').strip().lower()
    if not r:
        return 'done_manual'
    # success
    for k in ('done_success', 'success', 'completed'):
        if k in r:
            return 'done_success'
    # blocked（优先于 manual）
    for k in ('done_blocked', 'blocked'):
        if k in r:
            return 'done_blocked'
    # budget
    for k in ('done_budget', 'budget_exhausted', 'budget', 'timeout'):
        if k in r:
            return 'done_budget'
    # turns
    for k in ('done_turns', 'max_turns', 'turns'):
        if k in r:
            return 'done_turns'
    return 'done_manual'


def _validate_start(objective, budget_seconds, max_turns):
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError('objective must be non-empty str')
    if isinstance(budget_seconds, bool) or not isinstance(budget_seconds, (int, float)):
        raise ValueError('budget_seconds must be int/float >= 600')
    if budget_seconds < _MIN_BUDGET:
        raise ValueError(f'budget_seconds must be >= {_MIN_BUDGET}')
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
        raise ValueError('max_turns must be int >= 1')


def start_goal(objective, *, state_path=None, budget_seconds=3600, max_turns=200, handler=None):
    """创建 running state 并可选 enter_goal_mode；拒绝覆盖与二次绑定。"""
    global GOAL_STATE, _state, _handler
    _validate_start(objective, budget_seconds, max_turns)
    if _handler is not None:
        raise RuntimeError('handler already bound; call stop_goal first')

    path = os.path.abspath(state_path if state_path is not None else 'goal_state.json')
    if os.path.exists(path):
        raise FileExistsError(f'state file already exists: {path}')

    new_state = {
        'objective': objective,
        'budget_seconds': budget_seconds,
        'start_time': time.time(),
        'turns_used': 0,
        'max_turns': max_turns,
        'status': 'running',
        'done_prompt': '',
        'last_agent_turn': 0,
        'last_interrupt_reason': '',
        'last_summary': '',
        'last_checkpoint_at': 0.0,
        'session_max_turns': None,
        'agent_turns': 0,
        'paused_at': 0.0,
        'paused_seconds': 0.0,
        'objective_version': 1,
        'objective_updated_at': 0.0,
    }

    prev_path, prev_state = GOAL_STATE, _state
    GOAL_STATE = path
    _state = new_state
    try:
        _save()
    except Exception:
        GOAL_STATE, _state = prev_path, prev_state
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
        raise

    if handler is not None:
        handler = _coerce_handler(handler)
        try:
            handler.enter_goal_mode(path)
            _handler = handler
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            _handler = None
            GOAL_STATE, _state = prev_path, prev_state
            raise

    active = False
    if handler is not None:
        if hasattr(handler, '_in_goal_mode'):
            try:
                v = handler._in_goal_mode()
                active = v is not None and os.path.abspath(str(v)) == path
            except Exception:
                active = True
        else:
            active = True

    return {
        'state': dict(_state),
        'state_path': path,
        'handler_bound': _handler is not None,
        'handler_active': active,
    }


def stop_goal(reason='manual', *, handler=None):
    """running→映射终态；缺文件不抛；无论写盘结果都尝试安全 exit 并清绑定。"""
    global _state
    out = {
        'status': 'missing',
        'state_path': os.path.abspath(GOAL_STATE) if GOAL_STATE else None,
        'handler_bound': False,
        'handler_active': False,
        'missing': False,
    }
    h = handler if handler is not None else _handler
    try:
        _load()
        if _state.get('status') == 'running':
            _state['status'] = _map_done_status(reason)
            _save()
        # 非 running：不覆盖 status（幂等）
        out['status'] = _state.get('status')
        out['state'] = dict(_state)
    except RuntimeError:
        out['missing'] = True
        out['status'] = 'missing'

    skipped = _safe_exit(reason=reason or 'manual', handler=h)
    if skipped:
        out['exit_skipped'] = skipped
    clear_binding(path=None)  # 无条件清模块绑定
    sp = out.get('state_path')
    lg = _leak_guard_session(h, sp, reason=reason or 'manual')
    if lg:
        out['leak_guard'] = lg
    out['handler_bound'] = False
    out['handler_active'] = _obs_active(h)
    return out


def pause_goal(reason='user', *, handler=None):
    """running → paused。必须 exit_goal + clear_binding。幂等：已 paused 只确保 exit。"""
    global _state
    out = {
        'status': 'missing',
        'state_path': os.path.abspath(GOAL_STATE) if GOAL_STATE else None,
        'handler_bound': False,
        'handler_active': False,
        'missing': False,
        'error': '',
        'paused_at': 0.0,
    }
    h = handler if handler is not None else _handler
    try:
        _load()
    except RuntimeError:
        out['missing'] = True
        skipped = _safe_exit(reason=reason or 'paused', handler=h)
        if skipped:
            out['exit_skipped'] = skipped
        clear_binding(path=None)
        out['handler_active'] = _obs_active(h)
        return out

    st = _state.get('status')
    now = time.time()
    if st == 'running':
        _state['status'] = 'paused'
        _state['paused_at'] = now
        _state['last_interrupt_reason'] = str(reason or 'user')[:200]
        _save()
    elif st == 'paused':
        pass  # 幂等：只确保 exit
    else:
        out['error'] = f'terminal_status={st}'
        out['status'] = st
        out['state'] = dict(_state)
        skipped = _safe_exit(reason=reason or 'paused', handler=h)
        if skipped:
            out['exit_skipped'] = skipped
        clear_binding(path=None)
        out['handler_active'] = _obs_active(h)
        return out

    out['status'] = _state.get('status')
    out['paused_at'] = float(_state.get('paused_at') or 0)
    out['state'] = dict(_state)
    out['state_path'] = os.path.abspath(GOAL_STATE) if GOAL_STATE else out['state_path']
    skipped = _safe_exit(reason=reason or 'paused', handler=h)
    if skipped:
        out['exit_skipped'] = skipped
    clear_binding(path=None)
    lg = _leak_guard_session(h, out.get('state_path'), reason=reason or 'paused')
    if lg:
        out['leak_guard'] = lg
    out['handler_bound'] = False
    out['handler_active'] = _obs_active(h)
    return out


def resume_goal(*, handler=None):
    """paused|done_blocked → running。累计 paused_seconds；enter_goal_mode。"""
    global _state
    out = {
        'status': 'missing',
        'state_path': os.path.abspath(GOAL_STATE) if GOAL_STATE else None,
        'handler_bound': False,
        'handler_active': False,
        'missing': False,
        'error': '',
        'last_summary': '',
    }
    h = handler if handler is not None else _handler
    try:
        _load()
    except RuntimeError:
        out['missing'] = True
        return out

    st = _state.get('status')
    if st == 'running':
        out['status'] = 'running'
        out['state'] = dict(_state)
        out['last_summary'] = str(_state.get('last_summary') or '')
        # 已 running：尽量 re-bind
        path = os.path.abspath(GOAL_STATE) if GOAL_STATE else None
        if h is not None and path and hasattr(h, 'enter_goal_mode'):
            try:
                h.enter_goal_mode(path)
                out['handler_bound'] = True
            except Exception as e:
                out['error'] = f'enter_failed:{e}'
        out['handler_active'] = _obs_active(h)
        return out

    if st not in ('paused', 'done_blocked'):
        out['error'] = f'cannot_resume_from={st}'
        out['status'] = st
        out['state'] = dict(_state)
        return out

    now = time.time()
    paused_at = float(_state.get('paused_at') or 0)
    if paused_at > 0:
        _state['paused_seconds'] = float(_state.get('paused_seconds') or 0) + max(0.0, now - paused_at)
        _state['paused_at'] = 0.0
    if st == 'done_blocked':
        dp = str(_state.get('done_prompt') or '').strip()
        if dp and not str(_state.get('last_summary') or '').strip():
            _state['last_summary'] = dp[:_MAX_DONE]
        _state['done_prompt'] = ''
    _state['status'] = 'running'
    _save()

    path = os.path.abspath(GOAL_STATE) if GOAL_STATE else None
    out['status'] = 'running'
    out['state'] = dict(_state)
    out['state_path'] = path
    out['last_summary'] = str(_state.get('last_summary') or '')
    if h is not None and path and hasattr(h, 'enter_goal_mode'):
        try:
            h.enter_goal_mode(path)
            if hasattr(h, 'working') and isinstance(h.working, dict):
                h.working['goal_force_fidelity'] = True
            out['handler_bound'] = True
        except Exception as e:
            out['error'] = f'enter_failed:{e}'
    out['handler_active'] = _obs_active(h)
    return out


def update_goal_objective(new_objective, *, handler=None):
    """running|paused 可改 objective；version+1；不重置 start_time/turns/budget。"""
    global _state
    out = {
        'status': 'missing',
        'state_path': os.path.abspath(GOAL_STATE) if GOAL_STATE else None,
        'objective_version': 0,
        'error': '',
        'missing': False,
    }
    obj = str(new_objective or '').strip()
    if not obj:
        out['error'] = 'empty_objective'
        return out
    h = handler if handler is not None else _handler
    try:
        _load()
    except RuntimeError:
        out['missing'] = True
        return out

    st = _state.get('status')
    if st not in ('running', 'paused'):
        out['error'] = f'cannot_update_from={st}'
        out['status'] = st
        return out

    now = time.time()
    _state['objective'] = obj
    ver = int(_state.get('objective_version') or 1) + 1
    _state['objective_version'] = ver
    _state['objective_updated_at'] = now
    _save()

    if h is not None and hasattr(h, 'working') and isinstance(h.working, dict):
        h.working['goal_force_fidelity'] = True

    out['status'] = st
    out['objective_version'] = ver
    out['state'] = dict(_state)
    out['state_path'] = os.path.abspath(GOAL_STATE) if GOAL_STATE else out['state_path']
    return out


def finalize(result, reason='success', *, path=None, handler=None):
    """成功/主动收口：写 done_prompt + 映射 status；不改 turns_used；幂等。"""
    global GOAL_STATE, _state
    h = handler if handler is not None else _handler
    target = os.path.abspath(path) if path else (os.path.abspath(GOAL_STATE) if GOAL_STATE else None)
    out = {
        'status': 'missing',
        'state_path': target,
        'missing': False,
        'handler_bound': False,
    }
    if not target:
        out['missing'] = True
        _safe_exit(reason=reason or 'success', handler=h)
        clear_binding(path=None)
        return out
    try:
        data = _load_from(target)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        out['missing'] = True
        _safe_exit(reason=reason or 'success', handler=h)
        # path 守卫清绑定
        clear_binding(path=target)
        return out

    if data.get('status') == 'running':
        data['done_prompt'] = str(result)[:_MAX_DONE]
        data['status'] = _map_done_status(reason)
        # 不改 turns_used
        _save_to(target, data)
        if GOAL_STATE and os.path.abspath(GOAL_STATE) == target:
            _state = dict(data)
    # 已终态：不覆盖 status
    out['status'] = data.get('status')
    out['state'] = dict(data)

    # exit + 清绑定：临时对齐 GOAL_STATE 使 _safe_exit 路径匹配；clear 始终 path 守卫
    prev_gs = GOAL_STATE
    try:
        if prev_gs is None or os.path.abspath(str(prev_gs)) != target:
            GOAL_STATE = target
        skipped = _safe_exit(reason=reason or str(data.get('status') or 'success'), handler=h)
        if skipped:
            out['exit_skipped'] = skipped
    finally:
        if prev_gs is not None:
            GOAL_STATE = prev_gs
    clear_binding(path=target)  # path 守卫：GOAL_STATE!=target 时 no-op
    lg = _leak_guard_session(h, target, reason=reason or str(out.get('status') or 'success'))
    if lg:
        out['leak_guard'] = lg
    out['handler_bound'] = _handler is not None
    return out


def heartbeat(summary=None, agent_turn=None, *, path=None):
    """agent 可选刷新摘要；只读预算；绝不写 done_*；不自增 agent_turns。"""
    target = os.path.abspath(path) if path else (os.path.abspath(GOAL_STATE) if GOAL_STATE else None)
    out = {
        'should_stop': True,
        'status': 'missing',
        'state_path': target,
        'missing': False,
        'budget_remaining': 0,
        'turns_used': 0,
        'agent_turns': 0,
    }
    if not target or not os.path.isfile(target):
        out['missing'] = True
        return out
    try:
        data = _load_from(target)
    except Exception as e:
        out['error'] = str(e)
        out['missing'] = True
        return out

    now = time.time()
    budget = int(data.get('budget_seconds', 3600) or 3600)
    elapsed = _goal_elapsed(data, now)
    turns = int(data.get('turns_used', 0) or 0)
    max_turns = int(data.get('max_turns', 200) or 200)
    agent_turns = int(data.get('agent_turns', 0) or 0)
    status = data.get('status') or 'missing'

    out['status'] = status
    out['turns_used'] = turns
    out['agent_turns'] = agent_turns
    out['budget_remaining'] = max(0, budget - elapsed)
    out['should_stop'] = (
        status != 'running'
        or elapsed > budget
        or turns >= max_turns
    )

    if status != 'running':
        # 终态：带 summary 也不写盘
        return out

    dirty = False
    if summary is not None:
        data['last_summary'] = str(summary)[:_MAX_DONE]
        data['last_checkpoint_at'] = now
        dirty = True
    if agent_turn is not None:
        try:
            data['last_agent_turn'] = int(agent_turn)
            dirty = True
        except (TypeError, ValueError):
            pass
    if dirty:
        try:
            _save_to(target, data)
            if GOAL_STATE and os.path.abspath(GOAL_STATE) == target:
                global _state
                _state = dict(data)
        except Exception as e:
            out['error'] = str(e)
    return out


def auto_tick(path, turn, summary_hint=''):
    """path 中心预算闸：每轮由 turn_end 调用。可写 done_budget/done_turns；+1 agent_turns。

    禁止假设 GOAL_STATE==path；禁止用 agent_turns 触发 done_turns。
    """
    out = {
        'should_stop': False,
        'status': 'missing',
        'reason': '',
        'state_path': None,
        'agent_turns': 0,
        'budget_remaining': 0,
    }
    if not path:
        out['should_stop'] = True
        out['reason'] = 'stale'
        return out
    path = os.path.abspath(str(path))
    out['state_path'] = path
    if not os.path.isfile(path):
        out['should_stop'] = True
        out['reason'] = 'stale'
        return out
    try:
        data = _load_from(path)
    except Exception as e:
        print(f'[goal_mode] auto_tick load failed: {e}')
        out['should_stop'] = False
        out['error'] = str(e)
        out['reason'] = 'error'
        return out

    status = data.get('status')
    out['status'] = status
    if status != 'running':
        out['should_stop'] = True
        out['reason'] = 'stale_status'
        out['agent_turns'] = int(data.get('agent_turns', 0) or 0)
        return out

    now = time.time()
    # 1) 刷新 last_*
    hint = (summary_hint or '').strip()
    if hint:
        data['last_summary'] = hint[:_MAX_DONE]
    elif not data.get('last_summary'):
        data['last_summary'] = f'agent turn {turn}'
    try:
        data['last_agent_turn'] = int(turn)
    except (TypeError, ValueError):
        data['last_agent_turn'] = turn
    data['last_checkpoint_at'] = now

    # 2) agent_turns +1（仅此处；无条件）
    agent_turns = int(data.get('agent_turns') or 0) + 1
    data['agent_turns'] = agent_turns
    out['agent_turns'] = agent_turns

    budget = int(data.get('budget_seconds', 3600) or 3600)
    elapsed = _goal_elapsed(data, now)
    out['budget_remaining'] = max(0, budget - elapsed)
    turns_used = int(data.get('turns_used', 0) or 0)
    max_turns = int(data.get('max_turns', 200) or 200)

    # 3) 墙钟：elapsed > budget（严格 >）
    if elapsed > budget:
        data['status'] = 'done_budget'
        if not (data.get('done_prompt') or '').strip():
            data['done_prompt'] = f'budget exhausted after {agent_turns} agent turns'
        try:
            _save_to(path, data)
        except Exception as e:
            print(f'[goal_mode] auto_tick save failed: {e}')
            out['error'] = str(e)
        out['should_stop'] = True
        out['status'] = 'done_budget'
        out['reason'] = 'done_budget'
        print(f'[goal_mode] auto_tick budget 耗尽({budget}s) 自动收口 path={path}')
        return out

    # 4) 协议轮 turns_used >= max_turns（不用 agent_turns）
    if turns_used >= max_turns:
        data['status'] = 'done_turns'
        if not (data.get('done_prompt') or '').strip():
            data['done_prompt'] = f'turns exhausted {turns_used}/{max_turns}'
        try:
            _save_to(path, data)
        except Exception as e:
            print(f'[goal_mode] auto_tick save failed: {e}')
            out['error'] = str(e)
        out['should_stop'] = True
        out['status'] = 'done_turns'
        out['reason'] = 'done_turns'
        print(f'[goal_mode] auto_tick turns 耗尽({turns_used}/{max_turns}) path={path}')
        return out

    # 5) 未触顶：写盘 last_*/agent_turns
    try:
        _save_to(path, data)
    except Exception as e:
        print(f'[goal_mode] auto_tick save failed: {e}')
        out['error'] = str(e)
    out['should_stop'] = False
    out['status'] = 'running'
    out['reason'] = ''
    return out


def status(*, handler=None):
    """只读观测；缺文件 missing=True，不写盘、不 enter/exit。"""
    h = handler if handler is not None else _handler
    out = {
        'state_path': os.path.abspath(GOAL_STATE) if GOAL_STATE else None,
        'handler_bound': _handler is not None,
        'handler_active': _obs_active(h),
        'missing': False,
    }
    try:
        st = _load_from(GOAL_STATE)
        out['state'] = st
        now = time.time()
        budget = int(st.get('budget_seconds', 3600))
        elapsed = _goal_elapsed(st, now)
        turns = int(st.get('turns_used', 0) or 0)
        max_turns = int(st.get('max_turns', 200))
        out['budget_remaining'] = max(0, budget - elapsed)
        out['turns_remaining'] = max(0, max_turns - turns)
        out['agent_turns'] = int(st.get('agent_turns', 0) or 0)
    except FileNotFoundError:
        out['missing'] = True
    except Exception:
        out['missing'] = True
    return out


def check():
    """返回下一轮任务 prompt; 预算/轮次耗尽或非 running → None 自动收口"""
    _load()
    if _state.get('status') != 'running':
        _safe_exit(reason=str(_state.get('status') or 'stale'))
        clear_binding(path=None)
        return None
    now = time.time()
    budget = int(_state.get('budget_seconds', 3600))
    elapsed = _goal_elapsed(_state, now)
    if elapsed > budget:
        _state['status'] = 'done_budget'
        _save()
        print(f'[goal_mode] budget 耗尽({budget}s) 自动收口')
        _safe_exit(reason='done_budget')
        clear_binding(path=None)
        return None
    turns = int(_state.get('turns_used', 0) or 0)
    max_turns = int(_state.get('max_turns', 200))
    if turns >= max_turns:
        _state['status'] = 'done_turns'
        _save()
        print(f'[goal_mode] turns 耗尽({turns}/{max_turns}) 自动收口')
        _safe_exit(reason='done_turns')
        clear_binding(path=None)
        return None
    objective = _state.get('objective', '')
    done = _state.get('done_prompt', '') or ''
    prompt = f'[GoalMode 第{turns+1}轮] 目标: {objective}'
    if done:
        prompt += f'\n上一轮已完成: {done[:200]}'
    prompt += (
        '\n请继续推进目标; 不要重复已完成部分。'
        '勿改 objective/budget_seconds/max_turns/status；'
        '可用 heartbeat(summary=...) 更新 last_summary。'
    )
    return prompt


def on_done(result):
    """任务完成后回写 turns_used / done_prompt；达上限自动 done_turns + 安全 exit。"""
    _load()
    if _state.get('status') != 'running':
        _safe_exit(reason=str(_state.get('status') or 'stale'))
        clear_binding(path=None)
        return

    _state['turns_used'] = int(_state.get('turns_used', 0) or 0) + 1
    _state['done_prompt'] = str(result)[:_MAX_DONE]
    turns = _state['turns_used']
    max_turns = int(_state.get('max_turns', 200))
    now = time.time()
    budget = int(_state.get('budget_seconds', 3600))
    elapsed = _goal_elapsed(_state, now)

    if turns >= max_turns:
        _state['status'] = 'done_turns'
        _save()
        print(f"[goal_mode] round {turns} done, status=done_turns")
        _safe_exit(reason='done_turns')
        clear_binding(path=None)
        return

    if elapsed > budget:
        _state['status'] = 'done_budget'
        _save()
        print(f"[goal_mode] round {turns} done, status=done_budget")
        _safe_exit(reason='done_budget')
        clear_binding(path=None)
        return

    _save()
    print(f"[goal_mode] round {turns} done, status={_state.get('status')}")
