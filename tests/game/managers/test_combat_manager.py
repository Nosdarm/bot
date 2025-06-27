import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call, ANY
from typing import Dict, List, Any as TypingAny, Optional, cast

from bot.ai import rules_schema # Keep for ActionConflictDefinition etc. if used later
from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.ai.rules_schema import CoreGameRulesConfig, XPRule, LootTableEntry, LootTableDefinition
from bot.services.db_service import DBService
from bot.game.managers.rule_engine import RuleEngine
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.managers.inventory_manager import InventoryManager
from bot.game.managers.relationship_manager import RelationshipManager
from bot.game.managers.quest_manager import QuestManager


class TestCombatManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock(spec=DBService)
        self.mock_settings: Dict[str, TypingAny] = {}
        self.mock_rule_engine = AsyncMock(spec=RuleEngine)
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_npc_manager = AsyncMock(spec=NpcManager)
        self.mock_party_manager = AsyncMock(spec=PartyManager)
        self.mock_status_manager = AsyncMock(spec=StatusManager)
        self.mock_item_manager = AsyncMock(spec=ItemManager)
        self.mock_inventory_manager = AsyncMock(spec=InventoryManager)
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_game_log_manager = AsyncMock(spec=GameLogManager)
        self.mock_relationship_manager = AsyncMock(spec=RelationshipManager)
        self.mock_quest_manager = AsyncMock(spec=QuestManager)

        self.combat_manager = CombatManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            party_manager=self.mock_party_manager,
            status_manager=self.mock_status_manager,
            item_manager=self.mock_item_manager,
            location_manager=self.mock_location_manager,
            game_log_manager=self.mock_game_log_manager, # Added game_log_manager
            inventory_manager=self.mock_inventory_manager, # Added inventory_manager
            relationship_manager=self.mock_relationship_manager, # Added relationship_manager
            quest_manager=self.mock_quest_manager # Added quest_manager
        )

        # Corrected XPRule initialization
        xp_rules_mock = XPRule(
            level_difference_modifier={"0": 1.0}, # Example data
            base_xp_per_challenge={"medium": 100}  # Example data
        )

        self.rules_config = CoreGameRulesConfig(
             base_stats={}, equipment_slots={}, checks={}, damage_types={},
             status_effects={},
             xp_rules=xp_rules_mock,
             loot_tables={},
             action_conflicts=[], location_interactions={},
             item_effects={}, relation_rules=[], relationship_influence_rules=[]
        )

        self.actor_player = Character(id="player_actor_id", discord_user_id="123", name_i18n={"en": "ActorPlayer"}, guild_id="guild1", stats_json=json.dumps({"dexterity": 15, "hp":100, "max_health":100}), selected_language="en")
        self.player_winner1 = Character(id="player_winner1_id", discord_user_id="456", name_i18n={"en": "Winner1"}, guild_id="guild1", stats_json=json.dumps({"hp":50, "max_health":100}), selected_language="en")

        self.target_npc = NpcModel(id="npc_target_id", template_id="goblin_defeated", name_i18n={"en":"TargetNPC"}, guild_id="guild1", stats_json=json.dumps({"dexterity": 10, "health":0, "max_health":80}))
        self.target_npc_alive = NpcModel(id="npc_target_alive_id", template_id="goblin_standard", name_i18n={"en":"TargetNPCAlive"}, guild_id="guild1", stats_json=json.dumps({"dexterity": 10, "health":80, "max_health":80}))

        self.combat_participant_actor = CombatParticipant(entity_id="player_actor_id", entity_type="Character", hp=100, max_hp=100, initiative=15)
        self.combat_participant_winner1 = CombatParticipant(entity_id="player_winner1_id", entity_type="Character", hp=50, max_hp=100, initiative=12)
        self.combat_participant_target_defeated = CombatParticipant(entity_id="npc_target_id", entity_type="NPC", hp=0, max_hp=80, initiative=10)
        self.combat_participant_target_alive = CombatParticipant(entity_id="npc_target_alive_id", entity_type="NPC", hp=80, max_hp=80, initiative=5)

        self.active_combat = Combat(
            id="combat1", guild_id="guild1", location_id="loc1", is_active=True,
            participants=[self.combat_participant_actor, self.combat_participant_target_defeated],
            turn_order=["player_actor_id", "npc_target_id"], current_turn_index=0,
            combat_log_json='["Combat started."]'
        )
        self.combat_manager._active_combats["guild1"] = {"combat1": self.active_combat}

    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_complete_success(self, mock_calculate_stats: AsyncMock):
        self.active_combat.participants = [self.combat_participant_actor, self.combat_participant_target_alive]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat

        mock_calculate_stats.side_effect = [
            {"strength": 15, "dexterity": 15, "attack_bonus": 5, "max_hp":100, "hp":100},
            {"strength": 10, "dexterity": 10, "armor_class": 12, "max_hp":80, "hp":80}
        ]
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(return_value={
            "log_messages": ["PlayerActor attacks TargetNPCAlive for 10 damage."],
            "hp_changes": [{"participant_id": "npc_target_alive_id", "new_hp": 70}],
        })
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc_alive)

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context: Dict[str, TypingAny] = {
            "guild_id": "guild1", "rules_config": self.rules_config, "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
             "inventory_manager": self.mock_inventory_manager, "location_manager": self.mock_location_manager,
             "relationship_manager": self.mock_relationship_manager, "quest_manager": self.mock_quest_manager
        }

        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )

        self.mock_db_service.begin_transaction.assert_called_once()
        self.assertEqual(mock_calculate_stats.call_count, 2)
        self.mock_rule_engine.apply_combat_action_effects.assert_called_once()
        target_participant = self.active_combat.get_participant_data("npc_target_alive_id")
        assert target_participant is not None
        self.assertEqual(target_participant.hp, 70)
        self.mock_npc_manager.mark_npc_dirty.assert_called_with("guild1", "npc_target_alive_id")
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive for 10 damage.", guild_id="guild1", combat_id="combat1", actor_id="player_actor_id", target_ids=["npc_target_alive_id"]
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)

    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_attack_misses(self, mock_calculate_stats: AsyncMock):
        self.active_combat.participants = [self.combat_participant_actor, self.combat_participant_target_alive]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat

        mock_calculate_stats.side_effect = [
            {"strength": 15, "dexterity": 15, "attack_bonus": 5, "max_hp":100, "hp":100},
            {"strength": 10, "dexterity": 10, "armor_class": 12, "max_hp":80, "hp":80}
        ]
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(return_value={
            "log_messages": ["PlayerActor attacks TargetNPCAlive but misses!"],
            "hp_changes": [],
        })
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc_alive)

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context: Dict[str, TypingAny] = {
            "guild_id": "guild1", "rules_config": self.rules_config,
            "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
            "inventory_manager": self.mock_inventory_manager, "location_manager": self.mock_location_manager,
            "relationship_manager": self.mock_relationship_manager, "quest_manager": self.mock_quest_manager
        }

        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )

        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_rule_engine.apply_combat_action_effects.assert_called_once()
        target_participant = self.active_combat.get_participant_data("npc_target_alive_id")
        assert target_participant is not None
        self.assertEqual(target_participant.hp, 80)
        self.mock_npc_manager.mark_npc_dirty.assert_not_called()
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive but misses!", guild_id="guild1", combat_id="combat1", actor_id="player_actor_id", target_ids=["npc_target_alive_id"]
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)

    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_complete_rule_engine_exception(self, mock_calculate_stats: AsyncMock):
        mock_calculate_stats.side_effect = [ {"s":1}, {"s":1}]
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(side_effect=Exception("RuleEngine Boom!"))
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=self.actor_player) # Ensure managers return mocks
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc)

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_id"]}
        kwargs_context: Dict[str, TypingAny] = {
            "guild_id": "guild1", "rules_config": self.rules_config, "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
            "inventory_manager": self.mock_inventory_manager, "location_manager": self.mock_location_manager,
            "relationship_manager": self.mock_relationship_manager, "quest_manager": self.mock_quest_manager
        }
        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )
        self.mock_db_service.rollback_transaction.assert_called_once()
        self.mock_game_log_manager.log_error.assert_any_call(
            ANY,
            guild_id="guild1", combat_id="combat1", actor_id="player_actor_id", exception_info=True
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)

    @patch('random.randint')
    async def test_start_combat_success(self, mock_randint: MagicMock):
        guild_id = "guild_start_combat"; location_id = "loc_for_combat"
        char1_id, char1_dex = "char1_sc", 14; npc1_id, npc1_dex = "npc1_sc", 12
        mock_char1 = Character(id=char1_id, guild_id=guild_id, name_i18n={"en":"Char1"}, stats_json=json.dumps({"dexterity": char1_dex, "hp":50, "max_health":50}), selected_language="en", discord_user_id="user1")
        mock_npc1 = NpcModel(id=npc1_id, template_id="goblin", name_i18n={"en":"NPC1"}, guild_id=guild_id, stats_json=json.dumps({"dexterity": npc1_dex, "health":30, "max_health":30}))
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=mock_char1)
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=mock_npc1)
        mock_randint.side_effect = [2, 6] # npc_roll = 12+1d20 (12+2=14), char_roll = 14+1d20 (14+6=20) -> char wins initiative

        participants_data = [(char1_id, "Character"), (npc1_id, "NPC")]
        mock_send_cb = AsyncMock()
        mock_send_callback_factory = MagicMock(return_value=mock_send_cb)

        combat = await self.combat_manager.start_combat(guild_id, location_id, participants_data,
                                                        channel_id="combat_channel_1",
                                                        game_log_manager=self.mock_game_log_manager,
                                                        send_callback_factory=mock_send_callback_factory)
        assert combat is not None
        self.assertTrue(combat.is_active); self.assertEqual(combat.guild_id, guild_id)
        self.assertEqual(combat.location_id, location_id); self.assertEqual(len(combat.participants), 2)
        self.assertEqual(combat.current_round, 1); self.assertEqual(combat.current_turn_index, 0)
        self.assertEqual(combat.turn_order, [char1_id, npc1_id]) # Char1 should win with dex 14 + roll 6 = 20 vs NPC dex 12 + roll 2 = 14

        npc_participant = combat.get_participant_data(npc1_id)
        char_participant = combat.get_participant_data(char1_id)
        assert npc_participant is not None and char_participant is not None
        self.assertEqual(char_participant.initiative, 20) # 14 + 6
        self.assertEqual(npc_participant.initiative, 14) # 12 + 2
        self.assertIn(combat.id, self.combat_manager._active_combats[guild_id])
        self.assertIn(combat.id, self.combat_manager._dirty_combats[guild_id])
        mock_send_cb.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(ANY, guild_id=guild_id, location_id=location_id, combat_id=combat.id)


    async def test_start_combat_no_valid_participants(self):
        guild_id = "guild_no_parts_sc"
        self.mock_character_manager.get_character_by_id.return_value = None
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=None)
        combat = await self.combat_manager.start_combat(guild_id, "loc_no_parts", [("c1","Character"), ("n1","NPC")])
        self.assertIsNone(combat)
        self.mock_game_log_manager.log_warning.assert_any_call(
            f"CombatManager: No valid participants for combat in guild {guild_id}. Aborting start_combat.",
            guild_id=guild_id
        )

    @patch('bot.game.managers.combat_manager.NpcCombatAI')
    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_process_tick_npc_acts_and_ends_combat(self, mock_calculate_stats: AsyncMock, MockNpcCombatAI: MagicMock):
        guild_id = "guild_tick_npc_end"; combat_id = "combat_tick_end1"; npc_id_acting = "npc_tick_actor_end"
        mock_npc_actor_obj = NpcModel(id=npc_id_acting, template_id="strong_npc", name_i18n={"en":"Acting NPCEnd"}, guild_id=guild_id, stats_json=json.dumps({"dexterity":18, "health":50, "max_health":50}))
        npc_participant = CombatParticipant(entity_id=npc_id_acting, entity_type="NPC", hp=50, max_hp=50, initiative=20, acted_this_round=False)
        player_participant_defeated = CombatParticipant(entity_id="player_tick_target_end", entity_type="Character", hp=0, max_hp=60, initiative=10)
        test_combat = Combat(id=combat_id, guild_id=guild_id, location_id="loc_tick_end", is_active=True, participants=[npc_participant, player_participant_defeated], turn_order=[npc_id_acting, "player_tick_target_end"], current_turn_index=0, current_round=1, combat_log_json='[]')
        self.combat_manager._active_combats[guild_id] = {combat_id: test_combat}
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=mock_npc_actor_obj)
        mock_ai_instance = MockNpcCombatAI.return_value
        npc_chosen_action = {"type": "ATTACK", "target_ids": ["player_tick_target_end"], "action_name":"Finishing Blow"}
        mock_ai_instance.get_npc_combat_action = AsyncMock(return_value=npc_chosen_action)

        # Mock handle_participant_action_complete to simulate the action leading to combat end
        async def mock_handle_action_side_effect(*args, **kwargs):
            # Simulate HP change if needed for check_combat_end_conditions
            player_participant_defeated.hp = 0 # Ensure target is defeated
            return {"success": True, "log_messages": ["NPC attacks!"]}
        self.combat_manager.handle_participant_action_complete = AsyncMock(side_effect=mock_handle_action_side_effect)

        self.mock_rule_engine.check_combat_end_conditions = AsyncMock(return_value={"ended": True, "winners": [npc_id_acting]})
        self.combat_manager.end_combat = AsyncMock() # This will be called internally

        kwargs_for_tick: Dict[str, TypingAny] = { "guild_id": guild_id, "rules_config": self.rules_config, **self.combat_manager._get_manager_kwargs()}


        combat_should_be_removed = await self.combat_manager.process_tick(combat_id, game_time_delta=1.0, **kwargs_for_tick)
        self.assertTrue(combat_should_be_removed)
        MockNpcCombatAI.assert_called_once_with(mock_npc_actor_obj, test_combat, kwargs_for_tick)
        mock_ai_instance.get_npc_combat_action.assert_awaited_once()
        self.combat_manager.handle_participant_action_complete.assert_awaited_once_with(combat_instance_id=combat_id, actor_id=npc_id_acting, actor_type="NPC", action_data=npc_chosen_action, **kwargs_for_tick)
        self.mock_rule_engine.check_combat_end_conditions.assert_awaited_once_with(combat=test_combat, context=kwargs_for_tick)
        self.combat_manager.end_combat.assert_awaited_once_with(guild_id, combat_id, [npc_id_acting], context=kwargs_for_tick)

    async def test_end_combat_and_process_consequences(self):
        self.active_combat.participants = [self.combat_participant_winner1, self.combat_participant_target_defeated]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat
        winning_entity_ids = ["player_winner1_id"]
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc)
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=self.player_winner1) # Ensure winner can be fetched
        self.mock_character_manager.add_experience = AsyncMock()
        self.mock_rule_engine.resolve_loot_drop = AsyncMock(return_value=[{"item_template_id": "potion_health", "quantity": 1}]) # Return list of dicts
        self.mock_inventory_manager.add_item_to_character = AsyncMock(return_value={"success": True, "item_id": "new_potion_id"})

        context_for_end: Dict[str, TypingAny] = { "guild_id": "guild1", "rules_config": self.rules_config, **self.combat_manager._get_manager_kwargs()}


        await self.combat_manager.end_combat("guild1", "combat1", winning_entity_ids, context_for_end)
        self.assertFalse(self.active_combat.is_active)
        self.mock_game_log_manager.log_info.assert_any_call(f"Combat combat1 ended. Winners: {winning_entity_ids}.", guild_id="guild1", combat_id="combat1")

        # XP calculation depends on XPRule logic which is simplified here.
        # Assuming base_xp_per_challenge is used if target_npc.template_id matches a key.
        # For this test, let's assume a default XP from rules_config.xp_rules.base_xp_per_challenge if not specific.
        # If target_npc.template_id = "goblin_defeated", and rules_config.xp_rules.base_xp_per_challenge = {"goblin_defeated": 50}
        # then expected_xp = 50. For simplicity, let's assume 50.
        expected_xp = self.rules_config.xp_rules.base_xp_per_challenge.get(self.target_npc.template_id or "default", 50) if self.rules_config.xp_rules else 50

        self.mock_character_manager.add_experience.assert_called_once_with("guild1", "player_winner1_id", expected_xp)
        self.mock_game_log_manager.log_info.assert_any_call(f"Character player_winner1_id awarded {expected_xp} XP.", guild_id="guild1", combat_id="combat1", character_id="player_winner1_id")

        self.mock_inventory_manager.add_item_to_character.assert_called_with("guild1", "player_winner1_id", "potion_health", 1)
        self.mock_game_log_manager.log_info.assert_any_call(
            f"Item potion_health (x1) awarded to character player_winner1_id in guild guild1 from combat combat1.",
            guild_id="guild1", combat_id="combat1", character_id="player_winner1_id"
        )
        self.assertNotIn("combat1", self.combat_manager._active_combats.get("guild1", {}))
        self.assertIn("combat1", self.combat_manager._deleted_combats_ids.get("guild1", set()))

if __name__ == '__main__':
    unittest.main()
