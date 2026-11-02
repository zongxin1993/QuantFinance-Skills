#!/usr/bin/env bash
# 把本仓库 skills/* 安装到 agent 的技能目录。
#
# 默认用软链，保持"仓库即真源"：改仓库里的文件，装好的技能立即生效。
#
#   ./scripts/install.sh                    # 软链到 ~/.agents/skills
#   ./scripts/install.sh --target DIR       # 软链到指定目录
#   ./scripts/install.sh --copy             # 复制而不是软链（分发用）
#   ./scripts/install.sh --list             # 看本仓库有哪些技能
#   ./scripts/install.sh --uninstall        # 移除本仓库装过的技能

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${DSH_AGENTS_HOME:-$HOME/.agents}/skills"
MODE="link"
ACTION="install"

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift ;;
    --copy) MODE="copy" ;;
    --link) MODE="link" ;;
    --list) ACTION="list" ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help) usage ;;
    *) echo "未知参数: $1" >&2; usage ;;
  esac
  shift
done

TARGET="${TARGET/#\~/$HOME}"

skills() {
  find "$ROOT/skills" -mindepth 1 -maxdepth 1 -type d | sort
}

case "$ACTION" in
  list)
    echo "本仓库的技能："
    for dir in $(skills); do
      name="$(basename "$dir")"
      desc="$(sed -n 's/^description: *//p' "$dir/SKILL.md" 2>/dev/null | head -1 | cut -c1-70)"
      printf "  %-22s %s\n" "$name" "$desc"
    done
    ;;

  uninstall)
    for dir in $(skills); do
      name="$(basename "$dir")"
      dest="$TARGET/$name"
      if [[ -L "$dest" ]]; then
        rm -f "$dest" && echo "已移除软链 $dest"
      elif [[ -d "$dest" ]]; then
        echo "跳过 $dest（不是软链，未动它）"
      fi
    done
    ;;

  install)
    mkdir -p "$TARGET"
    echo "目标目录: $TARGET"
    for dir in $(skills); do
      name="$(basename "$dir")"
      dest="$TARGET/$name"
      if [[ -L "$dest" ]]; then
        rm -f "$dest"
      elif [[ -e "$dest" ]]; then
        echo "跳过 $name：$dest 已存在且不是软链，请先手动处理"
        continue
      fi
      if [[ "$MODE" == "link" ]]; then
        ln -s "$dir" "$dest"
        echo "  链接 $name -> $dir"
      else
        cp -R "$dir" "$dest"
        echo "  复制 $name -> $dest"
      fi
    done
    echo "完成。验证： ls -l \"$TARGET\""
    ;;
esac
