# bot/game/models/combat.py
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

@dataclass
class CombatParticipant:
    entity_id: str
    entity_type: str # "Character", "NPC"
    hp: int
    max_hp: int
    initiative: Optional[int] = None
    acted_this_round: bool = False
    # Add other combat-specific temp stats if needed, e.g., temp_attack_bonus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "initiative": self.initiative,
            "acted_this_round": self.acted_this_round,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CombatParticipant":
        if not data or 'entity_id' not in data or 'entity_type' not in data:
            # Adding a print here for server-side debugging if needed
            print(f"DEBUG: CombatParticipant.from_dict missing critical keys. Data: {data}")
            raise ValueError("CombatParticipant.from_dict: data must include 'entity_id' and 'entity_type'.")
        return cls(
            entity_id=str(data["entity_id"]),
            entity_type=str(data["entity_type"]),
            hp=int(data.get("hp", 0)),
            max_hp=int(data.get("max_hp", 0)),
            initiative=int(data["initiative"]) if data.get("initiative") is not None else None,
            acted_this_round=bool(data.get("acted_this_round", False))
        )

@dataclass
class Combat:
    id: str
    guild_id: str
    is_active: bool = True
    channel_id: Optional[int] = None
    event_id: Optional[str] = None
    location_id: Optional[str] = None
    current_round: int = 1

    participants: List[CombatParticipant] = field(default_factory=list) # List of CombatParticipant objects

    # Turn management
    turn_order: List[str] = field(default_factory=list) # List of entity_ids in order of initiative
    current_turn_index: int = 0 # Index in turn_order for current actor

    combat_log: List[str] = field(default_factory=list) # Simple list of log strings
    state_variables: Dict[str, Any] = field(default_factory=dict)

    def get_current_actor_id(self) -> Optional[str]:
        if self.turn_order and 0 <= self.current_turn_index < len(self.turn_order):
            return self.turn_order[self.current_turn_index]
        return None

    def get_participant_data(self, entity_id: str) -> Optional[CombatParticipant]:
        for p in self.participants:
            if p.entity_id == entity_id:
                return p
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'guild_id': self.guild_id,
            'is_active': self.is_active,
            'channel_id': self.channel_id,
            'event_id': self.event_id,
            'location_id': self.location_id,
            'current_round': self.current_round,
            'participants': [p.to_dict() for p in self.participants],
            'turn_order': self.turn_order,
            'current_turn_index': self.current_turn_index,
            'combat_log': self.combat_log,
            'state_variables': self.state_variables,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Combat":
        if 'id' not in data or 'guild_id' not in data:
            event_id_context = data.get('event_id', 'UnknownEvent')
            print(f"DEBUG: Combat.from_dict CRITICAL Error: Data for combat model (event: {event_id_context}) must include 'id' and 'guild_id'. Data: {data}")
            raise ValueError("Combat.from_dict: data must include 'id' and 'guild_id'.")

        participants_data = data.get('participants', [])
        if not isinstance(participants_data, list):
            print(f"DEBUG: Combat Model from_dict Warning - participants data for combat {data.get('id')} is not a list. Defaulting to empty list.")
            participants_list = []
        else:
            participants_list = []
            for i, p_data in enumerate(participants_data):
                if isinstance(p_data, dict):
                    try:
                        participants_list.append(CombatParticipant.from_dict(p_data))
                    except ValueError as ve:
                        print(f"DEBUG: Combat Model from_dict Error creating CombatParticipant for combat {data.get('id')}, participant index {i}: {ve}. Participant data: {p_data}")
                else:
                    print(f"DEBUG: Combat Model from_dict Warning - participant data item at index {i} is not a dict for combat {data.get('id')}. Participant data: {p_data}")

        return Combat(
            id=str(data['id']),
            guild_id=str(data['guild_id']),
            is_active=bool(data.get('is_active', True)),
            channel_id=int(data['channel_id']) if data.get('channel_id') is not None else None,
            event_id=data.get('event_id'),
            location_id=data.get('location_id'),
            current_round=int(data.get('current_round', 1)),
            participants=participants_list,
            turn_order=data.get('turn_order', []),
            current_turn_index=int(data.get('current_turn_index', 0)),
            combat_log=data.get('combat_log', []),
            state_variables=data.get('state_variables', {})
        )

print("DEBUG: combat.py (model) loaded with CombatParticipant and updated Combat model.")
