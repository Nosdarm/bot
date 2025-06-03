import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call
import uuid

# Managers involved in the flows
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.rule_engine import RuleEngine # Assuming a concrete RuleEngine might be needed for some trigger tests

# Models
from bot.game.models.character import Character
from bot.game.models.item import Item
from bot.game.models.location import Location

# Constants or default data that might be used
from bot.game.constants import DEFAULT_BASE_STATS, GUILD_DEFAULT_INITIAL_LOCATION_ID

# Dummy data for settings if needed
DUMMY_SETTINGS = {
    "default_initial_location_id": "default_start_loc_tpl",
    "default_base_stats": DEFAULT_BASE_STATS,
    "guilds": {
        "test_guild_1": {
            "default_location_id": "guild_specific_start_loc_inst_id" # This would be an instance ID
        }
    },
    "item_templates": { # For ItemManager
        "starting_sword": {"id": "starting_sword", "name": "Rusty Sword", "type": "equipment", "slot": "weapon", "properties": {"damage": 3}},
        "health_potion_template": {"id": "health_potion_template", "name": "Minor Potion", "type": "consumable", "properties": {"heal": 10}}
    }
}

# Dummy location template data for LocationManager
DUMMY_LOCATION_TEMPLATES_INTEGRATION = {
    "default_start_loc_tpl": {
        "id": "default_start_loc_tpl", "name": "Generic Starting Room Template",
        "description": "A plain room.", "exits": {}, "initial_state": {"lit": True},
        "on_enter_triggers": [{"action": "log", "message": "Entered generic start."}],
        "on_exit_triggers": []
    },
    "loc_A_tpl": {
        "id": "loc_A_tpl", "name": "Location A Template", "description": "First location.",
        "exits": {"east": "loc_B_tpl"}, # This would ideally be an instance ID after creation
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc A."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc A."}]
    },
    "loc_B_tpl": {
        "id": "loc_B_tpl", "name": "Location B Template", "description": "Second location.",
        "exits": {"west": "loc_A_tpl"},
        "on_enter_triggers": [{"action": "log", "message": "Entered Loc B."}],
        "on_exit_triggers": [{"action": "log", "message": "Exited Loc B."}]
    }
}


class TestCharacterCreationFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_1"
        self.mock_db_adapter = AsyncMock()

        # Mock settings - use a dictionary that can be accessed by managers
        self.mock_settings_dict = DUMMY_SETTINGS.copy()


        # Initialize Managers
        # For LocationManager, we want it to actually load templates and allow instance creation.
        # So, we don't mock its internal methods like create_location_instance unless necessary for a specific test.
        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings_dict, # Pass the dict directly
            rule_engine=AsyncMock(), # Mocked for now
            event_manager=AsyncMock(),
            character_manager=AsyncMock(), # Will be replaced by real CharacterManager later
            npc_manager=AsyncMock(),
            item_manager=AsyncMock(), # Will be replaced by real ItemManager later
            combat_manager=AsyncMock(),
            status_manager=AsyncMock(),
            party_manager=AsyncMock(),
            time_manager=AsyncMock(),
            send_callback_factory=MagicMock(),
            event_stage_processor=AsyncMock(),
            event_action_processor=AsyncMock(),
            on_enter_action_executor=AsyncMock(),
            stage_description_generator=AsyncMock()
        )
        # Manually trigger template loading for LocationManager if its __init__ doesn't do it,
        # or set up its internal _location_templates cache.
        # Assuming LocationManager's load_state or a specific method loads templates.
        # For integration, we might want to simulate this.
        # Let's assume load_state handles templates and instances.
        # For this test, we'll directly populate its template cache.
        self.location_manager._location_templates[self.guild_id] = DUMMY_LOCATION_TEMPLATES_INTEGRATION.copy()


        # ItemManager
        # Patch its _load_item_templates to control template loading for tests if needed,
        # or allow it to run if settings are mocked correctly.
        # For this flow, let's allow it to load from our DUMMY_SETTINGS.
        self.item_manager = ItemManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings_dict,
            character_manager=AsyncMock(), # Will be replaced
            npc_manager=AsyncMock(),
            location_manager=self.location_manager
        )
        # ItemManager's __init__ calls _load_item_templates which uses settings.get_all_item_templates()

        # CharacterManager - this is the primary manager under test for this flow.
        self.character_manager = CharacterManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings_dict,
            rule_engine=AsyncMock(), # Mocked for now
            location_manager=self.location_manager, # Real LocationManager
            status_manager=AsyncMock(),
            combat_manager=AsyncMock(),
            party_manager=AsyncMock()
            # item_manager=self.item_manager # If CharacterManager needs ItemManager directly
        )

        # Link managers if they have direct dependencies not set via __init__
        # (e.g., self.location_manager.character_manager = self.character_manager)
        # This depends on manager design. Assuming constructor injection is primary.

        # Create a default starting location instance for characters to spawn in
        self.default_loc_template_id = self.mock_settings_dict["default_initial_location_id"]

        # We need a way for CharacterManager to get the *instance ID* of the default location.
        # The setting "default_initial_location_id" points to a template ID.
        # The setting "guilds.test_guild_1.default_location_id" points to an instance ID.
        # Let's ensure LocationManager can provide this.

        self.default_start_location_instance_id = self.mock_settings_dict["guilds"][self.guild_id].get("default_location_id")
        if not self.default_start_location_instance_id:
             # If no guild-specific instance ID, create one from the global default template ID
            with patch('uuid.uuid4', return_value=uuid.UUID('fedcba98-4321-8765-4321-876543210abc')): # Predictable ID
                default_loc_instance = await self.location_manager.create_location_instance(
                    guild_id=self.guild_id,
                    template_id=self.default_loc_template_id,
                    instance_name="Default Starting Room"
                )
                self.assertIsNotNone(default_loc_instance, "Failed to create default location instance for test setup.")
                self.default_start_location_instance_id = default_loc_instance['id']
                # Update mock settings to reflect this created instance ID as the guild default
                self.mock_settings_dict["guilds"][self.guild_id]["default_location_id"] = self.default_start_location_instance_id
        else:
            # Ensure this pre-configured instance exists in LocationManager if it's defined in settings
            if not await self.location_manager.get_location_instance(self.guild_id, self.default_start_location_instance_id):
                 with patch('uuid.uuid4', return_value=uuid.UUID(self.default_start_location_instance_id.replace("guild_specific_start_loc_inst_id", "abcdef12-1234-5678-1234-567812345678"))): # Ensure UUID if needed by model
                    loc_inst = await self.location_manager.create_location_instance(
                        guild_id=self.guild_id,
                        template_id=self.default_loc_template_id, # Assume it's based on the global default template
                        instance_name="Guild Specific Start Instance"
                        # id_override=self.default_start_location_instance_id # If create_location_instance supports id_override
                    )
                    # If id_override is not supported, the instance ID might differ, adjust test logic.
                    # For now, assuming create_location_instance generates its own ID and we use that.
                    # This part of the setup is tricky if the instance ID is pre-defined in settings.
                    # A better approach for LocationManager might be to ensure a named default instance exists.
                    self.assertIsNotNone(loc_inst, "Failed to create guild specific default location instance.")
                    # Forcing the ID here if create_location_instance doesn't allow override:
                    # self.default_start_location_instance_id = loc_inst['id']
                    # self.mock_settings_dict["guilds"][self.guild_id]["default_location_id"] = self.default_start_location_instance_id


    async def test_character_creation_and_initial_setup(self):
        char_name = "IntegrationHero"
        discord_id = "discord_integration_user_1"

        # Spy on ItemManager.create_item_instance if testing default item spawning
        # self.item_manager.create_item_instance = AsyncMock(wraps=self.item_manager.create_item_instance)

        # 1. Create Character
        created_char = await self.character_manager.create_character(
            guild_id=self.guild_id,
            discord_id=discord_id,
            name=char_name
            # Assuming create_character uses LocationManager to find default location
        )

        # 2. Verify Character
        self.assertIsNotNone(created_char)
        self.assertEqual(created_char.name, char_name)
        self.assertEqual(created_char.guild_id, self.guild_id)
        self.assertIn(created_char.id, self.character_manager._characters[self.guild_id])

        # 3. Verify Location
        # CharacterManager should have used LocationManager to get the default location ID.
        # This default_start_location_instance_id was set up in asyncSetUp.
        self.assertIsNotNone(created_char.location_id, "Character location_id should not be None.")
        self.assertEqual(created_char.location_id, self.default_start_location_instance_id)

        # Verify the location instance actually exists in LocationManager
        start_location_instance = await self.location_manager.get_location_instance(self.guild_id, created_char.location_id)
        self.assertIsNotNone(start_location_instance, "Default start location instance not found in LocationManager.")
        self.assertEqual(start_location_instance['id'], self.default_start_location_instance_id)

        # 4. (Optional) Verify Default Item Spawning (if applicable)
        # Example: if characters should start with a "starting_sword"
        # await asyncio.sleep(0) # Allow any background item creation tasks to run if they exist
        # starting_sword_template_id = "starting_sword"
        # if starting_sword_template_id in DUMMY_SETTINGS["item_templates"]:
        #     char_items = self.item_manager.get_items_by_owner(self.guild_id, created_char.id)
        #     self.assertTrue(any(item.template_id == starting_sword_template_id for item in char_items),
        #                     "Character should have a starting sword.")
            # self.item_manager.create_item_instance.assert_called() # Check if it was called
            # call_args = self.item_manager.create_item_instance.call_args_list[0] # Get first call
            # self.assertEqual(call_args.kwargs['guild_id'], self.guild_id)
            # self.assertEqual(call_args.kwargs['template_id'], starting_sword_template_id)
            # self.assertEqual(call_args.kwargs['owner_id'], created_char.id)


class TestPlayerMovementFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_move_1"
        self.mock_db_adapter = AsyncMock()
        self.mock_settings_dict = DUMMY_SETTINGS.copy() # Re-use if applicable, or define specific for movement

        # RuleEngine needs to be less mocked here to verify trigger content, but execute_triggers itself spied on
        self.rule_engine = RuleEngine(settings=self.mock_settings_dict, event_manager=AsyncMock()) # Basic RuleEngine
        self.rule_engine.execute_triggers = AsyncMock(return_value=({}, True)) # Spy on execute_triggers

        # LocationManager setup
        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.rule_engine,
            event_manager=AsyncMock(), character_manager=AsyncMock(), npc_manager=AsyncMock(),
            item_manager=AsyncMock(), combat_manager=AsyncMock(), status_manager=AsyncMock(),
            party_manager=AsyncMock(), time_manager=AsyncMock(), send_callback_factory=MagicMock(),
            event_stage_processor=AsyncMock(),event_action_processor=AsyncMock(),
            on_enter_action_executor=AsyncMock(),stage_description_generator=AsyncMock()
        )
        # Populate templates directly
        self.location_manager._location_templates[self.guild_id] = {
            tpl['id']: tpl for tpl in [DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl'], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']]
        }

        # Create instances for loc_A and loc_B
        # Ensure exits correctly point to the *instance IDs*
        with patch('uuid.uuid4', side_effect=[uuid.UUID('11111111-aaaa-1111-aaaa-111111111111'), uuid.UUID('22222222-bbbb-2222-bbbb-222222222222')]):
            self.loc_a_instance = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id='loc_A_tpl', instance_name="Location A"
            )
            self.loc_b_instance = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id='loc_B_tpl', instance_name="Location B"
            )
        self.assertIsNotNone(self.loc_a_instance)
        self.assertIsNotNone(self.loc_b_instance)

        # Update exits to point to instance IDs - this is crucial for move_entity to work
        self.loc_a_instance['exits'] = {'east': self.loc_b_instance['id']}
        self.loc_b_instance['exits'] = {'west': self.loc_a_instance['id']}
        # Manually update in manager's cache for the test
        self.location_manager._location_instances[self.guild_id][self.loc_a_instance['id']] = self.loc_a_instance
        self.location_manager._location_instances[self.guild_id][self.loc_b_instance['id']] = self.loc_b_instance


        # CharacterManager setup
        self.character_manager = CharacterManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.rule_engine,
            location_manager=self.location_manager, status_manager=AsyncMock(),
            combat_manager=AsyncMock(), party_manager=AsyncMock()
        )
        # Link CharacterManager to LocationManager if it needs it (e.g. for location validation during move)
        # self.location_manager.character_manager = self.character_manager # Example

        # Create a character and place them in Location A
        with patch('uuid.uuid4', return_value=uuid.UUID('33333333-cccc-3333-cccc-333333333333')):
            self.test_char = await self.character_manager.create_character(
                guild_id=self.guild_id,
                discord_id="char_mover_discord",
                name="CharMover",
                initial_location_id=self.loc_a_instance['id'] # Place in Loc A
            )
        self.assertIsNotNone(self.test_char)
        self.assertEqual(self.test_char.location_id, self.loc_a_instance['id'])


    async def test_player_moves_between_locations_with_triggers(self):
        # 1. Move Character from A to B
        move_result = await self.location_manager.move_entity(
            guild_id=self.guild_id,
            entity_id=self.test_char.id,
            entity_type="Character",
            from_location_id=self.loc_a_instance['id'],
            to_location_id=self.loc_b_instance['id'],
            character_manager=self.character_manager, # Pass the actual CharacterManager instance
            rule_engine=self.rule_engine # Pass the RuleEngine instance
        )

        # 2. Assertions
        self.assertTrue(move_result, "move_entity should return True for successful move.")

        # Verify character's location in CharacterManager
        updated_char = await self.character_manager.get_character(self.guild_id, self.test_char.id)
        self.assertIsNotNone(updated_char)
        self.assertEqual(updated_char.location_id, self.loc_b_instance['id'])

        # Verify RuleEngine.execute_triggers calls
        self.assertGreaterEqual(self.rule_engine.execute_triggers.call_count, 2)

        departure_call = self.rule_engine.execute_triggers.call_args_list[0]
        arrival_call = self.rule_engine.execute_triggers.call_args_list[1]

        # Check departure triggers from loc_A_tpl
        # The context passed to execute_triggers is augmented by handle_entity_departure/arrival
        self.assertEqual(departure_call.args[0], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_A_tpl']['on_exit_triggers'])
        self.assertEqual(departure_call.kwargs['context']['location_instance_id'], self.loc_a_instance['id'])
        self.assertEqual(departure_call.kwargs['context']['entity_id'], self.test_char.id)


        # Check arrival triggers from loc_B_tpl
        self.assertEqual(arrival_call.args[0], DUMMY_LOCATION_TEMPLATES_INTEGRATION['loc_B_tpl']['on_enter_triggers'])
        self.assertEqual(arrival_call.kwargs['context']['location_instance_id'], self.loc_b_instance['id'])
        self.assertEqual(arrival_call.kwargs['context']['entity_id'], self.test_char.id)


class TestItemInteractionFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_item_1"
        self.mock_db_adapter = AsyncMock()
        self.mock_settings_dict = DUMMY_SETTINGS.copy()
        self.mock_rule_engine = AsyncMock()
        self.mock_event_manager = AsyncMock()

        # LocationManager
        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.mock_rule_engine,
            event_manager=self.mock_event_manager, character_manager=AsyncMock(), npc_manager=AsyncMock(),
            item_manager=AsyncMock(), combat_manager=AsyncMock(), status_manager=AsyncMock(),
            party_manager=AsyncMock(), time_manager=AsyncMock(), send_callback_factory=MagicMock(),
            event_stage_processor=AsyncMock(),event_action_processor=AsyncMock(),
            on_enter_action_executor=AsyncMock(),stage_description_generator=AsyncMock()
        )
        self.location_manager._location_templates[self.guild_id] = {
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']
        }
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-item-flow----1111')):
            self.test_location_instance = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id=DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'],
                instance_name="Item Interaction Zone"
            )
        self.assertIsNotNone(self.test_location_instance)

        # ItemManager
        self.item_manager = ItemManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict,
            character_manager=AsyncMock(), npc_manager=AsyncMock(), location_manager=self.location_manager
        )
        # Ensure "health_potion_template" is loaded
        self.item_manager._load_item_templates() # Force load from DUMMY_SETTINGS

        # CharacterManager
        self.character_manager = CharacterManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.mock_rule_engine,
            location_manager=self.location_manager, status_manager=AsyncMock(),
            combat_manager=AsyncMock(), party_manager=AsyncMock()
        )
        with patch('uuid.uuid4', return_value=uuid.UUID('char-int-item-flow---1111')):
            self.test_character = await self.character_manager.create_character(
                guild_id=self.guild_id, discord_id="item_user_discord", name="ItemUser",
                initial_location_id=self.test_location_instance['id']
            )
        self.assertIsNotNone(self.test_character)

        # Create a potion item in the location
        self.potion_template_id = "health_potion_template"
        with patch('uuid.uuid4', return_value=uuid.UUID('item-int-potion------1111')):
            self.item_in_location = await self.item_manager.create_item_instance(
                guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1,
                location_id=self.test_location_instance['id']
            )
        self.assertIsNotNone(self.item_in_location)
        # Verify it's in the location initially
        items_in_loc = self.item_manager.get_items_in_location(self.guild_id, self.test_location_instance['id'])
        self.assertIn(self.item_in_location, items_in_loc)


    async def test_pick_up_item_from_location(self):
        # Item self.item_in_location is already in self.test_location_instance
        # Character self.test_character is also in self.test_location_instance

        # 1. Action: Character picks up the item
        # Simulate by directly calling ItemManager.update_item_instance
        update_success = await self.item_manager.update_item_instance(
            guild_id=self.guild_id,
            item_id=self.item_in_location.id,
            update_data={
                "owner_id": self.test_character.id,
                "owner_type": "Character",
                "location_id": None # No longer in a world location, but on a character
            }
        )
        self.assertIsNotNone(update_success, "update_item_instance should return the updated item or True.")

        # 2. Assertions
        # Item no longer in location's item list
        items_in_loc_after_pickup = self.item_manager.get_items_in_location(self.guild_id, self.test_location_instance['id'])
        self.assertNotIn(self.item_in_location.id, [item.id for item in items_in_loc_after_pickup])
        # self.assertNotIn(self.item_in_location, items_in_loc_after_pickup) # This might fail if item object identity changes

        # Item is in character's inventory (owned by character)
        char_owned_items = self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id)
        found_picked_up_item = any(item.id == self.item_in_location.id for item in char_owned_items)
        self.assertTrue(found_picked_up_item, "Picked up item not found in character's ownership list.")

        # Verify the item instance itself reflects new ownership
        updated_item_instance = self.item_manager.get_item_instance(self.guild_id, self.item_in_location.id)
        self.assertIsNotNone(updated_item_instance)
        self.assertEqual(updated_item_instance.owner_id, self.test_character.id)
        self.assertEqual(updated_item_instance.owner_type, "Character")
        self.assertIsNone(updated_item_instance.location_id)

    async def test_drop_item_to_location(self):
        # 1. Setup: Give character an item first
        item_to_drop_id_obj = uuid.UUID('item-int-drop--------1111')
        item_to_drop_id = str(item_to_drop_id_obj)
        with patch('uuid.uuid4', return_value=item_to_drop_id_obj):
            char_item_to_drop = await self.item_manager.create_item_instance(
                guild_id=self.guild_id, template_id=self.potion_template_id, quantity=1,
                owner_id=self.test_character.id, owner_type="Character"
            )
        self.assertIsNotNone(char_item_to_drop)
        # Verify it's owned by character
        char_owned_items_before_drop = self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id)
        self.assertTrue(any(item.id == char_item_to_drop.id for item in char_owned_items_before_drop))

        # 2. Action: Character drops the item in their current location
        # Character's current location is self.test_location_instance['id']
        update_success = await self.item_manager.update_item_instance(
            guild_id=self.guild_id,
            item_id=char_item_to_drop.id,
            update_data={
                "owner_id": None, # No longer directly owned by character
                "owner_type": None, # Or could be 'Location' if schema implies that
                "location_id": self.test_character.location_id
            }
        )
        self.assertIsNotNone(update_success)

        # 3. Assertions
        # Item no longer in character's ownership list
        char_owned_items_after_drop = self.item_manager.get_items_by_owner(self.guild_id, self.test_character.id)
        self.assertFalse(any(item.id == char_item_to_drop.id for item in char_owned_items_after_drop))

        # Item is now in the location's item list
        items_in_loc_after_drop = self.item_manager.get_items_in_location(self.guild_id, self.test_character.location_id)
        self.assertTrue(any(item.id == char_item_to_drop.id for item in items_in_loc_after_drop))

        # Verify the item instance itself reflects new state
        dropped_item_instance = self.item_manager.get_item_instance(self.guild_id, char_item_to_drop.id)
        self.assertIsNotNone(dropped_item_instance)
        self.assertIsNone(dropped_item_instance.owner_id)
        self.assertEqual(dropped_item_instance.location_id, self.test_character.location_id)


class TestCombatFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = "test_guild_int_combat_1"
        self.mock_db_adapter = AsyncMock()
        self.mock_settings_dict = DUMMY_SETTINGS.copy()
        self.mock_rule_engine = AsyncMock() # For general triggers, if any
        self.mock_event_manager = AsyncMock()

        # LocationManager
        self.location_manager = LocationManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.mock_rule_engine,
            event_manager=self.mock_event_manager, character_manager=AsyncMock(), npc_manager=AsyncMock(),
            item_manager=AsyncMock(), combat_manager=AsyncMock(), status_manager=AsyncMock(),
            party_manager=AsyncMock(), time_manager=AsyncMock(), send_callback_factory=MagicMock(),
            event_stage_processor=AsyncMock(),event_action_processor=AsyncMock(),
            on_enter_action_executor=AsyncMock(),stage_description_generator=AsyncMock()
        )
        self.location_manager._location_templates[self.guild_id] = {
            DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id']: DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']
        }
        with patch('uuid.uuid4', return_value=uuid.UUID('loc--int-combat-flow---1111')):
            self.combat_location_instance = await self.location_manager.create_location_instance(
                guild_id=self.guild_id, template_id=DUMMY_LOCATION_TEMPLATES_INTEGRATION['default_start_loc_tpl']['id'],
                instance_name="Combat Arena"
            )
        self.assertIsNotNone(self.combat_location_instance)

        # CharacterManager
        # For combat, CharacterManager will be central for health updates and death handling.
        self.character_manager = CharacterManager(
            db_adapter=self.mock_db_adapter, settings=self.mock_settings_dict, rule_engine=self.mock_rule_engine,
            location_manager=self.location_manager, status_manager=AsyncMock(),
            combat_manager=AsyncMock(), # Will be the actual CombatManager if testing deeper integration
            party_manager=AsyncMock()
        )

        # CombatManager - Mocked for now, direct calls to CharacterManager.update_health will simulate damage
        self.combat_manager = AsyncMock()
        # If CombatManager was real, we'd initialize it here and link it to CharacterManager if needed.
        # self.character_manager.combat_manager = self.combat_manager


        # Create Attacker and Defender
        with patch('uuid.uuid4', side_effect=[uuid.UUID('char-attacker----------1'), uuid.UUID('char-defender----------1')]):
            self.char_attacker = await self.character_manager.create_character(
                guild_id=self.guild_id, discord_id="attacker_discord", name="Attacker",
                initial_location_id=self.combat_location_instance['id'],
                stats={"max_health": 100, "current_health": 100} # Ensure stats allow health
            )
            self.char_defender = await self.character_manager.create_character(
                guild_id=self.guild_id, discord_id="defender_discord", name="Defender",
                initial_location_id=self.combat_location_instance['id'],
                stats={"max_health": 100, "current_health": 100}
            )
        self.assertIsNotNone(self.char_attacker)
        self.assertIsNotNone(self.char_defender)
        # Manually set current health if create_character doesn't use initial_stats for current_health
        self.char_attacker.current_health = 100
        self.char_defender.current_health = 100
        self.character_manager._characters[self.guild_id][self.char_attacker.id] = self.char_attacker # ensure in cache
        self.character_manager._characters[self.guild_id][self.char_defender.id] = self.char_defender # ensure in cache


    async def test_attack_and_health_update(self):
        initial_defender_health = self.char_defender.current_health
        damage_amount = -10

        # Action: Simulate attacker attacking defender by directly updating defender's health
        # In a full combat system, this would go through CombatManager.process_attack_action,
        # which would then calculate damage and call CharacterManager.update_health.
        await self.character_manager.update_health(
            guild_id=self.guild_id,
            character_id=self.char_defender.id,
            health_change=damage_amount
        )

        # Assertions
        updated_defender = await self.character_manager.get_character(self.guild_id, self.char_defender.id)
        self.assertIsNotNone(updated_defender)
        self.assertEqual(updated_defender.current_health, initial_defender_health + damage_amount)

        # Attacker's health should be unchanged
        attacker_unchanged = await self.character_manager.get_character(self.guild_id, self.char_attacker.id)
        self.assertIsNotNone(attacker_unchanged)
        self.assertEqual(attacker_unchanged.current_health, self.char_attacker.current_health) # Assuming initial health was 100

    async def test_lethal_damage_and_death(self):
        # Setup: Defender has low health
        low_health = 5
        self.char_defender.current_health = low_health
        # Ensure this low health is reflected in the manager's cache if it was re-fetched elsewhere
        self.character_manager._characters[self.guild_id][self.char_defender.id].current_health = low_health

        lethal_damage_amount = -10 # More damage than current health

        # Spy on CharacterManager.handle_character_death
        self.character_manager.handle_character_death = AsyncMock(wraps=self.character_manager.handle_character_death)

        # Action: Simulate lethal damage
        await self.character_manager.update_health(
            guild_id=self.guild_id,
            character_id=self.char_defender.id,
            health_change=lethal_damage_amount
        )

        # Assertions
        dead_defender = await self.character_manager.get_character(self.guild_id, self.char_defender.id)
        self.assertIsNotNone(dead_defender)
        self.assertEqual(dead_defender.current_health, 0) # Health should cap at 0 on death
        self.assertFalse(dead_defender.is_alive)

        # Verify handle_character_death was called
        self.character_manager.handle_character_death.assert_called_once_with(self.guild_id, self.char_defender.id)


if __name__ == '__main__':
    unittest.main()
