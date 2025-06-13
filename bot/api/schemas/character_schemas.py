# bot/api/schemas/character_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any # Any for JSON fields

class CharacterBase(BaseModel):
    name_i18n: Dict[str, str] = Field(..., description="Character's name, i18n JSON object", example={"en": "Valerius", "ru": "Валериус"})
    class_i18n: Optional[Dict[str, str]] = Field(None, description="Character's class, i18n JSON object", example={"en": "Warrior", "ru": "Воин"})
    description_i18n: Optional[Dict[str, str]] = Field(None, description="Character's description, i18n JSON object")

    level: Optional[int] = Field(1, description="Character's level")
    xp: Optional[int] = Field(0, description="Character's experience points")

    stats: Optional[Dict[str, Any]] = Field(None, description="Character's stats, e.g., {'strength': 10}")
    current_hp: Optional[float] = Field(None, description="Character's current HP")
    max_hp: Optional[float] = Field(None, description="Character's maximum HP")

    abilities: Optional[List[Any]] = Field(None, description="List of character's abilities (IDs or embedded data)") # Or List[str] for IDs
    inventory: Optional[List[Any]] = Field(None, description="List of character's inventory items (IDs or embedded data)") # Or List[str] for IDs
    npc_relationships: Optional[Dict[str, str]] = Field(None, description="Relationships with NPCs, e.g., {'npc_id': 'friendly'}")

    is_active_char: Optional[bool] = Field(False, description="Is this the player's currently active character in the guild?")


class CharacterCreate(CharacterBase):
    # player_id will come from path or context (e.g. if creating for logged-in player)
    # guild_id will also come from path
    pass # Inherits all from CharacterBase, specific fields can be enforced if needed


class CharacterUpdate(BaseModel): # Allow partial updates
    name_i18n: Optional[Dict[str, str]] = None
    class_i18n: Optional[Dict[str, str]] = None
    description_i18n: Optional[Dict[str, str]] = None
    level: Optional[int] = None
    xp: Optional[int] = None
    stats: Optional[Dict[str, Any]] = None
    current_hp: Optional[float] = None
    max_hp: Optional[float] = None
    abilities: Optional[List[Any]] = None
    inventory: Optional[List[Any]] = None
    npc_relationships: Optional[Dict[str, str]] = None
    is_active_char: Optional[bool] = None


class CharacterResponse(CharacterBase):
    id: str = Field(..., description="Character's unique ID")
    player_id: str = Field(..., description="ID of the player this character belongs to")
    guild_id: str = Field(..., description="Guild ID this character belongs to")

    class Config:
        orm_mode = True
