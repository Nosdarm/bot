from __future__ import annotations
from typing import Optional, Dict, Any, List # Added List
import uuid

from bot.game.models.base_model import BaseModel

class Skill(BaseModel):
    def __init__(self,
                 id: Optional[str] = None,
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 effects: Optional[List[Dict[str, Any]]] = None,
                 # Add other relevant fields later like resource_cost, cooldown, target_type
                 placeholder: Optional[str] = None # Keep existing placeholder if desired
                ):
        super().__init__(id=id)
        self.name_i18n: Dict[str, str] = name_i18n if name_i18n is not None else {"en": "Unnamed Skill"}
        self.description_i18n: Dict[str, str] = description_i18n if description_i18n is not None else {"en": "No description."}
        self.effects: List[Dict[str, Any]] = effects if effects is not None else []
        self.placeholder: Optional[str] = placeholder


    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict.update({
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "effects": self.effects,
            "placeholder": self.placeholder
        })
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Skill:
        return cls(
            id=data.get('id'),
            name_i18n=data.get('name_i18n'),
            description_i18n=data.get('description_i18n'),
            effects=data.get('effects', []), # Ensure effects defaults to a list if missing
            placeholder=data.get('placeholder')
        )

    def __repr__(self) -> str:
        return f"<Skill(id='{self.id}', name='{self.name_i18n.get('en', self.id)}', effects_count={len(self.effects)})>"
