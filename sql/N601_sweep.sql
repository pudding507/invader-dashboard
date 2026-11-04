-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 扫荡记录(每个 攻方 × 城主 一行,sweepTimes = 累计次数,updateTime = 最近一次)。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT attackerId AS attacker_id, cityOwnerId AS city_owner_id, won, sweepTimes AS sweep_times, updateTime AS updated_at FROM invade_user_n601.dbo.invaderSweepRecord
