from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

@dataclass
class Character:
    id: str
    discord_user_id: int
    name_i18n: Dict[str, str]
    guild_id: str

    location_id: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    current_action: Optional[Dict[str, Any]] = None
    action_queue: List[Dict[str, Any]] = field(default_factory=list)
    party_id: Optional[str] = None
    state_variables: Dict[str, Any] = field(default_factory=dict)

    hp: float = 100.0
    max_health: float = 100.0
    is_alive: bool = True

    status_effects: List[Dict[str, Any]] = field(default_factory=list)
    level: int = 1
    experience: int = 0
    unspent_xp: int = 0
    active_quests: List[str] = field(default_factory=list)

    known_spells: List[str] = field(default_factory=list)
    spell_cooldowns: Dict[str, float] = field(default_factory=dict)
    skills: Dict[str, int] = field(default_factory=dict)

    known_abilities: List[str] = field(default_factory=list)
    ability_cooldowns: Dict[str, float] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    char_class: Optional[str] = None

    selected_language: Optional[str] = None
    current_game_status: Optional[str] = None
    collected_actions_json: Optional[str] = None
    current_party_id: Optional[str] = None

    def __post_init__(self):
        # Ensure stats contains hp and max_health as numbers
        if 'hp' not in self.stats:
            self.stats['hp'] = self.hp
        else:
            # If loaded from stats, ensure the attribute is set
            self.hp = float(self.stats.get('hp', self.hp))

        if 'max_health' not in self.stats:
            self.stats['max_health'] = self.max_health
        else:
            # If loaded from stats, ensure the attribute is set
            self.max_health = float(self.stats.get('max_health', self.max_health))

        # Basic default stats if missing
        if 'mana' not in self.stats:
            self.stats['mana'] = self.stats.get('max_mana', 50)
        if 'max_mana' not in self.stats:
            self.stats['max_mana'] = self.stats.get('mana', 50)
        if 'intelligence' not in self.stats:
            self.stats['intelligence'] = 10
            
        # Ensure collected_actions_json is None or a string, dump if it's a dict/list (shouldn't happen if loaded correctly)
        # This might be overly cautious if DB adapter always returns str or None.
        # If data loaded from DB is already JSON string, this does nothing.
        # If data loaded from DB is None, this does nothing.
        # If data loaded from DB somehow became a Python object *before* reaching here, this tries to fix it.
        # print(f"DEBUG: __post_init__ checking collected_actions_json: {self.collected_actions_json}, type: {type(self.collected_actions_json)}") # Debugging line
        if self.collected_actions_json is not None and not isinstance(self.collected_actions_json, str):
             try:
                 self.collected_actions_json = json.dumps(self.collected_actions_json)
                 # print(f"DEBUG: __post_init__ dumped collected_actions_json to string.") # Debugging line
             except TypeError as e:
                 print(f"WARNING: Could not json.dumps collected_actions_json in __post_init__: {e}. Value was: {self.collected_actions_json}")
                 self.collected_actions_json = None # Or handle error appropriately
        # print(f"DEBUG: __post_init__ finished. collected_actions_json: {self.collected_actions_json}, type: {type(self.collected_actions_json)}") # Debugging line


    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        if 'guild_id' not in data:
            raise ValueError("Missing 'guild_id' key in data for Character.from_dict")
        if 'id' not in data or 'discord_user_id' not in data or ('name' not in data and 'name_i18n' not in data):
            raise ValueError("Missing core fields (id, discord_user_id, and name/name_i18n) for Character.from_dict")

        data_copy = data.copy()

        # Handle legacy 'name' field and prioritize 'name_i18n'
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        elif "name" in data_copy and "name_i18n" in data_copy:
             # If both exist, prefer name_i18n and remove name
             data_copy.pop("name")

        # Handle collected_actions_json with backward compatibility
        # Prioritize the new name, fall back to the old one
        collected_actions_data = data_copy.get('collected_actions_json')
        if collected_actions_data is None:
             collected_actions_data = data_copy.get('собранные_действия_JSON')

        # The DB should store this as TEXT or NULL. If it was previously stored as JSON TEXT,
        # the adapter's fetchone/fetchall with row_factory=Row might return a string.
        # If it was NULL, it might return None.
        # The __post_init__ check *might* handle cases where the adapter deserialized it automatically,
        # but it's better if the adapter returns raw TEXT.
        # If data was manually dumped/loaded as JSON strings, this path is correct.

        init_data = {
            'id': data_copy.get('id'),
            'discord_user_id': data_copy.get('discord_user_id'),
            'name_i18n': data_copy.get('name_i18n'),
            'guild_id': data_copy.get('guild_id'),
            'location_id': data_copy.get('location_id'),
            'stats': data_copy.get('stats', {}), # Use default empty dict
            'inventory': data_copy.get('inventory', []), # Use default empty list
            'current_action': data_copy.get('current_action'), # Can be None
            'action_queue': data_copy.get('action_queue', []), # Use default empty list
            'party_id': data_copy.get('party_id'), # Can be None
            'state_variables': data_copy.get('state_variables', {}), # Use default empty dict

            # Load hp/max_health, prioritizing explicit columns if they exist, falling back to stats if needed, then defaults
            'hp': float(data_copy.get('hp', data_copy['stats'].get('hp', 100.0)) if 'stats' in data_copy else data_copy.get('hp', 100.0)),
            'max_health': float(data_copy.get('max_health', data_copy['stats'].get('max_health', 100.0)) if 'stats' in data_copy else data_copy.get('max_health', 100.0)),

            'is_alive': bool(data_copy.get('is_alive', True)),
            'status_effects': data_copy.get('status_effects', []), # Use default empty list
            'level': int(data_copy.get('level', 1)),
            'experience': int(data_copy.get('experience', 0)),
            'unspent_xp': int(data_copy.get('unspent_xp', 0)), # Added in v12, ensure default
            'active_quests': data_copy.get('active_quests', []), # Use default empty list

            'known_spells': data_copy.get('known_spells', []), # Use default empty list
            'spell_cooldowns': data_copy.get('spell_cooldowns', {}), # Use default empty dict
            'skills': data_copy.get('skills', {}), # Use default empty dict

            'known_abilities': data_copy.get('known_abilities', []), # Use default empty list
            'ability_cooldowns': data_copy.get('ability_cooldowns', {}), # Use default empty dict
            'flags': data_copy.get('flags', []), # Use default empty list
            'char_class': data_copy.get('char_class'), # Can be None

            'selected_language': data_copy.get('selected_language'), # Can be None
            'current_game_status': data_copy.get('current_game_status'), # Can be None
            'collected_actions_json': collected_actions_data, # Use the value retrieved handling old/new names
            'current_party_id': data_copy.get('current_party_id'), # Can be None
            # Note: 'race', 'mp', 'attack', 'defense' added in v4 migration are implicitly handled if present in data['stats'] or explicitly in data_copy
        }

        # Ensure hp/max_health are in stats dict as well, for consistency if stats are accessed directly later
        # __post_init__ handles syncing the attribute values back into the stats dict *if* stats is not None initially.
        # Let's ensure stats is populated with these values upon loading if they were loaded explicitly.
        if 'stats' in init_data:
             # Ensure float conversion if they weren't already
             init_data['stats']['hp'] = float(init_data['hp'])
             init_data['stats']['max_health'] = float(init_data['max_health'])
        else: # If stats somehow wasn't loaded or was None
             init_data['stats'] = {'hp': float(init_data['hp']), 'max_health': float(init_data['max_health'])}


        return cls(**init_data)

    def to_dict(self) -> Dict[str, Any]:
        # Ensure stats dict exists and contains hp/max_health before returning
        if self.stats is None:
            self.stats = {}
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health

        # Include all attributes explicitly for clarity and completeness
        # This ensures all potentially stored fields are serialized
        return {
            "id": self.id,
            "discord_user_id": self.discord_user_id,
            "name_i18n": self.name_i18n,
            "guild_id": self.guild_id,
            "location_id": self.location_id,
            "stats": self.stats,
            "inventory": self.inventory,
            "current_action": self.current_action,
            "action_queue": self.action_queue,
            "party_id": self.party_id, # This is the old field, possibly deprecated by current_party_id
            "state_variables": self.state_variables,
            "hp": self.hp, # Explicitly save hp/max_health outside stats as well (matches schema)
            "max_health": self.max_health,
            "is_alive": self.is_alive,
            "status_effects": self.status_effects,
            "level": self.level,
            "experience": self.experience,
            "unspent_xp": self.unspent_xp,
            "active_quests": self.active_quests,
            "known_spells": self.known_spells,
            "spell_cooldowns": self.spell_cooldowns,
            "skills": self.skills,
            "known_abilities": self.known_abilities,
            "ability_cooldowns": self.ability_cooldowns,
            "flags": self.flags,
            "char_class": self.char_class,
            "selected_language": self.selected_language,
            "current_game_status": self.current_game_status,
            "collected_actions_json": self.collected_actions_json, # **Included as requested**
            "current_party_id": self.current_party_id,
            # Attributes added in v4 like race, mp, attack, defense might implicitly be in stats or need explicit handling if not.
            # Based on the from_dict logic, it seems they were intended to be loaded into stats implicitly or handled explicitly there.
            # Adding them explicitly here mirrors the from_dict structure for completeness if they were Character attributes
            # "race": self.race, # If race etc were Character attributes
            # "mp": self.mp,
            # "attack": self.attack,
            # "defense": self.defense,
        }
