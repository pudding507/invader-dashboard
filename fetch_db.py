#!/usr/bin/env python3
"""Invader 看板 · 直连数据库抓卡片结果 → raw_metrics.json

现在库只能经 VPN 访问、Metabase 还没接,所以先直连跑 sql/ 下的卡片 SQL。
每个 .sql 第一行写 `-- db: log` 或 `-- db: prod`,决定连哪个库。
等开发在 Metabase 建好连接:把 sql/ 里的 SQL 原样存成 Metabase 卡片,
再换成 SoulMap 的 fetch_metabase.py(产物同为 {metrics: {卡名: [行...]}}),渲染脚本不用改。

用法:
  python3 fetch_db.py                     # 跑全部卡 → raw_metrics.json
  python3 fetch_db.py --only "Login_user day"
  python3 fetch_db.py --light             # 只抓「今天」的几张小卡,合并进已有的 raw_metrics.json(基础数据必须截至昨天)

轻量刷新(2026-10-28):sql_light/ 下的卡(今天的登录、今天的新注册)+ LIGHT_FROM_SQL 里的几张现有小卡。
完整抓数时 sql_light/ 也一起跑,这样每次发布都有「今天实时」;轻量刷新不碰其他卡,昨天及以前的数据沿用早上那份。

埋点数仓(2026-11-03):第一行写 `-- db: rs` 的卡连 Redshift 查 ods.invader_events,凭据读环境变量 INVADER_RS_*(在 ~/.invader_env)。
完整抓数后另存一份 601 每人等级快照到 data/n601_snapshots/(601 库只存当前等级,靠快照攒历史)。

凭据:读环境变量 INVADER_DB_USER / INVADER_DB_PASSWORD,
没有就读同目录 db_config.json({"user": ..., "password": ...},已在 .gitignore,勿提交)。
单张卡失败只记 errors、不中断,其余卡照常输出。

卡片之后还有一步「大 R 姓名」(2026-10-21 加):名字在各服 invade_user_n{服}.dbo.player 里,
大 R 名单每天在变,没法写成固定 SQL。这一步用订单卡算出近 90 天累计 ≥ $500 的玩家(比看板的 $1,000 宽,
保证不漏),按他们出现过的服逐服查 name(按主键查,几十行)。结果放 metrics['Whale_names'];
同时把名字追加进 data/whale_name_history.json,名字和上次不同就记一条,看板用它标「改名」。
这一步失败只记 warnings,不影响发布。
"""
from __future__ import annotations
import argparse, json, os, time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = os.environ.get('INVADER_DB_HOST', '192.168.50.14')
LOG_PORT, PROD_PORT = 39995, 39998
LIGHT_FROM_SQL = ['Revenue_today', 'N601_players detail', 'N601_activity tasks day', 'N601_checkout']   # 轻量刷新时重跑的现有小卡

def creds():
    u, p = os.environ.get('INVADER_DB_USER'), os.environ.get('INVADER_DB_PASSWORD')
    if u and p:
        return u, p
    cfg = HERE / 'db_config.json'
    if cfg.exists():
        c = json.loads(cfg.read_text())
        return c['user'], c['password']
    raise SystemExit('缺少数据库凭据:设置 INVADER_DB_USER / INVADER_DB_PASSWORD,或创建 db_config.json')

def connect(kind, user, pwd):
    if kind == 'rs':   # 2026-11-03:埋点数仓 Redshift(ods.invader_events),凭据在 ~/.invader_env 的 INVADER_RS_*,只读会话
        import psycopg2
        e = os.environ
        c = psycopg2.connect(host=e['INVADER_RS_HOST'], port=e['INVADER_RS_PORT'], dbname=e['INVADER_RS_DB'], user=e['INVADER_RS_USER'],
                             password=e['INVADER_RS_PASSWORD'], connect_timeout=15, options='-c statement_timeout=300000')
        c.set_session(readonly=True, autocommit=True)
        return c
    if kind == 'log':
        import pymysql
        return pymysql.connect(host=HOST, port=LOG_PORT, user=user, password=pwd, database='invaderLogData',
                               connect_timeout=15, read_timeout=1800, charset='utf8mb4')
    import pymssql   # SQL Server 2005:必须 tds_version 7.0
    return pymssql.connect(server=HOST, port=PROD_PORT, user=user, password=pwd, database='master',
                           login_timeout=15, timeout=180, tds_version='7.0')   # 老 SQL Server:单条查询超时 3 分钟就放弃,不重试

def jsonable(v):
    if isinstance(v, (datetime, date)): return v.isoformat(sep=' ') if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, bytes): return v.decode('utf-8', 'replace')
    return v

def whale_names(conn, metrics, through):
    """近 90 天累计 ≥ $500 的付费玩家 → 逐服查 player.name。返回行列表 [{monetId, server_id, name}]。"""
    end = datetime.fromisoformat(through) + timedelta(days=1)
    pay = defaultdict(float); servers = defaultdict(set)
    for o in metrics['Revenue_orders']:
        if datetime.fromisoformat(str(o['created_at'])[:19]) >= end - timedelta(days=90):
            pay[o['monetId']] += float(o['price'] or 0)
    ids = {m for m, v in pay.items() if v >= 500}
    for o in metrics['Revenue_orders']:
        if o['monetId'] in ids: servers[int(o['server_id'])].add(int(o['monetId']))
    for l in metrics.get('Login_user day', []):
        if l['monetId'] in ids: servers[int(l['server_id'])].add(int(l['monetId']))
    rows = []
    for sid, ms in sorted(servers.items()):
        if sid == 601: continue
        cur = conn.cursor()   # sid / monetId 都已转成 int,不会拼进别的东西
        cur.execute(f"SELECT monetId, name FROM invade_user_n{sid}.dbo.player WHERE monetId IN ({','.join(map(str, sorted(ms)))})")
        rows += [{'monetId': int(m), 'server_id': sid, 'name': n} for m, n in cur.fetchall()]
    return rows

def update_name_history(rows, day):
    """名字快照:同一个 (玩家, 服) 名字变了才追加一条。只能发现从开始记录以后的改名。"""
    f = HERE / 'data' / 'whale_name_history.json'
    f.parent.mkdir(exist_ok=True)
    h = json.loads(f.read_text()) if f.exists() else {}
    for r_ in rows:
        k = f"{r_['monetId']}@{r_['server_id']}"
        hist = h.setdefault(k, [])
        if not hist or hist[-1]['name'] != r_['name']:
            hist.append({'date': day, 'name': r_['name']})
    f.write_text(json.dumps(h, ensure_ascii=False, indent=0))
    return h

_RIR = None
def ip_country(ip):
    """IP → 国家码(小写),查本地 data/rir/ 下五大洲 IP 管理机构的公开分配表(2026-11-04 下载,每月可重新下载)。查不到返回 None。"""
    global _RIR
    import bisect, ipaddress
    if _RIR is None:
        rng = {4: [], 6: []}
        for f in (HERE / 'data' / 'rir').glob('delegated-*'):
            for line in f.read_text(errors='ignore').splitlines():
                p_ = line.split('|')
                if len(p_) < 7 or p_[2] not in ('ipv4', 'ipv6') or p_[1] in ('*', '') or p_[6] not in ('allocated', 'assigned'):
                    continue
                if p_[2] == 'ipv4':
                    a = int(ipaddress.IPv4Address(p_[3])); rng[4].append((a, a + int(p_[4]) - 1, p_[1].lower()))
                else:
                    n_ = ipaddress.IPv6Network(f"{p_[3]}/{p_[4]}", strict=False); rng[6].append((int(n_.network_address), int(n_.broadcast_address), p_[1].lower()))
        for k in rng: rng[k].sort()
        _RIR = {k: (v, [x[0] for x in v]) for k, v in rng.items()}
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None
    v, starts = _RIR[a.version]; i = bisect.bisect_right(starts, int(a)) - 1
    return v[i][2] if i >= 0 and v[i][1] >= int(a) else None

def post_process(name, rows):
    """个别卡抓完后在本地加工:N601_accounts 的注册 IP 换成国家码后删掉,不落盘。"""
    if name == 'N601_accounts':
        for r_ in rows:
            r_['country'] = ip_country(r_.pop('ip', None) or '')
    return rows

def save_n601_snapshot(metrics, through):
    """2026-11-03:601 库只存当前等级,没有历史。每天完整抓数后把每人各类建筑的最高等级(b5 = 主城)、
    英雄最高等级存一份到 data/n601_snapshots/<数据截至日>.json,攒下来算成长曲线。同一天重跑会覆盖。"""
    d = HERE / 'data' / 'n601_snapshots'; d.mkdir(parents=True, exist_ok=True)
    snap = defaultdict(dict)
    for r_ in metrics.get('N601_progress building', []):
        snap[int(r_['monetId'])][f"b{int(r_['building_type'])}"] = int(r_['max_level'])
    for r_ in metrics.get('N601_progress hero', []):
        snap[int(r_['monetId'])]['hero'] = int(r_['max_hero_level'])
    (d / f'{through}.json').write_text(json.dumps({'data_through': through, 'saved_at': datetime.now().isoformat(timespec='seconds'),
                                                   'players': snap}, ensure_ascii=False))
    return f'{len(snap)} 人 → data/n601_snapshots/{through}.json'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(HERE / 'raw_metrics.json'))
    ap.add_argument('--only', action='append')
    ap.add_argument('--light', action='store_true')
    a = ap.parse_args()
    user, pwd = creds()
    light_cards = sorted((HERE / 'sql_light').glob('*.sql'))
    if a.light:
        base = json.loads(Path(a.out).read_text()) if Path(a.out).exists() else {}
        if base.get('data_through') != (date.today() - timedelta(days=1)).isoformat() or base.get('errors'):
            print(f"基础数据截至 {base.get('data_through')}、失败 {list(base.get('errors', {}))},不是昨天的完整数据,先做完整抓数")
            raise SystemExit(2)
        cards = light_cards + [HERE / 'sql' / f'{n}.sql' for n in LIGHT_FROM_SQL]
    else:
        cards = sorted((HERE / 'sql').glob('*.sql')) + ([] if a.only else light_cards)
    if a.only: cards = [c for c in cards if c.stem in a.only]
    now = datetime.now().isoformat(timespec='seconds')
    out = {'run_at': now, 'today_at': now,
           'data_through': (date.today() - timedelta(days=1)).isoformat(),
           'source': 'direct-db', 'metrics': {}, 'errors': {}}
    conns = {}
    for f in cards:
        sql = f.read_text()
        first = sql.splitlines()[0]
        kind = 'log' if 'db: log' in first else 'rs' if 'db: rs' in first else 'prod'
        # 2026-10-28:VPN 不稳时连接会被重置,每张卡失败后重新连接再试一次(只试一次,不反复打库)
        for attempt in (1, 2):
            t = time.time()
            try:
                if kind not in conns: conns[kind] = connect(kind, user, pwd)
                cur = conns[kind].cursor(); cur.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = post_process(f.stem, [dict(zip(cols, map(jsonable, r))) for r in cur.fetchall()])
                out['metrics'][f.stem] = rows; out['errors'].pop(f.stem, None)
                print(f'  OK  {f.stem}: {len(rows)} 行, {time.time()-t:.0f}s' + ('(重试成功)' if attempt == 2 else ''), flush=True)
                break
            except Exception as e:
                out['errors'][f.stem] = str(e)[:300]
                print(f'  FAIL {f.stem}(第 {attempt} 次): {str(e)[:200]}', flush=True)
                conns.pop(kind, None)
    if a.light:   # 合并:只替换这几张小卡,其余沿用基础数据;任一张失败就不写文件,不发布
        if out['errors']:
            print(f"轻量刷新失败 {list(out['errors'])},保留原数据"); raise SystemExit(1)
        base['metrics'].update(out['metrics']); base['today_at'] = now
        Path(a.out).write_text(json.dumps(base, ensure_ascii=False))
        print(f'轻量刷新写入 {a.out}:{len(out["metrics"])} 张卡'); return
    out['warnings'] = {}
    if not a.only and 'Revenue_orders' in out['metrics']:
        t = time.time()
        try:
            if 'prod' not in conns: conns['prod'] = connect('prod', user, pwd)
            rows = whale_names(conns['prod'], out['metrics'], out['data_through'])
            out['metrics']['Whale_names'] = rows
            out['whale_name_history'] = update_name_history(rows, date.today().isoformat())
            print(f'  OK  Whale_names: {len(rows)} 行, {time.time()-t:.0f}s', flush=True)
        except Exception as e:
            out['warnings']['Whale_names'] = str(e)[:300]
            print(f'  WARN Whale_names(不影响发布): {str(e)[:200]}', flush=True)
    if not a.only:
        try:
            print(f'  OK  601 快照: {save_n601_snapshot(out["metrics"], out["data_through"])}', flush=True)
        except Exception as e:
            out['warnings']['N601_snapshot'] = str(e)[:300]
            print(f'  WARN 601 快照(不影响发布): {str(e)[:200]}', flush=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False))
    print(f'写出 {a.out}:{len(out["metrics"])} 张卡,失败 {len(out["errors"])} 张')

if __name__ == '__main__':
    main()
