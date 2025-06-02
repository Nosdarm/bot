# bot/nlu/nlu_data_types.py
from typing import TypedDict, Literal

class NLUEntity(TypedDict):
    id: str       # The unique ID of the entity in the database
    name: str     # The name of the entity in the specified language
    type: Literal["location", "npc", "item", "skill", "direction", "target_name", "location_name", "item_name", "npc_name", "skill_name", "search_target"] # Type of the entity
    lang: str     # Language of the 'name' field
    # Optional: Add other relevant fields, like a canonical name if different from the display name
    # canonical_name: Optional[str]

# Example of how it might be used in the parser's entity list:
# entities_list: List[Dict[str, str]] could become List[Union[NLUEntity, Dict[str,str]]]
# or the parser could transform its findings into NLUEntity structure where applicable.
# For now, the parser will likely produce dicts like:
# {"type": "location", "id": "loc_001", "name": "Forest of Whispers"}
# NLUEntity is more for the data coming *from* NLUDataService.

