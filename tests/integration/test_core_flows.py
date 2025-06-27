import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call
import uuid
from typing import Dict, Any, Optional, List, cast

# Managers involved in the flows
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.item_manager import ItemManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.db_service import DBService
from bot.game.managers.game_manager import GameManager # For spec

# Models
from bot.game.models.character import Character
from bot.game.models.item import Item
from bot.game.models.location import Location as PydanticLocation

# Constants or default data that might be used
from bot.game.constants import DEFAULT_BASE_STATS, GUILD_DEFAULT_INITIAL_LOCATION_ID

DUMMY_LOCATION_TEMPLATES_INTEGRATION: Dict[str, Any] = {
    "default_start_loc_tpl": {
        "id": "default_start_loc_tpl", "name_i18n": {"en": "Generic Starting Room Template"},
        "description_i18n": {"en": "A plain room."}, "exits": [],
        "initial_state": {"lit": True},
        "on_enter_triggers": [{"action": "log", "message": "Entered generic start."}],
        "on_exit_triggers": []
    },
    "loc_A_tpl": {
        "id": "loc_A_tpl", "name_i18n": {"en": "Location A Template"}, "description_i18n": {"en":"First location."},
        "exits": [{"direction": "east", "target_location_id": "loc_B_instance_move"}],
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc A."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc A."}]
    },
    "loc_B_tpl": {
        "id": "loc_B_tpl", "name_i18n": {"en": "Location B Template"}, "description_i18n": {"en":"Second location."},
        "exits": [{"direction": "west", "target_location_id": "loc_A_instance_move"}],
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc B."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc B."}]
    }
}

DUMMY_SETTINGS: Dict[str, Any] = {
    "default_initial_location_id": "default_start_loc_tpl",
    "default_base_stats": DEFAULT_BASE_STATS,
    "guilds": {
        "test_guild_int_1": {
            "default_location_id": "guild_specific_start_loc_inst_id"
        },
        "test_guild_int_move_1": {
            "default_location_id": "loc_A_instance_move"
        },
        "test_guild_int_item_1": {
             "default_location_id": "loc_item_interaction_zone"
        },
        "test_guild_int_combat_1": {
             "default_location_id": "loc_combat_arena"
        }
    },
    "item_templates": {
        "starting_sword": {"id": "starting_sword", "name_i18n": {"en":"Rusty Sword"}, "type": "equipment", "slot": "weapon", "properties": {"damage": 3}},
        "health_potion_template": {"id": "health_potion_template", "name_i18n": {"en":"Minor Potion"}, "type": "consumable", "properties": {"heal": 10}}
    },
    "location_templates": DUMMY_LOCATION_TEMPLATES_INTEGRATION
}


class BaseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    mock_db_service: DBService
    mock_game_manager: MagicMock
    mock_settings_dict: Dict[str, Any]
    location_manager: LocationManager
    item_manager: ItemManager
    character_manager: CharacterManager
    rule_engine: RuleEngine
    guild_id: str

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock(spec=DBService)
        mock_session_instance = AsyncMock() # spec=AsyncSession if available

        self.mock_db_service.get_session = MagicMock()
        self.mock_db_service.get_session.return_value.__aenter__.return_value = mock_session_instance
        self.mock_db_service.get_session.return_value.__aexit__ = AsyncMock(return_value=None)


        self.mock_settings_dict = DUMMY_SETTINGS.copy()

        # Mock GameManager and all its sub-managers that might be accessed
        self.mock_game_manager = MagicMock(spec=GameManager)
        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_game_manager.settings = self.mock_settings_dict

        # Mock all manager attributes on game_manager
        self.mock_game_manager.rule_engine = AsyncMock(spec=RuleEngine)
        self.mock_game_manager.event_manager = AsyncMock()
        self.mock_game_manager.character_manager = AsyncMock(spec=CharacterManager)
        self.mock_game_manager.npc_manager = AsyncMock()
        self.mock_game_manager.item_manager = AsyncMock(spec=ItemManager)
        self.mock_game_manager.combat_manager = AsyncMock()
        self.mock_game_manager.status_manager = AsyncMock()
        self.mock_game_manager.party_manager = AsyncMock()
        self.mock_game_manager.time_manager = AsyncMock()
        self.mock_game_manager.game_log_manager = AsyncMock()
        self.mock_game_manager.location_manager = AsyncMock(spec=LocationManager) # Added this
        self.mock_game_manager.inventory_manager = AsyncMock() # Added this
        self.mock_game_manager.equipment_manager = AsyncMock() # Added this
        self.mock_game_manager.dialogue_manager = AsyncMock() # Added this
        self.mock_game_manager.relationship_manager = AsyncMock() # Added this


        self.mock_game_manager._event_stage_processor = AsyncMock()
        self.mock_game_manager._event_action_processor = AsyncMock()
        self.mock_game_manager._on_enter_action_executor = AsyncMock()
        self.mock_game_manager._stage_description_generator = AsyncMock()
        self.mock_game_manager.send_callback_factory = MagicMock()


class TestCharacterCreationFlow(BaseIntegrationTest):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_1"
        await super().asyncSetUp()

        self.location_manager = LocationManager(db_service=self.mock_db_service, settings=self.mock_settings_dict, game_manager=self.mock_game_manager)
        self.mock_game_manager.location_manager = self.location_manager

        self.item_manager = ItemManager(db_service=self.mock_db_service, settings=self.mock_settings_dict, game_manager=self.mock_game_manager, location_manager=self.location_manager, rule_engine=self.mock_game_manager.rule_engine)
        self.mock_game_manager.item_manager = self.item_manager

        self.character_manager = CharacterManager(db_service=self.mock_db_service, settings=self.mock_settings_dict, game_manager=self.mock_game_manager) # Simplified for now
        self.mock_game_manager.character_manager = self.character_manager

        self.default_loc_template_id = self.mock_settings_dict["default_initial_location_id"]
        self.default_start_location_instance_id = self.mock_settings_dict["guilds"][self.guild_id].get("default_location_id")

        loc_instance_check = None
        if self.default_start_location_instance_id:
            loc_instance_check = await self.location_manager.get_location_instance_by_id(self.guild_id, self.default_start_location_instance_id) # Changed method and added await

        if not self.default_start_location_instance_id or not loc_instance_check:
            with patch('uuid.uuid4', return_value=uuid.UUID('fedcba98-4321-8765-4321-876543210abc')):
                default_loc_instance_dict = await self.location_manager.create_location_instance(guild_id=self.guild_id, template_id=self.default_loc_template_id, instance_name_i18n={"en":"Default Starting Room"})
                self.assertIsNotNone(default_loc_instance_dict)
                if default_loc_instance_dict:
                    self.default_start_location_instance_id = default_loc_instance_dict['id']
                    self.mock_settings_dict["guilds"][self.guild_id]["default_location_id"] = self.default_start_location_instance_id

    async def test_character_creation_and_initial_setup(self):
        char_name = "IntegrationHero"
        discord_id_str = "discord_integration_user_1"

        created_char: Optional[Character] = await self.character_manager.create_new_character(
            guild_id=self.guild_id, discord_user_id=discord_id_str,
            name_i18n={"en": char_name, "ru": char_name},
            language="en",
            initial_location_id=self.default_start_location_instance_id, # Added initial_location_id
            player_id=str(uuid.uuid4()) # Added player_id
        )
        self.assertIsNotNone(created_char); assert created_char is not None
        self.assertEqual(created_char.name_i18n.get("en"), char_name)
        self.assertEqual(created_char.guild_id, self.guild_id)
        self.assertIsNotNone(created_char.current_location_id)
        self.assertEqual(created_char.current_location_id, self.default_start_location_instance_id)
        start_location_instance: Optional[PydanticLocation] = await self.location_manager.get_location_instance_by_id(self.guild_id, created_char.current_location_id) # Changed method and added await
        self.assertIsNotNone(start_location_instance)
        if start_location_instance: self.assertEqual(start_location_instance.id, self.default_start_location_instance_id)


class TestPlayerMovementFlow(BaseIntegrationTest):
    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_move_1"
        await super().asyncSetUp()
        self.rule_engine = RuleEngine(settings=self.mock_settings_dict, game_manager=self.mock_game_manager)
        self.mock_game_manager.rule_engine = self.rule_engine
        self.rule_engine.execute_triggers = AsyncMock(return_value=({}, True))

        self.location_manager = LocationManager(db_service=self.mock_db_service, settings=self.mock_settings_dict, game_manager=self.mock_game_manager)
        self.mock_game_manager.location_manager = self.location_manager
        self.location_manager._location_templates = { # type: ignore[attr-defined]
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']['id']: PydanticLocation.model_validate(DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']),
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']['id']: PydanticLocation.model_validate(DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl'])
        }
        with patch('uuid.uuid4', side_effect=[uuid.UUID('11111111-aaaa-1111-aaaa-111111111111'), uuid.UUID('22222222-bbbb-2222-bbbb-222222222222')]):
            loc_a_dict = await self.location_manager.create_location_instance(guild_id=self.guild_id, template_id='loc_A_tpl', instance_name_i18n={"en":"Location A"})
            loc_b_dict = await self.location_manager.create_location_instance(guild_id=self.guild_id, template_id='loc_B_tpl', instance_name_i18n={"en":"Location B"})
        self.assertIsNotNone(loc_a_dict); self.assertIsNotNone(loc_b_dict)
        self.loc_a_instance = PydanticLocation.model_validate(loc_a_dict) if loc_a_dict else None
        self.loc_b_instance = PydanticLocation.model_validate(loc_b_dict) if loc_b_dict else None
        self.assertIsNotNone(self.loc_a_instance); self.assertIsNotNone(self.loc_b_instance)

        if self.loc_a_instance and self.loc_b_instance:
            self.loc_a_instance.exits = [{"direction": "east", "target_location_id": self.loc_b_instance.id, "is_visible": True, "travel_time_seconds": 60}]
            self.loc_b_instance.exits = [{"direction": "west", "target_location_id": self.loc_a_instance.id, "is_visible": True, "travel_time_seconds": 60}]
            cast(Dict[str, Dict[str, Dict[str,Any]]], self.location_manager._location_instances).setdefault(self.guild_id, {})[self.loc_a_instance.id] = self.loc_a_instance.model_dump(by_alias=True) # type: ignore[attr-defined]
            cast(Dict[str, Dict[str, Dict[str,Any]]], self.location_manager._location_instances).setdefault(self.guild_id, {})[self.loc_b_instance.id] = self.loc_b_instance.model_dump(by_alias=True) # type: ignore[attr-defined]

        self.character_manager = CharacterManager(db_service=self.mock_db_service, settings=self.mock_settings_dict, game_manager=self.mock_game_manager) # Simplified
        self.mock_game_manager.character_manager = self.character_manager

        with patch('uuid.uuid4', return_value=uuid.UUID('33333333-cccc-3333-cccc-333333333333')):
            self.test_char: Optional[Character] = await self.character_manager.create_new_character(
                guild_id=self.guild_id, discord_user_id="char_mover_discord",
                name_i18n={"en":"CharMover"}, language="en",
                initial_location_id=self.loc_a_instance.id if self.loc_a_instance else None,
                player_id=str(uuid.uuid4()) # Added player_id
            )
        self.assertIsNotNone(self.test_char)
        if self.test_char and self.loc_a_instance: self.assertEqual(self.test_char.current_location_id, self.loc_a_instance.id)

    async def test_player_moves_between_locations_with_triggers(self):
        self.assertIsNotNone(self.test_char); self.assertIsNotNone(self.loc_a_instance); self.assertIsNotNone(self.loc_b_instance)
        if not self.test_char or not self.loc_a_instance or not self.loc_b_instance: return

        move_result = await self.location_manager.move_entity(guild_id=self.guild_id, entity_id=self.test_char.id, entity_type="Character", from_location_id=self.loc_a_instance.id, to_location_id=self.loc_b_instance.id)
        self.assertTrue(move_result)
        updated_char = await self.character_manager.get_character_by_id(self.guild_id, self.test_char.id) # Changed to get_character_by_id
        self.assertIsNotNone(updated_char); assert updated_char is not None
        self.assertEqual(updated_char.current_location_id, self.loc_b_instance.id)

        self.assertGreaterEqual(cast(AsyncMock, self.rule_engine.execute_triggers).await_count, 2)
        departure_call = cast(AsyncMock, self.rule_engine.execute_triggers).await_args_list[0]
        arrival_call = cast(AsyncMock, self.rule_engine.execute_triggers).await_args_list[1]

        self.assertEqual(departure_call.kwargs['triggers'], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']['on_exit_triggers'])
        self.assertEqual(departure_call.kwargs['context']['location_instance_id'], self.loc_a_instance.id)
        self.assertEqual(departure_call.kwargs['context']['entity_id'], self.test_char.id)
        self.assertEqual(arrival_call.kwargs['triggers'], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']['on_enter_triggers'])
        self.assertEqual(arrival_call.kwargs['context']['location_instance_id'], self.loc_b_instance.id)
        self.assertEqual(arrival_call.kwargs['context']['entity_id'], self.test_char.id)

class TestItemInteractionFlow(BaseIntegrationTest):
    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_item_1"; await super().asyncSetUp()
        self.location_manager = LocationManager(self.mock_db_service, self.mock_settings_dict, self.mock_game_manager)
        self.mock_game_manager.location_manager = self.location_manager
        self.location_manager._location_templates = { DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: PydanticLocation.model_validate(DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl'])} # type: ignore[attr-defined]
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-item-flow----1111')):
            loc_dict = await self.location_manager.create_location_instance(self.guild_id, DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'], instance_name_i18n={"en":"Item Zone"})
        self.test_location_instance = PydanticLocation.model_validate(loc_dict) if loc_dict else None; self.assertIsNotNone(self.test_location_instance)

        self.item_manager = ItemManager(self.mock_db_service, self.mock_settings_dict, self.mock_game_manager, self.location_manager, self.mock_game_manager.rule_engine)
        self.mock_game_manager.item_manager = self.item_manager
        await self.item_manager._load_item_templates_from_settings() # Changed to await

        self.character_manager = CharacterManager(self.mock_db_service, self.mock_settings_dict, self.mock_game_manager) # Simplified
        self.mock_game_manager.character_manager = self.character_manager
        with patch('uuid.uuid4', return_value=uuid.UUID('char-int-item-flow---1111')):
            self.test_character = await self.character_manager.create_new_character(self.guild_id, "item_user_discord", name_i18n={"en":"ItemUser"}, language="en", initial_location_id=self.test_location_instance.id if self.test_location_instance else None, player_id=str(uuid.uuid4()))
        self.assertIsNotNone(self.test_character)

        self.potion_template_id = "health_potion_template"
        with patch('uuid.uuid4', return_value=uuid.UUID('item-int-potion------1111')):
            self.item_in_location_dict = await self.item_manager.create_item_instance_in_world(guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1.0, location_id=self.test_location_instance.id if self.test_location_instance else None) # Changed method and quantity to float
        self.assertIsNotNone(self.item_in_location_dict)
        self.item_in_location = Item.model_validate(self.item_in_location_dict) if self.item_in_location_dict else None

        if self.test_location_instance and self.item_in_location:
             items_in_loc = await self.item_manager.get_items_by_location_id(self.guild_id, self.test_location_instance.id)
             self.assertTrue(any(i.id == self.item_in_location.id for i in items_in_loc))

    async def test_pick_up_item_from_location(self):
        self.assertIsNotNone(self.test_character); self.assertIsNotNone(self.item_in_location); self.assertIsNotNone(self.test_location_instance)
        if not self.test_character or not self.item_in_location or not self.test_location_instance: return

        # Use transfer_item_world_to_character or similar high-level method if available
        # For now, directly updating via update_item_instance for test simplicity if transfer method is complex
        update_success = await self.item_manager.update_item_instance_in_world(self.guild_id, self.item_in_location.id, { "owner_id": self.test_character.id, "owner_type": "Character", "location_id": None })
        self.assertTrue(update_success)

        # Verify item is in character's inventory (using appropriate ItemManager method)
        char_items = await self.item_manager.get_items_by_owner_id(self.guild_id, self.test_character.id, owner_type="Character")
        self.assertTrue(any(i.id == self.item_in_location.id for i in char_items))

        # Verify item is no longer in location's inventory
        loc_items_after = await self.item_manager.get_items_by_location_id(self.guild_id, self.test_location_instance.id)
        self.assertFalse(any(i.id == self.item_in_location.id for i in loc_items_after))


    async def test_drop_item_to_location(self):
        self.assertIsNotNone(self.test_character); self.assertIsNotNone(self.test_location_instance)
        if not self.test_character or not self.test_location_instance : return

        # First, give the character an item
        dropped_item_id_obj = uuid.UUID('item-to-be-dropped---1111')
        with patch('uuid.uuid4', return_value=dropped_item_id_obj):
            char_item_dict = await self.item_manager.create_item_instance_in_inventory(guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1.0, owner_id=self.test_character.id, owner_type="Character")
        self.assertIsNotNone(char_item_dict)
        char_item = Item.model_validate(char_item_dict) if char_item_dict else None
        self.assertIsNotNone(char_item)
        if not char_item: return

        # Now, drop the item
        update_success = await self.item_manager.update_item_instance_in_world(self.guild_id, char_item.id, { "owner_id": None, "owner_type": None, "location_id": self.test_location_instance.id })
        self.assertTrue(update_success)

        # Verify item is in location
        loc_items_after_drop = await self.item_manager.get_items_by_location_id(self.guild_id, self.test_location_instance.id)
        self.assertTrue(any(i.id == char_item.id for i in loc_items_after_drop))

        # Verify item is not in character's inventory
        char_items_after_drop = await self.item_manager.get_items_by_owner_id(self.guild_id, self.test_character.id, owner_type="Character")
        self.assertFalse(any(i.id == char_item.id for i in char_items_after_drop))


class TestCombatFlow(BaseIntegrationTest): # Added BaseIntegrationTest
    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_combat_1"
        await super().asyncSetUp()
        # Further setup for combat specific entities (NPCs, Characters with combat stats)
        self.location_manager = LocationManager(self.mock_db_service, self.mock_settings_dict, self.mock_game_manager)
        self.mock_game_manager.location_manager = self.location_manager
        self.location_manager._location_templates = { DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: PydanticLocation.model_validate(DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl'])} # type: ignore[attr-defined]
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-combat-flow---1111')):
            loc_dict = await self.location_manager.create_location_instance(self.guild_id, DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'], instance_name_i18n={"en":"Combat Arena"})
        self.combat_arena_instance = PydanticLocation.model_validate(loc_dict) if loc_dict else None
        self.assertIsNotNone(self.combat_arena_instance)

        self.character_manager = CharacterManager(self.mock_db_service, self.mock_settings_dict, self.mock_game_manager) # Simplified
        self.mock_game_manager.character_manager = self.character_manager

        with patch('uuid.uuid4', return_value=uuid.UUID('hero-combat-flow---1111')):
            self.hero_char = await self.character_manager.create_new_character(self.guild_id, "hero_combat_discord", name_i18n={"en":"Hero"}, language="en", initial_location_id=self.combat_arena_instance.id if self.combat_arena_instance else None, player_id=str(uuid.uuid4()), stats_json=json.dumps({"hp": 50, "max_health": 50, "attack": 10}))
        self.assertIsNotNone(self.hero_char)

        # For NPC creation, we might need a mock NPCManager setup if CharacterManager doesn't handle it
        # For now, assume combat involves two characters or direct interaction with CharacterManager for HP updates.
        with patch('uuid.uuid4', return_value=uuid.UUID('vill-combat-flow---1111')):
            self.villain_char = await self.character_manager.create_new_character(self.guild_id, "villain_combat_discord", name_i18n={"en":"Villain"}, language="en", initial_location_id=self.combat_arena_instance.id if self.combat_arena_instance else None, player_id=str(uuid.uuid4()), stats_json=json.dumps({"hp": 30, "max_health": 30, "defense": 2}))
        self.assertIsNotNone(self.villain_char)


    async def test_attack_and_health_update(self):
        if not self.hero_char or not self.villain_char: self.fail("Characters not initialized")

        # Simulate an attack: Hero attacks Villain
        # This is a simplified interaction. Real combat would use CombatManager.
        # For integration, we assume CharacterManager might have a method to update health directly
        # or RuleEngine processes an attack action.

        # Assuming a direct health update via CharacterManager for simplicity of this flow test
        # In a real scenario, this would go through CombatManager -> RuleEngine -> CharacterManager
        initial_villain_hp_str = json.loads(self.villain_char.stats_json).get("hp", 0) if self.villain_char.stats_json else 0
        damage_dealt = 8 # Hero's attack (10) - Villain's defense (2 assumed from stats)
        new_villain_hp = initial_villain_hp_str - damage_dealt

        updated_char = await self.character_manager.update_character_health(self.guild_id, self.villain_char.id, new_villain_hp)
        self.assertTrue(updated_char)

        fetched_villain = await self.character_manager.get_character_by_id(self.guild_id, self.villain_char.id)
        self.assertIsNotNone(fetched_villain)
        if fetched_villain and fetched_villain.stats_json:
            self.assertEqual(json.loads(fetched_villain.stats_json).get("hp"), new_villain_hp)


    async def test_lethal_damage_and_death(self):
        if not self.hero_char or not self.villain_char: self.fail("Characters not initialized")

        # Villain attacks Hero with lethal damage
        initial_hero_hp_str = json.loads(self.hero_char.stats_json).get("hp", 0) if self.hero_char.stats_json else 0
        # Assume villain deals enough damage to bring hero to 0 or less
        damage_to_hero = initial_hero_hp_str + 5
        new_hero_hp = initial_hero_hp_str - damage_to_hero

        # Simulate lethal damage via CharacterManager or a hypothetical method
        # This would normally involve CombatManager and RuleEngine setting 'is_defeated' or similar
        updated_char = await self.character_manager.update_character_health(self.guild_id, self.hero_char.id, new_hero_hp)
        self.assertTrue(updated_char)

        # Fetch hero and check status (e.g., HP is 0, or a 'defeated' flag is set)
        # This depends on how death/defeat is modeled. For now, check HP.
        fetched_hero = await self.character_manager.get_character_by_id(self.guild_id, self.hero_char.id)
        self.assertIsNotNone(fetched_hero)
        if fetched_hero and fetched_hero.stats_json:
             self.assertEqual(json.loads(fetched_hero.stats_json).get("hp"), 0) # HP should be floored at 0

        # Further checks could involve:
        # - CharacterManager marking character as defeated/inactive
        # - Event triggers for character death (e.g., via RuleEngine)
        # - Loot drop or XP gain for the victor (would involve CombatManager/RuleEngine)

if __name__ == '__main__':
    unittest.main()
