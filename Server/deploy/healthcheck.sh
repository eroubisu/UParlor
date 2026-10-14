#!/usr/bin/env bash
# UParlor 健康探针 — 由 uparlor-healthcheck.timer 每分钟执行一次。
#
# 只解决 systemd 看不见的那类故障：进程还在、端口也监听，但已经卡死不再应答。
# 三次判定 + 最小重启间隔，避免探针误判把正常服务反复重启。
set -uo pipefail

PORT="${1:-5555}"
UNIT="${2:-uparlor}"
STATE_FILE=/run/uparlor-healthcheck.last
MAX_ATTEMPTS=3
MIN_RESTART_INTERVAL=120

if ! systemctl cat "$UNIT" >/dev/null 2>&1; then
    echo "$UNIT 服务未安装，跳过探针"
    exit 0
fi

# 连接端口并等待服务端连接后立即下发的握手数据（client_version / 登录提示）。
# 有数据说明应用层仍在工作，而不只是内核接受了连接。
probe() {
    timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT && head -c 1 <&3 >/dev/null" \
        >/dev/null 2>&1
}

attempt=0
while [ "$attempt" -lt "$MAX_ATTEMPTS" ]; do
    if probe; then
        exit 0
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -lt "$MAX_ATTEMPTS" ] && sleep 2
done

now=$(date +%s)
last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
if [ $((now - last)) -lt "$MIN_RESTART_INTERVAL" ]; then
    echo "$UNIT 连续 $MAX_ATTEMPTS 次探针失败，但距上次重启不足 ${MIN_RESTART_INTERVAL}s，本次跳过"
    exit 0
fi

echo "$UNIT 连续 $MAX_ATTEMPTS 次探针失败，重启服务"
echo "$now" > "$STATE_FILE"
systemctl restart "$UNIT"
