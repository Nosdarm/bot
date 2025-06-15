import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY
import json
import uuid # For fallback model ID generation
from typing import Optional, Dict, Any, List, Tuple # Ensure these are imported

# Main classes for integration
from bot.game.managers.faction_manager import FactionManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.ai.faction_generator import AIFactionGenerator

# Models - Attempt to import real models, with fallback
try:
    from bot.game.models.faction import Faction
    from bot.game.models.npc import NPC
except ImportError:
    Faction = Any # type: ignore
    NPC = Any # type: ignore


# Using simplified Pydantic models as fallbacks if real ones are problematic for tests
_FactionModel = Faction
_NPCModel = NPC

# Check if the imported models are actual Pydantic models or placeholders
if not hasattr(Faction, 'model_fields') and not hasattr(Faction, '__fields__'): # Pydantic v2 and v1 check
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
    from pydantic import BaseModel, Field
    from typing import Dict as PydanticDict, List as PydanticList, Optional as PydanticOptional, Any as PydanticAny

    class MinimalNPC(BaseModel):
        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        name_i18n: PydanticDict[str, str] = Field(default_factory=dict)
        guild_id: str
        template_id: str
        # Add other fields that might be accessed or set during tests
        current_location_id: PydanticOptional[str] = None
        faction_id: PydanticOptional[str] = None
        role: PydanticOptional[str] = None
        description_i18n: PydanticOptional[PydanticDict[str, str]] = None
        persona_i18n: PydanticOptional[PydanticDict[str, str]] = None
        base_stats: PydanticOptional[PydanticDict[str, float]] = None # Example
        inventory: PydanticOptional[PydanticList[str]] = None # Example
        state_variables: PydanticOptional[PydanticDict[str, PydanticAny]] = None


        @property
        def name(self): return self.name_i18n.get("en", self.id)
    _NPCModel = MinimalNPC # type: ignore


class TestAIFactionGenerationIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild_id = "faction_integ_guild"
        self.lang = "en"

        self.mock_openai_service = AsyncMock()
        self.mock_prompt_generator = MagicMock()
        self.mock_db_service = AsyncMock()

        self.ai_faction_generator = AIFactionGenerator(
            openai_service=self.mock_openai_service,
            prompt_generator=self.mock_prompt_generator
        )

        # NpcManager - real instance, but its create_npc will be mocked internally.
        # NpcManager's __init__ requires several other managers. We need to provide mocks for those.
        self.mock_item_mgr_for_npc = AsyncMock()
        self.mock_status_mgr_for_npc = AsyncMock()
        self.mock_party_mgr_for_npc = AsyncMock()
        self.mock_char_mgr_for_npc = AsyncMock()
        self.mock_rule_engine_for_npc = AsyncMock()
        self.mock_combat_mgr_for_npc = AsyncMock()
        self.mock_dialogue_mgr_for_npc = AsyncMock()
        self.mock_loc_mgr_for_npc = AsyncMock()
        self.mock_game_log_mgr_for_npc = AsyncMock()
        self.mock_mp_prompt_gen_for_npc = AsyncMock()
        self.mock_ai_validator_for_npc = AsyncMock()
        self.mock_campaign_loader_for_npc = MagicMock() # campaign_loader might not be async
        self.mock_notification_service_for_npc = AsyncMock()


        self.npc_manager = NpcManager(
            db_service=self.mock_db_service,
            settings={},
            item_manager=self.mock_item_mgr_for_npc,
            status_manager=self.mock_status_mgr_for_npc,
            party_manager=self.mock_party_mgr_for_npc,
            character_manager=self.mock_char_mgr_for_npc,
            rule_engine=self.mock_rule_engine_for_npc,
            combat_manager=self.mock_combat_mgr_for_npc,
            dialogue_manager=self.mock_dialogue_mgr_for_npc,
            location_manager=self.mock_loc_mgr_for_npc,
            game_log_manager=self.mock_game_log_mgr_for_npc,
            multilingual_prompt_generator=self.mock_mp_prompt_gen_for_npc,
            openai_service=self.mock_openai_service, # Can share openai mock
            ai_validator=self.mock_ai_validator_for_npc,
            campaign_loader=self.mock_campaign_loader_for_npc,
            notification_service=self.mock_notification_service_for_npc
        )

        self.faction_manager = FactionManager(db_service=self.mock_db_service, settings={})


    async def test_generate_and_create_factions_with_leaders(self):
        faction_concepts_from_ai = [
            {
                "name_i18n": {"en": "The Iron Legion", "ru": "Железный Легион"},
                "description_i18n": {"en": "Disciplined soldiers.", "ru": "Дисциплинированные солдаты."},
                "leader_concept": {"name": "General Volkov", "persona": "Stern and respected."},
                "goals": ["Conquer", "Defend"], "alignment_suggestion": "Lawful Neutral"
            },
            {
                "name_i18n": {"en": "The Mystic Circle"},
                "description_i18n": {"en": "Seekers of arcane knowledge."},
                "leader_concept": {"name": "Archmage Elara", "persona": "Wise and enigmatic."},
                "goals": ["Uncover secrets", "Preserve magic"], "alignment_suggestion": "True Neutral"
            }
        ]
        self.ai_faction_generator.openai_service.generate_master_response.return_value = json.dumps(faction_concepts_from_ai)
        self.ai_faction_generator.prompt_generator.generate_faction_creation_prompt.return_value = ("sys", "user")

        mock_leader1_id = "npc_volkov_integ"
        mock_leader2_id = "npc_elara_integ"

        # Store created NPC objects by their name for the side_effect to look up
        # This assumes names from leader_concept are unique enough for this test.
        _created_npcs_by_name_for_mock = {
            "General Volkov": _NPCModel(id=mock_leader1_id, guild_id=self.guild_id, template_id="generic", name_i18n={"en":"General Volkov"}),
            "Archmage Elara": _NPCModel(id=mock_leader2_id, guild_id=self.guild_id, template_id="generic", name_i18n={"en":"Archmage Elara"})
        }
        _created_npcs_by_id_for_mock = {npc.id: npc for npc in _created_npcs_by_name_for_mock.values()}


        async def mock_create_npc_internal(guild_id, npc_template_id, location_id=None, **kwargs):
            name_override_dict = kwargs.get("name_i18n_override", {})
            name_in_lang = name_override_dict.get(self.lang) # Use self.lang from setUp

            if name_in_lang == "General Volkov": return mock_leader1_id
            if name_in_lang == "Archmage Elara": return mock_leader2_id
            return str(uuid.uuid4())

        # This mock is for NpcManager's internal create_npc, which is called by create_npc_from_ai_concept
        self.npc_manager.create_npc = AsyncMock(side_effect=mock_create_npc_internal)

        async def mock_get_npc_by_id_internal(guild_id, npc_id):
            return _created_npcs_by_id_for_mock.get(npc_id)
        self.npc_manager.get_npc = AsyncMock(side_effect=mock_get_npc_by_id_internal)

        generated_concepts = await self.ai_faction_generator.generate_factions_from_concept(
            "Test Setting", None, None, self.lang, 2
        )
        self.assertEqual(len(generated_concepts), 2)

        created_factions_list: List[_FactionModel] = [] # type: ignore
        for concept in generated_concepts:
            # This now calls the real create_npc_from_ai_concept, which internally calls the mocked create_npc
            faction = await self.faction_manager.create_faction_from_ai(
                self.guild_id, concept, self.lang, self.npc_manager
            )
            self.assertIsNotNone(faction)
            if faction: created_factions_list.append(faction)

        self.assertEqual(len(created_factions_list), 2)

        iron_legion = next((f for f in created_factions_list if f.name_i18n['en'] == "The Iron Legion"), None)
        self.assertIsNotNone(iron_legion)
        if iron_legion:
            self.assertEqual(iron_legion.leader_id, mock_leader1_id)
            self.assertIn(mock_leader1_id, iron_legion.member_ids)
            self.assertIn("Conquer", iron_legion.state_variables.get("goals",[]))

        mystic_circle = next((f for f in created_factions_list if f.name_i18n['en'] == "The Mystic Circle"), None)
        self.assertIsNotNone(mystic_circle)
        if mystic_circle:
            self.assertEqual(mystic_circle.leader_id, mock_leader2_id)
            self.assertIn(mock_leader2_id, mystic_circle.member_ids)

        self.assertEqual(self.npc_manager.create_npc.call_count, 2)
        self.npc_manager.create_npc.assert_any_call(
            guild_id=self.guild_id,
            npc_template_id="generic_humanoid_ai", # Default from create_npc_from_ai_concept
            location_id=None,
            name_i18n_override={'en': 'General Volkov'},
            description_i18n_override=ANY,
            persona_i18n_override={'en': 'Stern and respected.'},
            role_override="faction_leader",
            faction_id_override=None
        )

        self.assertTrue(self.faction_manager._dirty_factions[self.guild_id].issuperset({f.id for f in created_factions_list if f}))

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)

```
