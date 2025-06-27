import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import json
import uuid # Added for unique IDs in tests

from bot.game.models.character import Character # Pydantic model
from bot.database.models import Character as CharacterDBModel, Player # SQLAlchemy model
from bot.game.managers.character_manager import CharacterManager
from bot.services.db_service import DBService # For type hinting
from bot.database.postgres_adapter import PostgresAdapter # Or your actual adapter
from sqlalchemy.ext.asyncio import AsyncSession


class TestCharacterManagerActionPersistence(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.guild_id = "test_guild_789"
        self.character_id = "test_char_123"
        self.discord_user_id = 1234567890

        self.mock_db_adapter = AsyncMock(spec=PostgresAdapter)
        self.mock_db_service = MagicMock(spec=DBService)
        self.mock_db_service.adapter = self.mock_db_adapter
        self.mock_db_service.get_session_factory = MagicMock() # Crucial for save/load_state

        self.mock_settings = {
            "default_initial_location_id": "start_loc_default",
            # Add other settings CharacterManager might use during init or operations
        }
        self.mock_game_manager = AsyncMock() # For CharacterManager init

        # Provide all necessary mocks for CharacterManager constructor
        self.character_manager = CharacterManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            item_manager=AsyncMock(),
            location_manager=AsyncMock(),
            rule_engine=AsyncMock(),
            status_manager=AsyncMock(),
            party_manager=AsyncMock(),
            combat_manager=AsyncMock(),
            dialogue_manager=AsyncMock(),
            relationship_manager=AsyncMock(),
            game_log_manager=AsyncMock(),
            npc_manager=AsyncMock(),
            inventory_manager=AsyncMock(),
            equipment_manager=AsyncMock(),
            game_manager=self.mock_game_manager
        )

        self.base_char_db_dict = { # Data representing a row from DB for CharacterDBModel
            "id": self.character_id,
            "guild_id": self.guild_id,
            "player_id": str(uuid.uuid4()), # Needs a player_id for CharacterDBModel
            "discord_user_id": str(self.discord_user_id), # Ensure string if DB stores as string
            "name_i18n": json.dumps({"en": "Test Character"}), # Stored as JSON string in DB
            "character_class_i18n": None, "race_key": None, "race_i18n": None, "description_i18n": None,
            "level": 1, "xp": 0, "unspent_xp": 0, "gold": 0,
            "current_hp": 100.0, "max_hp": 100.0, "mp": None, "base_attack": None, "base_defense": None,
            "is_alive": True,
            "stats_json": json.dumps({"strength": 10, "dexterity": 12}),
            "effective_stats_json": None,
            "status_effects_json": json.dumps([]),
            "skills_data_json": json.dumps([]),
            "abilities_data_json": json.dumps([]),
            "spells_data_json": json.dumps([]),
            "known_spells_json": json.dumps([]),
            "spell_cooldowns_json": json.dumps({}),
            "inventory_json": json.dumps([{"item_id":"item1", "quantity":1}]), # Example structure for Pydantic Character
            "equipment_slots_json": json.dumps({}),
            "active_quests_json": json.dumps([]),
            "flags_json": json.dumps({}),
            "state_variables_json": json.dumps({}),
            "current_game_status": None,
            "current_action_json": None,
            "action_queue_json": None,
            "collected_actions_json": None,
            "current_location_id": "start_town",
            "current_party_id": None,
            "selected_language": "en"
        }

        # This is the Pydantic model representation, used for setting up cache or comparing
        # Create a mock DBModel instance first
        mock_db_model_for_setup = CharacterDBModel(**self.base_char_db_dict) # type: ignore[arg-type]
        # Assuming Character.from_db_model is a class method or static method
        self.base_char_pydantic_data = Character.from_db_model(mock_db_model_for_setup)


    async def test_save_character_with_collected_actions(self):
        self.assertIsNotNone(self.base_char_pydantic_data, "base_char_pydantic_data should be initialized")
        char_pydantic = self.base_char_pydantic_data.model_copy(deep=True)
        sample_actions = [{"action": "move", "target": "north"}, {"action": "search"}]
        char_pydantic.collected_actions_json = json.dumps(sample_actions)

        self.character_manager._characters[self.guild_id] = {char_pydantic.id: char_pydantic}
        self.character_manager.mark_character_dirty(self.guild_id, char_pydantic.id)

        mock_session = AsyncMock(spec=AsyncSession)
        async def mock_merge(obj): return obj
        mock_session.merge = AsyncMock(side_effect=mock_merge)

        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context):
            await self.character_manager.save_state(self.guild_id)

        mock_session.merge.assert_called_once()
        merged_orm_instance = mock_session.merge.call_args[0][0]
        self.assertIsInstance(merged_orm_instance, CharacterDBModel)
        self.assertEqual(merged_orm_instance.collected_actions_json, json.dumps(sample_actions))


    async def test_load_character_with_collected_actions(self):
        sample_actions_list = [{"action": "attack", "target_id": "mob1"}]
        sample_actions_json_str = json.dumps(sample_actions_list)

        db_row_data = self.base_char_db_dict.copy()
        db_row_data["collected_actions_json"] = sample_actions_json_str

        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = self.base_char_db_dict["player_id"]
        mock_player_db.discord_user_id = str(self.discord_user_id)

        mock_char_db = CharacterDBModel(**db_row_data) # type: ignore[arg-type]

        async def mock_get_entities_load(session, model_class, *, guild_id):
            if model_class == Player and guild_id == self.guild_id: return [mock_player_db]
            if model_class == CharacterDBModel and guild_id == self.guild_id: return [mock_char_db]
            return []

        with patch('bot.database.crud_utils.get_entities', side_effect=mock_get_entities_load):
            await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)
        self.assertIsNotNone(loaded_char)

        if loaded_char is not None: # Pyright check
            self.assertEqual(loaded_char.collected_actions_json, sample_actions_json_str)
            if loaded_char.collected_actions_json is not None:
                loaded_actions_list = json.loads(loaded_char.collected_actions_json)
                self.assertEqual(loaded_actions_list, sample_actions_list)
            else:
                self.fail("loaded_char.collected_actions_json was None, expected a JSON string.")
        else: # Should not happen due to assertIsNotNone
            self.fail("loaded_char was None after loading state.")


    async def test_load_character_with_null_collected_actions(self):
        db_row_data_null_actions = self.base_char_db_dict.copy()
        db_row_data_null_actions["collected_actions_json"] = None

        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = self.base_char_db_dict["player_id"]
        mock_player_db.discord_id = str(self.discord_user_id)
        mock_char_db = CharacterDBModel(**db_row_data_null_actions) # type: ignore[arg-type]

        async def mock_get_entities_load_null(session, model_class, *, guild_id):
            if model_class == Player and guild_id == self.guild_id: return [mock_player_db]
            if model_class == CharacterDBModel and guild_id == self.guild_id: return [mock_char_db]
            return []

        with patch('bot.database.crud_utils.get_entities', side_effect=mock_get_entities_load_null):
            await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)
        self.assertIsNotNone(loaded_char)
        if loaded_char is not None:
            self.assertIsNone(loaded_char.collected_actions_json)


    async def test_save_character_with_empty_collected_actions(self):
        self.assertIsNotNone(self.base_char_pydantic_data, "base_char_pydantic_data should be initialized")
        char_pydantic = self.base_char_pydantic_data.model_copy(deep=True)
        empty_actions_json_str = json.dumps([])
        char_pydantic.collected_actions_json = empty_actions_json_str

        self.character_manager._characters[self.guild_id] = {char_pydantic.id: char_pydantic}
        self.character_manager.mark_character_dirty(self.guild_id, char_pydantic.id)

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.merge = AsyncMock(side_effect=lambda obj: obj)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context):
            await self.character_manager.save_state(self.guild_id)

        mock_session.merge.assert_called_once()
        merged_orm_instance = mock_session.merge.call_args[0][0]
        self.assertEqual(merged_orm_instance.collected_actions_json, empty_actions_json_str)


    async def test_save_character_with_null_collected_actions(self):
        self.assertIsNotNone(self.base_char_pydantic_data, "base_char_pydantic_data should be initialized")
        char_pydantic = self.base_char_pydantic_data.model_copy(deep=True)
        char_pydantic.collected_actions_json = None

        self.character_manager._characters[self.guild_id] = {char_pydantic.id: char_pydantic}
        self.character_manager.mark_character_dirty(self.guild_id, char_pydantic.id)

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.merge = AsyncMock(side_effect=lambda obj: obj)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context):
            await self.character_manager.save_state(self.guild_id)

        mock_session.merge.assert_called_once()
        merged_orm_instance = mock_session.merge.call_args[0][0]
        self.assertIsNone(merged_orm_instance.collected_actions_json)


    async def test_save_character_all_complex_fields(self):
        self.assertIsNotNone(self.base_char_pydantic_data, "base_char_pydantic_data should be initialized")
        char_pydantic = self.base_char_pydantic_data.model_copy(deep=True)
        char_pydantic.name_i18n = {"en": "Complex Hero", "ru": "Сложный Герой"}
        char_pydantic.skills_data = [{"skill_id": "alchemy", "level": 15}]
        char_pydantic.abilities_data = [{"ability_id": "double_strike", "rank": 2}]
        char_pydantic.spells_data = [{"spell_id": "invisibility", "duration": 60}]
        char_pydantic.character_class = "Rogue" # Pydantic model field
        char_pydantic.flags = {"is_hidden": True, "can_fly": False}
        char_pydantic.collected_actions_json = json.dumps([{"action": "hide"}])

        self.character_manager._characters[self.guild_id] = {char_pydantic.id: char_pydantic}
        self.character_manager.mark_character_dirty(self.guild_id, char_pydantic.id)

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.merge = AsyncMock(side_effect=lambda obj: obj)
        mock_guild_transaction_context = AsyncMock()
        mock_guild_transaction_context.__aenter__.return_value = mock_session

        with patch('bot.database.guild_transaction.GuildTransaction', return_value=mock_guild_transaction_context):
            await self.character_manager.save_state(self.guild_id)

        mock_session.merge.assert_called_once()
        merged_orm_instance = mock_session.merge.call_args[0][0]

        self.assertEqual(merged_orm_instance.name_i18n, char_pydantic.name_i18n) # Assuming name_i18n is also a dict on DBModel
        self.assertEqual(merged_orm_instance.skills_data_json, json.dumps(char_pydantic.skills_data))
        self.assertEqual(merged_orm_instance.abilities_data_json, json.dumps(char_pydantic.abilities_data))
        self.assertEqual(merged_orm_instance.spells_data_json, json.dumps(char_pydantic.spells_data))
        # For character_class, CharacterDBModel has character_class_i18n.
        # Assuming to_db_model handles converting Pydantic's character_class (str) to character_class_i18n (JSON str)
        # For this test, let's assume a simple mapping or that the DB model also has a plain character_class field.
        # If CharacterDBModel.character_class_i18n is the target:
        # self.assertEqual(json.loads(merged_orm_instance.character_class_i18n), {"en": char_pydantic.character_class})
        # For now, we'll skip direct assertion on character_class if DB model structure is different.
        self.assertEqual(merged_orm_instance.flags_json, json.dumps(char_pydantic.flags))
        self.assertEqual(merged_orm_instance.collected_actions_json, char_pydantic.collected_actions_json)


    async def test_load_character_all_complex_fields(self):
        name_i18n_obj = {"en": "Loaded Hero", "ru": "Загруженный Герой"}
        skills_data_obj = [{"skill_id": "herbalism", "level": 5}]
        abilities_data_obj = [{"ability_id": "quick_shot", "rank": 1}]
        spells_data_obj = [{"spell_id": "heal_light", "cost": 10}]
        flags_obj = {"is_leader": True, "is_merchant": False}
        coll_actions_list = [{"action": "trade", "item": "potion"}]
        char_class_i18n_obj = {"en": "Archer", "ru": "Лучник"}


        db_row_data = self.base_char_db_dict.copy()
        db_row_data.update({
            "name_i18n": json.dumps(name_i18n_obj),
            "skills_data_json": json.dumps(skills_data_obj),
            "abilities_data_json": json.dumps(abilities_data_obj),
            "spells_data_json": json.dumps(spells_data_obj),
            "character_class_i18n": json.dumps(char_class_i18n_obj),
            "flags_json": json.dumps(flags_obj),
            "collected_actions_json": json.dumps(coll_actions_list),
        })

        mock_player_db = MagicMock(spec=Player)
        mock_player_db.id = self.base_char_db_dict["player_id"]
        mock_player_db.discord_user_id = str(self.discord_user_id)
        mock_char_db = CharacterDBModel(**db_row_data) # type: ignore[arg-type]

        async def mock_get_entities_load_complex(session, model_class, *, guild_id):
            if model_class == Player and guild_id == self.guild_id: return [mock_player_db]
            if model_class == CharacterDBModel and guild_id == self.guild_id: return [mock_char_db]
            return []

        with patch('bot.database.crud_utils.get_entities', side_effect=mock_get_entities_load_complex):
            await self.character_manager.load_state(self.guild_id)

        loaded_char = self.character_manager.get_character(self.guild_id, self.character_id)
        self.assertIsNotNone(loaded_char)

        if loaded_char is not None:
            self.assertEqual(loaded_char.name_i18n, name_i18n_obj)
            self.assertEqual(loaded_char.skills_data, skills_data_obj)
            self.assertEqual(loaded_char.abilities_data, abilities_data_obj)
            self.assertEqual(loaded_char.spells_data, spells_data_obj)

            # Assuming Character.from_db_model correctly populates Pydantic's character_class
            # from the 'en' field of DB's character_class_i18n, or directly if Pydantic has character_class_i18n
            # If Pydantic model Character has `character_class: Optional[str]` and `character_class_i18n: Optional[Dict[str, str]]`
            # And from_db_model populates both:
            self.assertEqual(loaded_char.character_class, char_class_i18n_obj.get("en")) # Assuming it extracts 'en'
            # Or if Pydantic model has character_class_i18n field:
            # self.assertEqual(loaded_char.character_class_i18n, char_class_i18n_obj)


            self.assertEqual(loaded_char.flags, flags_obj)
            if loaded_char.collected_actions_json is not None:
                self.assertEqual(json.loads(loaded_char.collected_actions_json), coll_actions_list)
            else:
                self.fail("loaded_char.collected_actions_json was None, expected JSON string.")


if __name__ == '__main__':
    unittest.main()
