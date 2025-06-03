import uuid
from typing import Dict, Any, Optional

class BaseModel:
    def __init__(self, id: Optional[str] = None):
        if id is None:
             self.id: str = str(uuid.uuid4())
        else:
             self.id = id

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
         instance = cls(id=data.get('id'))
         instance.__dict__.update({k:v for k,v in data.items() if k != 'id'})
         return instance
