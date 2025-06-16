# bot/game/managers/__init__.py

"""
This package contains the manager classes for various game systems.
Managers are responsible for handling the logic, state, and interactions
of their respective game entities or systems.
"""

# Import manager classes here to make them available when the package is imported.
# Example:
# from .location_manager import LocationManager
# from .player_manager import PlayerManager
# from .item_manager import ItemManager
# from .npc_manager import NpcManager
# from .event_manager import EventManager
# from .quest_manager import QuestManager
# from .combat_manager import CombatManager
# from .party_manager import PartyManager

from .global_npc_manager import GlobalNpcManager
from .mobile_group_manager import MobileGroupManager

__all__ = [
    # 'LocationManager',
    # 'PlayerManager',
    # 'ItemManager',
    # 'NpcManager',
    # 'EventManager',
    # 'QuestManager',
    # 'CombatManager',
    # 'PartyManager',
    'GlobalNpcManager',
    'MobileGroupManager',
]
