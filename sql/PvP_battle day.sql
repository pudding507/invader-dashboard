-- db: log
-- 卡片:玩家 × 天 的入侵结算(进攻方)、城被攻打(城主)、反抗、复仇。近 60 天。
-- role = attack:monetId 是进攻方,wins = 进攻方胜场;role = owner:monetId 是城主(ownerId),wins = 城被打下的次数;
-- role = resist:反抗占领,wins = 反抗成功(winnerId = 自己);role = revenge:复仇次数(表里没有成败字段)。
-- 被打的城主很多是 30 天没登录的城,页面只统计活跃玩家时由渲染层与登录表关联。
-- 2026-10-21 初版。
SELECT 'attack' AS role, monetId, dateCN, COUNT(*) AS n, SUM(win) AS wins FROM EndInvadeBattle
  WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'owner', ownerId, dateCN, COUNT(*), SUM(win) FROM EndInvadeBattle
  WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() AND ownerId > 0 GROUP BY ownerId, dateCN
UNION ALL SELECT 'resist', monetId, dateCN, COUNT(*), SUM(winnerId = monetId) FROM invaderResist
  WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'revenge', monetId, dateCN, COUNT(*), 0 FROM Revenge
  WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
