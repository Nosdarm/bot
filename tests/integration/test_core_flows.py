import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call
import uuid
from typing import Dict, Any, Optional # Added Optional

# Managers involved in the flows
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.item_manager import ItemManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.db_service import DBService # Added for type hinting

# Models
from bot.game.models.character import Character
from bot.game.models.item import Item
from bot.game.models.location import Location as PydanticLocation # Aliased to avoid clash if DB model is named Location

# Constants or default data that might be used
from bot.game.constants import DEFAULT_BASE_STATS, GUILD_DEFAULT_INITIAL_LOCATION_ID

# Dummy data for settings if needed
DUMMY_SETTINGS: Dict[str, Any] = {
    "default_initial_location_id": "default_start_loc_tpl",
    "default_base_stats": DEFAULT_BASE_STATS,
    "guilds": {
        "test_guild_int_1": {
            "default_location_id": "guild_specific_start_loc_inst_id"
        },
        "test_guild_int_move_1": { # Added for movement test
            "default_location_id": "loc_A_instance_move"
        },
        "test_guild_int_item_1": { # Added for item test
             "default_location_id": "loc_item_interaction_zone"
        },
        "test_guild_int_combat_1": { # Added for combat test
             "default_location_id": "loc_combat_arena"
        }
    },
    "item_templates": {
        "starting_sword": {"id": "starting_sword", "name": "Rusty Sword", "type": "equipment", "slot": "weapon", "properties": {"damage": 3}},
        "health_potion_template": {"id": "health_potion_template", "name": "Minor Potion", "type": "consumable", "properties": {"heal": 10}}
    },
    "location_templates": DUMMY_LOCATION_TEMPLATES_INTEGRATION # Moved here for consistency
}

# Dummy location template data for LocationManager
DUMMY_LOCATION_TEMPLATES_INTEGRATION: Dict[str, Any] = {
    "default_start_loc_tpl": {
        "id": "default_start_loc_tpl", "name_i18n": {"en": "Generic Starting Room Template"},
        "description_i18n": {"en": "A plain room."}, "exits": {}, "initial_state": {"lit": True},
        "on_enter_triggers": [{"action": "log", "message": "Entered generic start."}],
        "on_exit_triggers": []
    },
    "loc_A_tpl": {
        "id": "loc_A_tpl", "name_i18n": {"en": "Location A Template"}, "description_i18n": {"en":"First location."},
        "exits": {"east": "loc_B_tpl"},
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc A."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc A."}]
    },
    "loc_B_tpl": {
        "id": "loc_B_tpl", "name_i18n": {"en": "Location B Template"}, "description_i18n": {"en":"Second location."},
        "exits": {"west": "loc_A_tpl"},
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc B."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc B."}]
    }
}

class BaseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    mock_db_service: DBService
    mock_game_manager: MagicMock # Using MagicMock for flexibility in assigning attributes
    mock_settings_dict: Dict[str, Any]
    location_manager: LocationManager
    item_manager: ItemManager
    character_manager: CharacterManager
    rule_engine: RuleEngine # Can be real or mock depending on test class
    guild_id: str # To be set by subclasses

    async def asyncSetUp(self):
        self.mock_db_service = AsyncMock(spec=DBService)
        mock_session_instance = AsyncMock()
        # Ensure get_session is a MagicMock that returns an object supporting async context management
        self.mock_db_service.get_session = MagicMock()
        self.mock_db_service.get_session.return_value.__aenter__.return_value = mock_session_instance

        self.mock_settings_dict = DUMMY_SETTINGS.copy()

        self.mock_game_manager = MagicMock() # Use MagicMock for easier attribute assignment
        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_game_manager.settings = self.mock_settings_dict
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
        self.mock_game_manager._event_stage_processor = AsyncMock()
        self.mock_game_manager._event_action_processor = AsyncMock()
        self.mock_game_manager._on_enter_action_executor = AsyncMock()
        self.mock_game_manager._stage_description_generator = AsyncMock()
        self.mock_game_manager.send_callback_factory = MagicMock()


class TestCharacterCreationFlow(BaseIntegrationTest):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_1"
        await super().asyncSetUp() # Call base setup

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager,
            send_callback_factory=self.mock_game_manager.send_callback_factory
        )
        self.mock_game_manager.location_manager = self.location_manager # Assign real instance back

        self.item_manager = ItemManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.item_manager = self.item_manager # Assign real instance back

        self.character_manager = CharacterManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.character_manager = self.character_manager # Assign real instance back

        # Default location setup
        self.default_loc_template_id = self.mock_settings_dict["default_initial_location_id"]
        self.default_start_location_instance_id = self.mock_settings_dict["guilds"][self.guild_id].get("default_location_id")

        if not self.default_start_location_instance_id or \
           not await self.location_manager.get_location_instance(self.guild_id, self.default_start_location_instance_id):
            with patch('uuid.uuid4', return_value=uuid.UUID('fedcba98-4321-8765-4321-876543210abc')):
                default_loc_instance_dict = await self.location_manager.create_location_instance(
                    guild_id=self.guild_id,
                    template_id=self.default_loc_template_id,
                    instance_name="Default Starting Room"
                )
                self.assertIsNotNone(default_loc_instance_dict)
                if default_loc_instance_dict:
                    self.default_start_location_instance_id = default_loc_instance_dict['id']
                    self.mock_settings_dict["guilds"][self.guild_id]["default_location_id"] = self.default_start_location_instance_id


    async def test_character_creation_and_initial_setup(self):
        char_name = "IntegrationHero"
        discord_id_str = "discord_integration_user_1" # Ensure it's a string if Character model expects string

        created_char: Optional[Character] = await self.character_manager.create_new_character( # Assuming create_new_character is the primary method
            guild_id=self.guild_id,
            discord_user_id=discord_id_str, # Pass as string
            character_name_i18n={"en": char_name, "ru": char_name}, # Pass as dict
            # language will be taken from default or rules
        )

        self.assertIsNotNone(created_char)
        if not created_char: return # For type checker

        self.assertEqual(created_char.name_i18n.get("en"), char_name)
        self.assertEqual(created_char.guild_id, self.guild_id)

        # Check if character is in manager's cache (implementation dependent)
        # self.assertIn(created_char.id, self.character_manager._characters[self.guild_id])

        self.assertIsNotNone(created_char.current_location_id, "Character location_id should not be None.")
        self.assertEqual(created_char.current_location_id, self.default_start_location_instance_id)

        start_location_instance: Optional[PydanticLocation] = await self.location_manager.get_location_instance(self.guild_id, created_char.current_location_id)
        self.assertIsNotNone(start_location_instance)
        if start_location_instance:
            self.assertEqual(start_location_instance.id, self.default_start_location_instance_id)


class TestPlayerMovementFlow(BaseIntegrationTest):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_move_1"
        await super().asyncSetUp()

        # RuleEngine needs to be less mocked here to verify trigger content
        self.rule_engine = RuleEngine(settings=self.mock_settings_dict, game_manager=self.mock_game_manager)
        self.mock_game_manager.rule_engine = self.rule_engine # Assign real instance
        self.rule_engine.execute_triggers = AsyncMock(return_value=({}, True))

        self.location_manager = LocationManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager,
            send_callback_factory=self.mock_game_manager.send_callback_factory
        )
        self.mock_game_manager.location_manager = self.location_manager

        # Populate templates directly for LocationManager
        self.location_manager._location_templates = { # Overwrite, not append to guild_id key
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl'],
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']
        }


        with patch('uuid.uuid4', side_effect=[uuid.UUID('11111111-aaaa-1111-aaaa-111111111111'), uuid.UUID('22222222-bbbb-2222-bbbb-222222222222')]):
            loc_a_dict = await self.location_manager.create_location_instance(guild_id=self.guild_id, template_id='loc_A_tpl', instance_name="Location A")
            loc_b_dict = await self.location_manager.create_location_instance(guild_id=self.guild_id, template_id='loc_B_tpl', instance_name="Location B")
        self.assertIsNotNone(loc_a_dict); self.assertIsNotNone(loc_b_dict)
        self.loc_a_instance = PydanticLocation.from_dict(loc_a_dict) if loc_a_dict else None
        self.loc_b_instance = PydanticLocation.from_dict(loc_b_dict) if loc_b_dict else None
        self.assertIsNotNone(self.loc_a_instance); self.assertIsNotNone(self.loc_b_instance)

        if self.loc_a_instance and self.loc_b_instance:
            self.loc_a_instance.exits = {'east': self.loc_b_instance.id}
            self.loc_b_instance.exits = {'west': self.loc_a_instance.id}
            self.location_manager._location_instances.setdefault(self.guild_id, {})[self.loc_a_instance.id] = self.loc_a_instance.model_dump(by_alias=True)
            self.location_manager._location_instances.setdefault(self.guild_id, {})[self.loc_b_instance.id] = self.loc_b_instance.model_dump(by_alias=True)


        self.character_manager = CharacterManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.character_manager = self.character_manager

        with patch('uuid.uuid4', return_value=uuid.UUID('33333333-cccc-3333-cccc-333333333333')):
            self.test_char: Optional[Character] = await self.character_manager.create_new_character(
                guild_id=self.guild_id, discord_user_id="char_mover_discord",
                character_name_i18n={"en":"CharMover"},
                initial_location_id=self.loc_a_instance.id if self.loc_a_instance else None
            )
        self.assertIsNotNone(self.test_char)
        if self.test_char and self.loc_a_instance:
            self.assertEqual(self.test_char.current_location_id, self.loc_a_instance.id)


    async def test_player_moves_between_locations_with_triggers(self):
        self.assertIsNotNone(self.test_char)
        self.assertIsNotNone(self.loc_a_instance)
        self.assertIsNotNone(self.loc_b_instance)
        if not self.test_char or not self.loc_a_instance or not self.loc_b_instance: return # Type guard

        move_result = await self.location_manager.move_entity(
            guild_id=self.guild_id, entity_id=self.test_char.id, entity_type="Character",
            from_location_id=self.loc_a_instance.id, to_location_id=self.loc_b_instance.id
        )
        self.assertTrue(move_result)
        updated_char = await self.character_manager.get_character_by_id(self.guild_id, self.test_char.id) # Use get_character_by_id
        self.assertIsNotNone(updated_char)
        if updated_char:
            self.assertEqual(updated_char.current_location_id, self.loc_b_instance.id)

        self.assertGreaterEqual(self.rule_engine.execute_triggers.call_count, 2)
        departure_call = self.rule_engine.execute_triggers.call_args_list[0]
        arrival_call = self.rule_engine.execute_triggers.call_args_list[1]

        # Note: DUMMY_LOCATION_TEMPLATES_INTEGRATION might need name_i18n etc. to match Pydantic models if used for comparison
        # For now, assuming trigger content is string based or simple dicts.
        self.assertEqual(departure_call.kwargs['triggers'], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']['on_exit_triggers'])
        self.assertEqual(departure_call.kwargs['context']['location_instance_id'], self.loc_a_instance.id)
        self.assertEqual(departure_call.kwargs['context']['entity_id'], self.test_char.id)

        self.assertEqual(arrival_call.kwargs['triggers'], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']['on_enter_triggers'])
        self.assertEqual(arrival_call.kwargs['context']['location_instance_id'], self.loc_b_instance.id)
        self.assertEqual(arrival_call.kwargs['context']['entity_id'], self.test_char.id)


class TestItemInteractionFlow(BaseIntegrationTest):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_item_1"
        await super().asyncSetUp()

        self.location_manager = LocationManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager,
            send_callback_factory=self.mock_game_manager.send_callback_factory
        )
        self.mock_game_manager.location_manager = self.location_manager
        self.location_manager._location_templates = { # Overwrite
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']
        }
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-item-flow----1111')):
            loc_dict = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id=DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'],
                instance_name="Item Interaction Zone"
            )
        self.assertIsNotNone(loc_dict)
        self.test_location_instance: Optional[PydanticLocation] = PydanticLocation.from_dict(loc_dict) if loc_dict else None
        self.assertIsNotNone(self.test_location_instance)


        self.item_manager = ItemManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.item_manager = self.item_manager
        self.item_manager._load_item_templates()

        self.character_manager = CharacterManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.character_manager = self.character_manager

        with patch('uuid.uuid4', return_value=uuid.UUID('char-int-item-flow---1111')):
            self.test_character: Optional[Character] = await self.character_manager.create_new_character(
                guild_id=self.guild_id, discord_user_id="item_user_discord",
                character_name_i18n={"en":"ItemUser"},
                initial_location_id=self.test_location_instance.id if self.test_location_instance else None
            )
        self.assertIsNotNone(self.test_character)

        self.potion_template_id = "health_potion_template"
        with patch('uuid.uuid4', return_value=uuid.UUID('item-int-potion------1111')):
            self.item_in_location: Optional[Item] = await self.item_manager.create_item_instance_in_db( # Assuming create_item_instance_in_db for direct creation
                guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1,
                location_id=self.test_location_instance.id if self.test_location_instance else None
            ) # create_item_instance_in_db returns Pydantic model
        self.assertIsNotNone(self.item_in_location)
        if self.test_location_instance and self.item_in_location:
            items_in_loc = await self.item_manager.get_items_in_location(self.guild_id, self.test_location_instance.id)
            self.assertTrue(any(i.id == self.item_in_location.id for i in items_in_loc))


    async def test_pick_up_item_from_location(self):
        self.assertIsNotNone(self.test_character); self.assertIsNotNone(self.item_in_location); self.assertIsNotNone(self.test_location_instance)
        if not self.test_character or not self.item_in_location or not self.test_location_instance: return

        update_success = await self.item_manager.update_item_instance_in_db( # Assuming update_item_instance_in_db
            guild_id=self.guild_id, item_id=self.item_in_location.id,
            updates={ "owner_id": self.test_character.id, "owner_type": "Character", "location_id": None }
        )
        self.assertTrue(update_success)

        items_in_loc_after_pickup = await self.item_manager.get_items_in_location(self.guild_id, self.test_location_instance.id)
        self.assertFalse(any(i.id == self.item_in_location.id for i in items_in_loc_after_pickup))

        char_owned_items = await self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id, "Character")
        self.assertTrue(any(item.id == self.item_in_location.id for item in char_owned_items))

        updated_item_instance = await self.item_manager.get_item_instance_from_db(self.guild_id, self.item_in_location.id)
        self.assertIsNotNone(updated_item_instance)
        if updated_item_instance:
            self.assertEqual(updated_item_instance.owner_id, self.test_character.id)
            self.assertEqual(updated_item_instance.owner_type, "Character")
            self.assertIsNone(updated_item_instance.location_id)

    async def test_drop_item_to_location(self):
        self.assertIsNotNone(self.test_character); self.assertIsNotNone(self.test_location_instance)
        if not self.test_character or not self.test_location_instance: return

        item_to_drop_id_obj = uuid.UUID('item-int-drop--------1111')
        with patch('uuid.uuid4', return_value=item_to_drop_id_obj):
            char_item_to_drop = await self.item_manager.create_item_instance_in_db(
                guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1,
                owner_id=self.test_character.id, owner_type="Character"
            )
        self.assertIsNotNone(char_item_to_drop)
        char_owned_items_before_drop = await self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id, "Character")
        self.assertTrue(any(item.id == char_item_to_drop.id for item in char_owned_items_before_drop))

        update_success = await self.item_manager.update_item_instance_in_db(
            guild_id=self.guild_id, item_id=char_item_to_drop.id,
            updates={ "owner_id": None, "owner_type": None, "location_id": self.test_character.current_location_id}
        )
        self.assertTrue(update_success)

        char_owned_items_after_drop = await self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id, "Character")
        self.assertFalse(any(item.id == char_item_to_drop.id for item in char_owned_items_after_drop))

        if self.test_character.current_location_id:
            items_in_loc_after_drop = await self.item_manager.get_items_in_location(self.guild_id, self.test_character.current_location_id)
            self.assertTrue(any(item.id == char_item_to_drop.id for item in items_in_loc_after_drop))

        dropped_item_instance = await self.item_manager.get_item_instance_from_db(self.guild_id, char_item_to_drop.id)
        self.assertIsNotNone(dropped_item_instance)
        if dropped_item_instance:
            self.assertIsNone(dropped_item_instance.owner_id)
            self.assertEqual(dropped_item_instance.location_id, self.test_character.current_location_id)


class TestCombatFlow(BaseIntegrationTest):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_combat_1"
        await super().asyncSetUp()

        self.location_manager = LocationManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager,
            send_callback_factory=self.mock_game_manager.send_callback_factory
        )
        self.mock_game_manager.location_manager = self.location_manager
        self.location_manager._location_templates = {
             DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']
        }
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-combat-flow---1111')):
            loc_dict = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id=DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'],
                instance_name="Combat Arena"
            )
        self.assertIsNotNone(loc_dict)
        self.combat_location_instance: Optional[PydanticLocation] = PydanticLocation.from_dict(loc_dict) if loc_dict else None
        self.assertIsNotNone(self.combat_location_instance)


        self.character_manager = CharacterManager(
            db_service=self.mock_db_service, settings=self.mock_settings_dict,
            game_manager=self.mock_game_manager
        )
        self.mock_game_manager.character_manager = self.character_manager

        # CombatManager itself is mocked on mock_game_manager
        # self.combat_manager = AsyncMock()
        # self.mock_game_manager.combat_manager = self.combat_manager


        with patch('uuid.uuid4', side_effect=[uuid.UUID('char-attacker----------1'), uuid.UUID('char-defender----------1')]):
            self.char_attacker: Optional[Character] = await self.character_manager.create_new_character(
                guild_id=self.guild_id, discord_user_id="attacker_discord", character_name_i18n={"en":"Attacker"},
                initial_location_id=self.combat_location_instance.id if self.combat_location_instance else None,
                stats={"max_health": 100, "current_health": 100}
            )
            self.char_defender: Optional[Character] = await self.character_manager.create_new_character(
                guild_id=self.guild_id, discord_user_id="defender_discord", character_name_i18n={"en":"Defender"},
                initial_location_id=self.combat_location_instance.id if self.combat_location_instance else None,
                stats={"max_health": 100, "current_health": 100}
            )
        self.assertIsNotNone(self.char_attacker); self.assertIsNotNone(self.char_defender)
        if self.char_attacker: self.char_attacker.current_health = 100.0 # Ensure float
        if self.char_defender: self.char_defender.current_health = 100.0 # Ensure float
        # If CharacterManager uses an internal cache, ensure it's updated or bypassed for test
        # For example, if get_character_by_id fetches fresh or from a cache that reflects these values


    async def test_attack_and_health_update(self):
        self.assertIsNotNone(self.char_attacker); self.assertIsNotNone(self.char_defender)
        if not self.char_defender or self.char_defender.current_health is None : self.fail("Defender not properly initialized")

        initial_defender_health = self.char_defender.current_health
        damage_amount = -10.0

        await self.character_manager.update_character_health( # Assuming method name
            guild_id=self.guild_id,
            character_id=self.char_defender.id,
            health_change=damage_amount
        )
        updated_defender = await self.character_manager.get_character_by_id(self.guild_id, self.char_defender.id)
        self.assertIsNotNone(updated_defender)
        if updated_defender and updated_defender.current_health is not None:
            self.assertEqual(updated_defender.current_health, initial_defender_health + damage_amount)

        attacker_unchanged = await self.character_manager.get_character_by_id(self.guild_id, self.char_attacker.id) # type: ignore
        self.assertIsNotNone(attacker_unchanged)
        if attacker_unchanged and self.char_attacker and self.char_attacker.current_health is not None:
            self.assertEqual(attacker_unchanged.current_health, self.char_attacker.current_health)

    async def test_lethal_damage_and_death(self):
        self.assertIsNotNone(self.char_defender)
        if not self.char_defender: self.fail("Defender not set up")

        low_health = 5.0
        self.char_defender.current_health = low_health
        # Simulate saving this change if CharacterManager relies on persisted state for get_character_by_id
        await self.character_manager.save_character_field(self.guild_id, self.char_defender.id, "current_health", low_health)


        lethal_damage_amount = -10.0
        self.character_manager.handle_character_death = AsyncMock() # Spy

        await self.character_manager.update_character_health(
            guild_id=self.guild_id,
            character_id=self.char_defender.id,
            health_change=lethal_damage_amount
        )
        dead_defender = await self.character_manager.get_character_by_id(self.guild_id, self.char_defender.id)
        self.assertIsNotNone(dead_defender)
        if dead_defender:
            self.assertEqual(dead_defender.current_health, 0)
            self.assertFalse(dead_defender.is_alive)

        cast(AsyncMock, self.character_manager.handle_character_death).assert_called_once_with(self.guild_id, self.char_defender.id)


if __name__ == '__main__':
    unittest.main()
