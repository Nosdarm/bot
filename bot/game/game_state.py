from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Forward declare manager types and other types as needed in the future
    # For now, it can be minimal if GameState itself doesn't directly use them yet.
    # from .managers.character_manager import CharacterManager
    # from .managers.npc_manager import NpcManager
    # ... etc.
    pass

class GameState:
    def __init__(self, guild_id: str): # Example: Store guild_id
        self.guild_id: str = guild_id
        # In the future, this class can hold references to various managers
        # For example:
        # from .managers.character_manager import CharacterManager 
        # from .managers.npc_manager import NpcManager
        # self.character_manager: Optional[CharacterManager] = None
        # self.npc_manager: Optional[NpcManager] = None
        print(f"GameState initialized for guild {self.guild_id}")

    # Add methods here if GameState is supposed to provide any direct functionality
    # For example, a method to get a specific manager:
    # def get_character_manager(self) -> Optional[CharacterManager]:
    #     return self.character_manager
