"""
网络通信模块
"""

import socket
import json
import platform


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

    def connect(self, host):
        """连接服务器"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        self.socket.connect((host, self.port))
        self.socket.settimeout(None)
        _enable_keepalive(self.socket)
        self.connected = True
        return True
    
    def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
    
    def send(self, data):
        """发送数据"""
        if not self.connected:
            return False
        try:
            msg = json.dumps(data) + '\n'
            self.socket.send(msg.encode('utf-8'))
            return True
        except OSError:
            return False
