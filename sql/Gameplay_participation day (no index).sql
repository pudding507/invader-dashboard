-- db: log
-- 卡片:玩家 × 天 × 玩法 的次数(没有 dateCN 索引的表)。近 60 天。
-- 这些表只有主键 tid,直接按日期筛会全表扫描。做法:只看最后 K 行(主键范围,走索引),再按日期筛。
-- K 取近 60 天写入量的 2~3 倍(2026-10-21 用主键二分测得:CheckIn 3.6 万、GetDailyTaskReward 42 万、
-- HeroArena 7.3 万、HeroGlory 9.7 万、Moba 0.24 万、PetFeed 2.9 万、LuckyDrawNew 4.8 万)。
-- 🛑 写入量涨到 K 覆盖不了 60 天时,较早的日子会缺数据;计算层会检查每个玩法最早的日期,不够 60 天就在页面上标「数据不全」。
-- 竞技场表只有 dateAR 索引,按 dateAR 筛。
-- 2026-10-21 初版。
SELECT 'checkin' AS feature, monetId, dateCN, COUNT(*) AS n FROM CheckIn
  WHERE tid > (SELECT MAX(tid) - 120000 FROM CheckIn) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'daily_task', monetId, dateCN, COUNT(*) FROM GetDailyTaskReward
  WHERE tid > (SELECT MAX(tid) - 1300000 FROM GetDailyTaskReward) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'arena', monetId, dateAR, COUNT(*) FROM HeroArenaService_endBattle
  WHERE dateAR >= CURDATE() - INTERVAL 60 DAY AND dateAR < CURDATE() GROUP BY monetId, dateAR
UNION ALL SELECT 'hero_glory', monetId, dateCN, COUNT(*) FROM HeroGlory_EndBattle
  WHERE tid > (SELECT MAX(tid) - 300000 FROM HeroGlory_EndBattle) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'moba', monetId, dateCN, COUNT(*) FROM MobaBattleFinished
  WHERE tid > (SELECT MAX(tid) - 10000 FROM MobaBattleFinished) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'pet', monetId, dateCN, COUNT(*) FROM PetFeed
  WHERE tid > (SELECT MAX(tid) - 90000 FROM PetFeed) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'lucky_draw', monetId, dateCN, COUNT(*) FROM LuckyDrawNew
  WHERE tid > (SELECT MAX(tid) - 150000 FROM LuckyDrawNew) AND dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
