import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid

# Models and Managers to be mocked or used
from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
from bot.game.managers.global_npc_manager import GlobalNpcManager
from bot.game.managers.mobile_group_manager import MobileGroupManager
# Other managers that WorldSimulationProcessor depends on in its __init__
from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.openai_service import OpenAIService # Assuming this is a class
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor
from bot.game.managers.persistence_manager import PersistenceManager
from bot.game.character_processors.character_action_processor import CharacterActionProcessor
from bot.game.party_processors.party_action_processor import PartyActionProcessor


class TestWorldSimulationProcessorIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Mock all dependencies of WorldSimulationProcessor
        self.mock_event_manager = MagicMock(spec=EventManager)
        self.mock_character_manager = MagicMock(spec=CharacterManager)
        self.mock_location_manager = MagicMock(spec=LocationManager)
        self.mock_rule_engine = MagicMock(spec=RuleEngine)
        self.mock_openai_service = MagicMock(spec=OpenAIService)
        self.mock_event_stage_processor = MagicMock(spec=EventStageProcessor)
        self.mock_event_action_processor = MagicMock(spec=EventActionProcessor)
        self.mock_persistence_manager = MagicMock(spec=PersistenceManager)
        self.mock_settings = {"discord_command_prefix": "/"}
        self.mock_send_callback_factory = MagicMock()

        self.mock_character_action_processor = MagicMock(spec=CharacterActionProcessor)
        self.mock_party_action_processor = MagicMock(spec=PartyActionProcessor)

        # Our new managers - use AsyncMock if their methods are async
        self.mock_global_npc_manager = AsyncMock(spec=GlobalNpcManager)
        self.mock_mobile_group_manager = AsyncMock(spec=MobileGroupManager)

        # Optional managers that WSP init takes
        self.mock_npc_manager = AsyncMock() # spec=NpcManager
        self.mock_combat_manager = AsyncMock() # spec=CombatManager
        self.mock_item_manager = AsyncMock() # spec=ItemManager
        self.mock_time_manager = AsyncMock() # spec=TimeManager
        self.mock_status_manager = AsyncMock() # spec=StatusManager
        self.mock_crafting_manager = AsyncMock() # spec=CraftingManager
        self.mock_economy_manager = AsyncMock() # spec=EconomyManager
        self.mock_party_manager = AsyncMock() # spec=PartyManager
        self.mock_dialogue_manager = AsyncMock() # spec=DialogueManager
        self.mock_quest_manager = AsyncMock() # spec=QuestManager
        self.mock_relationship_manager = AsyncMock() # spec=RelationshipManager
        self.mock_game_log_manager = AsyncMock() # spec=GameLogManager
        self.mock_multilingual_prompt_generator = AsyncMock()


        self.world_processor = WorldSimulationProcessor(
            event_manager=self.mock_event_manager,
            character_manager=self.mock_character_manager,
            location_manager=self.mock_location_manager,
            rule_engine=self.mock_rule_engine,
            openai_service=self.mock_openai_service,
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor,
            persistence_manager=self.mock_persistence_manager,
            settings=self.mock_settings,
            send_callback_factory=self.mock_send_callback_factory,
            character_action_processor=self.mock_character_action_processor,
            party_action_processor=self.mock_party_action_processor,
            # Pass new managers
            global_npc_manager=self.mock_global_npc_manager,
            mobile_group_manager=self.mock_mobile_group_manager,
            # Pass optional managers
            npc_manager=self.mock_npc_manager,
            combat_manager=self.mock_combat_manager,
            item_manager=self.mock_item_manager,
            time_manager=self.mock_time_manager,
            status_manager=self.mock_status_manager,
            crafting_manager=self.mock_crafting_manager,
            economy_manager=self.mock_economy_manager,
            party_manager=self.mock_party_manager,
            dialogue_manager=self.mock_dialogue_manager,
            quest_manager=self.mock_quest_manager,
            relationship_manager=self.mock_relationship_manager,
            game_log_manager=self.mock_game_log_manager,
            multilingual_prompt_generator=self.mock_multilingual_prompt_generator
        )

    async def test_process_world_tick_calls_new_managers(self):
        """
        Test that process_world_tick calls the process_tick methods of
        GlobalNpcManager and MobileGroupManager.
        """
        guild_id = str(uuid.uuid4())
        game_time_delta = 1.0

        # Mock PersistenceManager to return our test guild_id
        self.mock_persistence_manager.get_loaded_guild_ids.return_value = [guild_id]

        # Prepare the tick context that WorldSimulationProcessor expects to receive
        # This usually comes from GameManager and includes all managers
        mock_tick_context = {
            'persistence_manager': self.mock_persistence_manager,
            'location_manager': self.mock_location_manager,
            'time_manager': self.mock_time_manager,
            'status_manager': self.mock_status_manager,
            'crafting_manager': self.mock_crafting_manager,
            'combat_manager': self.mock_combat_manager,
            'character_manager': self.mock_character_manager,
            'character_action_processor': self.mock_character_action_processor,
            'party_manager': self.mock_party_manager,
            'party_action_processor': self.mock_party_action_processor,
            'item_manager': self.mock_item_manager,
            'economy_manager': self.mock_economy_manager,
            'event_manager': self.mock_event_manager,
            'event_stage_processor': self.mock_event_stage_processor,
            # Crucially, add the new managers to the context if their tick methods expect them
            # However, WSP's process_world_tick passes its own instances via guild_tick_context.
            # So, we just need to ensure the WSP instance has them.
        }

        await self.world_processor.process_world_tick(game_time_delta, **mock_tick_context)

        # Assert that the process_tick methods of our new managers were called
        self.mock_global_npc_manager.process_tick.assert_called_once_with(
            guild_id=guild_id,
            game_time_delta=game_time_delta,
            **mock_tick_context, # WSP adds guild_id to a copy of this
            # guild_id=guild_id # This will be part of the kwargs
        )

        # Check arguments more precisely for the call
        args, kwargs = self.mock_global_npc_manager.process_tick.call_args
        self.assertEqual(kwargs['guild_id'], guild_id)
        self.assertEqual(kwargs['game_time_delta'], game_time_delta)
        self.assertIn('location_manager', kwargs) # Check if context is passed


        self.mock_mobile_group_manager.process_tick.assert_called_once()
        args_mgm, kwargs_mgm = self.mock_mobile_group_manager.process_tick.call_args
        self.assertEqual(kwargs_mgm['guild_id'], guild_id)
        self.assertEqual(kwargs_mgm['game_time_delta'], game_time_delta)
        self.assertIn('location_manager', kwargs_mgm)
        self.assertIn('global_npc_manager', kwargs_mgm) # MobileGroupManager's tick expects this

    async def test_process_world_tick_handles_missing_optional_managers_gracefully(self):
        """
        Test that WSP process_world_tick runs without GlobalNpcManager and MobileGroupManager
        if they are not provided (i.e., are None).
        """
        guild_id = str(uuid.uuid4())
        game_time_delta = 1.0
        self.mock_persistence_manager.get_loaded_guild_ids.return_value = [guild_id]

        # Create WSP instance without the new managers
        minimal_world_processor = WorldSimulationProcessor(
            event_manager=self.mock_event_manager,
            character_manager=self.mock_character_manager,
            location_manager=self.mock_location_manager,
            rule_engine=self.mock_rule_engine,
            openai_service=self.mock_openai_service,
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor,
            persistence_manager=self.mock_persistence_manager,
            settings=self.mock_settings,
            send_callback_factory=self.mock_send_callback_factory,
            character_action_processor=self.mock_character_action_processor,
            party_action_processor=self.mock_party_action_processor,
            # global_npc_manager and mobile_group_manager are deliberately omitted (default to None)
             time_manager=self.mock_time_manager, # Add other required/optional for full test
             status_manager=self.mock_status_manager,
             crafting_manager=self.mock_crafting_manager,
             economy_manager=self.mock_economy_manager,
             item_manager=self.mock_item_manager,
             # etc.
        )

        mock_tick_context = {
            'persistence_manager': self.mock_persistence_manager,
            'location_manager': self.mock_location_manager,
             'time_manager': self.mock_time_manager,
             'status_manager': self.mock_status_manager,
             'crafting_manager': self.mock_crafting_manager,
             'economy_manager': self.mock_economy_manager,
             'item_manager': self.mock_item_manager,
        }

        try:
            await minimal_world_processor.process_world_tick(game_time_delta, **mock_tick_context)
        except Exception as e:
            self.fail(f"process_world_tick raised an exception with optional managers missing: {e}")

        # Verify that the (non-existent) tick methods were not called
        self.mock_global_npc_manager.process_tick.assert_not_called()
        self.mock_mobile_group_manager.process_tick.assert_not_called()

        # Verify other managers (like economy) were still called to ensure tick didn't just exit
        self.mock_economy_manager.process_tick.assert_called_once()


if __name__ == '__main__':
    unittest.main()
