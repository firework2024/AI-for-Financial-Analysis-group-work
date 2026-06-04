#!/usr/bin/env bash
# 在服务器 Git 仓库根目录执行（含 FinAgent/ 子目录的那一层）：
#   cd /www/wwwroot/AI-for-Financial-Analysis-group-work
#   bash FinAgent/scripts/server_recover.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" || ! -d "${ROOT}/FinAgent" ]]; then
  echo "错误：请在 AI-for-Financial-Analysis-group-work 仓库根目录运行此脚本" >&2
  exit 1
fi

cd "${ROOT}"
echo "==> 仓库: ${ROOT}"
echo "==> git pull"
git pull origin main

echo "==> 恢复 FinAgent 全部 tracked 文件"
git checkout HEAD -- FinAgent/

FA="${ROOT}/FinAgent"
cd "${FA}"

echo "==> 关键路径检查"
check() {
  if [[ -e "$1" ]]; then
    echo "  OK  $1"
  else
    echo "  缺失 $1" >&2
    missing=1
  fi
}
missing=0
check "finagent/web/static/index.html"
check "finagent/web/server.py"
check "finagent/cli.py"
check "pyproject.toml"
check "deploy/nginx-pkufinagent.site.conf"
if [[ "${missing}" -ne 0 ]]; then
  echo "仍有文件缺失，请检查 git 状态: git status FinAgent/" >&2
  exit 1
fi

echo "==> 运行时目录"
mkdir -p data_store chat_data annual_reports outputs chat_data/uploads chat_data/sessions chat_data/user_settings

if [[ ! -f .env ]]; then
  echo "  警告: FinAgent/.env 不存在，请从本机 scp 上传（见 DEPLOY.md）" >&2
fi

if [[ -d .venv ]]; then
  echo "==> pip install -e ."
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -U pip
  pip install -e .
else
  echo "  跳过 pip：未找到 .venv，请先 python3 -m venv .venv && source .venv/bin/activate"
fi

echo "==> 文件数量（git tracked）"
git ls-files FinAgent | wc -l
echo "==> 磁盘 finagent 包内 .py 数量"
find finagent -name '*.py' | wc -l

echo ""
echo "完成。请重启服务："
echo "  sudo systemctl restart finagent"
echo "验证："
echo "  curl -s http://127.0.0.1:8765/api/health"
echo "  curl -sI http://127.0.0.1:8765/ | head -1"
