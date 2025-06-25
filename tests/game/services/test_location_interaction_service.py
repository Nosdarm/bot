import asyncio
import unittest
from unittest.mock import MagicMock
from typing import Dict, Any

from bot.game.services.location_interaction_service import LocationInteractionService
from bot.ai.rules_schema import CoreGameRulesConfig, LocationInteractionDefinition, LocationInteractionOutcome

class TestLocationInteractionService(unittest.TestCase):

    def setUp(self):
        # Create MagicMock instances for all dependencies
        self.mock_db_service = MagicMock()
        self.mock_character_manager = MagicMock()
        self.mock_item_manager = MagicMock()
        self.mock_status_manager = MagicMock()
        self.mock_check_resolver = MagicMock() # Assuming CheckResolver is a class or a callable
        self.mock_notification_service = MagicMock()
        self.mock_game_log_manager = MagicMock()

        # Create a mock GameManager
        self.mock_game_manager = MagicMock()
        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.item_manager = self.mock_item_manager
        self.mock_game_manager.status_manager = self.mock_status_manager
        self.mock_game_manager.check_resolver = self.mock_check_resolver # If LIS accesses it via GM
        self.mock_game_manager.notification_service = self.mock_notification_service
        self.mock_game_manager.game_log_manager = self.mock_game_log_manager
        # Add other managers to mock_game_manager if LIS uses them, e.g., rule_engine, location_manager

        # Instantiate the service with the mock game_manager
        self.lis = LocationInteractionService(
            game_manager=self.mock_game_manager
        )

    def test_instantiation(self):
        """Test that LocationInteractionService can be instantiated with mock dependencies."""
        self.assertIsNotNone(self.lis)
        self.assertEqual(self.lis.game_manager, self.mock_game_manager)
        # Specific checks for managers can be done on self.mock_game_manager if needed

    def test_process_interaction_placeholder_generic(self):
        """Test the placeholder response of process_interaction for a generic intent."""
        # Create a minimal CoreGameRulesConfig
        rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=None, loot_tables={},
            action_conflicts=[], location_interactions={}, base_stats={},
            equipment_slots={}, item_effects={}, status_effects={}
        )

        action_data = {
            "intent": "INTERACT_OBJECT", # A generic interaction intent
            "entities": [{"type": "interactive_object_id", "id": "some_lever"}],
            "original_text": "pull some lever"
        }

        expected_result = {
            "success": False,
            "message": "You try to interact with 'some_lever', but nothing specific happens. (No definition found)",
            "state_changed": False
        }

        result = asyncio.run(self.lis.process_interaction(
            guild_id="test_guild",
            character_id="player_1",
            action_data=action_data,
            rules_config=rules_config
        ))
        self.assertEqual(result, expected_result)

    def test_process_interaction_placeholder_with_defined_interaction(self):
        """Test placeholder response when an interaction_id is found but logic is not yet full."""
        interaction_id = "lever_A"
        interaction_desc = "A rusty lever"
        rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=None, loot_tables={},
            action_conflicts=[],
            location_interactions={
                interaction_id: LocationInteractionDefinition(
                    id=interaction_id,
                    description_i18n={"en": interaction_desc},
                    success_outcome=LocationInteractionOutcome(type="display_message", message_i18n={"en": "It creaks!"})
                )
            },
            base_stats={}, equipment_slots={}, item_effects={}, status_effects={}
        )

        action_data = {
            "intent": "INTERACT_OBJECT",
            "entities": [{"type": "interactive_object_id", "id": interaction_id, "name": "lever"}],
            "original_text": "pull the lever"
        }

        # The current placeholder in LIS.process_interaction, when an interaction_def IS found:
        expected_message_template = "You interact with '{description}'. (Placeholder outcome)"
        expected_message = expected_message_template.format(description=interaction_desc)
        expected_result = {
            "success": True, # Placeholder currently returns True if def is found
            "message": expected_message,
            "state_changed": True, # Placeholder currently returns True if def is found
            "interaction_id": interaction_id
        }

        result = asyncio.run(self.lis.process_interaction(
            guild_id="test_guild",
            character_id="player_1",
            action_data=action_data,
            rules_config=rules_config
        ))
        self.assertEqual(result, expected_result)

    def test_process_interaction_search_placeholder(self):
        """Test the placeholder response for a 'search' intent."""
        rules_config = CoreGameRulesConfig(
            checks={}, damage_types={}, xp_rules=None, loot_tables={},
            action_conflicts=[], location_interactions={}, base_stats={},
            equipment_slots={}, item_effects={}, status_effects={}
        )

        action_data = {
            "intent": "search", # NLU might produce lowercase "search"
            "entities": [], # No specific target, general area search
            "original_text": "search the room"
        }

        # Based on current LIS placeholder:
        expected_result = {
            "success": False,
            "message": "LocationInteractionService: Interaction 'search' for 'search the room' - no specific interactive element processed.",
            "state_changed": False
        }
        # If the LIS specific check for "search" intent was hit:
        # expected_message = "You search the area. (Placeholder - LIS)"
        # expected_result = {"success": False, "message": expected_message, "state_changed": False}


        result = asyncio.run(self.lis.process_interaction(
            guild_id="test_guild",
            character_id="player_1",
            action_data=action_data,
            rules_config=rules_config
        ))
        self.assertEqual(result, expected_result)


if __name__ == '__main__':
    unittest.main()
