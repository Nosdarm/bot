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
# from bot.services.openai_service import OpenAIService
# from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
# from bot.services.db_service import DBService


# --- Mock Models (Simplified) ---
_FactionModel = Faction
_NPCModel = NPC

# Check if the imported models are placeholders (Any) or if they are actual classes
# that might be too complex for easy instantiation in tests.
if not hasattr(Faction, 'model_fields') and not hasattr(Faction, '__fields__'): # Pydantic v2 and v1 check
    # print("Using fallback MinimalFaction for testing.")
    from pydantic import BaseModel, Field
    from typing import Dict as PydanticDict, List as PydanticList, Optional as PydanticOptional, Any as PydanticAny

    class MinimalFaction(BaseModel):
        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        guild_id: str
        name_i18n: PydanticDict[str, str]
        description_i18n: PydanticDict[str, str] = Field(default_factory=dict)
        leader_id: PydanticOptional[str] = None
        alignment: PydanticOptional[str] = None
        member_ids: PydanticList[str] = Field(default_factory=list)
        state_variables: PydanticDict[str, PydanticAny] = Field(default_factory=dict)

        @property
        def name(self): return self.name_i18n.get("en", list(self.name_i18n.values())[0] if self.name_i18n else self.id)
    _FactionModel = MinimalFaction # type: ignore

if not hasattr(NPC, 'model_fields') and not hasattr(NPC, '__fields__'):
    # print("Using fallback MinimalNPC for testing.")
    from pydantic import BaseModel, Field
    from typing import Dict as PydanticDict, List as PydanticList, Optional as PydanticOptional, Any as PydanticAny
    class MinimalNPC(BaseModel):
        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        name_i18n: PydanticDict[str, str] = Field(default_factory=dict)
        guild_id: str
        template_id: str
        # Add other fields FactionManager/NpcManager might interact with
        @property
        def name(self): return self.name_i18n.get("en", self.id)
    _NPCModel = MinimalNPC # type: ignore


class TestAIFactionGenerator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_openai_service = AsyncMock()
        self.mock_prompt_generator = MagicMock()
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

        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys_prompt", "user_prompt")
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
        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys", "user")
        self.mock_openai_service.generate_master_response.return_value = llm_response_str

        factions = await self.faction_generator.generate_factions_from_concept("s", None, None, "en", 1)
        self.assertEqual(len(factions), 1)
        self.assertEqual(factions[0]["name_i18n"]["en"], "Direct JSON Faction")

    async def test_generate_factions_empty_or_invalid_response(self):
        self.mock_prompt_generator.generate_faction_creation_prompt.return_value = ("sys", "user")
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
        self.mock_db_service = AsyncMock() # Keep for NpcManager if it needs it
        self.mock_npc_manager = AsyncMock(spec=NpcManager)
        # FactionManager init does not take db_service
        self.faction_manager = FactionManager(settings={})

    async def test_create_faction_from_ai_success_no_leader(self):
        guild_id = "g1"
        lang = "en"
        faction_concept = {
            "name_i18n": {"en": "The Wanderers"},
            "description_i18n": {"en": "Nomads of the wasteland."},
            "goals": ["Explore", "Trade"],
            "alignment_suggestion": "True Neutral"
        }

        created_faction_id = str(uuid.uuid4())
        # Use the potentially minimal _FactionModel for instantiation
        expected_faction = _FactionModel(
            id=created_faction_id, guild_id=guild_id,
            name_i18n=faction_concept["name_i18n"],
            description_i18n=faction_concept["description_i18n"],
            alignment=faction_concept["alignment_suggestion"],
            state_variables={"goals": faction_concept["goals"]}
        )

        with patch.object(self.faction_manager, 'create_faction', new_callable=AsyncMock) as mock_internal_create:
            mock_internal_create.return_value = expected_faction

            faction = await self.faction_manager.create_faction_from_ai(
                guild_id, faction_concept, lang, self.mock_npc_manager
            )

            self.assertIsNotNone(faction)
            if faction: # type guard
                self.assertEqual(faction.name_i18n["en"], "The Wanderers")
                self.assertIsNone(faction.leader_id)
                self.assertIn("Explore", faction.state_variables.get("goals", []))

            mock_internal_create.assert_called_once()
            call_args = mock_internal_create.call_args[1]
            self.assertEqual(call_args['name_i18n']['en'], "The Wanderers")
            self.assertIsNone(call_args['leader_id'])

        # This assertion depends on NpcManager not being called due to placeholder
        if hasattr(self.mock_npc_manager, 'create_npc_from_ai_concept'):
            self.mock_npc_manager.create_npc_from_ai_concept.assert_not_called()


    async def test_create_faction_from_ai_with_leader_concept_npc_creation_placeholder(self):
        guild_id = "g1"
        lang = "ru"
        faction_concept = {
            "name_i18n": {"ru": "Клан Стали", "en": "Steel Clan"},
            "description_i18n": {"ru": "Кузнецы и воины.", "en": "Smiths and warriors."},
            "leader_concept": {"name": "Вождь Гром", "persona": "Суровый, но мудрый лидер."},
            "goals": ["Создать лучшее оружие"],
            "alignment_suggestion": "Lawful Neutral"
        }

        created_faction_id = str(uuid.uuid4())
        expected_faction = _FactionModel(id=created_faction_id, guild_id=guild_id, name_i18n=faction_concept["name_i18n"])

        with patch.object(self.faction_manager, 'create_faction', new_callable=AsyncMock) as mock_internal_create:
            mock_internal_create.return_value = expected_faction

            faction = await self.faction_manager.create_faction_from_ai(
                guild_id, faction_concept, lang, self.mock_npc_manager
            )
            self.assertIsNotNone(faction)
            if faction: # type guard
                 self.assertEqual(faction.name_i18n["ru"], "Клан Стали")
                 self.assertIsNone(faction.leader_id)

            mock_internal_create.assert_called_once()
            call_args_faction = mock_internal_create.call_args[1]
            self.assertIsNone(call_args_faction['leader_id'])

        if hasattr(self.mock_npc_manager, 'create_npc_from_ai_concept'):
            self.mock_npc_manager.create_npc_from_ai_concept.assert_not_called()


class TestNpcManagerAI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_db_service = AsyncMock()
        # For NpcManager's __init__, provide mocks for all dependencies
        self.mock_item_mgr = AsyncMock()
        self.mock_status_mgr = AsyncMock()
        self.mock_party_mgr = AsyncMock()
        self.mock_char_mgr = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_combat_mgr = AsyncMock()
        self.mock_dialogue_mgr = AsyncMock()
        self.mock_loc_mgr = AsyncMock()
        self.mock_game_log_mgr = AsyncMock()
        self.mock_mp_prompt_gen = MagicMock() # Often not async
        self.mock_openai_svc = AsyncMock()
        self.mock_ai_validator = MagicMock() # Often not async
        self.mock_campaign_loader = MagicMock() # Often not async
        self.mock_notification_svc = AsyncMock()
        self.mock_game_manager_for_npc = AsyncMock()


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

        # Mock the internal create_npc that create_npc_from_ai_concept calls
        # This method IS on NpcManager itself, so we mock it on the instance.
        # If create_npc_from_ai_concept is the one being tested, we might not want to mock create_npc
        # unless create_npc has complex side effects we want to isolate from.
        # The test seems to verify that create_npc_from_ai_concept calls create_npc correctly.
        self.npc_manager.create_npc = AsyncMock()
        # Mock get_npc which is called after create_npc
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
        created_npc_obj = _NPCModel(id=expected_npc_id, guild_id=guild_id, template_id="generic_humanoid_ai", name_i18n={"en":"Guard Captain"})

        self.npc_manager.create_npc.return_value = expected_npc_id
        self.npc_manager.get_npc.return_value = created_npc_obj

        npc = await self.npc_manager.create_npc_from_ai_concept(
            guild_id, npc_concept, lang, location_id="loc1"
        )

        self.assertIsNotNone(npc)
        if npc: # type guard
            self.assertEqual(npc.id, expected_npc_id)
            self.assertEqual(npc.name_i18n["en"], "Guard Captain")

        self.npc_manager.create_npc.assert_called_once()
        call_args = self.npc_manager.create_npc.call_args[1]
        self.assertEqual(call_args['guild_id'], guild_id)
        self.assertEqual(call_args['npc_template_id'], "generic_humanoid_ai")
        self.assertEqual(call_args['location_id'], "loc1")
        self.assertEqual(call_args['name_i18n_override']['en'], "Guard Captain")
        self.assertEqual(call_args['role_override'], "Captain")

        self.npc_manager.get_npc.assert_called_once_with(guild_id, expected_npc_id)

    async def test_create_npc_from_ai_concept_create_npc_fails_returns_none(self):
        guild_id = "g1"; lang = "en"; npc_concept = {"name_i18n": {"en":"Fail NPC"}}
        self.npc_manager.create_npc.return_value = None

        npc = await self.npc_manager.create_npc_from_ai_concept(guild_id, npc_concept, lang)
        self.assertIsNone(npc)

    async def test_create_npc_from_ai_concept_create_npc_returns_moderation_dict(self):
        guild_id = "g1"; lang = "en"; npc_concept = {"name_i18n": {"en":"Mod NPC"}}
        self.npc_manager.create_npc.return_value = {"moderation_needed": True}

        npc = await self.npc_manager.create_npc_from_ai_concept(guild_id, npc_concept, lang)
        self.assertIsNone(npc)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
