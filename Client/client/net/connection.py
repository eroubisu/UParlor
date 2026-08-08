"""
网络通信模块
"""

import socket
import json
import platform
import threading


def _enable_keepalive(sock: socket.socket, idle: int = 60, interval: int = 10, count: int = 5):
    """启用 TCP Keepalive，防止 NAT/防火墙关闭空闲连接"""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    system = platform.system()
    if system == 'Linux':
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
    elif system == 'Darwin':
        # macOS: TCP_KEEPALIVE = idle time
        TCP_KEEPALIVE = 0x10
        sock.setsockopt(socket.IPPROTO_TCP, TCP_KEEPALIVE, idle)
    elif system == 'Windows':
        # Windows: SIO_KEEPALIVE_VALS (onoff, keepalivetime_ms, keepaliveinterval_ms)
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))


class NetworkManager:
    """网络管理"""

    def __init__(self, port):
        self.socket = None
        self.port = port
        self.connected = False
        self.on_send_failure = None  # callback()
        self._send_lock = threading.Lock()

    def connect(self, host):
        """连接服务器"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, self.port))
        sock.settimeout(None)
        _enable_keepalive(sock)
        with self._send_lock:
            self.socket = sock
            self.connected = True
        return True

    def disconnect(self):
        """断开连接"""
        with self._send_lock:
            self.connected = False
            sock = self.socket
            self.socket = None
            if not sock:
                return
            try:
                sock.close()
            except OSError:
                pass

    def send(self, data):
        """发送数据"""
        failed = False
        try:
            with self._send_lock:
                if not self.connected or not self.socket:
                    return False
                msg = json.dumps(data) + '\n'
                self.socket.sendall(msg.encode('utf-8'))
        except OSError:
            failed = True
        if failed:
            callback = self.on_send_failure
            if callback:
                callback()
            return False
        return True
