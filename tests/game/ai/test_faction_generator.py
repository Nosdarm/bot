import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY
import json
import uuid # For MinimalFaction default ID
from typing import Optional, Dict, Any, List, Tuple # Ensure these are imported

# Modules to test
from bot.game.ai.faction_generator import AIFactionGenerator
from bot.game.managers.faction_manager import FactionManager
from bot.game.managers.npc_manager import NpcManager

# Models
try:
    from bot.game.models.faction import Faction
    from bot.game.models.npc import NPC
except ImportError:
    Faction = Any # type: ignore
    NPC = Any # type: ignore


# Dependencies to be mocked
from bot.services.openai_service import OpenAIService # Import for spec
from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator # Import for spec


# --- Mock Models (Simplified) ---
# Using Pydantic BaseModel for simplified test models
from pydantic import BaseModel, Field as PydanticField # Renamed Field to PydanticField
from typing import Dict as PydanticDict, List as PydanticList, Optional as PydanticOptional, Any as PydanticAny

class MinimalFaction(BaseModel):
    id: str = PydanticField(default_factory=lambda: str(uuid.uuid4()))
    guild_id: str
    name_i18n: PydanticDict[str, str]
    description_i18n: PydanticDict[str, str] = PydanticField(default_factory=dict)
    leader_id: PydanticOptional[str] = None
    alignment: PydanticOptional[str] = None
    member_ids: PydanticList[str] = PydanticField(default_factory=list)
    state_variables: PydanticDict[str, PydanticAny] = PydanticField(default_factory=dict)

    @property
    def name(self): return self.name_i18n.get("en", list(self.name_i18n.values())[0] if self.name_i18n else self.id)

class MinimalNPC(BaseModel):
    id: str = PydanticField(default_factory=lambda: str(uuid.uuid4()))
    name_i18n: PydanticDict[str, str] = PydanticField(default_factory=dict)
    guild_id: str
    template_id: str
    @property
    def name(self): return self.name_i18n.get("en", self.id)

_FactionModel = MinimalFaction
_NPCModel = MinimalNPC


class TestAIFactionGenerator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_openai_service = AsyncMock(spec=OpenAIService)
        self.mock_prompt_generator = MagicMock(spec=MultilingualPromptGenerator)
        self.faction_generator = AIFactionGenerator(
            openai_service=self.mock_openai_service,
            prompt_generator=self.mock_prompt_generator
        )

    async def test_generate_factions_success_parsing_json_block(self):
        guild_setting = "Grimdark Future"
        lang = "en"
        num_factions = 1
        expected_faction_data = [{
            "name_i18n": {"en": "Tech Scavengers"},
            "description_i18n": {"en": "They seek lost technology."},
            "leader_concept": {"name": "Scrap King", "persona": "A cunning cyborg."},
            "goals": ["Find tech", "Survive"],
            "alignment_suggestion": "Chaotic Neutral"
        }]
        llm_response_str = f"Here are the factions:\n```json\n{json.dumps(expected_faction_data)}\n```\nHope this helps!"

        assert isinstance(self.mock_prompt_generator.generate_faction_creation_prompt, MagicMock)
        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys_prompt", "user_prompt")

        assert isinstance(self.mock_openai_service.generate_master_response, AsyncMock)
        self.mock_openai_service.generate_master_response.return_value = llm_response_str

        factions = await self.faction_generator.generate_factions_from_concept(
            guild_setting, None, None, lang, num_factions
        )

        self.assertEqual(len(factions), 1)
        self.assertEqual(factions[0]["name_i18n"]["en"], "Tech Scavengers")
        self.mock_prompt_generator.generate_faction_creation_prompt.assert_called_once_with(
            guild_setting=guild_setting, existing_npcs_summary=None, existing_locations_summary=None,
            lang=lang, num_factions=num_factions
        )
        self.mock_openai_service.generate_master_response.assert_called_once()

    async def test_generate_factions_parsing_direct_json_list(self):
        expected_faction_data = [{"name_i18n": {"en": "Direct JSON Faction"}, "description_i18n": {}}]
        llm_response_str = json.dumps(expected_faction_data)
        assert isinstance(self.mock_prompt_generator.generate_faction_creation_prompt, MagicMock)
        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys", "user")
        assert isinstance(self.mock_openai_service.generate_master_response, AsyncMock)
        self.mock_openai_service.generate_master_response.return_value = llm_response_str

        factions = await self.faction_generator.generate_factions_from_concept("s", None, None, "en", 1)
        self.assertEqual(len(factions), 1)
        self.assertEqual(factions[0]["name_i18n"]["en"], "Direct JSON Faction")

    async def test_generate_factions_empty_or_invalid_response(self):
        assert isinstance(self.mock_prompt_generator.generate_faction_creation_prompt, MagicMock)
        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys", "user")

        assert isinstance(self.mock_openai_service.generate_master_response, AsyncMock)
        self.mock_openai_service.generate_master_response.return_value = ""
        factions_empty = await self.faction_generator.generate_factions_from_concept("s", None, None, "en", 1)
        self.assertEqual(factions_empty, [])

        self.mock_openai_service.generate_master_response.return_value = "Not JSON"
        factions_invalid = await self.faction_generator.generate_factions_from_concept("s", None, None, "en", 1)
        self.assertEqual(factions_invalid, [])

        self.mock_openai_service.generate_master_response.return_value = json.dumps({"not_a": "list"})
        factions_not_list = await self.faction_generator.generate_factions_from_concept("s", None, None, "en", 1)
        self.assertEqual(factions_not_list, [])


class TestFactionManagerAI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # self.mock_db_service = AsyncMock() # Not directly used by FactionManager if game_manager provides all
        self.mock_npc_manager = AsyncMock(spec=NpcManager)
        self.mock_game_manager = MagicMock(spec=FactionManager.get_game_manager_dependency_type()) # Use type hint from FactionManager
        self.faction_manager = FactionManager(game_manager=self.mock_game_manager)

    async def test_create_faction_from_ai_success_no_leader(self):
        guild_id = "g1"
        lang = "en"
        faction_concept = {
            "name_i18n": {"en": "The Wanderers"},
            "description_i18n": {"en": "Nomads of the wasteland."},
            "goals": ["Explore", "Trade"],
            "alignment_suggestion": "True Neutral"
        }

        # Ensure mock_npc_manager.create_npc_from_ai_concept is an AsyncMock
        self.mock_npc_manager.create_npc_from_ai_concept = AsyncMock(return_value=None)


        created_faction_id = str(uuid.uuid4())
        expected_faction = _FactionModel(
            id=created_faction_id, guild_id=guild_id,
            name_i18n=faction_concept["name_i18n"],
            description_i18n=faction_concept["description_i18n"],
            alignment=faction_concept["alignment_suggestion"],
            state_variables={"goals": faction_concept["goals"]}
        )

        with patch.object(self.faction_manager, 'create_faction', new_callable=AsyncMock) as mock_internal_create:
            mock_internal_create.return_value = expected_faction

            faction_result = await self.faction_manager.create_faction_from_ai( # Renamed variable
                guild_id, faction_concept, lang, self.mock_npc_manager
            )

            self.assertIsNotNone(faction_result)
            if faction_result:
                self.assertEqual(faction_result.name_i18n["en"], "The Wanderers")
                self.assertIsNone(faction_result.leader_id)
                self.assertIn("Explore", faction_result.state_variables.get("goals", []))

            mock_internal_create.assert_called_once()
            # Check call_args on the mock object itself if it's not a simple function
            call_args_dict = mock_internal_create.call_args[1] if mock_internal_create.call_args else {}
            self.assertEqual(call_args_dict.get('name_i18n', {}).get('en'), "The Wanderers")
            self.assertIsNone(call_args_dict.get('leader_id'))

        self.mock_npc_manager.create_npc_from_ai_concept.assert_not_called()


    async def test_create_faction_from_ai_with_leader_concept_npc_creation_placeholder(self):
        guild_id = "g1"
        lang = "ru"
        faction_concept = {
            "name_i18n": {"ru": "Клан Стали", "en": "Steel Clan"},
            "description_i18n": {"ru": "Кузнецы и воины.", "en": "Smiths and warriors."},
            "leader_concept": {"name_i18n": {"ru":"Вождь Гром"}, "persona_i18n": {"ru":"Суровый, но мудрый лидер."}}, # Ensure i18n structure
            "goals": ["Создать лучшее оружие"],
            "alignment_suggestion": "Lawful Neutral"
        }

        # Ensure mock_npc_manager.create_npc_from_ai_concept is an AsyncMock and returns a mock NPC
        mock_leader_npc = _NPCModel(id=str(uuid.uuid4()), guild_id=guild_id, template_id="leader_template", name_i18n={"ru":"Вождь Гром"})
        self.mock_npc_manager.create_npc_from_ai_concept = AsyncMock(return_value=mock_leader_npc)


        created_faction_id = str(uuid.uuid4())
        # Instantiate with all required fields for MinimalFaction
        expected_faction = _FactionModel(id=created_faction_id, guild_id=guild_id, name_i18n=faction_concept["name_i18n"], leader_id=mock_leader_npc.id)


        with patch.object(self.faction_manager, 'create_faction', new_callable=AsyncMock) as mock_internal_create:
            mock_internal_create.return_value = expected_faction

            faction_result = await self.faction_manager.create_faction_from_ai( # Renamed variable
                guild_id, faction_concept, lang, self.mock_npc_manager
            )
            self.assertIsNotNone(faction_result)
            if faction_result:
                 self.assertEqual(faction_result.name_i18n["ru"], "Клан Стали")
                 self.assertEqual(faction_result.leader_id, mock_leader_npc.id) # Should now have leader_id

            mock_internal_create.assert_called_once()
            call_args_faction_dict = mock_internal_create.call_args[1] if mock_internal_create.call_args else {}
            self.assertEqual(call_args_faction_dict.get('leader_id'), mock_leader_npc.id)

        self.mock_npc_manager.create_npc_from_ai_concept.assert_called_once_with(
            guild_id=guild_id,
            npc_concept=faction_concept["leader_concept"],
            lang=lang,
            faction_id=created_faction_id, # Faction ID should be passed to NPC creation
            location_id=None # Assuming no location specified for leader in this concept
        )


class TestNpcManagerAI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_db_service = AsyncMock()
        self.mock_item_mgr = AsyncMock()
        self.mock_status_mgr = AsyncMock()
        self.mock_party_mgr = AsyncMock()
        self.mock_char_mgr = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_combat_mgr = AsyncMock()
        self.mock_dialogue_mgr = AsyncMock()
        self.mock_loc_mgr = AsyncMock()
        self.mock_game_log_mgr = AsyncMock()
        self.mock_mp_prompt_gen = MagicMock(spec=MultilingualPromptGenerator)
        self.mock_openai_svc = AsyncMock(spec=OpenAIService)
        self.mock_ai_validator = MagicMock()
        self.mock_campaign_loader = MagicMock()
        self.mock_notification_svc = AsyncMock()
        self.mock_game_manager_for_npc = AsyncMock(spec=FactionManager.get_game_manager_dependency_type()) # Use a relevant spec


        self.npc_manager = NpcManager(
            db_service=self.mock_db_service,
            settings={},
            item_manager=self.mock_item_mgr,
            status_manager=self.mock_status_mgr,
            party_manager=self.mock_party_mgr,
            character_manager=self.mock_char_mgr,
            rule_engine=self.mock_rule_engine,
            combat_manager=self.mock_combat_mgr,
            dialogue_manager=self.mock_dialogue_mgr,
            location_manager=self.mock_loc_mgr,
            game_log_manager=self.mock_game_log_mgr,
            multilingual_prompt_generator=self.mock_mp_prompt_gen,
            openai_service=self.mock_openai_svc,
            ai_validator=self.mock_ai_validator,
            campaign_loader=self.mock_campaign_loader,
            notification_service=self.mock_notification_svc,
            game_manager=self.mock_game_manager_for_npc
        )

        # Mock the create_npc method which is called by create_npc_from_ai_concept
        # We are testing create_npc_from_ai_concept's logic, so we mock its dependency.
        self.npc_manager.create_npc = AsyncMock()
        self.npc_manager.get_npc = AsyncMock()


    async def test_create_npc_from_ai_concept_success(self):
        guild_id = "g1"
        lang = "en"
        npc_concept = {
            "name_i18n": {"en": "Guard Captain"},
            "description_i18n": {"en": "Stern and watchful."},
            "persona_i18n": {"en": "Always vigilant."},
            "role": "Captain"
        }

        expected_npc_id = "npc_ai_123"
        # Ensure MinimalNPC is used here for consistency
        created_npc_obj = _NPCModel(id=expected_npc_id, guild_id=guild_id, template_id="generic_humanoid_ai", name_i18n={"en":"Guard Captain"})

        assert isinstance(self.npc_manager.create_npc, AsyncMock)
        self.npc_manager.create_npc.return_value = expected_npc_id

        assert isinstance(self.npc_manager.get_npc, AsyncMock)
        self.npc_manager.get_npc.return_value = created_npc_obj

        npc_result = await self.npc_manager.create_npc_from_ai_concept( # Renamed variable
            guild_id, npc_concept, lang, location_id="loc1"
        )

        self.assertIsNotNone(npc_result)
        if npc_result:
            self.assertEqual(npc_result.id, expected_npc_id)
            # Ensure name_i18n is a dict before accessing
            name_i18n_val = getattr(npc_result, 'name_i18n', {})
            self.assertEqual(name_i18n_val.get("en"), "Guard Captain")


        self.npc_manager.create_npc.assert_called_once()
        call_args_dict = self.npc_manager.create_npc.call_args[1] if self.npc_manager.create_npc.call_args else {}
        self.assertEqual(call_args_dict.get('guild_id'), guild_id)
        self.assertEqual(call_args_dict.get('npc_template_id'), "generic_humanoid_ai")
        self.assertEqual(call_args_dict.get('location_id'), "loc1")
        self.assertEqual(call_args_dict.get('name_i18n_override',{}).get('en'), "Guard Captain")
        self.assertEqual(call_args_dict.get('role_override'), "Captain")

        self.npc_manager.get_npc.assert_called_once_with(guild_id, expected_npc_id)

    async def test_create_npc_from_ai_concept_create_npc_fails_returns_none(self):
        guild_id = "g1"; lang = "en"; npc_concept = {"name_i18n": {"en":"Fail NPC"}}
        assert isinstance(self.npc_manager.create_npc, AsyncMock)
        self.npc_manager.create_npc.return_value = None

        npc_result = await self.npc_manager.create_npc_from_ai_concept(guild_id, npc_concept, lang) # Renamed
        self.assertIsNone(npc_result)

    async def test_create_npc_from_ai_concept_create_npc_returns_moderation_dict(self):
        guild_id = "g1"; lang = "en"; npc_concept = {"name_i18n": {"en":"Mod NPC"}}
        assert isinstance(self.npc_manager.create_npc, AsyncMock)
        self.npc_manager.create_npc.return_value = {"moderation_needed": True}

        npc_result = await self.npc_manager.create_npc_from_ai_concept(guild_id, npc_concept, lang) # Renamed
        self.assertIsNone(npc)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
