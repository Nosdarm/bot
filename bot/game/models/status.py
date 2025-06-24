from typing import Dict, Optional, Any # Need these for basic methods signatures

class Status:
    def __init__(self, id: str, static_id: str, **kwargs):
        self.id = id
        self.static_id = static_id # Added static_id
        for key, value in kwargs.items():
             setattr(self, key, value)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Status":
        if 'static_id' not in data:
            raise ValueError("Missing required field 'static_id' in status data.")
        # Ensure 'id' is also present or generated if needed, current model requires it for __init__
        if 'id' not in data:
            # Depending on how Status objects are created, 'id' might be auto-generated
            # or also expected. For now, assuming it's expected like static_id.
            # If 'id' is meant to be an instance UUID generated on creation,
            # this from_dict might need to assign one if not present.
            # However, the current DB model has `default=lambda: str(uuid.uuid4())` for id,
            # so from_dict is likely for loading existing data or data that will get a new UUID.
            # The __init__ signature `id: str` implies it's expected.
            raise ValueError("Missing required field 'id' in status data.")
        return Status(**data)

    def to_dict(self) -> Dict[str, Any]:
        data = {"id": self.id, "static_id": self.static_id}
        # Include other attributes that were set via kwargs if they are part of a defined schema
        # For now, just saving id and static_id, and other fields managed by setattr.
        # A more robust to_dict would iterate over expected fields.
        # However, to match the simplicity of the current __init__ with **kwargs:
        for key, value in self.__dict__.items():
            if key not in ["id", "static_id"]: # Avoid duplicating id and static_id
                data[key] = value
        return data
