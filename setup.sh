#!/bin/bash
# Invader 看板 · 新机器安装(macOS)。在仓库目录里运行:bash setup.sh
# 做的事:检查 Python / Node → 装 Python 库和上传工具 → 写凭据文件(没有才问)→ 下载 IP 分配表 → 生成并装定时任务 → 试跑一次渲染。
# 不会抓数、不会发布;装完先手动跑一次 bash scheduled_refresh.sh 看日志。详见 DEPLOY.md。
set -euo pipefail
cd "$(dirname "$0")"; HERE="$(pwd)"
say(){ printf '\n== %s\n' "$*"; }

say "1/6 检查 Python 3 和 Node"
command -v python3 >/dev/null || { echo "没有 python3:先装 Xcode 命令行工具(xcode-select --install)"; exit 1; }
python3 --version
NODE_BIN="$(command -v node || true)"; [ -z "$NODE_BIN" ] && [ -x "$HOME/.local/node/bin/node" ] && NODE_BIN="$HOME/.local/node/bin/node"
[ -n "$NODE_BIN" ] || { echo "没有 node:到 nodejs.org 下载 LTS 版,或解压到 ~/.local/node"; exit 1; }
echo "node: $NODE_BIN"; export PATH="$(dirname "$NODE_BIN"):$PATH"

say "2/6 装 Python 库(装到当前用户,不动系统)和上传工具 wrangler"
python3 -m pip install --user -q "pandas==2.3.3" "numpy==2.0.2" "PyMySQL==1.2.0" "pymssql==2.4.5" "psycopg2-binary==2.9.12"
(cd tools && npm ci --silent)

say "3/6 凭据文件 ~/.invader_env"
if [ -f "$HOME/.invader_env" ]; then
  echo "已存在,不改动。"
else
  echo "逐项输入(不会显示在屏幕上的是密码 / 令牌);值找看板负责人私下要,不要发在群里。"
  read -rp  "数据库账号 INVADER_DB_USER: " u
  read -rsp "数据库密码 INVADER_DB_PASSWORD: " p; echo
  read -rp  "Redshift 地址 INVADER_RS_HOST: " rh
  read -rp  "Redshift 端口 INVADER_RS_PORT: " rp
  read -rp  "Redshift 库名 INVADER_RS_DB: " rd
  read -rp  "Redshift 账号 INVADER_RS_USER: " ru
  read -rsp "Redshift 密码 INVADER_RS_PASSWORD: " rw; echo
  read -rsp "Cloudflare 令牌 CLOUDFLARE_API_TOKEN: " ct; echo
  read -rp  "Cloudflare 账号 ID CLOUDFLARE_ACCOUNT_ID: " ca
  read -rp  "Pages 项目名 CF_PAGES_PROJECT [invader-dashboard]: " cp; cp=${cp:-invader-dashboard}
  umask 077
  cat > "$HOME/.invader_env" <<EOF
# Invader 看板凭据(只有本人可读,勿提交、勿外传)
export INVADER_DB_USER='$u'
export INVADER_DB_PASSWORD='$p'
export INVADER_RS_HOST='$rh'
export INVADER_RS_PORT='$rp'
export INVADER_RS_DB='$rd'
export INVADER_RS_USER='$ru'
export INVADER_RS_PASSWORD='$rw'
export CLOUDFLARE_API_TOKEN='$ct'
export CLOUDFLARE_ACCOUNT_ID='$ca'
export CF_PAGES_PROJECT='$cp'
EOF
  chmod 600 "$HOME/.invader_env"; echo "已写入,权限 600。"
fi

say "4/6 下载 IP 分配表到 data/rir/(公开数据,国家筛选用)"
mkdir -p data/rir logs
for u in https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-latest https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-latest \
         https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest https://ftp.apnic.net/stats/apnic/delegated-apnic-latest \
         https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-latest; do
  curl -fsS -m 300 -o "data/rir/$(basename "$u")" "$u" && echo "  $(basename "$u")"
done

say "5/6 生成并安装定时任务(每天 10:10 / 12:10 / 14:10 / 16:10 / 18:10)"
PL="$HOME/Library/LaunchAgents/com.invader.dashboard.daily.plist"
sed "s#/Users/wangchi/DataGripProjects/invader-dashboard#$HERE#g" com.invader.dashboard.daily.plist > "$PL"
launchctl unload "$PL" 2>/dev/null || true; launchctl load "$PL"
echo "已安装:$PL"

say "6/6 检查网络和渲染"
nc -z -G 5 192.168.50.14 39995 && echo "  Invader 数据库:能连" || echo "  Invader 数据库:连不上(要连 Tunnelblick VPN)"
. "$HOME/.invader_env"; nc -z -G 5 "$INVADER_RS_HOST" "$INVADER_RS_PORT" && echo "  Redshift:能连" || echo "  Redshift:连不上(要连公司 VPN)"
python3 -c "import pandas, pymysql, pymssql, psycopg2; print('  Python 库:正常')"
echo; echo "装好了。下一步:连好两个 VPN,运行 bash scheduled_refresh.sh,看 logs/refresh.log 最后几行是不是「完成」。"
