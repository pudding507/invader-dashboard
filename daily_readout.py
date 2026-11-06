#!/usr/bin/env python3
"""Invader 601 每日读数(2026-11-06,用户:数值 / Portal 标准由我们做,每天能出可信的读数)。

每次渲染后运行:从 site/index.html 里嵌的页面数据生成一页 md,写到 ~/DataGripProjects/invader/06_每日读数/读数_<数据截至日>.md。
只列事实:数字带分子分母和口径标签,样本小的标出来;不写原因判断和建议(那些由人看过再写)。同一天重跑会覆盖。
口径规则见 ~/DataGripProjects/invader/05_知识库/看板数值标准.md。
"""
import json, math, re, sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path.home() / 'DataGripProjects' / 'invader' / '06_每日读数'


def load():
    h = (HERE / 'site' / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'<script id="dash-data" type="application/json">(.*?)</script>', h, re.S)
    return json.loads(m.group(1).replace('<\\/', '</'))


def wilson(k, n, z=1.96):
    if not n: return None
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


def pct(k, n, ci=False):
    if not n: return '—'
    s = f'{k / n:.0%}({k}/{n})'
    if ci:
        lo, hi = wilson(k, n); s += f',区间 {lo:.0%}–{hi:.0%}'
    return s + (' ⚠ 样本 < 30' if n < 30 else '')


def money(x): return '—' if x is None else f'${x:,.2f}'


def main():
    D = load(); N = D.get('n601') or {}; E = D['meta']['data_through']; NX = D.get('n601_new') or {}; V = (D.get('n601_ev') or {}).get('0') or {}
    daily = N.get('daily', []); y = daily[-1] if daily else {}; prev = daily[-8:-1]
    avg = lambda f: (sum(f(r) for r in prev) / len(prev)) if prev else None
    L = []
    L.append(f'# Invader 601 每日读数 · {E}\n')
    L.append(f'> 自动生成于 {D["meta"]["run_at"].replace("T", " ")[:16]},数据截至 {E}(中国时间)。只列事实;原因判断和建议由人看过后再写。口径规则见《看板数值标准》。\n')
    # 一 数据状态
    fe, ce = D['meta'].get('fetch_errors') or {}, D['meta'].get('compute_errors') or {}
    bad = [c for c in D.get('checks', []) if c.get('status') not in ('pass',)]
    L.append('## 一、数据状态\n')
    L.append(f'- 抓数失败 {len(fe)} 张{(":" + "、".join(fe)) if fe else ""};计算失败 {len(ce)} 项{(":" + "、".join(ce)) if ce else ""}。')
    L.append(f'- 自洽检查 {len(D.get("checks", []))} 项,通过 {len(D.get("checks", [])) - len(bad)} 项。' + ('非通过项:' if bad else ''))
    for c in bad:
        L.append(f'  - {c["name"]}({ {"warn": "提示", "na": "无法判断", "fail": "未通过"}.get(c["status"], c["status"]) }):{c.get("value", "")}')
    L.append('')
    # 二 核心数字
    L.append(f'## 二、601 核心数字 · {E[5:]} vs 前 7 天日均\n')
    L.append('| 指标 | 当天 | 前 7 天日均 | 口径 |\n|---|---:|---:|---|')
    rows = [('新建角色', lambda r: r['reg_old'] + r['reg_new'], '服务端'), ('其中广告安装', lambda r: r.get('reg_ad', 0), '埋点下限'),
            ('活跃(活跃痕迹)', lambda r: r['act_old'] + r['act_new'], '代理'), ('付费人数', lambda r: r.get('paid_payers', 0), '服务端'),
            ('收入(美元)', lambda r: r.get('paid_usd') or 0, '服务端'), ('其中 PayerMax(美元)', lambda r: r.get('paid_payermax') or 0, '按下单计入')]   # 2026-11-06 PayerMax 计入收入
    for nm, f, tag in rows:
        a = avg(f); isusd = '美元' in nm
        L.append(f'| {nm} | {money(f(y)) if isusd else f(y)} | {"—" if a is None else (money(a) if isusd else f"{a:.1f}")} | {tag} |')
    ol = {k: y.get(k, 0) for k in ('ord_paid', 'ord_pending', 'ord_test', 'ord_refund')}
    L.append(f'\n- 当天订单:计入收入 {ol["ord_paid"]} 笔、未确认 {ol["ord_pending"]} 笔、测试 {ol["ord_test"]} 笔、退款 {ol["ord_refund"]} 笔。')
    ck = [r for r in ((N.get('checkout') or {}).get('daily') or []) if r.get('d') == E]
    if ck: L.append(f'- 点击付费(Google / Apple):{ck[0]["click_users"]} 人点击、{ck[0]["order_users"]} 人下单、{ck[0]["paid_users"]} 人到账。')
    coh = [c for c in N.get('cohorts', []) if c.get('d1', {}).get('base')]
    if coh:
        c = coh[-1]; L.append(f'- 最近一个满 1 天的注册日({c["d"][5:]})D1:{pct(c["d1"]["n"], c["d1"]["base"], ci=True)}(活跃痕迹口径)。')
    L.append('')
    # 三 获客
    A = V.get('acq')
    if A:
        last = A['daily'][-1] if A['daily'] else {}
        L.append(f'## 三、获客(埋点安装来源,只覆盖同意采集的玩家)\n')
        L.append('- 当天新安装:' + '、'.join(f'{k} {last.get(k, 0)}' for k in A['srcs'] if last.get(k)) + (';' if any(last.get(k) for k in A['srcs']) else '无;') +
                 f' {A["from"]} 以来合计:' + '、'.join(f'{x["src"]} {x["installs"]}(成为角色 {x["roles"]})' for x in A['total'] if x['installs']) + '。\n')
    # 四 活动与票
    if NX.get('activities'):
        L.append('## 四、活动(库里的排期)\n')
        for a in NX['activities']:
            L.append(f'- {a["name"]}:{a["now"]};{a["periods"]} 期,{a["first"]} ~ {a["last"]}' + (f';有积分 {a["users"]} 人、{a["points"]:,.0f} 分' if a['users'] else '') + (f';发奖 {a["rewards"]}' if a['rewards'] else '') + ('(结束时间待核实)' if a.get('odd_end') else '') + '。')
        T = NX.get('tickets')
        if T and T['daily']:
            t = T['daily'][-1]; L.append(f'- 限时票:当天发 {t["issued"]:,.0f} 张、用 {t["used"]:,.0f} 张;累计发 {T["issued"]:,.0f}、用 {T["used"]:,.0f}。')
        L.append('')
    # 五 战斗、钻石
    B, W = NX.get('battles'), NX.get('wallet')
    if B or W:
        L.append('## 五、战斗与钻石(服务端新表,11-04 起)\n')
        if B and B['daily']:
            b = B['daily'][-1]; L.append('- 当天战斗:' + '、'.join(f'{k} {b.get(k, 0)}' for k in B['cats'] if b.get(k)) + ' 场。')
        if W and W['daily']:
            w = W['daily'][-1]; tot = sum(v for k, v in w.items() if k != 'd')
            L.append(f'- 当天花掉 {tot:,.0f} 钻:' + '、'.join(f'{k} {w[k]:,.0f}' for k in W['keys'] if w.get(k)) + '。')
        L.append('')
    # 六 埋点与技术
    cov = [r for r in (V.get('coverage') or []) if r.get('d') == E]
    st = [r for r in ((V.get('startup') or {}).get('daily') or []) if r.get('d') == E]
    if cov or st:
        L.append('## 六、埋点与技术\n')
        if cov and cov[0].get('act'): L.append(f'- 埋点覆盖:当天埋点里的内测玩家 {cov[0]["ev_users"]} / 看板活跃 {cov[0]["act"]}({cov[0]["ev_users"] / cov[0]["act"]:.0%})。')
        if st: L.append(f'- 启动到登录成功(按安装):{pct(st[0]["ready"], st[0]["resources"])};启动失败的安装 {st[0]["failed"]}。')
        fp = [r for r in (V.get('fps_daily') or []) if r.get('d') == E]
        if fp and fp[0]['n']: L.append(f'- 战斗低于 30 帧:{pct(fp[0]["lt30"], fp[0]["n"])} 场。')
        L.append('')
    # 七 版本、投放、活动日历(当天发生的)
    evs = [e for e in D.get('n601_events', []) if e.get('start') and e['start'][:10] <= E <= (e.get('end') or e['start'])[:10]]
    if evs:
        L.append('## 七、当天在进行的版本 / 投放 / 活动\n')
        L += [f'- {e["kind"]}:{e["name"]}({e["start"]}{" ~ " + e["end"] if e.get("end") else ""})' for e in evs]
        L.append('')
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f'读数_{E}.md'; f.write_text('\n'.join(L), encoding='utf-8')
    print(f'每日读数写入 {f}')


if __name__ == '__main__':
    main()
