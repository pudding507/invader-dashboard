-- db: prod  (SQL Server invade_user_n601)
-- 卡片:601 战斗逐场(UnityBattleObservationV1,11-04 建表):每场一行。modeId 见 compute N6_MODE(2 侵略、5 反抗、7 剧本、11 新手 NPC、13 英雄竞技场、16 副本 2…);
--       targetType = stage(关卡)/ player / player_occupied(已被占的玩家城)/ npc;endedAtMs 为空 = 没有结束记录(中途退出或还没回报)。
--       attackerWon / occupied 只在有结束记录时有值。时间是 UTC 毫秒。
-- 2026-11-06 初版(用户确认:601 新表接看板)。只读,全表几十到两千行,几秒。
SELECT attackerId AS monetId, actualDefenderId AS defender_id, modeId AS mode_id, targetType AS target_type,
       startedAtMs AS started_ms, endedAtMs AS ended_ms, CAST(attackerWon AS int) AS won, CAST(occupied AS int) AS occupied
FROM invade_user_n601.dbo.UnityBattleObservationV1 WHERE serverId = 601
