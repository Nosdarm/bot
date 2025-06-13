# bot/api/schemas/character_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any # Any for JSON fields


class CharacterStatsSchema(BaseModel):
    base_strength: int = Field(10, description="Base strength attribute")
    base_dexterity: int = Field(10, description="Base dexterity attribute")
    base_constitution: int = Field(10, description="Base constitution attribute")
    base_intelligence: int = Field(10, description="Base intelligence attribute")
    base_wisdom: int = Field(10, description="Base wisdom attribute")
    base_charisma: int = Field(10, description="Base charisma attribute")


class CharacterBase(BaseModel):
    name_i18n: Dict[str, str] = Field(..., description="Character's name, i18n JSON object", example={"en": "Valerius", "ru": "Валериус"})
    class_i18n: Optional[Dict[str, str]] = Field(None, description="Character's class, i18n JSON object", example={"en": "Warrior", "ru": "Воин"})
    description_i18n: Optional[Dict[str, str]] = Field(None, description="Character's description, i18n JSON object")

    level: int = Field(1, description="Character's level", ge=1)
    experience: int = Field(0, alias='xp', description="Character's experience points", ge=0) # Renamed from xp, added alias

    stats: Optional[CharacterStatsSchema] = Field(default_factory=CharacterStatsSchema, description="Character's base attributes")
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
    level: Optional[int] = Field(None, ge=1)
    experience: Optional[int] = Field(None, alias='xp', ge=0) # Renamed from xp, added alias
    stats: Optional[CharacterStatsSchema] = None
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
