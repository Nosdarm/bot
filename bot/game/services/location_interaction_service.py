"""
Manages character interactions with interactive elements within game locations.

This service is responsible for interpreting player actions that target specific
interactive objects or features in a location (e.g., levers, doors, chests,
hidden switches). It uses `CoreGameRulesConfig.location_interactions` to
determine the outcomes of such interactions, which may involve skill checks,
item requirements, and state changes.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    # from bot.game.rules.check_resolver import CheckResolver # If CheckResolver is a class
    from bot.game.rules.check_resolver import resolve_check as CheckResolver # If it's a function
    from bot.services.notification_service import NotificationService
    from bot.ai.rules_schema import CoreGameRulesConfig

class LocationInteractionService:
    def __init__(self,
                 db_service: DBService,
                 character_manager: CharacterManager,
                 item_manager: ItemManager,
                 status_manager: StatusManager,
                 check_resolver: CheckResolver, # Type hint based on import
                 notification_service: Optional[NotificationService] = None,
                 game_log_manager: Optional[Any] = None # Optional GameLogManager
                 ):
        """
        Initializes the LocationInteractionService.

        Args:
            db_service: Service for database interactions.
            character_manager: Manages character data and state.
            item_manager: Manages item instances and templates.
            status_manager: Manages status effects on characters.
            check_resolver: Function or class instance to resolve game checks.
            notification_service: Optional service for sending messages to players.
            game_log_manager: Optional service for logging game events.
        """
        self.db_service = db_service
        self.character_manager = character_manager
        self.item_manager = item_manager
        self.status_manager = status_manager
        self.check_resolver = check_resolver
        self.notification_service = notification_service
        self.game_log_manager = game_log_manager
        print("LocationInteractionService initialized.")

    async def process_interaction(
        self,
        guild_id: str,
        character_id: str,
        action_data: Dict[str, Any],
        rules_config: CoreGameRulesConfig
    ) -> Dict[str, Any]:
        """
        Processes a character's interaction with an element in a location.

        This method is a placeholder for the full interaction logic. It will
        eventually determine the specific `LocationInteractionDefinition` based on
        the `action_data` (intent and entities, especially an entity of type
        'interactive_object_id'), check item requirements, perform skill checks
        using `self.check_resolver`, and apply success or failure outcomes
        (e.g., grant items, update character/location state, send messages).

        Args:
            guild_id: The ID of the guild where the interaction occurs.
            character_id: The ID of the character performing the interaction.
            action_data: A dictionary containing the parsed player action, including
                         intent (e.g., "INTERACT_OBJECT", "USE_SKILL_ON_OBJECT") and
                         entities (e.g., `{'type': 'interactive_object_id', 'id': 'door_A'}`).
            rules_config: The `CoreGameRulesConfig` containing definitions for
                          location interactions.

        Returns:
            A dictionary representing the result of the action, typically including:
            `success` (bool), `message` (str), and `state_changed` (bool).
            Currently returns a placeholder message.
        """
        intent = action_data.get("intent")
        entities = action_data.get("entities", [])
        original_text = action_data.get("original_text", "")

        # TODO: Implement full logic based on intent and entities.
        # This will involve:
        # 1. Identifying the specific LocationInteractionDefinition from rules_config.location_interactions.
        #    - This might be based on an entity ID (e.g., player targets "lever_A").
        #    - Or it might be based on intent + location (e.g., "search" in "room_12" might trigger "search_hidden_cache_room_12").
        # 2. Checking for required items if specified in the interaction definition.
        # 3. Performing a skill check if `interaction_def.check_type` is set, using self.check_resolver.
        # 4. Based on check success/failure, applying `success_outcome` or `failure_outcome`.
        #    - Outcomes can include:
        #        - Granting items (self.item_manager)
        #        - Revealing exits (modifying location state via LocationManager or directly if state is on Character)
        #        - Triggering traps (could involve StatusManager or CombatManager)
        #        - Updating state variables (on character, location, or globally)
        #        - Displaying messages (via NotificationService or by returning messages in result)
        # 5. Returning a detailed action_execution_result.

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id, "location_interaction_process_start",
                f"LIS: Processing interaction '{intent}' for char {character_id}. Entities: {entities}",
                {"character_id": character_id, "action_data": action_data}
            )

        # Placeholder result
        message = f"LocationInteractionService: Interaction '{intent}' for '{original_text}' is a placeholder."
        if intent == "search": # Example: "search" or "explore" might be simple
            message = f"You search the area. (Placeholder - LIS)"
            # In a real scenario, this might find hidden LocationInteractionDefinition based on area + search action.

        # Example: Find a specific interactive object entity
        interactive_object_entity = next((e for e in entities if e.get("type") == "interactive_object_id"), None) # Assuming NLU provides this type
        if not interactive_object_entity and intent in ["use_skill", "interact_object"]: # Fallback for more generic targets
             interactive_object_entity = next((e for e in entities if e.get("type") not in ["skill_name", "player", "npc"]), None)


        if interactive_object_entity:
            interaction_id = interactive_object_entity.get("id") # This ID should match a key in rules_config.location_interactions
            interaction_def = rules_config.location_interactions.get(interaction_id)

            if interaction_def:
                # TODO: Full logic here
                # 1. Check required_items
                # 2. Perform check_type if interaction_def.check_type
                # 3. Apply outcome
                message = f"You interact with '{interaction_def.description_i18n.get('en', interaction_id)}'. (Placeholder outcome)"
                # This is where check_resolver would be called, outcomes applied, etc.
                # For now, just acknowledge the interaction.
                return {"success": True, "message": message, "state_changed": True, "interaction_id": interaction_id}
            else:
                message = f"You try to interact with '{interactive_object_entity.get('name', interaction_id)}', but nothing specific happens. (No definition found)"
                return {"success": False, "message": message, "state_changed": False}

        return {"success": False, "message": f"LocationInteractionService: Interaction '{intent}' for '{original_text}' - no specific interactive element processed.", "state_changed": False}

if __name__ == '__main__':
    # This block is for basic testing of the service structure.
    # A more complete test would require mocking all dependencies.
    class MockDBService: pass
    class MockCharacterManager: pass
    class MockItemManager: pass
    class MockStatusManager: pass
    class MockCheckResolver: pass # Or use the actual function if it's stateless

    mock_db = MockDBService()
    mock_char_mngr = MockCharacterManager()
    mock_item_mngr = MockItemManager()
    mock_status_mngr = MockStatusManager()
    # If resolve_check is a standalone function:
    # from bot.game.rules.check_resolver import resolve_check as mock_check_resolver_func
    # lis = LocationInteractionService(mock_db, mock_char_mngr, mock_item_mngr, mock_status_mngr, mock_check_resolver_func)

    # If CheckResolver is a class to be instantiated:
    # mock_check_resolver_instance = MockCheckResolver()
    # lis = LocationInteractionService(mock_db, mock_char_mngr, mock_item_mngr, mock_status_mngr, mock_check_resolver_instance)

    print("LocationInteractionService can be instantiated (mock dependencies).")
    # To run process_interaction, more setup (like CoreGameRulesConfig) would be needed.
    # Example (conceptual, won't run without CoreGameRulesConfig and proper mocks):
    # async def test_interaction():
    #     rules_dict = {"location_interactions": {"lever_A": {"description_i18n": {"en": "A rusty lever"}, "success_outcome": {"type": "display_message", "message_i18n": {"en": "It creaks!"}}}}}
    #     mock_rules = CoreGameRulesConfig.parse_obj(rules_dict)
    #     action = {"intent": "interact_object", "entities": [{"type": "interactive_object_id", "id": "lever_A"}]}
    #     # result = await lis.process_interaction("guild1", "char1", action, mock_rules)
    #     # print(result)
    # asyncio.run(test_interaction())
