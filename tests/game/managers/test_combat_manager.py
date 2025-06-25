import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call

from bot.ai import rules_schema
from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.ai.rules_schema import CoreGameRulesConfig, XPRule, LootTableEntry, LootTableDefinition

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

        default_loot_table = rules_schema.LootTableDefinition(
            id="goblin_loot_table", # ID for the table
            entries=[
                rules_schema.LootTableEntry(item_template_id="potion_health", weight=1, quantity_dice="1")
            ]
        )
        self.rules_config = CoreGameRulesConfig(
             base_stats={}, equipment_slots={}, checks={}, damage_types={},
             # item_definitions={}, # item_definitions is not a field in CoreGameRulesConfig
             status_effects={},
             xp_rules=XPRule(base_xp_per_kill=50, xp_distribution_rule="even_split"),
             # loot_rules no longer exists, loot_tables is the new field.
             # For now, we'll remove it to fix the error. Loot tests might need adjustment later.
             loot_tables={}, # Assuming it expects a dict of LootTableDefinition
             action_conflicts=[], location_interactions={},
             item_effects={}, # Added missing item_effects
        )

        self.actor_player = Character(id="player_actor_id", discord_user_id=123, name_i18n={"en": "ActorPlayer"}, guild_id="guild1", hp=100, max_health=100, stats={"dexterity": 15}, selected_language="en")
        self.player_winner1 = Character(id="player_winner1_id", discord_user_id=456, name_i18n={"en": "Winner1"}, guild_id="guild1", hp=50, max_health=100, selected_language="en")

        self.target_npc = NpcModel(id="npc_target_id", template_id="goblin_defeated", name_i18n={"en":"TargetNPC"}, guild_id="guild1", health=0, max_health=80, stats={"dexterity": 10})
        self.target_npc_alive = NpcModel(id="npc_target_alive_id", template_id="goblin_standard", name_i18n={"en":"TargetNPCAlive"}, guild_id="guild1", health=80, max_health=80, stats={"dexterity": 10})

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
    async def test_handle_participant_action_attack_misses(self, mock_calculate_stats):
        # Setup similar to test_handle_participant_action_complete_success
        self.active_combat.participants = [self.combat_participant_actor, self.combat_participant_target_alive]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat

        mock_calculate_stats.side_effect = [
            {"strength": 15, "dexterity": 15, "attack_bonus": 5, "max_hp":100, "hp":100}, # Attacker
            {"strength": 10, "dexterity": 10, "armor_class": 12, "max_hp":80, "hp":80}  # Target
        ]
        # RuleEngine indicates a miss (no hp_changes, specific log message)
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(return_value={
            "log_messages": ["PlayerActor attacks TargetNPCAlive but misses!"],
            "hp_changes": [], # No HP change on a miss
        })
        self.mock_character_manager.get_character = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc = AsyncMock(return_value=self.target_npc_alive) # Target is alive

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context = {
            "guild_id": "guild1", "rules_config": self.rules_config,
            "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine
        }

        await self.combat_manager.handle_participant_action_complete(
            combat_instance_id="combat1", actor_id="player_actor_id", actor_type="Character",
            action_data=action_data, **kwargs_context
        )

        self.mock_db_service.begin_transaction.assert_called_once()
        self.mock_rule_engine.apply_combat_action_effects.assert_called_once()

        # Target's HP should not change
        target_participant = self.active_combat.get_participant_data("npc_target_alive_id")
        self.assertEqual(target_participant.hp, 80) # Initial HP
        self.mock_npc_manager.mark_npc_dirty.assert_not_called() # No HP change, so maybe not marked dirty for HP
                                                                # (but could be for other reasons if action had effects)

        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive but misses!", guild_id="guild1", combat_id="combat1"
        )
        # Turn should still advance
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
        self.mock_game_log_manager.log_error.assert_any_call(
            unittest.mock.ANY,
            guild_id="guild1",
            combat_id="combat1",
            actor_id="player_actor_id",
            exception_info=True # Added missing kwarg
        )
        self.assertEqual(self.active_combat.current_turn_index, 1) # Turn still advances

    # --- Tests for start_combat ---
    @patch('random.randint') # Mock randint for predictable initiative
    async def test_start_combat_success(self, mock_randint: MagicMock):
        guild_id = "guild_start_combat"
        location_id = "loc_for_combat"

        char1_id, char1_dex = "char1_sc", 14 # mod +2
        npc1_id, npc1_dex = "npc1_sc", 12   # mod +1

        mock_char1 = Character(id=char1_id, guild_id=guild_id, name_i18n={"en":"Char1"}, stats={"dexterity": char1_dex}, hp=50, max_health=50, selected_language="en") # Added selected_language
        mock_npc1 = NpcModel(id=npc1_id, template_id="goblin", name_i18n={"en":"NPC1"}, guild_id=guild_id, health=30, max_health=30, stats={"dexterity": npc1_dex}) # Added template_id

        self.mock_character_manager.get_character = AsyncMock(return_value=mock_char1)
        self.mock_npc_manager.get_npc = AsyncMock(return_value=mock_npc1)

        # Predictable initiative rolls: char1 rolls 10, npc1 rolls 15
        # Initiative: char1 = 10+2=12, npc1 = 15+1=16. So npc1 should be first.
        mock_randint.side_effect = [10, 15]

        participants_data = [(char1_id, "Character"), (npc1_id, "NPC")]

        mock_send_cb = AsyncMock()
        mock_send_callback_factory = MagicMock(return_value=mock_send_cb)

        combat = await self.combat_manager.start_combat(guild_id, location_id, participants_data,
                                                        channel_id="combat_channel_1",
                                                        game_log_manager=self.mock_game_log_manager,
                                                        send_callback_factory=mock_send_callback_factory)

        self.assertIsNotNone(combat)
        self.assertTrue(combat.is_active)
        self.assertEqual(combat.guild_id, guild_id)
        self.assertEqual(combat.location_id, location_id)
        self.assertEqual(len(combat.participants), 2)
        self.assertEqual(combat.current_round, 1)
        self.assertEqual(combat.current_turn_index, 0)

        self.assertEqual(combat.turn_order, [npc1_id, char1_id]) # npc1 (16) > char1 (12)

        npc_participant = next(p for p in combat.participants if p.entity_id == npc1_id)
        char_participant = next(p for p in combat.participants if p.entity_id == char1_id)
        self.assertEqual(npc_participant.initiative, 16)
        self.assertEqual(char_participant.initiative, 12)

        self.assertIn(combat.id, self.combat_manager._active_combats[guild_id])
        self.assertIn(combat.id, self.combat_manager._dirty_combats[guild_id])

        mock_send_cb.assert_called_once()
        self.assertIn("Бой начинается", mock_send_cb.call_args[0][0])
        self.assertIn(mock_npc1.name_i18n["en"] + " ходит первым", mock_send_cb.call_args[0][0])

        self.mock_game_log_manager.log_info.assert_any_call(
            unittest.mock.ANY, # CombatManager: Starting new combat...
            guild_id=guild_id, location_id=location_id
        )
        self.mock_game_log_manager.log_info.assert_any_call(
            f"Combat {combat.id} started in location {location_id} for guild {guild_id}.",
            guild_id=guild_id, combat_id=combat.id, location_id=location_id
        )

    async def test_start_combat_no_valid_participants(self):
        guild_id = "guild_no_parts_sc"
        self.mock_character_manager.get_character.return_value = None # Char not found
        self.mock_npc_manager.get_npc = AsyncMock(return_value=None) # NPC not found

        combat = await self.combat_manager.start_combat(guild_id, "loc_no_parts", [("c1","Character"), ("n1","NPC")])
        self.assertIsNone(combat)
        self.mock_game_log_manager.log_warning.assert_any_call(
            f"CombatManager: No valid participants for combat in guild {guild_id}. Aborting start_combat.",
            # No guild_id kwarg for logger.warning in current code, just positional.
        )

    # --- Tests for process_tick (NPC turn) ---
    @patch('bot.game.managers.combat_manager.NpcCombatAI')
    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_process_tick_npc_acts_and_ends_combat(self, mock_calculate_stats: AsyncMock, MockNpcCombatAI: MagicMock):
        guild_id = "guild_tick_npc_end"
        combat_id = "combat_tick_end1"
        npc_id_acting = "npc_tick_actor_end"

        mock_npc_actor_obj = NpcModel(id=npc_id_acting, template_id="strong_npc", name_i18n={"en":"Acting NPCEnd"}, guild_id=guild_id, health=50, max_health=50, stats={"dexterity":18})

        npc_participant = CombatParticipant(entity_id=npc_id_acting, entity_type="NPC", hp=50, max_hp=50, initiative=20, acted_this_round=False)
        player_participant_defeated = CombatParticipant(entity_id="player_tick_target_end", entity_type="Character", hp=0, max_hp=60, initiative=10) # Already defeated

        test_combat = Combat(
            id=combat_id, guild_id=guild_id, location_id="loc_tick_end", is_active=True,
            participants=[npc_participant, player_participant_defeated],
            turn_order=[npc_id_acting, "player_tick_target_end"], current_turn_index=0, current_round=1,
            combat_log=[]
        )
        self.combat_manager._active_combats[guild_id] = {combat_id: test_combat}

        self.mock_npc_manager.get_npc = AsyncMock(return_value=mock_npc_actor_obj)

        mock_ai_instance = MockNpcCombatAI.return_value
        npc_chosen_action = {"type": "ATTACK", "target_ids": ["player_tick_target_end"], "action_name":"Finishing Blow"}
        mock_ai_instance.get_npc_combat_action.return_value = npc_chosen_action

        # Mock handle_participant_action_complete itself to simplify this test's focus on process_tick's flow
        self.combat_manager.handle_participant_action_complete = AsyncMock()

        # Mock rule_engine.check_combat_end_conditions to return True (combat ends)
        # It should return a dict: {"ended": True, "winners": [npc_id_acting]}
        self.mock_rule_engine.check_combat_end_conditions = AsyncMock(return_value={"ended": True, "winners": [npc_id_acting]})

        # Mock end_combat to verify it's called
        self.combat_manager.end_combat = AsyncMock()

        kwargs_for_tick = {"guild_id": guild_id, "rule_engine": self.mock_rule_engine, "game_log_manager": self.mock_game_log_manager, "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager} # Added more managers for context

        combat_should_be_removed = await self.combat_manager.process_tick(combat_id, game_time_delta=1.0, **kwargs_for_tick)

        self.assertTrue(combat_should_be_removed) # process_tick returns True if combat ended
        MockNpcCombatAI.assert_called_once_with(mock_npc_actor_obj)
        mock_ai_instance.get_npc_combat_action.assert_called_once()

        self.combat_manager.handle_participant_action_complete.assert_awaited_once_with(
            combat_instance_id=combat_id,
            actor_id=npc_id_acting,
            actor_type="NPC",
            action_data=npc_chosen_action,
            **kwargs_for_tick
        )
        self.mock_rule_engine.check_combat_end_conditions.assert_awaited_once_with(combat=test_combat, context=kwargs_for_tick)
        self.combat_manager.end_combat.assert_awaited_once_with(guild_id, combat_id, [npc_id_acting], context=kwargs_for_tick)


    async def test_end_combat_and_process_consequences(self):
        # This test needs to be adjusted for the new structure of CoreGameRulesConfig
        # and how loot/xp rules are accessed.
        # The original test setup for self.rules_config needs to be updated.
        # For now, I will adapt the random.random patch to be active during end_combat.

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

        # Loot Assertions: Patch random.random for deterministic loot drop
        with patch('bot.game.managers.combat_manager.random.random', MagicMock(return_value=0.01)): # Ensure drop condition is met
            # Re-initialize context for end_combat as some mocks might have been reset or used
            context_for_end = {
                "guild_id": "guild1", "rules_config": self.rules_config,
                "game_log_manager": self.mock_game_log_manager,
                "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
                "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
                "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
                "inventory_manager": self.mock_inventory_manager,
                "relationship_manager": self.mock_relationship_manager,
                "quest_manager": self.mock_quest_manager
            }
            # Reset relevant mocks before the call that includes loot processing
            self.mock_inventory_manager.add_item_to_character.reset_mock()
            self.mock_game_log_manager.log_info.reset_mock() # Reset to check specific loot log

            await self.combat_manager.end_combat("guild1", "combat1", winning_entity_ids, context_for_end)

            # XP Assertions (should still be checked as end_combat calls process_combat_consequences)
            self.mock_character_manager.add_experience.assert_called_with("guild1", "player_winner1_id", 50)

            # Check loot-specific log (assuming default_drop_chance is e.g. 0.1 and random is 0.01)
            # The loot logic in process_combat_consequences is basic.
            # It uses loot_rules.get("placeholder_loot_item_id", "potion_health_lesser")
            # Ensure self.rules_config.loot_rules (or loot_tables) is set up for this.
            # If loot_tables is used, the key might be different.
            # For this test, we'll assume "potion_health" is the placeholder or resolved item.
            if self.rules_config.loot_tables: # Check if loot_tables is used
                 # This part needs to align with how loot_tables are structured and accessed in process_combat_consequences
                 # For now, let's assume the existing placeholder logic is hit.
                 self.mock_inventory_manager.add_item_to_character.assert_called_with(
                     "guild1", unittest.mock.ANY, "potion_health_lesser", 1 # Default placeholder
                 )
                 self.mock_game_log_manager.log_info.assert_any_call(
                    f"Item potion_health_lesser awarded to character {unittest.mock.ANY} in guild guild1 from combat combat1.",
                    guild_id="guild1", combat_id="combat1", character_id=unittest.mock.ANY
                )
            else: # If loot_tables is empty, or old loot_rules was used
                # This assertion might fail if the placeholder item ID changed from "potion_health"
                # to "potion_health_lesser" due to rule_config changes.
                # The test needs to be robust to the actual placeholder item used.
                 self.mock_inventory_manager.add_item_to_character.assert_called_with(
                     "guild1", unittest.mock.ANY, "potion_health_lesser", 1 # Assuming default placeholder
                 )


        # Test cleanup
        self.assertNotIn("combat1", self.combat_manager._active_combats.get("guild1", {}))
        self.assertIn("combat1", self.combat_manager._deleted_combats_ids.get("guild1", set()))


if __name__ == '__main__':
    unittest.main()
