-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 竞技场玩家(去掉机器人)。
-- 2026-10-21 初版(用户批准执行)。601 不写老版 Log 库(10-20 实测 33 张表均为 0),玩法只能从 601 自己的库取。
SELECT monetId, score, lv AS arena_level, active, todayPlayTimes AS today_play_times, lastTime AS last_at FROM invade_user_n601.dbo.HeroArenaInfo WHERE isRobot = 0
