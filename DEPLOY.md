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

## 运行环境

| 项目 | 最低版本 | 这台机器在用 | 说明 |
|---|---|---|---|
| Python | 3.9 | 3.9.6(macOS 自带) | 建议 3.9–3.12;3.13 以上要把 numpy 换成 2.1 以上 |
| Node | 16.17 | 20.18 | 只用来跑上传工具 wrangler 3.80.0 |

Python 库(setup.sh 按下面的版本装):

| 库 | 版本 | 用途 |
|---|---|---|
| pandas | 2.3.3 | 计算 |
| numpy | 2.0.2 | 计算 |
| PyMySQL | 1.2.0 | 连 Log 库(MySQL 5.6) |
| pymssql | 2.4.5 | 连生产库(SQL Server 2005,必须 `tds_version='7.0'`) |
| psycopg2-binary | 2.9.12 | 连 Redshift |

其余都是 Python 标准库。**不用浏览器、不用无头浏览器**:页面是 Python 拼出来的 HTML 文件,图表在看的人的浏览器里画。

和 Mac 绑定的只有三处,换 Windows / Linux 时要改:定时任务(launchd → 任务计划程序 / cron)、刷新脚本里检查端口的 `nc -z -G`(Linux 上写法不同)、Tunnelblick(Mac 专用;其他系统用 OpenVPN,同一份配置文件)。

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
