from typing import Dict, Optional, Any # Need these for basic methods signatures

class SomeModel:
    def __init__(self, id: str, **kwargs):
        self.id = id
        for key, value in kwargs.items():
             setattr(self, key, value)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SomeModel": return SomeModel(**data)
    def to_dict(self) -> Dict[str, Any]: return {"id": self.id} # Minimal save data