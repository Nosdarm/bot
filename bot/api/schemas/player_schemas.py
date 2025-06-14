# bot/api/schemas/player_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any # Any for JSON fields initially

# Forward declaration for Character schemas to avoid circular imports if needed
# However, for response models, it's better to define a specific brief schema here
# or import it if Character schemas are defined first.
# For now, let's assume Character schemas will be available or use a placeholder.

class CharacterBasicResponse(BaseModel): # A basic representation for lists
    id: str
    name_i18n: Dict[str, str]
    class_i18n: Optional[Dict[str, str]] = None
    level: int
    is_active_char: bool

    class Config:
        orm_mode = True


class PlayerBase(BaseModel):
    discord_id: Optional[str] = Field(None, description="Player's Discord User ID")
    name_i18n: Dict[str, str] = Field(..., description="Player's name (nickname/pseudonym), i18n JSON object", example={"en": "PlayerOne", "ru": "ИгрокОдин"})
    selected_language: Optional[str] = Field(None, description="Player's preferred language code (e.g., 'en', 'ru')")
    is_active: Optional[bool] = Field(True, description="Whether the player account is active")
    # Guild_id will be required in PlayerCreate schema as per requirements.

    # Game-specific fields that might be updatable or part of creation
    # These are extensive in the model; only include what's needed for API CRUD.
    # For example, stats, level, xp might be managed by game logic, not direct API update.
    # Let's keep it minimal for now, focusing on core identity.
    # stats: Optional[Dict[str, Any]] = None # Example if direct update was desired
    # character_class: Optional[str] = None # This is on Player model, but maybe should be on Character?


class PlayerCreate(PlayerBase):
    discord_id: str = Field(..., description="Player's Discord User ID")
    guild_id: str = Field(..., description="Guild ID this player record belongs to")
    # name_i18n is inherited from PlayerBase


class PlayerUpdate(BaseModel): # Using BaseModel directly for more control on optional fields
    name_i18n: Optional[Dict[str, str]] = Field(None, description="Player's name (nickname/pseudonym), i18n JSON object")
    selected_language: Optional[str] = Field(None, description="Player's preferred language code")
    is_active: Optional[bool] = Field(None, description="Set player account active status")
    # Other fields as needed for update


class PlayerRead(PlayerBase):
    id: str = Field(..., description="Player's unique ID")
    guild_id: str = Field(..., description="Guild ID this player record belongs to")
    xp: Optional[int] = Field(0, description="Player's experience points")
    level: Optional[int] = Field(1, description="Player's level")
    unspent_xp: Optional[int] = Field(0, description="Player's unspent XP")
    gold: Optional[int] = Field(0, description="Player's gold")
    # current_game_status: Optional[str] = Field(None, description="Player's current game status") # Example
    # characters: List['CharacterResponse'] = [] # Full CharacterResponse might be too verbose here
    characters: List[CharacterBasicResponse] = [] # List of basic character info

    class Config:
        orm_mode = True

# If CharacterRead is defined in character_schemas.py, you might need:
# from .character_schemas import CharacterRead
# And then PlayerRead.update_forward_refs() after CharacterRead is defined.
# For now, CharacterBasicResponse is self-contained.
