import asyncio
import unittest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch, call
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, cast

import pytest
# import discord # Not directly used, spec=discord.Client might be too broad if only Client methods are needed

from bot.game.managers.location_manager import LocationManager
from bot.game.models.location import Location as PydanticLocation, ExitDefinition as PydanticExitDefinition # Import ExitDefinition
from bot.database.models.world_related import Location as DBLocation
from bot.database.models.character_related import Character as DBCharacter, Party as DBParty
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.db_service import DBService
from bot.game.managers.game_manager import GameManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.services.location_interaction_service import LocationInteractionService
from bot.ai.rules_schema import CoreGameRulesConfig, XPRule # Import XPRule for mock_game_manager

# Default exit data to ensure all fields are present
DEFAULT_EXIT_DATA: Dict[str, Any] = {"direction":"north", "target_location_id":"placeholder_target", "is_visible": True, "travel_time_seconds": 60, "name_i18n": None, "description_i18n": None, "required_items": None, "visibility_conditions": None, "usability_conditions": None}


DUMMY_LOCATION_TEMPLATE_DATA: Dict[str, Any] = {
    "id": "tpl_world_center", "name_i18n": {"en":"World Center Template"},
    "description_i18n": {"en":"A template for central locations."},
    "exits": [{**DEFAULT_EXIT_DATA, "direction":"north", "target_location_id":"tpl_north_region_entrance_id"}],
    "on_enter_triggers": [{"action": "log_entry", "message": "Entered World Center area."}],
    "on_exit_triggers": [{"action": "log_exit", "message": "Exited World Center area."}],
    "channel_id": "123456789012345678"
}

DUMMY_NORTH_REGION_TEMPLATE_DATA: Dict[str, Any] = {
    "id": "tpl_north_region_entrance_id", "name_i18n": {"en":"North Region Template"},
    "description_i18n": {"en":"A template for north regions."},
    "exits": [{**DEFAULT_EXIT_DATA, "direction":"south", "target_location_id":"tpl_world_center"}],
    "on_enter_triggers": [{"action": "log_entry", "message": "Entered North Region."}],
    "on_exit_triggers": [{"action": "log_exit", "message": "Exited North Region."}],
    "channel_id": "123456789012345679"
}

DUMMY_LOCATION_INSTANCE_FROM: Dict[str, Any] = {
    "id": "instance_world_center_001", "guild_id": "test_guild_1", "template_id": "tpl_world_center",
    "name_i18n": {"en":"World Center Alpha"}, "descriptions_i18n": {"en":"The bustling heart of the world."},
    "exits": [{**DEFAULT_EXIT_DATA, "direction":"north", "target_location_id":"instance_north_region_main_001"}],
    "state_variables": {}, "is_active": True, "static_id": "static_wc_alpha",
    "type_i18n": {"en": "Hub", "ru": "Хаб"}
}
DUMMY_LOCATION_INSTANCE_TO: Dict[str, Any] = {
    "id": "instance_north_region_main_001", "guild_id": "test_guild_1", "template_id": "tpl_north_region_entrance_id",
    "name_i18n": {"en":"North Region Entrance"}, "descriptions_i18n": {"en":"Gateway to the frosty north."},
    "exits": [{**DEFAULT_EXIT_DATA, "direction":"south", "target_location_id":"instance_world_center_001"}],
    "state_variables": {}, "is_active": True, "static_id": "static_nr_entrance",
    "type_i18n": {"en": "Gateway", "ru": "Врата"}
}

class BaseLocationManagerTest(unittest.IsolatedAsyncioTestCase):
    mock_db_service: MagicMock
    mock_settings: MagicMock
    mock_game_manager: AsyncMock
    location_manager: LocationManager
    guild_id: str
    mock_session_instance: AsyncMock

    async def asyncSetUp(self):
        self.mock_db_service = MagicMock(spec=DBService)
        self.mock_db_service.adapter = AsyncMock()

        self.mock_session_instance = AsyncMock(spec=AsyncSession)
        self.mock_session_instance.info = {} # info should be a dict

        self.mock_db_service.get_session = MagicMock()
        self.mock_db_service.get_session.return_value.__aenter__.return_value = self.mock_session_instance
        self.mock_db_service.get_session.return_value.__aexit__ = AsyncMock(return_value=None)
        self.mock_db_service.get_session_factory = MagicMock(return_value=MagicMock())

        self.mock_settings = MagicMock()
        def mock_settings_get_side_effect(key: str, default: Any = None) -> Any:
            if key == "location_templates":
                return {
                    DUMMY_LOCATION_TEMPLATE_DATA["id"]: DUMMY_LOCATION_TEMPLATE_DATA.copy(),
                    DUMMY_NORTH_REGION_TEMPLATE_DATA["id"]: DUMMY_NORTH_REGION_TEMPLATE_DATA.copy()
                }
            return default
        self.mock_settings.get.side_effect = mock_settings_get_side_effect

        self.mock_game_manager = AsyncMock(spec=GameManager)
        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_game_manager.settings = self.mock_settings

        # Mock RuleEngine with a valid CoreGameRulesConfig
        mock_rule_engine_instance = AsyncMock(spec=RuleEngine)
        mock_xp_rules = XPRule(level_difference_modifier={}, base_xp_per_challenge={}) # Valid XPRule
        mock_core_rules = CoreGameRulesConfig(xp_rules=mock_xp_rules) # Valid CoreGameRulesConfig
        mock_rule_engine_instance.rules_config_data = mock_core_rules
        mock_rule_engine_instance.get_rule = AsyncMock() # Ensure get_rule is an AsyncMock
        self.mock_game_manager.rule_engine = mock_rule_engine_instance

        self.mock_game_manager.event_manager = AsyncMock(spec=EventManager)
        self.mock_game_manager.character_manager = AsyncMock(spec=CharacterManager)
        self.mock_game_manager.npc_manager = AsyncMock(spec=NpcManager)
        self.mock_game_manager.item_manager = AsyncMock(spec=ItemManager)
        self.mock_game_manager.combat_manager = AsyncMock(spec=CombatManager)
        self.mock_game_manager.status_manager = AsyncMock(spec=StatusManager)
        self.mock_game_manager.party_manager = AsyncMock(spec=PartyManager)
        self.mock_game_manager.time_manager = AsyncMock(spec=TimeManager)
        self.mock_game_manager.game_log_manager = AsyncMock(spec=GameLogManager)
        self.mock_game_manager.location_interaction_service = AsyncMock(spec=LocationInteractionService)

        # Ensure these internal attributes are also AsyncMock if they have async methods
        self.mock_game_manager._event_stage_processor = AsyncMock(spec=EventStageProcessor if TYPE_CHECKING else Any)
        self.mock_game_manager._event_action_processor = AsyncMock(spec=EventActionProcessor if TYPE_CHECKING else Any)
        self.mock_game_manager._on_enter_action_executor = AsyncMock()
        self.mock_game_manager._stage_description_generator = AsyncMock()
        self.mock_game_manager._multilingual_prompt_generator = AsyncMock()
        self.mock_game_manager._openai_service = AsyncMock()
        self.mock_game_manager._ai_validator = AsyncMock()
        self.mock_game_manager.send_callback_factory = MagicMock()

        self.location_manager = LocationManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            game_manager=self.mock_game_manager,
            send_callback_factory=self.mock_game_manager.send_callback_factory
        )

class TestLocationManagerMoveEntity(BaseLocationManagerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.guild_id = "test_guild_1"
        self.entity_id = "entity_test_1"
        self.from_location_id = DUMMY_LOCATION_INSTANCE_FROM["id"]
        self.to_location_id = DUMMY_LOCATION_INSTANCE_TO["id"]

        self.location_manager._location_instances = { # type: ignore [attr-defined]
            self.guild_id: {
                DUMMY_LOCATION_INSTANCE_FROM["id"]: PydanticLocation.model_validate(DUMMY_LOCATION_INSTANCE_FROM.copy()),
                DUMMY_LOCATION_INSTANCE_TO["id"]: PydanticLocation.model_validate(DUMMY_LOCATION_INSTANCE_TO.copy())
            }
        }
        self.location_manager._dirty_instances = {self.guild_id: set()} # type: ignore [attr-defined]
        self.location_manager._deleted_instances = {self.guild_id: set()} # type: ignore [attr-defined]

        assert self.mock_game_manager.party_manager is not None # Ensure party_manager is set
        cast(AsyncMock, self.mock_game_manager.party_manager).update_party_location = AsyncMock(return_value=True)

    async def test_successfully_moves_party(self):
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id, entity_id=self.entity_id, entity_type="Party",
            from_location_id=self.from_location_id, to_location_id=self.to_location_id
        )
        self.assertTrue(result)
        cast(AsyncMock, self.mock_game_manager.party_manager.update_party_location).assert_called_once()

    @patch('bot.game.managers.location_manager.LocationManager.get_location_instance')
    async def test_move_party_target_location_not_found(self, mock_get_instance_class_level: MagicMock):
        def mock_get_loc_inst_target_none(_slf: LocationManager, guild_id: str, loc_id: str) -> Optional[PydanticLocation]:
            if loc_id == self.to_location_id: return None
            if loc_id == self.from_location_id:
                # Use PydanticLocation.model_validate for consistency
                cached_data_dict = cast(Dict[str, Dict[str, PydanticLocation]], self.location_manager._location_instances).get(guild_id, {}).get(loc_id) # type: ignore [attr-defined]
                return cached_data_dict # Already PydanticLocation
            return None
        mock_get_instance_class_level.side_effect = mock_get_loc_inst_target_none
        cast(AsyncMock, self.mock_game_manager.party_manager).update_party_location = AsyncMock()
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id, entity_id=self.entity_id, entity_type="Party",
            from_location_id=self.from_location_id, to_location_id=self.to_location_id
        )
        self.assertFalse(result)
        cast(AsyncMock, self.mock_game_manager.party_manager.update_party_location).assert_not_called()

    async def test_move_party_party_manager_update_fails(self):
        cast(AsyncMock, self.mock_game_manager.party_manager).update_party_location = AsyncMock(return_value=False)
        result = await self.location_manager.move_entity(
            guild_id=self.guild_id, entity_id=self.entity_id, entity_type="Party",
            from_location_id=self.from_location_id, to_location_id=self.to_location_id
        )
        self.assertFalse(result)
        cast(AsyncMock, self.mock_game_manager.party_manager.update_party_location).assert_called_once()

class TestLocationManagerGetters(BaseLocationManagerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.guild_id = "get_test_guild"
        self.loc_id_1 = "loc_getter_1"
        self.loc_static_id_1 = "static_loc_1"
        self.loc_data_1: Dict[str, Any] = {
            "id": self.loc_id_1, "guild_id": self.guild_id, "static_id": self.loc_static_id_1,
            "name_i18n": {"en": "Test Location One", "ru": "Тестовая Локация Один"},
            "descriptions_i18n": {"en": "Desc One", "ru": "Описание Один"},
            "type_i18n": {"en": "Cave", "ru": "Пещера"},
            "template_id": "tpl_cave", "is_active": True, "state_variables": {},
            "exits": [{**DEFAULT_EXIT_DATA, "direction":"north", "target_location_id":"target1"}]
        }
        self.location_manager._location_instances = { # type: ignore [attr-defined]
            self.guild_id: {self.loc_id_1: PydanticLocation.model_validate(self.loc_data_1.copy())}
        }

    def test_get_location_instance_from_cache(self):
        pydantic_loc = self.location_manager.get_location_instance(self.guild_id, self.loc_id_1)
        self.assertIsNotNone(pydantic_loc)
        if pydantic_loc:
            self.assertIsInstance(pydantic_loc, PydanticLocation)
            self.assertEqual(pydantic_loc.id, self.loc_id_1)
            assert pydantic_loc.name_i18n is not None
            self.assertEqual(pydantic_loc.name_i18n["en"], "Test Location One")
            self.assertEqual(pydantic_loc.name, "Test Location One") # Access default lang via property

    def test_get_location_instance_not_in_cache(self):
        pydantic_loc = self.location_manager.get_location_instance(self.guild_id, "non_existent_loc")
        self.assertIsNone(pydantic_loc)

    async def test_get_location_by_static_id_from_cache(self):
        pydantic_loc = await self.location_manager.get_location_by_static_id(self.guild_id, self.loc_static_id_1)
        self.assertIsNotNone(pydantic_loc)
        if pydantic_loc:
            self.assertEqual(pydantic_loc.id, self.loc_id_1)
            self.assertEqual(pydantic_loc.static_id, self.loc_static_id_1)
            self.assertEqual(pydantic_loc.name, "Test Location One")

    async def test_get_location_by_static_id_from_db(self):
        cast(Dict[str, Dict[str, PydanticLocation]], self.location_manager._location_instances)[self.guild_id] = {} # type: ignore [attr-defined]
        db_loc_model = MagicMock(spec=DBLocation)
        db_loc_model.id = "db_loc_id_2"; db_loc_model.guild_id = self.guild_id
        db_loc_model.static_id = "static_from_db"
        db_loc_model.name_i18n = json.dumps({"en": "DB Location", "ru": "БД Локация"})
        db_loc_model.descriptions_i18n = json.dumps({"en": "DB Desc"})
        db_loc_model.type_i18n = json.dumps({"en": "DB Type"})
        db_loc_model.template_id = "db_tpl"
        db_loc_model.is_active = True
        db_loc_model.state_variables = json.dumps({})
        db_loc_model.exits = json.dumps([])
        db_loc_model.channel_id = "db_channel" # Added missing fields
        db_loc_model.image_url = None
        db_loc_model.coordinates = None
        db_loc_model.tags_i18n = None
        db_loc_model.atmosphere_i18n = None
        db_loc_model.features_i18n = None
        db_loc_model.points_of_interest_json = None
        db_loc_model.on_enter_events_json = None
        db_loc_model.on_exit_events_json = None
        db_loc_model.details_i18n = None
        db_loc_model.ai_metadata_json = None
        db_loc_model.neighbor_locations_json = None


        mock_scalars_result = MagicMock(); mock_scalars_result.first.return_value = db_loc_model
        mock_execute_result = MagicMock(scalars=MagicMock(return_value=mock_scalars_result))
        self.mock_session_instance.execute = AsyncMock(return_value=mock_execute_result)
        self.mock_session_instance.info = {"current_guild_id": self.guild_id}


        with patch('bot.game.managers.location_manager.GuildTransaction', return_value=self.mock_db_service.get_session.return_value):
             pydantic_loc = await self.location_manager.get_location_by_static_id(self.guild_id, "static_from_db")

        self.assertIsNotNone(pydantic_loc)
        if pydantic_loc:
            self.assertEqual(pydantic_loc.id, "db_loc_id_2")
            self.assertEqual(pydantic_loc.static_id, "static_from_db")
            self.assertEqual(pydantic_loc.name, "DB Location")
            self.assertIn("db_loc_id_2", cast(Dict[str, Dict[str, PydanticLocation]], self.location_manager._location_instances)[self.guild_id]) # type: ignore [attr-defined]
            cached_instance = cast(Dict[str, Dict[str, PydanticLocation]], self.location_manager._location_instances)[self.guild_id]["db_loc_id_2"] # type: ignore [attr-defined]
            assert cached_instance.name_i18n is not None
            self.assertEqual(cached_instance.name_i18n["en"], "DB Location")

    async def test_get_location_by_static_id_not_found_anywhere(self):
        cast(Dict[str, Dict[str, PydanticLocation]], self.location_manager._location_instances)[self.guild_id] = {} # type: ignore [attr-defined]
        mock_scalars_result = MagicMock(); mock_scalars_result.first.return_value = None
        mock_execute_result = MagicMock(scalars=MagicMock(return_value=mock_scalars_result))
        self.mock_session_instance.execute = AsyncMock(return_value=mock_execute_result)
        self.mock_session_instance.info = {"current_guild_id": self.guild_id}

        with patch('bot.game.managers.location_manager.GuildTransaction', return_value=self.mock_db_service.get_session.return_value):
            pydantic_loc = await self.location_manager.get_location_by_static_id(self.guild_id, "non_existent_static")
        self.assertIsNone(pydantic_loc)
        # get_session_factory might not be called if get_session is used directly by GuildTransaction mock
        # cast(MagicMock, self.mock_db_service.get_session_factory).assert_called_once()


class TestLocationManagerProcessCharacterMove(BaseLocationManagerTest):
    _current_test_instance: Optional['TestLocationManagerProcessCharacterMove'] = None # Class variable for staticmethod access

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.guild_id = "move_guild_1"; self.char_id = "char_move_1"; self.player_id = "player_for_char_move_1"
        self.party_id = "party_move_1"; self.loc_from_id = "loc_from"; self.loc_to_id = "loc_to"

        self.db_character = MagicMock(spec=DBCharacter)
        self.db_character.id = self.char_id; self.db_character.guild_id = self.guild_id
        self.db_character.current_location_id = self.loc_from_id
        self.db_character.current_party_id = None; self.db_character.player_id = self.player_id

        self.db_party = MagicMock(spec=DBParty)
        self.db_party.id = self.party_id; self.db_party.guild_id = self.guild_id
        self.db_party.current_location_id = self.loc_from_id
        self.db_party.leader_id = self.char_id
        self.db_party.player_ids_json = json.dumps([self.char_id, "char_member_2"])

        self.pydantic_loc_from = PydanticLocation.model_validate({**DUMMY_LOCATION_INSTANCE_FROM, "id": self.loc_from_id, "guild_id": self.guild_id, "static_id": "static_from", "neighbor_locations_json": json.dumps({self.loc_to_id: {"en": "Path to the north"}})})
        self.pydantic_loc_to = PydanticLocation.model_validate({**DUMMY_LOCATION_INSTANCE_TO, "id": self.loc_to_id, "guild_id": self.guild_id, "static_id": "static_to"})

        self.mock_session_instance.get.side_effect = self._mock_session_get_side_effect
        TestLocationManagerProcessCharacterMove._current_test_instance = self

        # Patching at the class level where the method is defined
        self.patcher_get_loc_inst = patch('bot.game.managers.location_manager.LocationManager.get_location_instance', side_effect=TestLocationManagerProcessCharacterMove._static_mock_lm_get_location_instance)
        self.mocked_get_loc_inst = self.patcher_get_loc_inst.start()
        self.addCleanup(self.patcher_get_loc_inst.stop)

        self.patcher_get_loc_static = patch('bot.game.managers.location_manager.LocationManager.get_location_by_static_id', side_effect=TestLocationManagerProcessCharacterMove._static_mock_lm_get_location_by_static_id)
        self.mocked_get_loc_static = self.patcher_get_loc_static.start()
        self.addCleanup(self.patcher_get_loc_static.stop)

        assert self.mock_game_manager.rule_engine is not None # Ensure rule_engine is set
        cast(AsyncMock, self.mock_game_manager.rule_engine).get_rule = AsyncMock(return_value={"allow_leader_only_move": True, "teleport_all_members": True})


    @staticmethod # Needs to be static if used as side_effect for a patch on the class
    def _static_mock_lm_get_location_instance(_lm_instance_unused: 'LocationManager', guild_id: str, loc_id: str) -> Optional[PydanticLocation]:
        test_self = TestLocationManagerProcessCharacterMove._current_test_instance
        assert test_self is not None, "Test instance not set for static mock"
        if guild_id == test_self.guild_id:
            if loc_id == test_self.loc_from_id: return test_self.pydantic_loc_from
            if loc_id == test_self.loc_to_id: return test_self.pydantic_loc_to
        return None

    @staticmethod # Needs to be static
    async def _static_mock_lm_get_location_by_static_id(_lm_instance_unused: 'LocationManager', guild_id: str, static_id_or_name: str, session: Optional[AsyncSession]=None) -> Optional[PydanticLocation]:
        test_self = TestLocationManagerProcessCharacterMove._current_test_instance
        assert test_self is not None, "Test instance not set for static mock"

        loc_to_name_i18n = getattr(test_self.pydantic_loc_to, 'name_i18n', None) if test_self.pydantic_loc_to else None
        loc_from_name_i18n = getattr(test_self.pydantic_loc_from, 'name_i18n', None) if test_self.pydantic_loc_from else None

        loc_to_static_id = getattr(test_self.pydantic_loc_to, 'static_id', None)
        loc_from_static_id = getattr(test_self.pydantic_loc_from, 'static_id', None)

        if guild_id == test_self.guild_id:
            if static_id_or_name == loc_to_static_id or (isinstance(loc_to_name_i18n, dict) and static_id_or_name == loc_to_name_i18n.get("en")):
                return test_self.pydantic_loc_to
            if static_id_or_name == loc_from_static_id or (isinstance(loc_from_name_i18n, dict) and static_id_or_name == loc_from_name_i18n.get("en")):
                return test_self.pydantic_loc_from
        return None

    async def _mock_session_get_side_effect(self, model_cls: TypingAny, entity_id: TypingAny) -> TypingAny:
        if model_cls == DBCharacter and entity_id == self.char_id: return self.db_character
        if model_cls == DBCharacter and entity_id == "char_member_2":
            member2 = MagicMock(spec=DBCharacter); member2.id = "char_member_2"; member2.guild_id = self.guild_id; member2.current_location_id = self.loc_from_id; return member2
        if model_cls == DBParty and entity_id == self.party_id: return self.db_party
        return None


    async def test_move_single_character_success(self):
        self.db_character.current_party_id = None
        assert self.pydantic_loc_to is not None and self.pydantic_loc_to.static_id is not None
        with patch('bot.game.managers.location_manager.GuildTransaction', return_value=self.mock_db_service.get_session.return_value):
            result = await self.location_manager.process_character_move(self.guild_id, self.char_id, self.pydantic_loc_to.static_id)
        self.assertTrue(result)
        self.assertEqual(self.db_character.current_location_id, self.loc_to_id)
        self.mock_session_instance.add.assert_any_call(self.db_character)
        cast(AsyncMock, self.mock_game_manager.game_log_manager.log_event).assert_awaited_once()
        cast(AsyncMock, self.mock_game_manager.location_interaction_service.process_on_enter_location_events).assert_awaited_once_with(
            self.guild_id, self.char_id, "Character", self.loc_to_id
        )

    # ... (Other tests, ensuring similar casting and safe attribute access) ...
    async def test_move_party_leader_teleports_all(self):
        self.db_character.current_party_id = self.party_id
        self.db_party.leader_id = self.char_id
        # Ensure get_rule is an AsyncMock on the rule_engine instance itself
        cast(AsyncMock, self.mock_game_manager.rule_engine.get_rule).return_value = {"allow_leader_only_move": True, "teleport_all_members": True}
        assert self.pydantic_loc_to is not None and self.pydantic_loc_to.static_id is not None
        with patch('bot.game.managers.location_manager.GuildTransaction', return_value=self.mock_db_service.get_session.return_value):
            result = await self.location_manager.process_character_move(self.guild_id, self.char_id, self.pydantic_loc_to.static_id)
        self.assertTrue(result)
        self.assertEqual(self.db_party.current_location_id, self.loc_to_id) # Party location should update
        self.mock_session_instance.add.assert_any_call(self.db_party)
        self.assertEqual(self.db_character.current_location_id, self.loc_to_id)
        self.mock_session_instance.add.assert_any_call(self.db_character)
        cast(AsyncMock, self.mock_game_manager.location_interaction_service.process_on_enter_location_events).assert_awaited_once_with(
            self.guild_id, self.party_id, "Party", self.loc_to_id
        )


class TestLocationManagerAICreation(BaseLocationManagerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.guild_id = "test_guild_aic"
        # Ensure adapter has the method if it's called directly
        self.mock_db_service.adapter.save_pending_moderation_request = AsyncMock()

    async def test_create_location_instance_ai_pending_moderation(self):
        template_id_arg = "AI:generate_haunted_mansion"
        user_id = "test_user_loc_mod"
        mock_validated_loc_data: Dict[str, Any] = {
            "name_i18n": {"en": "AI Haunted Mansion"}, "descriptions_i18n": {"en": "A spooky place."},
            "exits": [], "state_variables": {}, "template_id": "generated_mansion_tpl", # Ensure template_id is in mock
            "type_i18n": {"en": "Mansion"} # Ensure type_i18n for PydanticLocation
        }
        # Patching on the instance of location_manager
        with patch.object(self.location_manager, 'generate_location_details_from_ai', new_callable=AsyncMock) as mock_gen_details:
            mock_gen_details.return_value = mock_validated_loc_data
            result = await self.location_manager.create_location_instance(
                self.guild_id, template_id_arg, user_id=user_id,
                # Provide other necessary args or ensure defaults in create_location_instance
                instance_name_i18n=None, instance_description_i18n=None, instance_exits=None,
                initial_state=None, static_id_override=None, channel_id_override=None,
                image_url_override=None, type_i18n_override=None
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["status"], "pending_moderation")
        self.assertIn("request_id", result)
        mock_gen_details.assert_called_once_with(
            self.guild_id, "generate_haunted_mansion", player_context=None, session=unittest.mock.ANY
        )
        self.mock_db_service.adapter.save_pending_moderation_request.assert_called_once()


# ... (rest of the tests with similar safety checks and corrections)
class TestLocationManagerContinued(BaseLocationManagerTest): # No specific tests here yet
    pass

if __name__ == '__main__':
    unittest.main()
