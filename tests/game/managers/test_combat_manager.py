import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call, ANY # Added ANY
from typing import Dict, List, Any as TypingAny, Optional # Added TypingAny, Optional

from bot.ai import rules_schema
from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat, CombatParticipant
from bot.game.models.character import Character
from bot.game.models.npc import NPC as NpcModel
from bot.ai.rules_schema import CoreGameRulesConfig, XPRule, LootTableEntry, LootTableDefinition
from bot.services.db_service import DBService # For spec
from bot.game.managers.rule_engine import RuleEngine # For spec
from bot.game.managers.character_manager import CharacterManager # For spec
from bot.game.managers.npc_manager import NpcManager # For spec
from bot.game.managers.party_manager import PartyManager # For spec
from bot.game.managers.status_manager import StatusManager # For spec
from bot.game.managers.item_manager import ItemManager # For spec
from bot.game.managers.location_manager import LocationManager # For spec
from bot.game.managers.game_log_manager import GameLogManager # For spec
from bot.game.managers.inventory_manager import InventoryManager # For spec
from bot.game.managers.relationship_manager import RelationshipManager # For spec
from bot.game.managers.quest_manager import QuestManager # For spec


class TestCombatManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self): # Changed to asyncSetUp
        self.mock_db_service = AsyncMock(spec=DBService)
        self.mock_settings: Dict[str, TypingAny] = {} # Added type hint
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
            location_manager=self.mock_location_manager
        )

        # default_loot_table = rules_schema.LootTableDefinition( # Unused
        #     id="goblin_loot_table",
        #     entries=[
        #         rules_schema.LootTableEntry(item_template_id="potion_health", weight=1, quantity_dice="1")
        #     ]
        # )
        # Ensure XPRule is correctly initialized if it's a Pydantic model
        xp_rules_mock = XPRule(base_xp_per_kill=50, xp_distribution_rule="even_split") # Removed level_difference_modifier and party_size_modifier as they are not in XPRule

        self.rules_config = CoreGameRulesConfig(
             base_stats={}, equipment_slots={}, checks={}, damage_types={},
             status_effects={},
             xp_rules=xp_rules_mock, # Use the initialized XPRule model
             loot_tables={},
             action_conflicts=[], location_interactions={},
             item_effects={}, relation_rules=[], relationship_influence_rules=[] # Added relation_rules and relationship_influence_rules
        )

        self.actor_player = Character(id="player_actor_id", discord_user_id="123", name_i18n={"en": "ActorPlayer"}, guild_id="guild1", stats_json='{"dexterity": 15, "hp":100, "max_health":100}', selected_language="en") # discord_user_id to str, stats to json
        self.player_winner1 = Character(id="player_winner1_id", discord_user_id="456", name_i18n={"en": "Winner1"}, guild_id="guild1", stats_json='{"hp":50, "max_health":100}', selected_language="en")

        self.target_npc = NpcModel(id="npc_target_id", template_id="goblin_defeated", name_i18n={"en":"TargetNPC"}, guild_id="guild1", stats_json='{"dexterity": 10, "health":0, "max_health":80}') # stats to json
        self.target_npc_alive = NpcModel(id="npc_target_alive_id", template_id="goblin_standard", name_i18n={"en":"TargetNPCAlive"}, guild_id="guild1", stats_json='{"dexterity": 10, "health":80, "max_health":80}')

        self.combat_participant_actor = CombatParticipant(entity_id="player_actor_id", entity_type="Character", hp=100, max_hp=100, initiative=15)
        self.combat_participant_winner1 = CombatParticipant(entity_id="player_winner1_id", entity_type="Character", hp=50, max_hp=100, initiative=12)
        self.combat_participant_target_defeated = CombatParticipant(entity_id="npc_target_id", entity_type="NPC", hp=0, max_hp=80, initiative=10)
        self.combat_participant_target_alive = CombatParticipant(entity_id="npc_target_alive_id", entity_type="NPC", hp=80, max_hp=80, initiative=5)


        self.active_combat = Combat(
            id="combat1", guild_id="guild1", location_id="loc1", is_active=True,
            participants=[self.combat_participant_actor, self.combat_participant_target_defeated],
            turn_order=["player_actor_id", "npc_target_id"], current_turn_index=0,
            combat_log_json='["Combat started."]' # combat_log to combat_log_json
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
        self.mock_character_manager.get_character = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc_alive) # Changed to get_npc_by_id

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context: Dict[str, TypingAny] = { # Added type hint
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
        assert target_participant is not None # For type safety
        self.assertEqual(target_participant.hp, 70)
        self.mock_npc_manager.mark_npc_dirty.assert_called_with("guild1", "npc_target_alive_id")
        # self.assertEqual(self.target_npc_alive.health, 70) # target_npc_alive is a model, not updated directly by CM
        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive for 10 damage.", guild_id="guild1", combat_id="combat1"
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
        self.mock_character_manager.get_character = AsyncMock(return_value=self.actor_player)
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc_alive) # Changed to get_npc_by_id

        action_data = {"type": "ATTACK", "target_ids": ["npc_target_alive_id"]}
        kwargs_context: Dict[str, TypingAny] = { # Added type hint
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

        target_participant = self.active_combat.get_participant_data("npc_target_alive_id")
        assert target_participant is not None # For type safety
        self.assertEqual(target_participant.hp, 80)
        self.mock_npc_manager.mark_npc_dirty.assert_not_called()

        self.mock_db_service.commit_transaction.assert_called_once()
        self.mock_game_log_manager.log_info.assert_any_call(
            "PlayerActor attacks TargetNPCAlive but misses!", guild_id="guild1", combat_id="combat1"
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)


    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_handle_participant_action_complete_rule_engine_exception(self, mock_calculate_stats: AsyncMock):
        mock_calculate_stats.side_effect = [ {"s":1}, {"s":1}]
        self.mock_rule_engine.apply_combat_action_effects = AsyncMock(side_effect=Exception("RuleEngine Boom!"))
        action_data = {"type": "ATTACK", "target_ids": ["npc_target_id"]}
        kwargs_context: Dict[str, TypingAny] = { # Added type hint
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
            ANY, # Changed from unittest.mock.ANY
            guild_id="guild1",
            combat_id="combat1",
            actor_id="player_actor_id",
            exception_info=True
        )
        self.assertEqual(self.active_combat.current_turn_index, 1)

    @patch('random.randint')
    async def test_start_combat_success(self, mock_randint: MagicMock):
        guild_id = "guild_start_combat"
        location_id = "loc_for_combat"

        char1_id, char1_dex = "char1_sc", 14
        npc1_id, npc1_dex = "npc1_sc", 12

        mock_char1 = Character(id=char1_id, guild_id=guild_id, name_i18n={"en":"Char1"}, stats_json=json.dumps({"dexterity": char1_dex, "hp":50, "max_health":50}), selected_language="en")
        mock_npc1 = NpcModel(id=npc1_id, template_id="goblin", name_i18n={"en":"NPC1"}, guild_id=guild_id, stats_json=json.dumps({"dexterity": npc1_dex, "health":30, "max_health":30}))

        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=mock_char1) # Changed to get_character_by_id
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=mock_npc1) # Changed to get_npc_by_id

        mock_randint.side_effect = [10, 15]
        participants_data = [(char1_id, "Character"), (npc1_id, "NPC")]
        mock_send_cb = AsyncMock()
        mock_send_callback_factory = MagicMock(return_value=mock_send_cb)

        combat = await self.combat_manager.start_combat(guild_id, location_id, participants_data,
                                                        channel_id="combat_channel_1",
                                                        game_log_manager=self.mock_game_log_manager,
                                                        send_callback_factory=mock_send_callback_factory)

        self.assertIsNotNone(combat)
        assert combat is not None # For type safety
        self.assertTrue(combat.is_active)
        self.assertEqual(combat.guild_id, guild_id)
        self.assertEqual(combat.location_id, location_id)
        self.assertEqual(len(combat.participants), 2)
        self.assertEqual(combat.current_round, 1)
        self.assertEqual(combat.current_turn_index, 0)
        self.assertEqual(combat.turn_order, [npc1_id, char1_id])

        npc_participant = combat.get_participant_data(npc1_id) # Use helper
        char_participant = combat.get_participant_data(char1_id) # Use helper
        assert npc_participant is not None and char_participant is not None # For type safety
        self.assertEqual(npc_participant.initiative, 16)
        self.assertEqual(char_participant.initiative, 12)

        self.assertIn(combat.id, self.combat_manager._active_combats[guild_id])
        self.assertIn(combat.id, self.combat_manager._dirty_combats[guild_id])

        mock_send_cb.assert_called_once()
        # self.assertIn("Бой начинается", mock_send_cb.call_args[0][0]) # Localization key might change
        # self.assertIn(mock_npc1.name_i18n["en"] + " ходит первым", mock_send_cb.call_args[0][0])

        self.mock_game_log_manager.log_info.assert_any_call(
            ANY,
            guild_id=guild_id, location_id=location_id
        )
        self.mock_game_log_manager.log_info.assert_any_call(
            f"Combat {combat.id} started in location {location_id} for guild {guild_id}.",
            guild_id=guild_id, combat_id=combat.id, location_id=location_id
        )

    async def test_start_combat_no_valid_participants(self):
        guild_id = "guild_no_parts_sc"
        self.mock_character_manager.get_character_by_id.return_value = None # Changed to get_character_by_id
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=None) # Changed to get_npc_by_id

        combat = await self.combat_manager.start_combat(guild_id, "loc_no_parts", [("c1","Character"), ("n1","NPC")])
        self.assertIsNone(combat)
        self.mock_game_log_manager.log_warning.assert_any_call(
            f"CombatManager: No valid participants for combat in guild {guild_id}. Aborting start_combat.",
            guild_id=guild_id # Added guild_id kwarg
        )

    @patch('bot.game.managers.combat_manager.NpcCombatAI')
    @patch('bot.game.utils.stats_calculator.calculate_effective_stats', new_callable=AsyncMock)
    async def test_process_tick_npc_acts_and_ends_combat(self, mock_calculate_stats: AsyncMock, MockNpcCombatAI: MagicMock):
        guild_id = "guild_tick_npc_end"
        combat_id = "combat_tick_end1"
        npc_id_acting = "npc_tick_actor_end"

        mock_npc_actor_obj = NpcModel(id=npc_id_acting, template_id="strong_npc", name_i18n={"en":"Acting NPCEnd"}, guild_id=guild_id, stats_json=json.dumps({"dexterity":18, "health":50, "max_health":50}))

        npc_participant = CombatParticipant(entity_id=npc_id_acting, entity_type="NPC", hp=50, max_hp=50, initiative=20, acted_this_round=False)
        player_participant_defeated = CombatParticipant(entity_id="player_tick_target_end", entity_type="Character", hp=0, max_hp=60, initiative=10)

        test_combat = Combat(
            id=combat_id, guild_id=guild_id, location_id="loc_tick_end", is_active=True,
            participants=[npc_participant, player_participant_defeated],
            turn_order=[npc_id_acting, "player_tick_target_end"], current_turn_index=0, current_round=1,
            combat_log_json='[]' # combat_log to combat_log_json
        )
        self.combat_manager._active_combats[guild_id] = {combat_id: test_combat}

        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=mock_npc_actor_obj) # Changed to get_npc_by_id

        mock_ai_instance = MockNpcCombatAI.return_value
        npc_chosen_action = {"type": "ATTACK", "target_ids": ["player_tick_target_end"], "action_name":"Finishing Blow"}
        mock_ai_instance.get_npc_combat_action = AsyncMock(return_value=npc_chosen_action) # Make it async

        self.combat_manager.handle_participant_action_complete = AsyncMock()
        self.mock_rule_engine.check_combat_end_conditions = AsyncMock(return_value={"ended": True, "winners": [npc_id_acting]})
        self.combat_manager.end_combat = AsyncMock()

        kwargs_for_tick: Dict[str, TypingAny] = {"guild_id": guild_id, "rule_engine": self.mock_rule_engine, "game_log_manager": self.mock_game_log_manager, "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager, "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager, "party_manager": self.mock_party_manager, "inventory_manager": self.mock_inventory_manager, "location_manager": self.mock_location_manager, "relationship_manager": self.mock_relationship_manager, "quest_manager": self.mock_quest_manager, "rules_config": self.rules_config} # Added more managers

        combat_should_be_removed = await self.combat_manager.process_tick(combat_id, game_time_delta=1.0, **kwargs_for_tick)

        self.assertTrue(combat_should_be_removed)
        MockNpcCombatAI.assert_called_once_with(mock_npc_actor_obj, test_combat, kwargs_for_tick) # Added context
        mock_ai_instance.get_npc_combat_action.assert_awaited_once() # Changed to awaited

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
        self.active_combat.participants = [self.combat_participant_winner1, self.combat_participant_target_defeated]
        self.combat_manager._active_combats["guild1"]["combat1"] = self.active_combat

        winning_entity_ids = ["player_winner1_id"]
        self.mock_npc_manager.get_npc_by_id = AsyncMock(return_value=self.target_npc) # Changed to get_npc_by_id
        self.mock_character_manager.add_experience = AsyncMock()
        self.mock_rule_engine.resolve_loot_drop = AsyncMock(return_value=["potion_health"])
        self.mock_inventory_manager.add_item_to_character = AsyncMock(return_value={"success": True})

        context_for_end: Dict[str, TypingAny] = { # Added type hint
            "guild_id": "guild1", "rules_config": self.rules_config,
            "game_log_manager": self.mock_game_log_manager,
            "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
            "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
            "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
            "inventory_manager": self.mock_inventory_manager,
            "relationship_manager": self.mock_relationship_manager,
            "quest_manager": self.mock_quest_manager
        }

        await self.combat_manager.end_combat("guild1", "combat1", winning_entity_ids, context_for_end)

        self.assertFalse(self.active_combat.is_active)
        self.mock_game_log_manager.log_info.assert_any_call(
            f"Combat combat1 ended. Winners: {winning_entity_ids}.", guild_id="guild1", combat_id="combat1"
        )
        self.mock_character_manager.add_experience.assert_called_once_with("guild1", "player_winner1_id", 50)
        self.mock_game_log_manager.log_info.assert_any_call(
            "Character player_winner1_id awarded 50 XP.", guild_id="guild1", combat_id="combat1", character_id="player_winner1_id"
        )

        with patch('bot.game.managers.combat_manager.random.random', MagicMock(return_value=0.01)):
            context_for_end_loot: Dict[str, TypingAny] = { # Renamed and typed
                "guild_id": "guild1", "rules_config": self.rules_config,
                "game_log_manager": self.mock_game_log_manager,
                "character_manager": self.mock_character_manager, "npc_manager": self.mock_npc_manager,
                "item_manager": self.mock_item_manager, "status_manager": self.mock_status_manager,
                "rule_engine": self.mock_rule_engine, "party_manager": self.mock_party_manager,
                "inventory_manager": self.mock_inventory_manager,
                "relationship_manager": self.mock_relationship_manager,
                "quest_manager": self.mock_quest_manager
            }
            self.mock_inventory_manager.add_item_to_character.reset_mock()
            self.mock_game_log_manager.log_info.reset_mock()

            # Re-call end_combat, or more accurately, process_combat_consequences if it's separate
            # For this test, we'll re-call end_combat assuming it's idempotent for this part or setup is simple.
            # A better approach might be to test process_combat_consequences directly.
            await self.combat_manager.end_combat("guild1", "combat1", winning_entity_ids, context_for_end_loot)

            self.mock_character_manager.add_experience.assert_called_with("guild1", "player_winner1_id", 50)

            # Updated assertion for loot, assuming rules_config.loot_tables is now correctly populated.
            # The actual item ID will depend on how resolve_loot_drop is mocked or implemented.
            # For this test, resolve_loot_drop returns ["potion_health"]
            self.mock_inventory_manager.add_item_to_character.assert_called_with(
                 "guild1", ANY, "potion_health", 1
            )
            self.mock_game_log_manager.log_info.assert_any_call(
                f"Item potion_health awarded to character {ANY} in guild guild1 from combat combat1.",
                guild_id="guild1", combat_id="combat1", character_id=ANY
            )

        self.assertNotIn("combat1", self.combat_manager._active_combats.get("guild1", {}))
        self.assertIn("combat1", self.combat_manager._deleted_combats_ids.get("guild1", set()))


if __name__ == '__main__':
    unittest.main()
