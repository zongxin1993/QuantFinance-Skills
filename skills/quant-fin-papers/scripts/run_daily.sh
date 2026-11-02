#!/usr/bin/env bash
# 每日自动化：先更新技能仓库，再全平台增量采集。
#
#   ./run_daily.sh /path/to/library            # 更新 + 采集
#   ./run_daily.sh /path/to/library --no-pull  # 只采集
#   ./run_daily.sh /path/to/library --digest   # 采集后再出摘要
#
# 由 launchd / cron 调用；所有输出写到 <library>/logs/daily.log。

set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(git -C "$SKILL_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

ROOT="${1:-$PWD/quant-finance-library}"
DO_PULL=1
DO_DIGEST=0
for arg in "${@:2}"; do
  case "$arg" in
    --no-pull) DO_PULL=0 ;;
    --digest) DO_DIGEST=1 ;;
  esac
done

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily.log"

# 简单轮转：超过 2MB 就滚动一次
if [[ -f "$LOG" ]] && [[ $(stat -f%z "$LOG" 2>/dev/null || echo 0) -gt 2097152 ]]; then
  mv "$LOG" "$LOG.1"
fi

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

log "=== 开始 ==="
log "技能目录: $SKILL_DIR"
log "资料库  : $ROOT"

# ---- 1. 更新技能（git pull）--------------------------------------------
if [[ "$DO_PULL" == "1" ]]; then
  if [[ -z "$REPO_DIR" ]]; then
    log "跳过更新：技能不在 git 仓库里"
  elif [[ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]]; then
    log "跳过更新：工作区有未提交改动"
  else
    if git -C "$REPO_DIR" pull --ff-only --quiet >>"$LOG" 2>&1; then
      log "技能已更新到 $(git -C "$REPO_DIR" rev-parse --short HEAD) ($(git -C "$REPO_DIR" log -1 --format=%s))"
    else
      log "更新失败（继续用当前版本）"
    fi
  fi
fi

# ---- 2. 全平台增量采集 ---------------------------------------------------
PYTHON="${PYTHON:-$(command -v python3)}"
if [[ -z "$PYTHON" ]]; then
  log "✗ 找不到 python3"
  exit 1
fi

log "开始采集…"
"$PYTHON" "$SKILL_DIR/scripts/quantpapers.py" fetch --root "$ROOT" 2>&1 | tee -a "$LOG"
FETCH_RC=${PIPESTATUS[0]}
log "采集退出码: $FETCH_RC"

# ---- 3. 可选：出摘要 -----------------------------------------------------
if [[ "$DO_DIGEST" == "1" ]]; then
  "$PYTHON" "$SKILL_DIR/scripts/quantpapers.py" digest --root "$ROOT" 2>&1 | tee -a "$LOG"
fi

log "=== 结束 ==="
exit "$FETCH_RC"
