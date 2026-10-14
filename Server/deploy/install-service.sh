#!/usr/bin/env bash
# 在服务器上安装/刷新 UParlor 的 systemd 保活配置。幂等，可重复执行。
#
# 用法: sudo bash deploy/install-service.sh [工作目录] [端口]
#
# 保活分层，每层解决一种不同的故障：
#   1. uparlor.service            Restart=always + 开机自启 → 进程崩溃、主机重启
#   2. uparlor-healthcheck.timer  每分钟应用层探针        → 进程活着但卡死
#   3. healthcheck.sh 的三次判定 + 最小重启间隔           → 探针误判不会反复重启
set -euo pipefail

WORKDIR="${1:-/opt/game/server}"
PORT="${2:-5555}"
UNIT="uparlor"

if [ "$(id -u)" -ne 0 ]; then
    echo "需要 root 权限：请用 sudo 运行" >&2
    exit 1
fi
if [ ! -x "$WORKDIR/.venv/bin/python" ]; then
    echo "找不到 $WORKDIR/.venv/bin/python，请先完成一次部署" >&2
    exit 1
fi

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=UParlor game server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=$WORKDIR
ExecStart=$WORKDIR/.venv/bin/python -m server
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=uparlor

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/systemd/system/$UNIT-healthcheck.service" <<EOF
[Unit]
Description=UParlor health probe

[Service]
Type=oneshot
ExecStart=/bin/bash $WORKDIR/deploy/healthcheck.sh $PORT $UNIT
EOF

cat > "/etc/systemd/system/$UNIT-healthcheck.timer" <<EOF
[Unit]
Description=Probe the UParlor server every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "$UNIT"
systemctl enable --now "$UNIT-healthcheck.timer"
systemctl is-active "$UNIT" "$UNIT-healthcheck.timer"
echo "已安装：$UNIT 服务（崩溃自启 + 开机自启）与每分钟健康探针"
