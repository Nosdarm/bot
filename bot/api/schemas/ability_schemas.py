# bot/api/schemas/ability_schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class AbilityBase(BaseModel):
    name_i18n: Dict[str, str] = Field(..., description="Multilingual name of the ability", example={"en": "Fireball", "ru": "Огненный шар"})
    description_i18n: Dict[str, str] = Field(..., description="Multilingual description of the ability")
    effect_i18n: Dict[str, str] = Field(..., description="Multilingual description of the ability's effect")
    cost: Optional[Dict[str, Any]] = Field(None, description="Cost to use the ability, e.g., {'mana': 10, 'stamina': 5}")
    requirements: Optional[Dict[str, Any]] = Field(None, description="Requirements to learn or use the ability, e.g., {'level': 5}")
    type_i18n: Dict[str, str] = Field(..., description="Multilingual type of the ability, e.g., {'en': 'Combat', 'ru': 'Боевая'}")

class AbilityCreate(AbilityBase):
    # guild_id will be from path parameter
    pass

class AbilityUpdate(BaseModel): # For partial updates
    name_i18n: Optional[Dict[str, str]] = None
    description_i18n: Optional[Dict[str, str]] = None
    effect_i18n: Optional[Dict[str, str]] = None
    cost: Optional[Dict[str, Any]] = None
    requirements: Optional[Dict[str, Any]] = None
    type_i18n: Optional[Dict[str, str]] = None

class AbilityResponse(AbilityBase):
    id: str = Field(..., description="Unique ID of the ability")
    guild_id: str = Field(..., description="Guild ID this ability belongs to")

    class Config:
        orm_mode = True
