import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY, AsyncMock
import uuid
import json
import logging # Added for logger patching
from sqlalchemy.ext.asyncio import AsyncSession


from bot.game.managers.character_manager import CharacterManager, UpdateHealthResult, CharacterAlreadyExistsError
import bot.game.managers.character_manager as character_manager_module # For logger patching
from bot.game.models.character import Character
from bot.game.constants import DEFAULT_BASE_STATS, GUILD_DEFAULT_INITIAL_LOCATION_ID
from bot.database.models import Player # For type hinting if needed in player related tests

# Temporarily disable logging to reduce noise during tests, can be enabled for debugging
# logging.disable(logging.CRITICAL)


class TestCharacterManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock()
        self.mock_db_service.get_session_factory = MagicMock() # Needed for GuildTransaction
        self.mock_settings = {
            "default_initial_location_id": GUILD_DEFAULT_INITIAL_LOCATION_ID,
            "default_base_stats": DEFAULT_BASE_STATS,
            "default_bot_language": "en"
        }
        self.mock_rule_engine = AsyncMock()
        self.mock_location_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_item_manager = AsyncMock()
        self.mock_dialogue_manager = AsyncMock()
        self.mock_relationship_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_npc_manager = AsyncMock()
        self.mock_inventory_manager = AsyncMock()
        self.mock_equipment_manager = AsyncMock()
        self.mock_game_manager = AsyncMock()
        self.mock_game_manager.get_default_bot_language = AsyncMock(return_value="en") # Mock for language
        self.mock_game_manager.get_rule = AsyncMock(side_effect=lambda _, key, default: default) # Simple get_rule mock


        self.char_manager = CharacterManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            item_manager=self.mock_item_manager,
            location_manager=self.mock_location_manager,
            rule_engine=self.mock_rule_engine,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            combat_manager=self.mock_combat_manager,
            dialogue_manager=self.mock_dialogue_manager,
            relationship_manager=self.mock_relationship_manager,
            game_log_manager=self.mock_game_log_manager,
            npc_manager=self.mock_npc_manager,
            inventory_manager=self.mock_inventory_manager,
            equipment_manager=self.mock_equipment_manager,
            game_manager=self.mock_game_manager
        )
        # Ensure dependent managers are set on char_manager if they are optional and used by methods being tested
        self.char_manager._status_manager = self.mock_status_manager
        self.char_manager._combat_manager = self.mock_combat_manager
        self.char_manager._party_manager = self.mock_party_manager
        self.char_manager._location_manager = self.mock_location_manager
        self.char_manager._game_log_manager = self.mock_game_log_manager # Ensure this is set


    async def test_init_with_all_dependencies(self):
        self.assertEqual(self.char_manager._db_service, self.mock_db_service)
        self.assertEqual(self.char_manager._settings, self.mock_settings)
        self.assertEqual(self.char_manager._item_manager, self.mock_item_manager)
        self.assertEqual(self.char_manager._location_manager, self.mock_location_manager)
        self.assertEqual(self.char_manager._rule_engine, self.mock_rule_engine)
        self.assertEqual(self.char_manager._status_manager, self.mock_status_manager)
        self.assertEqual(self.char_manager._party_manager, self.mock_party_manager)
        self.assertEqual(self.char_manager._combat_manager, self.mock_combat_manager)
        self.assertEqual(self.char_manager._dialogue_manager, self.mock_dialogue_manager)
        self.assertEqual(self.char_manager._relationship_manager, self.mock_relationship_manager)
        self.assertEqual(self.char_manager._game_log_manager, self.mock_game_log_manager)
        self.assertEqual(self.char_manager._npc_manager, self.mock_npc_manager)
        self.assertEqual(self.char_manager._inventory_manager, self.mock_inventory_manager)
        self.assertEqual(self.char_manager._equipment_manager, self.mock_equipment_manager)
        self.assertEqual(self.char_manager._game_manager, self.mock_game_manager)
        self.assertEqual(self.char_manager._characters, {})
        self.assertEqual(self.char_manager._discord_to_player_map, {})
        self.assertEqual(self.char_manager._dirty_characters, {})
        self.assertEqual(self.char_manager._deleted_characters_ids, {})

    async def test_init_without_optional_dependencies(self):
        char_manager = CharacterManager(db_service=self.mock_db_service, settings=self.mock_settings)
        self.assertEqual(char_manager._db_service, self.mock_db_service)
        self.assertEqual(char_manager._settings, self.mock_settings)
        self.assertIsNone(char_manager._item_manager)
        self.assertIsNone(char_manager._rule_engine)
        self.assertIsNone(char_manager._location_manager)
        self.assertIsNone(char_manager._status_manager)
        self.assertIsNone(char_manager._combat_manager)
        self.assertIsNone(char_manager._party_manager)
        self.assertEqual(char_manager._characters, {})
        self.assertEqual(char_manager._discord_to_player_map, {})
        self.assertEqual(char_manager._dirty_characters, {})
        self.assertEqual(char_manager._deleted_characters_ids, {})

    async def test_create_new_character_success(self):
        guild_id = "guild1"
        discord_user_id = 12345
        character_name = "NewHero"
        language = "en"

        # Setup mocks for dependencies of create_new_character
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.begin_nested = AsyncMock(return_value=AsyncMock()) # for external session usage

        # Mock Player object that will be returned by get_entity_by_attributes or session.get
        mock_player_obj = Player(id="player_uuid_1", discord_id=str(discord_user_id), guild_id=guild_id, active_character_id=None)

        # Mock for get_entity_by_attributes (called if player not in cache or external session)
        # This needs to be patched within crud_utils or where it's called by CharacterManager if it's not direct.
        # For CharacterManager.create_new_character, it uses session.get or get_entity_by_attributes.
        # Let's assume it will find the player via get_entity_by_attributes
        with patch('bot.database.crud_utils.get_entity_by_attributes', AsyncMock(return_value=mock_player_obj)) as mock_get_player_attrs:
            # Mock location manager call
            mock_starting_loc = MagicMock()
            mock_starting_loc.id = "start_loc_id_123"
            self.mock_location_manager.get_location_by_static_id = AsyncMock(return_value=mock_starting_loc)

            # Mock _recalculate_and_store_effective_stats
            with patch.object(self.char_manager, '_recalculate_and_store_effective_stats', AsyncMock()) as mock_recalc:
                created_char_instance = await self.char_manager.create_new_character(
                    guild_id, discord_user_id, character_name, language, session=mock_session
                )

        self.assertIsNotNone(created_char_instance)
        self.assertEqual(created_char_instance.name, character_name) # name property check
        self.assertEqual(created_char_instance.name_i18n[language], character_name)
        self.assertEqual(created_char_instance.discord_user_id, discord_user_id) # Stored as int on model
        self.assertEqual(created_char_instance.guild_id, guild_id)
        self.assertEqual(created_char_instance.location_id, "start_loc_id_123")

        mock_session.add.assert_called() # Should be called for new Character and updated Player
        mock_session.flush.assert_called() # Should be called at least once

        # Verify cache update
        self.assertIn(guild_id, self.char_manager._characters)
        self.assertIn(created_char_instance.id, self.char_manager._characters[guild_id])
        self.assertIn(guild_id, self.char_manager._discord_to_player_map)
        self.assertEqual(self.char_manager._discord_to_player_map[guild_id][discord_user_id], mock_player_obj.id)


    async def test_create_character_already_exists_discord_id(self):
        guild_id = "guild1"
        discord_id_int = 12345
        name = "CharacterName"

        self.char_manager._characters[guild_id] = {}
        # Simulate Player already has an active character
        mock_player_obj_with_active_char = Player(id="player_uuid_existing", discord_id=str(discord_id_int), guild_id=guild_id, active_character_id="existing_char_id")
        # player_id is not a direct attribute of Character. The link is via Player.active_character_id == Character.id
        mock_existing_char_obj = Character(id="existing_char_id", guild_id=guild_id, discord_user_id=discord_id_int, name_i18n={"en":"Existing"}, selected_language="en")

        mock_session = AsyncMock(spec=AsyncSession)

        async def get_side_effect(model_cls, entity_id):
            if model_cls == Player and entity_id == mock_player_obj_with_active_char.id: return mock_player_obj_with_active_char
            if model_cls == Character and entity_id == "existing_char_id": return mock_existing_char_obj
            return None

        mock_session.get = AsyncMock(side_effect=get_side_effect)

        with patch('bot.database.crud_utils.get_entity_by_attributes', AsyncMock(return_value=mock_player_obj_with_active_char)):
            with self.assertRaises(CharacterAlreadyExistsError):
                await self.char_manager.create_new_character(guild_id, discord_id_int, name, "en", session=mock_session)

    async def test_get_character_exists(self):
        guild_id = "guild1"
        char_id = "char1"
        char_name = "TestChar"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=12345, name_i18n={"en": char_name, "ru": char_name},
            stats={'hp': 100.0, 'max_health': 100.0}, inventory=[], location_id="loc1", hp=100.0, max_health=100.0, selected_language="en"
        )
        self.char_manager._characters[guild_id] = {char_id: expected_char}

        retrieved_char = self.char_manager.get_character(guild_id, char_id) # This is synchronous
        self.assertEqual(retrieved_char, expected_char)

    async def test_get_character_by_discord_id_exists(self):
        guild_id = "guild1"
        discord_id_int = 12345
        char_id = "char1"
        # player_id is not directly on Character model, it's linked via Player.active_character_id
        char_name = "TestChar"
        expected_char = Character(
            id=char_id, guild_id=guild_id, discord_user_id=discord_id_int, name_i18n={"en": char_name, "ru": char_name},
            stats={'hp': 100.0, 'max_health': 100.0}, inventory=[], location_id="loc1", hp=100.0, max_health=100.0, selected_language="en"
        )
        # mock_player is used to simulate DB state for Player with active_character_id
        mock_player = Player(id="player_for_char1", discord_id=str(discord_id_int), guild_id=guild_id, active_character_id=char_id)

        self.char_manager._characters.setdefault(guild_id, {})[char_id] = expected_char
        self.char_manager._discord_to_player_map.setdefault(guild_id, {})[discord_id_int] = mock_player.id # Use mock_player.id

        mock_session = AsyncMock(spec=AsyncSession)

        async def mock_session_get(model_cls, pk_id):
            if model_cls == Player and pk_id == mock_player.id: return mock_player # Use mock_player.id
            if model_cls == Character and pk_id == char_id: return expected_char
            return None
        mock_session.get = AsyncMock(side_effect=mock_session_get)

        # Mock refresh to do nothing or update attributes if necessary
        async def mock_refresh(obj, attribute_names=None):
            if isinstance(obj, Player) and obj.id == player_id:
                obj.active_character_id = char_id # Ensure it's set after "refresh"
            return None
        mock_session.refresh = AsyncMock(side_effect=mock_refresh)

        retrieved_char = await self.char_manager.get_character_by_discord_id(guild_id, discord_id_int, session=mock_session)
        self.assertEqual(retrieved_char, expected_char)


    async def test_update_health_deal_lethal_damage_calls_dependent_managers(self):
        guild_id = "guild1"
        char_id = "char_death_test"
        character_to_die = Character(
            id=char_id, guild_id=guild_id, discord_user_id=999, name_i18n={"en": "Hero"},
            hp=10.0, max_health=100.0, stats={'hp': 10.0, 'max_health': 100.0}, inventory=[], is_alive=True,
            party_id="party_active", location_id="loc_active", selected_language="en"
            # current_combat_id is not a direct Character field
        )
        self.char_manager._characters.setdefault(guild_id, {})[char_id] = character_to_die # Add to cache

        mock_session = AsyncMock(spec=AsyncSession)
        # mock_session.get is not strictly needed here for update_health if _recalculate_and_store_effective_stats is fully mocked
        # and update_health operates on the cached Pydantic model.
        # mock_session.get = AsyncMock(return_value=character_to_die)
        mock_session.add = AsyncMock()

        # Configure mock_session.begin() and begin_nested() to return a proper async context manager
        async_context_manager_mock = AsyncMock()
        # __aenter__ needs to return an awaitable that resolves to the context for the 'as' clause (often the session or a transaction object)
        async_context_manager_mock.__aenter__ = AsyncMock(return_value=mock_session) # Or a dedicated transaction mock if needed
        async_context_manager_mock.__aexit__ = AsyncMock(return_value=False) # Return False to not suppress exceptions

        mock_session.begin.return_value = async_context_manager_mock
        mock_session.begin_nested.return_value = async_context_manager_mock

        # Ensure dependent managers are set and are AsyncMocks
        self.char_manager._status_manager = AsyncMock()
        self.char_manager._combat_manager = AsyncMock()
        self.char_manager._party_manager = AsyncMock()
        self.char_manager._location_manager = AsyncMock()
        self.char_manager._game_log_manager = AsyncMock() # Ensure this is an AsyncMock
        self.char_manager._game_manager = AsyncMock() # Ensure game_manager is also an AsyncMock for get_rule
        self.char_manager._game_manager.get_rule = AsyncMock(return_value=True) # e.g., death_events_enabled

        # Mock _recalculate_and_store_effective_stats as it's called by update_health
        with patch.object(self.char_manager, '_recalculate_and_store_effective_stats', AsyncMock()) as mock_recalc:
            await self.char_manager.update_health(guild_id, char_id, -50.0, session=mock_session)

        self.assertFalse(character_to_die.is_alive)
        self.assertEqual(character_to_die.hp, 0.0)
        # mock_session.add.assert_called_with(character_to_die) # Removed: update_health now marks dirty, save_state handles DB persistence.
        self.char_manager.mark_character_dirty.assert_called_once_with(guild_id, char_id)


        self.mock_status_manager.clean_up_for_character.assert_awaited_once_with(guild_id, char_id, session=mock_session)
        self.mock_combat_manager.remove_participant_from_combat.assert_awaited_once_with(guild_id, "combat_active", char_id, session=mock_session)
        self.mock_party_manager.handle_character_death.assert_awaited_once_with(guild_id, char_id, session=mock_session)
        self.mock_location_manager.handle_entity_departure.assert_awaited_once_with(guild_id, "loc_active", char_id, "Character", session=mock_session)
        self.mock_game_log_manager.log_event.assert_any_call(
            guild_id=guild_id,
            event_type="PLAYER_HEALTH_CHANGE", # Or specific death event type
            details=ANY,
            character_id=char_id, # Changed from player_id
            session=mock_session
        )
        mock_recalc.assert_awaited_once() # Stats should be recalculated on health change

    async def test_save_state_dirty_characters(self):
        guild_id = "guild1"
        char1_id = "char1"
        char1_name = "Char1"
        char1 = Character(
            id=char1_id, guild_id=guild_id, discord_user_id=1, name_i18n={"en": char1_name},
            max_health=100.0, hp=100.0, stats={"str":10, "hp": 100.0, "max_health": 100.0},
            inventory=[{"item_id":"potion","quantity":1}], location_id="loc1",
            status_effects=[{"id": "poisoned", "name": "Poisoned", "duration": 5}], # Changed from status_effects_json
            is_alive=True, level=1, experience=10, selected_language="en"
        )

        self.char_manager._characters[guild_id] = {char1_id: char1}
        self.char_manager._dirty_characters[guild_id] = {char1_id}
        self.char_manager._deleted_characters_ids[guild_id] = set()

        # Mock the GuildTransaction context manager and its yielded session
        mock_session_in_transaction = AsyncMock(spec=AsyncSession)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session_in_transaction

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context): # Patched correct location
            await self.char_manager.save_state(guild_id)

        mock_session_in_transaction.merge.assert_called_once()
        args, _ = mock_session_in_transaction.merge.call_args
        merged_orm_instance = args[0]
        self.assertIsInstance(merged_orm_instance, CharacterDBModel)
        self.assertEqual(merged_orm_instance.id, char1.id)
        # Assuming name_i18n on CharacterDBModel holds the dict directly after being set from Pydantic model's to_dict()
        # If CharacterDBModel stores it as a JSON string in a field like name_i18n_json, then comparison would be different.
        # Based on current model structure, name_i18n is the column name for JSONB/JsonVariant.
        self.assertEqual(merged_orm_instance.name_i18n, char1.name_i18n)
        self.assertEqual(merged_orm_instance.hp, char1.hp)
        self.assertEqual(merged_orm_instance.level, char1.level)

        self.assertNotIn(guild_id, self.char_manager._dirty_characters) # Should be cleared

    async def test_save_state_deleted_characters(self):
        guild_id = "guild1"
        deleted_id1 = "del_char1"
        self.char_manager._deleted_characters_ids[guild_id] = {deleted_id1}
        self.char_manager._dirty_characters[guild_id] = set()
        self.char_manager._characters[guild_id] = {}

        mock_session_in_transaction = AsyncMock(spec=AsyncSession)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session_in_transaction

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context): # Patched correct location
            await self.char_manager.save_state(guild_id)

        mock_session_in_transaction.execute.assert_called_once()
        stmt = mock_session_in_transaction.execute.call_args[0][0]
        # Basic check for delete statement structure
        self.assertTrue(str(stmt.compile(compile_kwargs={"literal_binds": True})).startswith("DELETE FROM characters"))
        self.assertIn(deleted_id1, str(stmt.compile(compile_kwargs={"literal_binds": True})))
        self.assertNotIn(guild_id, self.char_manager._deleted_characters_ids)


    async def test_load_state_success(self):
        guild_id = "guild1"
        player1_id = "player1_db"
        char1_id_db = "char1_db"
        # Mock data from Player and Character tables
        mock_player_from_db = Player(id=player1_id, discord_id="discord1", guild_id=guild_id, active_character_id=char1_id_db)
        # player_id is not a direct Character field. It's linked via Player.active_character_id
        mock_char_from_db = Character(
            id=char1_id_db, guild_id=guild_id, name_i18n={"en": "CharFromDB"}, discord_user_id=123, selected_language="en"
            # Add other required fields like hp, max_health, stats if CharacterManager.load_state relies on them
            # For now, assuming basic fields are enough for this test's scope if it just checks loading into cache.
        )

        mock_session_in_transaction = AsyncMock(spec=AsyncSession)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session_in_transaction

        # Mock crud_utils.get_entities
        # mock_char_from_db was Pydantic, this should be a mock of the SQLAlchemy model
        mock_char_from_db_sqla = MagicMock(spec=CharacterDBModel)
        # Populate essential fields that char_obj_db.to_dict() would provide for Character.from_db_model()
        mock_char_from_db_sqla.id = char1_id_db
        mock_char_from_db_sqla.guild_id = guild_id
        mock_char_from_db_sqla.name_i18n = {"en": "CharFromDB"} # Assuming to_dict returns dict for JSON fields
        mock_char_from_db_sqla.discord_user_id = 123 # Needs to be string if Player.discord_id is string
        mock_char_from_db_sqla.selected_language = "en"
        # Add all other fields Character.from_db_model expects from to_dict()
        mock_char_from_db_sqla.hp = 100.0; mock_char_from_db_sqla.max_hp = 100.0; mock_char_from_db_sqla.level = 1;
        mock_char_from_db_sqla.xp = 0; mock_char_from_db_sqla.unspent_xp = 0; mock_char_from_db_sqla.gold = 0;
        mock_char_from_db_sqla.stats_json = {}; mock_char_from_db_sqla.inventory_json = [];
        mock_char_from_db_sqla.status_effects_json = []; mock_char_from_db_sqla.active_quests_json = [];
        mock_char_from_db_sqla.known_spells_json = []; mock_char_from_db_sqla.spell_cooldowns_json = {};
        mock_char_from_db_sqla.skills_data_json = []; mock_char_from_db_sqla.abilities_data_json = [];
        mock_char_from_db_sqla.spells_data_json = []; mock_char_from_db_sqla.flags_json = {};
        mock_char_from_db_sqla.state_variables_json = {}; mock_char_from_db_sqla.equipment_slots_json = {};
        mock_char_from_db_sqla.is_alive = True; mock_char_from_db_sqla.player_id = player1_id; # Added player_id
        mock_char_from_db_sqla.character_class_i18n = None; mock_char_from_db_sqla.race_key = None;
        mock_char_from_db_sqla.race_i18n = None; mock_char_from_db_sqla.description_i18n = None;
        mock_char_from_db_sqla.mp = None; mock_char_from_db_sqla.base_attack = None; mock_char_from_db_sqla.base_defense = None;
        mock_char_from_db_sqla.effective_stats_json = None; mock_char_from_db_sqla.current_game_status = None;
        mock_char_from_db_sqla.current_action_json = None; mock_char_from_db_sqla.action_queue_json = None;
        mock_char_from_db_sqla.collected_actions_json = None; mock_char_from_db_sqla.current_location_id = None;
        mock_char_from_db_sqla.current_party_id = None;
        # Mock the to_dict method itself
        mock_char_from_db_sqla.to_dict.return_value = {
            f.name: getattr(mock_char_from_db_sqla, f.name) for f in CharacterDBModel.__table__.columns
        }


        async def mock_get_entities_fixed(session, model_class, *, guild_id):
            if model_class == Player:
                if guild_id == guild_id_str: return [mock_player_from_db]
            if model_class == CharacterDBModel: # Use CharacterDBModel
                if guild_id == guild_id_str: return [mock_char_from_db_sqla]
            return []
        guild_id_str = guild_id # For use in side_effect

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context):
            with patch('bot.database.crud_utils.get_entities', side_effect=mock_get_entities_fixed) as mock_crud_get_entities:
                await self.char_manager.load_state(guild_id)

        self.assertEqual(mock_crud_get_entities.call_count, 2)
        self.assertIn(guild_id, self.char_manager._characters)
        self.assertEqual(len(self.char_manager._characters[guild_id]), 1)
        self.assertEqual(self.char_manager._characters[guild_id][char1_id_db].name, "CharFromDB")
        self.assertIn(guild_id, self.char_manager._discord_to_player_map)
        self.assertEqual(self.char_manager._discord_to_player_map[guild_id][123], player1_id) # Assuming discord_id 123 for char1

    # Placeholder for other tests like JSON parsing errors, no characters in DB, etc.
    # They would need more specific mocking of crud_utils.get_entities or session.execute directly
    # if CharacterManager uses session.execute for loading.

if __name__ == '__main__':
    unittest.main()
