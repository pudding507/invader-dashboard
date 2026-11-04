#!/bin/bash
# Invader 数据看板 · 定时刷新并发布到 Cloudflare Pages(公开链接,不需要登录)
#
# 由 ~/Library/LaunchAgents/com.invader.dashboard.daily.plist 每天 10:30 / 12:30 / 14:30 / 16:30 触发(2026-10-28 起):
#   - 当天还没有完整抓数成功 → 完整抓数(全部卡 + 今天的小卡),失败的话下一个时间点重试
#   - 当天已经成功过 → 轻量刷新:只抓「今天」的几张小卡(fetch_db.py --light),页面的「今天实时」更新到这一刻,其余沿用早上的数据
#
# 凭据放在 ~/.invader_env(chmod 600,只有本人能读),不写进代码:
#   export INVADER_DB_USER=reader
#   export INVADER_DB_PASSWORD=...
#   export CLOUDFLARE_API_TOKEN=...      # 只开 Cloudflare Pages: Edit 权限
#   export CLOUDFLARE_ACCOUNT_ID=...
#   export CF_PAGES_PROJECT=invader-dashboard
#
# 保护生产库(SQL Server 2005,老且不稳,开发特别提醒):
#   - 完整抓数在 10:30(中国时间 = 05:30 沙特时间,低峰)，白天只跑几张今天的小卡;SQL Server 上是 28 条小查询(4 条老版 + 24 条 601,多为几十到几千行;设备 ID 那条扫 1.1 万行约 30~50 秒;另加几十行的大 R 姓名),单条超时 3 分钟就放弃
#   - VPN 连不上就不碰数据库;任一张卡失败就不发布,线上保留上一版(页面超过 2 天没更新会自己显示「数据已过期」)
set -uo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/node/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
[ -f "$HOME/.invader_env" ] && . "$HOME/.invader_env"
LOG="logs/refresh.log"; TODAY=$(date +%F); DONE="logs/last_success"
log(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

MODE=full; if [ -f "$DONE" ] && [ "$(cat "$DONE")" = "$TODAY" ]; then MODE=light; fi   # 今天完整抓数已成功 → 只做轻量刷新
if ! mkdir logs/.lock 2>/dev/null; then log "上一次还在跑,跳过"; exit 0; fi       # 防止两次同时跑
trap 'rmdir logs/.lock 2>/dev/null' EXIT

for v in CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID CF_PAGES_PROJECT; do
  if [ -z "${!v:-}" ]; then log "缺少 $v(写进 ~/.invader_env),退出"; exit 3; fi
done
if ! nc -z -G 5 192.168.50.14 39995 2>/dev/null || ! nc -z -G 5 192.168.50.14 39998 2>/dev/null; then
  log "VPN 未连上数据库,跳过(线上保留上一版)"; exit 0
fi

if [ "$MODE" = light ]; then
  log "开始轻量刷新(今天的小卡)"
  python3 fetch_db.py --light >> "$LOG" 2>&1 || { log "轻量刷新失败,不发布(线上保留上一版)"; exit 1; }
else
log "开始抓数"
python3 fetch_db.py >> "$LOG" 2>&1 || { log "抓数脚本出错,不发布"; exit 1; }
fi
# 守卫:所有卡都要成功
python3 - <<'PY' >> "$LOG" 2>&1 || { log "有卡失败,不发布"; exit 1; }
import json, glob, sys
import os
r = json.load(open('raw_metrics.json')); cards = {os.path.basename(f)[:-4] for f in glob.glob('sql/*.sql')}
ok = cards & set(r['metrics'])
print(f"卡片 {len(ok)}/{len(cards)},失败 {list(r['errors'])},提示 {list(r.get('warnings', {}))}")
light = {os.path.basename(f)[:-4] for f in glob.glob('sql_light/*.sql')}
print(f"今天的小卡 {len(light & set(r['metrics']))}/{len(light)},截至 {r.get('today_at')}")
sys.exit(0 if (not r['errors'] and ok == cards and light <= set(r['metrics'])) else 1)   # 大 R 姓名失败只是提示,不拦发布
PY
python3 render_dashboard.py >> "$LOG" 2>&1 || { log "渲染出错,不发布"; exit 1; }
# 2026-10-23 守卫:页面里嵌的数据必须是合法 JSON(曾因 NaN 导致整页白屏),不合法就不发布
python3 - <<'PY' >> "$LOG" 2>&1 || { log "页面数据不是合法 JSON,不发布(线上保留上一版)"; exit 1; }
import json, re
html = open('site/index.html', encoding='utf-8').read()
m = re.search(r'<script id="dash-data" type="application/json">(.*?)</script>', html, re.S)
json.loads(m.group(1).replace('<\\/', '</'), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
print('页面数据 JSON 检查通过')
PY
log "上传到 Cloudflare Pages"
rm -rf tools/node_modules/.cache/wrangler   # 2026-10-23:wrangler 会缓存上次用过的 Account ID 并优先用它;切换个人 / 公司账号时会发错地方,所以每次发布前清掉,只认 ~/.invader_env 里的配置
(cd tools && npx wrangler pages deploy ../site --project-name="$CF_PAGES_PROJECT" --branch=main --commit-dirty=true) >> "$LOG" 2>&1 \
  || { log "上传失败,线上保留上一版"; exit 1; }
[ "$MODE" = full ] && echo "$TODAY" > "$DONE"; log "完成($MODE)"
