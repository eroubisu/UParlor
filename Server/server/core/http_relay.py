"""网页手柄的公网中转 — 复用游戏端口上的 HTTP 请求。

手机浏览器访问 ``http://<服务器地址>:5555/r/<会话令牌>/``；服务端把该路径下的
HTTP 请求通过既有的游戏长连接转交给所属客户端，由客户端本机 HTTP 服务处理，
再把响应送回浏览器。网页、配对码和按键校验因此仍然只有客户端一份实现。

线程模型：浏览器每次请求一个线程（``ChatServer.start`` 已经如此），转发时用
``threading.Event`` 等待客户端响应，超时返回 504。
"""

from __future__ import annotations

import base64
import itertools
import logging
import secrets
import socket
import threading
from typing import NamedTuple

from ..msg_types import REMOTE_HTTP

logger = logging.getLogger(__name__)

SESSION_PREFIX = '/r/'
MAX_HEADER_BYTES = 16 * 1024
MAX_REQUEST_BODY = 64 * 1024
MAX_RESPONSE_BODY = 512 * 1024
FORWARD_TIMEOUT = 15.0
MAX_INFLIGHT_PER_SESSION = 4
# 窥探协议时的等待上限。游戏客户端连上就会先发一个问候包，因此只有浏览器
# （发来 GET 请求）和不想升级的旧客户端会真正等满这个时间。
PEEK_TIMEOUT = 2.0

_METHODS = (b'GET ', b'HEAD ', b'POST ', b'PUT ', b'DELETE ', b'OPTIONS ', b'PATCH ')
_REASONS = {
    200: 'OK',
    400: 'Bad Request',
    404: 'Not Found',
    413: 'Payload Too Large',
    429: 'Too Many Requests',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
}

_NO_SESSION_PAGE = (
    '<!doctype html><meta charset="utf-8">'
    '<title>UParlor 手柄</title>'
    '<body style="background:#0e1014;color:#e0e0e0;font-family:-apple-system,'
    'sans-serif;padding:32px;text-align:center">'
    '<h2>连接已失效</h2>'
    '<p>这个手柄地址已经过期。</p>'
    '<p>请在电脑上重新打开“iOS 连接”窗口，扫描新的二维码。</p>'
    '</body>'
).encode('utf-8')


class HttpRequest(NamedTuple):
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


def looks_like_http(client_socket, timeout: float = PEEK_TIMEOUT) -> bool:
    """窥探连接开头几个字节，判断是不是浏览器发来的 HTTP 请求。

    只窥探不消费：协议判定后原字节仍留给各自的读取方。客户端连上即发问候包，
    因此判定对游戏连接是即时的；浏览器则等自己的请求首字节到达。
    """
    try:
        previous = client_socket.gettimeout()
    except OSError:
        return False
    try:
        client_socket.settimeout(timeout)
        head = client_socket.recv(8, socket.MSG_PEEK)
    except OSError:
        return False
    finally:
        try:
            client_socket.settimeout(previous)
        except OSError:
            pass
    return any(head.startswith(method) for method in _METHODS)


def _read_head(client_socket) -> bytes | None:
    """读取请求行与请求头（含结尾空行），超限或被断开时返回 None。"""
    data = b''
    while b'\r\n\r\n' not in data and b'\n\n' not in data:
        try:
            chunk = client_socket.recv(2048)
        except OSError:
            return None
        if not chunk:
            return None
        data += chunk
        if len(data) > MAX_HEADER_BYTES:
            return None
    return data


def _split_head(raw: bytes) -> tuple[bytes, bytes]:
    if b'\r\n\r\n' in raw:
        head, _, rest = raw.partition(b'\r\n\r\n')
        return head, rest
    head, _, rest = raw.partition(b'\n\n')
    return head.replace(b'\r\n', b'\n'), rest


def read_request(client_socket) -> HttpRequest | None:
    """解析一个 HTTP 请求；不合法时返回 None。"""
    raw = _read_head(client_socket)
    if raw is None:
        return None
    head, rest = _split_head(raw)
    lines = head.decode('latin-1').splitlines()
    if not lines:
        return None
    parts = lines[0].split(' ')
    if len(parts) < 2:
        return None
    method, target = parts[0].upper(), parts[1]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        key, _, value = line.partition(':')
        if key and value:
            headers[key.strip().lower()] = value.strip()
    try:
        length = int(headers.get('content-length') or 0)
    except ValueError:
        return None
    if length < 0 or length > MAX_REQUEST_BODY:
        return None
    body = rest
    while len(body) < length:
        try:
            chunk = client_socket.recv(4096)
        except OSError:
            return None
        if not chunk:
            break
        body += chunk
    return HttpRequest(method, target, headers, body[:length])


def split_token(target: str) -> tuple[str, str]:
    """把 ``/r/<token>/rest`` 拆成 (token, '/rest')；不含会话前缀时返回 ('', target)。"""
    if not target.startswith(SESSION_PREFIX):
        return '', target
    remainder = target[len(SESSION_PREFIX):]
    token, _, rest = remainder.partition('/')
    if not token:
        return '', target
    return token, '/' + rest


class RemoteRelay:
    """会话令牌 → 客户端连接的注册表，并负责一次请求的往返。"""

    def __init__(self, send_to_client):
        self._send_to_client = send_to_client
        self._lock = threading.Lock()
        self._sessions: dict[str, socket.socket] = {}
        self._inflight: dict[str, int] = {}
        self._pending: dict[int, tuple[socket.socket, threading.Event, dict]] = {}
        self._ids = itertools.count(1)

    # ── 会话 ──

    def open_session(self, client_socket) -> str:
        """为一个客户端开通中转会话，返回新令牌（旧的同连接令牌作废）。"""
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._drop_locked(client_socket)
            self._sessions[token] = client_socket
        return token

    def close_session(self, client_socket) -> None:
        with self._lock:
            self._drop_locked(client_socket)

    def has_session(self, token: str) -> bool:
        with self._lock:
            return token in self._sessions

    def _drop_locked(self, client_socket) -> None:
        for token in [t for t, c in self._sessions.items() if c is client_socket]:
            self._sessions.pop(token, None)
            self._inflight.pop(token, None)
        for req_id in [i for i, (c, _, _) in self._pending.items()
                       if c is client_socket]:
            entry = self._pending.pop(req_id, None)
            if entry is not None:
                entry[1].set()

    # ── 请求往返 ──

    def forward(self, token: str, request: HttpRequest) -> dict | None:
        """把请求转给客户端，等待响应。返回 {status, content_type, body} 或 None。"""
        with self._lock:
            client_socket = self._sessions.get(token)
            if client_socket is None:
                return None
            if self._inflight.get(token, 0) >= MAX_INFLIGHT_PER_SESSION:
                return {'status': 429, 'content_type': 'text/plain; charset=utf-8',
                        'body': b'too many requests'}
            self._inflight[token] = self._inflight.get(token, 0) + 1
            req_id = next(self._ids)
            event = threading.Event()
            holder: dict = {}
            self._pending[req_id] = (client_socket, event, holder)

        try:
            payload = {
                'type': REMOTE_HTTP,
                'id': req_id,
                'method': request.method,
                'target': request.target,
                'body': base64.b64encode(request.body).decode('ascii'),
            }
            self._send_to_client(client_socket, payload)
            if not event.wait(FORWARD_TIMEOUT):
                logger.warning('手柄中转等待客户端超时: %s', request.target)
                return None
            return holder.get('response')
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
                remaining = self._inflight.get(token, 1) - 1
                if remaining > 0:
                    self._inflight[token] = remaining
                else:
                    self._inflight.pop(token, None)

    def deliver(self, client_socket, msg: dict) -> bool:
        """客户端回传响应；返回是否为合法的待处理请求。"""
        req_id = msg.get('id')
        if not isinstance(req_id, int):
            return False
        try:
            body = base64.b64decode(msg.get('body') or '')
        except (ValueError, TypeError):
            body = b''
        if len(body) > MAX_RESPONSE_BODY:
            return False
        response = {
            'status': int(msg.get('status') or 502),
            'content_type': str(msg.get('content_type')
                                or 'application/octet-stream'),
            'body': body,
        }
        with self._lock:
            entry = self._pending.get(req_id)
            if entry is None or entry[0] is not client_socket:
                return False
            entry[2]['response'] = response
            entry[1].set()
        return True

    def shutdown(self) -> None:
        """服务器退出：唤醒所有等待中的请求。"""
        with self._lock:
            entries = list(self._pending.values())
            self._pending.clear()
            self._sessions.clear()
            self._inflight.clear()
        for _, event, _ in entries:
            event.set()


def _send_response(client_socket, status: int, content_type: str,
                   body: bytes) -> None:
    reason = _REASONS.get(status, 'OK')
    # 只允许单行 Content-Type，防止响应头被注入
    safe_type = content_type.replace('\r', ' ').replace('\n', ' ').strip()
    head = (
        f'HTTP/1.1 {status} {reason}\r\n'
        f'Content-Type: {safe_type or "application/octet-stream"}\r\n'
        f'Content-Length: {len(body)}\r\n'
        'Cache-Control: no-store\r\n'
        'Connection: close\r\n\r\n'
    ).encode('latin-1')
    try:
        client_socket.sendall(head + body)
    except OSError:
        pass


def serve_http(client_socket, relay: RemoteRelay) -> None:
    """处理一个浏览器连接：解析请求 → 转发给客户端 → 回写响应。"""
    try:
        client_socket.settimeout(FORWARD_TIMEOUT)
        request = read_request(client_socket)
        if request is None:
            _send_response(client_socket, 400, 'text/plain; charset=utf-8',
                           b'bad request')
            return
        token, target = split_token(request.target)
        if not token:
            _send_response(client_socket, 200, 'text/html; charset=utf-8',
                           _NO_SESSION_PAGE)
            return
        if not relay.has_session(token):
            _send_response(client_socket, 200, 'text/html; charset=utf-8',
                           _NO_SESSION_PAGE)
            return
        forwarded = request._replace(target=target)
        response = relay.forward(token, forwarded)
        if response is None:
            _send_response(client_socket, 504, 'text/plain; charset=utf-8',
                           'gateway timeout'.encode('utf-8'))
            return
        _send_response(client_socket, response['status'],
                       response['content_type'], response['body'])
    finally:
        try:
            client_socket.close()
        except OSError:
            pass
