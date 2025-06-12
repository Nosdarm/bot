import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call

from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.ai.rules_schema import CoreGameRulesConfig, ExperienceRules, LootRules # Added for testing

class TestCombatManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock()
        self.mock_settings = {}
        self.mock_rule_engine = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_inventory_manager = AsyncMock() # Added for loot
        self.mock_location_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_relationship_manager = AsyncMock() # For consequences
        self.mock_quest_manager = AsyncMock() # For consequences


        self.combat_manager = CombatManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
            party_manager=self.mock_party_manager,
            status_manager=self.mock_status_manager,
            item_manager=self.mock_item_manager,
            location_manager=self.mock_location_manager
            # game_log_manager is passed via kwargs in methods usually
        )

        self.rules_config = CoreGameRulesConfig(
             base_stats={}, equipment_slots={}, checks={}, damage_types={},
             item_definitions={}, status_effects={},
             experience_rules=ExperienceRules(base_xp_per_kill=50, xp_distribution_rule="even_split"), # Added
             loot_rules=LootRules(default_drop_chance=0.5, placeholder_loot_item_id="potion_health", distribution_method="random_assignment_to_winner"), # Added
             action_conflicts=[], location_interactions={}
        )

        self.actor_player = Character(id="player_actor_id", name="ActorPlayer", guild_id="guild1", hp=100, max_health=100, stats={"dexterity": 15})
        self.player_winner1 = Character(id="player_winner1_id", name="Winner1", guild_id="guild1", hp=50, max_health=100)

        self.target_npc = NpcModel(id="npc_target_id", name_i18n={"en":"TargetNPC"}, guild_id="guild1", health=0, max_health=80, stats={"dexterity": 10}, template_id="goblin_defeated") # Defeated
        self.target_npc_alive = NpcModel(id="npc_target_alive_id", name_i18n={"en":"TargetNPCAlive"}, guild_id="guild1", health=80, max_health=80, stats={"dexterity": 10})

        self.combat_participant_actor = CombatParticipant(entity_id="player_actor_id", entity_type="Character", hp=100, max_hp=100, initiative=15)
        self.combat_participant_winner1 = CombatParticipant(entity_id="player_winner1_id", entity_type="Character", hp=50, max_hp=100, initiative=12)
        self.combat_participant_target_defeated = CombatParticipant(entity_id="npc_target_id", entity_type="NPC", hp=0, max_hp=80, initiative=10) # Defeated
        self.combat_participant_target_alive = CombatParticipant(entity_id="npc_target_alive_id", entity_type="NPC", hp=80, max_hp=80, initiative=5)


        self.active_combat = Combat(
            id="combat1", guild_id="guild1", location_id="loc1", is_active=True,
            participants=[self.combat_participant_actor, self.combat_participant_target_defeated], # actor and one defeated npc
            turn_order=["player_actor_id", "npc_target_id"], current_turn_index=0,
            combat_log=["Combat started."]
        )
        self.combat_manager._active_combats["guild1"] = {"combat1": self.active_combat}


    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_complete_success(self, mock_calculate_stats):
        # Setup target_npc to be alive for this test, then it gets damaged
        self.active_combat.participants = [self.combat_participant_actor, self.combat_participant_target_alive]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat # Re-assign

        mock_calculate_stats.side_effect = [
            {"strength": 15, "dexterity": 15, "attack_bonus": 5, "max_hp":100, "hp":100},
            {"strength": 10, "dexterity": 10, "armor_class": 12, "max_hp":80, "hp":80}
        ]
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(return_value={
            "log_messages": ["PlayerActor attacks TargetNPCAlive for 10 damage."],
            "hp_changes": [{"participant_id": "npc_target_alive_id", "new_hp": 70}],
        })
        self.mock_character_manager.get_character = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc = AsyncMock(return_value=self.target_npc_alive)

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context = {
            "guild_id": "guild1", "rules_config": self.rules_config, "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine
        }

        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )

        self.mock_db_service.begin_transaction.assert_called_once()
        self.assertEqual(mock_calculate_stats.call_count, 2)
        self.mock_rule_engine.apply_combat_action_effects.assert_called_once()
        target_participant = self.active_combat.get_participant_data("npc_target_alive_id")
        self.assertEqual(target_participant.hp, 70)
        self.mock_npc_manager.mark_npc_dirty.assert_called_with("guild1", "npc_target_alive_id")
        self.assertEqual(self.target_npc_alive.health, 70)
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive for 10 damage.", guild_id="guild1", combat_id="combat1"
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)

    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_complete_rule_engine_exception(self, mock_calculate_stats):
        # ... (setup as before) ...
        mock_calculate_stats.side_effect = [ {"s":1}, {"s":1}] # simplified
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(side_effect=Exception("RuleEngine Boom!"))
        action_data = {"type": "ATTACK", "target_ids": ["npc_target_id"]} # Use the defeated NPC for simplicity if no HP change
        kwargs_context = {
            "guild_id": "guild1", "rules_config": self.rules_config, "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine
        }
        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )
        self.mock_db_service.rollback_transaction.assert_called_once()
        self.mock_game_log_manager.log_error.assert_any_call(unittest.mock.ANY, guild_id="guild1", combat_id="combat1", actor_id="player_actor_id")
        self.assertEqual(self.active_combat.current_turn_index, 1) # Turn still advances


    async def test_end_combat_and_process_consequences(self):
        self.active_combat.participants = [self.combat_participant_winner1, self.combat_participant_target_defeated]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat

        winning_entity_ids = ["player_winner1_id"]

        # Mock get_npc for XP calculation
        self.mock_npc_manager.get_npc = AsyncMock(return_value=self.target_npc) # target_npc is already defeated (hp=0)

        # Mock add_experience
        self.mock_character_manager.add_experience = AsyncMock()

        # Mock InventoryManager for loot (not directly used by CM, but good for context)
        # RuleEngine might call it or return item data for CM to process via InventoryManager
        # For this test, assume RuleEngine returns item_ids and CM calls inventory_manager
        self.mock_rule_engine.resolve_loot_drop = AsyncMock(return_value=["potion_health"]) # Mock loot drop
        self.mock_inventory_manager.add_item_to_character = AsyncMock(return_value={"success": True})


        context_for_end = {
            "guild_id": "guild1", "rules_config": self.rules_config,
            "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
            "inventory_manager": self.mock_inventory_manager, # Added for loot
            "relationship_manager": self.mock_relationship_manager,
            "quest_manager": self.mock_quest_manager
        }

        await self.combat_manager.end_combat("guild1", "combat1", winning_entity_ids, context_for_end)

        self.assertFalse(self.active_combat.is_active)
        self.mock_game_log_manager.log_info.assert_any_call(
            f"Combat combat1 ended. Winners: {winning_entity_ids}.", guild_id="guild1", combat_id="combat1"
        )

        # XP Assertions
        self.mock_character_manager.add_experience.assert_called_once_with("guild1", "player_winner1_id", 50) # 50 base_xp_per_kill
        self.mock_game_log_manager.log_info.assert_any_call(
            "Character player_winner1_id awarded 50 XP.", guild_id="guild1", combat_id="combat1", character_id="player_winner1_id"
        )

        # Loot Assertions (simplified: assume RuleEngine returns item_ids and CM distributes)
        # This part depends heavily on how loot distribution is implemented in process_combat_consequences
        # The current placeholder logic in CM uses random.choice and calls inv_manager.
        # We'll check if inv_manager was called if loot was dropped.
        # Since loot drop itself is random in the placeholder, we can't guarantee a call unless we control random.
        # For now, let's assume the default_drop_chance (0.5) means it's likely called.
        # A more robust test would mock random.random() or RuleEngine.resolve_loot_drop more directly if CM uses it.
        # The current `process_combat_consequences` directly uses random.random()

        # To make it deterministic for test:
        with patch('random.random', MagicMock(return_value=0.4)): # Ensure drop_chance is met (0.4 < 0.5)
             # Re-run the part that does loot if it wasn't part of the initial call, or re-run end_combat
             # For simplicity, we'll assume the initial call to end_combat was sufficient.
             # If `process_combat_consequences` was already called, this patch won't affect it.
             # This highlights a limitation of patching random for a method already called.
             # A better way would be to mock the method that *uses* random if it's complex,
             # or ensure the test setup makes the outcome deterministic.

             # Let's re-call process_combat_consequences directly for deterministic loot test.
             # Reset mocks that would be called again
             self.mock_game_log_manager.reset_mock()
             self.mock_inventory_manager.reset_mock()

             await self.combat_manager.process_combat_consequences(self.active_combat, winning_entity_ids, context_for_end)

             self.mock_inventory_manager.add_item_to_character.assert_called_once_with(
                 "guild1", "player_winner1_id", "potion_health", 1
             )
             self.mock_game_log_manager.log_info.assert_any_call(
                 "Item potion_health awarded to character player_winner1_id.",
                 guild_id="guild1", combat_id="combat1", character_id="player_winner1_id"
             )


        # Test cleanup
        self.assertNotIn("combat1", self.combat_manager._active_combats.get("guild1", {}))
        self.assertIn("combat1", self.combat_manager._deleted_combats_ids.get("guild1", set()))


if __name__ == '__main__':
    unittest.main()
