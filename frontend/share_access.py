"""公网演示入口的访问保护；本地演示和后端接口不依赖此模块。"""

from collections import deque
import hashlib
import hmac
import math
import os
import re
import secrets
import threading
import time


HASH_ITERATIONS = 600_000
MIN_HASH_ITERATIONS = 100_000
MAX_HASH_ITERATIONS = 1_000_000
MIN_PASSWORD_CHARACTERS = 12
MAX_PASSWORD_CHARACTERS = 256
MAX_PASSWORD_BYTES = 1024
SESSION_SECONDS = 60 * 60
ATTEMPT_WINDOW_SECONDS = 10 * 60
SESSION_ATTEMPT_LIMIT = 5
PROCESS_ATTEMPT_LIMIT = 40

_AUTH_KEY = '_share_access_auth'
_ATTEMPTS_KEY = '_share_access_attempts'
_ERROR_KEY = '_share_access_error'
_PASSWORD_KEY = '_share_access_password'
_HASH_PATTERN = re.compile(r'pbkdf2_sha256\$([1-9][0-9]{5,6})\$([0-9a-f]{32})\$([0-9a-f]{64})')
# 只保存时间，不采信浏览器提供的地址或代理头。队列和锁是同一进程所有会话共享的。
_PROCESS_ATTEMPTS = deque(maxlen=PROCESS_ATTEMPT_LIMIT)
_PROCESS_LOCK = threading.Lock()


def _password_bytes(password):
    if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_CHARACTERS:
        return None
    try:
        encoded = password.encode('utf-8')
    except UnicodeError:
        return None
    return encoded if len(encoded) <= MAX_PASSWORD_BYTES else None


def _parse_hash(password_hash):
    if not isinstance(password_hash, str) or len(password_hash) > 160:
        return None
    match = _HASH_PATTERN.fullmatch(password_hash)
    if match is None:
        return None
    iterations = int(match[1])
    if not MIN_HASH_ITERATIONS <= iterations <= MAX_HASH_ITERATIONS:
        return None
    return iterations, bytes.fromhex(match[2]), bytes.fromhex(match[3])


def hash_access_password(password):
    """生成可放入部署密钥配置的哈希；口令至少 12 个字符，不输出口令本身。"""
    encoded = _password_bytes(password)
    if encoded is None or len(password) < MIN_PASSWORD_CHARACTERS:
        raise ValueError('访问口令需为 12 至 256 个字符，且不超过 1024 字节。')
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac('sha256', encoded, salt, HASH_ITERATIONS, dklen=32)
    return f'pbkdf2_sha256${HASH_ITERATIONS}${salt.hex()}${derived.hex()}'


def verify_access_password(password, password_hash):
    """格式、输入或计算异常均拒绝访问；限制计算量后进行恒定时间摘要比较。"""
    encoded = _password_bytes(password)
    parsed = _parse_hash(password_hash)
    if encoded is None or parsed is None:
        return False
    try:
        iterations, salt, expected = parsed
        actual = hashlib.pbkdf2_hmac('sha256', encoded, salt, iterations, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OverflowError, RuntimeError):
        return False


def _hash_fingerprint(password_hash):
    return hashlib.sha256(password_hash.encode('ascii')).hexdigest()


def _is_finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _session_is_authenticated(session_state, password_hash, now):
    auth = session_state.get(_AUTH_KEY)
    if not isinstance(auth, dict) or _parse_hash(password_hash) is None:
        return False
    expires_at = auth.get('expires_at')
    fingerprint = auth.get('fingerprint')
    if (not _is_finite_number(expires_at)
            or not now < expires_at <= now + SESSION_SECONDS
            or not isinstance(fingerprint, str)
            or re.fullmatch(r'[0-9a-f]{64}', fingerprint) is None):
        return False
    return hmac.compare_digest(fingerprint, _hash_fingerprint(password_hash))


def _session_attempts(session_state, now):
    attempts = session_state.get(_ATTEMPTS_KEY, [])
    # 不遍历不受限的输入；异常状态关闭访问，而不是悄悄重置计数。
    if not isinstance(attempts, list) or len(attempts) > SESSION_ATTEMPT_LIMIT:
        return None
    if any(not _is_finite_number(value) for value in attempts):
        return None
    return [value for value in attempts if now - ATTEMPT_WINDOW_SECONDS < value <= now]


def _expire_process_attempts(now):
    while _PROCESS_ATTEMPTS and _PROCESS_ATTEMPTS[0] <= now - ATTEMPT_WINDOW_SECONDS:
        _PROCESS_ATTEMPTS.popleft()


def _can_attempt(session_state, now):
    attempts = _session_attempts(session_state, now)
    with _PROCESS_LOCK:
        _expire_process_attempts(now)
        return (attempts is not None and len(attempts) < SESSION_ATTEMPT_LIMIT
                and len(_PROCESS_ATTEMPTS) < PROCESS_ATTEMPT_LIMIT)


def _reserve_attempt(session_state, now):
    """计算哈希前原子预留次数；成功尝试也计数，防止并发先计算后绕过限流。"""
    with _PROCESS_LOCK:
        attempts = _session_attempts(session_state, now)
        _expire_process_attempts(now)
        if (attempts is None or len(attempts) >= SESSION_ATTEMPT_LIMIT
                or len(_PROCESS_ATTEMPTS) >= PROCESS_ATTEMPT_LIMIT):
            return False
        _PROCESS_ATTEMPTS.append(now)
        session_state[_ATTEMPTS_KEY] = [*attempts, now]
        return True


def _configured_password_hash(st):
    """部署密钥优先；已配置但无效时不退回其他配置。"""
    password_hash = None
    found_in_secrets = False
    try:
        public_demo = st.secrets.get('public_demo', {})
        if 'password_hash' in public_demo:
            found_in_secrets = True
            password_hash = public_demo['password_hash']
    except (FileNotFoundError, KeyError):
        pass
    except (TypeError, AttributeError, ValueError):
        return None
    if not found_in_secrets:
        password_hash = os.environ.get('LOWALTITUDE_DEMO_PASSWORD_HASH')
    return password_hash if _parse_hash(password_hash) is not None else None


def _submit_password(st, password_hash):
    # 表单回调发生在下一次页面执行前，可清除密码控件的服务器状态。
    password = st.session_state.pop(_PASSWORD_KEY, '')
    now = time.monotonic()
    if not _reserve_attempt(st.session_state, now):
        st.session_state[_ERROR_KEY] = '访问尝试过于频繁，请十分钟后再试。'
        return
    if verify_access_password(password, password_hash):
        st.session_state.clear()
        st.session_state[_AUTH_KEY] = {
            'fingerprint': _hash_fingerprint(password_hash),
            'expires_at': now + SESSION_SECONDS,
        }
    else:
        st.session_state[_ERROR_KEY] = '访问口令不正确，请核对后重试。'


def require_share_access():
    """在公网入口配置页面后、导入或运行应用视图前调用；未认证时终止执行。"""
    import streamlit as st

    password_hash = _configured_password_hash(st)
    if password_hash is None:
        st.session_state.clear()
        st.error('演示访问保护尚未正确配置，请联系演示负责人。')
        st.stop()
        return

    now = time.monotonic()
    if _session_is_authenticated(st.session_state, password_hash, now):
        if st.sidebar.button('退出演示', key='_share_access_logout'):
            st.session_state.clear()
            st.rerun()
            st.stop()
        return

    if _AUTH_KEY in st.session_state:
        # 退出、到期或轮换口令后，清除上一位使用者的整个演示会话。
        st.session_state.clear()
    st.title('低空安全研判演示')
    st.caption('仅向受邀同学和老师开放，请输入访问口令。')
    if not _can_attempt(st.session_state, now):
        st.warning('访问尝试过于频繁，请十分钟后再试。')
        st.stop()
        return
    if error := st.session_state.get(_ERROR_KEY):
        st.error(error)
    with st.form('_share_access_form', clear_on_submit=True):
        st.text_input('访问口令', type='password', max_chars=MAX_PASSWORD_CHARACTERS,
                      key=_PASSWORD_KEY)
        st.form_submit_button('进入演示', type='primary', on_click=_submit_password,
                              args=(st, password_hash))
    st.stop()
