Invader 数据看板的管线代码(抓数 → 计算 → 渲染 → 发布 Cloudflare Pages)。
完整项目约定在文档目录 `../invader/CLAUDE.md`(这台机器上有就以它为准);别的机器上没有文档目录时,按下面的要点做。

@../invader/CLAUDE.md

## 要点(2026-11-11 起放在仓库里,部署到别的机器也能看到)

- **公司核心盈利项目,要非常谨慎。**老 App(1.12.x)跑在老服;New Era(2.4.x)目前只有 601 一个服。
- **只读**:数据库账号 reader,永不写库;查询卡住不要 kill,查 PROCESSLIST 后交给人。Log 库(MySQL 5.6)走 dateCN 索引或主键范围、串行;生产库是 SQL Server 2005,pymssql 必须 `tds_version='7.0'`。
- **网络**:Invader 老库(192.168.50.14,Log 库 39995 + 生产库 39998)走 Tunnelblick VPN;埋点数仓 Redshift 走公司 VPN。两个都连着才能完整刷新。
- **凭据只在 `~/.invader_env`**(chmod 600),不写进代码、文档和仓库。
- **601 测试号只认 `config/exclusions.json`**;不凭「点击不付费」猜测试号。
- **公开看板只放数据**:建议、负责人、诊断结论写 `internal/`(不进仓库)。告警要克制。
- 改 SQL、计算口径、页面前先说改法,等确认;改完写进 README 的改动记录。
- 目录、刷新流程、部署见 `README.md` 和 `DEPLOY.md`。
