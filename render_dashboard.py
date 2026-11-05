#!/usr/bin/env python3
"""Invader 看板 · 渲染:raw_metrics.json → site/index.html(完整网页,给 Cloudflare Pages)
                                          + preview_artifact.html(去掉外壳,给 Claude 网页发布)

用法:
  python3 render_dashboard.py --raw raw_metrics.json --out site/index.html --artifact preview_artifact.html

计算全在 compute.py;这里只负责把 DATA 嵌进页面,页面里的筛选(时间 × 平台 × 等级段)在浏览器端切换。
图表库 lib/chart.umd.min.js 内嵌(与 SoulMap 同一份 Chart.js 4.4.3),页面不依赖外网脚本。
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import compute

HERE = Path(__file__).resolve().parent
TITLE = 'Invader 数据看板'

# 指标定义:页面上每个 KPI 的 ⓘ 点开显示(规格第 3 节、第 41 条)
DEFS = {
    'dau': ['DAU', '当天有登录记录的账号数;一个账号在多个服登录只算一次', '当天 GetUserInfo 去重 monetId', '—', 'Log 库 invaderLogData.GetUserInfo'],
    'reg': ['新注册', '账号注册时间落在当天 / 窗口内', 'user_info 行数(user_id 去重)', '—', '生产库 invade_account.user_info'],
    'entry': ['进入游戏率', '注册当天就有登录记录的比例', '注册当天在 GetUserInfo 出现的注册账号', '同期注册账号', 'user_info + GetUserInfo,按 monetId 关联'],
    'lv3': ['当天到 Lv3 转化', '注册当天主城最高等级 ≥ 3 的比例;当前最大的新手断点', '注册当天最高 governmentLevel ≥ 3 的账号', '注册当天进入游戏的账号', '同上'],
    'd1': ['D1 留存', '注册后第 1 天当天有登录;只统计已满 1 天的注册日', '第 1 天有登录的注册账号', '同期注册账号(注册口径)', '同上'],
    'd7': ['D7 留存', '注册后第 7 天当天有登录;只统计已满 7 天的注册日', '第 7 天有登录的注册账号', '同期注册账号', '同上'],
    'd30': ['D30 留存', '注册后第 30 天当天有登录;只统计已满 30 天的注册日', '第 30 天有登录的注册账号', '同期注册账号', '同上'],
    'pay30': ['30 天内付费率', '注册后 30 天内有订单;只统计已满 30 天的注册日', '30 天内有订单的注册账号', '同期注册账号', 'user_info + TopUpRecord'],
    'revenue': ['收入', '订单美元金额之和(毛流水,未扣苹果 / 谷歌分成和第三方手续费;第三方为折后实付)', 'sum(price)', '—', '生产库 invade_billing.TopUpRecord'],
    'payers': ['付费人数', '窗口内有订单的账号数', '去重 monetId', '—', 'TopUpRecord'],
    'pay_rate': ['付费率', '窗口内付费人数 / 窗口内活跃人数', '付费人数', '活跃人数', 'TopUpRecord + GetUserInfo'],
    'arpu': ['ARPU', '收入 / 活跃人数', '收入', '窗口内活跃人数', '同上'],
    'arppu': ['ARPPU', '收入 / 付费人数;容易被少数大 R 拉高', '收入', '付费人数', 'TopUpRecord'],
    'new_payers': ['新付费人数', '历史第一笔订单落在窗口内的付费账号', '—', '—', 'TopUpRecord(2023-11-10 起)'],
    'repeat_payers': ['复购付费人数', '窗口内付费、且此前已有订单的账号', '—', '—', 'TopUpRecord'],
    'rev_new': ['每个新注册用户收入', '窗口内注册的账号在窗口内的付费 / 窗口内注册数', '新注册账号的收入', '窗口内注册数', 'user_info + TopUpRecord'],
}
COMMON = '时区:中国时间(dateCN,UTC+8)。排除:601 新版内测服(含测试付款)、monetId ≤ 0。数据截至:最近一个完整日。'


def _np(o):
    """numpy 标量(int64 / float64)转成 Python 数,其余转字符串"""
    return o.item() if hasattr(o, 'item') else str(o)


def _clean(o):
    """2026-10-23:把 NaN / Infinity(含 numpy 的)换成 null。JSON 里出现 NaN 会让整个页面解析失败、白屏
    (当天 601 有个玩家名字为空,pandas 变成了 NaN)。"""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, 'item') and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def page(D: dict, chartjs: str, full: bool) -> str:
    data = json.dumps(_clean(D), ensure_ascii=False, separators=(',', ':'), default=_np, allow_nan=False).replace('</', '<\\/')
    defs = json.dumps(DEFS, ensure_ascii=False).replace('</', '<\\/')
    body = TEMPLATE.replace('__TITLE__', TITLE).replace('__DATA__', data).replace('__DEFS__', defs) \
                   .replace('__COMMON__', COMMON).replace('__CHARTJS__', chartjs.replace('</script', '<\\/script'))
    if not full:
        return body
    return ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + body + '\n</body>\n</html>\n')


TEMPLATE = r"""<title>__TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* 布局:顶部固定的标题 + 页签 + 筛选条;下面按页签切换的卡片网格。色调取青金石蓝(中东题材)配冷灰中性色。 */
:root{
  --bg:#f3f5f8; --panel:#ffffff; --ink:#18202d; --muted:#5d6676; --line:#dde2ea; --grid:#e9ecf1;
  --accent:#1e4ea2; --accent-soft:rgba(30,78,162,.10); --gold:#b9852a; --slate:#6a788d; --violet:#7650a6;
  --good:#1d8657; --warn:#a8701a; --bad:#c23a2e; --good-soft:rgba(29,134,87,.12); --warn-soft:rgba(168,112,26,.14); --bad-soft:rgba(194,58,46,.12);
  --font-ui:"IBM Plex Sans","PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;
  --font-num:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
  --r:10px;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0e1219; --panel:#151b25; --ink:#e5e9f0; --muted:#97a1b2; --line:#283142; --grid:#212a38;
  --accent:#7aa3f2; --accent-soft:rgba(122,163,242,.14); --gold:#d9a84a; --slate:#8e9bb1; --violet:#a98ad8;
  --good:#4cc38a; --warn:#e0b25a; --bad:#f06b5f; --good-soft:rgba(76,195,138,.14); --warn-soft:rgba(224,178,90,.16); --bad-soft:rgba(240,107,95,.15);
  color-scheme:dark;}}
:root[data-theme="dark"]{
  --bg:#0e1219; --panel:#151b25; --ink:#e5e9f0; --muted:#97a1b2; --line:#283142; --grid:#212a38;
  --accent:#7aa3f2; --accent-soft:rgba(122,163,242,.14); --gold:#d9a84a; --slate:#8e9bb1; --violet:#a98ad8;
  --good:#4cc38a; --warn:#e0b25a; --bad:#f06b5f; --good-soft:rgba(76,195,138,.14); --warn-soft:rgba(224,178,90,.16); --bad-soft:rgba(240,107,95,.15);
  color-scheme:dark;}
body{background:var(--bg);color:var(--ink);font-family:var(--font-ui);font-size:14px;line-height:1.5}
.iv{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:0 48px;max-width:1440px;margin-inline:auto}
.iv *{box-sizing:border-box}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);padding-block:14px 10px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:10px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px}
.head h1{margin:0;font-size:20px;font-weight:600;letter-spacing:.01em}
.stamp{color:var(--muted);font-size:12.5px}
.ck{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;white-space:nowrap}.ck.pass{color:var(--good);background:var(--good-soft)}.ck.warn{color:var(--warn);background:var(--warn-soft)}.ck.na{color:var(--muted);background:var(--grid)}
.tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
.tabs button{all:unset;cursor:pointer;padding:6px 12px;border-radius:999px;color:var(--muted);white-space:nowrap;font-size:13.5px}
.tabs button[aria-selected="true"]{background:var(--accent-soft);color:var(--accent);font-weight:600}
.tabs.sub{margin-top:4px;padding-top:6px;border-top:1px solid var(--line)}
.tabs.sub button{font-size:13px;padding:5px 10px}
.tabs .sep{width:1px;background:var(--line);margin:4px 6px;flex:none}
.tabs button:focus-visible,.seg button:focus-visible,.link:focus-visible,.info:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.filters{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;font-size:12.5px;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel)}
.seg button{all:unset;cursor:pointer;padding:3px 9px;color:var(--muted);font-size:12.5px}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--accent);color:#fff}
.fl{display:inline-flex;align-items:center;gap:6px}
.note{color:var(--muted);font-size:12px}
section{display:flex;flex-direction:column;gap:14px;padding-top:16px}
h2{margin:8px 0 0;font-size:15px;font-weight:600}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(min(100%,26rem),1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px;min-width:0;display:flex;flex-direction:column;gap:8px}
.card h3{margin:0;font-size:14px;font-weight:600}
.card .sub{color:var(--muted);font-size:12px;margin-top:-4px}
.kpis{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(min(100%,10.5rem),1fr))}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:11px 13px;display:flex;flex-direction:column;gap:3px;min-width:0;border-top:3px solid var(--line)}
.kpi.st-red{border-top-color:var(--bad)} .kpi.st-yellow{border-top-color:var(--warn)} .kpi.st-green{border-top-color:var(--good)}
.kpi .lab{display:flex;justify-content:space-between;gap:6px;color:var(--muted);font-size:12.5px}
.kpi .val{font-family:var(--font-num);font-size:24px;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.kpi .dl{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.up{color:var(--good)} .down{color:var(--bad)} .flat{color:var(--muted)}
.info{all:unset;cursor:pointer;color:var(--muted);font-size:12px;border:1px solid var(--line);border-radius:999px;width:16px;height:16px;display:inline-grid;place-items:center;flex:none}
.chart{position:relative;height:260px;min-width:0}
.chart.tall{height:320px}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:500;background:var(--panel);position:sticky;top:0}
td.l{text-align:left;white-space:normal}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:500}
.p-red{background:var(--bad-soft);color:var(--bad)} .p-yellow{background:var(--warn-soft);color:var(--warn)} .p-green{background:var(--good-soft);color:var(--good)} .p-info{background:var(--accent-soft);color:var(--accent)}
.health{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(min(100%,7.5rem),1fr))}
.hb{all:unset;cursor:pointer;border:1px solid var(--line);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column;gap:2px;background:var(--panel)}
.hb .t{font-size:12.5px;color:var(--muted)} .hb .s{font-size:14px;font-weight:600}
.hb.red{border-color:var(--bad);background:var(--bad-soft)} .hb.yellow{border-color:var(--warn);background:var(--warn-soft)}
.hb[aria-expanded="true"]{outline:2px solid var(--accent)}
.prob{display:grid;gap:4px;border-left:3px solid var(--warn);padding:4px 0 4px 12px}
.prob.red{border-left-color:var(--bad)}
.prob .pt{font-weight:600} .prob dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0;font-size:12.5px}
.prob dt{color:var(--muted)} .prob dd{margin:0}
.funnel{display:flex;flex-direction:column;gap:5px;font-size:12.5px}
.fr{display:grid;grid-template-columns:minmax(7.5rem,9.5rem) 1fr minmax(8.5rem,auto);gap:8px;align-items:center}
.fb{height:18px;border-radius:4px;background:var(--accent);min-width:2px}
.fr.worst .fb{background:var(--bad)}
.fr .n{font-variant-numeric:tabular-nums;color:var(--muted);text-align:right}
.link{all:unset;cursor:pointer;color:var(--accent);font-size:12.5px}
.sel{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:2px 6px;font:inherit;font-size:12.5px}
.banner{border:1px solid var(--warn);background:var(--warn-soft);border-radius:8px;padding:6px 10px;font-size:12.5px}
.heat td{font-family:var(--font-num)}
.empty{color:var(--muted);font-size:12.5px;padding:8px 0}
.modal{position:fixed;inset:0;background:rgba(10,14,20,.45);display:grid;place-items:center;z-index:20;padding:16px}
.modal .box{background:var(--panel);border:1px solid var(--line);border-radius:12px;max-width:34rem;width:100%;padding:16px 18px;display:flex;flex-direction:column;gap:8px}
.modal dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0;font-size:13px}
.modal dt{color:var(--muted)} .modal dd{margin:0}
.modal .x{align-self:flex-end}
.hidden{display:none!important}
.srctag{display:inline-block;margin-left:6px;padding:0 6px;border:1px solid var(--grid);border-radius:9px;font-size:10.5px;font-weight:400;color:var(--muted);vertical-align:1px;cursor:help}
@media (max-width:560px){.kpi .val{font-size:20px}.fr{grid-template-columns:6.5rem 1fr auto}}
</style>

<div class="iv">
  <div class="top">
    <div class="head"><h1>__TITLE__</h1><span class="stamp" id="stamp"></span></div>
    <nav class="tabs" role="tablist" id="tabs">
      <button role="tab" data-tab="n601" id="t-n601">601 总览</button>
      <button role="tab" data-tab="n6tech" id="t-n6tech">获客与进入</button>
      <button role="tab" data-tab="n6first" id="t-n6first">新手与首日</button>
      <button role="tab" data-tab="n6new" id="t-n6new">留存与活跃</button>
      <button role="tab" data-tab="n6grow" id="t-n6grow">成长与玩法</button>
      <button role="tab" data-tab="n6pay" id="t-n6pay">付费</button>
      <button role="tab" data-tab="n6dq" id="t-n6dq">技术与数据</button>
      <span class="sep" aria-hidden="true"></span>
      <button role="tab" data-tab="old" id="t-old">老服</button>
      <button role="tab" data-tab="defs" id="t-defs">口径</button>
    </nav>
    <nav class="tabs sub hidden" role="tablist" id="tabs2" aria-label="老服页面">
      <button role="tab" data-tab="home">总览</button>
      <button role="tab" data-tab="newuser">新用户</button>
      <button role="tab" data-tab="life">生命周期</button>
      <button role="tab" data-tab="game">玩法</button>
      <button role="tab" data-tab="pvp">PvP</button>
      <button role="tab" data-tab="ally">联盟</button>
      <button role="tab" data-tab="money">商业化与大 R</button>
      <button role="tab" data-tab="geo">国家 / 版本</button>
      <button role="tab" data-tab="alerts">异常中心</button>
    </nav>
    <div class="filters" id="f-bar">
      <span class="fl" style="display:none">时间 <span class="seg" id="f-w"></span></span>
      <span class="note" style="margin-right:6px">时间:近 30 天(趋势图看近 30 天每天)</span>
      <span class="fl">平台 <span class="seg" id="f-plat"></span></span>
      <label class="fl" for="f-srv">服务器 <select class="sel" id="f-srv"></select></label>
      <label class="fl" for="f-country">国家 <select class="sel" id="f-country"></select></label>
      <label class="fl" for="f-ver">版本 <select class="sel" id="f-ver"></select></label>
      <span class="note">国家 / 版本 一次选一个;选了服务器时不能再选国家 / 版本 · 不含 601 内测服 · 同一账号可能在多个服,各服人数相加大于全服</span>
    </div>
  </div>
  <div class="filters hidden" id="f-bar6">
   <span class="fl">时间 <span class="seg" id="f-w6"></span></span>
   <span class="fl">平台 <span class="seg" id="f-plat6"></span></span>
   <label class="fl" for="f-country6">国家 <select class="sel" id="f-country6"></select></label>
   <label class="fl" for="f-ver6" title="玩家最后一次登录时的版本;看新版本带来的新人用「获客与进入」页的建号版本">版本(最后登录) <select class="sel" id="f-ver6"></select></label>
   <span class="note" id="f-w6note"></span>
  </div>
  <main id="root"></main>
</div>
<div class="modal hidden" id="modal" role="dialog" aria-modal="true" aria-labelledby="m-title"><div class="box">
  <button class="link x" id="m-close">关闭</button><h3 id="m-title" style="margin:0"></h3><dl id="m-body"></dl></div></div>

<script id="dash-data" type="application/json">__DATA__</script>
<script>__CHARTJS__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('dash-data').textContent);
const DEFS = __DEFS__;
const COMMON = '__COMMON__';
const BANDS = D.meta.bands, WINS = D.meta.windows, END = D.meta.data_through;
// 选了服务器时,活跃 / 等级 / 收入 / 新用户 / PvP / 联盟 都取该服的视图(同一账号可能在多个服)
const X = (name) => (S.server !== 'all' && D.srv && D.srv[S.server]) ? D.srv[S.server][name] : D[name];
const S = {tab:'n601', w6:1, seg6:'all', w:30, plat:'all', band:'all', server:'all', dauMode:'dau', revMode:'revenue', lvlMetric:'users', cohDen:'reg'};
try { const s = JSON.parse(localStorage.getItem('iv-state')||'{}'); Object.assign(S, {w:30, w6:[1,0].includes(s.w6) ? s.w6 : S.w6, seg6:s.seg6||S.seg6, plat:s.plat||'all', band:s.band||'all', server:s.server||'all'}); } catch(e) {}
if (S.server !== 'all' && !(D.srv && D.srv[S.server])) S.server = 'all';
if (S.server !== 'all' && (S.band.startsWith('c:') || S.band.startsWith('v:'))) S.band = 'all';
if (!S.band.startsWith('c:') && !S.band.startsWith('v:')) S.band = 'all';   // 2026-10-21 去掉等级段筛选:之前存下的等级段选择一律回到全部
// 2026-11-03:顶部只放 601 各页;老服 9 页收进「老服」,下面一排二级页签
const OLD = ['home','newuser','life','game','pvp','ally','money','geo','alerts'], N6 = ['n601','n6tech','n6first','n6new','n6grow','n6pay','n6dq'];
const h = location.hash.slice(1); if ([...OLD, ...N6, 'defs'].includes(h)) S.tab = h;
let lastOld = OLD.includes(S.tab) ? S.tab : 'home';
const charts = [];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fi = (x) => x == null || isNaN(x) ? '—' : Math.round(x).toLocaleString('en-US');
const fm = (x, d=0) => x == null || isNaN(x) ? '—' : '$' + Number(x).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const fp = (x, d=1) => x == null || isNaN(x) ? '—' : (x*100).toFixed(d) + '%';
const dpct = (a, b) => (a == null || b == null || !b) ? null : (a - b) / b;
const sgn = (x, d=0) => x == null || isNaN(x) ? '' : `<span class="${x>0.0005?'up':x<-0.0005?'down':'flat'}">${x>0?'+':''}${(x*100).toFixed(d)}%</span>`;
const sgnpp = (a, b) => (a == null || b == null) ? '' : `<span class="${a-b>0.0005?'up':a-b<-0.0005?'down':'flat'}">${a-b>0?'+':''}${((a-b)*100).toFixed(1)}pp</span>`;
const md = (s) => s ? s.slice(5) : '';
const addDays = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0,10); };
const sum = (a) => a.reduce((x, y) => x + (y||0), 0);
const PL = {all:'全部', iOS:'iOS', Android:'Android'};
const CN = {sa:'沙特',eg:'埃及',dz:'阿尔及利亚',ye:'也门',ma:'摩洛哥',tn:'突尼斯',iq:'伊拉克',kw:'科威特',jo:'约旦',sy:'叙利亚',ae:'阿联酋',lb:'黎巴嫩',om:'阿曼',qa:'卡塔尔',bh:'巴林',ly:'利比亚',sd:'苏丹',ps:'巴勒斯坦',us:'美国','未知':'未知'};
const cname = (c) => (CN[c] ? CN[c] + (c === '未知' ? '' : ' ' + c) : c);
const segName = () => S.band === 'all' ? '全部' : S.band.startsWith('c:') ? cname(S.band.slice(2)) : S.band.startsWith('v:') ? '版本 ' + S.band.slice(2) : 'Lv' + S.band;
const segOnly = () => (S.band.startsWith('c:') || S.band.startsWith('v:')) ? S.band : 'all';   // 生命周期等按行展示等级段的卡片
const noSeg = (txt) => S.band !== 'all' ? `<span class="note">${txt || '本卡不随等级段 / 国家 / 版本筛选'}</span>` : '';
const w60 = () => Math.min(S.w, 60);   // 玩法 / PvP / 联盟只抓了 60 天

function segs(){
  const mk = (el, opts, key) => { el.innerHTML = opts.map(([v,l]) => `<button aria-pressed="${String(S[key])===String(v)}" data-v="${v}">${l}</button>`).join('');
    el.querySelectorAll('button').forEach(b => b.onclick = () => { S[key] = (key==='w' || key==='w6') ? +b.dataset.v : b.dataset.v; save(); draw(); }); };
  mk($('f-w'), WINS.map(w => [w, `近 ${w} 天`]), 'w');
  mk($('f-w6'), [[1, '近 1 天'], [0, '内测以来']], 'w6');   // 2026-11-05 去掉近 7 / 14 / 30 天(老板看趋势);趋势图和埋点块不随这个筛选
  // 2026-11-04:601 的平台 / 国家 / 版本筛选,一次只选一项
  const SG = (D.n601_seg || {}).segs || {}, SC = (D.n601_seg || {}).counts || {};
  if (S.seg6 !== 'all' && !SG[S.seg6]) S.seg6 = 'all';
  mk($('f-plat6'), [['all','全部'], ...['Android','iOS'].filter(v => SG['p:' + v]).map(v => ['p:' + v, v])], 'seg6');
  const sel6 = (el, pre, label) => { const ks = Object.keys(SG).filter(k => k.startsWith(pre));
    el.innerHTML = `<option value="">全部</option>` + ks.map(k => `<option value="${esc(k)}">${esc(label(k.slice(2)))}(${SG[k].n} 人)</option>`).join('');
    el.value = S.seg6.startsWith(pre) ? S.seg6 : ''; el.onchange = () => { S.seg6 = el.value || 'all'; save(); draw(); }; };
  sel6($('f-country6'), 'c:', cname); sel6($('f-ver6'), 'v:', (x) => x);
  mk($('f-plat'), [['all','全部'],['iOS','iOS'],['Android','Android']], 'plat');
  const selMk = (el, prefix, items, label) => { el.innerHTML = `<option value="">全部</option>` + items.map(x => `<option value="${esc(prefix + x)}">${esc(label(x))}</option>`).join('');
    el.value = S.band.startsWith(prefix) ? S.band : ''; el.onchange = () => { S.band = el.value || 'all'; save(); draw(); }; };
  selMk($('f-country'), 'c:', D.meta.countries || [], cname);
  selMk($('f-ver'), 'v:', D.meta.versions || [], (x) => x);
  const sv = $('f-srv'); sv.innerHTML = `<option value="all">全部正式服</option>` + (D.meta.servers || []).map(x => `<option value="${esc(x.id)}">${esc(x.id)} 服(30 天活跃 ${fi(x.active30)})</option>`).join('');
  sv.value = S.server; sv.onchange = () => { S.server = sv.value; if (S.server !== 'all' && (S.band.startsWith('c:') || S.band.startsWith('v:'))) S.band = 'all'; save(); draw(); };
  $('f-country').disabled = $('f-ver').disabled = S.server !== 'all';
  $('f-country').title = $('f-ver').title = S.server !== 'all' ? '选了服务器时不能按国家 / 版本筛选' : '';
  const go = (t) => { S.tab = t === 'old' ? lastOld : t; if (OLD.includes(S.tab)) lastOld = S.tab; history.replaceState(null, '', '#' + S.tab); draw(); window.scrollTo(0,0); };
  document.querySelectorAll('#tabs button').forEach(b => { b.setAttribute('aria-selected', b.dataset.tab === S.tab || (b.dataset.tab === 'old' && OLD.includes(S.tab))); b.onclick = () => go(b.dataset.tab); });
  document.querySelectorAll('#tabs2 button').forEach(b => { b.setAttribute('aria-selected', b.dataset.tab === S.tab); b.onclick = () => go(b.dataset.tab); });
  $('tabs2').classList.toggle('hidden', !OLD.includes(S.tab));
}
function save(){ try { localStorage.setItem('iv-state', JSON.stringify({w:S.w, w6:S.w6, seg6:S.seg6, plat:S.plat, band:S.band, server:S.server})); } catch(e) {} }
function info(key){ return `<button class="info" data-def="${key}" aria-label="指标定义">i</button>`; }
function bindInfo(){ document.querySelectorAll('[data-def]').forEach(b => b.onclick = () => {
  const d = DEFS[b.dataset.def]; if (!d) return;
  $('m-title').textContent = d[0];
  $('m-body').innerHTML = `<dt>定义</dt><dd>${esc(d[1])}</dd><dt>分子</dt><dd>${esc(d[2])}</dd><dt>分母</dt><dd>${esc(d[3])}</dd><dt>数据来源</dt><dd>${esc(d[4])}</dd><dt>其他</dt><dd>${esc(COMMON)}</dd><dt>更新时间</dt><dd>${esc(D.meta.run_at||'')}(数据截至 ${esc(END)})</dd>`;
  $('modal').classList.remove('hidden'); $('m-close').focus(); }); }
$('m-close').onclick = () => $('modal').classList.add('hidden');
$('modal').onclick = (e) => { if (e.target.id === 'modal') $('modal').classList.add('hidden'); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('modal').classList.add('hidden'); });
function link(tab, txt){ return `<button class="link" data-go="${tab}">${txt} →</button>`; }
function bindLinks(){ document.querySelectorAll('[data-go]').forEach(b => b.onclick = () => { S.tab = b.dataset.go; if (OLD.includes(S.tab)) lastOld = S.tab; history.replaceState(null,'','#'+S.tab); draw(); window.scrollTo(0,0); }); }

// ---------- 数据访问
const daily = () => { const c = X('daily').columns, rows = X('daily').series[`${S.plat}|${S.band}`] || []; return rows.map(r => Object.fromEntries(c.map((k,i) => [k, r[i]]))); };
const kpi = () => (X('kpi')[`${S.w}|${S.plat}|${S.band}`] || {});
const nud = (plat) => { const c = X('new_user').daily.columns; return (X('new_user').daily.series[plat||S.plat] || []).map(r => Object.fromEntries(c.map((k,i) => [k, r[i]]))); };
function cohortRate(rows, num, N, w){  // 已满 N 天的最近 w 个注册日
  const ok = rows.filter(r => addDays(r.date, N) <= END); const cur = ok.slice(-w), prev = ok.slice(-2*w, -w);
  const rate = (a) => { const n = sum(a.map(r => r.registrations)); return n ? sum(a.map(r => r[num])) / n : null; };
  return {cur: rate(cur), prev: rate(prev), from: cur.length ? cur[0].date : null, to: cur.length ? cur[cur.length-1].date : null, n: sum(cur.map(r => r.registrations))};
}
function win(rows, w){ return {cur: rows.slice(-w), prev: rows.slice(-2*w, -w)}; }
function ratio(rows, a, b){ const d = sum(rows.map(r => r[b])); return d ? sum(rows.map(r => r[a])) / d : null; }
const rangeDays = () => 30;   // 2026-11-05 老服去掉时间筛选,趋势统一看近 30 天(用户确认)

// ---------- 图表
// 2026-11-04 601 版本 / 投放 / 活动日历(D.n601_events):趋势图按天标出。活动 = 浅金色底,单日事件(发版、开投)= 虚线
function evPlugin(dates){
  const wins = [];
  (D.n601_events || []).filter(e => e.start).forEach(e => (e.windows || [[e.start, e.end]]).forEach((w, k) =>
    wins.push({name:e.name, kind:e.kind, a:w[0].slice(0,10), b:(w[1] || w[0]).slice(0,10), point:!w[1], first:k === 0})));
  return {id:'evb', beforeDatasetsDraw(ch){
    if (!dates || !dates.length) return;
    const xs = ch.scales.x, a = ch.chartArea, g = ch.ctx, step = dates.length > 1 ? xs.getPixelForValue(1) - xs.getPixelForValue(0) : 20;
    let row = 0; g.save(); g.font = '10px ' + css('--font-ui');
    wins.forEach(w => {
      const i0 = dates.findIndex(d => d >= w.a); let j1 = -1; dates.forEach((d, i) => { if (d <= w.b) j1 = i; });
      if (i0 < 0 || j1 < i0) return;
      const x0 = xs.getPixelForValue(i0) - step / 2, x1 = xs.getPixelForValue(j1) + step / 2;
      if (w.point) { g.strokeStyle = css('--muted'); g.setLineDash([3,3]); g.beginPath(); g.moveTo(x0, a.top); g.lineTo(x0, a.bottom); g.stroke(); g.setLineDash([]); }
      else { g.fillStyle = 'rgba(201,150,40,0.12)'; g.fillRect(x0, a.top, x1 - x0, a.bottom - a.top); }
      if (w.first) { g.fillStyle = css('--muted'); const tw_ = g.measureText(w.name).width, tx = x0 + 3 + tw_ > a.right ? x0 - tw_ - 3 : x0 + 3; g.fillText(w.name, tx, a.top + 10 + (row++ % 3) * 11); }   // 靠右边的标签往左写,避免被截断
    });
    g.restore(); }};
}
function mkChart(id, cfg){
  const el = $(id); if (!el) return;
  if (cfg.evDates) { cfg.plugins = (cfg.plugins || []).concat([evPlugin(cfg.evDates)]); delete cfg.evDates; }
  const ink = css('--muted'), grid = css('--grid');
  cfg.options = Object.assign({responsive:true, maintainAspectRatio:false, animation:false, interaction:{mode:'index', intersect:false},
    plugins:{legend:{labels:{color:ink, boxWidth:10, boxHeight:10, font:{size:11}}}, tooltip:{}}}, cfg.options||{});
  const sc = cfg.options.scales = cfg.options.scales || {x:{}, y:{}};
  Object.values(sc).forEach(a => { a.ticks = Object.assign({color:ink, font:{size:11}, maxTicksLimit:8}, a.ticks||{}); a.grid = Object.assign({color:grid}, a.grid||{}); a.border = {display:false}; });
  charts.push(new Chart(el, cfg));
}
const ma = (arr, k) => arr.map((_, i) => i < k-1 ? null : sum(arr.slice(i-k+1, i+1)) / k);
const rollRatio = (rows, a, b, k) => rows.map((_, i) => { if (i < k-1) return null; const s = rows.slice(i-k+1, i+1); const d = sum(s.map(r => r[b])); return d ? sum(s.map(r => r[a])) / d : null; });

// ---------- 组件
function kpiCard(o){
  return `<div class="kpi"><div class="lab"><span>${esc(o.label)}</span>${o.def?info(o.def):''}</div><div class="val">${o.val}</div>${(o.lines||[]).map(l => `<div class="dl">${l}</div>`).join('')}</div>`;
}
function funnelHTML(f){
  if (!f || !f.n) return '<div class="empty">这个时间段没有满 30 天的注册账号</div>';
  const s = f.steps, top = s[0][1] || 1; let worst = -1, wv = -1;
  for (let i = 1; i < s.length; i++) { const drop = s[i-1][1] ? 1 - s[i][1]/s[i-1][1] : 0; if (s[i-1][1] >= 10 && drop > wv) { wv = drop; worst = i; } }
  return `<div class="funnel">` + s.map((x, i) => {
    const conv = i ? (s[i-1][1] ? x[1]/s[i-1][1] : null) : 1;
    return `<div class="fr ${i===worst?'worst':''}"><span>${esc(x[0])}</span><div class="fb" style="width:${Math.max(0.4, x[1]/top*100)}%"></div><span class="n">${fi(x[1])} · ${fp(x[1]/top)}${i?` · 本步 ${fp(conv,0)}`:''}</span></div>`;
  }).join('') + `<div class="fr"><span>30 天内付费(不嵌套)</span><div class="fb" style="width:${Math.max(0.4, f.pay30/top*100)}%;background:var(--gold)"></div><span class="n">${fi(f.pay30)} · ${fp(f.pay30/top)}</span></div></div>
  <div class="note">注册于 ${f.from} ~ ${f.to}(全部已满 30 天,所以比所选时间段早 30 天)。每层只算上一层的人;红色 = 流失比例最大的一步。</div>`;
}
function statusPill(s){ return `<span class="pill p-${s}">${{red:'需关注',yellow:'观察中',green:'正常',info:'提示'}[s]||s}</span>`; }

// ================= 首页
function home(){
  const dl = daily(), last = dl[dl.length-1] || {}, lw = dl[dl.length-8] || {};
  const k = kpi(), kc = k.cur || {}, kp = k.prev || {};
  const nu = nud(), nA = nud('Android'), nI = nud('iOS');
  const W = win(nu, S.w);
  const regC = sum(W.cur.map(r => r.registrations)), regP = sum(W.prev.map(r => r.registrations));
  const er = (rows) => ratio(rows, 'entered', 'registrations');
  const erC = er(W.cur), erP = er(W.prev);
  const l3C = ratio(W.cur, 'lv3', 'entered'), l3P = ratio(W.prev, 'lv3', 'entered');
  const d1 = cohortRate(nu, 'd1', 1, S.w), d7 = cohortRate(nu, 'd7', 7, S.w);
  const al = (D.alerts || []).filter(a => a.persistent !== false && a.level !== 'info'), stOf = (dim) => (D.health.find(x => x.key === dim) || {}).status;
  const bandNote = S.band !== 'all' ? '<span class="note">新用户类指标不随等级段筛选</span>' : '';
  let html = `<section id="sec-home">
  ${todayCard('home')}
  <div class="kpis">
   ${kpiCard({label:'DAU', def:'dau', val:fi(last.dau), st:stOf('eng'), lines:[`${md(last.date)} · 较上周同日 ${sgn(dpct(last.dau, lw.dau))}`, `近 7 天均值 ${fi(sum(dl.slice(-7).map(r=>r.dau))/7)}`]})}
   ${kpiCard({label:`新注册 · 近 ${S.w} 天`, def:'reg', val:fi(regC), st:stOf('acq'), lines:[`较前 ${S.w} 天 ${sgn(dpct(regC, regP))}`, `${md(END)} 当天 ${fi((nu[nu.length-1]||{}).registrations)}`]})}
   ${kpiCard({label:'进入游戏率', def:'entry', val:fp(erC), st:stOf('funnel'), lines:[`较前 ${S.w} 天 ${sgnpp(erC, erP)}`, `Android ${fp(er(win(nA,S.w).cur),0)} · iOS ${fp(er(win(nI,S.w).cur),0)}`]})}
   ${kpiCard({label:'当天到 Lv3', def:'lv3', val:fp(l3C), lines:[`较前 ${S.w} 天 ${sgnpp(l3C, l3P)}`, `Android ${fp(ratio(win(nA,S.w).cur,'lv3','entered'),0)} · iOS ${fp(ratio(win(nI,S.w).cur,'lv3','entered'),0)}`]})}
   ${kpiCard({label:'D1 留存', def:'d1', val:fp(d1.cur), st:stOf('ret'), lines:[`较前期 ${sgnpp(d1.cur, d1.prev)}`, `注册于 ${md(d1.from)}~${md(d1.to)}`]})}
   ${kpiCard({label:'D7 留存', def:'d7', val:fp(d7.cur), lines:[`较前期 ${sgnpp(d7.cur, d7.prev)}`, `注册于 ${md(d7.from)}~${md(d7.to)}`]})}
   ${kpiCard({label:`收入 · 近 ${S.w} 天`, def:'revenue', val:fm(kc.revenue), st:stOf('mon'), lines:[`较前 ${S.w} 天 ${sgn(dpct(kc.revenue, kp.revenue))}`, `${md(END)} 当天 ${fm(last.revenue)}`]})}
   ${kpiCard({label:'付费人数', def:'payers', val:fi(kc.payers), lines:[`较前 ${S.w} 天 ${sgn(dpct(kc.payers, kp.payers))}`, `付费率 ${fp(kc.pay_rate)}`]})}
   ${kpiCard({label:'ARPPU', def:'arppu', val:fm(kc.arppu), lines:[`较前 ${S.w} 天 ${sgn(dpct(kc.arppu, kp.arppu))}`, `ARPU ${fm(kc.arpu, 2)}`]})}
  </div>${bandNote}
  <div class="grid">
   <div class="card"><h3>活跃趋势</h3><div class="sub"><span class="seg" id="dau-mode"></span> 细线 = 7 日均线,虚线 = 28 日均线</div><div class="chart"><canvas id="c-dau"></canvas></div></div>
   <div class="card"><h3>收入趋势</h3><div class="sub"><span class="seg" id="rev-mode"></span> 收入降了要看是付费人数少了,还是 ARPPU 低了</div><div class="chart"><canvas id="c-rev"></canvas></div></div>
  </div>
  <div class="grid">
   <div class="card"><h3>新用户漏斗(严格嵌套) · ${PL[S.plat]}</h3>${funnelHTML(X('new_user').funnel[`${S.w}|${S.plat}`])}</div>
  </div>
  <div class="grid">
   <div class="card"><h3>新用户当天到 Lv3 转化</h3><div class="sub">7 日滚动;最大的新手断点,分平台看</div><div class="chart"><canvas id="c-lv3"></canvas></div></div>
   <div class="card"><h3>D1 / D7 留存 · 按注册周</h3><div class="sub">注册口径,只画已满期的周</div><div class="chart"><canvas id="c-ret"></canvas></div></div>
  </div>
  <div class="card"><h3>玩法健康矩阵 · 近 ${w60()} 天 · ${PL[S.plat]}${S.server !== 'all' ? ' · 全部正式服(不随服务器筛选)' : ''}</h3><div class="sub">横轴 = 参与率,纵轴 = 参与者与未参与者 15 天留存之差(同等级段加权),气泡大小 = 参与人数;虚线 = 各玩法的中位数。<b>只是相关性,不表示该玩法提升留存</b></div><div class="chart tall"><canvas id="c-mx"></canvas></div>${link('game','玩法详情')}</div>
  <div class="card"><h3>大 R 监控${S.server !== 'all' ? ' · 全部正式服' : ''}</h3>${whaleSummary()}${link('money','大 R 风险表')}</div>
  </section>`;
  $('root').innerHTML = html;
  const seg = (id, key, opts, fn) => { const el = $(id); el.innerHTML = opts.map(([v,l]) => `<button aria-pressed="${S[key]===v}" data-v="${v}">${l}</button>`).join(''); el.querySelectorAll('button').forEach(b => b.onclick = () => { S[key] = b.dataset.v; draw(); }); };
  seg('dau-mode', 'dauMode', [['dau','DAU'],['wau','WAU'],['mau','MAU']]);
  seg('rev-mode', 'revMode', [['revenue','收入'],['payers','付费人数'],['arppu','ARPPU']]);
  const R = dl.slice(-rangeDays()), lab = R.map(r => md(r.date));
  const acc = css('--accent'), gold = css('--gold'), slate = css('--slate');
  const v = R.map(r => r[S.dauMode]);
  mkChart('c-dau', {type:'line', data:{labels:lab, datasets:[{label:S.dauMode.toUpperCase(), data:v, borderColor:acc, borderWidth:2, pointRadius:0, tension:0},
    {label:'7 日均线', data:ma(v,7), borderColor:slate, borderWidth:1, pointRadius:0}, {label:'28 日均线', data:ma(dl.map(r=>r[S.dauMode]),28).slice(-R.length), borderColor:gold, borderWidth:1.5, borderDash:[5,4], pointRadius:0}]}});
  const rv = R.map(r => S.revMode === 'arppu' ? (r.payers ? r.revenue / r.payers : null) : r[S.revMode]);
  mkChart('c-rev', {data:{labels:lab, datasets:[{type:'bar', label:{revenue:'日收入 $', payers:'日付费人数', arppu:'日 ARPPU $'}[S.revMode], data:rv, backgroundColor:acc, borderRadius:3},
    {type:'line', label:'7 日均线', data:ma(rv.map(x=>x||0),7), borderColor:gold, borderWidth:2, pointRadius:0}]}});
  const lv = (rows) => rollRatio(rows, 'lv3', 'entered', 7);
  const RA = nA.slice(-rangeDays()), RI = nI.slice(-rangeDays());
  mkChart('c-lv3', {type:'line', data:{labels:RA.map(r=>md(r.date)), datasets:[{label:'Android', data:lv(nA).slice(-RA.length), borderColor:acc, borderWidth:2, pointRadius:0}, {label:'iOS', data:lv(nI).slice(-RI.length), borderColor:gold, borderWidth:2, pointRadius:0}]},
    options:{scales:{x:{}, y:{ticks:{callback:(x)=>Math.round(x*100)+'%'}, min:0}}}});
  retChart('c-ret');
  matrixChart('c-mx');
  bindInfo(); bindLinks();
}
function retChart(id){
  const C = X('new_user').cohort[S.plat] || [];
  mkChart(id, {type:'line', data:{labels:C.map(r => md(r.week)), datasets:[{label:'D1', data:C.map(r => r.D1), borderColor:css('--accent'), borderWidth:2, pointRadius:2}, {label:'D7', data:C.map(r => r.D7), borderColor:css('--gold'), borderWidth:2, pointRadius:2}]},
    options:{scales:{x:{}, y:{min:0, ticks:{callback:(x)=>(x*100).toFixed(0)+'%'}}}}});
}
function healthChips(){
  const el = $('health'); if (!el) return;
  el.innerHTML = D.health.map(x => `<button class="hb ${x.status}" data-dim="${x.key}" aria-expanded="false"><span class="t">${esc(x.name)}</span><span class="s">${{red:'🔴 需关注',yellow:'🟡 观察中',green:'🟢 正常'}[x.status]}</span></button>`).join('');
  el.querySelectorAll('.hb').forEach(b => b.onclick = () => {
    el.querySelectorAll('.hb').forEach(x => x.setAttribute('aria-expanded', 'false')); b.setAttribute('aria-expanded', 'true');
    const items = (D.alerts||[]).filter(a => a.dim === b.dataset.dim);
    $('health-why').innerHTML = items.length ? items.map(a => `· ${a.level==='info'?'[提示] ':''}${esc(a.metric)}:${esc(fmtAlertVal(a.current, a))}${a.baseline!=null?'(基准 '+esc(fmtAlertVal(a.baseline, a))+')':''}${a.note?' — '+esc(a.note):''}`).join('<br>') : '· 没有触发告警';
  });
}
function fmtAlertVal(v, a){ if (v == null) return '—'; if (a.metric.includes('率') || a.metric.includes('转化') || a.metric.includes('留存')) return fp(v); if (a.metric.includes('收入') || a.metric.includes('ARPPU')) return fm(v); if (a.category === '大 R') return fi(v) + ' 人'; return fi(v); }
function alertTable(rows, compact){
  if (!rows.length) return '<div class="empty">没有触发告警</div>';
  return `<div class="tw"><table><thead><tr><th>级别</th><th>指标</th><th>当前</th><th>基准</th><th>偏离</th>${compact?'':'<th>类别</th><th>说明</th>'}</tr></thead><tbody>` +
    rows.map(a => `<tr><td>${statusPill(a.level)}</td><td class="l">${esc(a.metric)}</td><td>${esc(fmtAlertVal(a.current,a))}</td><td>${esc(fmtAlertVal(a.baseline,a))}</td><td>${a.deviation==null?'—':sgn(a.deviation)}</td>${compact?'':`<td>${esc(a.category)}</td><td class="l">${esc(a.note||'')}</td>`}</tr>`).join('') + '</tbody></table></div>';
}
function whaleSummary(){
  const W = D.money.whales || [], c = (s) => W.filter(w => w.status === s).length;
  const top = W.filter(w => w.status !== 'green').slice(0, 5);
  return `<div class="note">大 R = 近 90 天累计付费 ≥ $1,000,共 ${W.length} 人:${statusPill('red')} ${c('red')} 人(停止登录或停止付费)· ${statusPill('yellow')} ${c('yellow')} 人(付费或活跃下降,仍在登录)· ${statusPill('green')} ${c('green')} 人</div>` +
    (top.length ? `<div class="tw"><table><thead><tr><th>玩家 ID</th><th>近 90 天</th><th>近 30 天</th><th>前 30 天</th><th>状态</th></tr></thead><tbody>${top.map(w => `<tr><td>${w.id}</td><td>${fm(w.rev90)}</td><td>${fm(w.pay30)}</td><td>${fm(w.pay_prev30)}</td><td>${statusPill(w.status)}</td></tr>`).join('')}</tbody></table></div>` : '');
}
function problems(){
  const P = D.problems || [];
  if (!P.length) return '<div class="empty">当前没有需要关注的情况</div>';
  return P.map((p, i) => `<div class="prob ${p.severity}"><div class="pt">${i+1}. ${esc(p.title)}</div><dl><dt>证据</dt><dd>${esc(p.evidence)}</dd><dt>影响</dt><dd>${esc(p.impact)}</dd></dl>${link(p.page,'看详情')}</div>`).join('');
}

// ================= 新用户
function newuser(){
  const nu = nud(), W = win(nu, S.w);
  const reg = sum(W.cur.map(r=>r.registrations)), regP = sum(W.prev.map(r=>r.registrations));
  const er = ratio(W.cur,'entered','registrations'), erP = ratio(W.prev,'entered','registrations');
  const l3 = ratio(W.cur,'lv3','entered'), l3P = ratio(W.prev,'lv3','entered');
  const d1 = cohortRate(nu,'d1',1,S.w), d7 = cohortRate(nu,'d7',7,S.w), d30 = cohortRate(nu,'d30',30,S.w), p30 = cohortRate(nu,'pay30',30,S.w);
  const k = kpi().cur || {};
  $('root').innerHTML = `<section id="sec-newuser">
  <div class="kpis">
   ${kpiCard({label:`注册 · 近 ${S.w} 天`, def:'reg', val:fi(reg), lines:[`较前 ${S.w} 天 ${sgn(dpct(reg, regP))}`]})}
   ${kpiCard({label:'进入游戏率', def:'entry', val:fp(er), lines:[`较前期 ${sgnpp(er, erP)}`]})}
   ${kpiCard({label:'当天到 Lv3', def:'lv3', val:fp(l3), lines:[`较前期 ${sgnpp(l3, l3P)}`, '分母 = 进入游戏的人']})}
   ${kpiCard({label:'D1', def:'d1', val:fp(d1.cur), lines:[`较前期 ${sgnpp(d1.cur, d1.prev)}`, `${md(d1.from)}~${md(d1.to)} · ${fi(d1.n)} 人`]})}
   ${kpiCard({label:'D7', def:'d7', val:fp(d7.cur), lines:[`较前期 ${sgnpp(d7.cur, d7.prev)}`, `${md(d7.from)}~${md(d7.to)} · ${fi(d7.n)} 人`]})}
   ${kpiCard({label:'D30', def:'d30', val:fp(d30.cur), lines:[`较前期 ${sgnpp(d30.cur, d30.prev)}`, `${md(d30.from)}~${md(d30.to)} · ${fi(d30.n)} 人`]})}
   ${kpiCard({label:'30 天内付费率', def:'pay30', val:fp(p30.cur, 2), lines:[`${md(p30.from)}~${md(p30.to)}`]})}
   ${kpiCard({label:'每个新注册用户收入', def:'rev_new', val:fm(k.rev_per_new_user, 2), lines:[`近 ${S.w} 天注册 ${fi(k.registrations)} 人`]})}
  </div><span class="note">新注册已剔除 601 新版内测服的账号 ${fi(D.meta.n601_excluded)} 个(它们不写老版登录日志,会被误算成「注册了没进游戏」)。${D.meta.farm && D.meta.farm.n ? `另剔除疑似刷量注册 ${fi(D.meta.farm.n)} 个(机型 ${esc(D.meta.farm.models.join('、'))},${md(D.meta.farm.first)} 起注册当天没进游戏的号;规则:近 28 天单一机型注册 ≥ 50 且注册当天进入游戏 < 10%,这些机型里进了游戏的照常计入)。` : ''}${S.band!=='all'?'本页只随时间、平台筛选,不随等级段 / 国家 / 版本筛选。':''}</span>
  <div class="grid">
   <div class="card"><h3>新手漏斗(严格嵌套) · ${PL[S.plat]}</h3>${funnelHTML(X('new_user').funnel[`${S.w}|${S.plat}`])}</div>
   <div class="card"><h3>当天到 Lv3 转化(Android / iOS)</h3><div class="sub">7 日滚动;虚线 = 该平台前 28 天平均</div><div class="chart"><canvas id="c-lv3b"></canvas></div></div>
  </div>
  <div class="grid">
   <div class="card"><h3>注册 → 进入游戏率(Android / iOS)</h3><div class="sub">7 日滚动;单平台断崖通常是客户端或渠道问题</div><div class="chart"><canvas id="c-entry"></canvas></div></div>
   <div class="card"><h3>每日注册(按平台)</h3><div class="sub">突然放量也要看:可能是买量、刷量或测试设备</div><div class="chart"><canvas id="c-regs"></canvas></div></div>
  </div>
  <div class="card"><h3>Cohort 留存 · 按注册周 · ${PL[S.plat]}</h3><div class="sub"><span class="seg" id="coh-den"></span> 空格 = 该周还没满期</div>${cohortTable()}</div>
  <div class="grid">
   <div class="card"><h3>新用户成长速度</h3><div class="sub">注册后 N 天内达到的最高主城等级分布 · ${esc(X('new_user').progression[S.plat].from||'')} ~ ${esc(X('new_user').progression[S.plat].to||'')} 注册且当天进入游戏的 ${fi(X('new_user').progression[S.plat].n)} 人</div>${progTable()}</div>
   <div class="card"><h3>进入游戏率下钻 · 近 28 天</h3><div class="sub">按系统版本 / 机型,只列注册最多的;进入率 < 30% 且注册 ≥ 20 的标红,常见原因是模拟器或测试设备</div>${drillTables()}</div>
  </div></section>`;
  const segEl = $('coh-den'); segEl.innerHTML = [['reg','分母 = 注册'],['ent','分母 = 进入游戏']].map(([v,l]) => `<button aria-pressed="${S.cohDen===v}" data-v="${v}">${l}</button>`).join('');
  segEl.querySelectorAll('button').forEach(b => b.onclick = () => { S.cohDen = b.dataset.v; draw(); });
  const nA = nud('Android'), nI = nud('iOS'), n = rangeDays(), lab = nA.slice(-n).map(r => md(r.date));
  const acc = css('--accent'), gold = css('--gold');
  const ref = (rows, a, b) => { const p = rows.slice(-35, -7); const v = ratio(p, a, b); return Array(n).fill(v); };
  mkChart('c-lv3b', {type:'line', data:{labels:lab, datasets:[
    {label:'Android', data:rollRatio(nA,'lv3','entered',7).slice(-n), borderColor:acc, borderWidth:2, pointRadius:0},
    {label:'iOS', data:rollRatio(nI,'lv3','entered',7).slice(-n), borderColor:gold, borderWidth:2, pointRadius:0},
    {label:'Android 前 28 天', data:ref(nA,'lv3','entered'), borderColor:acc, borderWidth:1, borderDash:[4,4], pointRadius:0},
    {label:'iOS 前 28 天', data:ref(nI,'lv3','entered'), borderColor:gold, borderWidth:1, borderDash:[4,4], pointRadius:0}]},
    options:{scales:{x:{}, y:{min:0, ticks:{callback:(x)=>Math.round(x*100)+'%'}}}}});
  mkChart('c-entry', {type:'line', data:{labels:lab, datasets:[
    {label:'Android', data:rollRatio(nA,'entered','registrations',7).slice(-n), borderColor:acc, borderWidth:2, pointRadius:0},
    {label:'iOS', data:rollRatio(nI,'entered','registrations',7).slice(-n), borderColor:gold, borderWidth:2, pointRadius:0}]},
    options:{scales:{x:{}, y:{min:0, max:1, ticks:{callback:(x)=>Math.round(x*100)+'%'}}}}});
  mkChart('c-regs', {type:'bar', data:{labels:lab, datasets:[
    {label:'Android', data:nA.slice(-n).map(r=>r.registrations), backgroundColor:acc, stack:'s'},
    {label:'iOS', data:nI.slice(-n).map(r=>r.registrations), backgroundColor:gold, stack:'s'}]},
    options:{scales:{x:{stacked:true}, y:{stacked:true}}}});
  bindInfo(); bindLinks();
}
function cohortTable(){
  const C = X('new_user').cohort[S.plat] || [], cols = ['D0','D1','D3','D7','D14','D30'], acc = css('--accent');
  const cell = (v) => v == null ? '<td></td>' : `<td style="background:color-mix(in srgb, ${acc} ${Math.min(85, v*100*(S.cohDen==='reg'?2.2:1.2))}%, transparent)">${fp(v)}</td>`;
  return `<div class="tw"><table class="heat"><thead><tr><th>注册周</th><th>注册</th><th>进入游戏</th>${cols.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>` +
    C.slice().reverse().map(r => `<tr><td>${r.week}</td><td>${fi(r.n)}</td><td>${fi(r.entered)}</td>${cols.map(c => c==='D0' ? (S.cohDen==='reg' ? cell(r.D0) : cell(r.entered?1:null)) : cell(S.cohDen==='reg' ? r[c] : r[c+'_e'])).join('')}</tr>`).join('') + '</tbody></table></div>';
}
function progTable(){
  const P = X('new_user').progression[S.plat]; if (!P || !P.n) return '<div class="empty">样本不足</div>';
  const rows = ['D0','D1','D3','D7','D14','D30'];
  return `<div class="tw"><table><thead><tr><th>注册后</th>${BANDS.map(b=>`<th>Lv${b}</th>`).join('')}</tr></thead><tbody>` +
    rows.map(k => `<tr><td>${k} 内</td>${P.dist[k].map(v => `<td>${fp(v/P.n)}</td>`).join('')}</tr>`).join('') + '</tbody></table></div>' +
    `<div class="note">30 天内到达:${Object.entries(P.reach_d30).map(([l,v]) => `Lv${l} ${fp(v)}`).join(' · ')}</div>`;
}
function drillTables(){
  const E = X('new_user').entry_drill, t = (rows, head) => `<div class="tw"><table><thead><tr><th>平台</th><th>${head}</th><th>注册</th><th>进入</th><th>进入率</th></tr></thead><tbody>` +
    rows.filter(r => S.plat === 'all' || r[0] === S.plat).map(r => { const rate = r[2] ? r[3]/r[2] : null, bad = rate != null && rate < 0.3 && r[2] >= 20;
      return `<tr><td>${esc(r[0])}</td><td class="l">${esc(r[1])}</td><td>${fi(r[2])}</td><td>${fi(r[3])}</td><td>${bad?statusPill('red')+' ':''}${fp(rate,0)}</td></tr>`; }).join('') + '</tbody></table></div>';
  return t(E.by_sys, '系统版本') + t(E.by_phone, '机型') + `<div class="note">注册于 ${E.from} 起</div>`;
}

// ================= 生命周期
function life(){
  const L = X('life')[`${S.w}|${S.plat}|${segOnly()}`] || {rows:[]}, ret = X('life').retention15.rows[S.plat] || [], ch = X('life').churn.rows[S.plat] || [];
  const LC = D.level_cap;
  const lcBins = LC ? [[1,5],[6,10],[11,15],[16,20],[21,LC.cap-1],[LC.cap,LC.cap]].map(([lo,hi]) => { const xs = LC.dist.filter(d => d.lv >= lo && d.lv <= hi); return {name: lo === hi ? `${lo}(上限)` : `${lo}–${hi}`, n: sum(xs.map(d => d.n)), payers: sum(xs.map(d => d.payers)), rev: sum(xs.map(d => d.rev))}; }) : [];
  $('root').innerHTML = `<section id="sec-life">
  ${LC ? `<div class="card"><h3>主城(政府)等级到顶</h3><div class="sub">全量计算,不随筛选变化。上限取登录日志里出现过的最高等级(${LC.cap} 级);同一账号多个服取最高。近 30 天活跃 ${fi(LC.active30)} 人,其中 <b>${fi(LC.at_cap.n)} 人(${fp(LC.at_cap.share)})在 ${LC.cap} 级</b>,付费 ${LC.at_cap.payers} 人,贡献近 30 天收入 ${fm(LC.at_cap.rev)}(${fp(LC.at_cap.rev_share)})</div>
   <div class="grid">
    <div><div class="tw"><table><thead><tr><th>主城等级</th><th>近 30 天活跃</th><th>占比</th><th>付费人数</th><th>收入</th><th>收入占比</th></tr></thead><tbody>${lcBins.map(b => `<tr><td>${b.name}</td><td>${fi(b.n)}</td><td>${fp(b.n / LC.active30)}</td><td>${fi(b.payers)}</td><td>${fm(b.rev)}</td><td>${LC.rev30 ? fp(b.rev / LC.rev30) : '—'}</td></tr>`).join('')}</tbody></table></div>
     ${LC.rev30_no_login ? `<div class="note">另有 ${fm(LC.rev30_no_login)} 收入来自窗口内没有登录记录的账号,不在上表</div>` : ''}</div>
    <div><div class="tw" style="max-height:320px"><table><thead><tr><th>周</th><th>当周活跃</th><th>在上限</th><th>占比</th><th>上限玩家收入</th><th>占当周收入</th></tr></thead><tbody>${[...LC.trend].reverse().map(t => `<tr><td>${md(t.from)}–${md(t.to)}</td><td>${fi(t.active)}</td><td>${fi(t.at_cap)}</td><td>${fp(t.share)}</td><td>${fm(t.rev_cap)}</td><td>${t.rev_share != null ? fp(t.rev_share) : '—'}</td></tr>`).join('')}</tbody></table></div>
     <div class="note">在上限的人数每周基本稳定,占比的起伏主要来自分母(当周活跃)变化,看趋势时两列一起看</div></div>
   </div></div>` : ''}
  <div class="grid">
   <div class="card"><h3>主城升级速度(中位天数)</h3><div class="sub">按「账号 × 服」计算首次被观察到达各级的日期之差;没登录的日子看不到,所以会出现「回来时已连升几级」的 0 天</div><div class="chart"><canvas id="c-speed"></canvas></div>
    <div class="tw"><table><thead><tr><th>阶段</th><th>样本</th><th>中位天数</th><th>P75</th></tr></thead><tbody>${X('life').speed.map(s => s.n >= 30 ? `<tr><td>Lv${s.from} → Lv${s.to}</td><td>${fi(s.n)}</td><td>${s.median ?? '—'}</td><td>${s.p75 ?? '—'}</td></tr>` : `<tr><td>Lv${s.from} → Lv${s.to}</td><td>${fi(s.n)}</td><td colspan="2" class="note">样本不足 30,不显示</td></tr>`).join('')}</tbody></table></div></div>
  </div></section>`;
  const acc = css('--accent'), bad = css('--bad');
  const okS = (s) => s.n >= 30;   // 样本不足 30 不下结论
  mkChart('c-speed', {type:'bar', data:{labels:X('life').speed.map(s => `${s.from}→${s.to}`), datasets:[{label:'中位天数', data:X('life').speed.map(s => okS(s) ? s.median : null), backgroundColor:acc, borderRadius:4}, {label:'P75', data:X('life').speed.map(s => okS(s) ? s.p75 : null), backgroundColor:css('--grid'), borderRadius:4}]}});
  bindInfo(); bindLinks();
}

// ================= 商业化与大 R
function money(){
  const k = kpi(), c = k.cur || {}, p = k.prev || {}, M = D.money;
  const dw = {7:'7', 14:'30', 30:'30', 90:'90'}[S.w], ds = (M.diamond_struct||{})[dw], dl = (M.diamond_ledger||{})[dw];
  const ch = (M.channels||{})[String(S.w)] || [], chTot = sum(ch.map(r => r[1]));
  $('root').innerHTML = `<section id="sec-money">
  <div class="kpis">
   ${kpiCard({label:`收入 · 近 ${S.w} 天`, def:'revenue', val:fm(c.revenue), lines:[`较前期 ${sgn(dpct(c.revenue,p.revenue))}`]})}
   ${kpiCard({label:'付费人数', def:'payers', val:fi(c.payers), lines:[`较前期 ${sgn(dpct(c.payers,p.payers))}`]})}
   ${kpiCard({label:'付费率', def:'pay_rate', val:fp(c.pay_rate), lines:[`较前期 ${sgnpp(c.pay_rate,p.pay_rate)}`, `活跃 ${fi(c.active)} 人`]})}
   ${kpiCard({label:'ARPU', def:'arpu', val:fm(c.arpu,2), lines:[`较前期 ${sgn(dpct(c.arpu,p.arpu))}`]})}
   ${kpiCard({label:'ARPPU', def:'arppu', val:fm(c.arppu), lines:[`较前期 ${sgn(dpct(c.arppu,p.arppu))}`]})}
   ${kpiCard({label:'新付费人数', def:'new_payers', val:fi(c.new_payers), lines:[`前期 ${fi(p.new_payers)}`]})}
   ${kpiCard({label:'复购付费人数', def:'repeat_payers', val:fi(c.repeat_payers), lines:[`前期 ${fi(p.repeat_payers)}`]})}
   ${kpiCard({label:'每个新注册用户收入', def:'rev_new', val:fm(c.rev_per_new_user,2), lines:[`前期 ${fm(p.rev_per_new_user,2)}`]})}
  </div>
  <div class="card"><h3>收入 / 付费人数 / ARPPU</h3><div class="sub">三者同屏:收入变化来自人数还是客单价</div><div class="chart tall"><canvas id="c-m3"></canvas></div></div>
  <div class="grid">
   ${D.rev_func ? (() => { const R = D.rev_func, ex = Object.fromEntries(R.by_func_ex3.map(x => [x[0], x[1]])), exTot = R.diamond_rev - R.top3_rev;
    return `<div class="card"><h3>收入按功能拆 · 近 ${R.days} 天(第一版)</h3><div class="sub">${md(R.from)}–${md(R.to)},全部正式服,不含 601,不随筛选变化。订单先按商品分类;<b>钻石包</b>的钱再按每个付费者同期的钻石去向按比例分摊(竞猜、老虎机按下注 − 返还,赢了记 0)。<b>只能作参考</b>:付费者这段时间花掉 ${fi(R.spent)} 钻,其中花钱买来的只有 ${fi(R.bought)} 钻(${fp(R.bought_ratio)}),其余来自 WPP、GameAPI、活动和竞猜返还等,钻石不分付费 / 免费,所以这张表说明的是「付费者把钻石花在哪」,不等于「钱买了什么」</div>
    <div class="grid"><div><div class="tw"><table><thead><tr><th>商品类别</th><th>金额</th><th>占比</th><th>笔数</th><th>人数</th></tr></thead><tbody>${R.classes.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fm(x[1])}</td><td>${fp(x[1] / R.total)}</td><td>${fi(x[2])}</td><td>${fi(x[3])}</td></tr>`).join('')}
     <tr style="font-weight:600"><td class="l">合计</td><td>${fm(R.total)}</td><td>100%</td><td>—</td><td>—</td></tr></tbody></table></div>
     <div class="note">礼包(USDPack)、限时礼包里各含什么(钻石、道具、宝箱券)待运营确认,暂按商品整体计。WPP、GameAPI 没有扣钻记录,分摊不到</div></div>
    <div><div class="tw"><table><thead><tr><th>钻石包收入 → 功能</th><th>分摊金额</th><th>占钻石包</th><th>花过的付费者</th><th>去掉前 3 人</th></tr></thead><tbody>${R.by_func.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fm(x[1])}</td><td>${fp(x[1] / R.diamond_rev)}</td><td>${fi(x[2])}</td><td>${ex[x[0]] != null ? `${fm(ex[x[0]])}<span class="note"> ${fp(ex[x[0]] / exTot)}</span>` : '—'}</td></tr>`).join('')}
     ${R.unspent ? `<tr><td class="l">没花钻石(留在余额)</td><td>${fm(R.unspent)}</td><td>${fp(R.unspent / R.diamond_rev)}</td><td>—</td><td>—</td></tr>` : ''}</tbody></table></div>
     <div class="note">钻石包收入 ${fm(R.diamond_rev)};前 3 位付费者贡献其中 ${fm(R.top3_rev)}(${fp(R.top3_rev / R.diamond_rev)}),「去掉前 3 人」一列看结构是否被大户带偏</div></div></div></div>`; })() : ''}
   <div class="card"><h3>付费分层 · 近 90 天累计</h3><div class="sub">全部正式服,不随任何筛选变化 · 付费 ${fi(M.concentration.payers)} 人 · ${fm(M.concentration.revenue)}</div>
    <div class="tw"><table><thead><tr><th>档位</th><th>人数</th><th>收入</th><th>占比</th><th>人均</th></tr></thead><tbody>${M.tiers.map(t => `<tr><td>${esc(t.tier)}</td><td>${fi(t.users)}</td><td>${fm(t.revenue)}</td><td>${fp(t.share)}</td><td>${fm(t.users ? t.revenue/t.users : null)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">收入集中度:${M.concentration.rows.map(r => `Top ${r.top}(${r.users} 人)${fp(r.share)}`).join(' · ')}</div></div>
   <div class="card"><h3>收入按渠道 · 近 ${S.w} 天合计</h3><div class="sub">全部正式服、全平台、全等级;每天的变化见上面「收入趋势 · 按维度」</div>
    <div class="tw"><table><thead><tr><th>渠道</th><th>收入</th><th>占比</th><th>付费人数</th></tr></thead><tbody>${ch.map(r => `<tr><td>${esc({Apple:'Apple',Google:'Google',ThirdParty:'第三方(网页)'}[r[0]]||r[0])}</td><td>${fm(r[1])}</td><td>${fp(chTot ? r[1]/chTot : null)}</td><td>${fi(r[2])}</td></tr>`).join('')}</tbody></table></div></div>
  </div>
  <div class="grid">
   ${dl ? `<div class="card"><h3>钻石账 · 近 ${dw} 天</h3><div class="sub">分三块:游戏内循环(充值、系统和活动发放 ↔ 商店和各项消耗)、游戏内博彩(宠物竞猜、老虎机,下注和返还都有记录)、外部接入(WPP、GameAPI)。外部接入只有发进来的钻石,没有下注扣钻记录,净额无法计算,不计入合计。全量,单位:钻石</div>
    <div class="tw"><table><thead><tr><th>板块</th><th>流入</th><th>流出</th><th>净额(流入 − 流出)</th><th>说明</th></tr></thead><tbody>
     <tr><td class="l">游戏内循环</td><td>${fi(dl.loop.in)}</td><td>${fi(dl.loop.out)}</td><td>${fi(dl.loop.net)}</td><td class="l">流入里充值 ${fi(dl.loop.topup)}、系统发放 ${fi(dl.loop.system)}</td></tr>
     <tr><td class="l">游戏内博彩</td><td>${fi(dl.gamble.in)}</td><td>${fi(dl.gamble.out)}</td><td>${fi(dl.gamble.net)}</td><td class="l">流入 = 返还,流出 = 下注${(() => { const TR = M.ticket_ret, k = dw === '7' ? '7' : (dw === '30' ? '28' : null); return TR && k && TR[k] ? `;流入里券局返还 ${fi(TR[k].total)}${k === '28' ? '(近 28 天)' : ''}(宠物竞猜 ${fi(TR[k].petquiz)}、老虎机 ${fi(TR[k].slot)}),券局不花钻石` : ''; })()}</td></tr>
     <tr style="font-weight:600"><td class="l">合计(以上两块)</td><td>${fi(dl.loop.in + dl.gamble.in)}</td><td>${fi(dl.loop.out + dl.gamble.out)}</td><td>${fi(dl.loop.net + dl.gamble.net)}</td><td class="l">—</td></tr>
     ${dl.ext.map(e => `<tr><td class="l">外部接入:${esc(e.name)}</td><td>${fi(e.in)}</td><td>${e.out ? fi(e.out) : '<span class="note">下注记录缺失</span>'}</td><td>${e.net == null ? '<span class="note">无法计算</span>' : fi(e.net)}</td><td class="l">${e.in ? `单日最多 ${e.users} 人收到` : '—'}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="note">外部接入的钻石从哪里来、下注扣钻记在哪里,待研发确认;确认前不判断它是增发还是玩家自己的钻石转进转出</div></div>` : ''}
   <div class="card"><h3>钻石流入 / 流出(游戏内循环)</h3><div class="sub">不含宠物竞猜、老虎机(单独算净消耗)和外部接入 WPP、GameAPI(单独画线,没有扣钻记录);柱 = 游戏内循环净流入(流入 − 流出),为正说明钻石在累积</div><div class="chart"><canvas id="c-dia"></canvas></div></div>
   <div class="card"><h3>钻石消耗结构 · 近 ${dw} 天</h3><div class="sub">竞猜、老虎机按净额(下注 − 返还);全量</div>${ds ? `<div class="chart"><canvas id="c-ds"></canvas></div><div class="note">宠物竞猜下注 ${fi(ds.gross_petquiz)},返还率 ${fp(ds.return_petquiz)};${M.slot && M.slot['28'] ? (() => { const S7 = M.slot[dw === '7' ? '7' : '28'], T = M.slot.tickets7; return `老虎机(近 ${dw === '7' ? 7 : 28} 天)钻石下注 ${fi(S7.bet)}、返还 ${fi(S7.ret)},返还率 ${fp(S7.rate)};另有用券的局 ${fi(S7.ticket_spins)} 次,不花钻石、返出 ${fi(S7.ticket_ret)} 钻(净发)${T ? `。近 7 天券发出 ${fi(T.issued)} 张、用掉 ${fi(T.used)} 张(${(T.used_by || []).map(x => `${({PetQuiz: '宠物竞猜', SlotSpin: '老虎机'})[x[0]] || esc(x[0])} ${fi(x[1])}`).join('、')}),来源:${T.by_source.slice(0,3).map(x => `${esc(x[0])} ${fi(x[1])}`).join('、')}` : ''}`; })() : `老虎机下注 ${fi(ds.gross_slot)},返还率 ${fp(ds.return_slot)}(含用券的局)`}</div>` : '<div class="empty">没有数据</div>'}</div>
  </div>
  <div class="card"><h3>大 R 风险表</h3><div class="sub">大 R = 近 90 天累计 ≥ $1,000。<b>需关注</b> = 连续 7 天没登录,或前 30 天付费 ≥ $1,000 而近 30 天为 0。<b>观察中</b> = 风险分 ≥ 2(风险分 = 以下信号的个数:登录天数减半、付费降 70% 以上、超过 3 倍平均付费间隔未付费、入侵减半、联盟捐献减半、最近 3 天未登录)。规则是第一版,需运营对照真实案例校准。改名、不在联盟只作参考,不计入风险分</div>${whaleTable()}</div>
  </section>`;
  const D1 = daily().slice(-rangeDays()), lab = D1.map(r => md(r.date)), acc = css('--accent'), gold = css('--gold'), slate = css('--slate');
  mkChart('c-m3', {data:{labels:lab, datasets:[
    {type:'bar', label:'收入 $', data:D1.map(r=>r.revenue), backgroundColor:acc, borderRadius:3, yAxisID:'y'},
    {type:'line', label:'付费人数', data:D1.map(r=>r.payers), borderColor:gold, borderWidth:2, pointRadius:0, yAxisID:'y1'},
    {type:'line', label:'ARPPU $', data:D1.map(r=>r.payers ? r.revenue/r.payers : null), borderColor:slate, borderWidth:1.5, pointRadius:0, yAxisID:'y2', spanGaps:true}]},
    options:{scales:{x:{}, y:{position:'left'}, y1:{position:'right', grid:{display:false}}, y2:{display:false}}}});
  const dd = M.diamond_daily; if (dd) { const rows = dd.rows.slice(-Math.min(rangeDays(), 90)), c_ = dd.columns, gi = (k) => c_.indexOf(k);
    mkChart('c-dia', {data:{labels:rows.map(r => md(r[0])), datasets:[
      {type:'bar', label:'游戏内循环净流入', data:rows.map(r => r[gi('in_loop')] - r[gi('out_loop')]), backgroundColor:rows.map(r => r[gi('in_loop')] - r[gi('out_loop')] > 0 ? css('--warn') : css('--good')), borderRadius:2},
      {type:'line', label:'流入(游戏内循环)', data:rows.map(r => r[gi('in_loop')]), borderColor:acc, borderWidth:1.5, pointRadius:0},
      {type:'line', label:'流出(游戏内循环)', data:rows.map(r => r[gi('out_loop')]), borderColor:slate, borderWidth:1.5, pointRadius:0},
      {type:'line', label:'博彩净消耗', data:rows.map(r => r[gi('gamble_net_out')]), borderColor:css('--violet'), borderWidth:1.5, borderDash:[4,3], pointRadius:0},
      {type:'line', label:'外部接入流入(WPP + GameAPI)', data:rows.map(r => r[gi('ext_in')]), borderColor:gold, borderWidth:1.5, borderDash:[2,2], pointRadius:0}]},
      options:{scales:{x:{}, y:{ticks:{callback:(x)=>Intl.NumberFormat('en',{notation:'compact'}).format(x)}}}}}); }
  if (ds) mkChart('c-ds', {type:'bar', data:{labels:ds.rows.map(r=>r[0]), datasets:[{label:'钻石', data:ds.rows.map(r=>r[1]), backgroundColor:acc, borderRadius:4}]},
    options:{indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{ticks:{callback:(x)=>Intl.NumberFormat('en',{notation:'compact'}).format(x)}}, y:{ticks:{autoSkip:false, maxTicksLimit:50}}}}});
  bindInfo(); bindLinks();
}
function whaleTable(){
  const W = D.money.whales || []; if (!W.length) return '<div class="empty">近 90 天没有累计 ≥ $1,000 的玩家</div>';
  const ch = (a, b) => `${a}<span class="note"> / ${b}</span>`;
  const nm = (w) => w.name == null ? '—' : `<span dir="auto">${esc(w.name)}</span>${w.name === 'Invader' + w.id ? '<span class="note">(默认名)</span>' : ''}`;
  const rn = (w) => w.renamed ? `<span class="pill p-yellow">${esc(md(w.renamed.date))} 改名</span><span class="note"> 原名 <span dir="auto">${esc(w.renamed.from)}</span></span>` : '—';
  const al = (w) => w.in_alliance == null ? '—' : w.in_alliance ? '在' : '<b>不在</b>';
  return `<div class="tw" style="max-height:560px"><table><thead><tr><th>玩家 ID</th><th>姓名(主服)</th><th>主服</th><th>状态</th><th>风险分</th><th>近 90 天</th><th>近 30 天付费</th><th>前 30 天</th><th>最后登录时间</th><th>登录记录数 近14/前14</th><th>登录天数 近14/前14</th><th>联盟</th><th>改名</th><th>最近付费</th><th>距上次付费</th><th>平均间隔</th><th>入侵 近14/前14</th><th>捐献 近14/前14</th><th>主城</th><th>信号</th></tr></thead><tbody>` +
   W.map(w => `<tr><td>${w.id}</td><td class="l" style="min-width:7rem">${nm(w)}</td><td>${w.server ?? '—'}${w.n_servers > 1 ? `<span class="note"> / 共 ${w.n_servers} 服</span>` : ''}</td><td>${statusPill(w.status)}</td><td>${w.score}</td><td>${fm(w.rev90)}</td><td>${fm(w.pay30)}</td><td>${fm(w.pay_prev30)}</td><td>${esc(w.last_login_at || md(w.last_login) || '—')}</td><td>${ch(fi(w.logins14), fi(w.logins_prev14))}</td><td>${ch(w.login14, w.login_prev14)}</td><td>${al(w)}</td><td class="l" style="min-width:9rem">${rn(w)}</td><td>${esc(md(w.last_pay)||'—')}</td><td>${w.since_pay ?? '—'} 天</td><td>${w.gap ?? '—'} 天</td><td>${ch(w.pvp14, w.pvp_prev14)}</td><td>${ch(w.ally14, w.ally_prev14)}</td><td>${w.level ?? '—'}</td><td class="l" style="min-width:16rem">${esc(w.flags.join(';'))}</td></tr>`).join('') + '</tbody></table></div>' +
   `<div class="note">主服 = 近 90 天付费最多的服(没有付费就取登录天数最多的服),姓名、联盟都取主服上的。最后登录时间 = 所有服里最后一条登录记录,中国时间,数据截至 ${esc(END)}。登录记录数 = GetUserInfo 记录条数。Log 库没有真正的登录表,这是最接近的;客户端一天会记很多条(活跃大 R 一天几十条),<b>不等于登录次数</b>,只适合和自己前 14 天比、看活跃变多还是变少。改名:${esc(D.meta.name_track_since || '2026-10-21')} 起每天记一次主服名字,和上次不同就标出来,之前的改名查不到。</div>`;
}

// ================= 601 新版内测服
function n601Page(part){
  const SEG = S.seg6 !== 'all' && D.n601_seg ? D.n601_seg.segs[S.seg6] : null;
  const N = SEG ? SEG.n601 : D.n601;
  const segTxt = SEG ? `当前筛选:${S.seg6.startsWith('p:') ? '平台 ' + S.seg6.slice(2) : S.seg6.startsWith('c:') ? '国家 ' + cname(S.seg6.slice(2)) : '版本 ' + S.seg6.slice(2)}(${SEG.n} 人)。` : '';
  if (!N) { $('root').innerHTML = '<section><div class="empty">601 数据这次没有取到</div></section>'; return; }
  const k = N.kpi, R = N.retention, G = {all:'全部', old:'老服账号', new:'新建号'};
  const WN = (N.win || {})[S.w6] || {from:N.start};
  const WL = S.w6 ? '近 1 天' : '内测以来';
  // 2026-11-05 关键数字卡底部:近 7 天 vs 前 7 天 + 内测以来的迷你趋势线(不随时间筛选)
  const spark = (vals) => { const v = vals.map(x => x || 0), mx = Math.max(...v, 1), w = 140, h = 26, st = v.length > 1 ? w / (v.length - 1) : w;
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;margin-top:4px"><polyline fill="none" stroke="${css('--accent')}" stroke-width="1.5" points="${v.map((y, i) => `${(i * st).toFixed(1)},${(h - 2 - (y / mx) * (h - 4)).toFixed(1)}`).join(' ')}"/></svg>`; };
  const trendL = (f, money, unit) => { const v = N.daily.map(f), a = v.slice(-7).reduce((x, y) => x + (y || 0), 0), b = v.slice(-14, -7).reduce((x, y) => x + (y || 0), 0), fmt = money ? (x) => fm(x) : (x) => fi(x) + (unit || '');
    return `近 7 天 ${fmt(a)} · 前 7 天 ${fmt(b)}${b ? `(${a >= b ? '+' : ''}${Math.round((a / b - 1) * 100)}%)` : ''}${spark(v)}`; };
  const rt = (x) => x && x.base ? `${fp(x.rate,0)}<span class="note"> ${x.n}/${x.base}</span>` : '—';
  // 带 95% 区间和参照线结论(2026-10-28);结论只在区间整体落在线的一侧时才给
  const vcls = v => !v ? '' : v.startsWith('低于') ? 'warn' : v.startsWith('达到') ? 'pass' : 'na';
  const rtc = (x, verdict = true) => x && x.base ? `${fp(x.rate,0)}<span class="note"> ${x.n}/${x.base}<br>[${fp(x.ci[0],0)}–${fp(x.ci[1],0)}]</span>${verdict && x.verdict ? `<br><span class="ck ${vcls(x.verdict)}">${esc(x.verdict.replace('区间跨过参照线,样本不足以判断','区间跨线'))}</span>` : ''}` : '—';
  const Q = N.cohort_q;
  const pn = v => String(Math.round(v * 1000) / 10), rg = (lo, hi) => hi != null ? `${pn(lo)}–${pn(hi)}%` : `${pn(lo)}%`;
  const lineTxt = Q ? Q.lines.map(l => `${l.name} D1 ${rg(l.d1, l.d1_hi)}${l.d7 != null ? ' / D7 ' + rg(l.d7, l.d7_hi) : ''}${l.d30 != null ? ' / D30 ' + rg(l.d30) : ''}`).join(';') : '';
  const r3 = md(addDays(END,-2));
  const dl = N.daily.filter(r => !N.win || r.d >= WN.from), dsum = (key) => sum(dl.map(r => r[key]));
  const W = N.whale_entry || {}, M = N.migration, TA = N.two_app;
  const tw = TA ? TA.weeks.filter(w => w.from >= N.start) : [];
  const V = SEG && part !== 'n6dq' ? (SEG.ev || {})['0'] : (D.n601_ev || {})['0'];   // 2026-11-05 埋点块固定内测以来   // 数据质量页始终是全部玩家
  const sToday = SEG ? '' : todayCard('n601');   // 今天实时只有全部玩家
  const sBanner = `<div class="banner">${segTxt ? `<b>${esc(segTxt)}</b>两个 App 合计、今天实时、埋点数据质量仍是全部玩家。<br>` : ''}601 是新版内测服,口径和其他页不同:<b>活跃</b>用每日任务、签到、付款、登录等痕迹代替(新版不写老版登录日志,会漏掉什么都没留下的人);<b>充值</b>:Google / Apple 订单按 New Era 支付表判断到账(商店确认扣款、奖励已发放;商店测试购买和退款已剔除),PayerMax 网页支付还没有状态记录,仍是「待核实」;确认到账和待核实分开显示,待核实不计入确认收入。只统计 ${esc(N.start)} 内测开始后注册的角色,已去掉测试号;时间都是中国时间。${V ? '「获客与进入」等页的客户端数据来自埋点,只有同意采集的玩家才上报,人数是下限。' : ''}</div>`;
  const VS = V ? V.startup.total : null, VU = V ? V.sessions.user_day : null, VC = V ? V.coverage.filter(x => x.act).slice(-1)[0] : null;
  // 2026-11-04 601 按玩家旅程重排(用户确认):关键数字按页拆开
  const KC = {
    players: kpiCard({label:'内测玩家', val:fi(k.players), lines:[`老服账号 ${fi(k.old)} · 新建号 ${fi(k.new)}`, `${WL}新增 ${fi(WN.reg)}(其中老服账号 ${fi(WN.reg_old)})`]}),
    act: kpiCard({label:`活跃 · ${WL}`, val:fi(WN.act), lines:[`按人去重;其中老服账号 ${fi(WN.act_old)} · 单日峰值 ${fi(k.act_peak)}`, trendL(r => r.act_old + r.act_new).replace(/近 7 天 [^·]+ · 前 7 天 [^<(]+(\([^)]*\))?/, '每天活跃')]}),
    d1: kpiCard({label:'D1 留存(全部内测期间)', val:fp(R.all.d1.rate,0), lines:[`${R.all.d1.n}/${R.all.d1.base} 人`, `D7 ${fp(R.all.d7.rate,0)}(${R.all.d7.n}/${R.all.d7.base})`]}),
    newdev: kpiCard({label:'新用户(全新设备)', val:fi((N.origin||[]).find(o => o.key==='new')?.n), lines:[`其余为回流用户或无法判断`, `见「用户来源」`]}),
    pay: kpiCard({label:`确认到账 · ${WL}`, val:fm(WN.paid_usd,2), lines:[`另有待核实 ${fm(WN.pending_usd,2)}(PayerMax 等没有到账状态,不计入)`, trendL(r => r.paid_usd, true), `${fi(WN.payers)} 人 · ${fi(WN.orders)} 笔`, (WN.by_channel||[]).map(c => `${esc(c.ch)} ${fm(c.usd)}`).join(' · ') || '无订单']}),
    payrate: kpiCard({label:`付费人数占活跃 · ${WL}`, val:fp(WN.act ? WN.payers / WN.act : null), lines:[`${fi(WN.payers)}/${fi(WN.act)} 人`, '含 PayerMax 待核实']}),
    startup: V ? kpiCard({label:'启动到登录成功(按安装)', val:fp(VS.resources ? VS.ready / VS.resources : null, 0), lines:[`${fi(VS.ready)}/${fi(VS.resources)} 个安装`, `启动失败后没登录上 ${fi(VS.failed_never_ready)} 个`]}) : '',
    playtime: V ? kpiCard({label:'每人每天游戏时长', val:VU.min_p50 != null ? VU.min_p50 + ' 分钟' : '—', lines:[`中位数;四分之一的人超过 ${VU.min_p75} 分钟`, `每人每天会话中位数 ${VU.sess_p50} 次`]}) : '',
    coverage: V && VC ? kpiCard({label:`埋点覆盖 · ${md(VC.d)}`, val:fp(VC.ev_users / VC.act, 0), lines:[`埋点里 ${VC.ev_users} 人 / 活跃 ${VC.act} 人`, '只有同意采集的玩家上报']}) : '',
    twoapp: TA ? kpiCard({label:'两个 App 合计 · 内测首周', val:fm(tw[0] ? tw[0].old + tw[0].n601 : null), lines:[`基线 ${fm(TA.baseline)}/周 · ${sgn(dpct(tw[0] ? tw[0].old + tw[0].n601 : null, TA.baseline))}`, `目标 = 基线 × 1.5 = ${fm(TA.baseline*1.5)}`]}) : '',
    acq: V && V.acq ? kpiCard({label:'带安装来源的新安装', val:fi(V.acq.with_ref), lines:[V.acq.total.filter(x => x.installs).map(x => `${esc(x.src)} ${fi(x.installs)}`).join(' · '), `${esc(V.acq.from)} 起;只覆盖同意采集的玩家`]}) : '',
  };
  const kp = (...ks) => `<div class="kpis">${ks.map(x => KC[x] || '').join('')}</div>`;
  const intro = (t) => `<div class="sub" style="margin:2px 0 12px">${t}</div>`;
  // 2026-11-05 总览核心数字(用户需求 5.1):新建角色、活跃、D1、确认到账、确认付费人数、待核实、Lv3 到达、两 App 合计
  const CRa = (N.city_reach || []).find(x => x.key === 'all');
  Object.assign(KC, {
    newrole: kpiCard({label:`新建角色 · ${WL}`, val:fi(WN.reg), lines:[`其中老服账号 ${fi(WN.reg_old)};现在已到主城 Lv3 ${fi(WN.reg_lv3)}`, trendL(r => r.reg_old + r.reg_new)]}),
    paidpayers: kpiCard({label:`确认付费人数 · ${WL}`, val:fi(WN.paid_payers), lines:[`有已到账订单的人;只有待核实订单的另有 ${fi((WN.payers || 0) - (WN.paid_payers || 0))} 人`, trendL(r => r.paid_payers, false, ' 人次'), `占同期活跃 ${fp(WN.act ? WN.paid_payers / WN.act : null)}`]}),
    pending: kpiCard({label:`待核实金额 · ${WL}`, val:fm(WN.pending_usd,2), lines:['PayerMax 等没有到账状态的订单', '不计入确认到账']}),
    lv3: CRa ? kpiCard({label:'主城 Lv3 到达(全部内测)', val:fp(CRa.n ? CRa.lv3 / CRa.n : null, 0), lines:[`${fi(CRa.lv3)}/${fi(CRa.n)} 人;Lv3 解锁入侵`, '按现在的等级,不随时间筛选']}) : ''});
  const sKpi = kp('newrole', 'act', 'd1', 'pay', 'paidpayers', 'pending', 'lv3', 'twoapp');
  const sScale = `<h2>每日新增与活跃</h2>
  <div class="grid">
   <div class="card"><h3>每日新增角色</h3><div class="sub">老服账号 = 用旧账号直接进 601;新建号 = 新账号(含老玩家小号,见「用户来源」)</div><div class="chart"><canvas id="c-n6reg"></canvas></div></div>
   <div class="card"><h3>每日活跃</h3><div class="sub">当天有每日任务、签到、名人任务、加速道具、付款或登录痕迹的人</div><div class="chart"><canvas id="c-n6act"></canvas></div></div>
  </div>
  <div class="card"><h3>每日明细</h3><div class="sub">付费率 = 当天付费人数 ÷ 当天活跃;ARPPU = 当天金额 ÷ 当天付费人数;金额含 PayerMax 待核实;付费人数「合计」按人去重</div>
   <div class="tw"><table><thead><tr><th>日期</th><th>新增</th><th>其中老服账号</th><th>活跃</th><th>付费人数</th><th>付费率</th><th>金额</th><th>ARPPU</th></tr></thead><tbody>${dl.map(r => { const a = r.act_old + r.act_new; return `<tr><td>${md(r.d)}</td><td>${r.reg_old + r.reg_new}</td><td>${r.reg_old}</td><td>${a}</td><td>${r.payers}</td><td>${r.payers ? fp(r.payers / a) : '—'}</td><td>${r.usd ? fm(r.usd,2) : '—'}</td><td>${r.payers ? fm(r.usd / r.payers,2) : '—'}</td></tr>`; }).join('')}
    <tr style="font-weight:600"><td>合计</td><td>${fi(WN.reg)}</td><td>${fi(WN.reg_old)}</td><td>${fi(WN.act)}<span class="note"> 去重</span></td><td>${fi(WN.payers)}</td><td>${WN.act ? fp(WN.payers / WN.act) : '—'}<span class="note"> 占期间活跃</span></td><td>${fm(WN.usd,2)}</td><td>${WN.payers ? fm(WN.usd / WN.payers,2) : '—'}</td></tr></tbody></table></div>
   ${(N.suspects||[]).length ? `<div class="note">疑似批量账号 ${N.suspects.length} 个,<b>尚未剔除</b>,仍计入上面所有数字(待确认):${[...new Set(N.suspects.map(x => x.reason))].map(rs => `${N.suspects.filter(x => x.reason === rs).map(x => x.id).join('、')}(${esc(rs)})`).join(';')}</div>` : ''}</div>`;
  const sOrigin = `<h2>用户来源<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2>
  ${N.origin ? `<div class="card"><h3>回流用户与新用户切分</h3><div class="sub">每个 601 玩家关联的老账号 = 自己(旧号直接进)+ 同一台手机(设备广告 ID 相同)上的旧账号,再看这些老账号在老服历史上付没付过费(订单从 2023-11 起)。<b>沉睡回流</b> = 进 601 前 30 天关联老账号一次都没在老服登录。设备 ID 只用来匹配,不在页面上显示</div>
   <div class="tw"><table><thead><tr><th>来源</th><th>人数</th><th>旧号直接进 / 同设备新建号</th><th>其中沉睡回流</th><th>关联老账号历史付费</th><th>D1</th><th>${r3} 以来登录过</th><th>601 付费人数</th><th>601 充值</th></tr></thead><tbody>${N.origin.map(o => `<tr><td class="l">${esc(o.name)}</td><td>${fi(o.n)}</td><td>${o.direct} / ${o.alt}</td><td>${o.dormant}</td><td>${o.old_pay ? fm(o.old_pay) : '—'}</td><td>${rt(o.d1)}</td><td>${fi(o.recent)}</td><td>${fi(o.payers)}</td><td>${fm(o.usd,2)}</td></tr>`).join('')}</tbody></table></div></div>` : ''}
  <div class="grid">
   ${W.w90 != null ? `<div class="card"><h3>老服大 R 进入 601 比例</h3><div class="sub">「已进入」= 本人账号或同一台手机上的账号是 601 内测玩家</div>
    <div class="tw"><table><thead><tr><th>老服大 R</th><th>人数</th><th>已进入 601</th><th>比例</th></tr></thead><tbody>
     <tr><td class="l">近 90 天付费 ≥ $1,000(大 R 风险表那批)</td><td>${W.w90}</td><td>${W.w90_in}</td><td>${fp(W.w90_in / W.w90,0)}</td></tr>
     <tr><td class="l">历史累计 ≥ $1,000,且近 30 天在老服登录过</td><td>${W.wlife}</td><td>${W.wlife_in}</td><td>${fp(W.wlife_in / W.wlife,0)}</td></tr></tbody></table></div></div>` : ''}
   ${M ? `<div class="card"><h3>老服账号近 3 日活跃分布</h3><div class="sub">${M.n} 人;${r3} ~ ${md(END)} 在老服 / 601 的活跃情况</div>
    <div class="tw"><table><thead><tr><th>${r3} ~ ${md(END)}</th><th>人数</th></tr></thead><tbody>
     <tr><td>仅老服活跃</td><td>${M.recent.only_old}</td></tr><tr><td>两端均活跃</td><td>${M.recent.both}</td></tr>
     <tr><td>仅 601 活跃</td><td>${M.recent.only_601}</td></tr><tr><td>两端均未活跃</td><td>${M.recent.neither}</td></tr></tbody></table></div></div>` : ''}
  </div>
  ${M ? `<div class="card"><h3>老服账号每日活跃:老服 vs 601</h3><div class="sub">老服 = 当天在任一老服有登录记录;601 = 当天有活跃痕迹。虚线左边是 601 开测前一周</div><div class="chart"><canvas id="c-n6mig"></canvas></div>
   <details><summary class="link">展开账号明细(${M.n} 人)</summary>
   <div class="tw" style="max-height:360px"><table><thead><tr><th>玩家 ID</th><th>601 里的名字</th><th>老服近 90 天付费</th><th>601 活跃天数</th><th>老服登录天数</th><th>登录过的老服</th><th>601 主城</th><th>601 最后登录</th><th>老服最后登录</th></tr></thead><tbody>${M.people.map(x => `<tr><td>${x.id}</td><td class="l"><span dir="auto">${esc(x.name ?? '—')}</span></td><td>${x.pay90_old ? fm(x.pay90_old) : '—'}</td><td>${x.days_601}</td><td>${x.days_old}</td><td class="l">${esc(x.old_servers || '—')}</td><td>${x.city ?? '—'}</td><td>${esc((x.last_601||'—').slice(5))}</td><td>${esc((x.last_old||'—').slice(5))}</td></tr>`).join('')}</tbody></table></div>
   <div class="note">天数从 ${esc(N.start)} 算起(共 ${M.days} 天)</div></details></div>` : ''}`;
  const sRet = `<h2>留存<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2>
  <div class="grid">
   <div class="card"><h3>留存:老服账号 vs 新建号</h3><div class="sub">注册后第 N 天有活跃痕迹;只算已满 N 天的注册日。样本量小,波动较大;按来源的 D1 见「用户来源」</div>
    <div class="tw"><table><thead><tr><th>分组</th><th>人数</th><th>D1</th><th>D3</th><th>D7</th></tr></thead><tbody>${['all','old','new'].map(g => `<tr><td>${G[g]}</td><td>${fi(N.progress[g].n)}</td><td>${rt(R[g].d1)}</td><td>${rt(R[g].d3)}</td><td>${rt(R[g].d7)}</td></tr>`).join('')}</tbody></table></div></div>
   ${Q ? '' : `<div class="card"><h3>按注册日留存</h3><div class="sub">「—」= 还没满期</div>
    <div class="tw" style="max-height:300px"><table><thead><tr><th>注册日</th><th>人数</th><th>其中老服账号</th><th>D1</th><th>D3</th><th>D7</th></tr></thead><tbody>${N.cohorts.map(c => `<tr><td>${md(c.d)}</td><td>${c.n}</td><td>${c.old}</td><td>${rt(c.d1)}</td><td>${rt(c.d3)}</td><td>${rt(c.d7)}</td></tr>`).join('')}</tbody></table></div></div>`}
  </div>
  ${Q ? `<div class="card"><h3>新人留存:按来源,带 95% 置信区间</h3><div class="sub">参照线:${esc(lineTxt)}。方括号是 95% 区间(Wilson);只有区间整体在某条线上方才写「达到」,整体在底线下方才写「低于底线」,跨线写「区间跨线」——样本小时不按点估计下结论</div>
    <div class="tw"><table><thead><tr><th>来源</th><th>人数</th><th>D1</th><th>D3</th><th>D7</th><th>D30</th></tr></thead><tbody>
    ${Q.summary.map(x => `<tr${x.key === 'all' ? ' style="font-weight:600"' : ''}><td class="l">${esc(x.name)}</td><td>${fi(x.n)}</td><td>${rtc(x.d1)}</td><td>${rtc(x.d3, false)}</td><td>${rtc(x.d7)}</td><td>${rtc(x.d30)}</td></tr>`).join('')}
    <tr><td class="l">对照:老服同期新用户<span class="note"><br>注册当天进入游戏的,去掉疑似刷量机型${Q.old_ref.excluded_models.length ? '(' + esc(Q.old_ref.excluded_models.join('、')) + ')' : ''}</span></td><td>${fi(Q.old_ref.n)}</td><td>${rtc(Q.old_ref.d1)}</td><td>${rtc(Q.old_ref.d3, false)}</td><td>${rtc(Q.old_ref.d7)}</td><td>${rtc(Q.old_ref.d30)}</td></tr>
    </tbody></table></div>
    <div class="note">真新设备 = 设备上没有老服账号,且是这台设备上最早的 601 账号(重装分不出);同设备重复新号 = 同一设备上第二个及以后的 601 新号。601 的留存按活跃痕迹算(任务、签到、加速、付款、最后登录),只登录不做事的人会漏掉,数字偏低;老服按登录日志算。两边来源结构不同(601 多为老玩家回流),只作参照,不代表同一批人的差距。</div></div>
  <div class="card"><h3>按注册日 × 来源</h3><div class="sub">每天一行;「—」= 还没满期。每天人数少,区间很宽,看趋势时以上面汇总为准</div>
    <div class="tw" style="max-height:360px"><table><thead><tr><th>注册日</th><th>人数</th>${Q.src.map(s_ => `<th>${esc(s_.name.replace(/\(.*\)/, ''))}</th>`).join('')}<th>D1</th><th>其中真新设备 D1</th><th>D3</th><th>D7</th><th>D30</th></tr></thead><tbody>
    ${Q.rows.map(x => `<tr><td>${md(x.d)}</td><td>${x.n}</td>${Q.src.map(s_ => `<td>${x[s_.key] || '—'}</td>`).join('')}<td>${rtc(x.d1, false)}</td><td>${rtc(x.fresh_d1, false)}</td><td>${rtc(x.d3, false)}</td><td>${rtc(x.d7, false)}</td><td>${rtc(x.d30, false)}</td></tr>`).join('')}</tbody></table></div></div>` : ''}
`;
  const sGrow = `<h2>成长与玩法<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2>
  <div class="grid">
   ${N.climb ? `<div class="card"><h3>等级成长速度</h3><div class="sub">按在服天数分组的当前等级;「近 3 日活跃」= ${r3} 以来有登录。<b>「201 级」推测指英雄等级</b>(老服有 200 级英雄),待开发确认</div>
    <div class="tw"><table><thead><tr><th>在服天数</th><th>人数</th><th>主城中位数</th><th>英雄最高等级中位数</th><th>英雄最高</th><th>近 3 日活跃</th><th>活跃者主城 / 英雄中位数</th></tr></thead><tbody>${N.climb.map(x => `<tr><td>${esc(x.name)}</td><td>${x.n}</td><td>${x.city ?? '—'}</td><td>${x.hero ?? '—'}</td><td>${x.hero_max ?? '—'}</td><td>${x.recent}</td><td>${x.city_recent ?? '—'} / ${x.hero_recent ?? '—'}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">英雄等级达到:${(N.hero_marks||[]).map(x => `${x[0]} 级 ${x[1]} 人`).join(' · ')}</div></div>` : ''}
   <div class="card"><h3>主城等级分布</h3><div class="sub">条 = 人数;深色 = 其中 ${r3} 以来(含今天)登录过的人。用于观察等级停滞点</div><div class="chart"><canvas id="c-n6city"></canvas></div></div>
  </div>
  <div class="card"><h3>各建筑 / 英雄等级</h3><div class="sub">每人取该类建筑中等级最高的一座;「拥有人数」= 建有该类建筑的内测玩家;「近 3 日活跃」= ${r3} 以来(含今天)有登录。建筑名来自游戏配置表,另有 5 类建筑(类型 6、9~12)配置里没有名字,不列</div>
   <div class="tw"><table><thead><tr><th>建筑 / 英雄</th><th>拥有人数</th><th>中位等级</th><th>P90</th><th>最高</th><th>近 3 日活跃人数</th><th>活跃者中位等级</th></tr></thead><tbody>${(N.levels||[]).map(x => `<tr><td>${esc(x.name)}</td><td>${fi(x.users)}</td><td>${x.median ?? '—'}</td><td>${x.p90 ?? '—'}</td><td>${x.max ?? '—'}</td><td>${fi(x.recent_users)}</td><td>${x.recent_median ?? '—'}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="card"><h3>玩法参与</h3><div class="sub">各玩法参与人数。601 的玩法表多为当前状态或每人最近一条记录,只能统计是否参与及进度。「近 3 日活跃」= ${r3} 以来(含今天)有登录;参与者与未参与者的差异只是相关,<b>不代表因果</b></div>
   <div class="tw"><table><thead><tr><th>玩法</th><th>参与人数</th><th>参与率</th><th>老服账号 / 新建号</th><th>参与者近 3 日活跃率</th><th>未参与者近 3 日活跃率</th><th>说明</th></tr></thead><tbody>${(N.gameplay||[]).map(g => `<tr><td>${esc(g.name)}</td><td>${fi(g.users)}</td><td>${fp(g.share,0)}</td><td>${g.old} / ${g.new}</td><td>${fp(g.recent_in.rate,0)}<span class="note"> ${g.recent_in.n}/${g.recent_in.base}</span></td><td>${fp(g.recent_out.rate,0)}<span class="note"> ${g.recent_out.n}/${g.recent_out.base}</span></td><td class="l" style="min-width:14rem">${esc(g.note)}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="grid">
   ${N.achievements ? `<div class="card"><h3>成就完成</h3><div class="sub">每人完成的成就数:中位数 ${N.achievements.per_player_median},P90 ${N.achievements.per_player_p90},一个都没完成 ${N.achievements.zero} 人(共 ${N.achievements.n} 人)。<b>库里只有成就编号,没有名称</b></div>
    <div class="tw" style="max-height:300px"><table><thead><tr><th>成就编号</th><th>完成人数</th><th>占内测玩家</th></tr></thead><tbody>${N.achievements.rows.filter(x => x[1] > 0).sort((a,b) => b[1]-a[1]).map(x => `<tr><td>${x[0]}</td><td>${fi(x[1])}</td><td>${fp(x[1]/N.achievements.n,0)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">没人完成的:${N.achievements.rows.filter(x => !x[1]).map(x => x[0]).join('、') || '无'}</div></div>` : ''}
  </div>
  <div class="card"><h3>活动参与</h3><div class="sub">只列内测玩家有记录的活动;多数活动在 ${esc(N.start)} 内测开始前就结束了</div>
   <div class="tw"><table><thead><tr><th>活动</th><th>时间</th><th>有积分的人</th><th>有记录的人</th><th>领过奖的人</th></tr></thead><tbody>${(N.activities||[]).map(x => `<tr><td class="l">${esc(x.name)}</td><td>${esc(x.open.slice(5))} ~ ${esc(x.close.slice(0,4) > '2027' ? '长期' : x.close.slice(5))}</td><td>${fi(x.with_points)}</td><td>${fi(x.records)}</td><td>${fi(x.claimed)}</td></tr>`).join('')}</tbody></table></div></div>`;
  // 2026-11-04 新手与首日成长(用户需求 5.3):引导、主城 Lv1→Lv3、注册当天、新人前 7 天、建筑升级与受阻
  const sGuideCard = (N.guide ? `<div class="card"><h3>新手引导</h3><div class="sub">完成过各引导步骤的人数(共 ${fi(N.guide.n)} 人)。<b>库里只有步骤编号,没有名称</b>;200、201、202、210、299 几乎所有人都走过,是新手主线</div>
    <div class="tw"><table><thead><tr><th>主线步骤</th><th>完成人数</th><th>占比</th></tr></thead><tbody>${N.guide.main.map(x => `<tr><td>${x[0]}</td><td>${fi(x[1])}</td><td>${fp(x[1]/N.guide.n,0)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">功能引导:${N.guide.other.map(x => `${x[0]}(${x[1]} 人)`).join(' · ')}</div></div>` : '');
  const sFirst7 = (N.first7 ? (() => { const F = N.first7, pc = (k, n) => n ? `${fp(k / n, 0)}<span class="note"> ${k}/${n}</span>` : '—', lv = (x) => x && x.covered ? `${x.median}<span class="note"> n=${x.covered}</span>` : '—';
   return `<div class="card"><h3>新人前 7 天 · 按来源</h3><div class="sub">只算 ${md(F.upto)} 及以前注册(已满 7 天)的内测玩家,第 0–6 天。活跃天数按活跃痕迹;主城等级取到第 N 天为止签到记录里的最高等级,没签到过的人看不到,n = 有签到记录的人数;入联盟只能看到现在仍在联盟的人;竞技场只算真正挑战过的人(不限 7 天)</div>
    <div class="tw"><table><thead><tr><th>来源</th><th>人数</th><th>活跃天数中位数</th><th>平均</th><th>活跃 ≥ 3 天</th><th>主城 第 1 天</th><th>第 3 天</th><th>第 7 天</th><th>7 天内入联盟</th><th>打过竞技场</th><th>7 天内付费</th><th>付费 ≥ 2 笔</th></tr></thead><tbody>
    ${F.rows.filter(x => x.n).map(x => `<tr${x.key === 'all' ? ' style="font-weight:600"' : ''}><td class="l">${esc(x.name)}</td><td>${fi(x.n)}</td><td>${x.days_median}</td><td>${x.days_mean}</td><td>${pc(x.days_ge3, x.n)}</td><td>${lv(x.lv1)}</td><td>${lv(x.lv3)}</td><td>${lv(x.lv7)}</td><td>${pc(x.ally7, x.n)}</td><td>${pc(x.arena, x.n)}</td><td>${pc(x.pay7, x.n)}</td><td>${x.payers ? `${x.repeat}/${x.payers}` : '—'}</td></tr>`).join('')}
    </tbody></table></div><div class="note">「付费 ≥ 2 笔」= 付过费的人里有 2 笔及以上的(不限 7 天),已去掉测试号。第一次入侵的结果、单次时长 601 库里没有记录</div></div>`; })() : '');
  const pc6 = (k, n) => n ? `${fp(k / n, 0)}<span class="note"> ${fi(k)}/${fi(n)}</span>` : '—';
  const CR = N.city_reach;
  const sReach = CR ? `<h2>主城等级到达<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2>
  <div class="card"><h3>主城 Lv2 / Lv3 / Lv5 到达 · 按来源</h3><div class="sub">「到达」= 现在的主城等级不低于该级(服务端状态,只知道到没到,不知道哪天到)。「注册当天到 Lv3」用签到记录近似:签到时记了主城等级,只看注册当天签过到的人,是下限。Lv3 解锁入侵</div>
   <div class="tw"><table><thead><tr><th>来源</th><th>人数</th><th>到 Lv2</th><th>到 Lv3</th><th>到 Lv5</th><th>注册当天签过到</th><th>其中当天已到 Lv3</th></tr></thead><tbody>${CR.map(x => `<tr${x.key === 'all' ? ' style="font-weight:600"' : ''}><td class="l">${esc(x.name)}</td><td>${fi(x.n)}</td><td>${pc6(x.lv2, x.n)}</td><td>${pc6(x.lv3, x.n)}</td><td>${pc6(x.lv5, x.n)}</td><td>${pc6(x.d0_signed, x.n)}</td><td>${pc6(x.d0_lv3, x.d0_signed)}</td></tr>`).join('')}</tbody></table></div>
   <div class="note">逐次升级时间要等 B72 的建筑升级埋点(E034 带 operation_id、target_level)攒够数据;没有时间戳前不算「首日 Lv3 转化率」</div></div>` : '';
  const sPay = `<h2>付费</h2>
  <div class="grid">
   <div class="card"><h3>渠道构成</h3><div class="sub">已到账 = New Era 支付表里有商店收据、商店确认扣款(Apple 为生产环境收据)、奖励已发放</div>
    <div class="tw"><table><thead><tr><th>渠道</th><th>金额</th><th>笔数</th><th>人数</th><th>已到账</th><th>状态</th></tr></thead><tbody>${(WN.by_channel || []).map(c => `<tr><td>${esc(c.ch)}</td><td>${fm(c.usd,2)}</td><td>${c.orders}</td><td>${c.payers}</td><td>${c.paid} 笔 · ${fm(c.paid_usd,2)}</td><td class="l">${c.paid === c.orders ? '全部已到账' : c.ch.startsWith('PayerMax') ? '待核实:PayerMax 状态表已建,还没有数据' : `${c.orders - c.paid} 笔没有到账确认`}</td></tr>`).join('')}</tbody></table></div>
    <h3 style="margin-top:8px">已剔除的订单<span class="note" style="font-weight:400"> · 不随时间筛选</span></h3><div class="tw"><table><thead><tr><th>原因</th><th>笔数</th><th>金额</th><th>账号数</th></tr></thead><tbody>${N.excluded.map(x => `<tr><td>${esc(x.why)}</td><td>${x.orders}</td><td>${fm(x.usd,2)}</td><td>${x.users}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">已剔除账号:${N.test_ids.join('、')}(统一排除名单)。内测开始前注册的 ${N.excluded_players.before_start} 个角色不算内测玩家。</div></div>
   <div class="card"><h3>商品构成</h3><div class="sub">按商品;钻石包里 PayerMax 网页价是商店价的 85%</div>
    <div class="tw"><table><thead><tr><th>商品</th><th>笔数</th><th>人数</th><th>金额</th></tr></thead><tbody>${(WN.products||[]).map(x => `<tr><td>${esc(x.name)}</td><td>${x.orders}</td><td>${x.payers}</td><td>${fm(x.usd,2)}</td></tr>`).join('')}</tbody></table></div>
    ${N.gift_intent ? `<div class="note">发起过礼包购买的 ${N.gift_intent.users} 人(${N.gift_intent.rows} 次),其中 ${N.gift_intent.both} 人最后付了款;付费的共 ${N.gift_intent.payers} 人(有人走 PayerMax 网页,不经过礼包下单)。下单状态的含义未核对</div>` : ''}</div>
  </div>
  ${N.checkout ? (() => { const F = WN.checkout || N.checkout.total, act = Object.fromEntries(N.daily.map(r => [r.d, r.act_old + r.act_new])), CDw = N.checkout.daily.filter(r => r.d >= WN.from), i0 = CDw.findIndex(r => r.clicks), CD = i0 < 0 ? [] : CDw.slice(i0);
   const cv = (k, n) => n ? `${fp(k / n)}<span class="note"> ${k}/${n}</span>` : '—';
   return `<div class="card"><h3>点击付费漏斗(Google / Apple 内购)</h3><div class="sub">点击付费 = 在游戏里发起一次 Google / Apple 支付(每次发起记一条,同一人可多次);生成订单 = 这次发起拿到了订单号;到账 = 同一天有 Google / Apple 已到账订单。PayerMax 网页支付不经过这一步,不在漏斗里。只算内测玩家,已去掉排除名单。最近一次点击 ${esc(N.checkout.last_click || '—')}</div>
    <div class="tw"><table><thead><tr><th>点击付费人数</th><th>点击次数</th><th>生成订单人数</th><th>到账人数</th><th>点击 → 生成订单</th><th>生成订单 → 到账</th><th>点击 → 到账</th></tr></thead><tbody>
     <tr><td>${fi(F.click_users)}</td><td>${fi(F.clicks)}</td><td>${fi(F.order_users)}</td><td>${fi(F.paid_users)}</td><td>${cv(F.order_users, F.click_users)}</td><td>${cv(F.paid_users, F.order_users)}</td><td>${cv(F.paid_users, F.click_users)}</td></tr></tbody></table></div>
    ${F.paid_no_click ? `<div class="note">另有 ${F.paid_no_click} 人有 Google / Apple 订单但没有点击记录,需核对</div>` : ''}
    <h3 style="margin-top:8px">按天</h3><div class="tw"><table><thead><tr><th>日期</th><th>活跃</th><th>点击付费人数</th><th>点击占活跃</th><th>点击次数</th><th>生成订单人数</th><th>到账人数</th></tr></thead><tbody>${CD.map(r => `<tr><td>${md(r.d)}</td><td>${fi(act[r.d] ?? 0)}</td><td>${fi(r.click_users)}</td><td>${act[r.d] ? cv(r.click_users, act[r.d]) : '—'}</td><td>${fi(r.clicks)}</td><td>${fi(r.order_users)}</td><td>${fi(r.paid_users)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">人数少,比率只作参考;一天内同一人多次点击按 1 人计</div></div>`; })() : ''}
  <div class="card"><h3>付费玩家<span class="note" style="font-weight:400"> · 不随时间筛选</span></h3><div class="sub">按金额排序(含 PayerMax 待核实)。首充时主城 = 首次付费前最后一次签到记下的主城等级(没签到过就是「—」),是近似值</div>
   <div class="tw"><table><thead><tr><th>玩家 ID</th><th>姓名</th><th>来源</th><th>注册</th><th>注册到首充</th><th>首充时主城</th><th>金额</th><th>笔数</th><th>渠道</th><th>首次付费</th><th>最近付费</th><th>现在主城</th><th>活跃天数</th><th>最后登录</th></tr></thead><tbody>${N.payers.map(p => `<tr><td>${p.id}</td><td class="l"><span dir="auto">${esc(p.name ?? '—')}</span></td><td class="l">${esc(p.origin || G[p.grp] || '—')}</td><td>${md(p.reg)}</td><td>${p.days_to_first ?? '—'} 天</td><td>${p.city_at_first ?? '—'}</td><td>${fm(p.usd,2)}</td><td>${p.orders}</td><td class="l">${esc(p.channels)}</td><td>${esc((p.first||'').slice(5))}</td><td>${esc((p.last_pay||'').slice(5))}</td><td>${p.city ?? '—'}</td><td>${p.act_days ?? '—'}</td><td>${esc((p.last_login||'').slice(5))}</td></tr>`).join('')}</tbody></table></div></div>`;
  const sTA = `${TA ? `<h2>两个 App 合计收入<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2>
  <div class="card"><h3>周付费:老服 + 601</h3><div class="sub">每 7 天一周,从内测开始日 ${esc(N.start)} 往前往后切;基线 = 开测前 ${TA.base_weeks} 周老服的平均周付费 ${fm(TA.baseline)};首轮目标 = 基线 × 1.5(总纲 6.2)。601 拆成确认到账和待核实两段(待核实主要是 PayerMax,没有到账状态);「合计」和「比基线」含待核实;最后一周没过完,按实际天数</div>
   <div class="chart"><canvas id="c-n6wk"></canvas></div>
   <div class="tw"><table><thead><tr><th>周</th><th>天数</th><th>老服</th><th>601 确认到账</th><th>601 待核实</th><th>合计</th><th>比基线</th></tr></thead><tbody>${TA.weeks.map(w => { const t = w.old + w.n601, b = TA.baseline * w.days / 7; return `<tr${w.from >= N.start ? ' style="font-weight:600"' : ''}><td>${md(w.from)} ~ ${md(w.to)}</td><td>${w.days}</td><td>${fm(w.old)}</td><td>${w.from >= N.start ? fm(w.n601_paid ?? w.n601) : '—'}</td><td>${w.from >= N.start ? fm(w.n601_other || 0) : '—'}</td><td>${fm(t)}</td><td>${sgn(dpct(t, b))}</td></tr>`; }).join('')}</tbody></table></div>
   <div class="note">不足 7 天的周,「比基线」按天数折算。评分、卡顿、支付失败数库里没有,暂不能并列</div></div>` : ''}`;
  const EV = n6ev(V);
  // 版本 / 投放 / 活动日历(2026-11-04):读趋势时当切点;趋势图上同样标出
  const thru = D.meta.data_through || '';
  const evState = (e) => !e.start ? '时间未定' : (e.end ? (thru >= e.end.slice(0,10) ? '已结束' : thru >= e.start.slice(0,10) ? '进行中' : '未开始') : (thru >= e.start.slice(0,10) ? '已发生' : '未到'));
  const sCal = (D.n601_events || []).length ? `<h2>版本、投放与活动</h2><div class="card"><div class="sub">时间是中国 / 新加坡时间;状态按数据截至日 ${esc(thru)} 判断。活动开始后以数据为准核对是否真的开了。趋势图上:活动 = 浅金色底,发版和投放变化 = 虚线</div>
   <div class="tw"><table><thead><tr><th>类型</th><th>名称</th><th>时间</th><th>状态</th><th>说明</th></tr></thead><tbody>${D.n601_events.map(e => `<tr><td>${esc(e.kind)}</td><td class="l">${esc(e.name)}</td><td class="l">${e.start ? esc(e.start) + (e.end ? ' ~ ' + esc(e.end) : '') : '—'}</td><td>${evState(e)}</td><td class="l note">${esc(e.note || '')}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  // 逐日趋势(2026-11-05,老板要求):核心指标每天一张小图,共用日期轴,从内测开始,不随时间筛选;版本和活动标在图上
  const VT = V;
  const sTrend = `<h2>逐日趋势<span class="note" style="font-weight:400"> · 从内测开始,不随时间筛选</span></h2>
  <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
   <div class="card"><h3>新建角色</h3><div class="sub">按注册日;广告安装 = 埋点来源是 Facebook / Instagram、没有广告 ID 的新号</div><div class="chart" style="height:180px"><canvas id="c-trreg"></canvas></div></div>
   <div class="card"><h3>活跃(活跃痕迹)</h3><div class="sub">当天有任务、签到、付款、登录等痕迹的人</div><div class="chart" style="height:180px"><canvas id="c-tract"></canvas></div></div>
   <div class="card"><h3>D1 留存 · 按注册日</h3><div class="sub">只画已满 1 天的注册日;每天人数少,单日波动大,悬停看分子分母</div><div class="chart" style="height:180px"><canvas id="c-trd1"></canvas></div></div>
   <div class="card"><h3>充值:确认到账 / 待核实</h3><div class="sub">美元;待核实 = PayerMax 等没有到账状态的订单,不计入确认收入</div><div class="chart" style="height:180px"><canvas id="c-trrev"></canvas></div></div>
   <div class="card"><h3>付费人数</h3><div class="sub">有已到账订单的人 / 下过单的人(含待核实)</div><div class="chart" style="height:180px"><canvas id="c-trpay"></canvas></div></div>
   <div class="card"><h3>每人每天游戏时长</h3><div class="sub">中位数,分钟;埋点(只覆盖同意采集的人,10-29 起)</div><div class="chart" style="height:180px"><canvas id="c-trmin"></canvas></div></div>
   <div class="card"><h3>启动到登录成功率</h3><div class="sub">按安装;当天开始启动的安装里登录成功的比例(埋点)</div><div class="chart" style="height:180px"><canvas id="c-trst"></canvas></div></div>
  </div>`;
  const PBk = N.postback;
  const PBN = {'facebook-http-accepted':'服务端已发给 Meta(已接受)', 'meta-route-held':'交给客户端 Meta SDK 发送', 'skipped-no-attribution':'没有归因,未发'};
  const sPost = PBk ? `<div class="card"><h3>付费回传 Meta · 状态</h3><div class="sub">${esc(N.start)} 以来 601 付费回传记录,按回传状态;10-29 起改由客户端 Meta SDK 发送,发送结果不回写库,要以 Meta 后台为准。同期确认到账订单 ${fi(PBk.paid_orders)} 笔(回传记录含测试单,两者不是一一对应)。PayerMax 网页支付没有回传记录</div>
   <div class="tw"><table><thead><tr><th>回传状态</th><th>记录数</th></tr></thead><tbody>${Object.entries(PBk.total).map(([k, v]) => `<tr><td class="l">${esc(PBN[k] || k)}</td><td>${fi(v)}</td></tr>`).join('')}</tbody></table></div>
   <details><summary class="link">按天</summary><div class="tw"><table><thead><tr><th>日期</th>${Object.keys(PBN).map(k => `<th>${esc(PBN[k])}</th>`).join('')}</tr></thead><tbody>${PBk.daily.map(x => `<tr><td>${md(x.d)}</td>${Object.keys(PBN).map(k => `<td>${fi(x[k] || 0)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details></div>` : '';
  const PW = N.pay_weeks, CKD = (N.checkout || {}).daily || [];
  const sPayTrend = `<h2>付费趋势<span class="note" style="font-weight:400"> · 从内测开始,不随时间筛选</span></h2><div class="grid">
   ${PW ? `<div class="card"><h3>每周充值 · 按渠道</h3><div class="sub">每 7 天一周(从内测开始日切,最后一周按实际天数);Google / Apple 为确认到账,待核实主要是 PayerMax。按天太稀,所以按周</div><div class="chart" style="height:200px"><canvas id="c-n6pw"></canvas></div></div>` : ''}
   ${CKD.length ? `<div class="card"><h3>点击付费 → 下单 → 到账 · 按天</h3><div class="sub">Google / Apple 内购;点击 = 在游戏里发起支付的人,下单 = 拿到订单号的人,到账 = 当天有已到账订单的人。PayerMax 网页支付不经过这一步</div><div class="chart" style="height:200px"><canvas id="c-n6ck"></canvas></div></div>` : ''}
  </div>`;
  const OL = N.order_layers;
  const sLayers = OL ? `<div class="card"><h3>订单状态分层</h3><div class="sub">${esc(N.start)} 内测开始以来 601 的全部订单,按状态分层;<b>只有「确认到账」计入确认收入</b>,其余各层单列。「—」= 没有这类记录的数据源,不是 0</div>
   <div class="tw"><table><thead><tr><th>状态</th><th>笔数</th><th>金额</th><th>人数</th><th>计入确认收入</th><th>说明</th></tr></thead><tbody>${OL.map(x => `<tr${x.counted ? ' style="font-weight:600"' : ''}><td class="l">${esc(x.name)}</td><td>${x.orders == null ? '—' : fi(x.orders)}</td><td>${x.usd == null ? '—' : fm(x.usd, 2)}</td><td>${x.users == null ? '—' : fi(x.users)}</td><td>${x.counted ? '是' : '否'}</td><td class="l note">${esc(x.note)}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const RV = N.reg_versions;
  const sRegVer = RV && RV.length ? `<h2>建号版本<span class="note" style="font-weight:400"> · 不随时间筛选</span></h2><div class="card"><h3>新账号按建号时的版本</h3><div class="sub">建号版本 = 账号第一次注册时的客户端版本,看「哪个版本带来的新人」用它;顶部筛选的版本是最后登录版本,两者不同。旧号直接进的账号建号版本是老 App 的,不在表里。D1 按活跃痕迹,只算满 1 天的人</div>
   <div class="tw"><table><thead><tr><th>建号版本</th><th>人数</th><th>注册日期</th><th>D1</th><th>现在到主城 Lv3</th></tr></thead><tbody>${RV.map(x => `<tr><td>${esc(x.v)}</td><td>${fi(x.n)}</td><td>${md(x.from)} ~ ${md(x.to)}</td><td>${x.d1 && x.d1.base ? `${fp(x.d1.rate,0)}<span class="note"> ${x.d1.n}/${x.d1.base}</span>` : '—'}</td><td>${pc6(x.lv3, x.n)}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const H2 = (t, note) => `<h2>${t}${note ? `<span class="note" style="font-weight:400"> · ${note}</span>` : ''}</h2>`;
  const PARTS = {
    n601:  [sToday, sBanner, intro('601 内测整体情况:规模、留存、付费的关键数字、逐日趋势和从获客到付费的全链路;每一步的细节在后面的页签。'), sKpi, sTrend, EV.chain, sCal, sTA],
    n6tech:[sBanner, intro('玩家从哪里来、装上之后能不能顺利进入游戏:安装来源、新老玩家来源、启动到登录。'), kp('acq', 'newdev', 'startup'), EV.acq, sOrigin, EV.techStart, sRegVer],
    n6first:[sBanner, intro('新玩家进来后的头几天:注册当天做了什么、新手引导、主城 Lv1 → Lv3、建筑升级与受阻、新人前 7 天。引导步骤漏斗要等研发给步骤顺序表。'),
             EV.first, H2('新手引导', '不随时间筛选') + `<div class="grid">${sGuideCard}${EV.steps}</div>`, sReach + (EV.lv3 || ''), EV.build ? H2('建筑升级与受阻') + EV.build : '', sFirst7 ? H2('新人前 7 天', '不随时间筛选') + sFirst7 + (EV.f7 || '') : ''],
    n6new: [sBanner, intro('进入以后留不留得住:每日新增与活跃、按来源的留存(活跃痕迹和埋点会话两种口径)、游戏时长与时段。'), kp('act', 'd1', 'playtime'), sScale, sRet, EV.dual, EV.sess],
    n6grow:[sBanner, intro('留下来的人玩到哪、玩什么:主城等级随时间、建筑与英雄、玩法参与、成就、活动、小游戏。'), EV.palace, sGrow, EV.games],
    n6pay: [sBanner, intro('付费规模与到账情况:确认到账和待核实分开;渠道与商品、点击到到账的链路、付费玩家、钻石存量。'), kp('pay', 'paidpayers', 'pending', 'payrate'), sPayTrend, sLayers, sPost, sPay, EV.shop, EV.dia],
    n6dq:  [intro('客户端性能和数据本身的可靠性:加载与帧率、请求失败与异常、埋点覆盖与字段质量。本页始终是全部玩家,不随平台、国家、版本筛选。'), kp('coverage'), EV.techPerf, EV.dq]};
  // 2026-11-04 口径标签(用户需求 4.2「强制展示」):每张卡标数据来自哪类口径,按卡片标题前缀匹配
  const SRC_TAG = {
    '服务端': ['每日新增角色', '回流用户与新用户切分', '老服大 R 进入 601', '新手引导', '主城 Lv2', '每天各主城等级', '等级成长速度', '主城等级分布', '各建筑 / 英雄等级', '玩法参与', '成就完成', '活动参与', '宠物竞猜与老虎机', '渠道构成', '已剔除的订单', '商品构成', '点击付费漏斗', '按天', '付费玩家', '玩家手里的钻石', '周付费', '订单状态分层', '每周充值', '点击付费 → 下单', '新建角色', '充值:确认到账', '付费人数', '付费回传 Meta'],
    '埋点下限': ['安装 → 登录', '每日启动漏斗', '启动各阶段耗时', '启动失败', '客户端版本', '注册当天游戏时长', '建筑升级怎么完成', '引导步骤 · 埋点', '建筑升级 · 按类型', '单次会话时长', '一天里什么时候在玩', '每人每天游戏时长', '商店 → 付费', '从哪里进商店', '每天打开商店', '页面加载耗时', '战斗帧率', '关键请求失败', '客户端异常', '每天埋点覆盖', '字段可用性', '各事件条数', '新安装按来源', '各来源合计', '注册后多久到主城 Lv3', '页面加载耗时 · 按天', '战斗低于 30 帧', '每人每天游戏时长', '启动到登录成功率', '会话结束时停在', '会话怎么结束', '启动与加载 · 按系统版本'],
    '代理': ['活跃(活跃痕迹)', 'D1 留存 · 按注册日', '每日活跃', '留存:老服账号 vs 新建号', '新人留存:按来源', '按注册日 × 来源', '新人前 7 天 · 按来源'],
    '混合': ['新人前 7 天 · 逐日', '建角色 → 付费', '留存双轨', '每日明细', '老服账号近 3 日活跃', '老服账号每日活跃', '新账号按建号时的版本'],
    '含待核实': ['每日明细', '付费玩家', '周付费', '渠道构成']};
  const TAG_TIP = {'服务端':'服务端库表,全量', '埋点下限':'客户端埋点,只覆盖同意采集的玩家,人数是下限', '代理':'没有登录流水,用活跃痕迹近似,可能漏人', '混合':'不同来源的数字并列,各行口径见说明,不能直接相除', '含待核实':'金额含 PayerMax 等没有到账状态的订单'};
  const tagsFor = (t) => Object.entries(SRC_TAG).filter(([k, arr]) => arr.some(x => t.startsWith(x))).map(([k]) => `<span class="srctag" title="${TAG_TIP[k]}">${k}</span>`).join('');
  const html6 = PARTS[part].join('\n').replace(/<h3>([^<]+)/g, (m, t) => m + tagsFor(t.trim()));
  $('root').innerHTML = `<section id="sec-${part}">${html6}</section>`;
  const lab = dl.map(r => md(r.d)), acc = css('--accent'), gold = css('--gold'), slate = css('--slate');
  const stack = {x:{stacked:true}, y:{stacked:true, beginAtZero:true}};
  { const TD = N.daily, tl = TD.map(r => md(r.d)), tdd = TD.map(r => r.d), sm = {x:{}, y:{beginAtZero:true, ticks:{precision:0}}};
    mkChart('c-trreg', {evDates:tdd, type:'bar', data:{labels:tl, datasets:[{label:'广告安装', data:TD.map(r => r.reg_ad || 0), backgroundColor:css('--accent'), borderRadius:2, stack:'s'},
      {label:'其他', data:TD.map(r => r.reg_old + r.reg_new - (r.reg_ad || 0)), backgroundColor:css('--accent-soft'), borderColor:css('--accent'), borderWidth:1, borderRadius:2, stack:'s'}]}, options:{scales:{x:{stacked:true}, y:{stacked:true, beginAtZero:true}}}});
    mkChart('c-tract', {evDates:tdd, type:'bar', data:{labels:tl, datasets:[{label:'活跃', data:TD.map(r => r.act_old + r.act_new), backgroundColor:css('--accent'), borderRadius:2}]}, options:{plugins:{legend:{display:false}}, scales:sm}});
    const CH = (N.cohorts || []).filter(x => x.d1 && x.d1.base);
    mkChart('c-trd1', {evDates:CH.map(x => x.d), type:'line', data:{labels:CH.map(x => md(x.d)), datasets:[{label:'D1', data:CH.map(x => x.d1.rate), borderColor:css('--accent'), borderWidth:2, pointRadius:2}]},
      options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c) => `D1 ${fp(c.raw, 0)}(${CH[c.dataIndex].d1.n}/${CH[c.dataIndex].d1.base})`}}}, scales:{x:{}, y:{beginAtZero:true, ticks:{callback:(v) => Math.round(v*100) + '%'}}}}});
    mkChart('c-trrev', {evDates:tdd, type:'bar', data:{labels:tl, datasets:[{label:'确认到账', data:TD.map(r => r.paid_usd || 0), backgroundColor:css('--gold'), borderRadius:2, stack:'s'},
      {label:'待核实', data:TD.map(r => Math.max(0, (r.usd || 0) - (r.paid_usd || 0))), backgroundColor:'rgba(201,150,40,0.35)', borderColor:css('--gold'), borderWidth:1, borderRadius:2, stack:'s'},
      {type:'line', label:'确认到账 7 天平均', data:ma(TD.map(r => r.paid_usd || 0), 7), borderColor:css('--accent'), borderWidth:1.5, pointRadius:0, stack:'l'}]}, options:{scales:{x:{stacked:true}, y:{stacked:true, beginAtZero:true}}}});
    mkChart('c-trpay', {evDates:tdd, type:'bar', data:{labels:tl, datasets:[{label:'确认付费', data:TD.map(r => r.paid_payers || 0), backgroundColor:css('--gold'), borderRadius:2},
      {label:'下过单(含待核实)', data:TD.map(r => r.payers), backgroundColor:'rgba(201,150,40,0.35)', borderColor:css('--gold'), borderWidth:1, borderRadius:2},
      {type:'line', label:'确认付费 7 天平均', data:ma(TD.map(r => r.paid_payers || 0), 7), borderColor:css('--accent'), borderWidth:1.5, pointRadius:0}]}, options:{scales:sm}});
    if (VT) { const SD = VT.sessions.daily.filter(r => r.users), SU = VT.startup.daily.filter(r => r.resources);
      mkChart('c-trmin', {evDates:SD.map(r => r.d), type:'line', data:{labels:SD.map(r => md(r.d)), datasets:[{label:'中位数(分钟)', data:SD.map(r => r.min_p50), borderColor:css('--accent'), borderWidth:2, pointRadius:2}]}, options:{plugins:{legend:{display:false}}, scales:{x:{}, y:{beginAtZero:true}}}});
      mkChart('c-trst', {evDates:SU.map(r => r.d), type:'line', data:{labels:SU.map(r => md(r.d)), datasets:[{label:'登录成功率', data:SU.map(r => r.resources ? r.ready / r.resources : null), borderColor:css('--accent'), borderWidth:2, pointRadius:2}]},
        options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c) => `${fp(c.raw, 0)}(${SU[c.dataIndex].ready}/${SU[c.dataIndex].resources})`}}}, scales:{x:{}, y:{beginAtZero:true, max:1, ticks:{callback:(v) => Math.round(v*100) + '%'}}}}}); } }
  if (PW) mkChart('c-n6pw', {type:'bar', data:{labels:PW.map(w => md(w.from) + (w.days < 7 ? `(${w.days} 天)` : '')), datasets:[{label:'Google 确认到账', data:PW.map(w => w.Google), backgroundColor:css('--gold'), borderRadius:2, stack:'s'},
    {label:'Apple 确认到账', data:PW.map(w => w.Apple), backgroundColor:css('--slate'), borderRadius:2, stack:'s'}, {label:'待核实', data:PW.map(w => w.pending), backgroundColor:'rgba(201,150,40,0.35)', borderColor:css('--gold'), borderWidth:1, borderRadius:2, stack:'s'}]}, options:{scales:{x:{stacked:true}, y:{stacked:true, beginAtZero:true}}}});
  if (CKD.length) { const i0 = CKD.findIndex(r => r.clicks), cd = i0 < 0 ? CKD : CKD.slice(i0);
    mkChart('c-n6ck', {evDates:cd.map(r => r.d), type:'line', data:{labels:cd.map(r => md(r.d)), datasets:[{label:'点击付费的人', data:cd.map(r => r.click_users), borderColor:css('--accent'), borderWidth:2, pointRadius:2},
      {label:'下单的人', data:cd.map(r => r.order_users), borderColor:css('--slate'), borderWidth:2, pointRadius:2}, {label:'到账的人', data:cd.map(r => r.paid_users), borderColor:css('--gold'), borderWidth:2, pointRadius:2}]}, options:{scales:{x:{}, y:{beginAtZero:true, ticks:{precision:0}}}}}); }
  mkChart('c-n6reg', {evDates:N.daily.map(r=>r.d), type:'bar', data:{labels:N.daily.map(r => md(r.d)), datasets:[{label:'新建号', data:N.daily.map(r=>r.reg_new), backgroundColor:acc, borderRadius:3}, {label:'老服账号', data:N.daily.map(r=>r.reg_old), backgroundColor:gold, borderRadius:3}]}, options:{scales:stack}});
  mkChart('c-n6act', {evDates:N.daily.map(r=>r.d), type:'bar', data:{labels:N.daily.map(r => md(r.d)), datasets:[{label:'新建号', data:N.daily.map(r=>r.act_new), backgroundColor:acc, borderRadius:3}, {label:'老服账号', data:N.daily.map(r=>r.act_old), backgroundColor:gold, borderRadius:3}]}, options:{scales:stack}});
  if (M) { const mg = M.daily, si = mg.findIndex(r => r.n601 != null);
    mkChart('c-n6mig', {type:'line', data:{labels:mg.map(r => md(r.d)), datasets:[
      {label:'在老服登录', data:mg.map(r => r.old_server), borderColor:slate, borderWidth:2, pointRadius:2},
      {label:'在 601 活跃', data:mg.map(r => r.n601), borderColor:acc, borderWidth:2, pointRadius:2, spanGaps:false}]},
      options:{scales:{x:{}, y:{beginAtZero:true, ticks:{precision:0}}}},
      plugins:[{id:'cut', afterDraw(ch){ if (si < 0) return; const x = ch.scales.x.getPixelForValue(si) - 0.5*(ch.scales.x.getPixelForValue(1)-ch.scales.x.getPixelForValue(0)), a = ch.chartArea, g = ch.ctx;
        g.save(); g.strokeStyle = css('--muted'); g.setLineDash([4,4]); g.beginPath(); g.moveTo(x, a.top); g.lineTo(x, a.bottom); g.stroke(); g.restore(); }}]}); }
  const cd = N.progress.all.city_dist;
  mkChart('c-n6city', {type:'bar', data:{labels:cd.map(x => '主城 ' + x[0]), datasets:[{label:'近 3 天登录过', data:cd.map(x=>x[2]), backgroundColor:acc, borderRadius:3}, {label:'近 3 天没登录', data:cd.map(x=>x[1]-x[2]), backgroundColor:css('--accent-soft'), borderColor:acc, borderWidth:1, borderRadius:3}]}, options:{scales:stack}});
  if (TA) { const wk = TA.weeks;
    mkChart('c-n6wk', {data:{labels:wk.map(w => md(w.from) + (w.days < 7 ? `(${w.days} 天)` : '')), datasets:[
      {type:'bar', label:'老服', data:wk.map(w => w.old), backgroundColor:slate, borderRadius:3, stack:'s'},
      {type:'bar', label:'601 确认到账', data:wk.map(w => w.n601_paid ?? w.n601), backgroundColor:gold, borderRadius:3, stack:'s'},
      {type:'bar', label:'601 待核实', data:wk.map(w => w.n601_other || 0), backgroundColor:'rgba(201,150,40,0.35)', borderColor:gold, borderWidth:1, borderRadius:3, stack:'s'},
      {type:'line', label:'基线(按天数折算)', data:wk.map(w => TA.baseline * w.days / 7), borderColor:acc, borderWidth:1.5, borderDash:[5,4], pointRadius:0, stack:'l1'},
      {type:'line', label:'目标 = 基线 × 1.5', data:wk.map(w => TA.baseline * 1.5 * w.days / 7), borderColor:css('--good'), borderWidth:1.5, borderDash:[2,3], pointRadius:0, stack:'l2'}]},
      options:{scales:{x:{stacked:true}, y:{stacked:true, beginAtZero:true}}}}); }
  EV.charts(); bindInfo(); bindLinks();
}

// ================= 601 埋点与全链路(2026-11-03,第一期)
function n6ev(V){
  const none = '<div class="card"><div class="empty">埋点数据这次没有取到</div></div>';
  if (!V) return {chain:'', tech:none, techStart:none, techPerf:'', sess:'', first:'', palace:'', build:'', games:'', shop:'', dia:'', dq:none, acq:'', steps:'', dual:'', lv3:'', f7:'', charts(){}};
  const pc = (k, n) => n ? `${fp(k / n, 0)}<span class="note"> ${fi(k)}/${fi(n)}</span>` : '—';
  const sec = (x) => x == null ? '—' : x + ' 秒';
  const bars = (rows, top) => `<div class="funnel">` + rows.map((x, i) => `<div class="fr"><span>${esc(x[0])}</span><div class="fb" style="width:${Math.max(0.4, (x[1] || 0) / (top || 1) * 100)}%"></div><span class="n">${x[1] == null ? '待接入' : fi(x[1]) + (i ? ` · 本步 ${rows[i-1][1] ? fp(x[1] / rows[i-1][1], 0) : '—'}` : '')}</span></div>`).join('') + `</div>`;
  const C = V.chain, S = V.startup, SS = V.sessions, B = V.build, SH = V.shop, G = V.games, Q = V.dq;
  const stPl = C.players[0].n;
  const chain = `<h2>全链路</h2><div class="sub" style="margin:-4px 0 10px">每一步的细节:获客与安装 → 「获客与进入」;留存 → 「留存与活跃」;成长 → 「成长与玩法」;付费 → 「付费」</div>
  <div class="grid">
   <div class="card"><h3>安装 → 登录(埋点,按安装)</h3><div class="sub">一个安装 = 一次安装(重装算新的);${esc(Q.from)} 起。「本步」= 占上一步的比例</div>${bars(C.installs, C.installs[0][1])}
    <div class="note">启动失败过、之后也没登录上的安装 ${fi(S.total.failed_never_ready)} 个;失败原因见「获客与进入」</div></div>
   <div class="card"><h3>建角色 → 付费(按人)</h3><div class="sub">内测开始以来的内测玩家。每一步写了来源;埋点那步只算同意采集的人,是下限。各步不是严格嵌套(例如没完成主线也可能升到 3 级)</div>
    <div class="tw"><table><thead><tr><th>步骤</th><th>人数</th><th>占建角色</th><th>来源</th></tr></thead><tbody>${C.players.map(x => `<tr><td class="l">${esc(x.name)}</td><td>${x.n == null ? '—' : fi(x.n)}</td><td>${x.n == null ? '—' : x.base ? pc(x.n, x.base) : pc(x.n, stPl)}</td><td class="l">${esc(x.src)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">还没接进这条链路的步骤:${C.pending.map(esc).join('、')}。D1 / D7 的分母是满期的人数,不是全部建角色的人</div></div>
  </div>`;
  // 启动与技术
  const vt = V.versions.filter(x => x.installs >= 3);
  const tech = `<h2>启动与登录</h2>
  <div class="card"><h3>每日启动漏斗(按安装)</h3><div class="sub">每天完成各启动阶段的安装数,和当天登录成功的安装数</div><div class="chart"><canvas id="c-n6st"></canvas></div>
   <div class="tw" style="max-height:300px"><table><thead><tr><th>日期</th>${N6ST.map(x => `<th>${x[1]}</th>`).join('')}<th>登录成功</th><th>启动失败</th><th>失败后没登录上</th></tr></thead><tbody>${S.daily.filter(r => r.resources || r.failed).map(r => `<tr><td>${md(r.d)}</td>${N6ST.map(x => `<td>${fi(r[x[0]])}</td>`).join('')}<td>${fi(r.ready)}</td><td>${fi(r.failed)}</td><td>${fi(r.failed_never_ready)}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="grid">
   <div class="card"><h3>启动各阶段耗时</h3><div class="sub">每次完成该阶段记一条;秒</div>
    <div class="tw"><table><thead><tr><th>阶段</th><th>次数</th><th>中位数</th><th>90% 分位</th></tr></thead><tbody>${S.stage_ms.map(x => `<tr><td class="l">${esc(x.stage)}</td><td>${fi(x.n)}</td><td>${x.p50 == null ? '—' : (x.p50/1000).toFixed(1)}</td><td>${x.p90 == null ? '—' : (x.p90/1000).toFixed(1)}</td></tr>`).join('')}</tbody></table></div></div>
   <div class="card"><h3>启动失败</h3><div class="sub">按失败阶段和错误类型;安装数 = 出现过这种失败的安装。失败时的网络:${Object.entries(S.network).map(([k,v]) => `${esc({local_area:'Wi-Fi / 局域网', carrier_data:'移动数据', unknown:'未知'}[k] || k)} ${v}`).join(' · ')}</div>
    <div class="tw"><table><thead><tr><th>阶段</th><th>错误</th><th>次数</th><th>安装数</th></tr></thead><tbody>${S.fail.map(x => `<tr><td class="l">${esc(x.stage)}</td><td>${esc(x.err)}</td><td>${fi(x.n)}</td><td>${fi(x.installs)}</td></tr>`).join('') || '<tr><td colspan="4">无</td></tr>'}</tbody></table></div></div>
  </div>
  <div class="card"><h3>客户端版本</h3><div class="sub">每个版本的安装数、开始启动的安装、其中登录成功的安装;只列 ≥ 3 个安装的版本</div>
   <div class="tw"><table><thead><tr><th>版本</th><th>安装</th><th>开始启动</th><th>登录成功</th><th>登录成功率</th><th>内测玩家</th><th>出现日期</th></tr></thead><tbody>${vt.map(x => `<tr><td>${esc(x.v)}</td><td>${fi(x.installs)}</td><td>${fi(x.started)}</td><td>${fi(x.ready)}</td><td>${x.started ? fp(x.ready / x.started, 0) : '—'}</td><td>${fi(x.users)}</td><td>${esc(x.first)} ~ ${esc(x.last)}</td></tr>`).join('')}</tbody></table></div></div>
  <h2>加载与帧率</h2>
  <div class="grid">
   <div class="card"><h3>页面加载耗时</h3><div class="sub">秒;低档机 = 内存 < 3 GB 或 CPU < 4 核,高档机 = 内存 ≥ 6 GB 且 CPU ≥ 8 核</div>
    <div class="tw"><table><thead><tr><th>页面</th><th>机型</th><th>次数</th><th>中位数</th><th>90% 分位</th></tr></thead><tbody>${V.loads.slice().sort((a,b) => a.screen.localeCompare(b.screen) || (a.tier === '全部' ? -1 : b.tier === '全部' ? 1 : a.tier.localeCompare(b.tier))).map(x => `<tr${x.tier === '全部' ? ' style="font-weight:600"' : ''}><td>${esc(x.screen)}</td><td>${esc(x.tier)}</td><td>${fi(x.n)}</td><td>${sec(x.p50)}</td><td>${sec(x.p90)}</td></tr>`).join('')}</tbody></table></div></div>
   <div class="card"><h3>战斗帧率 · 按机型</h3><div class="sub">每场战斗一条;帧 / 秒的分布</div><div class="chart"><canvas id="c-n6fpst"></canvas></div></div>
  </div>
  <div class="card"><h3>战斗帧率 · 按战斗类型</h3><div class="sub">每场战斗一条;卡顿 = 单帧明显超时的次数</div>
   <div class="tw"><table><thead><tr><th>战斗类型</th><th>场数</th>${V.fps.labels.map(l => `<th>${esc(l)} 帧</th>`).join('')}<th>低于 30 帧</th><th>卡顿中位数</th><th>卡顿 90% 分位</th></tr></thead><tbody>${[V.fps.all, ...V.fps.by_mode].map(x => `<tr${x.name === '全部' ? ' style="font-weight:600"' : ''}><td class="l">${esc(x.name)}</td><td>${fi(x.n)}</td>${x.b.map(v => `<td>${fi(v)}</td>`).join('')}<td>${pc(x.b[0] + x.b[1], x.n)}</td><td>${x.stall_p50 ?? '—'}</td><td>${x.stall_p90 ?? '—'}</td></tr>`).join('')}</tbody></table></div></div>
  <h2>请求失败与异常</h2>
  <div class="grid">
   <div class="card"><h3>关键请求失败</h3><div class="sub">登录、主城初始化、支付、充值领奖四类请求;安装数 = 出现过的安装</div>
    <div class="tw"><table><thead><tr><th>请求</th><th>错误</th><th>次数</th><th>安装数</th></tr></thead><tbody>${V.reqfail.by.map(x => `<tr><td>${esc(x.stage)}</td><td>${esc(x.err)}</td><td>${fi(x.n)}</td><td>${fi(x.users)}</td></tr>`).join('') || '<tr><td colspan="4">无</td></tr>'}</tbody></table></div>
    <div class="chart"><canvas id="c-n6req"></canvas></div></div>
   <div class="card"><h3>客户端异常</h3><div class="sub">按出错的模块;只记捕获到的异常,不是全量崩溃。战斗中断 ${fi(V.interrupted)} 次</div>
    <div class="tw"><table><thead><tr><th>模块</th><th>次数</th></tr></thead><tbody>${V.exceptions.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fi(x[1])}</td></tr>`).join('') || '<tr><td colspan="2">无</td></tr>'}</tbody></table></div></div>
  </div>`;
  // 会话
  // 获客来源(2026-11-04):B72 起首次启动带安装来源;只覆盖同意采集的玩家
  const A = V.acq;
  const acq = `<h2>获客来源</h2>` + (A ? `
  <div class="grid">
   <div class="card"><h3>新安装按来源 · 每天</h3><div class="sub">Google Play 安装来源(埋点 session_start 的 install_referrer,每个安装取第一次);${esc(A.from)} 起(B72 / 2.4.0053 才开始带)</div><div class="chart"><canvas id="c-n6acq"></canvas></div></div>
   <div class="card"><h3>各来源合计</h3><div class="tw"><table><thead><tr><th>来源</th><th>新安装</th><th>其中登录成为 601 角色</th></tr></thead><tbody>${A.total.map(x => `<tr><td class="l">${esc(x.src)}</td><td>${fi(x.installs)}</td><td>${pc(x.roles, x.installs)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">B72 及以后版本有 session_start 的安装 ${fi(A.b72_installs)} 个,其中带安装来源的 ${fi(A.with_ref)} 个(只在首次启动上报,重装、升级不报)。只有同意采集的玩家才上报,是下限;iOS 没有这个字段。账号库的广告 ID 记录 11-04 开投后 601 新号仍为 0,所以来源暂以这里为准</div></div>
  </div>` : `<div class="card"><div class="empty">还没有安装来源数据:B72(2.4.0053)11-04 发版后才开始上报,数据截至日到 11-04 以后会出现</div></div>`);
  // 2026-11-04:引导 step_id 分布(B72 起)、留存双轨(埋点会话 vs 代理)
  const ST = V.steps, RD = V.ret_dual;
  const steps = `<div class="card"><h3>引导步骤 · 埋点(E023 step_id)</h3>` + (ST ? `<div class="sub">${esc(ST.from)} 起(B72 才带 step_id),完成过各步骤的内测玩家 ${fi(ST.users)} 人。<b>研发还没给步骤顺序和名称</b>,这里只按编号列出人数,不是漏斗,相邻两行不能相除</div>
   <div class="tw" style="max-height:300px"><table><thead><tr><th>step_id</th><th>完成人数</th></tr></thead><tbody>${ST.rows.map(x => `<tr><td>${x[0]}</td><td>${fi(x[1])}</td></tr>`).join('')}</tbody></table></div></div>`
    : `<div class="empty">还没有 step_id 数据:B72(2.4.0053)11-04 发版后才开始上报,数据截至日到 11-04 以后会出现。引导步骤漏斗要等研发给步骤顺序表,在此之前不计算</div></div>`);
  const SCN = {login:'登录界面', city:'主城', world:'世界地图', building_detail:'建筑详情', battle_prepare:'战斗准备', battle:'战斗中', battle_result:'战斗结算', shop:'商店', alliance:'联盟', hero:'英雄', other:'其他界面'};
  const ENDN = {background:'切到后台', role_change:'切换角色 / 账号', shutdown:'关闭游戏', recovered:'异常后恢复'};
  const ls = SS.last_screen || {}, lsn = SS.last_screen_n || 0, er = SS.end_reason || {}, ern = Object.values(er).reduce((a, b) => a + b, 0);
  const lastCard = `<div class="grid">
   <div class="card"><h3>会话结束时停在哪个界面</h3>${lsn ? `<div class="sub">每次会话结束时所在的界面(内测玩家),共 ${fi(lsn)} 次会话带界面信息(B72 起才有);每个界面停留多久要等离开界面事件(E131)发版</div>
    <div class="tw"><table><thead><tr><th>界面</th><th>会话数</th><th>占比</th></tr></thead><tbody>${Object.entries(ls).map(([k, v]) => `<tr><td class="l">${esc(SCN[k] || k)}</td><td>${fi(v)}</td><td>${fp(v / lsn, 0)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">还没有界面信息:B72(2.4.0053)起才上报</div>'}</div>
   <div class="card"><h3>会话怎么结束</h3><div class="sub">共 ${fi(ern)} 次会话(内测玩家)</div>
    <div class="tw"><table><thead><tr><th>结束方式</th><th>会话数</th><th>占比</th></tr></thead><tbody>${Object.entries(er).map(([k, v]) => `<tr><td class="l">${esc(ENDN[k] || k)}</td><td>${fi(v)}</td><td>${fp(v / ern, 0)}</td></tr>`).join('')}</tbody></table></div></div>
  </div>`;
  const LDD = (V.loads_daily || []).filter(r => r.n), FPD = (V.fps_daily || []).filter(r => r.n);
  const perfTrend = LDD.length || FPD.length ? `<h2>性能趋势<span class="note" style="font-weight:400"> · 埋点起始日以来</span></h2><div class="grid">
   ${LDD.length ? `<div class="card"><h3>页面加载耗时 · 按天</h3><div class="sub">每天各页面加载耗时的中位数,秒</div><div class="chart" style="height:200px"><canvas id="c-n6ldd"></canvas></div></div>` : ''}
   ${FPD.length ? `<div class="card"><h3>战斗低于 30 帧的占比 · 按天</h3><div class="sub">每场战斗一条,帧率在 30 帧以下的场次占比;悬停看场次</div><div class="chart" style="height:200px"><canvas id="c-n6fpd"></canvas></div></div>` : ''}
  </div>` : '';
  const OSV = V.os;
  const osCard = OSV && OSV.length ? `<h2>按系统版本</h2><div class="card"><h3>启动与加载 · 按系统版本</h3><div class="sub">B72 起事件带系统版本;按安装数取前 12 个。登录成功率 = 开始启动的安装里登录成功的比例;加载中位数来自页面加载事件</div>
   <div class="tw"><table><thead><tr><th>系统版本</th><th>安装</th><th>开始启动</th><th>登录成功</th><th>登录成功率</th><th>启动失败过的安装</th><th>页面加载中位数</th></tr></thead><tbody>${OSV.map(x => `<tr><td class="l">${esc(x.v)}</td><td>${fi(x.installs)}</td><td>${fi(x.started)}</td><td>${fi(x.ready)}</td><td>${pc(x.ready, x.started)}</td><td>${fi(x.fail)}</td><td>${x.load_p50 == null ? '—' : x.load_p50 + ' 秒'}<span class="note"> n=${x.load_n}</span></td></tr>`).join('')}</tbody></table></div></div>` : '';
  const F7 = V.first7_daily;
  const f7Card = F7 ? `<div class="card"><h3>新人前 7 天 · 逐日</h3><div class="sub">注册满 7 天的内测玩家 ${fi(F7.n)} 人,第 0–6 天每天的情况。活跃 = 活跃痕迹(全部人);会话、时长、商店、建筑升级来自埋点,只覆盖同意采集的人(10-29 起,当前 ${fi(F7.ev_n)} 人)${F7.ev_n < 30 ? ',<b>埋点几列样本不足,只作参考</b>' : ''}</div>
   <div class="tw"><table><thead><tr><th>第几天</th><th>活跃</th><th>活跃占比</th><th>有会话的人</th><th>当天游戏时长中位数</th><th>打开商店的人</th><th>建筑升级次数</th></tr></thead><tbody>${F7.rows.map(x => `<tr><td>第 ${x.k} 天</td><td>${fi(x.act)}</td><td>${fp(F7.n ? x.act / F7.n : null, 0)}</td><td>${fi(x.ses)}</td><td>${x.min_p50 == null ? '—' : x.min_p50 + ' 分钟'}</td><td>${fi(x.shop)}</td><td>${fi(x.upg)}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const L3 = V.lv3;
  const lv3 = `<div class="card"><h3>注册后多久到主城 Lv3 · 埋点</h3>` + (L3 ? `<div class="sub">${esc(L3.from)} 起注册、且注册当天就有埋点的内测玩家 ${fi(L3.n)} 人;用建筑升级完成埋点(E034,B72 起带 target_level 和时间)找第一次升到主城 Lv3 的时刻</div>
   <div class="tw"><table><thead><tr><th>已升到 Lv3</th><th>注册到 Lv3 用时(中位数)</th><th>满 24 小时的人</th><th>其中 24 小时内到 Lv3</th></tr></thead><tbody><tr><td>${pc(L3.reached, L3.n)}</td><td>${L3.p50_h == null ? '—' : L3.p50_h + ' 小时'}</td><td>${fi(L3.mature)}</td><td>${L3.mature ? pc(L3.in24, L3.mature) : '—(还没有人满 24 小时)'}</td></tr></tbody></table></div>
   <div class="note">「首日 Lv3 转化率」只算注册满 24 小时的人;样本在积累中。只覆盖同意采集的玩家</div></div>`
    : `<div class="empty">还没有数据:要等 B72 之后注册的玩家攒够埋点</div></div>`);
  const ci_ = (k, n, ci) => n ? `${fp(k / n, 0)}<span class="note"> ${k}/${n}${ci ? `<br>[${fp(ci[0],0)}–${fp(ci[1],0)}]` : ''}</span>` : '—';
  const dual = RD ? `<div class="card"><h3>留存双轨:埋点会话 vs 活跃痕迹</h3><div class="sub">同一批人:注册当天就有埋点的内测玩家(${fi(RD.obs)} 人,埋点 ${esc(RD.from || '')} 起)。<b>埋点会话</b> = 第 N 天有启动或登录成功的埋点;<b>活跃痕迹</b> = 看板现行的代理口径。埋点只覆盖同意采集的人,是可观测子集,不能替代全量;两种口径不相加</div>
   <div class="tw"><table><thead><tr><th>留存</th><th>满期人数</th><th>埋点会话</th><th>活跃痕迹</th><th>任一口径</th></tr></thead><tbody>${RD.rows.map(x => `<tr><td>D${x.n}</td><td>${fi(x.base)}</td><td>${ci_(x.session, x.base, x.ci_s)}</td><td>${ci_(x.proxy, x.base, x.ci_p)}</td><td>${x.base ? fi(x.either) : '—'}</td></tr>`).join('')}</tbody></table></div>
   <div class="note">满期人数为 0 的行表示这批人还没到第 N 天,显示「—」,不是 0。两种口径差得越多,说明活跃痕迹漏掉的人越多</div></div>` : '';
  const sess = `<h2>会话与活跃时段</h2>
  <div class="grid">
   <div class="card"><h3>单次会话时长</h3><div class="sub">登录后的会话(内测玩家),切到后台或退出算一次结束;中位数 ${sec(SS.p50)},75% 分位 ${sec(SS.p75)},90% 分位 ${sec(SS.p90)}(共 ${fi(SS.n)} 次)</div><div class="chart"><canvas id="c-n6sess"></canvas></div></div>
   <div class="card"><h3>一天里什么时候在玩</h3><div class="sub">按小时(中国时间)统计有埋点的内测玩家人数,${esc(Q.from)} 以来合计</div><div class="chart"><canvas id="c-n6hour"></canvas></div></div>
  </div>
  <div class="card"><h3>每人每天游戏时长</h3><div class="sub">每人每天会话活跃时长合计,分钟;整体中位数 ${SS.user_day.min_p50 ?? '—'},75% 分位 ${SS.user_day.min_p75 ?? '—'},90% 分位 ${SS.user_day.min_p90 ?? '—'}(${fi(SS.user_day.n)} 个人天)</div><div class="chart"><canvas id="c-n6min"></canvas></div></div>`;
  const first = `<h2>注册当天</h2>
  <div class="grid">
   <div class="card"><h3>注册当天游戏时长 × 次日回来</h3><div class="sub">只算注册当天有埋点、已满 1 天的内测玩家;次日回来 = 次日有埋点或每日任务记录。只是相关,不代表时长长就能留下</div>
    <div class="tw"><table><thead><tr><th>注册当天时长</th><th>人数</th><th>次日回来</th></tr></thead><tbody>${V.first_day.map(x => `<tr><td>${esc(x.name)}</td><td>${fi(x.n)}</td><td>${pc(x.d1, x.n)}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">人数少,比例只作参考</div></div>
   <div class="card"><h3>建筑升级怎么完成</h3><div class="sub">埋点里所有建筑升级(${fi(B.n)} 次,${fi(B.users)} 位内测玩家);免费立即完成 = 剩余时间在 VIP 免费时长内</div><div class="chart"><canvas id="c-n6bm"></canvas></div>
    <div class="note">升级受阻(资源不足)${fi(B.blocked)} 次;成长资源不足:${B.shortage.map(x => `${esc({building:'建筑', equipment_refine:'装备精炼', hero_magic:'英雄法术', hero_level:'英雄升级'}[x[0]] || x[0])} ${x[1]}`).join(' · ') || '无'}</div></div>
  </div>`;
  const PH = V.palace_hist;
  const palace = PH ? `<h2>主城等级随时间</h2>
  <div class="card"><h3>每天各主城等级的人数</h3><div class="sub">来自旧后台每天对 601 全服角色做的等级快照(10-01 起),<b>含测试号和内测前的角色</b>,人数和下面略有出入;只用来看分布怎么随天移动。601 库本身只存当前等级</div><div class="chart"><canvas id="c-n6ph"></canvas></div></div>` : '';
  const build = `<div class="card"><h3>建筑升级 · 按类型</h3><div class="sub">埋点里的建筑升级次数,按完成方式拆</div>
   <div class="tw"><table><thead><tr><th>建筑</th><th>升级次数</th>${Object.values(N6DONE).map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>${B.by_type.map(x => `<tr><td class="l">${esc(x.name)}</td><td>${fi(x.n)}</td>${Object.values(N6DONE).map(k => `<td>${fi(x[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  const gm = (g, nm, unit) => g ? `<tr><td class="l">${nm}</td><td>${fi(g.users)}</td><td>${fi(g.rounds)}</td><td>${fi(g.dia_rounds)}<span class="note"> ${fi(g.dia_users)} 人</span></td><td>${fi(g.ticket_rounds)}</td><td>${fi(g.bet)}</td><td>${fi(g.reward)}</td><td>${g.bet ? fp(g.reward / g.bet, 0) : '—'}</td><td>${g.per_user_p50 ?? '—'} / ${fi(g.per_user_max)}</td></tr>` : '';
  const games = `<h2>小游戏</h2>
  <div class="card"><h3>宠物竞猜与老虎机</h3><div class="sub">内测开始以来的内测玩家;一轮 / 一局记一条。钻石下注、返还只算用了钻石的轮次;用券的不花钻石,单列。返还率 = 返还 ÷ 下注</div>
   <div class="tw"><table><thead><tr><th>小游戏</th><th>玩过的人</th><th>轮 / 局</th><th>用钻石</th><th>只用券</th><th>钻石下注</th><th>钻石返还</th><th>返还率</th><th>每人轮数 中位 / 最多</th></tr></thead><tbody>${gm(G.petquiz, '宠物竞猜')}${gm(G.slot, '老虎机')}</tbody></table></div>
   <div class="chart"><canvas id="c-n6gm"></canvas></div></div>`;
  const PCS = V.pay_chain.steps;
  const shop = `<h2>商店与付费链路</h2>
  <div class="grid">
   <div class="card"><h3>商店 → 付费(埋点玩家)</h3><div class="sub">只算埋点里出现过的内测玩家(${esc(V.pay_chain.since)} 以来);看到过商品 = 有商品曝光记录。「点商品」「支付结果」事件还没接入</div>${bars(PCS, PCS[0][1])}</div>
   <div class="card"><h3>从哪里进商店、先看哪页</h3><div class="sub">打开商店 ${fi(SH.opens)} 次,${fi(SH.users)} 位内测玩家</div>
    <div class="tw"><table><thead><tr><th>入口</th><th>次数</th></tr></thead><tbody>${SH.entry.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fi(x[1])}</td></tr>`).join('')}</tbody></table></div>
    <div class="tw" style="margin-top:8px"><table><thead><tr><th>打开时落在的页签</th><th>次数</th></tr></thead><tbody>${SH.tab.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fi(x[1])}</td></tr>`).join('')}</tbody></table></div>
    <div class="tw" style="margin-top:8px"><table><thead><tr><th>商品曝光位置</th><th>次数</th><th>人数</th></tr></thead><tbody>${SH.impr.map(x => `<tr><td class="l">${esc(x[0])}</td><td>${fi(x[1])}</td><td>${fi(x[2])}</td></tr>`).join('')}</tbody></table></div></div>
  </div>
  <div class="card"><h3>每天打开商店的人</h3><div class="sub">当天打开过商店的内测玩家 / 当天埋点里出现的内测玩家</div><div class="chart"><canvas id="c-n6shop"></canvas></div></div>`;
  const DI = V.diamonds;
  const dia = DI ? `<div class="card"><h3>玩家手里的钻石</h3><div class="sub">内测玩家当前钻石存量(${fi(DI.n)} 人有记录):中位数 ${fi(DI.p50)},90% 分位 ${fi(DI.p90)},最多 ${fi(DI.max)},合计 ${fi(DI.total)}</div><div class="chart"><canvas id="c-n6dia"></canvas></div></div>` : '';
  const cv = V.coverage.filter(x => x.act && x.d >= Q.from);
  const dq = `<h2>埋点数据质量</h2>
  <div class="kpis">
   ${kpiCard({label:'埋点行数(Invader · 601)', val:fi(Q.rows), lines:[`${esc(Q.from)} 起;最近一条 ${esc(Q.last_at)}`, `原始 ${fi(Q.raw_rows)} 行,去掉测试号安装和截至日之后的`]})}
   ${kpiCard({label:'内测玩家 / 安装', val:`${fi(Q.users)} / ${fi(Q.installs)}`, lines:[`登录前的事件占 ${fp(Q.anon_share, 0)}(没有玩家 ID)`, Object.entries(Q.platform).map(([k,v]) => `${k} ${fi(v)} 行`).join(' · ')]})}
  </div>
  <div class="card"><h3>每天埋点覆盖了多少活跃玩家</h3><div class="sub">埋点里出现的内测玩家 ÷ 看板活跃(活跃痕迹口径)。只有同意采集的玩家才上报,覆盖不到 100% 是正常的</div><div class="chart"><canvas id="c-n6cov"></canvas></div>
   <div class="tw" style="max-height:260px"><table><thead><tr><th>日期</th><th>埋点里的内测玩家</th><th>看板活跃</th><th>覆盖</th><th>安装数</th></tr></thead><tbody>${cv.map(x => `<tr><td>${md(x.d)}</td><td>${fi(x.ev_users)}</td><td>${fi(x.act)}</td><td>${pc(x.ev_users, x.act)}</td><td>${fi(x.installs)}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="grid">
   <div class="card"><h3>字段可用性</h3><div class="tw"><table><thead><tr><th>字段</th><th>情况</th></tr></thead><tbody>
    <tr><td class="l">新手引导步骤(E023)</td><td class="l">guide_id 只有 ${Q.guide_ids.join(' / ') || '—'}(是引导类型,不是步骤号);引导漏斗要等 step_id 接入</td></tr>
    <tr><td class="l">是否老账号(E019)</td><td class="l">空 ${fp(Q.existing_null, 0)}</td></tr>
    <tr><td class="l">登录方式(E019)</td><td class="l">${Object.entries(Q.login_methods).map(([k,v]) => `${esc(k)} ${v}`).join(' · ')}(切换第三方账号也记 native,区分不了游客和绑定账号)</td></tr>
    <tr><td class="l">国家</td><td class="l">几乎全是「Old mobile version」,不可用</td></tr>
    <tr><td class="l">商品资格、目录版本(E075 / E076)</td><td class="l">资格全空;目录版本全是 unknown</td></tr>
    <tr><td class="l">事件时间</td><td class="l">部分手机时钟不准(有落在未来一周的);看板一律用服务器收件时间</td></tr>
    <tr><td class="l">去重(event_uuid)</td><td class="l">数仓不去重。带 uuid 的 ${fi(Q.uuid_rows)} 行里重复 ${fi(Q.dup_rows)} 行,已去掉;B72 之前的版本不带 uuid(${fi(Q.no_uuid_rows)} 行),没法精确去重</td></tr>
    <tr><td class="l">服号为空</td><td class="l">不只是登录前事件:商店打开、商品曝光等登录后事件也常没有服号,看板按玩家 ID 认角色,不按服号</td></tr>
   </tbody></table></div></div>
   <div class="card"><h3>各事件条数</h3><div class="tw" style="max-height:320px"><table><thead><tr><th>事件</th><th>条数</th></tr></thead><tbody>${Q.events.map(x => `<tr><td class="l">${esc(x[0].replace('invader_',''))}</td><td>${fi(x[1])}</td></tr>`).join('')}</tbody></table></div>
    <div class="note">过滤规则:只取 app_source = INVADER(去掉混进来的 Looba 事件)、服号为空(登录前)或 601(去掉测试服 1、3);出现过排除名单账号的安装整条去掉(${fi(Q.test_installs)} 个)</div></div>
  </div>`;
  function charts(){
    const acc = css('--accent'), gold = css('--gold'), slate = css('--slate'), vio = css('--violet'), good = css('--good'), bad = css('--bad'), soft = css('--accent-soft');
    const stack = {x:{stacked:true}, y:{stacked:true, beginAtZero:true}};
    const sd = S.daily.filter(r => r.resources || r.failed);
    mkChart('c-n6st', {evDates:sd.map(r=>r.d), type:'bar', data:{labels:sd.map(r => md(r.d)), datasets:[{label:'资源准备完成', data:sd.map(r => r.resources), backgroundColor:soft, borderColor:acc, borderWidth:1, borderRadius:3},
      {label:'登录成功', data:sd.map(r => r.ready), backgroundColor:acc, borderRadius:3}, {label:'启动失败', data:sd.map(r => r.failed), backgroundColor:bad, borderRadius:3}]}, options:{scales:{x:{}, y:{beginAtZero:true}}}});
    const pal = [bad, gold, slate, acc, good];
    const ft = V.fps.by_tier.filter(x => x.n >= 5);
    mkChart('c-n6fpst', {type:'bar', data:{labels:ft.map(x => `${x.name}(${x.n})`), datasets:V.fps.labels.map((l, i) => ({label:l + ' 帧', data:ft.map(x => x.n ? x.b[i] / x.n : 0), backgroundColor:pal[i]}))},
      options:{indexAxis:'y', scales:{x:{stacked:true, max:1, ticks:{callback:(v) => Math.round(v*100) + '%'}}, y:{stacked:true}}, plugins:{tooltip:{callbacks:{label:(c) => `${c.dataset.label}:${fp(c.raw,0)}`}}}}});
    const rd = V.reqfail.daily.filter(r => Object.values(r).some(v => typeof v === 'number' && v > 0)), rk = ['账号登录', '主城初始化', '支付', '充值领奖'];
    mkChart('c-n6req', {evDates:rd.map(r=>r.d), type:'bar', data:{labels:rd.map(r => md(r.d)), datasets:rk.map((k, i) => ({label:k, data:rd.map(r => r[k]), backgroundColor:[acc, slate, bad, gold][i]}))}, options:{scales:stack}});
    mkChart('c-n6sess', {type:'bar', data:{labels:SS.dist.map(x => x[0]), datasets:[{label:'会话数', data:SS.dist.map(x => x[1]), backgroundColor:acc, borderRadius:3}]}, options:{plugins:{legend:{display:false}}, scales:{x:{}, y:{beginAtZero:true}}}});
    mkChart('c-n6hour', {type:'bar', data:{labels:SS.hours.map(x => x[0] + '点'), datasets:[{label:'玩家人数(按小时去重后相加)', data:SS.hours.map(x => x[1]), backgroundColor:acc, borderRadius:3}]}, options:{plugins:{legend:{display:false}}, scales:{x:{}, y:{beginAtZero:true}}}});
    const md_ = SS.daily.filter(r => r.users);
    mkChart('c-n6min', {evDates:md_.map(r=>r.d), data:{labels:md_.map(r => md(r.d)), datasets:[{type:'bar', label:'有会话的人', data:md_.map(r => r.users), backgroundColor:soft, borderColor:acc, borderWidth:1, yAxisID:'y1', borderRadius:3},
      {type:'line', label:'每人时长中位数(分钟)', data:md_.map(r => r.min_p50), borderColor:gold, borderWidth:2, pointRadius:2, yAxisID:'y'},
      {type:'line', label:'每人时长平均(分钟)', data:md_.map(r => r.min_mean), borderColor:vio, borderWidth:1.5, borderDash:[4,3], pointRadius:0, yAxisID:'y'}]},
      options:{scales:{x:{}, y:{beginAtZero:true, position:'left'}, y1:{beginAtZero:true, position:'right', grid:{display:false}}}}});
    mkChart('c-n6bm', {type:'bar', data:{labels:B.method.map(x => x[0]), datasets:[{label:'次数', data:B.method.map(x => x[1]), backgroundColor:acc, borderRadius:3}]}, options:{indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{beginAtZero:true}, y:{}}}});
    if (PH) { const cols = [slate, soft, acc, gold, good];
      mkChart('c-n6ph', {type:'bar', data:{labels:PH.rows.map(r => md(r[0])), datasets:PH.bands.map((b, i) => ({label:'主城 ' + b, data:PH.rows.map(r => r[i+1]), backgroundColor:cols[i], borderColor:acc, borderWidth:i === 1 ? 1 : 0}))}, options:{scales:stack}}); }
    if (G.petquiz || G.slot) { const pd = (G.petquiz || G.slot).daily, i0 = pd.findIndex((r, i) => r.rounds || ((G.slot||{}).daily||[])[i]?.rounds), dd = i0 < 0 ? pd : pd.slice(i0);
      mkChart('c-n6gm', {evDates:dd.map(r=>r.d), type:'bar', data:{labels:dd.map(r => md(r.d)), datasets:[{label:'宠物竞猜(人)', data:dd.map(r => r.users), backgroundColor:acc, borderRadius:3},
        {label:'老虎机(人)', data:G.slot ? G.slot.daily.slice(i0 < 0 ? 0 : i0).map(r => r.users) : [], backgroundColor:gold, borderRadius:3}]}, options:{scales:{x:{}, y:{beginAtZero:true, ticks:{precision:0}}}}}); }
    const shd = SH.daily.filter(r => r.ev_users);
    mkChart('c-n6shop', {evDates:shd.map(r=>r.d), type:'bar', data:{labels:shd.map(r => md(r.d)), datasets:[{label:'埋点里的内测玩家', data:shd.map(r => r.ev_users), backgroundColor:soft, borderColor:acc, borderWidth:1, borderRadius:3}, {label:'其中打开过商店', data:shd.map(r => r.open_users), backgroundColor:acc, borderRadius:3}]}, options:{scales:{x:{}, y:{beginAtZero:true}}}});
    if (DI) mkChart('c-n6dia', {type:'bar', data:{labels:DI.dist.map(x => x[0] + ' 钻'), datasets:[{label:'人数', data:DI.dist.map(x => x[1]), backgroundColor:gold, borderRadius:3}]}, options:{plugins:{legend:{display:false}}, scales:{x:{}, y:{beginAtZero:true}}}});
    if (LDD.length) mkChart('c-n6ldd', {evDates:LDD.map(r => r.d), type:'line', data:{labels:LDD.map(r => md(r.d)), datasets:['主城', '世界地图', '战斗'].map((k, i) => ({label:k, data:LDD.map(r => r[k]), borderColor:[acc, gold, slate][i], borderWidth:2, pointRadius:2, spanGaps:true}))}, options:{scales:{x:{}, y:{beginAtZero:true}}}});
    if (FPD.length) mkChart('c-n6fpd', {evDates:FPD.map(r => r.d), type:'line', data:{labels:FPD.map(r => md(r.d)), datasets:[{label:'低于 30 帧', data:FPD.map(r => r.lt30 / r.n), borderColor:bad, borderWidth:2, pointRadius:2}]},
      options:{plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c) => `${fp(c.raw, 0)}(${FPD[c.dataIndex].lt30}/${FPD[c.dataIndex].n} 场)`}}}, scales:{x:{}, y:{beginAtZero:true, max:1, ticks:{callback:(v) => Math.round(v*100) + '%'}}}}});
    if (A) { const ad = A.daily, cl = [acc, vio, good, slate, gold];
      mkChart('c-n6acq', {evDates:ad.map(r=>r.d), type:'bar', data:{labels:ad.map(r => md(r.d)), datasets:A.srcs.map((s_, i) => ({label:s_, data:ad.map(r => r[s_]), backgroundColor:cl[i], borderRadius:3}))}, options:{scales:stack}}); }
    mkChart('c-n6cov', {evDates:cv.map(x=>x.d), data:{labels:cv.map(x => md(x.d)), datasets:[{type:'bar', label:'看板活跃', data:cv.map(x => x.act), backgroundColor:soft, borderColor:acc, borderWidth:1, borderRadius:3},
      {type:'bar', label:'埋点里的内测玩家', data:cv.map(x => x.ev_users), backgroundColor:acc, borderRadius:3}]}, options:{scales:{x:{}, y:{beginAtZero:true}}}});
  }
  const ti = tech.indexOf('<h2>加载与帧率</h2>'), techStart = ti < 0 ? tech : tech.slice(0, ti), techPerf = ti < 0 ? '' : tech.slice(ti);
  // 技术卡的数据状态(2026-11-05,用户需求 5.7):事件没出现 / 样本不足(<30)单独标出,不让「没数据」看起来像「没问题」
  const evN = Object.fromEntries(Q.events || []);
  const stateOf = (ev, n) => !evN[ev] ? '<span class="srctag" title="数仓里没有这个事件:可能没开启,也可能没发生">未采集到</span>' : (n != null && n < 30 ? `<span class="srctag" title="样本少于 30,只作参考">样本不足 n=${n}</span>` : '');
  const sumN = (arr) => (arr || []).reduce((a, x) => a + (x.n || 0), 0);
  let tp = techPerf;
  [['页面加载耗时', 'invader_screen_load_summary', sumN((V.loads || []).filter(x => x.tier === '全部'))], ['战斗帧率 · 按机型', 'invader_battle_performance_summary', sumN(V.fps && V.fps.by_tier)],
   ['战斗帧率 · 按战斗类型', 'invader_battle_performance_summary', null], ['关键请求失败', 'invader_critical_request_failed', null], ['客户端异常', 'invader_client_exception_summary', null]]
    .forEach(([t, ev, n]) => { tp = tp.replace(`<h3>${t}</h3>`, `<h3>${t}${stateOf(ev, n)}</h3>`); });
  return {chain, tech, techStart, techPerf:perfTrend + tp + osCard, sess:sess + lastCard, first, palace, build, games, shop, dia, dq, acq, steps, dual, lv3, f7:f7Card, charts};
}
const N6ST = [['resources','资源准备'], ['account_version','账号 / 版本检查'], ['connection','连接游戏服'], ['city_initialization','主城初始化']];
const N6DONE = {free:'免费立即完成', natural:'自然计时完成', diamond:'花钻石', card:'加速卡'};

// ================= 异常中心
function alerts(){
  const g = D.gameplay_pulse || [];
  $('root').innerHTML = `<section id="sec-alerts">
  <div class="card"><h3>游戏健康度</h3><div class="sub">${(D.health||[]).length} 个维度分别判断,不合成总分;点开看原因</div><div class="health" id="health"></div><div id="health-why" class="note"></div></div>
  ${(D.checks||[]).length ? `<div class="card"><h3>数据自洽检查</h3><div class="note">${checksSummary()}${(D.checks||[]).filter(x => x.status === 'warn').map(x => `<br>· 需核对:${esc(x.name)}(${esc(x.value)})`).join('')}</div>${link('defs', '看全部检查项')}</div>` : ''}
  <div class="card"><h3>持续性异常 · ${md(END)}</h3><div class="sub">只列持续一周以上的变化;全量计算,不随筛选变化</div>${alertTable((D.alerts||[]).filter(a => a.persistent !== false && a.level !== 'info'), false)}</div>
  <div class="card"><h3>提示</h3><div class="sub">单日起伏、注册上升等,不算异常,仅供参考</div>${alertTable((D.alerts||[]).filter(a => a.persistent === false || a.level === 'info'), false)}</div>
  <div class="card"><h3>核心玩法日参与</h3><div class="sub">近 7 天日均参与人数 vs 之前 28 天;下降超过 20% 报「观察中」</div>
   <div class="tw"><table><thead><tr><th>玩法</th><th>近 7 天日均</th><th>前 28 天日均</th><th>变化</th></tr></thead><tbody>${g.map(x => `<tr><td>${esc(x.name)}</td><td>${x.now}</td><td>${x.base}</td><td>${sgn(x.dev)}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="card"><h3>告警规则</h3><div class="tw"><table><thead><tr><th>告警</th><th>条件</th><th>级别</th></tr></thead><tbody>
   <tr><td>活跃</td><td class="l">近 7 天 DAU 均值比前 4 周低 10% 以上;连续两周都低 20% 以上才是「需关注」</td><td>观察中 / 需关注</td></tr>
   <tr><td>新注册</td><td class="l">近 7 天比前 4 周周均低 50% 以上;上升只作提示</td><td>观察中 / 提示</td></tr>
   <tr><td>进入游戏率、当天到 Lv3(分平台)</td><td class="l">近 14 天或近 28 天比更早 28 天低 20% 以上,且样本够(注册 ≥ 30、进入 ≥ 40)</td><td>观察中</td></tr>
   <tr><td>D1</td><td class="l">最近 7 个满期注册日比之前 28 天低 30% 以上</td><td>观察中</td></tr>
   <tr><td>收入</td><td class="l">近 7 天比前 4 周周均低 30% 以上;连续两周都低 30% 以上才是「需关注」。单日偏离只作提示</td><td>观察中 / 需关注 / 提示</td></tr>
   <tr><td>付费人次 / ARPPU</td><td class="l">近 7 天付费人次比前 4 周低 30% 以上 / ARPPU 偏离 40% 以上只作提示</td><td>观察中 / 提示</td></tr>
   <tr><td>大 R</td><td class="l">连续 7 天没登录,或前 30 天 ≥ $1,000 而近 30 天为 0 → 需关注;风险分 ≥ 2 → 观察中</td><td>需关注 / 观察中</td></tr>
   <tr><td>玩法参与</td><td class="l">入侵、联盟捐献、副本 1 的近 7 天日均比之前 28 天低 20% 以上</td><td>观察中</td></tr>
   <tr><td>DAU 单日断崖</td><td class="l">昨天 DAU 不到前 4 周同星期中位数的一半(可能是宕机或数据缺失)</td><td>观察中</td></tr>
   <tr><td>单一机型注册集中</td><td class="l">近 7 天任一天,单一机型占当天注册 ≥ 30% 且当天注册 ≥ 20</td><td>提示</td></tr>
   <tr><td>601 真新设备留存低于底线</td><td class="l">D1 或 D7 的 95% 区间整体低于底线(22.6% / 4.9%);区间跨线不报</td><td>观察中</td></tr>
   <tr><td>601 连续无真实订单</td><td class="l">连续 5 天以上没有真实订单(已去掉测试号)</td><td>观察中</td></tr>
   <tr><td>首次付费人数</td><td class="l">老服近 14 天首次付费人数低于之前 8 个两周均值的一半,且基准 ≥ 4 人</td><td>观察中</td></tr>
   <tr><td>主城到顶占比上升</td><td class="l">近 4 周到顶人数占比的均值比前 4 周高 3 个百分点以上</td><td>观察中</td></tr>
   <tr><td>钻石净发</td><td class="l">游戏内循环 + 博彩的净额连续两周为正;外部接入(WPP、GameAPI)没有扣钻记录,不计入,占游戏内消耗一半以上时只作提示</td><td>观察中 / 提示</td></tr>
   <tr><td>老虎机返还率</td><td class="l">只看钻石下注的局,近 7 天返还 ÷ 下注 > 100%;用券的局不花钻石,单列</td><td>观察中</td></tr>
   <tr><td>老虎机券积压</td><td class="l">近 7 天券发出数 ≥ 使用数的 2 倍;使用 = 宠物竞猜 + 老虎机两种用途合计</td><td>观察中</td></tr>
   <tr><td>数据过期</td><td class="l">数据截至日距今天超过 2 天,页面顶部显示提示</td><td>提示</td></tr>
</tbody></table></div><div class="note">阈值是第一版建议值,跑两周后按误报情况调整。</div></div></section>`;
  healthChips(); bindInfo(); bindLinks();
}

// ================= 今天实时(2026-10-28):今天 0 点到抓数时刻,未完整,不进任何日指标
function todayCard(scope){
  const T = D.today; if (!T || !T.old) return '';
  const o = T.old, oy = T.old_y || {}, of = T.old_y_full || {}, n = T.n601, g = T.reg, gy = T.reg_y || {};
  const fmM = x => x == null ? '—' : fm(x, 2), fiN = x => x == null ? '—' : fi(x);
  const farmTxt = (T.farm_models||[]).join('、') || '疑似刷量机型';
  const rows = [
    [`DAU${T.login_through ? `<span class="note"> 登录数据截至 ${esc(T.login_through)}</span>` : ''}`, fiN(T.dau), fiN(T.dau_y), fiN(T.dau_y_full)],
    ['充值', fmM(o.usd), fmM(oy.usd), fmM(of.usd)],
    ['付费人数 / 笔数', `${fiN(o.payers)} / ${fiN(o.orders)}`, `${fiN(oy.payers)} / ${fiN(oy.orders)}`, `${fiN(of.payers)} / ${fiN(of.orders)}`],
    g ? [`新注册<span class="note"> 其中 ${esc(farmTxt)}</span>`, `${fi(g.n)}<span class="note"> ${fi(g.farm)}</span>`, `${fiN(gy.n)}<span class="note"> ${fiN(gy.farm)}</span>`, fiN(gy.n_full)] : null,
    g ? ['新注册当天已进游戏', `${fi(g.entered)}`, '—', '—'] : null,
  ].filter(Boolean);
  const oldTbl = `<div class="tw"><table><thead><tr><th>老服</th><th>今天截至 ${esc(T.as_of.slice(11))}</th><th>昨天同一时刻(${esc(T.y_cut)})</th><th>昨天全天</th></tr></thead><tbody>${rows.map(r_ => `<tr><td class="l">${r_[0]}</td><td>${r_[1]}</td><td>${r_[2]}</td><td>${r_[3]}</td></tr>`).join('')}</tbody></table></div>`;
  const n6Txt = `<b>601</b>:充值 ${fm(n.usd,2)}(${n.orders} 笔 · ${n.payers} 人)${T.n601_reg != null ? ` · 新建角色 ${T.n601_reg} · 今天登录过 ${T.n601_login}` : ''}${(T.n601_orders||[]).length && scope === 'n601' ? `<br>今天订单:${T.n601_orders.map(x => `${x.t} ${x.id} ${esc(x.ch)} ${fm(x.usd,2)}`).join(';')}` : ''}`;
  const t6 = T.n601_tbl;
  const pay = x => x ? `${fm(x.usd,2)}<span class="note"> ${x.payers} 人 · ${x.orders} 笔</span>` : '—';
  const n6Tbl = t6 ? `<div class="tw"><table><thead><tr><th>601</th><th>今天截至 ${esc(T.as_of.slice(11))}</th><th>昨天同一时刻(${esc(T.y_cut)})</th><th>昨天全天</th></tr></thead><tbody>
    <tr><td class="l">充值<span class="note"> 已剔除测试卡、沙盒、退款;PayerMax 未核对</span></td><td>${pay(t6.pay[0])}</td><td>${pay(t6.pay[1])}</td><td>${pay(t6.pay[2])}</td></tr>
    ${t6.click ? (() => { const ck = x => x ? `${fi(x.users)} 人<span class="note"> ${x.clicks} 次 · 生成订单 ${x.order_users} 人</span>` : '—'; return `<tr><td class="l">点击付费<span class="note"> Google / Apple</span></td><td>${ck(t6.click[0])}</td><td>${ck(t6.click[1])}</td><td>${ck(t6.click[2])}</td></tr>`; })() : ''}
    <tr><td class="l">新建角色</td><td>${fiN(t6.reg[0])}</td><td>${fiN(t6.reg[1])}</td><td>${fiN(t6.reg[2])}</td></tr>
    <tr><td class="l">今天登录过<span class="note"> 角色表只留最后一次登录,没有昨天对照</span></td><td>${fiN(t6.login[0])}</td><td>—</td><td>—</td></tr>
    <tr><td class="l">做过每日任务<span class="note"> 只有日期,没有时刻</span></td><td>${fiN(t6.tasks[0])}</td><td>—</td><td>${fiN(t6.tasks[2])}</td></tr>
    </tbody></table></div>${(T.n601_orders||[]).length ? `<div class="note" style="margin-top:6px">今天订单:${T.n601_orders.map(x => `${x.t} ${x.id} ${esc(x.ch)} ${fm(x.usd,2)}`).join(';')}</div>` : ''}` : `<div class="note">${n6Txt}</div>`;
  if (scope === 'n601') return `<div class="card"><h3>601 今天(${md(T.day)})截至 ${esc(T.as_of.slice(11))}</h3><div class="sub">工作时间每 2 小时更新一次(10:10 / 12:10 / 14:10 / 16:10 / 18:10)。今天还没过完,和「昨天同一时刻」比才有意义;只在这里展示,不进下面各块(仍截至 ${md(END)})。只算内测开始后注册、不在排除名单里的角色;今天的充值还没核对到账状态</div>${n6Tbl}</div>`;
  return `<div class="card"><h3>今天(${md(T.day)})截至 ${esc(T.as_of.slice(11))}</h3><div class="sub">工作时间每 2 小时更新一次(10:10 / 12:10 / 14:10 / 16:10 / 18:10)。今天还没过完,只在这里展示,和「昨天同一时刻」比才有意义;不进图表、KPI 和告警,下面各块仍截至 ${md(END)}。登录日志是批量写入的,DAU 截至时间可能比更新时间早</div>
   ${oldTbl}<div class="note" style="font-size:13px;margin-top:6px">${n6Txt}</div></div>`;
}

// ================= 数据自洽检查(2026-10-28)
const CK_LABEL = {pass: '通过', warn: '需核对', na: '无法判断'};
function checksSummary(){
  const ck = D.checks || []; if (!ck.length) return '未运行';
  const n = st => ck.filter(x => x.status === st).length;
  return `${n('pass')} 项通过 · ${n('warn')} 项需核对 · ${n('na')} 项无法判断`;
}
function checksCard(){
  const ck = D.checks || []; if (!ck.length) return '';
  const order = {warn: 0, na: 1, pass: 2};
  const rows = [...ck].sort((a, b) => order[a.status] - order[b.status]);
  return `<div class="card" id="checks"><h3>数据自洽检查</h3><div class="sub">每次刷新自动跑,只用已抓到的数据。需核对 = 规则没通过,要人看是数据问题还是业务原因;无法判断 = 缺数据。${checksSummary()}</div>
   <div class="tw"><table><thead><tr><th>范围</th><th>检查项</th><th>规则</th><th>结果</th><th>数值</th><th>说明</th></tr></thead><tbody>
   ${rows.map(x => `<tr><td>${esc(x.group)}</td><td class="l">${esc(x.name)}</td><td class="l">${esc(x.rule)}</td><td><span class="ck ${x.status}">${CK_LABEL[x.status] || esc(x.status)}</span></td><td class="l">${esc(x.value)}</td><td class="l">${esc(x.detail || '')}</td></tr>`).join('')}</tbody></table></div></div>`;
}

// ================= 口径
function defs(){
  const fe = D.meta.fetch_errors || {}, ce = D.meta.compute_errors || {};
  $('root').innerHTML = `<section id="sec-defs">
  <div class="card"><h3>指标定义</h3><div class="sub">${esc(COMMON)}</div><div class="tw"><table><thead><tr><th>指标</th><th>定义</th><th>分子</th><th>分母</th><th>来源</th></tr></thead><tbody>
   ${Object.values(DEFS).map(d => `<tr><td>${esc(d[0])}</td><td class="l">${esc(d[1])}</td><td class="l">${esc(d[2])}</td><td class="l">${esc(d[3])}</td><td class="l">${esc(d[4])}</td></tr>`).join('')}</tbody></table></div></div>
  <div class="card"><h3>说明</h3><div class="note" style="font-size:13px;line-height:1.7">
   · 等级段:KPI、生命周期用窗口内最高主城等级;新手漏斗用注册当天最高等级。<br>
   · 平台:新用户按注册时的系统(sysType);活跃玩家按登录客户端(googleClient = Android,iosClient / apple = iOS)。<br>
   · 新手漏斗为严格嵌套,注册日取满 30 天的一段,所以比所选时间段早 30 天。<br>
   · 自动事件(进游戏自动生产士兵、主城 2 级自动成就)不计入任何主动行为。<br>
   · 「参与某玩法的人留存更高」只是相关性,不是该玩法提升了留存。<br>
   · 钻石:宠物竞猜、老虎机有返还,净消耗 = 同类型消耗 − 产出,不能用下注额当真实消耗。<br>
   · 收入为美元毛流水,不含 601 新版内测服。新注册剔除 601 内测账号(当前 ${fi(D.meta.n601_excluded)} 个)。${D.meta.farm && D.meta.farm.n ? `新注册另剔除疑似刷量注册 ${fi(D.meta.farm.n)} 个(${esc(D.meta.farm.models.join('、'))},注册当天没进游戏的)。` : ''}<br>
   · 防护:昨天 DAU 不到前 4 周同星期一半时报「DAU 单日断崖」;单一机型占当天注册 30% 以上时出「提示」;数据超过 2 天没更新时页面顶部显示「数据已过期」。<br>
   · 数据刷新:目前在可连 VPN 的电脑上运行管线;Metabase 接入后改为定时自动刷新。</div></div>
  ${checksCard()}
  <div class="card"><h3>本次运行</h3><div class="note">抓数时间 ${esc(D.meta.run_at||'')} · 数据截至 ${esc(END)} · 来源 ${esc(D.meta.source||'')}<br>抓数失败:${Object.keys(fe).length ? esc(Object.keys(fe).join('、')) : '无'} · 计算失败:${Object.keys(ce).length ? esc(Object.keys(ce).join('、')) : '无'} · 自洽检查:${checksSummary()}</div></div>
  </section>`;
}


// ================= 玩法健康矩阵
function matrixChart(id){
  const G = (D.gameplay || {})[`${w60()}|${S.plat}`]; if (!G) return;
  const rows = G.rows.filter(r => r.rate != null && r.lift != null), maxU = Math.max(...rows.map(r => r.users), 1);
  const quad = (r) => (r.rate >= G.rate_cut ? 1 : 0) + (r.lift >= G.lift_cut ? 2 : 0);
  const cols = [css('--slate'), css('--gold'), css('--violet'), css('--accent')];
  const labelPlugin = {id:'lbl', afterDatasetsDraw(ch){ const ctx = ch.ctx; ctx.save(); ctx.font = '11px ' + css('--font-ui'); ctx.fillStyle = css('--ink');
    const placed = [];
    ch.getDatasetMeta(0).data.forEach((pt, i) => { const t = rows[i].name, wd = ctx.measureText(t).width, rad = pt.options ? pt.options.radius : 6;
      const cands = [[pt.x + rad + 3, pt.y + 4], [pt.x + rad + 3, pt.y - rad - 2], [pt.x + rad + 3, pt.y + rad + 11], [pt.x - rad - 3 - wd, pt.y + 4]];
      let best = cands[0];
      for (const [x, y] of cands) { const box = [x, y - 10, x + wd, y + 2]; if (!placed.some(b => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) { best = [x, y]; break; } }
      placed.push([best[0], best[1] - 10, best[0] + wd, best[1] + 2]); ctx.fillText(t, best[0], best[1]); });
    const xs = ch.scales.x, ys = ch.scales.y; ctx.strokeStyle = css('--muted'); ctx.setLineDash([4,4]); ctx.beginPath();
    ctx.moveTo(xs.getPixelForValue(G.rate_cut), ys.top); ctx.lineTo(xs.getPixelForValue(G.rate_cut), ys.bottom);
    ctx.moveTo(xs.left, ys.getPixelForValue(G.lift_cut)); ctx.lineTo(xs.right, ys.getPixelForValue(G.lift_cut)); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = css('--muted'); ctx.textAlign = 'right';
    ctx.fillText('高参与 · 留存差大:核心玩法', xs.right - 4, ys.top + 12); ctx.textAlign = 'left';
    ctx.fillText('低参与 · 留存差大:潜在核心', xs.left + 4, ys.top + 12); ctx.textAlign = 'right';
    ctx.fillText('高参与 · 留存差小:需观察价值', xs.right - 4, ys.bottom - 6); ctx.textAlign = 'left';
    ctx.fillText('低参与 · 留存差小:需进一步判断', xs.left + 4, ys.bottom - 6); ctx.restore(); }};
  mkChart(id, {type:'bubble', data:{datasets:[{label:'玩法', data:rows.map(r => ({x:r.rate, y:r.lift, r:4 + 14 * Math.sqrt(r.users / maxU)})),
    backgroundColor:rows.map(r => cols[quad(r)] + '99'), borderColor:rows.map(r => cols[quad(r)])}]},
    plugins:[labelPlugin],
    options:{interaction:{mode:'nearest', intersect:true}, plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c) => { const r = rows[c.dataIndex]; return `${r.name}:参与 ${fi(r.users)} 人(${fp(r.rate)}),留存差 ${(r.lift*100).toFixed(1)}pp`; }}}},
      scales:{x:{title:{display:true, text:'参与率', color:css('--muted')}, ticks:{callback:(x)=>Math.round(x*100)+'%'}}, y:{title:{display:true, text:'15 天留存差(pp)', color:css('--muted')}, ticks:{callback:(x)=>(x*100).toFixed(0)}}}}});
}
function game(){
  const G = (D.gameplay || {})[`${w60()}|${S.plat}`]; if (!G) { $('root').innerHTML = '<div class="empty">没有数据</div>'; return; }
  const rw = D.gameplay.retention_windows;
  const quadName = (r) => r.rate == null || r.lift == null ? '—' : r.rate >= G.rate_cut ? (r.lift >= G.lift_cut ? '高参与 · 留存差大' : '高参与 · 留存差小') : (r.lift >= G.lift_cut ? '低参与 · 留存差大' : '低参与 · 留存差小');
  $('root').innerHTML = `<section id="sec-game">
  ${S.w > 60 ? '<div class="banner">玩法数据只抓了近 60 天,「近 90 天」在本页按 60 天计算。</div>' : ''}
  ${S.server !== 'all' ? '<div class="banner">玩法页不随服务器筛选,显示的是全部正式服。</div>' : ''}
  <div class="banner">「参与者留存更高」只是相关性:参与的人本来就更投入。不能据此判断某个玩法提升了留存;要判断因果需要做随机实验。</div>
  <div class="card"><h3>玩法健康矩阵 · 近 ${w60()} 天 · ${PL[S.plat]}</h3><div class="sub">象限分界 = 各玩法参与率、留存差的中位数(${fp(G.rate_cut)}、${(G.lift_cut*100).toFixed(1)}pp)。${noSeg()}</div><div class="chart tall"><canvas id="c-mx"></canvas></div></div>
  <div class="card"><h3>各玩法明细</h3><div class="sub">活跃 ${fi(G.active)} 人。留存差 = ${rw[0]}~${rw[1]} 参与者与未参与者在 ${rw[2]}~${rw[3]} 仍登录的比例之差,先在每个等级段内算再按人数加权。「收入覆盖」= 参与者的付费占全部付费的比例,付费者几乎什么都玩,所以不代表玩法带来收入</div>
   <div class="tw"><table><thead><tr><th>玩法</th><th>参与人数</th><th>参与率</th><th>人均参与天数</th><th>参与者 15 天留存</th><th>未参与者</th><th>留存差</th><th>收入覆盖</th><th>象限</th><th>数据来源</th></tr></thead><tbody>
   ${G.rows.slice().sort((a,b) => (b.rate||0) - (a.rate||0)).map(r => `<tr><td>${esc(r.name)}${r.complete ? '' : ' <span class="pill p-yellow">数据不全</span>'}</td><td>${fi(r.users)}</td><td>${fp(r.rate)}</td><td>${r.avg_days ?? '—'}</td><td>${fp(r.kept_part,0)}</td><td>${fp(r.kept_non,0)}</td><td>${r.lift == null ? '—' : (r.lift>0?'+':'') + (r.lift*100).toFixed(1) + 'pp'}</td><td>${fp(r.rev_cov,0)}</td><td>${quadName(r)}</td><td class="l note">${esc(r.source)}</td></tr>`).join('')}
   </tbody></table></div>
   <div class="note">自动事件不计入:进入游戏时自动产生的生产士兵、主城升 2 级自动触发的成就都不在表里。「最强王者 / 最强联盟」用的是参与奖领取记录,可能是自动发放的,参与人数可能偏高。宠物竞猜、老虎机按花钻石的记录判断参与。</div></div>
  </section>`;
  matrixChart('c-mx'); bindInfo(); bindLinks();
}

// ================= PvP
function pvpPage(){
  const P = X('pvp') || {}, k = P[`${w60()}|${S.plat}|${S.band}`] || {};
  const A = P.after_loss || {rows:[]};
  $('root').innerHTML = `<section id="sec-pvp">
  ${S.w > 60 ? '<div class="banner">PvP 数据只抓了近 60 天,「近 90 天」在本页按 60 天计算。</div>' : ''}
  <div class="kpis">
   ${kpiCard({label:`发起入侵人数 · 近 ${w60()} 天`, val:fi(k.initiators), lines:[`占活跃 ${fp(k.active ? k.initiators/k.active : null)} · 发起 ${fi(k.initiated)} 次`, '来源:CheckInvadeBattle']})}
   ${kpiCard({label:'完成入侵战斗的人数', val:fi(k.attackers), lines:[`结算 ${fi(k.attacks)} 场 · 人均 ${k.attackers ? (k.attacks/k.attackers).toFixed(1) : '—'} 场`, '来源:EndInvadeBattle']})}
   ${kpiCard({label:'入侵胜率', val:fp(k.attacks ? k.wins/k.attacks : null), lines:[`胜 ${fi(k.wins)} / ${fi(k.attacks)} 场`]})}
   ${kpiCard({label:'城被攻打的活跃玩家', val:fi(k.owners), lines:[`被攻打 ${fi(k.attacked)} 次`]})}
   ${kpiCard({label:'城被打下', val:fi(k.lost_users) + ' 人', lines:[`共 ${fi(k.lost)} 次`]})}
   ${kpiCard({label:'反抗', val:fi(k.resisters) + ' 人', lines:[`成功率 ${fp(k.resists ? k.resist_wins/k.resists : null)}`]})}
   ${kpiCard({label:'复仇', val:fi(k.revengers) + ' 人', lines:[`被打下城的人中复仇 ${fp(k.lost_users ? k.revenge_of_lost/k.lost_users : null)}`]})}
  </div>
  <div class="note">「发起」是点了入侵(含没打起来的),「完成战斗」是有结算记录的,所以前者人数更多。「城被攻打」只统计窗口内活跃的玩家;全服被打的城里约一半属于 30 天没登录的玩家。复仇表没有成败字段,所以没有复仇成功率。</div>
  <div class="grid">
   <div class="card"><h3>每日入侵</h3><div class="sub">${S.server === 'all' ? '全部正式服' : S.server + ' 服的活跃玩家'};不随平台 / 等级段变化</div><div class="chart"><canvas id="c-pvpd"></canvas></div></div>
   <div class="card"><h3>PvP 获得的资源 · 按天</h3><div class="sub">占领、抢夺、税收、反抗四种来源(两类资源合计);全部正式服,不随任何筛选变化,含非玩家 ID</div><div class="chart"><canvas id="c-loot"></canvas></div></div>
  </div>
  <div class="card"><h3>城池被攻破后的留存</h3><div class="sub">${A.window ? A.window.join(' ~ ') : ''} 的活跃日。处理组 = 当天城被打下;对照组 = 当天和前 7 天都没被打下。按等级段 × 事件前 7 天登录率(低 ≤30%、中、高 >70%)分层比较</div>
   <div class="banner">Correlation, not causation:被打的玩家本身更显眼、更活跃,分层只能扣掉一部分差异。样本 < 30 的格子不下结论。</div>
   ${afterLossTable(A.rows)}</div>
  </section>`;
  const dd = (P.daily || []).slice(-30), lab = dd.map(r => md(r[0]));   // 2026-11-05 趋势统一近 30 天
  mkChart('c-pvpd', {data:{labels:lab, datasets:[{type:'bar', label:'入侵次数', data:dd.map(r => r[2]), backgroundColor:css('--accent'), yAxisID:'y'},
    {type:'line', label:'发起人数', data:dd.map(r => r[1]), borderColor:css('--gold'), borderWidth:2, pointRadius:0, yAxisID:'y1'},
    {type:'line', label:'城被打下的活跃玩家', data:dd.map(r => r[4]), borderColor:css('--bad'), borderWidth:1.5, pointRadius:0, yAxisID:'y1'}]},
    options:{scales:{x:{}, y:{position:'left'}, y1:{position:'right', grid:{display:false}}}}});
  if (P.loot) { const cols = P.loot.columns, nm = {CollectTax:'税收', Occupy:'占领', Snatch:'抢夺', Resist:'反抗'}, pal = [css('--accent'), css('--gold'), css('--slate'), css('--violet')];
    mkChart('c-loot', {type:'bar', data:{labels:P.loot.rows.map(r => md(r[0])), datasets:cols.map((c, i) => ({label:nm[c]||c, data:P.loot.rows.map(r => r[i+1]), backgroundColor:pal[i % 4], stack:'s'}))},
      options:{scales:{x:{stacked:true}, y:{stacked:true, ticks:{callback:(x)=>Intl.NumberFormat('en',{notation:'compact'}).format(x)}}}}}); }
  bindInfo(); bindLinks();
}
function afterLossTable(rows){
  const pre = {low:'低', mid:'中', high:'高'}, by = {};
  rows.forEach(r => { by[`${r.band}|${r.pre}|${r.treat}`] = r; });
  const cell = (r, k) => !r ? '—' : r.n < 30 ? `<span class="note">n=${r.n}</span>` : fp(r[k], 0);
  let h = `<div class="tw"><table><thead><tr><th>等级段</th><th>事件前活跃</th><th>被打下 n</th><th>次日登录</th><th>后 7 天登录率</th><th>14 天内流失</th><th>对照 n</th><th>次日登录</th><th>后 7 天登录率</th><th>14 天内流失</th></tr></thead><tbody>`;
  BANDS.forEach(b => ['low','mid','high'].forEach(p => { const t = by[`${b}|${p}|true`], c = by[`${b}|${p}|false`]; if (!t && !c) return;
    h += `<tr><td>Lv${b}</td><td>${pre[p]}</td><td>${t ? fi(t.n) : 0}</td><td>${cell(t,'next1')}</td><td>${cell(t,'post7')}</td><td>${cell(t,'gone')}</td><td>${c ? fi(c.n) : 0}</td><td>${cell(c,'next1')}</td><td>${cell(c,'post7')}</td><td>${cell(c,'gone')}</td></tr>`; }));
  return h + '</tbody></table></div>';
}

// ================= 联盟
function allyPage(){
  const Al = X('alliance') || {}, k = Al[`${w60()}|${S.plat}|${S.band}`] || {}, jt = (Al.join_timing || {}), rates = jt[S.plat + '_rates'] || {};
  const rb = (Al.retention_by_band || {})[S.plat] || [];
  $('root').innerHTML = `<section id="sec-ally">
  ${S.w > 60 ? '<div class="banner">联盟事件只抓了近 60 天,「近 90 天」在本页按 60 天计算。</div>' : ''}
  <div class="kpis">
   ${kpiCard({label:`在盟率 · 近 ${w60()} 天`, val:fp(k.active ? k.in_alliance/k.active : null), lines:[`在盟 ${fi(k.in_alliance)} / 活跃 ${fi(k.active)}`]})}
   ${kpiCard({label:'新用户 3 天内入盟', val:fp(rates.d3), lines:['注册且当天进入游戏的人', '平台筛选有效']})}
   ${kpiCard({label:'新用户 7 天内入盟', val:fp(rates.d7)})}
   ${kpiCard({label:'申请入盟', val:fi(k.applied) + ' 人'})}
   ${kpiCard({label:'入盟', val:fi(k.joined) + ' 人'})}
   ${kpiCard({label:'退盟', val:fi(k.left) + ' 人'})}
   ${kpiCard({label:'新建联盟', val:fi(k.created) + ' 人'})}
  </div>
  <div class="banner">Correlation only:在联盟里的玩家本来就更投入,下面的对比都不能说明「入盟导致留存」。要判断因果,需要做「随机推荐入盟」的实验。</div>
  <div class="grid">
   <div class="card"><h3>联盟参与漏斗 · 近 ${w60()} 天</h3><div class="sub">每层只算上一层的人</div>${simpleFunnel(k.funnel || [])}</div>
   <div class="card"><h3>在盟 vs 不在盟</h3><div class="sub">近 ${w60()} 天活跃玩家</div>
    <div class="tw"><table><thead><tr><th></th><th>人数</th><th>人均活跃天数</th><th>付费率</th></tr></thead><tbody>
    <tr><td>在联盟</td><td>${fi(k.cmp?.in?.n)}</td><td>${k.cmp?.in?.days ?? '—'}</td><td>${fp(k.cmp?.in?.pay)}</td></tr>
    <tr><td>不在联盟</td><td>${fi(k.cmp?.out?.n)}</td><td>${k.cmp?.out?.days ?? '—'}</td><td>${fp(k.cmp?.out?.pay)}</td></tr></tbody></table></div>
    <h3 style="margin-top:8px">同等级段的 15 天留存</h3>
    <div class="tw"><table><thead><tr><th>等级段</th><th>在盟 n</th><th>在盟留存</th><th>不在盟 n</th><th>不在盟留存</th></tr></thead><tbody>
    ${rb.map(r => `<tr><td>Lv${r.band}</td><td>${fi(r.in_n)}</td><td>${r.in_n >= 30 ? fp(r.in_kept,0) : '<span class="note">样本不足</span>'}</td><td>${fi(r.out_n)}</td><td>${r.out_n >= 30 ? fp(r.out_kept,0) : '<span class="note">样本不足</span>'}</td></tr>`).join('')}</tbody></table></div></div>
  </div>
  <div class="grid">
   <div class="card"><h3>新用户入盟时间 vs 30 天表现</h3><div class="sub">${jt ? '' : ''}注册于 ${esc((Al.join_timing_window||[]).join(' ~ '))}、当天进入游戏的新用户;按注册后第几天首次在联盟里分组 · ${PL[S.plat]}</div>
    <div class="tw"><table><thead><tr><th>首次入盟</th><th>人数</th><th>D7</th><th>D30</th><th>30 天内活跃天数</th><th>30 天内付费率</th></tr></thead><tbody>
    ${(jt[S.plat] || []).map(r => `<tr><td>${esc(r.bucket)}</td><td>${fi(r.n)}</td><td>${r.n >= 30 ? fp(r.d7,0) : '<span class="note">n<30</span>'}</td><td>${r.n >= 30 ? fp(r.d30,0) : '<span class="note">n<30</span>'}</td><td>${r.days30 ?? '—'}</td><td>${r.n >= 30 ? fp(r.pay30,0) : '<span class="note">n<30</span>'}</td></tr>`).join('')}</tbody></table></div></div>
   <div class="card"><h3>每日联盟事件(人数)</h3><div class="sub">${S.server === 'all' ? '全部正式服' : S.server + ' 服的活跃玩家'}</div><div class="chart"><canvas id="c-ally"></canvas></div></div>
  </div></section>`;
  const dd = (Al.daily || []).slice(-30), pal = [css('--accent'), css('--good'), css('--bad'), css('--gold')];   // 近 30 天
  mkChart('c-ally', {type:'line', data:{labels:dd.map(r => md(r[0])), datasets:['申请','入盟','退盟','建盟'].map((n, i) => ({label:n, data:dd.map(r => r[i+1]), borderColor:pal[i], borderWidth:1.5, pointRadius:0}))}});
  bindInfo(); bindLinks();
}
function simpleFunnel(steps){
  if (!steps.length) return '<div class="empty">没有数据</div>';
  const top = steps[0][1] || 1;
  return '<div class="funnel">' + steps.map((x, i) => `<div class="fr"><span>${esc(x[0])}</span><div class="fb" style="width:${Math.max(0.4, x[1]/top*100)}%"></div><span class="n">${fi(x[1])} · ${fp(x[1]/top,0)}${i ? ' · 本步 ' + fp(steps[i-1][1] ? x[1]/steps[i-1][1] : null, 0) : ''}</span></div>`).join('') + '</div>';
}

// ================= 国家 / 版本
function geoPage(){
  const g = D.geo || {}, C = g[`country|${S.w}`] || [], V = g[`version|${S.w}`] || [], cov = g.coverage || {};
  $('root').innerHTML = `<section id="sec-geo">
  ${S.server !== 'all' ? '<div class="banner">国家 / 版本页不随服务器筛选,显示的是全部正式服。</div>' : ''}
  <div class="banner">国家来源:先用登录时记录的国家(getUserCountry),没有的再用各服务器玩家记录里的国家(两边都有的账号 99% 一致)。近 30 天活跃 ${fi(cov.active)} 人中 ${fi(cov.active_with_country)} 人(${fp(cov.active ? cov.active_with_country/cov.active : null, 0)})有国家,其中 ${fi(cov.from_server || 0)} 人来自服务器记录;近 30 天收入中国家「未知」的占 ${fp(cov.rev_unknown_share, 0)}。像 ar_KW 这类记录是手机的语言设置,不代表所在国家,一律算作「未知」。</div>
  <div class="card"><h3>国家 · 近 ${S.w} 天</h3><div class="sub">活跃、付费、新用户数按窗口;D1 / D7 / D30 / 30 天 LTV 用固定 cohort:近 150 天注册且已满期、有国家记录的新用户(国家只在登录时记录,这些人基本都进过游戏),所以比注册口径的留存高,只能在国家之间横向比较。全平台、全等级</div>
   <div class="tw"><table><thead><tr><th>国家</th><th>活跃</th><th>日均 DAU</th><th>新用户</th><th>D1</th><th>D7</th><th>D30</th><th>付费人数</th><th>付费率</th><th>ARPU</th><th>ARPPU</th><th>收入</th><th>新用户 30 天 LTV</th></tr></thead><tbody>
   ${C.map(r => `<tr><td>${esc(cname(r.country))}</td><td>${fi(r.active)}</td><td>${r.avg_dau ?? '—'}</td><td>${fi(r.new_users)}</td><td>${fp(r.d1,0)}</td><td>${r.n_d7 >= 30 ? fp(r.d7,0) : `<span class="note">n=${r.n_d7}</span>`}</td><td>${r.n_d30 >= 30 ? fp(r.d30,1) : `<span class="note">n=${r.n_d30}</span>`}</td><td>${fi(r.payers)}</td><td>${fp(r.pay_rate)}</td><td>${fm(r.arpu,2)}</td><td>${fm(r.arppu)}</td><td>${fm(r.revenue)}</td><td>${fm(r.ltv30,2)}</td></tr>`).join('')}
   </tbody></table></div></div>
  <div class="grid">
   <div class="card"><h3>国家质量矩阵</h3><div class="sub">横轴 = 活跃人数,纵轴 = 新用户 D7(有国家记录口径),气泡 = 收入;不含「未知」;D7 样本 < 30 的国家不画</div><div class="chart tall"><canvas id="c-cq"></canvas></div></div>
   <div class="card"><h3>版本 · 每天(近 30 天)</h3><div class="sub">每天活跃玩家用的客户端版本;没有版本发布记录,做不了发布前后对比</div>
    <div class="tw"><table><thead><tr><th>版本</th><th>活跃</th><th>占比</th><th>人均活跃天数</th><th>等级中位数</th><th>付费人数</th><th>付费率</th><th>收入</th></tr></thead><tbody>
    ${V.map(r => `<tr><td>${esc(r.version)}</td><td>${fi(r.active)}</td><td>${fp(r.share)}</td><td>${r.avg_days ?? '—'}</td><td>${r.lvl ?? '—'}</td><td>${fi(r.payers)}</td><td>${fp(r.pay_rate)}</td><td>${fm(r.revenue)}</td></tr>`).join('')}</tbody></table></div>
    <h3 style="margin-top:8px">每日活跃的版本分布</h3><div class="chart"><canvas id="c-ver"></canvas></div></div>
  </div></section>`;
  const pts = C.filter(r => r.country !== '未知' && r.n_d7 >= 30 && r.d7 != null), maxR = Math.max(...pts.map(r => r.revenue || 0), 1);
  mkChart('c-cq', {type:'bubble', data:{datasets:[{label:'国家', data:pts.map(r => ({x:r.active, y:r.d7, r:5 + 16*Math.sqrt((r.revenue||0)/maxR)})), backgroundColor:css('--accent') + '88', borderColor:css('--accent')}]},
    plugins:[{id:'cl', afterDatasetsDraw(ch){ const ctx = ch.ctx; ctx.save(); ctx.font = '11px ' + css('--font-ui'); ctx.fillStyle = css('--ink'); ch.getDatasetMeta(0).data.forEach((p, i) => ctx.fillText(cname(pts[i].country), p.x + 8, p.y - 6)); ctx.restore(); }}],
    options:{interaction:{mode:'nearest', intersect:true}, plugins:{legend:{display:false}, tooltip:{callbacks:{label:(c) => { const r = pts[c.dataIndex]; return `${cname(r.country)}:活跃 ${r.active},D7 ${fp(r.d7,0)},收入 ${fm(r.revenue)}`; }}}},
      scales:{x:{title:{display:true, text:'活跃人数', color:css('--muted')}}, y:{min:0, title:{display:true, text:'新用户 D7', color:css('--muted')}, ticks:{callback:(x)=>Math.round(x*100)+'%'}}}}});
  const vd0 = g.version_daily, vd = vd0 ? {columns:vd0.columns, rows:vd0.rows.slice(-30)} : null; /* 近 30 天 */ if (vd) { const pal = [css('--accent'), css('--gold'), css('--slate'), css('--violet'), css('--grid')];
    mkChart('c-ver', {type:'bar', data:{labels:vd.rows.map(r => md(r[0])), datasets:vd.columns.map((c, i) => ({label:c, data:vd.rows.map(r => r[i+1]), backgroundColor:pal[i % 5], stack:'s'}))}, options:{scales:{x:{stacked:true}, y:{stacked:true}}}}); }
  bindInfo(); bindLinks();
}

function draw(){
  charts.splice(0).forEach(c => c.destroy());
  segs();
  $('stamp').textContent = `数据截至 ${END}(中国时间) · 更新于 ${(D.meta.run_at||'').replace('T',' ').slice(0,16)}${S.server !== 'all' ? ' · 当前:' + S.server + ' 服' : ''}`;
  const today = new Date(); const lag = Math.floor((Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) - Date.parse(END + 'T00:00:00Z')) / 864e5);
  const stale = lag > 2 ? `<div class="banner" style="margin-top:12px">数据已过期:截至 ${END},已经 ${lag} 天没有更新。页面上的数字和告警都停在那一天,请先刷新数据再做判断。</div>` : '';
  $('f-bar').classList.toggle('hidden', !OLD.includes(S.tab));   // 筛选只用于老服各页
  $('f-bar6').classList.toggle('hidden', !N6.includes(S.tab) || S.tab === 'n6dq');   // 2026-11-05 技术与数据页不随筛选,不显示筛选条
  const W6 = D.n601 && D.n601.win ? D.n601.win[S.w6] : null;
  const SC6 = (D.n601_seg || {}).counts || {};
  $('f-w6note').textContent = W6 ? `${W6.from.slice(5)} ~ ${END.slice(5)}${S.w6 === 1 ? '(数据截至日全天)' : '(内测以来)'};时间筛选只影响关键数字卡和几张汇总表;趋势图、埋点块、标「不随时间筛选」的卡片都是全部内测期间或当前状态。平台 / 国家 / 版本一次选一项;国家按账号注册 IP 判断(挂 VPN 会判错),版本是最后一次登录的版本,不足 10 人的不单列;无法判断:平台 ${(SC6.plat||{})['未知'] ?? 0} 人、国家 ${(SC6.country||{})['未知'] ?? 0} 人、版本 ${(SC6.ver||{})['未知'] ?? 0} 人` : '';
  if (N6.includes(S.tab)) $('stamp').textContent = `601 数据截至 ${END} · 中国时间 · 更新于 ${(D.meta.run_at||'').replace('T',' ').slice(0,16)}`;
  ({home, newuser, life, game, pvp:pvpPage, ally:allyPage, money, geo:geoPage, alerts, defs,
    n601:() => n601Page('n601'), n6tech:() => n601Page('n6tech'), n6first:() => n601Page('n6first'), n6new:() => n601Page('n6new'), n6grow:() => n601Page('n6grow'), n6pay:() => n601Page('n6pay'), n6dq:() => n601Page('n6dq')})[S.tab]();
  oldExtra(S.tab);
  if (stale) $('root').insertAdjacentHTML('afterbegin', stale);
}
// 2026-11-05 老服三项(缺失清单 P1-5 / P1-7 / P2-8,用户确认上「老服」页签;只放数字,内部稿的结论不搬):
// 入侵结构 → PvP 页;金币 / 水晶账本 → 商业化页;新号按设备拆 → 新用户页。全部老服、不随筛选
function oldExtra(tab){
  const sec = $('root').querySelector('section'); if (!sec) return;
  const big = (v) => v == null ? '—' : v >= 1e12 ? (v / 1e12).toFixed(2) + ' 万亿' : v >= 1e8 ? (v / 1e8).toFixed(1) + ' 亿' : fi(v);
  const pcx = (k, n) => n ? `${fp(k / n, 0)}<span class="note"> ${fi(k)}/${fi(n)}</span>` : '—';
  const NOTE = '<span class="note" style="font-weight:400"> · 全部老服,不随筛选</span>';
  // 2026-11-05 维度趋势(用户:老服改趋势、近 30 天,图内可切国家等维度)。维度拆分是全部正式服、全平台,不随顶部筛选
  const T = D.old_trends;
  if (T) {
    const lab = T.dates.map(md), pal = [css('--accent'), css('--gold'), css('--slate'), css('--violet'), css('--good'), css('--bad'), 'rgba(120,120,140,0.55)'];
    const draw_ = (id, ser, kind) => { const ex = Chart.getChart($(id)); if (ex) ex.destroy(); const ks = Object.keys(ser);
      mkChart(id, {type:kind === 'bar' ? 'bar' : 'line', data:{labels:lab, datasets:ks.map((k, i) => ({label:k === '其他' ? '其他' : (cname(k) || k), data:ser[k], backgroundColor:pal[i % pal.length], borderColor:pal[i % pal.length], borderWidth:kind === 'bar' ? 0 : 2, pointRadius:0, borderRadius:2, stack:kind === 'bar' ? 's' : undefined}))},
        options:{scales:kind === 'bar' ? {x:{stacked:true}, y:{stacked:true, beginAtZero:true}} : {x:{}, y:{beginAtZero:true}}}}); };
    const dimCard = (id, title, sub, dims, h) => `<div class="card"><h3>${title}</h3><div class="sub">${sub} <span class="seg" id="${id}-seg">${dims.map((d, i) => `<button aria-pressed="${i === 0}" data-v="${d}">${d}</button>`).join('')}</span></div><div class="chart"${h ? ` style="height:${h}px"` : ''}><canvas id="${id}"></canvas></div></div>`;
    const bindDim = (id, src, kind) => { const segEl = $(id + '-seg'); if (!segEl) return; const first = segEl.querySelector('button').dataset.v; draw_(id, src[first], kind);
      segEl.querySelectorAll('button').forEach(b => b.onclick = () => { segEl.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw_(id, src[b.dataset.v], kind); }); };
    if (tab === 'home') { const anchor = $('c-dau') && $('c-dau').closest('.grid');
      if (anchor) { anchor.insertAdjacentHTML('afterend', `<div class="grid">${dimCard('c-ddim', '活跃 · 按维度拆分', '近 30 天每天活跃人数,全部正式服、全平台;服务器 / 国家取最多的 6 个,其余并入「其他」。', Object.keys(T.dau))}${dimCard('c-rdim', '收入 · 按维度拆分', '近 30 天每天收入(美元),不含 601。', Object.keys(T.revenue))}</div>`);
        bindDim('c-ddim', T.dau, 'line'); bindDim('c-rdim', T.revenue, 'bar'); } }
    if (tab === 'money') { sec.insertAdjacentHTML('afterbegin', `<div class="grid">${dimCard('c-mdim', '收入趋势 · 按维度', '近 30 天每天收入(美元),不含 601;下面的「收入按渠道」是这 30 天的合计。', Object.keys(T.revenue))}</div>`); bindDim('c-mdim', T.revenue, 'bar'); }
    if (tab === 'geo') { const anchor = sec.querySelector('.card'); const html = `<div class="grid">${dimCard('c-gdim', '国家趋势 · 近 30 天', '每天活跃人数 / 收入,按国家(取最多的 6 个);国家来自登录记录和服务器记录,未知的并入「其他」。', ['活跃', '收入'])}</div>`;
      if (anchor) anchor.insertAdjacentHTML('beforebegin', html); else sec.insertAdjacentHTML('beforeend', html); bindDim('c-gdim', {'活跃': T.dau['国家'], '收入': T.revenue['国家']}, 'line'); }
    if (tab === 'game' && T.gameplay) { const ks = Object.keys(T.gameplay), def = ['建筑升级', '副本 1', '入侵', '竞技场'].filter(k => ks.includes(k)), on = new Set(def);
      sec.insertAdjacentHTML('afterbegin', `<div class="card"><h3>玩法每日参与 · 近 30 天</h3><div class="sub">每天参与该玩法的人数,全部正式服、全平台。点下面的玩法名加减曲线</div><div class="chips" id="gp-chips" style="display:flex;flex-wrap:wrap;gap:4px;margin:6px 0">${ks.map(k => `<button class="pill" aria-pressed="${on.has(k)}" data-v="${esc(k)}" style="cursor:pointer;border:1px solid var(--grid)">${esc(k)}</button>`).join('')}</div><div class="chart"><canvas id="c-gpd"></canvas></div></div>`);
      const redraw = () => draw_('c-gpd', Object.fromEntries([...on].map(k => [k, T.gameplay[k]])), 'line');
      $('gp-chips').querySelectorAll('button').forEach(b => { const st = () => { b.style.background = on.has(b.dataset.v) ? 'var(--accent-soft)' : 'transparent'; }; st(); b.onclick = () => { on.has(b.dataset.v) ? on.delete(b.dataset.v) : on.add(b.dataset.v); st(); redraw(); }; }); redraw(); }
  }
  if (tab === 'pvp' && D.old_invade) { const X = D.old_invade, T = X.total;
    sec.insertAdjacentHTML('beforeend', `<h2>入侵结构 · 近 28 天${NOTE}</h2><div class="card"><h3>入侵、占领与解救 · 按天</h3><div class="sub">${md(X.from)} ~ ${md(X.to)}。打 NPC 城 = 城主号 ≥ 10 亿;打已被占的城 = 当时城的占领者不是城主(占领者为空的约 8.6% 场次含义不明,不算);解救 = invaderRelease。税收、占领、掠夺的资源见上面的「PvP 资源」</div>
     <div class="kpis">${kpiCard({label:'进攻场次', val:fi(T.battles), lines:[`攻方胜 ${fp(T.wins / T.battles, 0)}`]})}${kpiCard({label:'打 NPC 城', val:fp(T.npc / T.battles, 1), lines:[`${fi(T.npc)} 场`]})}${kpiCard({label:'打已被占的城', val:fp(T.on_occ / T.battles, 0), lines:[`${fi(T.on_occ)} 场`]})}${kpiCard({label:'解救', val:fi(T.release), lines:['次数']})}</div>
     <div class="chart"><canvas id="c-oinv"></canvas></div></div>`);
    const dl = X.daily; mkChart('c-oinv', {type:'bar', data:{labels:dl.map(r => md(r.d)), datasets:[{label:'进攻场次', data:dl.map(r => r.battles), backgroundColor:css('--accent'), borderRadius:2, yAxisID:'y'},
      {type:'line', label:'打已被占的城占比', data:dl.map(r => r.battles ? r.on_occ / r.battles : null), borderColor:css('--gold'), borderWidth:2, pointRadius:0, yAxisID:'y1'},
      {type:'line', label:'解救次数', data:dl.map(r => r.release), borderColor:css('--slate'), borderWidth:1.5, pointRadius:0, yAxisID:'y'}]},
      options:{scales:{x:{}, y:{beginAtZero:true}, y1:{beginAtZero:true, max:1, position:'right', grid:{display:false}, ticks:{callback:(v) => Math.round(v*100) + '%'}}}}}); }
  if (tab === 'money' && D.old_ledger) { const L = D.old_ledger;
    sec.insertAdjacentHTML('beforeend', `<h2>金币 / 水晶账本 · 近 28 天${NOTE}</h2><div class="sub">${md(L.from)} ~ ${md(L.to)}。应发 = 记录里的发放量;实际进账 = 真正加到玩家身上的量,两者的差按字段名推断是仓库满了溢出(待研发确认);进账含 NPC、离线产出等非玩家号。花费只统计 10 个在运营的老服</div>
     <div class="grid">${L.res.map((R, i) => `<div class="card"><h3>${esc(R.name)}</h3>
      <div class="tw"><table><tbody><tr><td class="l">应发</td><td>${big(R.issued)}</td></tr><tr><td class="l">实际进账</td><td>${big(R.actual)}<span class="note"> 占应发 ${fp(R.actual / R.issued, 0)}</span></td></tr><tr><td class="l">花费</td><td>${big(R.spent)}</td></tr><tr><td class="l">进账 − 花费</td><td>${big(R.actual - R.spent)}</td></tr></tbody></table></div>
      <div class="chart"><canvas id="c-oled${i}"></canvas></div>
      <details><summary class="link">进账来源(应发最多的 8 个)</summary><div class="tw"><table><thead><tr><th>来源</th><th>应发</th><th>实际进账</th><th>进账率</th></tr></thead><tbody>${R.sources.map(x => `<tr><td class="l">${esc(x.src)}</td><td>${big(x.issued)}</td><td>${big(x.actual)}</td><td>${fp(x.issued ? x.actual / x.issued : null, 0)}</td></tr>`).join('')}</tbody></table></div></details>
      <details><summary class="link">花费去向(最多的 8 个)</summary><div class="tw"><table><thead><tr><th>去向</th><th>花费</th></tr></thead><tbody>${R.spend_top.map(x => `<tr><td class="l">${esc(x.src)}</td><td>${big(x.spent)}</td></tr>`).join('')}</tbody></table></div></details></div>`).join('')}</div>`);
    L.res.forEach((R, i) => mkChart('c-oled' + i, {type:'bar', data:{labels:R.daily.map(r => md(r.d)), datasets:[{label:'实际进账', data:R.daily.map(r => r.actual), backgroundColor:css('--accent'), borderRadius:2}, {label:'花费', data:R.daily.map(r => r.spent), backgroundColor:css('--gold'), borderRadius:2}]},
      options:{scales:{x:{}, y:{beginAtZero:true, ticks:{callback:(v) => big(v)}}}}})); }
  if (tab === 'newuser' && D.old_newdev) { const ND = D.old_newdev;
    sec.insertAdjacentHTML('beforeend', `<h2>新号按设备拆:全新设备 vs 老玩家小号${NOTE}</h2><div class="card"><h3>近 150 天注册、注册后 7 天内在老服登录过的新号(${fi(ND.n)} 个,已去掉 601 账号和疑似刷量号)</h3><div class="sub">同一个广告 ID 下有更早建的号 = 老玩家小号;有广告 ID 但设备上没有更早的号 = 全新设备;没取到广告 ID = 无法判断。广告 ID 2025-09-18 起才记录,更早的老号多数没有,所以小号比例是下限;iOS 绝大多数不给广告 ID,基本拆不开。D1 / D7 = 注册后第 N 天在老服登录;30 天付费只算满 30 天的号</div>
     <div class="tw"><table><thead><tr><th>分组</th><th>平台</th><th>人数</th><th>D1</th><th>D7</th><th>30 天内付费</th></tr></thead><tbody>${ND.rows.map(x => `<tr><td class="l">${esc(x.name)}</td><td>${esc(x.plat)}</td><td>${fi(x.n)}</td><td>${pcx(x.d1.n, x.d1.base)}</td><td>${pcx(x.d7.n, x.d7.base)}</td><td>${pcx(x.pay30.n, x.pay30.base)}</td></tr>`).join('')}</tbody></table></div></div>`); }
}
draw(); window.scrollTo(0, 0);
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
new MutationObserver(draw).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
})();
</script>
"""


def write_internal_md(A, run_at):
    """内部参考:三张清单、当日指导卡、六个病。只写本地,不发布。"""
    d = HERE / 'internal'; d.mkdir(exist_ok=True)
    L = [f"# Invader 内部清单 · 数据截至 {A['date']}", '', f"生成时间 {run_at}。规则自动生成,未经人工审核,只供内部参考;对外沟通前先核对。", '',
         '## 当日指导卡', '', '**最大的 3 个问题**', '']
    for i, x in enumerate(A['top'], 1):
        L += [f"{i}. **{x['title']}**{'(新)' if x.get('new') else ''}:{x.get('evidence') or x.get('impact')}。建议:{x['action']}(负责人:{x['owner']})"]
    L += ['', '**最大的 3 个机会**', '']
    for i, x in enumerate(A['opps'], 1):
        L += [f"{i}. **{x['title']}**:{x['evidence']}。建议:{x['action']}(负责人:{x['owner']})"]
    L += ['', '## 六个病 · 近 4 周 vs 前 4 周', '', '| 病 | 状态 | 依据 | 护栏 |', '|---|---|---|---|']
    L += [f"| {x['name']} | {x['status']} | {x['basis']} | {x['guard']} |" for x in A['diseases']]
    for t in ('错误', '断层', '缺失'):
        rows = A['lists'].get(t, [])
        L += ['', f'## {t}({len(rows)})', '', '| 编号 | 严重度 | 问题 | 证据 / 影响 | 负责人 | 建议 | 标注 |', '|---|---|---|---|---|---|---|']
        for x in rows:
            ev = (x.get('evidence') or x.get('impact') or '').replace('|', '/')
            lab = x['label'] + (f"({x['label_note']})" if x.get('label_note') else '')
            L += [f"| {x['key']} | {x['sev']} | {x['title']}{'(新)' if x.get('new') else ''}{'(登记)' if x['source'] == '登记' else ''} | {ev} | {x['owner']} | {x['action']} | {lab} |"]
    if A.get('closed'):
        L += ['', '## 比上一次少了(已关闭)', ''] + [f"- {x['title']}" for x in A['closed']]
    (d / f"ai_lists_{A['date']}.md").write_text('\n'.join(L) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', default=str(HERE / 'raw_metrics.json'))
    ap.add_argument('--out', default=str(HERE / 'site' / 'index.html'))
    ap.add_argument('--artifact', default=str(HERE / 'preview_artifact.html'))
    a = ap.parse_args()
    raw = json.loads(Path(a.raw).read_text())
    D = compute.build(raw)
    # 2026-10-29 用户决定:三张清单 / 当日指导卡 / 六个病只做内部参考,不上公开看板(含建议和负责人,未经人工审核)。
    # 每天写成本地 md,页面数据里删掉,连网页源码里也看不到
    ai = D.pop('ai', None)
    if ai:
        try:
            write_internal_md(ai, raw.get('today_at') or raw.get('run_at'))
        except Exception as e:
            print(f'内部清单写出失败(不影响看板):{e}')
    chartjs = (HERE / 'lib' / 'chart.umd.min.js').read_text()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(page(D, chartjs, True))
    Path(a.artifact).write_text(page(D, chartjs, False))
    errs = D['meta']['compute_errors']
    print(f'写出 {a.out} 和 {a.artifact};计算失败 {len(errs)} 项 {list(errs) if errs else ""}')


if __name__ == '__main__':
    main()
