-- db: log
-- 卡片:玩家 × 天 × 玩法 的次数(有 dateCN 索引的表)。近 60 天。玩法健康矩阵 / 联盟页 / PvP 页用。
-- 自动事件不进来:不用 productionSoldier(进游戏自动 1 条)、finishAchievement(主城 2 级自动 1 条)。
-- 宠物竞猜、老虎机用钻石消耗表判断参与(下注表 PetQuizBet 60 天约 1,100 万行,太重)。
-- 2026-10-21 初版。
SELECT 'building' AS feature, monetId, dateCN, COUNT(*) AS n FROM UpgradeBuildingLevel WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'soldier_up', monetId, dateCN, COUNT(*) FROM upgradeSoldierLevel WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'hero_up', monetId, dateCN, COUNT(*) FROM UpgradeHeroLevel WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'soul_fuse', monetId, dateCN, COUNT(*) FROM WarriorSoulFuse WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'dungeon2', monetId, dateCN, COUNT(*) FROM EndDungeon2 WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'world_boss', monetId, dateCN, COUNT(*) FROM AttackWorldMonster WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_skill', monetId, dateCN, COUNT(*) FROM activatedAllianceSkill WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_dungeon', monetId, dateCN, COUNT(*) FROM EndAllianceDungeons WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_apply', monetId, dateCN, COUNT(*) FROM applyAlliance WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_join', monetId, dateCN, COUNT(*) FROM acceptAlliance WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_leave', monetId, dateCN, COUNT(*) FROM leaveAlliance WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_create', monetId, dateCN, COUNT(*) FROM createAlliance WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'king_event', monetId, dateCN, COUNT(*) FROM StrongestKingActivity_getParticipationReward WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'alliance_event', monetId, dateCN, COUNT(*) FROM StrongestAllianceActivity_getParticipationReward WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'shop', monetId, dateCN, COUNT(*) FROM buyItemFromShop WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() GROUP BY monetId, dateCN
UNION ALL SELECT 'pet_quiz', monetId, dateCN, COUNT(*) FROM ConsumeDiamond WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() AND typeEnum = 'PetQuiz' GROUP BY monetId, dateCN
UNION ALL SELECT 'slot', monetId, dateCN, COUNT(*) FROM ConsumeDiamond WHERE dateCN >= CURDATE() - INTERVAL 60 DAY AND dateCN < CURDATE() AND typeEnum = 'SlotSpin' GROUP BY monetId, dateCN
