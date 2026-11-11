# 在新机器上部署 Invader 看板

## 这是什么

几个 Python 脚本加一个 macOS 定时任务:每天从 Invader 的 Log 库、生产库和埋点 Redshift 只读抓数 → 算指标 → 生成一个网页 → 上传到 Cloudflare Pages(https://invader-dashboard.pages.dev/)。每天 10:10 完整刷新,之后每 2 小时只刷新「今天实时」的几张小卡。

## 机器要求

- macOS,常开、不休眠(系统设置 → 电池 / 节能:接电源时不自动睡眠)。
- 能同时连两个 VPN,断了能自动重连:
  - **Tunnelblick**:连 Invader 老数据库(Log 库、生产库);
  - **公司 VPN**:连埋点数仓 Redshift。
- 能访问外网(GitHub、Cloudflare、pypi、npm)。
- 硬盘留 1 GB 以上(缓存和数据约 400 MB)。

## 部署步骤

1. 取代码:`git clone <仓库地址> ~/DataGripProjects/invader-dashboard`(仓库迁到公司 GitHub 后用新地址)。
2. 装 Node(nodejs.org 的 LTS 版)。Python 用系统自带的 python3 即可(没有就 `xcode-select --install`)。
3. 进目录运行 `bash setup.sh`。它会:
   - 装 Python 库(装到当前用户)和上传工具 wrangler;
   - 没有 `~/.invader_env` 时逐项问凭据并写入(权限 600)。**凭据找看板负责人私下要,不要发在群里**;
   - 下载 IP 分配表到 `data/rir/`;
   - 生成并安装定时任务;
   - 检查两个 VPN 是否连得上。
4. 连好两个 VPN,手动跑一次:`bash scheduled_refresh.sh`,看 `logs/refresh.log` 最后一行是不是「完成(full)」。第一次是完整抓取,要 20–30 分钟(之后有缓存,10 分钟以内)。

## 日常

- **日志**:`logs/refresh.log`。「VPN 未连上数据库,跳过」= Tunnelblick 断了;「有卡失败,不发布」= 有查询失败,线上保留上一版,下一个时间点自动重试。
- **手动补一次**:`bash scheduled_refresh.sh`。
- **停掉定时任务**:`launchctl unload ~/Library/LaunchAgents/com.invader.dashboard.daily.plist`。
- **只在一台机器上改代码**。其他机器只拉代码、不改代码。

## 不在仓库里的东西(每台机器各自有)

| 东西 | 位置 | 怎么来 |
|---|---|---|
| 凭据 | `~/.invader_env` | setup.sh 时输入 |
| 抓下来的数据、缓存、快照 | `raw_metrics.json`、`data/` | 刷新时自动生成 |
| IP 分配表 | `data/rir/` | setup.sh 下载 |
| 生成的网页 | `site/` | 刷新时自动生成 |
| 日志、内部分析稿、备份 | `logs/`、`internal/`、`_backup/` | — |

需要进仓库的配置放在 `config/`:`exclusions.json`(601 测试号排除名单)、`issues.json`(问题清单里人工登记的部分)。

## 还没做(等仓库迁到公司 GitHub、主机落实后)

- **主机 / 备机分工**:备机比主机晚 30–60 分钟跑,先看线上今天更新了没有,更新了就跳过。
- **自动拉代码**:每次刷新前从 GitHub 拉「主机已跑通」的那一版;只有主机推送,备机只读。
- 现在的刷新脚本退出时会自动提交并推送代码改动;部署到别的机器前要关掉这一步。
