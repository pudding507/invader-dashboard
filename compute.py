"""Invader 看板 · 计算层:raw_metrics.json → 页面用的 DATA(dict)

口径全部按《Invader数据现状与分析方法》《Invader看板产品规格》:
- 活跃 = 当天有登录记录(GetUserInfo,dateCN,中国时间);一个账号多个服只算一次
- 新用户 = user_info.create_date 在期内;平台取 sysType
- 留存 = 注册后第 N 天当天有登录,只统计已满 N 天的 cohort
- 收入 = TopUpRecord 美元毛流水,不含 601(已在 SQL 里排除)
- 等级段:窗口类指标取窗口内最高等级;新手漏斗取注册当天最高
- 两个自动事件(进游戏自动生产士兵、主城 2 级自动成就)不进任何「主动行为」指标(MVP 未用这两张表)
单项计算失败只把该块置空,不拖垮整页(见 errors)。
"""
from __future__ import annotations
import json
import math
import os
from collections import defaultdict
from datetime import date, timedelta
import pandas as pd
import numpy as np

BANDS = [(1, 2, '1-2'), (3, 5, '3-5'), (6, 10, '6-10'), (11, 15, '11-15'), (16, 20, '16-20'), (21, 25, '21-25'), (26, 26, '26')]
BAND_NAMES = [b[2] for b in BANDS]
PLATS = ['all', 'iOS', 'Android']
WINDOWS = [7, 14, 30, 90]
GAMBLING = ('PetQuiz', 'SlotSpin')
# 2026-10-29 外部接入:Log 库只有发进来的钻石(addDiamond),没有对应的下注扣钻记录,净额算不出,单列、不进游戏内循环
EXTERNAL = {'Wpp': 'WPP', 'GameAPI': 'GameAPI'}
TICKET_USE = {'PetQuiz': '宠物竞猜', 'SlotSpin': '老虎机'}   # 老虎机券(道具 52001)的用途,useItem.from


def band_of(level):
    if level is None or (isinstance(level, float) and math.isnan(level)) or level < 1:
        return '1-2'
    for lo, hi, name in BANDS:
        if lo <= level <= hi:
            return name
    return '26'


def plat_from_client(ct):
    if ct == 'googleClient':
        return 'Android'
    if ct in ('iosClient', 'apple'):
        return 'iOS'
    return '其他'


def plat_from_sys(s):
    s = (s or '').lower()
    if s.startswith('android'):
        return 'Android'
    if s.startswith('ios'):
        return 'iOS'
    return '其他'


def r(x, n=4):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    return round(float(x), n)


def safe(fn, errors, key):
    try:
        return fn()
    except Exception as e:  # 单块失败只置空
        errors[key] = f'{type(e).__name__}: {e}'
        return None


class Ctx:
    def __init__(self, raw):
        m = raw['metrics']
        self.end = pd.Timestamp(raw['data_through'])
        self.run_at = raw.get('run_at')
        self.today_at = raw.get('today_at')   # 「今天实时」那几张卡单独补抓时的时间
        LS = pd.DataFrame(m['Login_user day'])          # 账号 × 天 × 服
        LS['d'] = pd.to_datetime(LS.dateCN)
        LS = LS[LS.server_id != 601].copy()
        LS['plat'] = LS.client_type.map(plat_from_client)
        if 'last_login_at' not in LS:   # 2026-10-21 前的抓数结果没有这一列
            LS['last_login_at'] = None
        self.LS = LS
        # 账号 × 天:等级取各服最高,联盟取最高,平台 / 服 取等级最高的那个角色
        LS2 = LS.sort_values(['monetId', 'd', 'max_level'])
        L = LS2.groupby(['monetId', 'd'], as_index=False).agg(
            login_records=('login_records', 'sum'), max_level=('max_level', 'max'), alliance_id=('alliance_id', 'max'),
            plat=('plat', 'last'), client_version=('client_version', 'last'), server_id=('server_id', 'last'),
            last_login_at=('last_login_at', 'max'))
        L['dateCN'] = L.d.dt.strftime('%Y-%m-%d')
        L['band'] = L.max_level.map(band_of)
        self.L = L
        A = pd.DataFrame(m['NewUser_accounts'])
        A['t'] = pd.to_datetime(A.create_date, format='mixed')
        A = A.sort_values('t').drop_duplicates('monetId')
        A['reg'] = A.t.dt.normalize()
        A['plat'] = A.sys_type.map(plat_from_sys)
        # 2026-10-21:剔除 601 新版内测服的账号。601 不写老版登录日志,内测账号在这里表现为「注册了但没进游戏」,
        # 会把进入游戏率和留存拉低(10 月新注册里有 127 个,全部没进过老版)。
        self.n601 = set(r_['monetId'] for r_ in m.get('N601_players', []))
        self.n601_excluded = int(A.monetId.isin(self.n601).sum())
        A = A[~A.monetId.isin(self.n601)]
        self.A = A
        self.names = pd.DataFrame(m.get('Whale_names', []))
        self.name_hist = raw.get('whale_name_history', {})
        self.raw = m
        O = pd.DataFrame(m['Revenue_orders'])
        O['t'] = pd.to_datetime(O.created_at, format='mixed')
        O['d'] = O.t.dt.normalize()
        self.O = O
        F = pd.DataFrame(m['Revenue_first order'])
        F['first'] = pd.to_datetime(F.first_order_at, format='mixed').dt.normalize()
        self.first_order = F.set_index('monetId')['first']
        self.pvp = pd.DataFrame(m.get('PvP_attacker day', []))
        self.ally = pd.DataFrame(m.get('Alliance_contrib day', []))
        self.pve = pd.DataFrame(m.get('PvE_dungeon day', []))
        for df in (self.pvp, self.ally, self.pve):
            if len(df):
                df['d'] = pd.to_datetime(df.dateCN)
        # 国家:getUserCountry 里两种写法并存。两位码(sa / eg)当作国家;ar_KW 这类是手机的「语言_地区」设置,
        # 不代表玩家所在地,不猜,和 Unknown、缺失一起算「未知」
        cty = pd.DataFrame(m.get('User_country', []))
        def norm_c(x):
            x = (x or '').strip().lower()
            if len(x) == 2 and x.isalpha():
                return x
            return '未知'
        self.country = cty.set_index('monetId').country.map(norm_c) if len(cty) else pd.Series(dtype=str)
        # 2026-10-30 补全:getUserCountry 没有国家的,用各服 player.countryCode(游戏服务器记录;10-30 核对两边都有的 5,493 个账号 99% 一致)。
        # 一个账号在多个服时取出现最多的国家;每个账号的国家来源记在 self.country_src
        known = self.country[self.country != '未知']
        src_ = pd.Series('getUserCountry', index=known.index)
        PC = pd.DataFrame(m.get('User_country by server', []))
        if len(PC):
            PC['cc'] = PC.country_code.map(norm_c)
            pc = PC[PC.cc != '未知'].groupby('monetId').cc.agg(lambda s_: s_.value_counts().index[0])
            fill = pc[~pc.index.isin(known.index)]
            known = pd.concat([known, fill]); src_ = pd.concat([src_, pd.Series('区服记录', index=fill.index)])
        self.country = known
        self.country_src = src_
        G = pd.concat([pd.DataFrame(m.get('Gameplay_participation day', [])), pd.DataFrame(m.get('Gameplay_participation day (no index)', []))])
        if len(G):
            G['d'] = pd.to_datetime(G.dateCN)
        self.G = G
        PB = pd.DataFrame(m.get('PvP_battle day', []))
        if len(PB):
            PB['d'] = pd.to_datetime(PB.dateCN)
        self.PB = PB
        self.loot = pd.DataFrame(m.get('PvP_loot daily', []))
        self.dia = pd.DataFrame(m.get('Diamond_flow daily', []))
        if len(self.dia):
            self.dia['d'] = pd.to_datetime(self.dia.dateCN)
        self.login_set = set(zip(self.L.monetId, self.L.d))
        # 2026-10-29:剔除疑似刷量注册(用户确认)。疑似刷量机型见 farm_models();只剔除这些机型里「注册当天没进游戏」的号,
        # 进了游戏的照常算,其他机型不受影响。剔除的号留在 self.farm_regs,页面单列;self.A_all 保留全部注册
        self.A_all = self.A
        self.farm_list = sorted(farm_models(self).index)
        ent = pd.Series([(a, d) in self.login_set for a, d in zip(self.A.monetId, self.A.reg)], index=self.A.index)
        fr = self.A.phone_type.fillna('未知').isin(self.farm_list) & ~ent
        self.farm_regs = self.A[fr]
        self.A = self.A[~fr]
        self.start = self.L.d.min()
        # 每个用户每天的平台 / 等级段,订单按当天属性归类,当天没登录就用最近一次
        self.L['country'] = self.L.monetId.map(self.country).fillna('未知')
        self.L['ver'] = self.L.client_version.fillna('未知')
        self.user_last = self.L.sort_values('d').groupby('monetId').last()[['plat', 'band', 'country', 'ver']]
        # 分段:等级段 / 国家 / 版本(一次只能选一个,和平台、时间自由组合)。国家、版本只列近 30 天活跃 ≥ 30 人的
        recent = self.L[self.L.d > self.end - pd.Timedelta(days=30)]
        cu = recent.groupby('country').monetId.nunique().sort_values(ascending=False)
        vu = recent.groupby('ver').monetId.nunique().sort_values(ascending=False)
        self.countries = [c_ for c_, n in cu.items() if n >= 30 and c_ != '未知'] + ['未知']
        self.versions = [v for v, n in vu.items() if n >= 20]
        self.segs = ['all'] + BAND_NAMES + ['c:' + c_ for c_ in self.countries] + ['v:' + v for v in self.versions]

    def day(self, k):
        return self.end - pd.Timedelta(days=k)


def window_users(c, w, end=None):
    """窗口内活跃用户及其窗口属性:平台 = 窗口内出现最多的平台,等级段 = 窗口内最高等级。"""
    end = end or c.end
    x = c.L[(c.L.d > end - pd.Timedelta(days=w)) & (c.L.d <= end)]
    g = x.groupby('monetId').agg(days=('d', 'nunique'), lvl=('max_level', 'max'), aid=('alliance_id', 'max'),
                                 plat=('plat', lambda s: s.mode().iat[0]), ver=('ver', 'last'))
    g['band'] = g.lvl.map(band_of)
    g['country'] = g.index.map(c.country).fillna('未知')
    return g


def filt(df, plat, seg, plat_col='plat', band_col='band'):
    """seg:'all' / 等级段名 / 'c:国家码' / 'v:版本号'"""
    if plat != 'all':
        df = df[df[plat_col] == plat]
    if seg == 'all':
        return df
    if seg.startswith('c:'):
        return df[df['country'] == seg[2:]]
    if seg.startswith('v:'):
        return df[df['ver'] == seg[2:]]
    return df[df[band_col] == seg]


# ---------------------------------------------------------------- 日序列(首页趋势、商业化趋势)
def daily_series(c):
    days = pd.date_range(c.end - pd.Timedelta(days=119), c.end)
    L = c.L[c.L.d > c.end - pd.Timedelta(days=150)]
    O = c.O.copy()
    # 订单归类:当天有登录用当天属性,否则用该用户最近属性
    day_attr = c.L.set_index(['monetId', 'd'])[['plat', 'band']]
    keys = list(zip(O.monetId, O.d))
    idx = pd.MultiIndex.from_tuples(keys, names=['monetId', 'd'])
    got = day_attr.reindex(idx)
    last = c.user_last.reindex(O.monetId)
    O['plat'] = np.where(got.plat.notna().values, got.plat.values, last.plat.values)
    O['band'] = np.where(got.band.notna().values, got.band.values, last.band.values)
    O['plat'] = O['plat'].fillna('其他')
    O['band'] = O['band'].fillna('1-2')
    O['country'] = O.monetId.map(c.country).fillna('未知')
    O['ver'] = O.monetId.map(c.user_last.ver).fillna('未知')
    out = {}
    by_day = {d: grp for d, grp in L.groupby('d')}
    for plat in PLATS:
        for band in c.segs:
            key = f'{plat}|{band}'
            sets = {}
            for d in pd.date_range(days[0] - pd.Timedelta(days=29), days[-1]):
                g = by_day.get(d)
                sets[d] = set(filt(g, plat, band).monetId) if g is not None else set()
            oo = filt(O, plat, band)
            rev = oo.groupby('d').price.sum()
            pay = oo.groupby('d').monetId.nunique()
            rows = []
            for d in days:
                wau = set().union(*[sets[d - pd.Timedelta(days=i)] for i in range(7)])
                mau = set().union(*[sets[d - pd.Timedelta(days=i)] for i in range(30)])
                rv, py = float(rev.get(d, 0.0)), int(pay.get(d, 0))
                rows.append([d.strftime('%Y-%m-%d'), len(sets[d]), len(wau), len(mau), round(rv, 2), py])
            out[key] = rows
    return {'columns': ['date', 'dau', 'wau', 'mau', 'revenue', 'payers'], 'series': out}


# ---------------------------------------------------------------- 窗口 KPI(首页、商业化)
def window_kpis(c):
    res = {}
    for w in WINDOWS:
        cur_u = window_users(c, w)
        prev_u = window_users(c, w, c.end - pd.Timedelta(days=w))
        for plat in PLATS:
            for band in c.segs:
                def kp(users, end):
                    u = filt(users, plat, band)
                    o = c.O[(c.O.d > end - pd.Timedelta(days=w)) & (c.O.d <= end)]
                    o = o[o.monetId.isin(u.index)] if (plat != 'all' or band != 'all') else o
                    payers = o.monetId.nunique(); rev = o.price.sum()
                    active = len(u)
                    fo = c.first_order.reindex(o.monetId.unique())
                    new_payers = int(((fo > end - pd.Timedelta(days=w)) & (fo <= end)).sum())
                    regs = c.A[(c.A.reg > end - pd.Timedelta(days=w)) & (c.A.reg <= end)]
                    if plat != 'all':
                        regs = regs[regs.plat == plat]
                    if band.startswith('c:'):
                        regs = regs[regs.monetId.map(c.country).fillna('未知') == band[2:]]
                    rev_new = o[o.monetId.isin(regs.monetId)].price.sum()
                    return {'active': active, 'revenue': r(rev, 2), 'payers': int(payers),
                            'pay_rate': r(payers / active) if active else None,
                            'arpu': r(rev / active, 2) if active else None,
                            'arppu': r(rev / payers, 2) if payers else None,
                            'new_payers': new_payers, 'repeat_payers': int(payers - new_payers),
                            'registrations': int(len(regs)), 'rev_per_new_user': r(rev_new / len(regs), 3) if len(regs) else None,
                            'avg_days': r(u.days.mean(), 2) if active else None}
                res[f'{w}|{plat}|{band}'] = {'cur': kp(cur_u, c.end), 'prev': kp(prev_u, c.end - pd.Timedelta(days=w))}
    return res


# ---------------------------------------------------------------- 新用户
def new_user(c):
    A = c.A[c.A.reg <= c.end].copy()
    L = c.L
    d0 = L.merge(A[['monetId', 'reg']], on='monetId')
    d0 = d0[d0.d == d0.reg].groupby('monetId').max_level.max()
    A['entered'] = A.monetId.isin(d0.index)
    A['d0_lvl'] = A.monetId.map(d0).fillna(0)
    for n in (1, 3, 7, 14, 30):
        A[f'd{n}'] = [(m, r_ + pd.Timedelta(days=n)) in c.login_set for m, r_ in zip(A.monetId, A.reg)]
        A[f'm{n}'] = A.reg + pd.Timedelta(days=n) <= c.end
    # 每人注册后 N 天内的最高等级(成长速度)
    lj = L.merge(A[['monetId', 'reg']], on='monetId')
    lj['age'] = (lj.d - lj.reg).dt.days
    for n in (0, 1, 3, 7, 14, 30):
        mx = lj[lj.age.between(0, n)].groupby('monetId').max_level.max()
        A[f'lvl_by_d{n}'] = A.monetId.map(mx).fillna(0)
    od = c.O.merge(A[['monetId', 'reg']], on='monetId')
    od = od[(od.d >= od.reg) & (od.d <= od.reg + pd.Timedelta(days=30))]
    A['pay30'] = A.monetId.isin(od.monetId)
    out = {}
    # 日序列:注册、进入率、Lv3 转化,分平台
    days = pd.date_range(c.end - pd.Timedelta(days=119), c.end)
    ser = {}
    for plat in PLATS:
        a = A if plat == 'all' else A[A.plat == plat]
        g = a.groupby('reg').agg(n=('monetId', 'size'), ent=('entered', 'sum'), l2=('d0_lvl', lambda s: int((s >= 2).sum())),
                                 l3=('d0_lvl', lambda s: int((s >= 3).sum())), d1=('d1', 'sum'), d7=('d7', 'sum'), d30=('d30', 'sum'),
                                 p30=('pay30', 'sum'))
        g = g.reindex(days, fill_value=0)
        ser[plat] = [[d.strftime('%Y-%m-%d'), int(v.n), int(v.ent), int(v.l2), int(v.l3), int(v.d1), int(v.d7), int(v.d30), int(v.p30)]
                     for d, v in g.iterrows()]
    # d1 / d7 / d30 / p30 只对已满期的注册日有意义(注册日 + N <= 数据截至日),页面按日期自己判断
    out['daily'] = {'columns': ['date', 'registrations', 'entered', 'lv2', 'lv3', 'd1', 'd7', 'd30', 'pay30'], 'series': ser}
    # 严格嵌套漏斗:注册在 [END-30-w+1, END-30],全部满 30 天
    fun = {}
    for w in WINDOWS:
        hi = c.end - pd.Timedelta(days=30); lo = hi - pd.Timedelta(days=w - 1)
        for plat in PLATS:
            a = A[(A.reg >= lo) & (A.reg <= hi)]
            if plat != 'all':
                a = a[a.plat == plat]
            steps = [('注册', np.ones(len(a), bool)), ('当天进入游戏', a.entered.values), ('当天主城 ≥2 级', (a.d0_lvl >= 2).values),
                     ('当天主城 ≥3 级', (a.d0_lvl >= 3).values), ('D1 登录', a.d1.values), ('D3 登录', a.d3.values),
                     ('D7 登录', a.d7.values), ('D14 登录', a.d14.values), ('D30 登录', a.d30.values)]
            cum = np.ones(len(a), bool); rows = []
            for name, mask in steps:
                cum = cum & mask
                rows.append([name, int(cum.sum())])
            fun[f'{w}|{plat}'] = {'from': lo.strftime('%Y-%m-%d'), 'to': hi.strftime('%Y-%m-%d'), 'steps': rows,
                                  'pay30': int(a.pay30.sum()), 'n': int(len(a))}
    out['funnel'] = fun
    # Cohort 热力图(按注册周,周一开始)
    A['week'] = A.reg - pd.to_timedelta(A.reg.dt.weekday, unit='D')
    coh = {}
    for plat in PLATS:
        a = A if plat == 'all' else A[A.plat == plat]
        rows = []
        for wk, g in sorted(a.groupby('week'), key=lambda kv: kv[0])[-20:]:
            wk_end = wk + pd.Timedelta(days=6)
            row = {'week': wk.strftime('%Y-%m-%d'), 'n': int(len(g)), 'entered': int(g.entered.sum())}
            row['D0'] = r(g.entered.mean())
            for n in (1, 3, 7, 14, 30):
                row[f'D{n}'] = r(g[f'd{n}'].mean()) if wk_end + pd.Timedelta(days=n) <= c.end else None
                row[f'D{n}_e'] = r(g[g.entered][f'd{n}'].mean()) if (wk_end + pd.Timedelta(days=n) <= c.end and g.entered.any()) else None
            rows.append(row)
        coh[plat] = rows
    out['cohort'] = coh
    # 成长速度:注册于 31~150 天前(都满 30 天)
    prog = {}
    base = A[(A.reg <= c.end - pd.Timedelta(days=30)) & A.entered]
    for plat in PLATS:
        a = base if plat == 'all' else base[base.plat == plat]
        dist = {}
        for n in (0, 1, 3, 7, 14, 30):
            vc = a[f'lvl_by_d{n}'].map(band_of).value_counts()
            dist[f'D{n}'] = [int(vc.get(b, 0)) for b in BAND_NAMES]
        reach = {str(L_): r((a.lvl_by_d30 >= L_).mean()) for L_ in (3, 6, 10, 15, 20, 26)}
        prog[plat] = {'n': int(len(a)), 'dist': dist, 'reach_d30': reach,
                      'from': a.reg.min().strftime('%Y-%m-%d') if len(a) else None, 'to': a.reg.max().strftime('%Y-%m-%d') if len(a) else None}
    out['progression'] = prog
    # 进入率下钻:近 28 天 Android 按系统版本 / 机型
    rec = A[A.reg > c.end - pd.Timedelta(days=28)]
    def tab(col):
        g = rec.groupby(['plat', col]).agg(n=('monetId', 'size'), ent=('entered', 'sum')).reset_index()
        g = g.sort_values('n', ascending=False).head(15)
        return [[p, str(v), int(n), int(e)] for p, v, n, e in g.values]
    out['entry_drill'] = {'by_sys': tab('sys_type'), 'by_phone': tab('phone_type'),
                          'from': (c.end - pd.Timedelta(days=27)).strftime('%Y-%m-%d')}
    c.A_enriched = A
    return out


# ---------------------------------------------------------------- 生命周期
def lifecycle(c):
    out = {}
    pvp = c.pvp; pve = c.pve
    for w in WINDOWS:
        u = window_users(c, w)
        ww = min(w, 60)   # PvP / PvE 只抓了 60 天
        pv = set(pvp[pvp.d > c.end - pd.Timedelta(days=ww)].monetId) if len(pvp) else set()
        pe = set(pve[pve.d > c.end - pd.Timedelta(days=ww)].monetId) if len(pve) else set()
        o = c.O[(c.O.d > c.end - pd.Timedelta(days=w))]
        rev = o.groupby('monetId').price.sum()
        u['rev'] = u.index.map(rev).fillna(0.0)
        u['pvp'] = u.index.isin(pv); u['pve'] = u.index.isin(pe)
        for plat, seg in [(p_, s_) for p_ in PLATS for s_ in c.segs if s_ == 'all' or s_[:2] in ('c:', 'v:')]:
            uu = filt(u, plat, seg)
            rows = []
            for b in BAND_NAMES:
                g = uu[uu.band == b]
                n = len(g); payers = int((g.rev > 0).sum())
                rows.append({'band': b, 'users': n, 'avg_days': r(g.days.mean(), 1) if n else None,
                             'alliance': r((g.aid > 0).mean()) if n else None, 'pvp': r(g.pvp.mean()) if n else None,
                             'pve': r(g.pve.mean()) if n else None, 'payers': payers, 'pay_rate': r(payers / n) if n else None,
                             'revenue': r(g.rev.sum(), 2), 'arppu': r(g.rev.sum() / payers, 1) if payers else None})
            out[f'{w}|{plat}|{seg}'] = {'rows': rows, 'pv_window': ww}
    # 15 天留存:前 15 天活跃者在后 15 天是否还登录(固定窗口)
    early = window_users(c, 15, c.end - pd.Timedelta(days=15))
    late = set(c.L[c.L.d > c.end - pd.Timedelta(days=15)].monetId)
    early['kept'] = early.index.isin(late)
    ret = {}
    for plat in PLATS:
        e = early if plat == 'all' else early[early.plat == plat]
        ret[plat] = [[b, int((e.band == b).sum()), int(e[e.band == b].kept.sum())] for b in BAND_NAMES]
    out['retention15'] = {'rows': ret, 'early': [(c.end - pd.Timedelta(days=29)).strftime('%Y-%m-%d'), (c.end - pd.Timedelta(days=15)).strftime('%Y-%m-%d')],
                          'late': [(c.end - pd.Timedelta(days=14)).strftime('%Y-%m-%d'), c.end.strftime('%Y-%m-%d')]}
    # 流失:在 [END-43, END-14] 活跃,之后 14 天没有登录
    act = window_users(c, 30, c.end - pd.Timedelta(days=14))
    last = c.L.groupby('monetId').d.max()
    # 用 reindex 保持日期类型:新开服窗口内没人时 act 为空,Index.map 会退化成 int64 导致比较报错(10-26 新开的 351 服)
    act['churn'] = (last.reindex(act.index) <= c.end - pd.Timedelta(days=14)).values
    ch = {}
    for plat in PLATS:
        a = act if plat == 'all' else act[act.plat == plat]
        ch[plat] = [[b, int((a.band == b).sum()), int(a[a.band == b].churn.sum())] for b in BAND_NAMES]
    out['churn'] = {'rows': ch, 'window': [(c.end - pd.Timedelta(days=43)).strftime('%Y-%m-%d'), (c.end - pd.Timedelta(days=14)).strftime('%Y-%m-%d')]}
    # 升级速度:首次到达各级日期之差(只统计在数据窗口内被观察到从低于 L 级升上来的人,避免左截断)
    # 按 账号 × 服 计算:同一账号不同服的角色各算各的
    Ls = c.LS.sort_values('d').copy()
    Ls['key'] = Ls.monetId.astype(str) + '@' + Ls.server_id.astype(str)
    reach = {}
    for L_ in (2, 3, 6, 10, 15, 20, 26):
        reach[L_] = Ls[Ls.max_level >= L_].groupby('key').d.first()
    first_lvl = Ls.groupby('key').max_level.first()
    pairs = [(1, 2), (2, 3), (3, 6), (6, 10), (10, 15), (15, 20), (20, 26)]
    sp = []
    for a_, b_ in pairs:
        if a_ == 1:
            start = Ls.groupby('key').d.first()
            ok = first_lvl[first_lvl < 2].index
        else:
            start = reach[a_]
            ok = first_lvl[first_lvl < a_].index
        end_ = reach[b_]
        ids = start.index.intersection(end_.index).intersection(ok)
        days_ = (end_[ids] - start[ids]).dt.days
        sp.append({'from': a_, 'to': b_, 'n': int(len(days_)), 'median': r(days_.median(), 1) if len(days_) else None,
                   'p75': r(days_.quantile(.75), 1) if len(days_) else None})
    out['speed'] = sp
    return out


# ---------------------------------------------------------------- 今天实时(2026-10-28)
# 今天 0 点到抓数时刻,未完整,只单独展示,不进任何日指标 / 告警。601 订单同样剔除统一排除名单里的账号
def today_live(c):
    """今天 0 点到抓数时刻。和「昨天同一时刻」对照(昨天 0 点到昨天的同一钟点),半天的数才看得出快慢。
    老服 DAU 用 Login_today(昨天 + 今天,带每人当天首次登录时间);新注册用 NewUser_today,昨天同刻用 NewUser_accounts;
    订单昨天同刻用 Revenue_orders。601 只统计内测开始后注册、不在排除名单里的角色(和 601 页同口径),601 没有昨天同刻对照。"""
    day = (c.end + pd.Timedelta(days=1)).strftime('%Y-%m-%d'); yday = c.end.strftime('%Y-%m-%d')
    as_of = pd.Timestamp(c.today_at or c.run_at)
    clock = as_of - as_of.normalize()                       # 当天已过去的时长
    y_cut = c.end + clock                                   # 昨天的同一时刻
    ex601, _, _ = load_exclusions('n601')
    out = {'day': day, 'as_of': as_of.strftime('%Y-%m-%d %H:%M'), 'y_cut': y_cut.strftime('%H:%M')}
    def part(x):
        return {'orders': int(len(x)), 'payers': int(x.monetId.nunique()) if len(x) else 0, 'usd': r(x.price.sum(), 2) if len(x) else 0.0}
    # 订单
    T = pd.DataFrame(c.raw.get('Revenue_today', []))
    if len(T):
        T['t'] = pd.to_datetime(T.created_at, format='mixed'); T = T[T.t.dt.strftime('%Y-%m-%d') == day]
    old = T[T.server_id != 601] if len(T) else T
    n6 = T[(T.server_id == 601) & ~T.monetId.isin(ex601)] if len(T) else T
    out['old'] = part(old)
    out['old_y'] = part(c.O[(c.O.d == c.end) & (c.O.t <= y_cut)])
    out['old_y_full'] = part(c.O[c.O.d == c.end])
    out['n601'] = part(n6)
    out['n601_orders'] = [{'t': x.t.strftime('%H:%M'), 'id': int(x.monetId), 'ch': x.channel, 'product': x.product_id, 'usd': r(x.price, 2)}
                          for _, x in n6.sort_values('t').iterrows()] if len(n6) else []
    # 老服 DAU
    LT = pd.DataFrame(c.raw.get('Login_today', []))
    if len(LT):
        LT = LT[LT.server_id != 601]
        LT['first'] = pd.to_datetime(LT.first_login_at, format='mixed'); LT['dd'] = LT.dateCN.astype(str).str[:10]
        tod = LT[LT.dd == day]; yd = LT[LT.dd == yday]
        # Log 库是批量写入的(10-28 观察:17:21 抓到的最新登录是 16:59:57),所以昨天对照按今天登录数据实际截至的钟点切
        lt_max = pd.to_datetime(tod.last_login_at, format='mixed').max() if len(tod) else as_of
        ly_cut = c.end + (lt_max - lt_max.normalize())
        out['dau'] = int(tod.monetId.nunique())
        out['dau_y'] = int(yd[yd['first'] <= ly_cut].monetId.nunique())
        out['dau_y_full'] = int(yd.monetId.nunique())
        out['login_through'] = lt_max.strftime('%H:%M')
        today_ids = set(tod.monetId)
    else:
        today_ids = set()
    # 老服新注册(去掉 601 角色,和新用户页同口径);疑似刷量机型单列
    NT = pd.DataFrame(c.raw.get('NewUser_today', []))
    n601_ids = c.n601 | set(r_['monetId'] for r_ in c.raw.get('N601_players detail', []))
    fm_ = set(farm_models(c).index)
    if len(NT):
        NT = NT[~NT.monetId.isin(n601_ids)].drop_duplicates('monetId')
        NT['t'] = pd.to_datetime(NT.create_date, format='mixed'); NT = NT[NT.t.dt.strftime('%Y-%m-%d') == day]
        farm = NT.phone_type.fillna('未知').isin(fm_)
        out['reg'] = {'n': int(len(NT)), 'farm': int(farm.sum()), 'entered': int(NT.monetId.isin(today_ids).sum()),
                      'entered_ex_farm': int(NT[~farm].monetId.isin(today_ids).sum()),
                      'top_model': (lambda vc: [str(vc.index[0]), int(vc.iat[0])] if len(vc) else None)(NT.phone_type.fillna('未知').value_counts())}
    Ay = c.A_all[c.A_all.reg == c.end]
    out['reg_y'] = {'n': int((Ay.t <= y_cut).sum()), 'farm': int((Ay[Ay.t <= y_cut].phone_type.fillna('未知').isin(fm_)).sum()), 'n_full': int(len(Ay))}
    out['farm_models'] = sorted(fm_)
    # 601:角色表是实时的
    P = pd.DataFrame(c.raw.get('N601_players detail', []))
    if len(P):
        P = P[~P.monetId.isin(ex601)]
        cr = pd.to_datetime(P.created_at, format='mixed')
        P = P[cr >= pd.Timestamp(N601_START)]; cr = cr[cr >= pd.Timestamp(N601_START)]
        ll = pd.to_datetime(P.last_login_at, format='mixed').dt.strftime('%Y-%m-%d')
        out['n601_reg'] = int((cr.dt.strftime('%Y-%m-%d') == day).sum()); out['n601_login'] = int((ll == day).sum())
        # 601 对照表(2026-10-28):订单和建角色有精确时间,能比昨天同一时刻;登录只留最后一次(昨天的会被今天覆盖),
        # 每日任务只有日期,这两项只能和昨天全天比
        ids = set(P.monetId)
        O6 = pd.DataFrame(c.raw.get('N601_orders', []))
        if len(O6):
            O6['t'] = pd.to_datetime(O6.created_at, format='mixed'); O6 = O6[~O6.monetId.isin(ex601) & (O6.t >= pd.Timestamp(N601_START))]
        oy = O6[(O6.t >= c.end) & (O6.t < c.end + pd.Timedelta(days=1))] if len(O6) else O6
        TK = pd.DataFrame(c.raw.get('N601_activity tasks day', []))
        tk = (lambda d_: int(TK[(TK.day.astype(str).str[:10] == d_) & TK.monetId.isin(ids)].monetId.nunique()) if len(TK) else None)
        # 点击付费(2026-10-29):有精确时间,能比昨天同一时刻
        CK = pd.DataFrame(c.raw.get('N601_checkout', []))
        if len(CK):
            CK['t'] = pd.to_datetime(CK.created_ms.astype('int64'), unit='ms') + pd.Timedelta(hours=8)
            CK = CK[(CK.server_id == 601) & CK.monetId.isin(ids)]
        ck = (lambda x: {'users': int(x.monetId.nunique()), 'clicks': int(len(x)), 'order_users': int(x[x.has_order == 1].monetId.nunique())}) if len(CK) else (lambda x: None)
        cy = CK[(CK.t >= c.end) & (CK.t < c.end + pd.Timedelta(days=1))] if len(CK) else CK
        ct = CK[CK.t >= c.end + pd.Timedelta(days=1)] if len(CK) else CK
        out['n601_tbl'] = {
            'pay': [part(n6), part(oy[oy.t <= y_cut]) if len(oy) else part(oy), part(oy)],
            'click': [ck(ct), ck(cy[cy.t <= y_cut]) if len(CK) else None, ck(cy)],
            'reg': [out['n601_reg'], int(((cr >= c.end) & (cr <= y_cut)).sum()), int((cr.dt.strftime('%Y-%m-%d') == yday).sum())],
            'login': [out['n601_login'], None, None],
            'tasks': [tk(day), None, tk(yday)]}
    return out


# ---------------------------------------------------------------- 等级到顶(2026-10-28,《AI 看板数据需求》病 4)
# 老服主城(政府)等级:上限取登录日志里出现过的最高等级(现在是 26);全量计算,不随筛选变化
def level_cap(c, weeks=12):
    LS = c.LS
    cap = int(LS.max_level.max())
    E = c.end
    a30 = c.L[c.L.d > E - pd.Timedelta(days=30)].groupby('monetId').max_level.max()
    rv30 = c.O[c.O.d > E - pd.Timedelta(days=30)].groupby('monetId').price.sum()
    df = pd.DataFrame({'lv': a30}).join(rv30.rename('rev')).fillna({'rev': 0.0})
    g = df.groupby('lv').agg(n=('rev', 'size'), payers=('rev', lambda s_: int((s_ > 0).sum())), rev=('rev', 'sum'))
    dist = [{'lv': int(k), 'n': int(v.n), 'payers': int(v.payers), 'rev': r(v.rev, 2)} for k, v in g.iterrows()]
    tot_rev = float(rv30.sum())
    no_login_rev = float(rv30[~rv30.index.isin(a30.index)].sum())   # 付了费但窗口内没有登录记录的,不在分布里
    trend = []
    for i in range(weeks - 1, -1, -1):
        we = E - pd.Timedelta(days=7 * i); ws = we - pd.Timedelta(days=6)
        a = c.L[(c.L.d >= ws) & (c.L.d <= we)].groupby('monetId').max_level.max()
        o = c.O[(c.O.d >= ws) & (c.O.d <= we)].groupby('monetId').price.sum()
        at = set(a[a >= cap].index)
        trend.append({'from': ws.strftime('%Y-%m-%d'), 'to': we.strftime('%Y-%m-%d'), 'active': int(len(a)), 'at_cap': int(len(at)),
                      'share': r(len(at) / len(a)) if len(a) else None, 'rev': r(o.sum(), 2), 'rev_cap': r(o[o.index.isin(at)].sum(), 2),
                      'rev_share': r(o[o.index.isin(at)].sum() / o.sum()) if o.sum() else None,
                      'payers_cap': int(o.index.isin(at).sum())})
    capd = g.loc[cap] if cap in g.index else None
    return {'cap': cap, 'active30': int(len(a30)), 'dist': dist, 'rev30': r(tot_rev, 2), 'rev30_no_login': r(no_login_rev, 2),
            'at_cap': {'n': int(capd.n) if capd is not None else 0, 'payers': int(capd.payers) if capd is not None else 0,
                       'rev': r(capd.rev, 2) if capd is not None else 0.0,
                       'share': r(capd.n / len(a30)) if capd is not None and len(a30) else None,
                       'rev_share': r(capd.rev / tot_rev) if capd is not None and tot_rev else None},
            'trend': trend}


# ---------------------------------------------------------------- 商业化与大 R
def monetization(c):
    out = {}
    o90 = c.O[c.O.d > c.end - pd.Timedelta(days=90)]
    pu = o90.groupby('monetId').price.sum().sort_values(ascending=False)
    tiers = [('<$10', 0, 10), ('$10–100', 10, 100), ('$100–1k', 100, 1000), ('$1k–5k', 1000, 5000), ('>$5k', 5000, 1e12)]
    tot = pu.sum()
    out['tiers'] = [{'tier': t, 'users': int(((pu >= lo) & (pu < hi)).sum()), 'revenue': r(pu[(pu >= lo) & (pu < hi)].sum(), 2),
                     'share': r(pu[(pu >= lo) & (pu < hi)].sum() / tot) if tot else None} for t, lo, hi in tiers]
    conc = []
    for q in (0.01, 0.05, 0.10, 0.20):
        k = max(1, int(round(len(pu) * q)))
        conc.append({'top': f'{int(q*100)}%', 'users': k, 'share': r(pu.iloc[:k].sum() / tot) if tot else None})
    out['concentration'] = {'rows': conc, 'payers': int(len(pu)), 'revenue': r(tot, 2)}
    ch = {}
    for w in WINDOWS:
        o = c.O[c.O.d > c.end - pd.Timedelta(days=w)]
        g = o.groupby('channel').agg(rev=('price', 'sum'), payers=('monetId', 'nunique'))
        ch[str(w)] = [[k, r(v.rev, 2), int(v.payers)] for k, v in g.iterrows()]
    out['channels'] = ch
    # 钻石
    if len(c.dia):
        D = c.dia
        days = sorted(D.d.unique())
        piv = D.pivot_table(index='d', columns=['direction', 'diamond_type'], values='diamonds', aggfunc='sum', fill_value=0)
        rows = []
        for d in days:
            ins = piv.loc[d].get('in', pd.Series(dtype=float)); outs = piv.loc[d].get('out', pd.Series(dtype=float))
            gin, gout = float(ins.sum()), float(outs.sum())
            gamb_net = sum(float(outs.get(t, 0)) - float(ins.get(t, 0)) for t in GAMBLING)
            ext_in = sum(float(ins.get(t, 0)) for t in EXTERNAL); ext_out = sum(float(outs.get(t, 0)) for t in EXTERNAL)
            nin = gin - sum(float(ins.get(t, 0)) for t in GAMBLING) - ext_in
            nout = gout - sum(float(outs.get(t, 0)) for t in GAMBLING) - ext_out
            rows.append([pd.Timestamp(d).strftime('%Y-%m-%d'), round(gin), round(gout), round(nin), round(nout), round(gamb_net), round(ext_in), round(ext_out)])
        out['diamond_daily'] = {'columns': ['date', 'gross_in', 'gross_out', 'in_loop', 'out_loop', 'gamble_net_out', 'ext_in', 'ext_out'], 'rows': rows}
        # 钻石账三块(2026-10-29):游戏内循环 / 游戏内博彩 / 外部接入。外部接入没有扣钻记录时净额给 None(页面写「无法计算」)
        ledger = {}
        for w in (7, 30, 90):
            x = D[D.d > c.end - pd.Timedelta(days=w)]
            i = x[x.direction == 'in'].groupby('diamond_type').diamonds.sum(); o = x[x.direction == 'out'].groupby('diamond_type').diamonds.sum()
            skip = set(GAMBLING) | set(EXTERNAL)
            li = i[~i.index.isin(skip)]; lo = o[~o.index.isin(skip)]
            gi_, go_ = float(i.reindex(GAMBLING).fillna(0).sum()), float(o.reindex(GAMBLING).fillna(0).sum())
            ext = []
            for t, nm in EXTERNAL.items():
                ei, eo = float(i.get(t, 0)), float(o.get(t, 0))
                ext.append({'name': nm, 'in': round(ei), 'out': round(eo), 'net': round(ei - eo) if eo else None,
                            'users': int(x[(x.diamond_type == t) & (x.direction == 'in')].users.max() or 0) if ei else 0})
            ledger[str(w)] = {'loop': {'in': round(li.sum()), 'out': round(lo.sum()), 'net': round(li.sum() - lo.sum()),
                                       'topup': round(float(li.get('Topup', 0))), 'system': round(float(li.get('System', 0))),
                                       'in_top': [[k, round(v)] for k, v in li.sort_values(ascending=False).head(5).items()]},
                              'gamble': {'in': round(gi_), 'out': round(go_), 'net': round(gi_ - go_)},
                              'ext': ext}
        out['diamond_ledger'] = ledger
        cat = {'Shop': '商店', 'LimitShop': '限时商店', 'InvaderSweep': '入侵扫荡', 'CleanInvaderSweepCD': '入侵扫荡',
               'AllianceWarBuyFire': '联盟', 'ContributeAlliance': '联盟', 'AllianceDungeons': '联盟', 'AllianceWarRevive': '联盟',
               'AllianceWarQuiz': '联盟', 'ActivatedAllianceBuf': '联盟', 'CreateAlliance': '联盟', 'BuyNewAllianceIcon': '联盟',
               'FinishAllianceNextAllowJoinTime': '联盟', 'AttackAllianceMember': '联盟',
               'FinishUpgradeBuilding': '加速', 'FinishUpgradeSoldier': '加速', 'FinishProduceSoldier': '加速', 'FinishUpgradeSoul': '加速',
               'FinishUpgradePotential': '加速', 'FinishProduceSoul': '加速', 'FinishUpgradeEmploySoldier': '加速', 'FinishSoldierChangeJob': '加速',
               'BuyHeroMana': '英雄 / 装备', 'BuyHeroLife': '英雄 / 装备', 'Fuse': '英雄 / 装备', 'AddTrepanning': '英雄 / 装备',
               'Skill': '英雄 / 装备', 'LearnExtraMagic': '英雄 / 装备', 'BuyHeroMaxLife': '英雄 / 装备',
               'LuckyDrawNew': '抽奖', 'LuckyDrawOneTime': '抽奖', 'LuckyDrawTenTimes': '抽奖', 'LuckyDrawHundredTimes': '抽奖', 'LuckyDraw': '抽奖'}
        struct = {}
        for w in (7, 30, 90):
            x = D[D.d > c.end - pd.Timedelta(days=w)]
            o = x[x.direction == 'out'].groupby('diamond_type').diamonds.sum()
            i = x[x.direction == 'in'].groupby('diamond_type').diamonds.sum()
            agg = defaultdict(float)
            for t, v in o.items():
                if t == 'PetQuiz':
                    agg['宠物竞猜(净)'] += v - float(i.get(t, 0))
                elif t == 'SlotSpin':
                    agg['老虎机(净)'] += v - float(i.get(t, 0))
                else:
                    agg[cat.get(t, '其他')] += v
            gross_pq = float(o.get('PetQuiz', 0)); gross_ss = float(o.get('SlotSpin', 0))
            struct[str(w)] = {'rows': sorted([[k, round(v)] for k, v in agg.items()], key=lambda kv: -kv[1]),
                              'gross_petquiz': round(gross_pq), 'gross_slot': round(gross_ss),
                              'return_petquiz': r(float(i.get('PetQuiz', 0)) / gross_pq) if gross_pq else None,
                              'return_slot': r(float(i.get('SlotSpin', 0)) / gross_ss) if gross_ss else None}
        out['diamond_struct'] = struct
    # 老虎机拆分(2026-10-29):钻石下注的局 vs 用券的局(券局不花钻石,返出的钻石是净发)。窗口 7 / 28 天
    SS = pd.DataFrame(c.raw.get('Slot_spin daily', []))
    if len(SS):
        SS['d'] = pd.to_datetime(SS.dateCN)
        for k_ in ('spins', 'users', 'base_diamond', 'reward_diamond'):
            SS[k_] = SS[k_].astype(float)
        slot = {'first': SS.d.min().strftime('%Y-%m-%d'), 'complete': bool(SS.d.min() <= c.end - pd.Timedelta(days=27))}
        for w in (7, 28):
            x = SS[SS.d > c.end - pd.Timedelta(days=w)]
            dm, tk = x[x.kind == 'diamond'], x[x.kind == 'ticket']
            bet, ret = float(dm.base_diamond.sum()), float(dm.reward_diamond.sum())
            slot[str(w)] = {'bet': round(bet), 'ret': round(ret), 'rate': r(ret / bet) if bet else None, 'spins': int(dm.spins.sum()),
                            'ticket_spins': int(tk.spins.sum()), 'ticket_ret': round(float(tk.reward_diamond.sum()))}
        TI = pd.DataFrame(c.raw.get('Slot_ticket issued', []))
        if len(TI):
            TI['tickets'] = TI.tickets.astype(float)
            src = TI.groupby('typeEnum').tickets.sum().sort_values(ascending=False)
            # 2026-11-02:使用按 useItem 两种用途合计(宠物竞猜 + 老虎机);缺这张卡时退回只算老虎机券局
            TU = pd.DataFrame(c.raw.get('Slot_ticket used', []))
            if len(TU):
                TU['tickets'] = TU.tickets.astype(float)
                by_use = TU.groupby('use_for').tickets.sum().sort_values(ascending=False)
                used7 = round(float(by_use.sum())); used_by = [[k_, round(v)] for k_, v in by_use.items()]
            else:
                used7 = slot['7']['ticket_spins']; used_by = [['SlotSpin', used7]]
            iss7 = float(src.sum())
            slot['tickets7'] = {'issued': round(iss7), 'used': used7, 'used_by': used_by, 'by_source': [[k_, round(v)] for k_, v in src.head(5).items()],
                                'per_ticket': r(slot['28']['ticket_ret'] / slot['28']['ticket_spins'], 2) if slot['28']['ticket_spins'] else None}
        out['slot'] = slot
        # 券局返还(2026-11-02):宠物竞猜纯券轮次 + 老虎机券局,券局不花钻石,返还是净发。窗口 7 / 28 天(竞猜卡只取 28 天)
        PQ = pd.DataFrame(c.raw.get('PetQuiz_ticket reward', []))
        if len(PQ):
            PQ['d'] = pd.to_datetime(PQ.dateCN); PQ['reward_diamond'] = PQ.reward_diamond.astype(float)
            tr = {'complete': bool(PQ.d.min() <= c.end - pd.Timedelta(days=27))}
            for w in (7, 28):
                pq = round(float(PQ[PQ.d > c.end - pd.Timedelta(days=w)].reward_diamond.sum())); sp = slot[str(w)]['ticket_ret']
                tr[str(w)] = {'petquiz': pq, 'slot': sp, 'total': pq + sp}
            out['ticket_ret'] = tr
    out['whales'] = whales(c, pu)
    return out


def whales(c, pu90):
    W = pu90[pu90 >= 1000]
    E = c.end
    def cnt(df, col, ids, a, b):
        if not len(df):
            return pd.Series(0, index=ids)
        x = df[(df.d > E - pd.Timedelta(days=b)) & (df.d <= E - pd.Timedelta(days=a)) & df.monetId.isin(ids)]
        return x.groupby('monetId')[col].sum().reindex(ids, fill_value=0)
    ids = W.index
    L = c.L[c.L.monetId.isin(ids)]
    ld_now = L[L.d > E - pd.Timedelta(days=14)].groupby('monetId').d.nunique().reindex(ids, fill_value=0)
    ld_prev = L[(L.d > E - pd.Timedelta(days=28)) & (L.d <= E - pd.Timedelta(days=14))].groupby('monetId').d.nunique().reindex(ids, fill_value=0)
    last_login = L.groupby('monetId').d.max().reindex(ids)
    lvl = L.groupby('monetId').max_level.max().reindex(ids)
    O = c.O[c.O.monetId.isin(ids)]
    p30 = O[O.d > E - pd.Timedelta(days=30)].groupby('monetId').price.sum().reindex(ids, fill_value=0)
    pp30 = O[(O.d > E - pd.Timedelta(days=60)) & (O.d <= E - pd.Timedelta(days=30))].groupby('monetId').price.sum().reindex(ids, fill_value=0)
    last_pay = O.groupby('monetId').d.max().reindex(ids)
    def avg_gap(s):
        ds = sorted(set(s))
        return np.mean(np.diff(ds).astype('timedelta64[D]').astype(float)) if len(ds) >= 3 else np.nan
    gap = O.groupby('monetId').d.apply(avg_gap).reindex(ids)
    pvp_now = cnt(c.pvp, 'invade_count', ids, 0, 14); pvp_prev = cnt(c.pvp, 'invade_count', ids, 14, 28)
    al_now = cnt(c.ally, 'contrib_count', ids, 0, 14); al_prev = cnt(c.ally, 'contrib_count', ids, 14, 28)
    # 2026-10-21 业务要求加:服务器、是否在联盟、姓名(看改名 / 卖号)、最后登录时间(到秒)、登录次数
    # 主服 = 近 90 天付费最多的服;没有就取近 90 天登录天数最多的服
    o90 = O[O.d > E - pd.Timedelta(days=90)]
    main = o90.groupby(['monetId', 'server_id']).price.sum().reset_index().sort_values('price').groupby('monetId').server_id.last()
    LSw = c.LS[c.LS.monetId.isin(ids)]
    main_l = LSw.groupby(['monetId', 'server_id']).d.nunique().reset_index().sort_values('d').groupby('monetId').server_id.last()
    main = main.reindex(ids).fillna(main_l.reindex(ids))
    n_srv = LSw.groupby('monetId').server_id.nunique().reindex(ids, fill_value=0)
    lr_now = L[L.d > E - pd.Timedelta(days=14)].groupby('monetId').login_records.sum().reindex(ids, fill_value=0)
    lr_prev = L[(L.d > E - pd.Timedelta(days=28)) & (L.d <= E - pd.Timedelta(days=14))].groupby('monetId').login_records.sum().reindex(ids, fill_value=0)
    last_at = LSw.groupby('monetId').last_login_at.max().reindex(ids)
    nm = {(int(x.monetId), int(x.server_id)): x['name'] for _, x in c.names.iterrows()} if len(c.names) else {}
    def ally_of(m, sid):   # 主服上最近一天登录记录里的联盟 ID;> 0 = 在联盟
        x = LSw[(LSw.monetId == m) & (LSw.server_id == sid)]
        if not len(x): return None
        a = x.sort_values('d').alliance_id.iloc[-1]
        return bool(pd.notna(a) and a > 0)
    def rename_of(m, sid):  # 名字快照里该 (玩家, 主服) 出现过不止一个名字 → 最近一次改名
        h = c.name_hist.get(f'{m}@{sid}', [])
        return {'date': h[-1]['date'], 'from': h[-2]['name']} if len(h) >= 2 else None
    rows = []
    for m in ids:
        since_pay = (E - last_pay[m]).days if pd.notna(last_pay[m]) else None
        flags = []
        if ld_prev[m] >= 4 and ld_now[m] < ld_prev[m] / 2: flags.append('登录天数减半')
        if pp30[m] > 0 and p30[m] < pp30[m] * 0.3: flags.append('付费降 70% 以上')
        if since_pay is not None and pd.notna(gap[m]) and gap[m] > 0 and since_pay > 3 * gap[m]: flags.append('超过 3 倍付费间隔未付费')
        if pvp_prev[m] >= 4 and pvp_now[m] < pvp_prev[m] / 2: flags.append('入侵次数减半')
        if al_prev[m] >= 4 and al_now[m] < al_prev[m] / 2: flags.append('联盟捐献减半')
        if pd.isna(last_login[m]) or (E - last_login[m]).days >= 3: flags.append('最近 3 天未登录')
        score = len(flags)
        stopped = (pd.isna(last_login[m]) or (E - last_login[m]).days >= 7) or (pp30[m] >= 1000 and p30[m] == 0)
        rows.append({'id': int(m), 'rev90': r(W[m], 2), 'pay30': r(p30[m], 2), 'pay_prev30': r(pp30[m], 2),
                     'last_login': last_login[m].strftime('%Y-%m-%d') if pd.notna(last_login[m]) else None,
                     'last_pay': last_pay[m].strftime('%Y-%m-%d') if pd.notna(last_pay[m]) else None,
                     'gap': r(gap[m], 1) if pd.notna(gap[m]) else None, 'since_pay': since_pay,
                     'login14': int(ld_now[m]), 'login_prev14': int(ld_prev[m]),
                     'pvp14': int(pvp_now[m]), 'pvp_prev14': int(pvp_prev[m]),
                     'ally14': int(al_now[m]), 'ally_prev14': int(al_prev[m]),
                     'level': int(lvl[m]) if pd.notna(lvl[m]) else None,
                     'server': int(main[m]) if pd.notna(main[m]) else None, 'n_servers': int(n_srv[m]),
                     'name': nm.get((int(m), int(main[m]))) if pd.notna(main[m]) else None,
                     'renamed': rename_of(int(m), int(main[m])) if pd.notna(main[m]) else None,
                     'in_alliance': ally_of(m, main[m]) if pd.notna(main[m]) else None,
                     'last_login_at': str(last_at[m])[:19] if pd.notna(last_at[m]) else None,
                     'logins14': int(lr_now[m]), 'logins_prev14': int(lr_prev[m]),
                     'score': score, 'flags': flags, 'stopped': bool(stopped),
                     'status': 'red' if stopped else ('yellow' if score >= 2 else 'green')})
    rows.sort(key=lambda x: ({'red': 0, 'yellow': 1, 'green': 2}[x['status']], -x['score'], -x['rev90']))
    return rows



# ---------------------------------------------------------------- 玩法健康矩阵(2026-10-21 第二版)
FEATURES = [  # (key, 名称, 来源)
    ('building', '建筑升级', 'UpgradeBuildingLevel'), ('soldier_up', '士兵升级', 'upgradeSoldierLevel'),
    ('hero_up', '英雄升级', 'UpgradeHeroLevel'), ('soul_fuse', '战魂合成', 'WarriorSoulFuse'), ('pet', '宠物喂养', 'PetFeed'),
    ('dungeon1', '副本 1', 'EndDungeon'), ('dungeon2', '副本 2', 'EndDungeon2'), ('world_boss', '世界 BOSS', 'AttackWorldMonster'),
    ('invade', '入侵', 'CheckInvadeBattle'), ('invaded', '城被攻打', 'EndInvadeBattle.ownerId'), ('arena', '竞技场', 'HeroArenaService_endBattle'),
    ('hero_glory', '英雄荣耀', 'HeroGlory_EndBattle'), ('moba', 'MOBA', 'MobaBattleFinished'),
    ('alliance_contrib', '联盟捐献', 'allianceContribution'), ('alliance_skill', '联盟技能', 'activatedAllianceSkill'),
    ('alliance_dungeon', '联盟副本', 'EndAllianceDungeons'), ('king_event', '最强王者(活动)', 'StrongestKingActivity_getParticipationReward'),
    ('alliance_event', '最强联盟(活动)', 'StrongestAllianceActivity_getParticipationReward'), ('shop', '商店购买', 'buyItemFromShop'),
    ('pet_quiz', '宠物竞猜', 'ConsumeDiamond PetQuiz'), ('slot', '老虎机', 'ConsumeDiamond SlotSpin'), ('lucky_draw', '抽奖', 'LuckyDrawNew'),
    ('checkin', '签到', 'CheckIn'), ('daily_task', '每日任务', 'GetDailyTaskReward'),
]


def feature_days(c):
    """所有玩法统一成 (feature, monetId, d) 的玩家 × 天 参与表"""
    parts = [c.G[['feature', 'monetId', 'd']]] if len(c.G) else []
    for key, df in (('dungeon1', c.pve), ('alliance_contrib', c.ally), ('invade', c.pvp)):
        if len(df):
            x = df[['monetId', 'd']].copy(); x['feature'] = key; parts.append(x)
    if len(c.PB):
        x = c.PB[c.PB.role == 'owner'][['monetId', 'd']].copy(); x['feature'] = 'invaded'; parts.append(x)
    return pd.concat(parts, ignore_index=True)


def gameplay(c):
    F = feature_days(c)
    start60 = c.end - pd.Timedelta(days=59)
    first = F.groupby('feature').d.min()
    early = window_users(c, 15, c.end - pd.Timedelta(days=15))
    late = set(c.L[c.L.d > c.end - pd.Timedelta(days=15)].monetId)
    early['kept'] = early.index.isin(late)
    e_lo, e_hi = c.end - pd.Timedelta(days=29), c.end - pd.Timedelta(days=15)
    out = {}
    for w in (7, 14, 30, 60):
        u = window_users(c, w)
        rev = c.O[c.O.d > c.end - pd.Timedelta(days=w)].groupby('monetId').price.sum()
        fw = F[F.d > c.end - pd.Timedelta(days=w)]
        for plat in PLATS:
            uu = u if plat == 'all' else u[u.plat == plat]
            ee = early if plat == 'all' else early[early.plat == plat]
            tot_rev = rev.reindex(uu.index).fillna(0).sum()
            rows = []
            for key, name, src in FEATURES:
                x = fw[(fw.feature == key) & fw.monetId.isin(uu.index)]
                part = x.monetId.unique()
                n = len(part)
                days = x.groupby('monetId').d.nunique().mean() if n else None
                pe = set(F[(F.feature == key) & (F.d >= e_lo) & (F.d <= e_hi)].monetId)
                be = ee.assign(p=ee.index.isin(pe))
                diffs, wts = [], []
                for b, gg in be.groupby('band'):
                    a_, c_ = gg[gg.p], gg[~gg.p]
                    if len(a_) >= 10 and len(c_) >= 10:
                        diffs.append(a_.kept.mean() - c_.kept.mean()); wts.append(len(gg))
                lift = float(np.average(diffs, weights=wts)) if diffs else None
                cov = rev.reindex(part).fillna(0).sum() / tot_rev if tot_rev else None
                complete = bool(first.get(key, c.end) <= c.end - pd.Timedelta(days=w - 1)) if key in first else False
                rows.append({'key': key, 'name': name, 'source': src, 'users': int(n), 'rate': r(n / len(uu)) if len(uu) else None,
                             'avg_days': r(days, 1), 'lift': r(lift), 'kept_part': r(be[be.p].kept.mean()) if be.p.any() else None,
                             'kept_non': r(be[~be.p].kept.mean()) if (~be.p).any() else None, 'rev_cov': r(cov), 'complete': complete})
            rates = [x['rate'] for x in rows if x['rate'] is not None]; lifts = [x['lift'] for x in rows if x['lift'] is not None]
            out[f'{w}|{plat}'] = {'rows': rows, 'active': int(len(uu)),
                                  'rate_cut': r(float(np.median(rates))) if rates else None, 'lift_cut': r(float(np.median(lifts))) if lifts else None}
    out['retention_windows'] = [e_lo.strftime('%Y-%m-%d'), e_hi.strftime('%Y-%m-%d'), (c.end - pd.Timedelta(days=14)).strftime('%Y-%m-%d'), c.end.strftime('%Y-%m-%d')]
    return out


# ---------------------------------------------------------------- PvP
def pvp(c):
    PB = c.PB
    out = {}
    login_days = c.L.groupby('monetId').d.apply(lambda s: np.sort(s.values.astype('datetime64[D]')))
    for w in (7, 14, 30, 60):
        u = window_users(c, w)
        x = PB[PB.d > c.end - pd.Timedelta(days=w)]
        for plat in PLATS:
            for seg in c.segs:
                uu = filt(u, plat, seg)
                ids = uu.index
                a = x[(x.role == 'attack') & x.monetId.isin(ids)]
                o = x[(x.role == 'owner') & x.monetId.isin(ids)]
                rs = x[(x.role == 'resist') & x.monetId.isin(ids)]
                rv = x[(x.role == 'revenge') & x.monetId.isin(ids)]
                lost_users = o[o.wins > 0].monetId.unique()
                ini = c.pvp[(c.pvp.d > c.end - pd.Timedelta(days=w)) & c.pvp.monetId.isin(ids)] if len(c.pvp) else c.pvp
                out[f'{w}|{plat}|{seg}'] = {
                    'active': int(len(ids)), 'initiators': int(ini.monetId.nunique()) if len(ini) else 0, 'initiated': int(ini.invade_count.sum()) if len(ini) else 0,
                    'attackers': int(a.monetId.nunique()), 'attacks': int(a.n.sum()), 'wins': int(a.wins.sum()),
                    'owners': int(o.monetId.nunique()), 'attacked': int(o.n.sum()), 'lost': int(o.wins.sum()), 'lost_users': int(len(lost_users)),
                    'resisters': int(rs.monetId.nunique()), 'resists': int(rs.n.sum()), 'resist_wins': int(rs.wins.sum()),
                    'revengers': int(rv.monetId.nunique()), 'revenges': int(rv.n.sum()),
                    'revenge_of_lost': int(len(set(rv.monetId) & set(lost_users)))}
    # 每日:进攻人数 / 次数 / 胜场;活跃城主被打下的人数
    days = pd.date_range(c.end - pd.Timedelta(days=59), c.end)
    act_day = set(zip(c.L.monetId, c.L.d))
    a = PB[PB.role == 'attack'].groupby('d').agg(attackers=('monetId', 'nunique'), attacks=('n', 'sum'), wins=('wins', 'sum'))
    o = PB[(PB.role == 'owner') & (PB.wins > 0)]
    o = o[[(m, d) in act_day for m, d in zip(o.monetId, o.d)]]
    ol = o.groupby('d').monetId.nunique()
    out['daily'] = [[d.strftime('%Y-%m-%d'), int(a.attackers.get(d, 0)), int(a.attacks.get(d, 0)), int(a.wins.get(d, 0)), int(ol.get(d, 0))] for d in days]
    # PvP 获得的资源(全量,按天)
    if len(c.loot):
        lt = c.loot.groupby(['dateCN', 'source']).amount.sum().unstack(fill_value=0)
        out['loot'] = {'columns': list(lt.columns), 'rows': [[d] + [float(v) for v in row] for d, row in lt.iterrows()]}
    # 被打下城之后:当天有登录的活跃城主,之后 1 / 7 / 14 天是否还登录;对照 = 同等级段、同等前期活跃度、当天及前 7 天没被打下的活跃日
    lost_set = set(zip(o.monetId, o.d))
    lostd = o.groupby('monetId').d.apply(lambda s: np.sort(s.values.astype('datetime64[D]')))
    lo, hi = c.end - pd.Timedelta(days=59) + pd.Timedelta(days=7), c.end - pd.Timedelta(days=14)
    base = c.L[(c.L.d >= lo) & (c.L.d <= hi)][['monetId', 'd', 'band']].copy()
    base['treat'] = [(m, d) in lost_set for m, d in zip(base.monetId, base.d)]
    def cnt(arr, d0, a_, b_):
        if arr is None or (isinstance(arr, float)):
            return 0
        d0 = np.datetime64(d0, 'D')
        return int(((arr >= d0 + np.timedelta64(a_, 'D')) & (arr <= d0 + np.timedelta64(b_, 'D'))).sum())
    recs = []
    for m, d, b, t in base.itertuples(index=False):
        ld = login_days.get(m)
        if not t and cnt(lostd.get(m), d, -7, 0) > 0:
            continue
        pre = cnt(ld, d, -7, -1) / 7
        recs.append((b, t, 'low' if pre <= 0.3 else ('mid' if pre <= 0.7 else 'high'), cnt(ld, d, 1, 1) > 0,
                     cnt(ld, d, 1, 7) / 7, cnt(ld, d, 8, 14) / 7, cnt(ld, d, 1, 14) == 0))
    E = pd.DataFrame(recs, columns=['band', 'treat', 'pre', 'next1', 'post7', 'post14', 'gone'])
    rows = []
    for (b, pre, t), g in E.groupby(['band', 'pre', 'treat']):
        rows.append({'band': b, 'pre': pre, 'treat': bool(t), 'n': int(len(g)), 'next1': r(g.next1.mean()), 'post7': r(g.post7.mean()),
                     'post14': r(g.post14.mean()), 'gone': r(g.gone.mean())})
    out['after_loss'] = {'rows': rows, 'window': [lo.strftime('%Y-%m-%d'), hi.strftime('%Y-%m-%d')]}
    return out


# ---------------------------------------------------------------- 联盟
def alliance(c):
    F = feature_days(c)
    out = {}
    for w in (7, 14, 30, 60):
        u = window_users(c, w)
        fw = F[F.d > c.end - pd.Timedelta(days=w)]
        rev = c.O[c.O.d > c.end - pd.Timedelta(days=w)].groupby('monetId').price.sum()
        sets = {k: set(fw[fw.feature == k].monetId) for k in ('alliance_apply', 'alliance_join', 'alliance_leave', 'alliance_create', 'alliance_contrib', 'alliance_skill', 'alliance_dungeon', 'alliance_event')}
        for plat in PLATS:
            for seg in c.segs:
                uu = filt(u, plat, seg); ids = set(uu.index)
                inn = set(uu[uu.aid > 0].index)
                step = [('活跃玩家', ids), ('在联盟', inn), ('联盟捐献', inn & sets['alliance_contrib']), ('联盟技能', inn & sets['alliance_contrib'] & sets['alliance_skill']),
                        ('联盟副本或联盟活动', inn & sets['alliance_contrib'] & sets['alliance_skill'] & (sets['alliance_dungeon'] | sets['alliance_event']))]
                g_in, g_out = uu[uu.aid > 0], uu[uu.aid <= 0]
                pr = lambda g: r((rev.reindex(g.index).fillna(0) > 0).mean()) if len(g) else None
                out[f'{w}|{plat}|{seg}'] = {
                    'active': len(ids), 'in_alliance': len(inn), 'applied': len(ids & sets['alliance_apply']), 'joined': len(ids & sets['alliance_join']),
                    'left': len(ids & sets['alliance_leave']), 'created': len(ids & sets['alliance_create']),
                    'funnel': [[n_, len(s_)] for n_, s_ in step],
                    'cmp': {'in': {'n': len(g_in), 'days': r(g_in.days.mean(), 1), 'pay': pr(g_in)}, 'out': {'n': len(g_out), 'days': r(g_out.days.mean(), 1), 'pay': pr(g_out)}}}
    # 新用户入盟时点 vs D30(注册满 30 天、当天进入游戏的人)
    A = getattr(c, 'A_enriched', None)
    if A is not None:
        lj = c.L[c.L.alliance_id > 0].merge(A[['monetId', 'reg']], on='monetId')
        lj['age'] = (lj.d - lj.reg).dt.days
        first_join = lj[lj.age >= 0].groupby('monetId').age.min()
        base = A[(A.reg <= c.end - pd.Timedelta(days=30)) & A.entered].copy()
        base['join_age'] = base.monetId.map(first_join)
        la = c.L.merge(base[['monetId', 'reg']], on='monetId'); la['age'] = (la.d - la.reg).dt.days
        d30days = la[la.age.between(0, 30)].groupby('monetId').d.nunique()
        base['days30'] = base.monetId.map(d30days).fillna(0)
        def bucket(x):
            if pd.isna(x) or x > 14: return '14 天内未入盟'
            if x == 0: return 'D0'
            if x == 1: return 'D1'
            if x <= 3: return 'D2–3'
            if x <= 7: return 'D4–7'
            return 'D8–14'
        base['b'] = base['join_age'].map(bucket)
        order = ['D0', 'D1', 'D2–3', 'D4–7', 'D8–14', '14 天内未入盟']
        res = {}
        for plat in PLATS:
            bb = base if plat == 'all' else base[base.plat == plat]
            res[plat] = [{'bucket': k, 'n': int((bb.b == k).sum()), 'd7': r(bb[bb.b == k].d7.mean()) if (bb.b == k).any() else None,
                          'd30': r(bb[bb.b == k].d30.mean()) if (bb.b == k).any() else None, 'days30': r(bb[bb.b == k].days30.mean(), 1) if (bb.b == k).any() else None,
                          'pay30': r(bb[bb.b == k].pay30.mean()) if (bb.b == k).any() else None} for k in order]
            ok3 = bb[bb.reg <= c.end - pd.Timedelta(days=3)]; ok7 = bb[bb.reg <= c.end - pd.Timedelta(days=7)]
            res[plat + '_rates'] = {'d3': r((ok3['join_age'] <= 3).mean()) if len(ok3) else None, 'd7': r((ok7['join_age'] <= 7).mean()) if len(ok7) else None, 'n': int(len(bb))}
        out['join_timing'] = res
        out['join_timing_window'] = [base.reg.min().strftime('%Y-%m-%d'), base.reg.max().strftime('%Y-%m-%d')] if len(base) else None
    # 在盟 vs 不在盟:同等级段的 15 天留存(前 15 天活跃者在后 15 天是否还在),相关性
    early = window_users(c, 15, c.end - pd.Timedelta(days=15))
    late = set(c.L[c.L.d > c.end - pd.Timedelta(days=15)].monetId)
    early['kept'] = early.index.isin(late); early['ally'] = early.aid > 0
    ret = {}
    for plat in PLATS:
        e = early if plat == 'all' else early[early.plat == plat]
        ret[plat] = [{'band': b, 'in_n': int(((e.band == b) & e.ally).sum()), 'in_kept': r(e[(e.band == b) & e.ally].kept.mean()) if ((e.band == b) & e.ally).any() else None,
                      'out_n': int(((e.band == b) & ~e.ally).sum()), 'out_kept': r(e[(e.band == b) & ~e.ally].kept.mean()) if ((e.band == b) & ~e.ally).any() else None}
                     for b in BAND_NAMES]
    out['retention_by_band'] = ret
    days = pd.date_range(c.end - pd.Timedelta(days=59), c.end)
    ev = F[F.feature.isin(['alliance_apply', 'alliance_join', 'alliance_leave', 'alliance_create'])].groupby(['d', 'feature']).monetId.nunique().unstack(fill_value=0)
    out['daily'] = [[d.strftime('%Y-%m-%d')] + [int(ev[k].get(d, 0)) if k in ev else 0 for k in ('alliance_apply', 'alliance_join', 'alliance_leave', 'alliance_create')] for d in days]
    return out


# ---------------------------------------------------------------- 国家 / 版本
def geo(c, DATA):
    A = c.A_enriched
    A = A.assign(country=A.monetId.map(c.country).fillna('未知'))
    out = {'countries': c.countries, 'versions': c.versions}
    for w in WINDOWS:
        u = window_users(c, w)
        o = c.O[c.O.d > c.end - pd.Timedelta(days=w)].groupby('monetId').price.sum()
        rows = []
        for ct in c.countries:
            uu = u[u.country == ct]
            regs = A[(A.country == ct) & (A.reg > c.end - pd.Timedelta(days=w))]
            # 新用户留存按固定 cohort:近 150 天注册、已满 N 天(只按窗口取样本太小,大多数国家 D7 不足 30 人)
            mat = lambda n: A[(A.country == ct) & (A.reg <= c.end - pd.Timedelta(days=n))]
            m1, m7, m30 = mat(1), mat(7), mat(30)
            rv = o.reindex(uu.index).fillna(0); payers = int((rv > 0).sum())
            ltv_c = m30
            ltv = None
            if len(ltv_c):
                oo = c.O.merge(ltv_c[['monetId', 'reg']], on='monetId'); oo = oo[(oo.d >= oo.reg) & (oo.d <= oo.reg + pd.Timedelta(days=30))]
                ltv = oo.price.sum() / len(ltv_c)
            dau = DATA['daily']['series'].get(f'all|c:{ct}', [])
            avg_dau = float(np.mean([x[1] for x in dau[-w:]])) if dau else None
            # 国家只在登录时记录,有国家记录的新用户基本都进过游戏:这里的留存分母 = 有国家记录的新用户,不能和注册口径比,也不给进入率
            rows.append({'country': ct, 'active': int(len(uu)), 'avg_dau': r(avg_dau, 1), 'new_users': int(len(regs)),
                         'd1': r(m1.d1.mean()) if len(m1) else None, 'd7': r(m7.d7.mean()) if len(m7) else None, 'd30': r(m30.d30.mean()) if len(m30) else None,
                         'n_d7': int(len(m7)), 'n_d30': int(len(m30)),
                         'payers': payers, 'pay_rate': r(payers / len(uu)) if len(uu) else None, 'revenue': r(rv.sum(), 2),
                         'arpu': r(rv.sum() / len(uu), 2) if len(uu) else None, 'arppu': r(rv.sum() / payers, 1) if payers else None, 'ltv30': r(ltv, 3)})
        out[f'country|{w}'] = rows
        vrows = []
        for v in c.versions + ['其他']:
            uu = u[u.ver == v] if v != '其他' else u[~u.ver.isin(c.versions)]
            rv = o.reindex(uu.index).fillna(0); payers = int((rv > 0).sum())
            vrows.append({'version': v, 'active': int(len(uu)), 'share': r(len(uu) / len(u)) if len(u) else None, 'payers': payers,
                          'pay_rate': r(payers / len(uu)) if len(uu) else None, 'revenue': r(rv.sum(), 2),
                          'avg_days': r(uu.days.mean(), 1) if len(uu) else None, 'lvl': r(uu.lvl.median(), 1) if len(uu) else None})
        out[f'version|{w}'] = vrows
    # 版本占比的时间线(按天,活跃账号当天的版本)
    days = pd.date_range(c.end - pd.Timedelta(days=119), c.end)
    vv = c.L[c.L.d >= days[0]].copy(); vv['vg'] = vv.ver.where(vv.ver.isin(c.versions[:4]), '其他')
    t = vv.groupby(['d', 'vg']).monetId.nunique().unstack(fill_value=0).reindex(days, fill_value=0)
    out['version_daily'] = {'columns': list(t.columns), 'rows': [[d.strftime('%Y-%m-%d')] + [int(x) for x in row] for d, row in t.iterrows()]}
    wu = window_users(c, 30)
    O30 = c.O[c.O.d > c.end - pd.Timedelta(days=30)].groupby('monetId').price.sum()
    out['coverage'] = {'active_with_country': int((wu.country != '未知').sum()), 'active': int(len(wu)),
                       'from_server': int(wu.index.map(c.country_src).isin(['区服记录']).sum()) if hasattr(c, 'country_src') else 0,
                       'rev_unknown_share': r(float(O30[~O30.index.isin(c.country.index)].sum()) / float(O30.sum())) if O30.sum() else None}
    return out


# ---------------------------------------------------------------- 按服务器(2026-10-21)
SERVER_MIN_ACTIVE = 100   # 近 30 天活跃不足的服不单独列


def server_view(c, srv):
    """某个服的视图:活跃 / 等级按该服角色算,收入按订单所在服,新用户按注册后第一个登录的服。
    同一账号在多个服时,各服人数相加大于全服总数。PvP / 联盟 / 副本等行为表没有服字段,按「在该服活跃的玩家」近似。"""
    import copy
    v = copy.copy(c)
    LS = c.LS[c.LS.server_id == srv].copy()
    L = LS.groupby(['monetId', 'd'], as_index=False).agg(
        login_records=('login_records', 'sum'), max_level=('max_level', 'max'), alliance_id=('alliance_id', 'max'),
        plat=('plat', 'last'), client_version=('client_version', 'last'), server_id=('server_id', 'last'))
    L['dateCN'] = L.d.dt.strftime('%Y-%m-%d'); L['band'] = L.max_level.map(band_of)
    L['country'] = L.monetId.map(c.country).fillna('未知'); L['ver'] = L.client_version.fillna('未知')
    v.L = L
    v.user_last = L.sort_values('d').groupby('monetId').last()[['plat', 'band', 'country', 'ver']]
    v.O = c.O[c.O.server_id == srv]
    # 新用户:注册后第一个登录的服(同一天多个服取等级最高的角色)
    first = c.LS.sort_values(['monetId', 'd', 'max_level']).groupby('monetId').agg(fd=('d', 'first'))
    fs = c.LS.merge(first, left_on='monetId', right_index=True)
    fs = fs[fs.d == fs.fd].sort_values('max_level').groupby('monetId').server_id.last()
    v.A = c.A[c.A.monetId.map(fs) == srv]
    ids = set(L.monetId)
    v.pvp = c.pvp[c.pvp.monetId.isin(ids)] if len(c.pvp) else c.pvp
    v.ally = c.ally[c.ally.monetId.isin(ids)] if len(c.ally) else c.ally
    v.pve = c.pve[c.pve.monetId.isin(ids)] if len(c.pve) else c.pve
    v.PB = c.PB[c.PB.monetId.isin(ids)] if len(c.PB) else c.PB
    v.G = c.G[c.G.monetId.isin(ids)] if len(c.G) else c.G
    v.segs = ['all'] + BAND_NAMES      # 服务器可以和等级段组合,不和国家 / 版本组合
    return v


def by_server(c, errors):
    recent = c.LS[c.LS.d > c.end - pd.Timedelta(days=30)]
    act = recent.groupby('server_id').monetId.nunique().sort_values(ascending=False)
    servers = [int(sv) for sv, n in act.items() if n >= SERVER_MIN_ACTIVE]
    out = {}
    for sv in servers:
        v = server_view(c, sv)
        D = {}
        D['daily'] = safe(lambda: daily_series(v), errors, f'srv{sv}.daily')
        D['kpi'] = safe(lambda: window_kpis(v), errors, f'srv{sv}.kpi') or {}
        D['new_user'] = safe(lambda: new_user(v), errors, f'srv{sv}.new_user')
        D['life'] = safe(lambda: lifecycle(v), errors, f'srv{sv}.life')
        D['pvp'] = safe(lambda: pvp(v), errors, f'srv{sv}.pvp')
        D['alliance'] = safe(lambda: alliance(v), errors, f'srv{sv}.alliance')
        D['active30'] = int(act.get(sv, 0))
        out[str(sv)] = D
    return out

# ---------------------------------------------------------------- 告警 / 健康度 / Top 问题
def alerts_and_health(c, DATA):
    """2026-10-21 收紧(用户要求:避免频繁标红引起过度反应,但不隐藏真问题):
    - 只对「持续性」变化报警(近 7 / 14 / 28 天对比更早的基准);单日波动只作「提示」,只在异常中心明细里出现
    - 红色只留给「连续两周都明显下降」的收入 / 活跃,以及大 R 实际停止登录或停止付费;其余最多黄色
    - 注册上升、单日收入起伏、ARPPU 变化都只是提示"""
    E = c.end
    al = []
    s = pd.DataFrame(DATA['daily']['series']['all|all'], columns=DATA['daily']['columns'])
    nd = {p: pd.DataFrame(v, columns=DATA['new_user']['daily']['columns']) for p, v in DATA['new_user']['daily']['series'].items()}
    def add(cat, dim, metric, cur, base, dev, level, page, note='', win=None, persistent=True):
        al.append({'category': cat, 'dim': dim, 'metric': metric, 'current': cur, 'baseline': base, 'deviation': r(dev),
                   'level': level, 'page': page, 'note': note, 'date': E.strftime('%Y-%m-%d'), 'win': win, 'persistent': persistent})
    def wk(series, k):          # 倒数第 k 周(k=0 是最近 7 天)的合计
        n = len(series); return series.iloc[n - 7 * (k + 1): n - 7 * k].sum()
    def wk_dev(series, k):      # 第 k 周 vs 它之前 4 周的周均值
        base = np.mean([wk(series, k + j) for j in (1, 2, 3, 4)])
        return (wk(series, k) - base) / base if base else None, wk(series, k), base
    # 活跃:近 7 天 DAU 均值 vs 前 4 周;降 > 10% 黄,连续两周降 > 20% 红
    d0, now, base = wk_dev(s.dau, 0); d1, _, _ = wk_dev(s.dau, 1)
    if d0 is not None and d0 < -0.10:
        lvl = 'red' if (d0 < -0.20 and d1 is not None and d1 < -0.20) else 'yellow'
        add('用户', 'eng', 'DAU(近 7 天均值)', r(now / 7, 1), r(base / 7, 1), d0, lvl, 'home', '对比前 4 周的周均值', 7)
    # 防护①:单日断崖(如宕机)。昨天 DAU 低于前 4 周同星期中位数的一半 → 观察中
    sd = [s.dau.iloc[-1 - 7 * k] for k in (1, 2, 3, 4) if len(s) > 7 * k]
    if sd and s.dau.iloc[-1] < 0.5 * float(np.median(sd)):
        add('用户', 'eng', 'DAU 单日断崖', int(s.dau.iloc[-1]), r(float(np.median(sd)), 1), (s.dau.iloc[-1] - np.median(sd)) / np.median(sd),
            'yellow', 'home', '昨天的 DAU 不到前 4 周同星期的一半,可能是宕机或数据缺失,请先确认数据', 1)
    # 防护②:单一机型注册集中。近 7 天任一天,单一机型占当天注册 ≥ 30% 且当天注册 ≥ 20 → 提示
    if hasattr(c, 'A') and 'phone_type' in c.A:
        a7 = c.A[c.A.reg > E - pd.Timedelta(days=7)]
        hits = []
        for d_, g_ in a7.groupby('reg'):
            if len(g_) >= 20:
                vc = g_.phone_type.value_counts()
                if vc.iat[0] / len(g_) >= 0.30:
                    hits.append((d_.strftime('%m-%d'), vc.index[0], int(vc.iat[0]), len(g_)))
        if hits:
            models = sorted(set(h[1] for h in hits))
            add('平台', 'acq', f'单一机型注册集中:{"、".join(models)}', len(hits), None, None, 'info', 'newuser',
                '近 7 天有 ' + str(len(hits)) + ' 天,单一机型占当天注册 30% 以上(' + ';'.join(f'{h[0]} {h[1]} {h[2]}/{h[3]}' for h in hits[:4]) + ')。可能是模拟器、测试设备或某个渠道,需确认来源', 7, persistent=False)
    # 新注册:下降 > 50% 黄;上升只提示
    reg = nd['all'].registrations
    d0, now, base = wk_dev(reg, 0)
    if d0 is not None and d0 < -0.50:
        add('用户', 'acq', '新注册(近 7 天)', now, r(base, 1), d0, 'yellow', 'newuser', '对比前 4 周的周均值', 7)
    elif d0 is not None and d0 > 0.50:
        add('用户', 'acq', '新注册(近 7 天)', now, r(base, 1), d0, 'info', 'newuser', '注册上升:可能是买量,也可能是刷量或测试设备(见新用户页「进入率下钻」)', 7, persistent=False)
    # 进入游戏率、当天到 Lv3:分平台,持续 14 天以上下降 > 20% 才报,最多黄;28 天持续下滑写「排查中」
    for plat in ('Android', 'iOS'):
        d = nd[plat]
        for metric, num, den, minn in (('注册 → 进入游戏率', 'entered', 'registrations', 30), ('当天到 Lv3 转化', 'lv3', 'entered', 40)):
            done = False
            for win, prev in ((28, 28), (14, 28)):
                cur = d.iloc[-win:]; pr = d.iloc[-(win + prev):-win]
                if cur[den].sum() < minn or pr[den].sum() == 0:
                    continue
                a_, b_ = cur[num].sum() / cur[den].sum(), pr[num].sum() / pr[den].sum()
                dev = (a_ - b_) / b_ if b_ else None
                if dev is not None and dev < -0.20 and not done:
                    note = f'近 {win} 天 vs 再往前 {prev} 天;近 {win} 天{"注册" if den == "registrations" else "进入游戏"} {int(cur[den].sum())} 人'
                    if num == 'entered':
                        Aw = c.A[(c.A.plat == plat) & (c.A.reg > E - pd.Timedelta(days=win))]
                        Aw = Aw.assign(ent=Aw.monetId.map(dict(zip(c.A_enriched.monetId, c.A_enriched.entered))).fillna(False)) if hasattr(c, 'A_enriched') else Aw
                        if len(Aw) and 'ent' in Aw:
                            top = Aw.phone_type.value_counts()
                            if len(top) and top.iat[0] / len(Aw) >= 0.10:
                                rest = Aw[Aw.phone_type != top.index[0]]
                                note += f';其中机型 {top.index[0]} 注册 {int(top.iat[0])} 个、进入 {int(Aw[Aw.phone_type == top.index[0]].ent.sum())} 个,去掉它后进入率为 {rest.ent.mean():.0%}'
                        note += ';排查中'
                    add('平台', 'funnel', f'{plat} {metric}', r(a_), r(b_), dev, 'yellow', 'newuser', note, win)
                    done = True
    # D1:最近 7 个满期注册日 vs 之前 28 天,降 > 30% 黄
    a = nd['all']
    d1n = a.iloc[-8:-1]; d1p = a.iloc[-36:-8]
    if d1n.registrations.sum() >= 30 and d1p.registrations.sum():
        now, base = d1n.d1.sum() / d1n.registrations.sum(), d1p.d1.sum() / d1p.registrations.sum()
        dev = (now - base) / base if base else None
        if dev is not None and dev < -0.30:
            add('用户', 'ret', 'D1 留存(注册口径)', r(now), r(base), dev, 'yellow', 'newuser', '最近 7 个满期注册日', 7)
    # 收入:近 7 天 vs 前 4 周周均值,降 > 30% 黄,连续两周 > 30% 红;单日只提示
    d0, now, base = wk_dev(s.revenue, 0); d1, _, _ = wk_dev(s.revenue, 1)
    if d0 is not None and d0 < -0.30:
        lvl = 'red' if (d1 is not None and d1 < -0.30) else 'yellow'
        add('商业化', 'mon', '收入(近 7 天)', r(now, 2), r(base, 2), d0, lvl, 'money', '对比前 4 周的周均值;收入受大 R 影响很大', 7)
    rev28 = s.revenue.iloc[-29:-1]; cur = float(s.revenue.iloc[-1]); med = float(rev28.median())
    dv = (cur - med) / med if med else None
    if dv is not None and abs(dv) > 0.30:
        add('商业化', 'mon', '日收入(单日)', cur, med, dv, 'info', 'money', '单日波动主要由个别大 R 充值决定,不算异常', 1, persistent=False)
    # 付费人次:降 > 30% 黄
    d0, now, base = wk_dev(s.payers, 0)
    if d0 is not None and d0 < -0.30:
        add('商业化', 'mon', '付费人次(近 7 天)', now, r(base, 1), d0, 'yellow', 'money', '按天去重后相加', 7)
    # ARPPU:只提示
    rv0, py0 = wk(s.revenue, 0), wk(s.payers, 0)
    rvb, pyb = np.mean([wk(s.revenue, k) for k in (1, 2, 3, 4)]), np.mean([wk(s.payers, k) for k in (1, 2, 3, 4)])
    if py0 and pyb and rvb:
        ap0, apb = rv0 / py0, rvb / pyb
        if abs(ap0 - apb) / apb > 0.40:
            add('商业化', 'mon', 'ARPPU(近 7 天,按付费人次)', r(ap0, 1), r(apb, 1), (ap0 - apb) / apb, 'info', 'money', '', 7, persistent=False)
    # 大 R:不逐人报;汇总成一条
    W = DATA['money']['whales']
    reds = [w for w in W if w['status'] == 'red']; yel = [w for w in W if w['status'] == 'yellow']
    if reds:
        add('大 R', 'whale', f'大 R 停止登录或停止付费:{len(reds)} 人', len(reds), None, None, 'red', 'money', '、'.join(str(w['id']) for w in reds))
    if yel:
        add('大 R', 'whale', f'大 R 需运营关注:{len(yel)} 人', len(yel), None, None, 'yellow', 'money', '、'.join(str(w['id']) for w in yel) + '(仍在登录,付费或活跃有下降)')
    # 玩法参与:近 7 天日均 vs 之前 28 天,降 > 20% 黄
    gp = []
    for name, df in (('入侵', c.pvp), ('联盟捐献', c.ally), ('副本 1', c.pve)):
        if not len(df): continue
        dd = df.groupby('d').monetId.nunique().reindex(pd.date_range(E - pd.Timedelta(days=34), E), fill_value=0)
        now, base = dd.iloc[-7:].mean(), dd.iloc[:-7].mean()
        dev = (now - base) / base if base else None
        gp.append({'name': name, 'now': r(now, 1), 'base': r(base, 1), 'dev': r(dev)})
        if dev is not None and dev < -0.20:
            add('玩法', 'game', f'{name} 日参与人数(近 7 天均值)', r(now, 1), r(base, 1), dev, 'yellow', 'life', '', 7)
    # ---- 2026-10-29 按《AI 看板数据需求》第七节补的预警,最多「观察中」,都是持续性指标
    # 601 真新设备留存低于底线:95% 区间整体低于底线才报(样本小时不下结论)
    N = DATA.get('n601') or {}
    for q in ((N.get('cohort_q') or {}).get('summary') or []):
        if q.get('key') != 'fresh':
            continue
        for m_, line in (('d1', 0.226), ('d7', 0.049)):
            x = q.get(m_) or {}
            if (x.get('verdict') or '').startswith('低于'):
                add('601', 'n601', f'601 真新设备 {m_.upper()} 留存低于底线', x.get('rate'), line, (x['rate'] - line) / line if x.get('rate') is not None else None,
                    'yellow', 'n601', f'{x.get("n")}/{x.get("base")} 人,95% 区间 {x["ci"][0]:.1%}–{x["ci"][1]:.1%},整体低于底线 {line:.1%}', 7)
    # 601 连续无真实订单(已去掉测试号)
    nd601 = N.get('daily') or []
    if nd601:
        k_ = 0
        for x in reversed(nd601):
            if x.get('payers'):
                break
            k_ += 1
        if k_ >= 5:
            last = next((x['d'] for x in reversed(nd601) if x.get('payers')), None)
            add('601', 'n601', f'601 连续 {k_} 天没有真实订单', f'{k_} 天', None, None, 'yellow', 'n601',
                f'最后一笔真实订单在 {last};已去掉排除名单里的测试号' if last else '内测以来没有真实订单', k_)
    # 老服首付断流:近 14 天首次付费人数 vs 之前 8 个两周的均值,降 > 50% 且基准 ≥ 4 人
    F_ = c.first_order[c.first_order <= E]
    cnt = [int(((F_ > E - pd.Timedelta(days=14 * (k + 1))) & (F_ <= E - pd.Timedelta(days=14 * k))).sum()) for k in range(9)]
    base_ = float(np.mean(cnt[1:]))
    if base_ >= 4 and cnt[0] < 0.5 * base_:
        add('商业化', 'mon', '首次付费人数(近 14 天)', cnt[0], r(base_, 1), (cnt[0] - base_) / base_, 'yellow', 'money', '对比之前 8 个两周的均值;老服,按账号历史第一笔订单', 14)
    # 到顶堆积:主城到顶人数占比,近 4 周均值比前 4 周升 ≥ 3 个百分点
    tr = (DATA.get('level_cap') or {}).get('trend') or []
    if len(tr) >= 8:
        a4 = np.mean([x['share'] for x in tr[-4:] if x['share'] is not None]); b4 = np.mean([x['share'] for x in tr[-8:-4] if x['share'] is not None])
        if a4 - b4 >= 0.03:
            add('生命周期', 'life', '主城到顶人数占比上升(近 4 周)', r(a4), r(b4), (a4 - b4) / b4 if b4 else None, 'yellow', 'life', f'到顶 = 主城 {DATA["level_cap"]["cap"]} 级;对比前 4 周', 28)
    # 钻石:能算出的净额(游戏内循环 + 博彩)连续两周为正 = 净发钻;外部接入没有扣钻记录,单独提示
    M_ = DATA.get('money') or {}
    ddr = (M_.get('diamond_daily') or {}).get('rows') or []
    if len(ddr) >= 14:
        dd_ = pd.DataFrame(ddr, columns=M_['diamond_daily']['columns'])
        net_ = dd_.in_loop - dd_.out_loop - dd_.gamble_net_out
        w0, w1 = float(net_.iloc[-7:].sum()), float(net_.iloc[-14:-7].sum())
        if w0 > 0 and w1 > 0:
            add('经济', 'econ', '钻石净发(连续两周)', round(w0), round(w1), None, 'yellow', 'money', '游戏内循环 + 博彩的净额连续两周为正;不含外部接入 WPP、GameAPI', 14)
        e0, l0 = float(dd_.ext_in.iloc[-7:].sum()), float(dd_.out_loop.iloc[-7:].sum())
        if e0 and l0 and e0 / l0 >= 0.5:
            add('经济', 'econ', '外部接入发钻占游戏内消耗的比例(近 7 天)', r(e0 / l0), None, None, 'info', 'money',
                f'WPP + GameAPI 近 7 天发出 {e0 / 1e4:,.0f} 万钻,游戏内循环消耗 {l0 / 1e4:,.0f} 万钻;外部接入没有扣钻记录,来源待研发确认', 7, persistent=False)
    # 老虎机:只看钻石下注的局,返还率 > 100% = 玩家整体赢钻;券积压单列
    sl = M_.get('slot') or {}
    if sl.get('7') and sl['7']['bet'] and sl['7']['rate'] is not None and sl['7']['rate'] > 1.0:
        add('经济', 'econ', '老虎机返还率(钻石下注的局,近 7 天)', sl['7']['rate'], 1.0, sl['7']['rate'] - 1.0, 'yellow', 'money',
            f'下注 {sl["7"]["bet"]:,} 钻,返还 {sl["7"]["ret"]:,} 钻;不含用券的局', 7)
    tk7 = sl.get('tickets7')
    if tk7 and tk7['used'] and tk7['issued'] >= 2 * tk7['used']:
        add('经济', 'econ', '老虎机券积压(近 7 天发放 ÷ 使用)', f"{tk7['issued'] / tk7['used']:.1f} 倍", None, None, 'yellow', 'money',
            f'发出 {tk7["issued"]:,} 张、用掉 {tk7["used"]:,} 张(' + '、'.join(f'{TICKET_USE.get(k_, k_)} {v:,}' for k_, v in tk7.get('used_by', [])) +
            f');老虎机每张券平均返还约 {tk7["per_ticket"]} 钻;来源前三:' +
            '、'.join(f'{k_} {v:,}' for k_, v in tk7['by_source'][:3]), 7)
    order = {'red': 0, 'yellow': 1, 'info': 2}
    al.sort(key=lambda x: (order[x['level']], -(x['win'] or 0)))
    def lvl_of(dim):
        ls = [x['level'] for x in al if x['dim'] == dim and x['level'] != 'info']
        return 'red' if 'red' in ls else ('yellow' if 'yellow' in ls else 'green')
    names = [('acq', '获客'), ('funnel', '新手漏斗'), ('ret', '留存'), ('eng', '活跃'), ('game', '玩法'), ('mon', '商业化'), ('whale', '大 R'),
             ('econ', '经济'), ('life', '生命周期'), ('n601', '601')]
    health = [{'key': k, 'name': n, 'status': lvl_of(k)} for k, n in names]
    return al, health, gp


def top_problems(c, DATA):
    P = []
    nu = DATA['new_user']; E = c.end
    # 告警里的红色先列
    for a in DATA['alerts']:
        if a['level'] not in ('red', 'yellow') or a['category'] == '大 R' or not a.get('persistent', True):
            continue
        if '进入游戏' in a['metric']:
            plat = a['metric'].split()[0]; w_ = a.get('win') or 7
            d = pd.DataFrame(nu['daily']['series'][plat], columns=nu['daily']['columns']).iloc[-w_:]
            lost = int(d.registrations.sum() * a['baseline'] - d.entered.sum()) if a['baseline'] else None
            base_txt = '前 4 周' if w_ == 7 else '再往前 28 天'
            P.append({'severity': a['level'], 'title': f'{plat} 新用户「注册 → 进入游戏」比例下降(排查中)' if w_ == 28 else f'{plat} 新用户「注册 → 进入游戏」比例下降',
                      'evidence': f"近 {w_} 天 {a['current']:.0%},{base_txt} {a['baseline']:.0%}({a['note']})",
                      'impact': f'按{base_txt}的比例估算,近 {w_} 天少进来约 {lost} 人' if lost and lost > 0 else '—',
                      'cause': '待验证:客户端包 / 资源下载 / 选服创角流程故障,或新买量渠道、模拟器等异常设备(见新用户页「进入率下钻」)',
                      'action': '研发查该平台启动、下载、创角日志;投放查近期新增渠道;排除异常机型后复看', 'page': 'newuser'})
        elif 'Lv3' in a['metric']:
            plat = a['metric'].split()[0]; w_ = a.get('win') or 7
            d = pd.DataFrame(nu['daily']['series'][plat], columns=nu['daily']['columns']).iloc[-w_:]
            fewer = int(round(d.entered.sum() * (a['baseline'] - a['current']))) if a['baseline'] is not None else None
            base_txt = '前 4 周' if w_ == 7 else '再往前 28 天'
            P.append({'severity': a['level'], 'title': a['metric'] + ' 下降',
                      'evidence': f"近 {w_} 天 {a['current']:.0%},{base_txt} {a['baseline']:.0%}({a['note']})",
                      'impact': f'近 {w_} 天进入游戏 {int(d.entered.sum())} 人,按{base_txt}的比例估算,当天到 Lv3 的少了约 {fewer} 人' if fewer and fewer > 0 else '—',
                      'cause': '待验证:新手引导或首日数值改动,或同期进入游戏的人群变了(如异常设备)', 'action': '对照最近版本与引导改动;按机型排除异常设备后复看', 'page': 'newuser'})
        elif a['metric'].startswith('DAU'):
            P.append({'severity': a['level'], 'title': 'DAU 低于前 4 周水平', 'evidence': f"近 7 天日均 {a['current']:.0f},前 4 周 {a['baseline']:.0f}",
                      'impact': f"{a['deviation']:+.0%}", 'cause': '待验证:按平台 / 等级段切换看下降来自哪类玩家', 'action': '首页切平台与等级段筛选定位', 'page': 'home'})
        elif a['metric'].startswith('收入'):
            P.append({'severity': a['level'], 'title': '近 7 天收入低于前 4 周水平', 'evidence': f"${a['current']:,.0f} vs 前 4 周周均 ${a['baseline']:,.0f}",
                      'impact': f"{a['deviation']:+.0%}", 'cause': '收入日波动主要由大 R 决定', 'action': '看大 R 风险表与付费人数', 'page': 'money'})
    # 结构性问题:每次刷新都按最新数据重新判断是否仍然成立
    d = pd.DataFrame(nu['daily']['series']['all'], columns=nu['daily']['columns']).iloc[-30:]
    if d.entered.sum():
        l3 = d.lv3.sum() / d.entered.sum()
        if l3 < 0.30:
            P.append({'severity': 'yellow', 'title': '新手首日停在主城 1–2 级的比例过高',
                      'evidence': f'近 30 天进入游戏 {int(d.entered.sum())} 人,当天到 Lv3 的 {int(d.lv3.sum())} 人({l3:.0%})',
                      'impact': f'近 30 天约 {int(d.entered.sum() - d.lv3.sum())} 个新玩家首日停在 1–2 级;这类人次日留存通常远低于到 3 级的人(相关性)',
                      'cause': '待验证:首次加载、引导在 2 级后缺下一步目标、首日反馈', 'action': '引导延伸到 3 级做 A/B(按账号 ID 随机分组)', 'page': 'newuser'})
    conc = DATA['money']['concentration']['rows']
    top5 = next((x for x in conc if x['top'] == '5%'), None)
    if top5 and top5['share'] and top5['share'] > 0.5:
        P.append({'severity': 'yellow', 'title': '收入高度依赖少数大 R',
                  'evidence': f"近 90 天前 5% 付费者({top5['users']} 人)贡献 {top5['share']:.0%} 收入",
                  'impact': '任何一个头部大 R 流失都直接体现在月流水上', 'cause': '游戏生命周期长、新付费者少',
                  'action': '按大 R 风险表逐个跟进;红色名单当天联系', 'page': 'money'})
    life = DATA['life']['retention15']['rows']['all']
    lo = next((x for x in life if x[0] == '1-2'), None)
    if lo and lo[1] >= 30 and lo[2] / lo[1] < 0.2:
        P.append({'severity': 'yellow', 'title': '1–2 级玩家几乎留不住',
                  'evidence': f'前 15 天活跃的 1–2 级玩家 {lo[1]} 人,后 15 天还在的 {lo[2]} 人({lo[2]/lo[1]:.0%})',
                  'impact': '新用户投入基本流失在这一段', 'cause': '同「新手首日」', 'action': '同上', 'page': 'life'})
    k = DATA['kpi'].get('30|all|all', {}).get('cur', {})
    if k.get('registrations') and k.get('rev_per_new_user') is not None and k['rev_per_new_user'] < 0.5:
        P.append({'severity': 'yellow', 'title': '新用户几乎不产生收入',
                  'evidence': f"近 30 天注册 {k['registrations']} 人,人均带来 ${k['rev_per_new_user']:.2f}",
                  'impact': '买量难回本', 'cause': '新人走不到需要付费的等级', 'action': '3–6 级首充礼包与新手目标绑定,随机分组验证', 'page': 'money'})
    return P[:5]



# ---------------------------------------------------------------- 601 新版内测服(2026-10-21 初版)
# 601 是新版,不写老版登录日志,所以和其他页的口径不同:
# - 活跃 = 当天有任一痕迹:每日任务 / 签到 / 名人每日任务 / 加速道具 / 付款 / 注册当天 / player.lastLoginTime 那天。仍会漏人(偏低)
# - 601 库的时间是中国时间(UTC+8;用礼包下单的 UTC 毫秒时间戳对过,正好差 8 小时),和老服 Log 库的 timeCN 一致
# - 老服账号 = monetId < 2,110,000(用旧号直接进 601);新建号 = 其余。新建号里也有老玩家换设备 / 建小号,这里分不出
# - 充值:Google / Apple 订单按 New Era 支付表判断到账(2026-11-03 起);PayerMax 网页支付没有状态记录,仍是「待核实」
N601_START = '2026-10-13'              # 内测开始;之前是支付联调期,注册和订单都不算
# 601 版本、投放、活动日历(2026-11-04 加,用户确认):趋势图上按天标出,读数时当切点。时间都是新加坡 / 中国时间(UTC+8)。
# 来源:B72 更新说明截图(invader/参考资料/版本说明/)、用户口述(投放)。活动开始后要按数据确认真的开了。
def _carnival_weeks():
    out, d = [], pd.Timestamp('2026-11-06 05:00')
    while d < pd.Timestamp('2026-12-31'):
        out.append([d.strftime('%Y-%m-%d %H:%M'), (d + pd.Timedelta(days=5)).strftime('%Y-%m-%d %H:%M')]); d += pd.Timedelta(days=7)
    return out
N601_EVENTS = [
    {'kind': '投放', 'name': '新 App 停投(约)', 'start': '2026-10-24', 'end': None, 'note': '用户口述,日期是大约;老 App 一直在投'},
    {'kind': '版本', 'name': 'B72(2.4.0053)发版', 'start': '2026-11-04', 'end': None, 'note': '依赖服务端构建 56;带 event_uuid、install_referrer 等新字段'},
    {'kind': '投放', 'name': '601 重新开投', 'start': '2026-11-04', 'end': None, 'note': '用户口述'},
    {'kind': '活动', 'name': '消费嘉年华', 'start': '2026-11-06 05:00', 'end': '2026-12-31', 'windows': _carnival_weeks(), 'note': '每周五 05:00 至下周三 05:00,持续到 12 月'},
    {'kind': '活动', 'name': '充值返利(百分百分红)', 'start': '2026-11-06 05:00', 'end': '2026-11-07 05:00', 'note': '只开这一次'},
    {'kind': '活动', 'name': '英雄升级', 'start': '2026-11-14 03:00', 'end': '2027-01-04 02:59', 'windows': [['2026-11-14 03:00', '2026-11-21 02:59']], 'note': '第一期 11-14 03:00 ~ 11-21 02:59,之后每 11 天一期'},
    {'kind': '道具', 'name': '限时票 1,500 张(5 位指定玩家)', 'start': None, 'end': None, 'note': '7 天有效,需单独发放,发放时间未定;读券数据时单列'},
]
N6_WINDOWS = (1, 7, 14, 30)            # 2026-11-03:601 各页的时间筛选;近 1 天 = 数据截至日全天(中国时间)
# 2026-10-28 排除名单改为读 data/exclusions.json(所有报表共用一份);文件缺失或损坏时退回下面这份测试号
EXCLUSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'exclusions.json')
N601_TEST_IDS_FALLBACK = {2116084, 2116101, 2116102, 2116103, 2116104, 2116105, 2116106, 2116107, 2116108, 2116131, 2116132}   # 2026-10-29 已确认测试账号 11 个(提审号 2 + InvTest001–008 + 原技术号)


def load_exclusions(scope):
    """返回 (剔除 id 集合, 疑似名单 list, 错误信息)。只认 status=exclude 的条目做剔除;suspect 只展示。"""
    try:
        acc = [a for a in json.load(open(EXCLUSIONS_FILE, encoding='utf-8'))['accounts'] if a.get('scope') == scope]
        ex = {int(a['id']) for a in acc if a.get('status') == 'exclude'}
        sus = [{'id': int(a['id']), 'reason': a.get('reason', ''), 'added': a.get('added', '')} for a in acc if a.get('status') == 'suspect']
        return ex, sus, None
    except Exception as e:
        return set(N601_TEST_IDS_FALLBACK), [], f'{type(e).__name__}: {e}'


N601_OLD_ID_MAX = 2110000
# 建筑类型名:来自 601 库各建筑配置表(GoldMineType 等)的 Name。类型 6、9、10、11、12 配置表里没有名字,不展示
N601_BUILDINGS = {5: '主城 Palace', 1: '金矿 Gold Mine', 2: '金库 Gold Storage', 3: '水晶矿 Crystal Mine', 4: '水晶库 Crystal Storage',
                  7: '兵营 Camp', 8: '学院 Academy', 13: '法力神殿 Mana Shrine', 16: '宠物乐园 Pet Garden'}


# 留存参照线(2026-10-28,《Invader AI 看板数据需求》H5 / 《对症下药》「留存目标」):底线 = 中东全品类平均
RET_LINES = [{'key': 'floor', 'name': '底线', 'd1': 0.226, 'd7': 0.049},
             {'key': 'step1', 'name': '第一步', 'd1': 0.25, 'd7': 0.07, 'd1_hi': 0.27, 'd7_hi': 0.08},
             {'key': 'target', 'name': '目标线', 'd1': 0.33, 'd7': 0.11, 'd30': 0.04}]


def wilson(k, n, z=1.96):
    """二项比例的 Wilson 95% 区间;n = 0 返回 None。小样本比正态近似稳。"""
    if not n:
        return None
    p_ = k / n; d = 1 + z * z / n
    c_ = (p_ + z * z / (2 * n)) / d; h = z * math.sqrt(p_ * (1 - p_) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c_ - h), 4), round(min(1.0, c_ + h), 4)]


def ret_verdict(metric, ci):
    """按区间判断相对参照线的位置;区间跨线时不下结论。只对有参照线的 D1 / D7 / D30 给结论。"""
    lines = [(x['name'], x[metric]) for x in RET_LINES if metric in x]
    if not ci or not lines:
        return None
    lo, hi = ci
    if hi < lines[0][1]:
        return f'低于{lines[0][0]}'
    passed = [nm for nm, v in lines if lo >= v]
    if passed:
        return f'达到{passed[-1]}'
    return '区间跨过参照线,样本不足以判断'


def farm_models(c, days=28):
    """近 N 天注册里的疑似刷量机型(和自洽检查同一条规则)。"""
    A = getattr(c, 'A_all', c.A)
    A = A[A.reg > c.end - pd.Timedelta(days=days)].copy()
    A['entered'] = [(a, d) in c.login_set for a, d in zip(A.monetId, A.reg)]
    g = A.groupby(A.phone_type.fillna('未知')).agg(n=('monetId', 'size'), ent=('entered', 'mean'))
    return g[(g.n >= CHECK_FARM_MIN_REGS) & (g.ent < CHECK_FARM_MAX_ENTRY)].sort_values('n', ascending=False)


def n601(c, only=None):
    m = c.raw
    P = pd.DataFrame(m.get('N601_players detail', []))
    if not len(P):
        return None
    E = c.end
    start = pd.Timestamp(N601_START)
    N601_TEST_IDS, suspects, excl_err = load_exclusions('n601')
    P['reg'] = pd.to_datetime(P.created_at, format='mixed').dt.normalize()
    P['last'] = pd.to_datetime(P.last_login_at, format='mixed')
    all_ids = set(P.monetId)
    before = int((P.reg < start).sum()); tests = int(P.monetId.isin(N601_TEST_IDS).sum())
    P = P[(P.reg >= start) & (P.reg <= E) & ~P.monetId.isin(N601_TEST_IDS)].copy()
    if only is not None:   # 2026-11-04 平台 / 版本 / 国家筛选:只算这批玩家
        P = P[P.monetId.isin(only)].copy()
    P['grp'] = np.where(P.monetId < N601_OLD_ID_MAX, 'old', 'new')
    ids = set(P.monetId)
    # 订单
    O = pd.DataFrame(m.get('N601_orders', []))
    O['t'] = pd.to_datetime(O.created_at, format='mixed'); O['d'] = O.t.dt.normalize()
    O['why'] = None
    O.loc[O.d < start, 'why'] = '内测开始前(支付联调期)'
    O.loc[O.why.isna() & O.monetId.isin(N601_TEST_IDS), 'why'] = '清单内测试号'
    # 到账状态(2026-11-03):New Era 支付表按商店订单号对上(卡 N601_order status)。paid = 商店确认扣款(Apple 为生产环境收据)且奖励已发放;
    # test = Google 测试卡 / Apple 沙盒;refund = Google 状态已退款;unconfirmed = 有记录但没确认;pending = 没有状态记录(PayerMax 网页,待核实)
    def order_status(x):
        if x['environment'] == 'sandbox' or x['store_test']: return 'test'
        if x['money_state'] == 'REFUNDED': return 'refund'
        if x['rewards_done'] and (x['money_state'] == 'PROCESSED' or (x['channel'] == 'apple' and x['environment'] == 'production')): return 'paid'
        return 'unconfirmed'
    O['status'] = O.order_id.astype(str).map({str(x['order_id']): order_status(x) for x in m.get('N601_order status', [])}).fillna('pending')
    O.loc[O.why.isna() & (O.status == 'test'), 'why'] = '商店测试购买(Google 测试卡 / Apple 沙盒)'
    O.loc[O.why.isna() & (O.status == 'refund'), 'why'] = '已退款'
    O.loc[O.why.isna() & ~O.monetId.isin(all_ids), 'why'] = '角色已不在 601'
    O.loc[O.why.isna() & (O.d > E), 'why'] = '今天(未完整)'
    Ok = O[O.why.isna()].copy()
    if only is not None:   # 分组时订单也只算这批玩家
        Ok = Ok[Ok.monetId.isin(set(P.monetId))].copy()
    Ok['pay_ch'] = Ok.channel.map({'ThirdParty': 'PayerMax(网页)', 'Google': 'Google', 'Apple': 'Apple'}).fillna(Ok.channel)
    # 活跃痕迹
    acts = []
    T = pd.DataFrame(m.get('N601_activity tasks day', []))
    if len(T): acts.append(pd.DataFrame({'monetId': T.monetId, 'd': pd.to_datetime(T.day)}))
    S = pd.DataFrame(m.get('N601_activity signin', []))
    if len(S): acts.append(pd.DataFrame({'monetId': S.monetId, 'd': pd.to_datetime(S.signin_at, format='mixed').dt.normalize()}))
    # 2026-10-21 补两种带日期的记录:名人每日任务、加速道具(1970 占位日期会被下面的日期范围过滤掉)。
    # 签到活动 CheckIn 不用:它的 checkInDate 是游戏日(约凌晨 5 点换日),0~5 点注册的人会被记到前一天,混进来会出现注册前就活跃
    for card in ('N601_activity celebrity tasks day', 'N601_activity accelerator'):
        X_ = pd.DataFrame(m.get(card, []))
        if len(X_): acts.append(pd.DataFrame({'monetId': X_.monetId, 'd': pd.to_datetime(X_.day, errors='coerce')}))
    acts.append(pd.DataFrame({'monetId': P.monetId, 'd': P.reg}))
    acts.append(pd.DataFrame({'monetId': P.monetId, 'd': P['last'].dt.normalize()}))
    acts.append(pd.DataFrame({'monetId': Ok.monetId, 'd': Ok.d}))
    Act = pd.concat(acts).dropna()
    Act = Act[Act.monetId.isin(ids) & (Act.d >= start) & (Act.d <= E)].drop_duplicates()
    Act['grp'] = Act.monetId.map(P.set_index('monetId').grp)
    act_set = set(zip(Act.monetId, Act.d))
    if only is None:   # 2026-11-04 留存双轨:代理活跃集合和注册日留给埋点会话口径对照(只在全部玩家时)
        c.n601_act, c.n601_reg = act_set, P.set_index('monetId').reg.to_dict()
    # 2026-10-28 自洽检查用:注册日之前就有活跃痕迹的人(时区或游戏日口径错位时会出现)
    pre = Act[Act.d < Act.monetId.map(P.set_index('monetId').reg)]
    act_before_reg = {'rows': int(len(pre)), 'users': int(pre.monetId.nunique())}
    days = pd.date_range(start, E)
    daily = []
    for d in days:
        reg = P[P.reg == d]; a = Act[Act.d == d]; o = Ok[Ok.d == d]
        daily.append({'d': d.strftime('%Y-%m-%d'), 'reg_old': int((reg.grp == 'old').sum()), 'reg_new': int((reg.grp == 'new').sum()),
                      'act_old': int((a.grp == 'old').sum()), 'act_new': int((a.grp == 'new').sum()),
                      'orders': int(len(o)), 'payers': int(o.monetId.nunique()), 'usd': r(o.price.sum(), 2)})
    # 留存:注册后第 N 天有活跃痕迹;只算已满 N 天的注册日
    def ret(sub, n):
        ok = sub[sub.reg + pd.Timedelta(days=n) <= E]
        k = sum((mm, rg + pd.Timedelta(days=n)) in act_set for mm, rg in zip(ok.monetId, ok.reg))
        return {'n': int(k), 'base': int(len(ok)), 'rate': r(k / len(ok)) if len(ok) else None}
    groups = {'all': P, 'old': P[P.grp == 'old'], 'new': P[P.grp == 'new']}
    retention = {g: {f'd{n}': ret(x, n) for n in (1, 3, 7)} for g, x in groups.items()}
    cohorts = []
    for d, x in P.groupby('reg'):
        cohorts.append({'d': d.strftime('%Y-%m-%d'), 'n': int(len(x)), 'old': int((x.grp == 'old').sum()),
                        **{f'd{n}': ret(x, n) for n in (1, 3, 7)}})
    # 进度:主城 = building type 5;英雄
    B = pd.DataFrame(m.get('N601_progress building', []))
    city = B[B.building_type == 5].set_index('monetId').max_level if len(B) else pd.Series(dtype=float)
    H = pd.DataFrame(m.get('N601_progress hero', []))
    hero = H.set_index('monetId') if len(H) else pd.DataFrame(columns=['heroes', 'max_hero_level'])
    P['city'] = P.monetId.map(city); P['hero_lv'] = P.monetId.map(hero.max_hero_level) if len(H) else np.nan
    P['heroes'] = P.monetId.map(hero.heroes).fillna(0) if len(H) else 0
    P['act_days'] = P.monetId.map(Act.groupby('monetId').d.nunique()).fillna(0).astype(int)
    P['since_last'] = (E - P['last'].dt.normalize()).dt.days
    groups = {'all': P, 'old': P[P.grp == 'old'], 'new': P[P.grp == 'new']}   # 重新切:上面加了进度列
    city_bins = [(1, 1, '1'), (2, 2, '2'), (3, 5, '3-5'), (6, 10, '6-10'), (11, 15, '11-15'), (16, 99, '16+')]
    def dist(x):
        return [[name, int(((x.city >= lo) & (x.city <= hi)).sum()), int(((x.city >= lo) & (x.city <= hi) & (x.since_last <= 2)).sum())] for lo, hi, name in city_bins]
    def med(sr):
        sr = sr.dropna(); return r(sr.median(), 1) if len(sr) else None
    progress = {g: {'n': int(len(x)), 'city_median': med(x.city), 'city_p90': r(x.city.quantile(.9), 1) if x.city.notna().any() else None,
                    'hero_median': med(x.hero_lv), 'hero_users': int((x.heroes > 0).sum()), 'act_days_median': med(x.act_days),
                    'city_dist': dist(x)} for g, x in groups.items()}
    # 各建筑 + 英雄等级:每人取该类建筑里最高的一座;「近 3 天在玩」= 最后登录在 截至日前 2 天 及以后(含今天,player.lastLoginTime 是实时的)
    recent = set(P[P.since_last <= 2].monetId)
    def lv_row(name, sr):
        sr = sr[sr.index.isin(ids)].dropna()
        rc = sr[sr.index.isin(recent)]
        return {'name': name, 'users': int(len(sr)), 'median': med(sr), 'p90': r(sr.quantile(.9), 1) if len(sr) else None,
                'max': int(sr.max()) if len(sr) else None, 'recent_users': int(len(rc)), 'recent_median': med(rc)}
    levels = []
    if len(B):
        for t, name in N601_BUILDINGS.items():
            levels.append(lv_row(name, B[B.building_type == t].groupby('monetId').max_level.max()))
    if len(H):
        levels.append(lv_row('英雄(最高一个)', hero.max_hero_level))
    # 玩法参与(2026-10-21):601 的玩法表多是「当前状态」或每人只留一条,看不了每天,只看「玩过没有、玩到哪」
    # 入侵记录的时间大多是 1970 占位值、竞技场对战每人只留近期几条,所以都不做逐日
    def ids_of(card, col, cond=None):
        x = pd.DataFrame(m.get(card, []))
        if not len(x): return set(), x
        if cond is not None: x = x[cond(x)]
        return set(x[col]) & ids, x
    feats = []
    D_ = pd.DataFrame(m.get('N601_dungeons', []))
    for mode, label in (('dungeon1', '副本 1'), ('dungeon2', '副本 2')):
        x = D_[(D_['mode'] == mode) & D_.monetId.isin(ids) & (D_.completed > 0)] if len(D_) else D_
        feats.append((label, set(x.monetId) if len(x) else set(), f"通关的最大关卡编号:中位数 {med(x.max_completed) if len(x) else '—'},最大 {int(x.max_completed.max()) if len(x) else '—'}(关卡编号是否连续未核对)"))
    s_inv, _ = ids_of('N601_invade battles', 'attacker_id')
    feats.append(('入侵', s_inv, '库里每人只留最近一条,看不了次数'))
    s_sw, x = ids_of('N601_sweep', 'attacker_id')
    feats.append(('扫荡', s_sw, f"{len(x[x.attacker_id.isin(ids)])} 个 攻方 × 城主 组合"))
    s_ab, xb = ids_of('N601_arena battles', 'attacker_id')
    # 2026-11-04 改:「打过竞技场」原按 score != 1000 判,和「新人前 7 天」那处(lastTime 不是 1900)不一致,统一成 lastTime。
    # 原因:解锁时自动建行,积分 1000、lastTime 1900 占位;打过又回到 1000 分的人会被积分判法漏掉。
    # 影响:11-04 全表非机器人 238 行,积分判法 14 人,lastTime 判法 54 人;再并上对战表攻方。用户 11-04 确认。
    s_ap, xa = ids_of('N601_arena players', 'monetId', lambda d: ~d.last_at.astype(str).str[:4].isin(['', '1900', 'None', 'NaT', 'nan']))
    s_open, _ = ids_of('N601_arena players', 'monetId')
    feats.append(('竞技场', s_ab | s_ap, f"开启竞技场 {len(s_open)} 人;对战记录只留近期 {len(xb)} 场"))
    s_wb, xw = ids_of('N601_world boss', 'monetId')
    fw = xw[xw.monetId.isin(ids)].fights if len(xw) else pd.Series(dtype=float)
    feats.append(('世界 BOSS', s_wb, f"每人记录条数中位数 {med(fw)},最多 {int(fw.max()) if len(fw) else '—'}(少数人几百条,所以不用平均;一条记录是否等于一次挑战未核对)"))
    s_al, xm = ids_of('N601_alliance members', 'monetId')
    n_al = xm[xm.monetId.isin(ids)].alliance_id.nunique() if len(xm) else 0
    feats.append(('在联盟', s_al, f"分布在 {n_al} 个联盟(601 共 {len(m.get('N601_alliances', []))} 个)"))
    grp = P.set_index('monetId').grp
    def recent_rate(sset):
        k = len(sset & recent); return {'n': k, 'base': len(sset), 'rate': r(k / len(sset)) if sset else None}
    gameplay = [{'name': nm_, 'users': len(ss), 'share': r(len(ss) / len(ids)) if ids else None,
                 'old': int(sum(grp.get(i) == 'old' for i in ss)), 'new': int(sum(grp.get(i) == 'new' for i in ss)),
                 'recent_in': recent_rate(ss), 'recent_out': recent_rate(ids - ss), 'note': note}
                for nm_, ss, note in feats]
    # 老服账号在老服还玩不玩(2026-10-21):同一批人在 601 的活跃 vs 在老服的登录(Log 库 GetUserInfo,中国时间)
    # 两边都是中国时间。「近 3 天」两边都取 截至日前 2 天 ~ 截至日(601 用活跃痕迹,不用实时的 lastLoginTime,避免 601 多算今天)
    old_ids = set(P[P.grp == 'old'].monetId)
    LO = c.LS[c.LS.monetId.isin(old_ids)]
    base_from = start - pd.Timedelta(days=7)
    migration_daily = []
    for d in pd.date_range(base_from, E):
        migration_daily.append({'d': d.strftime('%Y-%m-%d'), 'old_server': int(LO[LO.d == d].monetId.nunique()),
                                'n601': int(Act[(Act.d == d) & Act.monetId.isin(old_ids)].monetId.nunique()) if d >= start else None})
    O90 = c.O[(c.O.d > E - pd.Timedelta(days=90)) & c.O.monetId.isin(old_ids)].groupby('monetId').price.sum()
    lo_days = LO[LO.d >= start].groupby('monetId').d.nunique()
    lo_last = LO.groupby('monetId').last_login_at.max()
    lo_srv = LO[LO.d >= start].groupby('monetId').server_id.agg(lambda v: '、'.join(map(str, sorted(set(v)))))
    a601 = Act[Act.monetId.isin(old_ids)].groupby('monetId').d.nunique()
    n_days = (E - start).days + 1
    migrants = []
    for _, x in P[P.grp == 'old'].iterrows():
        mm = x.monetId
        migrants.append({'id': int(mm), 'name': x['name'], 'pay90_old': r(O90.get(mm, 0), 2), 'days_601': int(a601.get(mm, 0)),
                         'days_old': int(lo_days.get(mm, 0)), 'old_servers': lo_srv.get(mm, ''),
                         'last_601': x['last'].strftime('%Y-%m-%d %H:%M') if pd.notna(x['last']) else None,
                         'last_old': str(lo_last.get(mm))[:16] if pd.notna(lo_last.get(mm)) else None,
                         'city': int(x.city) if pd.notna(x.city) else None})
    migrants.sort(key=lambda z: -(z['pay90_old'] or 0))
    r3_601 = set(Act[(Act.d >= E - pd.Timedelta(days=2)) & Act.monetId.isin(old_ids)].monetId)
    r3_old = set(LO[LO.d > E - pd.Timedelta(days=3)].monetId)
    migration = {'n': len(old_ids), 'days': n_days, 'daily': migration_daily,
                 'recent': {'both': len(r3_601 & r3_old), 'only_601': len(r3_601 - r3_old), 'only_old': len(r3_old - r3_601),
                            'neither': len(old_ids - r3_601 - r3_old)},
                 'payers_old': int((O90 > 0).sum()), 'whales_old': int((O90 >= 1000).sum()), 'people': migrants,
                 'new_with_old_login': int(c.LS[c.LS.monetId.isin(set(P[P.grp == 'new'].monetId)) & (c.LS.d >= start)].monetId.nunique())}
    # 按设备分组(2026-10-21):新建号里,同一台设备(广告 ID)上有老账号的 = 老玩家小号;否则 = 全新设备;没有广告 ID = 无法判断
    DV = pd.DataFrame(m.get('N601_device ids', []))
    if len(DV):
        dev_accts = DV.groupby('device_hash').monetId.apply(set)
        acct_devs = DV.groupby('monetId').device_hash.apply(set)
        def dev_group(mm):
            if mm < N601_OLD_ID_MAX: return 'old'
            if mm not in acct_devs.index: return 'noid'
            accts = set().union(*[dev_accts[h] for h in acct_devs[mm]])
            return 'olddev' if any(a_ < N601_OLD_ID_MAX for a_ in accts) else 'newdev'
        P['dev'] = P.monetId.map(dev_group)
        paid = Ok.groupby('monetId').price.sum()
        device_groups = []
        for g_, label in (('old', '老服账号(旧号直接进)'), ('olddev', '老玩家小号(同设备有旧号)'), ('newdev', '全新设备'), ('noid', '无广告 ID,无法判断')):
            x = P[P.dev == g_]
            device_groups.append({'key': g_, 'name': label, 'n': int(len(x)), 'd1': ret(x, 1), 'd3': ret(x, 3),
                                  'recent': int((x.since_last <= 2).sum()), 'payers': int(x.monetId.isin(paid.index).sum()),
                                  'usd': r(paid.reindex(x.monetId).sum(), 2), 'city_median': med(x.city)})
    else:
        device_groups = None
    # 新人队列(2026-10-28,H3 / H5):按注册日 × 来源,D1 / D3 / D7 / D30 带 95% 区间,和参照线、老服同期新用户对照
    # 真新设备 = 设备上没有老服账号,且是这台设备上最早的 601 账号;同设备第二个及以后的新号单列(重装 / 小号分不出)
    cohort_q = None
    if len(DV):
        first_on_dev = {}
        Pt = P.set_index('monetId')
        for mm in P[P.dev == 'newdev'].monetId:
            peers = set().union(*[dev_accts[h] for h in acct_devs[mm]]) & set(Pt.index)
            t0 = pd.to_datetime(Pt.loc[list(peers), 'created_at'], format='mixed')
            first_on_dev[mm] = t0.idxmin() == mm
        P['src'] = P.dev.map({'old': 'direct', 'olddev': 'alt', 'noid': 'noid'})
        P.loc[P.dev == 'newdev', 'src'] = P.loc[P.dev == 'newdev', 'monetId'].map(lambda x: 'fresh' if first_on_dev[x] else 'repeat')
        SRC = [('fresh', '真新设备'), ('repeat', '同设备重复新号'), ('alt', '老玩家小号(同设备有旧号)'), ('direct', '旧号直接进'), ('noid', '无广告 ID')]
        def rc(x, n):
            v = ret(x, n); v['ci'] = wilson(v['n'], v['base']); v['verdict'] = ret_verdict(f'd{n}', v['ci']); return v
        summary = [{'key': k_, 'name': nm, 'n': int((P.src == k_).sum()), **{f'd{n}': rc(P[P.src == k_], n) for n in (1, 3, 7, 30)}} for k_, nm in SRC]
        summary.append({'key': 'all', 'name': '全部', 'n': int(len(P)), **{f'd{n}': rc(P, n) for n in (1, 3, 7, 30)}})
        rows_q = []
        for d, x in P.groupby('reg'):
            rows_q.append({'d': d.strftime('%Y-%m-%d'), 'n': int(len(x)), **{k_: int((x.src == k_).sum()) for k_, _ in SRC},
                           **{f'd{n}': rc(x, n) for n in (1, 3, 7, 30)},
                           'fresh_d1': rc(x[x.src == 'fresh'], 1)})
        # 老服同期新用户:同一段注册日、注册当天进入游戏的(601 的角色都是进过游戏才有),去掉疑似刷量机型;留存用登录日志
        fm_ = set(farm_models(c).index)
        A0 = c.A_all[(c.A_all.reg >= start) & (c.A_all.reg <= E) & ~c.A_all.phone_type.fillna('未知').isin(fm_)].copy()
        A0 = A0[[(a, d) in c.login_set for a, d in zip(A0.monetId, A0.reg)]]
        def ret_old(n):
            ok = A0[A0.reg + pd.Timedelta(days=n) <= E]
            k_ = sum((a, d + pd.Timedelta(days=n)) in c.login_set for a, d in zip(ok.monetId, ok.reg))
            ci = wilson(k_, len(ok))
            return {'n': int(k_), 'base': int(len(ok)), 'rate': r(k_ / len(ok)) if len(ok) else None, 'ci': ci, 'verdict': ret_verdict(f'd{n}', ci)}
        old_ref = {'n': int(len(A0)), 'excluded_models': sorted(fm_), **{f'd{n}': ret_old(n) for n in (1, 3, 7, 30)}}
        cohort_q = {'summary': summary, 'rows': rows_q, 'old_ref': old_ref, 'lines': RET_LINES, 'src': [{'key': k_, 'name': nm} for k_, nm in SRC]}
    # 新手引导:每人完成过的引导步骤编号(同一人可能多行,取并集)。200→201→202→210→299 是所有人都走的主线,其余是功能引导
    import json as _json
    GD = pd.DataFrame(m.get('N601_guide', []))
    guide = None
    if len(GD):
        steps = defaultdict(set)
        for mm, gs in zip(GD.monetId, GD.guides):
            if mm in ids:
                try: steps[mm] |= set(_json.loads(gs))
                except Exception: pass
        main = [200, 201, 202, 210, 299]
        cnt = defaultdict(int)
        for st in steps.values():
            for k_ in st: cnt[k_] += 1
        guide = {'n': len(ids), 'with_record': len(steps), 'main': [[k_, cnt.get(k_, 0)] for k_ in main],
                 'other': sorted([[k_, v] for k_, v in cnt.items() if k_ not in main and k_ != 0], key=lambda kv: kv[0])}
    # 成就:只有编号,没有名字
    AC = pd.DataFrame(m.get('N601_achievements', []))
    achievements = None
    if len(AC):
        AC = AC[AC.monetId.isin(ids)]
        per = AC.groupby('monetId').finished.sum().reindex(list(ids), fill_value=0)
        rows_ = AC.groupby('achievement_id').agg(users=('monetId', 'nunique'), done=('finished', 'sum')).reset_index()
        achievements = {'per_player_median': med(per), 'per_player_p90': r(per.quantile(.9), 1),
                        'zero': int((per == 0).sum()), 'n': len(ids),
                        'rows': [[int(x.achievement_id), int(x.done)] for _, x in rows_.sort_values('achievement_id').iterrows()]}
    # 活动:只列内测玩家有参与记录的活动
    ACT = pd.DataFrame(m.get('N601_activities', []))
    activities = []
    if len(ACT):
        names = {'PassionLeveling': '冲级活动', 'BuildingUp': '建筑冲级', 'GroupingExchangeItem': '兑换商店', 'RemainsAdventure': '遗迹探险',
                 'NewInviteFriends': '邀请好友', 'WorldMonster': '世界 BOSS'}
        ACT = ACT.set_index('activity_id')
        PT = pd.DataFrame(m.get('N601_activity points', []))
        RC = pd.DataFrame(m.get('N601_activity records', []))
        aids = set(PT[PT.monetId.isin(ids)].activity_id) if len(PT) else set()
        aids |= set(RC[RC.monetId.isin(ids)].activity_id) if len(RC) else set()
        for aid in sorted(aids):
            if aid not in ACT.index: continue
            nm_ = ACT.activity_name[aid]
            pt_ = PT[(PT.activity_id == aid) & PT.monetId.isin(ids)] if len(PT) else PT
            rc_ = RC[(RC.activity_id == aid) & RC.monetId.isin(ids)] if len(RC) else RC
            activities.append({'name': f"{names.get(nm_, nm_)}({nm_})", 'open': str(ACT.activity_open[aid])[:10], 'close': str(ACT.activity_close[aid])[:10],
                               'with_points': int((pt_.point > 0).sum()) if len(pt_) else 0, 'records': int(rc_.monetId.nunique()) if len(rc_) else 0,
                               'claimed': int((rc_.times > 0).sum()) if len(rc_) else 0})
        activities = [x for x in activities if x['with_points'] or x['records'] or x['claimed']]   # 全是 0 的不列
    # 礼包:按商品;发起购买(下单意向)vs 实际付费
    def prod_name(p_):
        p_ = str(p_)
        if 'limit_time_pack' in p_: return '限时礼包 $' + p_.split('usd')[0]
        if 'cashgift' in p_: return '现金礼包 $0.99'
        for k_ in ('diamonds.', ''):
            pass
        import re as _re
        mt = _re.search(r'(\d+)', p_.replace('invader.unity.diamonds.', ''))
        return f"{mt.group(1)} 钻石" if mt and 'diamond' in p_ else p_
    Ok['product'] = Ok.product_id.map(prod_name)
    products = [{'name': k_, 'orders': int(len(v)), 'payers': int(v.monetId.nunique()), 'usd': r(v.price.sum(), 2)}
                for k_, v in sorted(Ok.groupby('product'), key=lambda kv: -kv[1].price.sum())]
    GR = pd.DataFrame(m.get('N601_gift reservations', []))
    gift_intent = None
    if len(GR):
        GR = GR[GR.monetId.isin(ids)]
        gift_intent = {'users': int(GR.monetId.nunique()), 'rows': int(len(GR)), 'payers': int(Ok.monetId.nunique()),
                       'both': int(len(set(GR.monetId) & set(Ok.monetId)))}
    # 来源切分(2026-10-22,团队包 E6 ③「邀请回流老付费者 vs 真新用户」):
    # 每个 601 玩家关联的老账号 = 自己(旧号直接进)+ 同一台设备上的旧账号;看这些老账号在老服历史上付没付过费
    LT = pd.DataFrame(m.get('Revenue_lifetime by account', []))
    life_pay = LT.set_index('monetId').usd if len(LT) else pd.Series(dtype=float)
    linked = {}
    for mm in ids:
        acc_ = {mm} if mm < N601_OLD_ID_MAX else set()
        if len(DV) and mm in acct_devs.index:
            for h_ in acct_devs[mm]:
                acc_ |= {a_ for a_ in dev_accts[h_] if a_ < N601_OLD_ID_MAX}
        linked[mm] = acc_
    def origin_of(mm):
        acc_ = linked[mm]
        if acc_:
            v = float(life_pay.reindex(list(acc_)).fillna(0).sum())
            return ('whale' if v >= 1000 else 'payer') if v > 0 else 'free'
        return 'noid' if P.loc[P.monetId == mm, 'dev'].iloc[0] == 'noid' else 'new'
    P['origin'] = P.monetId.map(origin_of)
    P['linked_pay'] = P.monetId.map(lambda mm: float(life_pay.reindex(list(linked[mm])).fillna(0).sum()) if linked[mm] else 0.0)
    # 沉睡回流:进 601 前 30 天,关联老账号在老服一次都没登录过
    LSi = c.LS[['monetId', 'd']]
    def dormant(mm, reg):
        acc_ = linked[mm]
        if not acc_: return False
        x = LSi[LSi.monetId.isin(acc_) & (LSi.d >= reg - pd.Timedelta(days=30)) & (LSi.d < reg)]
        return len(x) == 0
    P['dormant'] = [dormant(mm, rg) for mm, rg in zip(P.monetId, P.reg)]
    paid601 = Ok.groupby('monetId').price.sum()
    origin_rows = []
    for g_, label in (('whale', '回流大 R(关联老账号历史付费 ≥ $1,000)'), ('payer', '回流付费用户(历史付费 < $1,000)'),
                      ('free', '回流免费用户(关联老账号无付费)'), ('new', '新用户(设备上无旧账号)'), ('noid', '无法判断(无广告 ID)')):
        x = P[P.origin == g_]
        origin_rows.append({'key': g_, 'name': label, 'n': int(len(x)), 'direct': int((x.grp == 'old').sum()), 'alt': int((x.grp == 'new').sum()),
                            'dormant': int(x.dormant.sum()), 'old_pay': r(x.linked_pay.sum(), 0), 'd1': ret(x, 1),
                            'recent': int((x.since_last <= 2).sum()), 'payers': int(x.monetId.isin(paid601.index).sum()),
                            'usd': r(paid601.reindex(x.monetId).sum(), 2)})
    # 老服大 R 有多少进了 601(同账号或同设备)
    acc_in_601 = set()
    for mm in ids: acc_in_601 |= linked[mm]
    O90w = c.O[c.O.d > E - pd.Timedelta(days=90)].groupby('monetId').price.sum()
    w90 = set(O90w[O90w >= 1000].index)
    recent_old = set(c.LS[c.LS.d > E - pd.Timedelta(days=30)].monetId)
    wlife = set(life_pay[life_pay >= 1000].index) & recent_old
    whale_entry = {'w90': len(w90), 'w90_in': len(w90 & acc_in_601), 'wlife': len(wlife), 'wlife_in': len(wlife & acc_in_601)}
    # 爬级速度(团队包 E6 ⑤):按进服天数分组看当前等级。「201 级」推测指英雄等级(老服有 200 级英雄),待确认
    P['tenure'] = (E - P.reg).dt.days + 1
    climb = []
    for lo, hi, label in ((1, 2, '1~2 天'), (3, 4, '3~4 天'), (5, 6, '5~6 天'), (7, 99, '7 天以上')):
        x = P[(P.tenure >= lo) & (P.tenure <= hi)]
        xr = x[x.since_last <= 2]
        climb.append({'name': label, 'n': int(len(x)), 'city': med(x.city), 'hero': med(x.hero_lv), 'hero_max': int(x.hero_lv.max()) if x.hero_lv.notna().any() else None,
                      'recent': int(len(xr)), 'city_recent': med(xr.city), 'hero_recent': med(xr.hero_lv)})
    hero_marks = [[t, int((P.hero_lv >= t).sum())] for t in (30, 50, 100, 150, 200)]
    # 主城等级到达(2026-11-04,新手与首日页):当前等级是服务端状态(只知道到没到,不知道哪天到);
    # 注册当天到 Lv3 用签到记录近似(签到时记了主城等级,没签到的人看不到,是下限)
    S0 = pd.DataFrame(m.get('N601_activity signin', []))
    d0lv = {}
    if len(S0):
        S0['d'] = pd.to_datetime(S0.signin_at, format='mixed').dt.normalize()
        S0 = S0.merge(P[['monetId', 'reg']], on='monetId'); S0 = S0[S0.d == S0.reg]
        d0lv = S0.groupby('monetId').government_level.max().to_dict()
    def reach(x):
        sig = [d0lv[m_] for m_ in x.monetId if m_ in d0lv]
        return {'n': int(len(x)), 'lv2': int((x.city >= 2).sum()), 'lv3': int((x.city >= 3).sum()), 'lv5': int((x.city >= 5).sum()),
                'd0_signed': len(sig), 'd0_lv3': int(sum(v >= 3 for v in sig))}
    SRCN = [('fresh', '真新设备'), ('repeat', '同设备重复新号'), ('alt', '老玩家小号'), ('direct', '旧号直接进'), ('noid', '无广告 ID')]
    city_reach = ([{'key': k_, 'name': nm, **reach(P[P.src == k_])} for k_, nm in SRCN if 'src' in P and (P.src == k_).any()]
                  + [{'key': 'all', 'name': '全部', **reach(P)}])
    # 两个 App 合计周付费(总纲 6.2):以内测开始日为周起点,往前 8 周是基线(全是老服);601 部分 = 已到账 + PayerMax 待核实
    weeks = []
    for k_ in range(-8, (E - start).days // 7 + 1):
        a0 = start + pd.Timedelta(days=7 * k_); a1 = min(a0 + pd.Timedelta(days=6), E)
        old_ = float(c.O[(c.O.d >= a0) & (c.O.d <= a1)].price.sum())
        wk = Ok[(Ok.d >= a0) & (Ok.d <= a1)]; n6 = float(wk.price.sum())
        # 2026-11-04(用户需求 5.10):601 拆成确认到账 / 待核实,待核实不并入确认收入
        n6p = float(wk[wk.status == 'paid'].price.sum()) if 'status' in wk else n6
        weeks.append({'from': a0.strftime('%Y-%m-%d'), 'to': a1.strftime('%Y-%m-%d'), 'days': (a1 - a0).days + 1, 'old': r(old_, 2), 'n601': r(n6, 2),
                      'n601_paid': r(n6p, 2), 'n601_other': r(n6 - n6p, 2)})
    base = [w['old'] for w in weeks if w['to'] < N601_START]
    two_app = {'weeks': weeks, 'baseline': r(sum(base) / len(base), 2) if base else None, 'base_weeks': len(base)}
    # 付费
    pay_users = Ok.groupby('monetId').agg(orders=('price', 'size'), usd=('price', 'sum'), first=('t', 'min'), last_pay=('t', 'max'),
                                          channels=('pay_ch', lambda v: '、'.join(sorted(set(v))))).reset_index()
    pay_users = pay_users.merge(P[['monetId', 'name', 'grp', 'reg', 'city', 'act_days', 'last']], on='monetId', how='left')
    payers = [{'id': int(x.monetId), 'name': x['name'], 'grp': x.grp, 'reg': x.reg.strftime('%Y-%m-%d') if pd.notna(x.reg) else None,
               'orders': int(x.orders), 'usd': r(x.usd, 2), 'channels': x.channels, 'first': str(x['first'])[:16], 'last_pay': str(x['last_pay'])[:16],
               'city': int(x.city) if pd.notna(x.city) else None, 'act_days': int(x.act_days) if pd.notna(x.act_days) else None,
               'last_login': x['last'].strftime('%Y-%m-%d %H:%M') if pd.notna(x['last']) else None}
              for _, x in pay_users.sort_values('usd', ascending=False).iterrows()]
    S_ = pd.DataFrame(m.get('N601_activity signin', []))
    if len(S_): S_['t'] = pd.to_datetime(S_.signin_at, format='mixed')
    ORIGIN_NAME = {'whale': '回流大 R', 'payer': '回流付费用户', 'free': '回流免费用户', 'new': '新用户', 'noid': '无法判断'}
    Pi = P.set_index('monetId')
    for p_ in payers:
        mm = p_['id']; reg_ = Pi.reg.get(mm); first_ = pd.Timestamp(p_['first'])
        p_['days_to_first'] = int((first_.normalize() - reg_).days) if reg_ is not None and pd.notna(reg_) else None
        p_['origin'] = ORIGIN_NAME.get(Pi.origin.get(mm)) if 'origin' in Pi else None
        lv = S_[(S_.monetId == mm) & (S_.t <= first_)].government_level.max() if len(S_) else np.nan
        p_['city_at_first'] = int(lv) if pd.notna(lv) else None
    # 点击付费漏斗(2026-10-29):UnityBillingCheckoutV1 每次发起支付一行,只覆盖 Google / Apple 内购(PayerMax 网页不经过);
    # 有 orderKey = 生成订单;到账 = 同一天在 TopUpRecord 有 Google / Apple 已到账订单(2026-11-03 起按支付表状态)。只算内测玩家(已去掉排除名单)
    CK = pd.DataFrame(m.get('N601_checkout', []))
    checkout = None
    if len(CK):
        CK['t'] = pd.to_datetime(CK.created_ms.astype('int64'), unit='ms') + pd.Timedelta(hours=8); CK['d'] = CK.t.dt.normalize()
        CK = CK[(CK.server_id == 601) & CK.monetId.isin(ids) & (CK.d >= start) & (CK.d <= E)]
        store = Ok[Ok.channel.isin(['Google', 'Apple']) & (Ok.status == 'paid')]

        def funnel(ck, st):
            cu = set(ck.monetId); pu = set(st.monetId)
            return {'clicks': int(len(ck)), 'click_users': len(cu), 'order_users': int(ck[ck.has_order == 1].monetId.nunique()),
                    'paid_users': len(cu & pu), 'paid_no_click': len(pu - cu)}
        checkout = {'total': funnel(CK, store), 'last_click': CK.t.max().strftime('%Y-%m-%d %H:%M') if len(CK) else None,
                    'daily': [dict(d=d_.strftime('%Y-%m-%d'), **funnel(CK[CK.d == d_], store[store.d == d_])) for d_ in pd.date_range(start, E)]}
    # 新人前 7 天(2026-10-30,H3「活得开心」代理指标):只算注册满 7 天的人,按来源分组。只给数字,不下结论。
    # 活跃天数用活跃痕迹;主城等级用签到记录(没签到过的人看不到,单列覆盖人数);入联盟只能看到现在还在联盟的人
    first7 = None
    if 'src' in P:
        AL = pd.DataFrame(m.get('N601_alliance members', []))
        if len(AL): AL['t'] = pd.to_datetime(AL.joined_at, format='mixed')
        # 竞技场记录解锁时自动建(积分 1000、最后挑战时间 1900 占位),只算真正打过的
        AR = set(r_['monetId'] for r_ in m.get('N601_arena players', []) if str(r_.get('last_at') or '')[:4] not in ('', '1900'))
        M7 = P[P.reg <= E - pd.Timedelta(days=6)].copy()
        def f7(x):
            if not len(x):
                return None
            reg_ = x.set_index('monetId').reg
            a = Act[Act.monetId.isin(x.monetId)].copy(); a['k'] = (a.d - a.monetId.map(reg_)).dt.days
            days = a[(a.k >= 0) & (a.k <= 6)].groupby('monetId').d.nunique().reindex(x.monetId).fillna(0)
            lv = {}
            for n_ in (1, 3, 7):
                if len(S_):
                    s_ = S_[S_.monetId.isin(x.monetId)]
                    s_ = s_[s_.t < s_.monetId.map(reg_) + pd.Timedelta(days=n_)]
                    g_ = s_.groupby('monetId').government_level.max()
                else:
                    g_ = pd.Series(dtype=float)
                lv[f'lv{n_}'] = {'median': r(float(g_.median()), 1) if len(g_) else None, 'covered': int(len(g_))}
            ally = 0
            if len(AL):
                al_ = AL[AL.monetId.isin(x.monetId)]
                ally = int((al_.t < al_.monetId.map(reg_) + pd.Timedelta(days=7)).sum())
            o_ = Ok[Ok.monetId.isin(x.monetId)]
            fp_ = int((o_.t < o_.monetId.map(reg_) + pd.Timedelta(days=7)).groupby(o_.monetId).any().sum()) if len(o_) else 0
            cnt = o_.groupby('monetId').size()
            return {'n': int(len(x)), 'days_median': r(float(days.median()), 1), 'days_mean': r(float(days.mean()), 2),
                    'days_ge3': int((days >= 3).sum()), **lv, 'ally7': ally, 'arena': int(x.monetId.isin(AR).sum()),
                    'pay7': fp_, 'payers': int(len(cnt)), 'repeat': int((cnt >= 2).sum())}
        SRCN = [('fresh', '真新设备'), ('repeat', '同设备重复新号'), ('alt', '老玩家小号'), ('direct', '旧号直接进'), ('noid', '无广告 ID')]
        first7 = {'upto': (E - pd.Timedelta(days=6)).strftime('%Y-%m-%d'),
                  'rows': [dict(key=k_, name=nm, **(f7(M7[M7.src == k_]) or {'n': 0})) for k_, nm in SRCN] + [dict(key='all', name='全部', **(f7(M7) or {'n': 0}))]}
    Ok['paid_usd'] = Ok.price.where(Ok.status == 'paid', 0.0)
    by_ch = Ok.groupby('pay_ch').agg(orders=('price', 'size'), usd=('price', 'sum'), payers=('monetId', 'nunique'),
                                     paid=('status', lambda v: int((v == 'paid').sum())), paid_usd=('paid_usd', 'sum')).reset_index()
    excluded = O[O.why.notna()].groupby('why').agg(orders=('price', 'size'), usd=('price', 'sum'), users=('monetId', 'nunique')).reset_index()
    E7 = E - pd.Timedelta(days=6)
    a7 = Act[Act.d >= E7]
    kpi = {'players': int(len(P)), 'old': int((P.grp == 'old').sum()), 'new': int((P.grp == 'new').sum()),
           'reg7': int((P.reg >= E7).sum()), 'act_yday': int((Act.d == E).sum()), 'act7': int(a7.monetId.nunique()),
           'act_peak': max((x['act_old'] + x['act_new'] for x in daily), default=0),
           'usd': r(Ok.price.sum(), 2), 'paid_usd': r(Ok.paid_usd.sum(), 2), 'pending_usd': r(Ok.price.sum() - Ok.paid_usd.sum(), 2),
           'paid_orders': int((Ok.status == 'paid').sum()), 'payers': int(Ok.monetId.nunique()), 'orders': int(len(Ok)),
           'pay_rate': r(Ok.monetId.nunique() / len(P)) if len(P) else None}
    # 时间筛选(2026-11-03):新增、活跃、付费、渠道、商品、点击付费漏斗按窗口重算;留存、当前等级、来源等不随窗口变
    win = {}
    for w_ in N6_WINDOWS:
        lo = E - pd.Timedelta(days=w_ - 1)
        o_ = Ok[Ok.d >= lo]; a_ = Act[Act.d >= lo]; p_ = P[P.reg >= lo]
        bc = o_.groupby('pay_ch').agg(orders=('price', 'size'), usd=('price', 'sum'), payers=('monetId', 'nunique'),
                                      paid=('status', lambda v: int((v == 'paid').sum())), paid_usd=('paid_usd', 'sum')).reset_index()
        win[str(w_)] = {'from': lo.strftime('%Y-%m-%d'), 'reg': int(len(p_)), 'reg_old': int((p_.grp == 'old').sum()),
                        'act': int(a_.monetId.nunique()), 'act_old': int(a_[a_.grp == 'old'].monetId.nunique()),
                        'payers': int(o_.monetId.nunique()), 'orders': int(len(o_)), 'usd': r(o_.price.sum(), 2), 'paid_usd': r(o_.paid_usd.sum(), 2),
                        'pending_usd': r(o_.price.sum() - o_.paid_usd.sum(), 2),
                        'by_channel': [{'ch': x.pay_ch, 'orders': int(x.orders), 'usd': r(x.usd, 2), 'payers': int(x.payers), 'paid': int(x.paid), 'paid_usd': r(x.paid_usd, 2)} for _, x in bc.sort_values('usd', ascending=False).iterrows()],
                        'products': [{'name': k_, 'orders': int(len(v)), 'payers': int(v.monetId.nunique()), 'usd': r(v.price.sum(), 2)} for k_, v in sorted(o_.groupby('product'), key=lambda kv: -kv[1].price.sum())],
                        'checkout': funnel(CK[CK.d >= lo], store[store.d >= lo]) if checkout else None}
    return {'start': N601_START, 'end': E.strftime('%Y-%m-%d'), 'win': win, 'kpi': kpi, 'daily': daily, 'retention': retention, 'cohorts': cohorts,
            'progress': progress, 'levels': levels, 'gameplay': gameplay, 'migration': migration, 'device_groups': device_groups, 'origin': origin_rows, 'whale_entry': whale_entry, 'climb': climb,
            'hero_marks': hero_marks, 'two_app': two_app, 'guide': guide, 'city_reach': city_reach,
            'achievements': achievements, 'activities': activities, 'products': products, 'gift_intent': gift_intent, 'payers': payers, 'checkout': checkout,
            'by_channel': [{'ch': x.pay_ch, 'orders': int(x.orders), 'usd': r(x.usd, 2), 'payers': int(x.payers), 'paid': int(x.paid), 'paid_usd': r(x.paid_usd, 2)} for _, x in by_ch.sort_values('usd', ascending=False).iterrows()],
            'excluded': [{'why': x.why, 'orders': int(x.orders), 'usd': r(x.usd, 2), 'users': int(x.users)} for _, x in excluded.iterrows()],
            'excluded_players': {'before_start': before, 'test': tests},
            'test_ids': sorted(N601_TEST_IDS), 'suspects': suspects, 'exclusions_error': excl_err,
            'act_before_reg': act_before_reg, 'cohort_q': cohort_q, 'first7': first7}


# ---------------------------------------------------------------- 601 客户端埋点 + 全链路(2026-11-03,601 看板第一期)
# 埋点来自 Redshift ods.invader_events(卡 N601_client events),只有同意采集的玩家才上报,人数是下限。
# 日期 = 服务器收件时间 server_time(UTC)+ 8 小时;手机时间有误差不用。登录前的事件 user_id = 0,只能按安装(install_md5)看;
# 安装 ID 每次安装都会变,同一台手机重装算两个。测试号按统一排除名单去掉(安装里出现过测试号的整条安装去掉)。
N6_STAGES = [('resources', '资源准备'), ('account_version', '账号 / 版本检查'), ('connection', '连接游戏服'), ('city_initialization', '主城初始化')]
N6_SCREEN = {'city': '主城', 'world': '世界地图', 'battle': '战斗'}
N6_TIER = {'low': '低档机', 'medium': '中档机', 'high': '高档机', 'unknown': '未知'}
N6_FPS = [('lt_20', '< 20'), ('20_29', '20–29'), ('30_44', '30–44'), ('45_59', '45–59'), ('gte_60', '≥ 60')]
N6_MODE = {2: '侵略', 3: '竞技场', 4: '侵略防守', 5: '反抗', 6: '普通战斗', 7: '剧本', 10: '世界 BOSS', 11: '新手 NPC', 12: '新手副本',
           13: '英雄竞技场', 14: '联盟副本', 15: '无头骑士', 16: '副本 2', 17: '第二侵略', 19: '联盟战', 20: '英雄荣耀', 21: '副本 3',
           22: '副本 4', 23: '全服挑战', 24: '驻城战斗', 25: '守城布阵'}
N6_BTYPE = {1: '金矿', 2: '金币仓库', 3: '水晶矿', 4: '水晶仓库', 5: '主城', 6: '兵营', 7: '营地', 8: '实验室', 9: '联盟建筑', 10: '铁匠铺',
            11: '英雄祭坛', 12: '抽奖建筑', 13: '星石矿(法力神殿)', 15: '雇佣兵营', 16: '兽园'}
N6_DONE = {'free': '免费立即完成', 'natural': '自然计时完成', 'diamond': '花钻石', 'card': '加速卡', 'manual': '内部手动'}
N6_TAB = {0: '建筑', 1: '装备', 2: '杂项', 3: '钻石', 4: '限时礼包'}
N6_ENTRY = {'shop': '商店按钮', 'homepage': '首页', 'lackOfDiamonds': '钻石不足弹窗', 'vipInfoPage': 'VIP 页', 'buyGoldButton': '买金币按钮', 'CasionNew': 'Casino'}
N6_PLACE = {'shop_diamonds': '商店钻石商品', 'shop_limit_gifts': '商店限时礼包'}
N6_REQ = {'login2': '账号登录', 'city_initialization': '主城初始化', 'payment': '支付', 'reward': '充值领奖'}
N6_ERR = {'transport': '网络传输', 'unknown': '未知', 'timeout': '超时', 'rejected': '服务器拒绝', 'terminal_session': '会话终止'}


def n6_paid_users(m, ids):
    """有 Google / Apple 已到账订单的内测玩家数(到账判断同 n601 的 order_status)。"""
    ok = {str(x['order_id']) for x in m.get('N601_order status', [])
          if x['environment'] != 'sandbox' and not x['store_test'] and x['money_state'] != 'REFUNDED' and x['rewards_done']
          and (x['money_state'] == 'PROCESSED' or (x['channel'] == 'apple' and x['environment'] == 'production'))}
    return len({o['monetId'] for o in m.get('N601_orders', []) if str(o['order_id']) in ok} & ids)


def n601_client(c, N, w=None, seg=None):
    m = c.raw
    E_ = pd.DataFrame(m.get('N601_client events', []))
    if not len(E_) or not N:
        return None
    E = c.end
    ex, _, _ = load_exclusions('n601')
    P = pd.DataFrame(m.get('N601_players detail', []))
    P['reg'] = pd.to_datetime(P.created_at, format='mixed').dt.normalize()
    P = P[(P.reg >= pd.Timestamp(N601_START)) & (P.reg <= E) & ~P.monetId.isin(ex)]
    if seg:   # 平台 / 版本按事件本身的字段筛;国家按「这个安装登录过的号属于该国家」筛
        P = P[P.monetId.isin(seg[2])]
    ids = set(P.monetId)
    # 2026-11-04:按 event_uuid 去重(数仓链路不去重;B72 之前的版本没有 uuid,这部分保留原样,不能精确去重)
    uuid_rows = no_uuid_rows = dup_rows = None
    if 'event_uuid' in E_:
        hu = E_.event_uuid.notna() & (E_.event_uuid.astype(str) != '')
        uuid_rows, no_uuid_rows = int(hu.sum()), int((~hu).sum())
        dup_rows = uuid_rows - int(E_.loc[hu, 'event_uuid'].nunique())
        E_ = pd.concat([E_[hu].drop_duplicates('event_uuid'), E_[~hu]], ignore_index=True)
    E_['t'] = pd.to_datetime(E_.server_time, format='mixed') + pd.Timedelta(hours=8)
    if seg and seg[0] == 'p':
        E_ = E_[E_.platform == {'Android': 1, 'iOS': 2}[seg[1]]]
    elif seg and seg[0] == 'v':
        E_ = E_[E_.client_version == seg[1]]
    elif seg and seg[0] == 'c':
        E_ = E_[E_.install_md5.isin(set(E_[E_.user_id.isin(ids)].install_md5))]
    E_['d'] = E_.t.dt.normalize()
    bad = set(E_[E_.user_id.isin(ex)].install_md5)
    raw_rows = len(E_)
    E_ = E_[~E_.install_md5.isin(bad) & (E_.d <= E)]
    E_all = E_   # 时间筛选前的全量(留存双轨要看全部注册日)
    wlo = E - pd.Timedelta(days=w - 1) if w else pd.Timestamp('2000-01-01')   # 时间筛选:近 w 天
    E_ = E_[E_.d >= wlo]
    if not len(E_):
        return None
    U = E_[E_.user_id.isin(ids)]
    ev = lambda name: E_[E_.event_name == name]
    # 获客来源(2026-11-04,用户确认):B72 起 session_start 首次启动带 install_referrer(Google Play 安装来源原文)。
    # 按安装取最早一条,原文只在这里归成类别,不进页面;安装后登录过的内测玩家算「成为 601 角色」。只覆盖同意采集的玩家,是下限。
    acq = None
    if 'install_referrer' in E_:
        def ref_src(x):
            x = str(x).lower()
            if 'facebook' in x: return 'Facebook'
            if 'instagram' in x: return 'Instagram'
            if 'organic' in x or 'google-play' in x: return '自然量'
            if 'not%20set' in x or 'not set' in x: return '未设置'
            return '其他'
        SS_ = E_[E_.event_name == 'invader_session_start']
        R_ = SS_[SS_.install_referrer.notna() & (SS_.install_referrer.astype(str) != '')].sort_values('t').drop_duplicates('install_md5')
        if len(R_):
            R_ = R_.assign(src=R_.install_referrer.map(ref_src))
            inst_user = E_[E_.user_id.isin(ids)].groupby('install_md5').user_id.first()
            R_['user'] = R_.install_md5.map(inst_user)
            SRCS = ['Facebook', 'Instagram', '自然量', '未设置', '其他']
            b72 = SS_[SS_.client_version >= '2.4.0053']
            acq = {'srcs': SRCS, 'from': R_.d.min().strftime('%Y-%m-%d'),
                   'total': [{'src': s_, 'installs': int((R_.src == s_).sum()), 'roles': int(R_[R_.src == s_].user.nunique())} for s_ in SRCS],
                   'daily': [{'d': d_.strftime('%Y-%m-%d'), **{s_: int(((R_.d == d_) & (R_.src == s_)).sum()) for s_ in SRCS}} for d_ in pd.date_range(R_.d.min(), E)],
                   'b72_installs': int(b72.install_md5.nunique()), 'with_ref': int(len(R_))}
    q = lambda s, p: r(float(s.quantile(p)), 1) if len(s) else None
    d0 = E_.d.min()
    days = pd.date_range(d0, E)
    act = {x['d']: x['act_old'] + x['act_new'] for x in N['daily']}
    # 覆盖率:每天埋点里出现的内测玩家 vs 看板活跃(活跃痕迹)
    cov = [{'d': d_.strftime('%Y-%m-%d'), 'ev_users': int(U[U.d == d_].user_id.nunique()), 'act': act.get(d_.strftime('%Y-%m-%d')),
            'installs': int(E_[E_.d == d_].install_md5.nunique())} for d_ in days]
    # 启动漏斗(按安装):各阶段完成 → 登录成功;失败阶段和错误
    st = ev('invader_startup_stage_completed'); ready = ev('invader_login_ready'); fail = ev('invader_startup_failed')
    def sfun(x_st, x_ready, x_fail):
        o = {k: int(x_st[x_st.stage == k].install_md5.nunique()) for k, _ in N6_STAGES}
        o['ready'] = int(x_ready.install_md5.nunique()); o['failed'] = int(x_fail.install_md5.nunique())
        o['failed_never_ready'] = int(len(set(x_fail.install_md5) - set(x_ready.install_md5)))
        return o
    startup = {'total': sfun(st, ready, fail),
               'daily': [dict(d=d_.strftime('%Y-%m-%d'), **sfun(st[st.d == d_], ready[ready.d == d_], fail[fail.d == d_])) for d_ in days],
               'stage_ms': [{'stage': nm, 'n': int((st.stage == k).sum()), 'p50': q(st[st.stage == k].duration_ms, .5), 'p90': q(st[st.stage == k].duration_ms, .9)} for k, nm in N6_STAGES],
               'fail': [{'stage': dict(N6_STAGES).get(k[0], k[0]), 'err': N6_ERR.get(k[1], k[1]), 'n': int(v), 'installs': int(fail[(fail.stage == k[0]) & (fail.safe_error_code == k[1])].install_md5.nunique())}
                        for k, v in fail.groupby(['stage', 'safe_error_code']).size().sort_values(ascending=False).items()],
               'network': {str(k): int(v) for k, v in fail.network_type.value_counts().items()}}
    vers = []
    for v_, g in E_.groupby('client_version'):
        s_ = set(g[g.event_name == 'invader_startup_stage_completed'].install_md5) | set(g[g.event_name == 'invader_startup_failed'].install_md5)
        rd = set(g[g.event_name == 'invader_login_ready'].install_md5)
        vers.append({'v': v_, 'installs': int(g.install_md5.nunique()), 'started': len(s_), 'ready': len(rd & s_) if s_ else len(rd),
                     'users': int(g[g.user_id.isin(ids)].user_id.nunique()), 'first': g.d.min().strftime('%m-%d'), 'last': g.d.max().strftime('%m-%d')})
    vers.sort(key=lambda x: x['v'], reverse=True)
    # 会话:单次活跃时长、每人每天合计、每天会话数;24 小时分布(中国时间)
    ss = ev('invader_session_summary'); su = ss[ss.user_id.isin(ids)]
    pud = su.groupby(['user_id', 'd']).agg(sec=('active_seconds', 'sum'), n=('sid', 'nunique')).reset_index()
    bins = [0, 30, 60, 180, 600, 1800, 1e9]; lab = ['< 30 秒', '30 秒–1 分钟', '1–3 分钟', '3–10 分钟', '10–30 分钟', '≥ 30 分钟']
    # 单次会话只算登录后的(内测玩家);登录前的片段 user_id = 0,多为几秒的启动过程
    sess = {'n': int(len(su)), 'p50': q(su.active_seconds, .5), 'p75': q(su.active_seconds, .75), 'p90': q(su.active_seconds, .9),
            'dist': [[l_, int(v)] for l_, v in zip(lab, pd.cut(su.active_seconds, bins, right=False, labels=lab).value_counts().reindex(lab).fillna(0))],
            'user_day': {'n': int(len(pud)), 'min_p50': q(pud.sec / 60, .5), 'min_p75': q(pud.sec / 60, .75), 'min_p90': q(pud.sec / 60, .9), 'sess_p50': q(pud.n, .5)},
            'daily': [{'d': d_.strftime('%Y-%m-%d'), 'users': int((pud.d == d_).sum()), 'min_p50': q(pud[pud.d == d_].sec / 60, .5), 'min_mean': r(float((pud[pud.d == d_].sec / 60).mean()), 1) if (pud.d == d_).any() else None,
                       'sess': int(su[su.d == d_].sid.nunique())} for d_ in days],
            'end_reason': {str(k): int(v) for k, v in su.end_reason.value_counts().items()}}
    hr = U.assign(h=U.t.dt.hour).groupby('h').agg(users=('user_id', 'nunique'), ev=('event_name', 'size')).reindex(range(24), fill_value=0)
    sess['hours'] = [[int(h), int(x.users), int(x.ev)] for h, x in hr.iterrows()]
    # 首日:注册当天的会话时长 → 次日是否还有活跃痕迹(相关,不是因果)
    reg = P.set_index('monetId').reg
    first = pud.assign(reg=pud.user_id.map(reg)); first = first[first.d == first.reg]
    acts_raw = m.get('N601_activity tasks day', [])
    # 次日回来 = 次日有埋点或每日任务记录(比看板 D1 的活跃痕迹窄一些)
    nxt = set(zip(U.user_id, U.d)) | {(a['monetId'], pd.Timestamp(str(a['day'])[:10])) for a in acts_raw}
    fd = []
    for lo, hi, nm in ((0, 3, '< 3 分钟'), (3, 10, '3–10 分钟'), (10, 30, '10–30 分钟'), (30, 1e9, '≥ 30 分钟')):
        g = first[(first.sec / 60 >= lo) & (first.sec / 60 < hi) & (first.reg + pd.Timedelta(days=1) <= E)]
        k = sum((u_, r_ + pd.Timedelta(days=1)) in nxt for u_, r_ in zip(g.user_id, g.reg))
        fd.append({'name': nm, 'n': int(len(g)), 'd1': int(k)})
    # 加载耗时、战斗帧率
    ld = ev('invader_screen_load_summary')
    loads = [{'screen': N6_SCREEN.get(s_, s_), 'tier': N6_TIER.get(t_, t_), 'n': int(len(g)), 'p50': q(g.duration_ms / 1000, .5), 'p90': q(g.duration_ms / 1000, .9)}
             for (s_, t_), g in ld.groupby(['screen_id', 'device_tier'])] + \
            [{'screen': N6_SCREEN.get(s_, s_), 'tier': '全部', 'n': int(len(g)), 'p50': q(g.duration_ms / 1000, .5), 'p90': q(g.duration_ms / 1000, .9)} for s_, g in ld.groupby('screen_id')]
    bp = ev('invader_battle_performance_summary')
    def fps_row(g, name):
        vc = g.fps_bucket.value_counts()
        return {'name': name, 'n': int(len(g)), 'b': [int(vc.get(k, 0)) for k, _ in N6_FPS], 'stall_p50': q(g.stall_count, .5), 'stall_p90': q(g.stall_count, .9)}
    fps = {'labels': [l_ for _, l_ in N6_FPS],
           'by_mode': sorted([fps_row(g, N6_MODE.get(int(k), str(k))) for k, g in bp.groupby('mode_id')], key=lambda x: -x['n']),
           'by_tier': [fps_row(g, N6_TIER.get(k, k)) for k, g in bp.groupby('device_tier')], 'all': fps_row(bp, '全部')}
    cr = ev('invader_critical_request_failed')
    reqfail = {'by': [{'stage': N6_REQ.get(k[0], k[0]), 'err': N6_ERR.get(k[1], k[1]), 'n': int(v), 'users': int(cr[(cr.stage == k[0]) & (cr.safe_error_code == k[1])].install_md5.nunique())}
                      for k, v in cr.groupby(['stage', 'safe_error_code']).size().sort_values(ascending=False).items()],
               'daily': [{'d': d_.strftime('%Y-%m-%d'), **{N6_REQ.get(s_, s_): int(((cr.d == d_) & (cr.stage == s_)).sum()) for s_ in N6_REQ}} for d_ in days]}
    exc = ev('invader_client_exception_summary'); bi = ev('invader_battle_interrupted')
    # 建筑升级、资源不足
    bu = ev('invader_building_upgrade_completed')
    build = {'n': int(len(bu)), 'users': int(bu[bu.user_id.isin(ids)].user_id.nunique()),
             'method': [[N6_DONE.get(k, k), int(v)] for k, v in bu.completion_method.value_counts().items()],
             'by_type': [{'name': N6_BTYPE.get(int(k), str(k)), 'n': int(len(g)), **{N6_DONE.get(mm, mm): int((g.completion_method == mm).sum()) for mm in N6_DONE}}
                         for k, g in sorted(bu.groupby('building_type'), key=lambda kv: -len(kv[1]))],
             'daily': [{'d': d_.strftime('%Y-%m-%d'), 'n': int((bu.d == d_).sum()), 'users': int(bu[bu.d == d_].user_id.nunique())} for d_ in days],
             'blocked': int(len(ev('invader_building_upgrade_blocked'))),
             'shortage': [[str(k), int(v)] for k, v in ev('invader_growth_resource_shortage').growth_system.value_counts().items()]}
    # 商店
    so = ev('invader_shop_open'); oi = ev('invader_offer_impression')
    shop = {'opens': int(len(so)), 'users': int(so[so.user_id.isin(ids)].user_id.nunique()),
            'entry': [[N6_ENTRY.get(k, k), int(v)] for k, v in so.entry.value_counts().items()],
            'tab': [[N6_TAB.get(int(k), str(k)), int(v)] for k, v in so.tab.value_counts().items()],
            'impr': [[N6_PLACE.get(k, k), int(v), int(oi[oi.placement == k].user_id.nunique())] for k, v in oi.placement.value_counts().items()],
            'daily': [{'d': d_.strftime('%Y-%m-%d'), 'open_users': int(so[(so.d == d_) & so.user_id.isin(ids)].user_id.nunique()), 'opens': int((so.d == d_).sum()),
                       'ev_users': int(U[U.d == d_].user_id.nunique())} for d_ in days]}
    # 付费链路(同一批玩家:埋点上报过的内测玩家,埋点开始以后)
    since = d0
    CK = pd.DataFrame(m.get('N601_checkout', []))
    ck_users = set()
    if len(CK):
        CK['t'] = pd.to_datetime(CK.created_ms.astype('int64'), unit='ms') + pd.Timedelta(hours=8)
        ck_users = set(CK[(CK.server_id == 601) & (CK.t >= since) & (CK.t < E + pd.Timedelta(days=1))].monetId)
    O = pd.DataFrame(m.get('N601_orders', []))
    paid_users = set()
    if len(O):
        O['t'] = pd.to_datetime(O.created_at, format='mixed')
        paid_users = set(O[(O.t >= since) & (O.t < E + pd.Timedelta(days=1))].monetId)
    base = set(U.user_id)
    pay_chain = {'since': since.strftime('%Y-%m-%d'), 'steps': [
        ['埋点里出现过的内测玩家', len(base)], ['打开过商店', len(base & set(so.user_id))], ['看到过商品', len(base & set(oi.user_id))],
        ['发起过 Google / Apple 支付', len(base & ck_users)], ['有订单(含 PayerMax)', len(base & paid_users)]]}
    # 全链路(玩家口径,内测开始以来;埋点那几步只算上报过的人,是下限)
    gd = pd.DataFrame(m.get('N601_guide', []))
    g299 = 0
    if len(gd):
        gd = gd[gd.monetId.isin(ids)]
        g299 = int(gd.guides.map(lambda x: 299 in (json.loads(x) if isinstance(x, str) else (x or []))).sum())
    pb = pd.DataFrame(m.get('N601_progress building', []))
    c3 = int(pb[pb.monetId.isin(ids) & (pb.building_type == 5) & (pb.max_level >= 3)].monetId.nunique()) if len(pb) else 0
    R1 = N['retention']['all']['d1']; R7 = N['retention']['all']['d7']
    k = N['kpi']
    chain = {'installs': [['资源准备完成', startup['total']['resources']], ['账号 / 版本检查通过', startup['total']['account_version']],
                          ['连接游戏服', startup['total']['connection']], ['主城初始化完成', startup['total']['city_initialization']], ['登录成功', startup['total']['ready']]],
             'players': [{'name': '建角色(内测玩家)', 'n': len(ids), 'src': '601 库'},
                         {'name': '完成新手主线(步骤 299)', 'n': g299, 'src': '601 库'},
                         {'name': '主城到 3 级(入侵解锁)', 'n': c3, 'src': '601 库'},
                         {'name': '次日回来(D1)', 'n': R1['n'], 'base': R1['base'], 'src': '活跃痕迹,只算满 1 天的'},
                         {'name': '第 7 天回来(D7)', 'n': R7['n'], 'base': R7['base'], 'src': '活跃痕迹,只算满 7 天的'},
                         {'name': '打开过商店', 'n': int(len(ids & set(so.user_id))), 'src': '埋点,下限'},
                         {'name': '发起过 Google / Apple 支付', 'n': int(len(ids & (set(CK[CK.server_id == 601].monetId) if len(CK) else set()))), 'src': '支付表'},
                         {'name': '付费(含 PayerMax 待核实)', 'n': k['payers'], 'src': '订单表'},
                         {'name': '其中有已到账订单(Google / Apple)', 'n': n6_paid_users(m, ids), 'src': '订单表 + New Era 支付表'}],
             'pending': ['首次打开(E002 entry,B72 起有数据)', '引导每一步(E023 step_id,B72 起有数据)', '发起购买(E126,未发版)', '支付结果(E127,未发版)']}   # 2026-11-04 按 11-03 定稿编号更正(原写 E126 / E130 / E128 是重编号前的)
    # 钻石存量、小游戏
    DS = pd.DataFrame(m.get('N601_diamond stock', []))
    dia = None
    if len(DS):
        DS = DS[DS.monetId.isin(ids)]; v = DS.diamonds.astype(float)
        bb = [0, 1, 50, 200, 1000, 5000, 1e12]; bl = ['0', '1–49', '50–199', '200–999', '1,000–4,999', '≥ 5,000']
        dia = {'n': int(len(DS)), 'p50': q(v, .5), 'p90': q(v, .9), 'max': r(float(v.max()), 0), 'total': r(float(v.sum()), 0),
               'dist': [[l_, int(x)] for l_, x in zip(bl, pd.cut(v, bb, right=False, labels=bl).value_counts().reindex(bl).fillna(0))]}
    def mg(df, used_col, used_val, bet, rew):
        if not len(df):
            return None
        g0 = max(pd.Timestamp(N601_START), wlo)
        df = df.copy(); df['t'] = pd.to_datetime(df.created_at, format='mixed'); df = df[df.monetId.isin(ids) & (df.t >= g0) & (df.t < E + pd.Timedelta(days=1))]
        dd = df[df[used_col] == used_val]
        return {'users': int(df.monetId.nunique()), 'rounds': int(len(df)), 'dia_rounds': int(len(dd)), 'dia_users': int(dd.monetId.nunique()),
                'ticket_rounds': int(len(df) - len(dd)), 'bet': r(float(bet(dd)), 0), 'reward': r(float(rew(dd)), 0),
                'per_user_p50': q(df.groupby('monetId').size(), .5), 'per_user_max': int(df.groupby('monetId').size().max()) if len(df) else 0,
                'daily': [{'d': d_.strftime('%Y-%m-%d'), 'users': int(df[df.t.dt.normalize() == d_].monetId.nunique()), 'rounds': int((df.t.dt.normalize() == d_).sum())}
                          for d_ in pd.date_range(g0, E)]}
    PQ = pd.DataFrame(m.get('N601_minigame petquiz', []))
    SL = pd.DataFrame(m.get('N601_minigame slot', []))
    def slot_rew(dd):
        tot = 0
        for s_ in dd.rewards:
            try:
                tot += sum(int(x[1]) for x in json.loads(s_ or '[]') if int(x[0]) == 3)
            except Exception:
                pass
        return tot
    games = {'petquiz': mg(PQ, 'used_diamond', 1, lambda d: d.bet.astype(float).sum(), lambda d: d.reward_diamonds.astype(float).sum()),
             'slot': mg(SL, 'used_ticket', 0, lambda d: d.bet_base.astype(float).sum(), slot_rew)}
    # 留存双轨(2026-11-04,用户需求 5.4):埋点会话口径 = 当天有 session_start 或 login_ready 且带玩家 ID;只覆盖同意采集的玩家。
    # 可观测队列 = 注册当天就有埋点的内测玩家;同一批人再用代理口径(活跃痕迹)算一次,两者并列,不互相替代
    dual = None
    act_p, regs = getattr(c, 'n601_act', None), getattr(c, 'n601_reg', None)
    if act_p is not None and regs and not seg:
        SE = E_all[E_all.event_name.isin(['invader_session_start', 'invader_login_ready']) & E_all.user_id.isin(ids)]
        ses = set(zip(SE.user_id, SE.d))
        obs = sorted({u for u, d_ in ses if regs.get(u) is not None and d_ == regs.get(u)})
        rows_ = []
        for n_ in (1, 3, 7):
            base_ = [u for u in obs if regs[u] + pd.Timedelta(days=n_) <= E]
            hit = lambda S: sum((u, regs[u] + pd.Timedelta(days=n_)) in S for u in base_)
            k_s, k_p = hit(ses), hit(act_p)
            rows_.append({'n': n_, 'base': len(base_), 'session': k_s, 'proxy': k_p, 'ci_s': wilson(k_s, len(base_)), 'ci_p': wilson(k_p, len(base_)),
                          'either': sum(((u, regs[u] + pd.Timedelta(days=n_)) in ses) or ((u, regs[u] + pd.Timedelta(days=n_)) in act_p) for u in base_)})
        dual = {'obs': len(obs), 'from': SE.d.min().strftime('%Y-%m-%d') if len(SE) else None, 'rows': rows_}
    # 引导步骤(2026-11-04):B72 起 E023 带 step_id;没有顺序定义表,只按编号列出人数,不当漏斗
    steps = None
    T23 = E_[(E_.event_name == 'invader_tutorial_step_completed') & E_.user_id.isin(ids)] if 'step_id' in E_ else E_.iloc[0:0]
    T23 = T23[T23.step_id.notna()] if len(T23) else T23
    if len(T23):
        steps = {'users': int(T23.user_id.nunique()), 'from': T23.d.min().strftime('%Y-%m-%d'),
                 'rows': [[int(k_), int(v)] for k_, v in T23.groupby('step_id').user_id.nunique().sort_index().items()]}
    # 数据质量
    lr = ready
    dq = {'raw_rows': raw_rows, 'rows': int(len(E_)), 'from': d0.strftime('%Y-%m-%d'), 'last_at': E_.t.max().strftime('%Y-%m-%d %H:%M'),
          'users': int(U.user_id.nunique()), 'installs': int(E_.install_md5.nunique()), 'anon_share': r(float((E_.user_id == 0).mean()), 3),
          'test_installs': len(bad), 'events': [[k_, int(v)] for k_, v in E_.event_name.value_counts().items()],
          'platform': {('安卓' if k_ == 1 else 'iOS' if k_ == 2 else '未知'): int(v) for k_, v in E_.platform.value_counts().items()},
          'existing_null': r(float(lr.is_existing_account.isna().mean()), 3) if len(lr) else None,
          'guide_ids': sorted(int(x) for x in ev('invader_tutorial_step_completed').guide_id.dropna().unique()),
          'login_methods': {str(k_): int(v) for k_, v in lr.login_method.value_counts().items()},
          'uuid_rows': uuid_rows, 'no_uuid_rows': no_uuid_rows, 'dup_rows': dup_rows}
    # 主城等级按天(旧后台每日快照,含测试号和内测前角色)
    PH = pd.DataFrame(m.get('N601_portal palace daily', []))
    palace = None
    if len(PH):
        PH = PH[pd.to_datetime(PH.date) >= wlo]
    if len(PH):
        PH['band'] = pd.cut(PH.city, [0, 1, 2, 5, 10, 99], labels=['1 级', '2 级', '3–5 级', '6–10 级', '11 级以上'])
        tb = PH.pivot_table(index='date', columns='band', values='players', aggfunc='sum', observed=False).fillna(0).sort_index()
        palace = {'bands': [str(x) for x in tb.columns], 'rows': [[str(d_)[:10]] + [int(v) for v in row] for d_, row in tb.iterrows()]}
    return {'palace_hist': palace, 'coverage': cov, 'startup': startup, 'versions': vers, 'sessions': sess, 'first_day': fd, 'loads': loads, 'fps': fps,
            'reqfail': reqfail, 'exceptions': [[str(k_), int(v)] for k_, v in exc.component.value_counts().items()], 'interrupted': int(len(bi)),
            'build': build, 'shop': shop, 'pay_chain': pay_chain, 'chain': chain, 'diamonds': dia, 'games': games, 'dq': dq, 'acq': acq,
            'ret_dual': dual, 'steps': steps}


def n601_segments(c):
    """601 每个内测玩家的平台、版本、国家(2026-11-04)。
    平台:埋点最近一条的平台 > 角色表客户端类型(googleClient / iosClient)> 账号建号系统;
    版本:角色表最后一次登录的版本 > 埋点最近一条的版本;国家:账号注册 IP 查本地 IP 分配表(fetch_db 已换成国家码)。"""
    m = c.raw
    P = pd.DataFrame(m.get('N601_players detail', []))
    ex, _, _ = load_exclusions('n601')
    P['reg'] = pd.to_datetime(P.created_at, format='mixed').dt.normalize()
    P = P[(P.reg >= pd.Timestamp(N601_START)) & (P.reg <= c.end) & ~P.monetId.isin(ex)].set_index('monetId')
    E_ = pd.DataFrame(m.get('N601_client events', []))
    ev_pl, ev_ver = {}, {}
    if len(E_):
        E_ = E_[E_.user_id.isin(P.index)].sort_values('server_time')
        ev_pl = E_.dropna(subset=['platform']).groupby('user_id').platform.last().map({1: 'Android', 2: 'iOS'}).dropna().to_dict()
        ev_ver = E_.dropna(subset=['client_version']).groupby('user_id').client_version.last().to_dict()
    A = pd.DataFrame(m.get('N601_accounts', []))
    A = A.drop_duplicates('monetId').set_index('monetId') if len(A) else pd.DataFrame(columns=['sys_type', 'country'])
    rows = []
    for mid, x in P.iterrows():
        st = str(A.sys_type.get(mid) or '').lower()
        pl = ev_pl.get(mid) or {'googleClient': 'Android', 'iosClient': 'iOS'}.get(x.client_type) or ('iOS' if st.startswith('ios') else 'Android' if st.startswith('android') else '未知')
        ver = x.client_version if isinstance(x.client_version, str) and x.client_version else ev_ver.get(mid) or '未知'
        cc = A.country.get(mid) if 'country' in A else None
        rows.append({'monetId': mid, 'plat': pl, 'ver': ver, 'country': cc if isinstance(cc, str) and cc else '未知'})
    return pd.DataFrame(rows)


N6_SEG_MIN = 10   # 版本 / 国家:内测玩家 ≥ 10 人才单独给一个筛选项


def n601_by_segment(c, errors):
    G = n601_segments(c)
    segs = {'p:' + v: ('p', v) for v in ('Android', 'iOS') if (G.plat == v).any()}
    segs.update({'v:' + v: ('v', v) for v, n in G.ver.value_counts().items() if n >= N6_SEG_MIN and v != '未知'})
    segs.update({'c:' + v: ('c', v) for v, n in G.country.value_counts().items() if n >= N6_SEG_MIN and v != '未知'})
    col = {'p': 'plat', 'v': 'ver', 'c': 'country'}
    out = {}
    for key, (k, v) in segs.items():
        ids = set(G[G[col[k]] == v].monetId)
        N = safe(lambda: n601(c, only=ids), errors, f'n601_seg_{key}')
        if not N:
            continue
        out[key] = {'n': len(ids), 'n601': N,
                    'ev': {str(w_): safe(lambda w_=w_: n601_client(c, N, w_, seg=(k, v, ids)), errors, f'n601_ev_{key}_{w_}') for w_ in N6_WINDOWS}}
    counts = {'plat': {str(a): int(b) for a, b in G.plat.value_counts().items()}, 'ver': {str(a): int(b) for a, b in G.ver.value_counts().items()},
              'country': {str(a): int(b) for a, b in G.country.value_counts().items()}}
    return {'segs': out, 'counts': counts}


# ---------------------------------------------------------------- 数据自洽检查(2026-10-28)
# 每条:status = pass(通过)/ warn(需核对)/ na(缺数据,无法判断)。只用已抓到的数据,不另查库。
# 规则来源:《Invader AI 看板数据需求》第 3.1 节「错误」类。阈值是第一版,跑两周后按误报调整。
CHECK_FRESH_CARDS = [('Login_user day', 'dateCN', '老服登录'), ('Revenue_orders', 'created_at', '老服订单'),
                     ('NewUser_accounts', 'create_date', '新注册账号'), ('Diamond_flow daily', 'dateCN', '钻石流水'),
                     ('Gameplay_participation day', 'dateCN', '玩法参与'), ('PvP_battle day', 'dateCN', 'PvP 战斗'),
                     ('PvE_dungeon day', 'dateCN', '副本'), ('Alliance_contrib day', 'dateCN', '联盟贡献'),
                     ('N601_activity tasks day', 'day', '601 每日任务')]
CHECK_FARM_MIN_REGS = 50      # 近 28 天单一机型注册 ≥ 50
CHECK_FARM_MAX_ENTRY = 0.10   # 且当天进入游戏率 < 10%,判为疑似刷量机型
CHECK_BATCH_GAP_MIN = 3       # 601:相邻注册间隔 ≤ 3 分钟
CHECK_BATCH_MIN_RUN = 5       # 且连续 ≥ 5 个,判为疑似批量号


def consistency_checks(c, DATA):
    out = []
    def add(group, name, rule, status, value, detail=''):
        out.append({'group': group, 'name': name, 'rule': rule, 'status': status, 'value': value, 'detail': detail})
    E = c.end; m = c.raw
    # 1 数据新鲜度
    stale, seen = [], []
    for card, col, label in CHECK_FRESH_CARDS:
        df = pd.DataFrame(m.get(card, []))
        if not len(df) or col not in df:
            stale.append(f'{label}(无数据)'); continue
        mx = pd.to_datetime(df[col], format='mixed', errors='coerce').max().normalize()
        seen.append(label)
        if mx < E:
            stale.append(f'{label}(最新 {mx:%m-%d})')
    add('数据', '数据新鲜度', f'各表最新日期都应到数据截至日 {E:%m-%d}', 'warn' if stale else 'pass',
        f'{len(seen) - len([s_ for s_ in stale if "无数据" not in s_])}/{len(CHECK_FRESH_CARDS)} 张表已更新到截至日',
        '未更新:' + '、'.join(stale) if stale else '')
    # 2 老服活跃层级:每天 DAU ≤ WAU ≤ MAU
    s = pd.DataFrame(DATA['daily']['series']['all|all'], columns=DATA['daily']['columns'])
    bad = s[(s.dau > s.wau) | (s.wau > s.mau)]
    add('老服', '活跃层级', '每天 DAU ≤ 7 日活跃 ≤ 30 日活跃(近 120 天)', 'warn' if len(bad) else 'pass',
        f'{len(bad)} 天不满足', '、'.join(bad.date.tail(10)) if len(bad) else '')
    # 3 付费人数 ≤ 当天活跃;另列付费当天没有登录记录的人次(PayerMax 网页付款可以不进游戏,不算错误)
    bad = s[s.payers > s.dau]
    o30 = c.O[c.O.d > E - pd.Timedelta(days=30)]
    pdays = o30[['monetId', 'd']].drop_duplicates()
    nolog = pdays[[(a, b) not in c.login_set for a, b in zip(pdays.monetId, pdays.d)]]
    add('老服', '付费人数 ≤ 活跃', '每天付费人数不超过当天活跃人数(近 120 天)', 'warn' if len(bad) else 'pass',
        f'{len(bad)} 天不满足', f'另:近 30 天 {len(pdays)} 个「人 × 付费日」里有 {len(nolog)} 个当天没有登录记录(网页付款可不进游戏)')
    # 4 收入两条计算路径一致:日序列近 30 天合计 = 30 天 KPI
    k30 = ((DATA.get('kpi') or {}).get('30|all|all') or {}).get('cur', {}).get('revenue')
    s30 = round(float(s.revenue.tail(30).sum()), 2)
    if k30 is None:
        add('老服', '收入合计一致', '日序列近 30 天之和 = 30 天 KPI 收入', 'na', '30 天 KPI 未算出')
    else:
        add('老服', '收入合计一致', '日序列近 30 天之和 = 30 天 KPI 收入', 'pass' if abs(s30 - k30) < 0.05 else 'warn',
            f'${s30:,.2f} vs ${k30:,.2f}')
    # 5 分服收入之和 ≤ 总收入(差额 = 活跃不足、不单独展示的小服)
    srv = DATA.get('srv') or {}
    ssum = round(sum((((v.get('kpi') or {}).get('30|all|all') or {}).get('cur') or {}).get('revenue') or 0 for v in srv.values()), 2)
    if k30 is not None:
        add('老服', '分服收入之和', '各服 30 天收入之和 ≤ 总收入;差额是不单独展示的小服', 'pass' if ssum <= k30 + 0.05 else 'warn',
            f'各服合计 ${ssum:,.2f},总计 ${k30:,.2f},差额 ${k30 - ssum:,.2f}')
    # 6 订单明细 vs 账号累计 / 首充表(同一张订单表的三种取法)
    LT = pd.DataFrame(m.get('Revenue_lifetime by account', []))
    if len(LT):
        os_ = c.O.groupby('monetId').price.sum()
        lt = LT.set_index('monetId').usd.reindex(os_.index)
        over = int((os_ > lt.fillna(0) + 0.01).sum())
        mo = c.O.groupby('monetId').t.min()
        fo = pd.to_datetime(pd.DataFrame(m['Revenue_first order']).set_index('monetId').first_order_at, format='mixed').reindex(mo.index)
        late = int((fo.isna() | (fo > mo)).sum())
        add('老服', '订单三表一致', '每个账号:近 150 天订单之和 ≤ 历史累计;首充时间 ≤ 窗口内最早订单', 'warn' if over or late else 'pass',
            f'{over} 个账号累计偏小,{late} 个账号首充时间不对', f'核对 {len(os_)} 个付费账号')
    else:
        add('老服', '订单三表一致', '每个账号:近 150 天订单之和 ≤ 历史累计', 'na', '历史累计表未抓到')
    # 7 付费账号都应有登录记录
    p90 = set(c.O[c.O.d > E - pd.Timedelta(days=90)].monetId)
    nol = p90 - set(c.L.monetId)
    add('老服', '付费账号有登录', '近 90 天付费账号在近 150 天登录日志里都能找到', 'warn' if nol else 'pass',
        f'{len(nol)} / {len(p90)} 个找不到', ('、'.join(map(str, sorted(nol)[:20]))) if nol else '')
    # 8 疑似刷量机型
    A = c.A_all[c.A_all.reg > E - pd.Timedelta(days=28)]
    farm = farm_models(c)   # 和新用户页同口径:注册当天进入游戏
    add('老服', '疑似刷量机型', f'近 28 天单一机型注册 ≥ {CHECK_FARM_MIN_REGS} 且注册当天进入游戏率 < {CHECK_FARM_MAX_ENTRY:.0%}',
        'warn' if len(farm) else 'pass',
        f'{len(farm)} 个机型' + (f',共 {int(farm.n.sum())} 个注册,占近 28 天注册 {farm.n.sum() / max(len(A), 1):.0%}' if len(farm) else ''),
        ';'.join(f'{k}:注册 {int(v.n)},当天进游戏 {v.ent:.1%}' for k, v in farm.iterrows()) + ('。其中注册当天没进游戏的已从新用户各项指标中剔除(2026-10-29 起)' if len(farm) else ''))
    # 601
    N = DATA.get('n601')
    if not N:
        add('601', '601 数据', '601 页能算出', 'na', '601 页未算出'); return out
    k = N['kpi']
    bad = [x['d'] for x in N['daily'] if x['payers'] > x['act_old'] + x['act_new']]
    add('601', '付费人数 ≤ 活跃', '每天付费人数不超过当天活跃;累计付费人数不超过玩家数', 'warn' if bad or k['payers'] > k['players'] else 'pass',
        f'{len(bad)} 天不满足', '、'.join(bad))
    rb = [f"{g_}·{d_}" for g_, x in N['retention'].items() for d_, v in x.items() if v['base'] and v['n'] > v['base']]
    add('601', '留存分子 ≤ 分母', 'D1 / D3 / D7 回访人数不超过已满天数的注册人数', 'warn' if rb else 'pass', f'{len(rb)} 项不满足', '、'.join(rb))
    ab = N.get('act_before_reg') or {}
    add('601', '注册前无活跃', '活跃痕迹不早于注册日(时区或游戏日口径错位时会出现)', 'warn' if ab.get('rows') else 'pass',
        f"{ab.get('rows', 0)} 条 / {ab.get('users', 0)} 人")
    # 排除名单漏网:内测期注册里,相邻注册间隔 ≤ 3 分钟且连续 ≥ 5 个,或客户端为空且注册即最后登录
    P = pd.DataFrame(m.get('N601_players detail', []))
    known = set()
    try:
        known = {int(a['id']) for a in json.load(open(EXCLUSIONS_FILE, encoding='utf-8'))['accounts']}
    except Exception:
        pass
    if len(P):
        P['t'] = pd.to_datetime(P.created_at, format='mixed'); P['lt'] = pd.to_datetime(P.last_login_at, format='mixed')
        P = P[(P.t >= pd.Timestamp(N601_START))].sort_values('t').reset_index(drop=True)
        gap = P.t.diff().dt.total_seconds().div(60)
        run_id = (gap.isna() | (gap > CHECK_BATCH_GAP_MIN)).cumsum()
        runs = P.groupby(run_id).monetId.transform('size')
        cand = set(P[runs >= CHECK_BATCH_MIN_RUN].monetId) | set(P[P.client_type.isna() & (P.t == P.lt)].monetId)
        new_c = sorted(cand - known)
        add('601', '排除名单漏网', f'相邻注册间隔 ≤ {CHECK_BATCH_GAP_MIN} 分钟且连续 ≥ {CHECK_BATCH_MIN_RUN} 个,或客户端为空且注册后再没登录;不在统一排除名单里',
            'warn' if new_c else 'pass', f'{len(new_c)} 个新疑似号(规则共命中 {len(cand)} 个,其余已在名单)',
            '、'.join(map(str, new_c[:30])))
    gd = pd.DataFrame(m.get('N601_guide', []))
    if len(gd):
        st = gd.guides.map(lambda x: set(json.loads(x)) if isinstance(x, str) else set(x or []))
        skip = int(st.map(lambda x: 202 in x and 201 not in x).sum())
        add('601', '引导步骤人数递减', '按步骤先后,人数应逐步减少', 'na', '缺步骤定义表',
            f'库里只有每人完成过的步骤编号,没有先后顺序;例如 {skip} 人完成了 202 但没有 201,可能是可跳过的步骤,要研发给定义表才能判断')
    # 2026-11-03:Google / Apple 订单改用 New Era 支付表的到账状态;PayerMax 和老服订单仍没有状态
    st_ = [x for x in N['by_channel'] if x['ch'] in ('Google', 'Apple')]
    so, sp = sum(x['orders'] for x in st_), sum(x['paid'] for x in st_)
    pm = sum(x['orders'] - x['paid'] for x in N['by_channel'] if x['ch'] not in ('Google', 'Apple'))
    add('601', '订单到账状态', 'Google / Apple 订单都应有商店扣款确认并发完奖励', 'warn' if sp < so else ('na' if pm else 'pass'),
        f'Google / Apple {so} 笔里已到账 {sp} 笔' + (f';PayerMax {pm} 笔没有状态记录' if pm else ''),
        '状态来自 New Era 支付表(收据、扣款确认、奖励发放);PayerMax 状态表已建、还没有数据;老服订单表只有下单记录')
    return out


# ---------------------------------------------------------------- 收入按功能拆(2026-10-29,需求第五节 A,第一版)
# 订单按商品分三类:钻石包 / 礼包(USDPack)/ 限时礼包。钻石包的钱按每个付费者近 90 天钻石去向按比例分摊;
# 竞猜、老虎机按净额(下注 − 返还,赢了记 0)。钻石不分付费 / 免费,分摊结果只作参考。WPP、GameAPI 没有扣钻记录,分不到
FUNC_CAT = {'Shop': '商店', 'LimitShop': '限时商店', 'InvaderSweep': '入侵扫荡', 'CleanInvaderSweepCD': '入侵扫荡',
            'FinishUpgradeBuilding': '加速', 'FinishUpgradeSoldier': '加速', 'FinishProduceSoldier': '加速', 'FinishUpgradeSoul': '加速',
            'FinishUpgradePotential': '加速', 'FinishProduceSoul': '加速', 'FinishUpgradeEmploySoldier': '加速', 'FinishSoldierChangeJob': '加速',
            'BuyHeroMana': '英雄 / 装备', 'BuyHeroLife': '英雄 / 装备', 'Fuse': '英雄 / 装备', 'AddTrepanning': '英雄 / 装备',
            'Skill': '英雄 / 装备', 'LearnExtraMagic': '英雄 / 装备', 'BuyHeroMaxLife': '英雄 / 装备',
            'LuckyDrawNew': '抽奖', 'LuckyDrawOneTime': '抽奖', 'LuckyDrawTenTimes': '抽奖', 'LuckyDrawHundredTimes': '抽奖', 'LuckyDraw': '抽奖',
            'PetQuiz': '宠物竞猜(净)', 'SlotSpin': '老虎机(净)'}


def func_of(t):
    if t in FUNC_CAT:
        return FUNC_CAT[t]
    if t.startswith('AllianceWar'):
        return '联盟战'
    if 'Alliance' in t:
        return '联盟'
    if t.startswith(('HeroGlory', 'TopOneKing', 'HeroArena', 'BuyHeroArena', 'RefreshHeroArena', 'StrongestAlliance')):
        return '竞技 / 冲榜'
    if t.startswith('Dungeons'):
        return '副本 / 扫荡'
    if 'Pet' in t:
        return '宠物'
    if t in ('UserHead', 'RenameCard', 'CityProfiling', 'Broadcast', 'Bubble'):
        return '外观 / 社交'
    if t == 'System':
        return '系统扣除'
    return '其他'


def product_class(pid):
    p_ = (pid or '').lower()
    if 'limit_time_pack' in p_:
        return '限时礼包'
    if 'usdpack' in p_:
        return '礼包(USDPack)'
    if 'diamond' in p_:
        return '钻石包'
    return '其他'


def revenue_by_function(c, days=90):
    S = pd.DataFrame(c.raw.get('Diamond_spend by account', []))
    if not len(S):
        return None
    S['diamonds'] = S.diamonds.astype(float)
    E = c.end
    O = c.O[c.O.d > E - pd.Timedelta(days=days)].copy()
    O['cls'] = O.product_id.map(product_class)
    out_ = S[S.direction == 'out'].pivot_table(index='monetId', columns='diamond_type', values='diamonds', aggfunc='sum', fill_value=0)
    in_ = S[S.direction == 'in'].pivot_table(index='monetId', columns='diamond_type', values='diamonds', aggfunc='sum', fill_value=0)
    for t in GAMBLING:   # 竞猜、老虎机按净额,赢钻记 0
        if t in out_:
            out_[t] = (out_[t] - in_.get(t, pd.Series(dtype=float)).reindex(out_.index).fillna(0)).clip(lower=0)
    F = out_.T.groupby(func_of).sum().T   # 账号 × 功能
    rev_d = O[O.cls == '钻石包'].groupby('monetId').price.sum()
    tot = F.sum(axis=1)
    share = F.div(tot.where(tot > 0), axis=0)
    payers = rev_d.index
    sh = share.reindex(payers)
    alloc = sh.mul(rev_d, axis=0)
    unspent = float(rev_d[sh.isna().all(axis=1)].sum())          # 付了钱但窗口内没花钻石的
    top3 = rev_d.sort_values(ascending=False).head(3).index
    def rows(a_, rv):
        g = a_.sum().sort_values(ascending=False)
        res = [[k, round(float(v), 2), int((a_[k] > 0).sum())] for k, v in g.items() if v > 0.5]
        return res
    by_func = rows(alloc, rev_d); by_func_ex3 = rows(alloc.drop(index=top3, errors='ignore'), rev_d.drop(index=top3, errors='ignore'))
    cls = O.groupby('cls').agg(usd=('price', 'sum'), orders=('price', 'size'), payers=('monetId', 'nunique')).sort_values('usd', ascending=False)
    # 付费者花掉的钻石里,买来的占多少(只算钻石包里写明数量的;礼包里的钻石不在内)
    O['dia'] = O.product_id.str.extract(r'(\d+)d[iI]amond', expand=False).astype(float)
    bought = O[O.cls == '钻石包'].groupby('monetId').dia.sum()
    spent_by_payers = float(tot.reindex(payers).fillna(0).sum())
    return {'days': days, 'from': (E - pd.Timedelta(days=days - 1)).strftime('%Y-%m-%d'), 'to': E.strftime('%Y-%m-%d'),
            'total': round(float(O.price.sum()), 2), 'classes': [[k, round(float(v.usd), 2), int(v.orders), int(v.payers)] for k, v in cls.iterrows()],
            'diamond_rev': round(float(rev_d.sum()), 2), 'by_func': by_func, 'unspent': round(unspent, 2),
            'by_func_ex3': by_func_ex3, 'top3_rev': round(float(rev_d.loc[top3].sum()), 2),
            'bought_ratio': r(float(bought.sum()) / spent_by_payers) if spent_by_payers else None,
            'bought': round(float(bought.sum())), 'spent': round(spent_by_payers)}


# ---------------------------------------------------------------- 三张清单 / 当日指导卡 / 六个病(2026-10-29,需求第三节)
# 规则生成,不调大模型。登记项和负责人标注在 data/issues.json;每天的清单快照在 data/issue_history.json(按数据截至日),用来标「新」和「关闭」
ISSUES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'issues.json')
ISSUE_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'issue_history.json')
SEV = {'高': 3, '中': 2, '低': 1}


def _trend(cur, base, up_good=True, thr=0.10, min_n=None):
    """恶化 / 持平 / 好转;样本太小时返回「样本不足」。"""
    if base is None or cur is None:
        return '无法判断'
    if min_n is not None and max(cur, base) < min_n:
        return '样本不足'
    if not base:
        return '持平' if not cur else ('好转' if up_good else '恶化')
    d = (cur - base) / abs(base)
    if abs(d) < thr:
        return '持平'
    return '好转' if (d > 0) == up_good else '恶化'


def ai_lists(c, DATA):
    E = c.end; items = []
    def it(key, typ, sev, title, evidence, owner, action, page=None, impact=''):
        items.append({'key': key, 'type': typ, 'sev': sev, 'title': title, 'evidence': evidence, 'impact': impact,
                      'owner': owner, 'action': action, 'page': page, 'source': '自动'})
    N = DATA.get('n601') or {}; M = DATA.get('money') or {}
    # ---- 错误:自洽检查没通过的、经济类异常、疑似批量号
    for ck in DATA.get('checks') or []:
        if ck['status'] == 'warn':
            it(f"E-check-{ck['name']}", '错误', '中', f"自洽检查未通过:{ck['name']}", f"{ck['value']}。{ck['detail']}"[:300], 'Chris', '核对后修正口径,或把确认过的账号 / 机型写进排除名单', 'defs')
    sl = M.get('slot') or {}; tk = sl.get('tickets7')
    if tk and tk['used'] and tk['issued'] >= 2 * tk['used']:
        it('E-slot-ticket', '错误', '高', '老虎机券发放远超使用,钻石在积压',
           f"近 7 天发出 {tk['issued']:,} 张、用掉 {tk['used']:,} 张(宠物竞猜 + 老虎机,{tk['issued'] / tk['used']:.1f} 倍);每张券平均返还约 {tk['per_ticket']} 钻;来源:" + '、'.join(f'{k} {v:,}' for k, v in tk['by_source'][:3]),
           '运营 / David', '核对 GameAPI 和活动奖励的发券量是否符合设计;评估积压的券集中兑现时的钻石冲击', 'money')
    SS = pd.DataFrame(c.raw.get('Slot_spin daily', []))
    if len(SS):
        tdays = set(SS[SS.kind == 'ticket'].dateCN.astype(str))
        miss = [d.strftime('%Y-%m-%d') for d in pd.date_range(E - pd.Timedelta(days=27), E) if d.strftime('%Y-%m-%d') not in tdays]
        if miss:
            it('E-slot-gap', '错误', '低', '老虎机用券记录有缺天', f"近 28 天有 {len(miss)} 天没有任何用券记录:{'、'.join(m[5:] for m in miss[:6])};前后几天每天 1–6 万条", '勇飞', '确认是日志丢失还是当天停服 / 关闭玩法', 'money')
    if N.get('suspects'):
        it('E-n601-suspects', '错误', '低', f"601 疑似批量号 {len(N['suspects'])} 个未剔除", '同一联盟的一批老服小号,多次在几分钟内逐个登录,从未付费;都是旧号直接进 601,不影响真新设备留存', '运营', '确认是否工作室;确认后写进排除名单', 'n601')
    # ---- 缺失:无法判断的检查项、可从数据看出的缺口
    for ck in DATA.get('checks') or []:
        if ck['status'] == 'na':
            own = {'引导步骤人数递减': ('策划 / David', '给出 601 引导步骤编号 → 名称 → 先后顺序'), '订单到账状态': ('David / 财务', '订单表加到账状态和到账时间,或提供渠道对账结果')}.get(ck['name'], ('研发', '补齐所缺的字段或定义表'))
            it(f"M-check-{ck['name']}", '缺失', '中', f"无法检查:{ck['name']}", f"{ck['value']}。{ck['detail']}"[:300], own[0], own[1], 'defs')
    P6 = pd.DataFrame(c.raw.get('N601_players detail', []))
    if len(P6):
        dev = set(r_['monetId'] for r_ in c.raw.get('N601_device ids', []))
        P6['t'] = pd.to_datetime(P6.created_at, format='mixed')
        nw = P6[(P6.t > E - pd.Timedelta(days=6)) & (P6.monetId >= N601_OLD_ID_MAX)]
        if len(nw) >= 5:
            k_ = int(nw.monetId.isin(dev).sum())
            if k_ / len(nw) < 0.5:
                allnew = P6[P6.monetId >= N601_OLD_ID_MAX]; lw = allnew[allnew.monetId.isin(dev)].t.max()
                tail = allnew[allnew.t > lw] if pd.notna(lw) else allnew
                it('M-n601-adid', '缺失', '高', '601 新建号缺广告 ID', f"近 7 天 601 新建号 {len(nw)} 个,有广告 ID 的 {k_} 个;" + (f"{lw.strftime('%m-%d')} 之后新建的 {len(tail)} 个全部没有" if pd.notna(lw) else '内测以来都没有') + ";同期老 App 新注册照常有",
                   'David', '查 New Era 10-24 前后广告 ID 上报的改动', 'n601', '无法区分真新设备和老玩家小号,广告无法归因')
    cty = c.country
    O30 = c.O[c.O.d > E - pd.Timedelta(days=30)].groupby('monetId').price.sum()
    if len(O30) and len(cty):
        unk = float(O30[~O30.index.isin(cty[cty != '未知'].index)].sum()); tot = float(O30.sum())
        if tot and unk / tot >= 0.3:
            it('M-country', '缺失', '中', '大部分收入没有国家', f"近 30 天收入 ${tot:,.0f} 里 ${unk:,.0f}({unk / tot:.0%})来自国家未知的账号", 'Chris', '用区服 player.countryCode 补,IP 只作兜底', 'geo')
    # ---- 断层:新手漏斗掉得最多的一步、601 留存、点击未成单、告警里的漏斗 / 留存 / 601
    fn = ((DATA.get('new_user') or {}).get('funnel') or {}).get('30|all')
    if fn:
        st = fn['steps'][:5]
        drops = [(st[i][0], st[i + 1][0], st[i][1], st[i + 1][1]) for i in range(len(st) - 1) if st[i][1]]
        a_, b_, n0, n1 = max(drops, key=lambda x: 1 - x[3] / x[2])
        it('G-old-funnel', '断层', '高', f'老服新手:「{a_} → {b_}」掉得最多', f"{fn['from'][5:]}–{fn['to'][5:]} 注册 {fn['n']} 人;这一步 {n0} → {n1},留下 {n1 / n0:.0%}。全程:" + ' → '.join(f'{x[0]} {x[1]}' for x in st),
           '勇飞 / 策划', '查这一步的引导和首日目标;引导延伸到下一步做 A/B(按账号 ID 随机分组)', 'newuser')
    q = next((x for x in ((N.get('cohort_q') or {}).get('summary') or []) if x.get('key') == 'fresh'), None)
    if q and q['d1'].get('base'):
        it('G-n601-ret', '断层', '中', '601 真新设备次日流失', f"真新设备 {q['n']} 人,D1 {q['d1']['n']}/{q['d1']['base']}({q['d1']['rate']:.0%},95% 区间 {q['d1']['ci'][0]:.0%}–{q['d1']['ci'][1]:.0%});{q['d1'].get('verdict') or ''}",
           'David', '对照引导结束到次日之间的节点(缺引导定义表和会话日志)', 'n601')
    ck_ = (N.get('checkout') or {}).get('total')
    if ck_ and ck_['click_users'] - ck_['order_users'] > 0:
        it('G-n601-checkout', '断层', '中', '601 点了付费但没生成订单', f"内测期 {ck_['click_users']} 人点击付费,{ck_['order_users']} 人生成订单;{ck_['click_users'] - ck_['order_users']} 人点了没成单", 'David', '提供支付失败 / 取消的原因码', 'n601')
    for a in DATA.get('alerts') or []:
        if a['level'] == 'info' or a.get('persistent') is False:
            continue
        if a['dim'] in ('funnel', 'ret', 'n601', 'game', 'life'):
            it(f"G-alert-{a['metric']}", '断层', '高' if a['level'] == 'red' or a['dim'] == 'n601' else '中', a['metric'], a.get('note') or '', '勇飞 / David' if a['dim'] != 'n601' else 'David / 运营', '见对应页面', a.get('page'))
        elif a['dim'] in ('econ',) and not a['metric'].startswith('老虎机券'):
            it(f"E-alert-{a['metric']}", '错误', '中', a['metric'], a.get('note') or '', '运营', '见对应页面', a.get('page'))
    # ---- 登记项
    try:
        reg = json.load(open(ISSUES_FILE, encoding='utf-8'))
    except Exception:
        reg = {'registered': [], 'labels': {}}
    for x in reg.get('registered', []):
        if x.get('status') == '已解决':
            continue
        items.append({'key': x['key'], 'type': x['type'], 'sev': '中', 'title': x['title'], 'evidence': '', 'impact': x.get('impact', ''),
                      'owner': x.get('owner', ''), 'action': x.get('action', ''), 'page': None, 'source': '登记'})
    labels = reg.get('labels', {})
    for x in items:
        lb = labels.get(x['key']) or {}
        x['label'] = lb.get('status') or next((y.get('status') for y in reg.get('registered', []) if y['key'] == x['key']), None) or '未标注'
        x['label_note'] = lb.get('reason', '')
    # ---- 新 / 关闭:和上一个数据截至日比
    day = E.strftime('%Y-%m-%d')
    try:
        hist = json.load(open(ISSUE_HISTORY_FILE, encoding='utf-8'))
    except Exception:
        hist = {}
    prev_days = sorted(d for d in hist if d < day)
    prev = hist[prev_days[-1]] if prev_days else None
    cur = {x['key']: x['title'] for x in items}
    for x in items:
        x['new'] = prev is not None and x['key'] not in prev
    closed = [{'key': k, 'title': v} for k, v in (prev or {}).items() if k not in cur]
    hist[day] = cur
    try:
        json.dump({d: hist[d] for d in sorted(hist)[-60:]}, open(ISSUE_HISTORY_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    except Exception:
        pass
    items.sort(key=lambda x: (-SEV[x['sev']], x['source'] != '自动', not x['key'].startswith('G-alert-601'), x['key']))   # 601 无真实订单排最前
    lists = {t: [x for x in items if x['type'] == t] for t in ('缺失', '断层', '错误')}
    # ---- 当日指导卡:3 个最大问题 + 3 个最大机会
    top = [x for x in items if x['source'] == '自动'][:3]
    opp = []
    W = M.get('whales') or []
    wr = [w for w in W if w['status'] in ('red', 'yellow')]
    if wr:
        opp.append({'title': f'{len(wr)} 个大 R 付费下降但仍在登录', 'evidence': f"前 30 天合计付费 ${sum(w['pay_prev30'] for w in wr):,.0f},近 30 天 ${sum(w['pay30'] for w in wr):,.0f};" + '、'.join(str(w['id']) for w in wr[:5]),
                    'owner': '运营', 'action': '按大 R 风险表逐个联系,先联系「需关注」的', 'page': 'money'})
    LC = DATA.get('level_cap') or {}
    if LC.get('at_cap'):
        ac = LC['at_cap']
        opp.append({'title': f"主城 {LC['cap']} 级到顶玩家贡献 {ac['rev_share']:.0%} 收入", 'evidence': f"近 30 天活跃 {LC['active30']:,} 人里 {ac['n']} 人在 {LC['cap']} 级({ac['share']:.0%}),付费 {ac['payers']} 人、${ac['rev']:,.0f}",
                    'owner': '运营 / 勇飞', 'action': '给到顶玩家安排新的追求(活动、养成线),先在一个服试', 'page': 'life'})
    if fn:
        st = fn['steps']
        opp.append({'title': f"老服新人当天停在主城 1–2 级", 'evidence': f"{fn['from'][5:]}–{fn['to'][5:]} 进入游戏 {st[1][1]} 人,当天到 3 级 {st[3][1]} 人({st[3][1] / st[1][1]:.0%}),D1 {st[4][1]} 人",
                    'owner': '勇飞 / 策划', 'action': '把引导延伸到主城 3 级,按账号 ID 随机分组做 A/B', 'page': 'newuser'})
    if ck_ and ck_['click_users'] - ck_['order_users'] > 0:
        opp.append({'title': f"601 有 {ck_['click_users'] - ck_['order_users']} 人点了付费没成单", 'evidence': f"内测期点击付费 {ck_['click_users']} 人、生成订单 {ck_['order_users']} 人", 'owner': 'David / 运营', 'action': '查失败原因;对点了没成单的玩家做一次触达', 'page': 'n601'})
    # ---- 六个病:近 4 周 vs 前 4 周
    dz = []
    gp = DATA.get('gameplay_pulse') or []
    if gp:
        devs = [g['dev'] for g in gp if g['dev'] is not None]
        mean_dev = float(np.mean(devs)) if devs else None
        dz.append({'name': '1 SLG 没有新东西', 'status': _trend(1 + mean_dev, 1.0) if mean_dev is not None else '无法判断',
                   'basis': '核心玩法日参与人数(近 7 天 vs 前 28 天):' + '、'.join(f"{g['name']} {g['now']}({g['dev']:+.0%})" for g in gp),
                   'guard': '只看参与人数,不看收入(收入会被大户波动带偏);缺内容上线日志'})
    F_ = c.first_order[c.first_order <= E]
    f0 = int(((F_ > E - pd.Timedelta(days=28)) & (F_ <= E)).sum()); f1 = int(((F_ > E - pd.Timedelta(days=56)) & (F_ <= E - pd.Timedelta(days=28))).sum())
    n6p = sum(x['payers'] for x in (N.get('daily') or [])[-28:])
    dz.append({'name': '2 没有新的付费用户进来', 'status': _trend(f0, f1, thr=0.2, min_n=10), 'basis': f'老服首次付费人数 近 28 天 {f0} 人,前 28 天 {f1} 人;601 近 28 天付费人次 {n6p}(含 PayerMax 待核实)',
               'guard': '老玩家换号会冒充新付费;601 按设备来源分组看'})
    nd = pd.DataFrame(DATA['new_user']['daily']['series']['all'], columns=DATA['new_user']['daily']['columns'])
    a_, b_ = nd.iloc[-29:-1], nd.iloc[-57:-29]
    r0 = a_.d1.sum() / a_.entered.sum() if a_.entered.sum() else None; r1 = b_.d1.sum() / b_.entered.sum() if b_.entered.sum() else None
    dz.append({'name': '3 新人接不住、老人留不住', 'status': _trend(r0, r1, thr=0.15),
               'basis': (f"老服新人 D1(进入游戏口径)近 28 个满期注册日 {r0:.1%}({int(a_.d1.sum())}/{int(a_.entered.sum())}),前 28 天 {r1:.1%}" if r0 is not None and r1 is not None else '老服新人 D1 无数据') +
                        (f";601 真新设备 D1 {q['d1']['rate']:.0%}({q['d1']['n']}/{q['d1']['base']})" if q and q['d1'].get('base') else ''),
               'guard': '来源结构变了不能直接比,按来源分层;刷量注册已剔除'})
    tr = LC.get('trend') or []
    if len(tr) >= 8:
        a4 = float(np.mean([x['share'] for x in tr[-4:]])); b4 = float(np.mean([x['share'] for x in tr[-8:-4]]))
        stt = '恶化' if a4 - b4 >= 0.03 else ('好转' if b4 - a4 >= 0.03 else '持平')
        dz.append({'name': '4 等级到顶', 'status': stt, 'basis': f"主城 {LC['cap']} 级人数占周活跃 近 4 周 {a4:.1%},前 4 周 {b4:.1%}",
                   'guard': '新服提上限解决不了老服 26 级,老服、新服分开看'})
    ddr = (M.get('diamond_daily') or {}).get('rows') or []
    if len(ddr) >= 56:
        dd_ = pd.DataFrame(ddr, columns=M['diamond_daily']['columns'])
        allnet = dd_.in_loop + dd_.ext_in - dd_.out_loop - dd_.gamble_net_out
        n0, n1 = float(allnet.iloc[-28:].sum()), float(allnet.iloc[-56:-28].sum()); cons = float(dd_.out_loop.iloc[-28:].sum())
        stt = '恶化' if n0 - n1 > 0.1 * cons else ('好转' if n1 - n0 > 0.1 * cons else '持平')
        if float(dd_.ext_in.iloc[-56:].sum()) > 0 and float(dd_.ext_out.iloc[-56:].sum()) == 0:
            stt = '无法判断'   # 外部接入只有流入、没有扣钻记录时,净额不可靠,不给方向
        dz.append({'name': '5 钻石越来越不值钱', 'status': stt,
                   'basis': f"全部流入 − 流出(含外部接入)近 28 天 {n0 / 1e4:+,.0f} 万钻,前 28 天 {n1 / 1e4:+,.0f} 万钻" + (f";老虎机券近 7 天发放是使用的 {tk['issued'] / tk['used']:.1f} 倍" if tk and tk['used'] else ''),
                   'guard': '外部接入(WPP、GameAPI)没有扣钻记录,研发说明前不给方向;只看单日会被「挪钱」骗,看 28 天'})
    O_ = c.O
    def mid(lo_, hi_):
        x = O_[(O_.d > hi_ - pd.Timedelta(days=28)) & (O_.d <= hi_)].groupby('monetId').price.sum()
        return int(((x >= 20) & (x < 500)).sum()), int((x >= 500).sum())
    m0, w0 = mid(None, E); m1, w1 = mid(None, E - pd.Timedelta(days=28))
    dz.append({'name': '6 中层变薄', 'status': _trend(m0, m1, thr=0.15, min_n=10), 'basis': f'28 天付费 $20–$499 的人 近 28 天 {m0} 人,前 28 天 {m1} 人(≥ $500 的 {w0} / {w1} 人)',
               'guard': '中层变厚可能是大户降档,要看同一批人的历史档位'})
    return {'date': day, 'lists': lists, 'closed': closed, 'counts': {t: len(v) for t, v in lists.items()},
            'new_count': sum(1 for x in items if x.get('new')), 'top': top, 'opps': opp[:3], 'diseases': dz,
            'first_run': prev is None}


def build(raw):
    errors = {}
    c = Ctx(raw)
    DATA = {'meta': {'data_through': c.end.strftime('%Y-%m-%d'), 'run_at': c.run_at, 'source': raw.get('source'),
                     'fetch_errors': raw.get('errors', {}), 'bands': BAND_NAMES, 'windows': WINDOWS}}
    DATA['daily'] = safe(lambda: daily_series(c), errors, 'daily')
    DATA['kpi'] = safe(lambda: window_kpis(c), errors, 'kpi') or {}
    DATA['new_user'] = safe(lambda: new_user(c), errors, 'new_user')
    DATA['life'] = safe(lambda: lifecycle(c), errors, 'life')
    DATA['money'] = safe(lambda: monetization(c), errors, 'money')
    DATA['gameplay'] = safe(lambda: gameplay(c), errors, 'gameplay')
    DATA['pvp'] = safe(lambda: pvp(c), errors, 'pvp')
    DATA['alliance'] = safe(lambda: alliance(c), errors, 'alliance')
    DATA['geo'] = safe(lambda: geo(c, DATA), errors, 'geo')
    DATA['srv'] = safe(lambda: by_server(c, errors), errors, 'srv') or {}
    DATA['level_cap'] = safe(lambda: level_cap(c), errors, 'level_cap')
    DATA['rev_func'] = safe(lambda: revenue_by_function(c), errors, 'rev_func')
    DATA['today'] = safe(lambda: today_live(c), errors, 'today')
    DATA['n601'] = safe(lambda: n601(c), errors, 'n601')
    DATA['n601_events'] = N601_EVENTS
    DATA['n601_ev'] = {str(w_): safe(lambda w_=w_: n601_client(c, DATA['n601'], w_), errors, f'n601_ev_{w_}') for w_ in N6_WINDOWS}
    DATA['n601_seg'] = safe(lambda: n601_by_segment(c, errors), errors, 'n601_seg')
    if DATA['n601'] and DATA['n601'].get('exclusions_error'):
        errors['exclusions'] = '排除名单读取失败,已退回内置测试号:' + DATA['n601']['exclusions_error']
    DATA['meta']['segs'] = c.segs
    DATA['meta']['n601_excluded'] = getattr(c, 'n601_excluded', 0)
    fr_ = getattr(c, 'farm_regs', None)
    DATA['meta']['farm'] = {'models': getattr(c, 'farm_list', []), 'n': int(len(fr_)) if fr_ is not None else 0,
                            'n28': int((fr_.reg > c.end - pd.Timedelta(days=28)).sum()) if fr_ is not None else 0,
                            'first': fr_.reg.min().strftime('%Y-%m-%d') if fr_ is not None and len(fr_) else None}
    DATA['meta']['servers'] = [{'id': k, 'active30': v.get('active30')} for k, v in DATA['srv'].items()]
    DATA['meta']['countries'] = c.countries
    DATA['meta']['versions'] = c.versions
    res = safe(lambda: alerts_and_health(c, DATA), errors, 'alerts')
    DATA['alerts'], DATA['health'], DATA['gameplay_pulse'] = res if res else ([], [], [])
    DATA['problems'] = safe(lambda: top_problems(c, DATA), errors, 'problems') or []
    DATA['checks'] = safe(lambda: consistency_checks(c, DATA), errors, 'checks') or []
    DATA['ai'] = safe(lambda: ai_lists(c, DATA), errors, 'ai')
    DATA['meta']['compute_errors'] = errors
    return DATA
