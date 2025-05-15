# bot/game/npc_action_handlers/npc_action_handler_registry.py

# --- Imports ---
import traceback # Import traceback, needed by some handlers
from typing import Dict, Any, Optional, Callable, Awaitable # Import typing components

# Import base handler
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback # Import base handler and callback types

# Import specific completion handlers
from .npc_move_completion_handler import NpcMoveCompletionHandler
from .npc_combat_attack_completion_handler import NpcCombatAttackCompletionHandler
from .npc_rest_completion_handler import NpcRestCompletionHandler
from .npc_search_completion_handler import NpcSearchCompletionHandler
from .npc_craft_completion_handler import NpcCraftCompletionHandler
from .npc_use_item_completion_handler import NpcUseItemCompletionHandler
# TODO: Import other specific completion handlers you create
# from .npc_dialogue_completion_handler import NpcDialogueCompletionHandler


# Import managers needed by the completion handlers (to be injected into handlers)
# List ALL managers required by ANY handler here
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.npc_manager import NpcManager # Needed by many handlers (add_item, mark dirty)
from bot.game.managers.combat_manager import CombatManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.crafting_manager import CraftingManager
from bot.game.managers.character_manager import CharacterManager # Needed by UseItemHandler (for target)

# TODO: Add imports for other managers needed by your handlers
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.event_processors.event_stage_processor import EventStageProcessor


class NpcActionHandlerRegistry:
    """
    Реестр для хранения экземпляров обработчиков завершения действий NPC.
    Позволяет получить нужный обработчик по типу действия.
    """
    def __init__(self,
                 # List ALL managers/services required by ANY handler here
                 location_manager: LocationManager,
                 npc_manager: NpcManager,
                 combat_manager: CombatManager,
                 rule_engine: RuleEngine,
                 status_manager: StatusManager,
                 item_manager: ItemManager,
                 crafting_manager: CraftingManager,
                 character_manager: CharacterManager, # Add character_manager

                 # TODO: Add other managers needed by your handlers
                 dialogue_manager: Optional['DialogueManager'] = None, # Optional if not always used
                 event_stage_processor: Optional['EventStageProcessor'] = None, # Optional if not always used
                 # etc.
                ):
        """
        Инициализирует реестр, создавая и регистрируя обработчики завершения действий NPC.

        При создании каждого обработчика ему инжектируются менеджеры, которые ему специфически нужны.
        """
        print("Initializing NpcActionHandlerRegistry...")

        # Store managers (pass them to handlers)
        # We store them here as they are used to instantiate the handlers below.
        self._location_manager = location_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._crafting_manager = crafting_manager
        self._character_manager = character_manager

        # Store other managers
        self._dialogue_manager = dialogue_manager # Store optional
        self._event_stage_processor = event_stage_processor # Store optional


        # Instantiate and register handlers
        self._handlers: Dict[str, BaseNpcActionHandler] = {} # Use BaseNpcActionHandler type hint

        # Instantiate handlers, injecting their specific dependencies
        # We wrap each in try/except in case a required manager wasn't passed to the registry
        # or if the handler's __init__ is incorrect.
        try:
            # Move handler needs location_manager, npc_manager
            if self._location_manager and self._npc_manager:
                 self.register_handler('move', NpcMoveCompletionHandler(location_manager=self._location_manager, npc_manager=self._npc_manager))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcMoveCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcMoveCompletionHandler: {e}"); traceback.print_exc()

        try:
            # Combat Attack handler needs combat_manager
            if self._combat_manager:
                 self.register_handler('combat_attack', NpcCombatAttackCompletionHandler(combat_manager=self._combat_manager))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcCombatAttackCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcCombatAttackCompletionHandler: {e}"); traceback.print_exc()

        try:
            # Rest handler needs rule_engine, status_manager, npc_manager
            if self._rule_engine and self._status_manager and self._npc_manager:
                 self.register_handler('rest', NpcRestCompletionHandler(rule_engine=self._rule_engine, status_manager=self._status_manager, npc_manager=self._npc_manager))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcRestCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcRestCompletionHandler: {e}"); traceback.print_exc()

        try:
            # Search handler needs rule_engine, item_manager, npc_manager
            if self._rule_engine and self._item_manager and self._npc_manager:
                 self.register_handler('search', NpcSearchCompletionHandler(rule_engine=self._rule_engine, item_manager=self._item_manager, npc_manager=self._npc_manager))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcSearchCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcSearchCompletionHandler: {e}"); traceback.print_exc()

        try:
            # Craft handler needs crafting_manager, item_manager, npc_manager
            if self._crafting_manager and self._item_manager and self._npc_manager:
                 self.register_handler('craft', NpcCraftCompletionHandler(crafting_manager=self._crafting_manager, item_manager=self._item_manager, npc_manager=self._npc_manager))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcCraftCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcCraftCompletionHandler: {e}"); traceback.print_exc()

        try:
            # Use Item handler needs item_manager, rule_engine, npc_manager, character_manager, status_manager.
            # Managers like CombatManager, LocationManager are needed for item *effects*,
            # which are handled by RuleEngine.calculate_item_use_effect, so they don't need to be
            # injected into UseItemCompletionHandler's __init__, but must be passed to the
            # handler's `handle` method via kwargs.
            if self._item_manager and self._rule_engine and self._npc_manager and self._character_manager and self._status_manager:
                 self.register_handler('use_item', NpcUseItemCompletionHandler(
                     item_manager=self._item_manager,
                     rule_engine=self._rule_engine,
                     npc_manager=self._npc_manager,
                     character_manager=self._character_manager, # CharacterManager is needed to get Character targets
                     status_manager=self._status_manager, # StatusManager is needed to apply status effects
                     # Managers needed by calculate_item_use_effect but not handler's __init__ are passed via handle's kwargs:
                     # combat_manager=self._combat_manager,
                     # location_manager=self._location_manager,
                 ))
            else: print("NpcActionHandlerRegistry: Warning: Skipping NpcUseItemCompletionHandler registration due to missing dependencies.")
        except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcUseItemCompletionHandler: {e}"); traceback.print_exc()

        # TODO: Instantiate and register other handlers (dialogue, etc.)
        # try:
        #     # Dialogue handler needs dialogue_manager, event_stage_processor, character_manager, npc_manager
        #     if self._dialogue_manager and self._event_stage_processor and self._character_manager and self._npc_manager:
        #          self.register_handler('ai_dialogue', NpcDialogueCompletionHandler(
        #              dialogue_manager=self._dialogue_manager,
        #              event_stage_processor=self._event_stage_processor,
        #              character_manager=self._character_manager,
        #              npc_manager=self._npc_manager,
        #              # Add other managers needed by dialogue logic via kwargs
        #              # rule_engine=self._rule_engine,
        #              # item_manager=self._item_manager,
        #              # etc.
        #          ))
        #     else: print("NpcActionHandlerRegistry: Warning: Skipping NpcDialogueCompletionHandler registration due to missing dependencies.")
        # except Exception as e: print(f"NpcActionHandlerRegistry: Error instantiating NpcDialogueCompletionHandler: {e}"); traceback.print_exc()


        print(f"NpcActionHandlerRegistry initialized with {len(self._handlers)} handlers.")

    def register_handler(self, action_type: str, handler: BaseNpcActionHandler) -> None:
        """
        Регистрирует экземпляр обработчика для конкретного типа действия.
        """
        if not isinstance(action_type, str) or not action_type:
            print(f"NpcActionHandlerRegistry: Warning: Attempted to register handler with invalid action type: {action_type}")
            return

        # Optional: Type check if handler is an instance of BaseNpcActionHandler
        if not isinstance(handler, BaseNpcActionHandler):
             print(f"NpcActionHandlerRegistry: Warning: Attempted to register handler for '{action_type}' that is not a BaseNpcActionHandler instance: {type(handler).__name__}. Skipping.")
             return

        if action_type in self._handlers:
            print(f"NpcActionHandlerRegistry: Warning: Handler for action type '{action_type}' is already registered. Overwriting.")

        self._handlers[action_type] = handler
        # print(f"NpcActionHandlerRegistry: Handler registered for action type '{action_type}'.") # Print moved to __init__

    def get_handler(self, action_type: str) -> Optional[BaseNpcActionHandler]:
        """
        Возвращает экземпляр обработчика для заданного типа действия.

        :param action_type: Тип действия (str).
        :return: Экземпляр обработчика (BaseNpcActionHandler) или None, если обработчик не найден.
        """
        return self._handlers.get(action_type)

# End of NpcActionHandlerRegistry class