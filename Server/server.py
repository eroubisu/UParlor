"""
游戏大厅 - 服务器入口
"""

import sys
import threading
import time
from server.chat_server import ChatServer


def main():
    server = ChatServer()
    
    # 在后台线程启动服务器
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()
    
    # 检查是否有终端输入（后台运行时没有）
    if sys.stdin.isatty():
        # 有终端，等待输入
        print("\n输入 'quit' 或 'exit' 关闭服务器")
        print("或按 Ctrl+C 强制关闭\n")
        
        try:
            while True:
                cmd = input().strip().lower()
                if cmd in ('quit', 'exit', 'q'):
                    print("正在关闭服务器...")
                    server.stop()
                    break
        except KeyboardInterrupt:
            print("\n正在关闭服务器...")
            server.stop()
    else:
        # 无终端（后台运行），保持运行
        print("\n[后台模式] 服务器运行中...")
        print("使用 'pkill -f server.py' 停止服务器\n")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            server.stop()
    
    print("服务器已关闭")


if __name__ == '__main__':
    main()
