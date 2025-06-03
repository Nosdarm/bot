import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
import json

from bot.game.managers.npc_manager import NpcManager
from bot.game.models.npc import NPC # Assuming NPC model can be instantiated for tests

class TestNpcManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {} # Basic settings
        self.mock_item_manager = AsyncMock()
        self.mock_status_manager = AsyncMock()
        self.mock_party_manager = AsyncMock()
        self.mock_character_manager = AsyncMock()
        self.mock_rule_engine = AsyncMock()
        self.mock_combat_manager = AsyncMock()
        self.mock_dialogue_manager = AsyncMock()
        self.mock_location_manager = AsyncMock()
        self.mock_game_log_manager = AsyncMock()
        self.mock_prompt_generator = AsyncMock()
        self.mock_openai_service = AsyncMock()
        self.mock_ai_validator = AsyncMock()
        self.mock_campaign_loader = AsyncMock()

        self.npc_manager = NpcManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            item_manager=self.mock_item_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            character_manager=self.mock_character_manager,
            rule_engine=self.mock_rule_engine,
            combat_manager=self.mock_combat_manager,
            dialogue_manager=self.mock_dialogue_manager,
            location_manager=self.mock_location_manager,
            game_log_manager=self.mock_game_log_manager,
            multilingual_prompt_generator=self.mock_prompt_generator,
            openai_service=self.mock_openai_service,
            ai_validator=self.mock_ai_validator
        )

    async def test_create_npc_ai_pending_moderation(self):
        """Test AI NPC creation successfully goes to pending moderation."""
        guild_id = "test_guild_ai_success"
        npc_template_id = "AI:generate_guard"
        user_id = "test_user_moderation"
        mock_validated_data = {"name": "AI Guard", "archetype": "guard", "stats": {"strength": 12}}

        self.mock_ai_validator.validate_ai_response.return_value = {
            "overall_status": "success",
            "entities": [{"validated_data": mock_validated_data}]
        }
        # Mock generate_npc_details_from_ai to directly return the validated data for simplicity here,
        # as generate_npc_details_from_ai itself will be tested elsewhere or assumed working.
        # Alternatively, mock the services it calls if testing generate_npc_details_from_ai implicitly.
        # For this test, we focus on create_npc's logic after generate_npc_details_from_ai returns.
        self.npc_manager.generate_npc_details_from_ai = AsyncMock(return_value=mock_validated_data)


        expected_request_id = str(uuid.uuid4())
        with patch('uuid.uuid4', return_value=uuid.UUID(expected_request_id)):
            result = await self.npc_manager.create_npc(
                guild_id, npc_template_id, location_id="loc1", user_id=user_id, campaign_loader=self.mock_campaign_loader
            )

        self.assertEqual(result, {"status": "pending_moderation", "request_id": expected_request_id})
        self.mock_db_adapter.save_pending_moderation_request.assert_called_once()
        call_args = self.mock_db_adapter.save_pending_moderation_request.call_args[0]
        self.assertEqual(call_args[0], expected_request_id)
        self.assertEqual(call_args[1], guild_id)
        self.assertEqual(call_args[2], user_id)
        self.assertEqual(call_args[3], "npc")
        self.assertEqual(json.loads(call_args[4]), mock_validated_data)

    async def test_create_npc_ai_validation_fails_or_requires_moderation_itself(self):
        """Test AI NPC creation returns None if AI validation/generation itself fails."""
        guild_id = "test_guild_ai_fail"
        npc_template_id = "AI:generate_goblin"
        user_id = "test_user_fail"

        # Scenario 1: generate_npc_details_from_ai returns None (e.g. validator said needs_moderation or error)
        self.npc_manager.generate_npc_details_from_ai = AsyncMock(return_value=None)

        result = await self.npc_manager.create_npc(
            guild_id, npc_template_id, location_id="loc2", user_id=user_id, campaign_loader=self.mock_campaign_loader
        )

        self.assertIsNone(result)
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

    async def test_create_npc_ai_no_user_id(self):
        """Test AI NPC creation fails if user_id is not provided."""
        guild_id = "test_guild_ai_no_user"
        npc_template_id = "AI:generate_villager"
        mock_validated_data = {"name": "AI Villager", "archetype": "villager"}
        self.npc_manager.generate_npc_details_from_ai = AsyncMock(return_value=mock_validated_data)

        result = await self.npc_manager.create_npc(
            guild_id, npc_template_id, location_id="loc3", campaign_loader=self.mock_campaign_loader # No user_id
        )

        self.assertIsNone(result)
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

    async def test_create_npc_non_ai_from_template(self):
        """Test non-AI NPC creation from a campaign template."""
        guild_id = "test_guild_template"
        npc_template_id = "guard_template_001"
        archetype_data = {
            "id": npc_template_id,
            "name": "Guard Template",
            "archetype": "guard",
            "stats": {"strength": 10, "max_health": 60},
            "inventory": [], "traits": [], "desires": [], "motives": [], "backstory": ""
        }
        self.mock_campaign_loader.get_npc_archetypes.return_value = [archetype_data]
        # Mock rule engine if it's called for stats and not part of archetype
        self.mock_rule_engine.generate_initial_npc_stats = AsyncMock(return_value={"dexterity": 8, "max_health": 50})


        result_id = await self.npc_manager.create_npc(
            guild_id, npc_template_id, location_id="loc_barracks", campaign_loader=self.mock_campaign_loader
        )

        self.assertIsNotNone(result_id)
        self.assertIsInstance(result_id, str) # Should be the npc_id
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()

        # Check if NPC is in cache
        created_npc = self.npc_manager.get_npc(guild_id, result_id)
        self.assertIsNotNone(created_npc)
        self.assertEqual(created_npc.name, archetype_data["name"])
        self.assertEqual(created_npc.archetype, archetype_data["archetype"])
        self.assertIn("strength", created_npc.stats)
        self.assertIn("dexterity", created_npc.stats) # From rule_engine mock
        self.assertEqual(created_npc.stats["strength"], 10)


    async def test_generate_npc_details_from_ai_success(self):
        """Test generate_npc_details_from_ai successfully returns validated data."""
        guild_id = "test_guild_gen_success"
        npc_concept = "powerful mage"
        expected_data = {"name": "Mighty Wizard", "archetype": "mage_lord"}

        self.mock_prompt_generator.generate_npc_profile_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": json.dumps(expected_data)})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "success",
            "entities": [{"validated_data": expected_data}]
        })

        result = await self.npc_manager.generate_npc_details_from_ai(guild_id, npc_concept)
        self.assertEqual(result, expected_data)
        self.mock_prompt_generator.generate_npc_profile_prompt.assert_called_once()
        self.mock_openai_service.generate_structured_multilingual_content.assert_called_once()
        self.mock_ai_validator.validate_ai_response.assert_called_once()

    async def test_generate_npc_details_from_ai_openai_fails(self):
        """Test generate_npc_details_from_ai handles OpenAI service failure."""
        self.mock_prompt_generator.generate_npc_profile_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"error": "OpenAI down"})

        result = await self.npc_manager.generate_npc_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_generate_npc_details_from_ai_validator_fails(self):
        """Test generate_npc_details_from_ai handles AI validator failure."""
        self.mock_prompt_generator.generate_npc_profile_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"global_errors": ["validation failed"]})

        result = await self.npc_manager.generate_npc_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_generate_npc_details_from_ai_validator_needs_moderation(self):
        """Test generate_npc_details_from_ai handles AI validator 'requires_moderation' flag."""
        self.mock_prompt_generator.generate_npc_profile_prompt.return_value = {"system": "sys", "user": "usr"}
        self.mock_openai_service.generate_structured_multilingual_content = AsyncMock(return_value={"json_string": "{}"})
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={
            "overall_status": "requires_manual_review", # or similar status
            "entities": [{"validated_data": {"name":"Needs Review"}, "requires_moderation": True}]
        })
        # Based on current NpcManager.generate_npc_details_from_ai, if 'requires_moderation' is true on the entity,
        # it returns None.
        result = await self.npc_manager.generate_npc_details_from_ai("gid", "concept")
        self.assertIsNone(result)

    async def test_create_npc_from_moderated_data(self):
        """Test creating an NPC from moderated, pre-validated data."""
        guild_id = "test_guild_moderated_npc"
        # This data is what would have been stored in pending_moderation_requests.data
        # It should be complete enough for NPC.from_dict after initial AI validation.
        moderated_npc_data = {
            "id": str(uuid.uuid4()), # ID might be pre-assigned or generated in method
            "name": "Approved NPC",
            "name_i18n": {"en": "Approved NPC", "ru": "Одобренный НПЦ"},
            "archetype": "bard",
            "stats": {"strength": 7, "dexterity": 14, "intelligence": 12, "max_health": 45.0},
            "location_id": "tavern_main_hall",
            "inventory": [{"item_id": "lute", "quantity": 1}],
            "traits": ["charming", "talkative"],
            "desires": ["fame"],
            "motives": ["entertain"],
            "backstory": "A wandering minstrel, approved by the masters.",
            "backstory_i18n": {"en": "A wandering minstrel, approved by the masters."},
            "is_temporary": False,
            # Other fields expected by NPC.from_dict like guild_id will be set by the method
        }
        context_data = {"some_context_info": "value"}

        # Ensure a unique ID is used if one isn't in moderated_npc_data or is unsuitable
        # For this test, let's assume moderated_npc_data comes with a valid ID.
        if 'id' not in moderated_npc_data:
            moderated_npc_data['id'] = str(uuid.uuid4())

        npc_id = await self.npc_manager.create_npc_from_moderated_data(guild_id, moderated_npc_data, context_data)

        self.assertIsNotNone(npc_id)
        self.assertEqual(npc_id, moderated_npc_data['id'])

        # Verify NPC is in cache
        created_npc = self.npc_manager.get_npc(guild_id, npc_id)
        self.assertIsNotNone(created_npc)
        self.assertEqual(created_npc.name, moderated_npc_data['name'])
        self.assertEqual(created_npc.archetype, moderated_npc_data['archetype'])
        self.assertEqual(created_npc.stats['strength'], 7)
        self.assertEqual(created_npc.location_id, "tavern_main_hall")
        self.assertTrue(self.npc_manager._dirty_npcs[guild_id].__contains__(npc_id))

        # Verify no AI services were called
        self.mock_prompt_generator.generate_npc_profile_prompt.assert_not_called()
        self.mock_openai_service.generate_structured_multilingual_content.assert_not_called()
        self.mock_ai_validator.validate_ai_response.assert_not_called()
        self.mock_db_adapter.save_pending_moderation_request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
