#!/usr/bin/env bash
# 为 quant-fin-papers 安装/打印定时任务（macOS launchd 或 cron）。
#
# 用法:
#   ./install_schedule.sh --print-launchd [--hour 8 --minute 30] [--root DIR]
#   ./install_schedule.sh --install-launchd [--hour 8 --minute 30] [--root DIR]
#   ./install_schedule.sh --print-cron   [--hour 8 --minute 30] [--root DIR]
#   ./install_schedule.sh --uninstall
#
# 说明: --install-launchd 会写入 ~/Library/LaunchAgents，需要普通用户权限；
#       若在受限沙箱里执行会失败，请把 --print-launchd 的输出重定向后手动加载。

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SKILL_DIR/scripts/quantpapers.py"
LABEL="com.quantfin.papers"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

ROOT="${QF_LIBRARY:-$PWD/quant-finance-library}"
HOUR=8
MINUTE=30
MODE=""

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --print-launchd|--install-launchd|--print-cron|--uninstall) MODE="$1" ;;
    --root) ROOT="$2"; shift ;;
    --hour) HOUR="$2"; shift ;;
    --minute) MINUTE="$2"; shift ;;
    -h|--help) usage ;;
    *) echo "未知参数: $1" >&2; usage ;;
  esac
  shift
done

[[ -n "$MODE" ]] || usage

PYTHON="${PYTHON:-$(command -v python3 || true)}"
[[ -n "$PYTHON" ]] || { echo "找不到 python3" >&2; exit 1; }
ROOT="$(cd "$ROOT" 2>/dev/null && pwd || echo "$ROOT")"
LOG_DIR="$ROOT/logs"

plist_body() {
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${SCRIPT}</string>
    <string>fetch</string>
    <string>--root</string>
    <string>${ROOT}</string>
  </array>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>${HOUR}</integer>
    <key>Minute</key><integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key><string>${LOG_DIR}/fetch.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/fetch.log</string>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
}

case "$MODE" in
  --print-launchd)
    plist_body
    ;;
  --install-launchd)
    mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
    plist_body > "$PLIST"
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    launchctl enable "gui/$(id -u)/${LABEL}"
    echo "已安装: $PLIST"
    echo "每天 ${HOUR}:$(printf '%02d' "$MINUTE") 运行；日志: ${LOG_DIR}/fetch.log"
    echo "立即测试: launchctl kickstart -k gui/$(id -u)/${LABEL}"
    ;;
  --print-cron)
    mkdir -p "$LOG_DIR"
    echo "# 每天 ${HOUR}:$(printf '%02d' "$MINUTE") 增量采集量化金融文献"
    echo "$MINUTE $HOUR * * * cd \"${ROOT}\" && \"${PYTHON}\" \"${SCRIPT}\" fetch --root \"${ROOT}\" >> \"${LOG_DIR}/fetch.log\" 2>&1"
    ;;
  --uninstall)
    if [[ -f "$PLIST" ]]; then
      launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
      rm -f "$PLIST"
      echo "已卸载 launchd 任务"
    else
      echo "未找到 $PLIST"
    fi
    echo "如使用 cron，请手动 crontab -e 删除对应行"
    ;;
esac
