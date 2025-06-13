import uuid
import datetime
from pydantic import BaseModel, Field, validator
from typing import Optional

class RPGCharacterBase(BaseModel):
    name: str = Field(..., example="Aragorn")
    class_name: str = Field(..., example="Ranger") # Renamed from 'class'
    level: int = Field(default=1, example=1)
    health: int = Field(..., example=100)
    mana: int = Field(..., example=50)

    @validator('level')
    def level_must_be_non_negative(cls, value):
        if value < 0:
            raise ValueError("Level must be non-negative")
        return value

    @validator('health')
    def health_must_be_non_negative(cls, value):
        if value < 0:
            raise ValueError("Health must be non-negative")
        return value

    @validator('mana')
    def mana_must_be_non_negative(cls, value):
        if value < 0:
            raise ValueError("Mana must be non-negative")
        return value

class RPGCharacterCreate(RPGCharacterBase):
    pass

class RPGCharacterUpdate(BaseModel):
    name: Optional[str] = Field(None, example="Aragorn King")
    class_name: Optional[str] = Field(None, example="King")
    level: Optional[int] = Field(None, example=10)
    health: Optional[int] = Field(None, example=150)
    mana: Optional[int] = Field(None, example=75)

    @validator('level', always=True)
    def update_level_must_be_non_negative(cls, value):
        if value is not None and value < 0:
            raise ValueError("Level must be non-negative")
        return value

    @validator('health', always=True)
    def update_health_must_be_non_negative(cls, value):
        if value is not None and value < 0:
            raise ValueError("Health must be non-negative")
        return value

    @validator('mana', always=True)
    def update_mana_must_be_non_negative(cls, value):
        if value is not None and value < 0:
            raise ValueError("Mana must be non-negative")
        return value

class RPGCharacterResponse(RPGCharacterBase):
    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        orm_mode = True
