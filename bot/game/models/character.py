# В bot/game/models/character.py
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field # Import dataclass and field

# TODO: Импортировать другие модели, если Character имеет на них ссылки (напр., Item)
# from bot.game.models.item import Item

@dataclass
class Character:
    id: str
    discord_user_id: int
    name: str
    guild_id: str
    
    location_id: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict) # e.g., {"health": 100, "mana": 50, "strength": 10, "intelligence": 12}
    inventory: List[Dict[str, Any]] = field(default_factory=list) # List of item instance dicts or Item objects
    current_action: Optional[Dict[str, Any]] = None
    action_queue: List[Dict[str, Any]] = field(default_factory=list)
    party_id: Optional[str] = None
    state_variables: Dict[str, Any] = field(default_factory=dict) # For quests, flags, etc.
    
    # Attributes that might have been separate but often make sense within stats or derived
    hp: float = 100.0 # Current health, often also in stats for convenience
    max_health: float = 100.0 # Max health, often also in stats
    is_alive: bool = True
    
    status_effects: List[Dict[str, Any]] = field(default_factory=list) # List of status effect instances (or their dicts)
    level: int = 1
    experience: int = 0  # This will be treated as 'xp'
    unspent_xp: int = 0
    active_quests: List[str] = field(default_factory=list) # List of quest IDs

    # Spell Management Fields
    known_spells: List[str] = field(default_factory=list) # List of spell_ids
    spell_cooldowns: Dict[str, float] = field(default_factory=dict) # spell_id -> cooldown_end_timestamp
    skills: Dict[str, int] = field(default_factory=dict) # skill_name -> level, e.g., {"evocation": 5, "first_aid": 2}

    # Ability Management Fields
    known_abilities: List[str] = field(default_factory=list) # List of ability_ids
    ability_cooldowns: Dict[str, float] = field(default_factory=dict) # ability_id -> cooldown_end_timestamp
    flags: List[str] = field(default_factory=list) # List of flags, e.g., "darkvision", "immune_to_poison"
    char_class: Optional[str] = None # Character class, e.g., "warrior", "mage"

    # New fields for player status and preferences
    selected_language: Optional[str] = None # Player's preferred language
    current_game_status: Optional[str] = None # E.g., "active", "paused", "in_tutorial"
    collected_actions_json: Optional[str] = None # JSON string of collected actions
    current_party_id: Optional[str] = None # ID of the party the player is currently in (fk to parties table)

    # Catch-all for any other fields that might come from data
    # This is less common with dataclasses as fields are explicit, but can be used if __post_init__ handles it.
    # For now, we'll assume all relevant fields are explicitly defined.
    # extra_fields: Dict[str, Any] = field(default_factory=dict)


    def __post_init__(self):
        # Ensure basic stats are present if not provided, especially health/max_health
        # This also helps bridge the gap if health/max_health were not in stats from older data.
        if 'hp' not in self.stats:
            self.stats['hp'] = self.hp
        else:
            self.hp = float(self.stats['hp'])

        if 'max_health' not in self.stats:
            self.stats['max_health'] = self.max_health
        else:
            self.max_health = float(self.stats['max_health'])
        
        # Ensure mana and intelligence are present for spellcasting if not already
        if 'mana' not in self.stats:
            self.stats['mana'] = self.stats.get('max_mana', 50) # Default mana if not set
        if 'max_mana' not in self.stats: # Assuming max_mana is a stat
            self.stats['max_mana'] = self.stats.get('mana', 50)
        if 'intelligence' not in self.stats:
            self.stats['intelligence'] = 10 # Default intelligence

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        """Creates a Character instance from a dictionary."""
        if 'guild_id' not in data:
            raise ValueError("Missing 'guild_id' key in data for Character.from_dict")
        if 'id' not in data or 'discord_user_id' not in data or 'name' not in data:
            raise ValueError("Missing core fields (id, discord_user_id, name) for Character.from_dict")

        # Populate known fields, providing defaults for new/optional ones if missing in data
        init_data = {
            'id': data.get('id'),
            'discord_user_id': data.get('discord_user_id'),
            'name': data.get('name'),
            'guild_id': data.get('guild_id'),
            'location_id': data.get('location_id'),
            'stats': data.get('stats', {}), # Ensure stats is at least an empty dict
            'inventory': data.get('inventory', []),
            'current_action': data.get('current_action'),
            'action_queue': data.get('action_queue', []),
            'party_id': data.get('party_id'),
            'state_variables': data.get('state_variables', {}),
            'hp': float(data.get('hp', 100.0)), # Ensure float
            'max_health': float(data.get('max_health', 100.0)), # Ensure float
            'is_alive': bool(data.get('is_alive', True)), # Ensure bool
            'status_effects': data.get('status_effects', []),
            'level': int(data.get('level', 1)), # Ensure int
            'experience': int(data.get('experience', 0)), # Ensure int
            'unspent_xp': int(data.get('unspent_xp', 0)), # Ensure int
            'active_quests': data.get('active_quests', []),
            
            # New spell-related fields with defaults for backward compatibility
            'known_spells': data.get('known_spells', []),
            'spell_cooldowns': data.get('spell_cooldowns', {}),
            'skills': data.get('skills', {}),

            # New ability-related fields
            'known_abilities': data.get('known_abilities', []),
            'ability_cooldowns': data.get('ability_cooldowns', {}),
            'flags': data.get('flags', []),
            'char_class': data.get('char_class'), # Defaults to None if missing, which is fine for Optional[str]

            # New fields
            'selected_language': data.get('selected_language'),
            'current_game_status': data.get('current_game_status'),
            'collected_actions_json': data.get('collected_actions_json'),
            'current_party_id': data.get('current_party_id'),
        }
        
        # If stats from data doesn't have health/max_health, use the top-level ones
        if 'hp' not in init_data['stats'] and 'hp' in data : # hp might be in stats or top-level
             init_data['stats']['hp'] = init_data['hp']
        if 'max_health' not in init_data['stats'] and 'max_health' in data:
             init_data['stats']['max_health'] = init_data['max_health']


        return cls(**init_data)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Character instance to a dictionary for serialization."""
        # dataclasses.asdict(self) could be used for simple cases,
        # but a manual approach gives more control if needed (e.g., for complex objects in fields)
        # For now, a direct mapping of fields should be fine.
        
        # Ensure stats reflects current health/max_health before saving
        # This is important if self.hp is modified directly elsewhere
        # and should be the source of truth for stats dict.
        if self.stats is None: self.stats = {} # Should be initialized by default_factory
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health
        
        return {
            "id": self.id,
            "discord_user_id": self.discord_user_id,
            "name": self.name,
            "guild_id": self.guild_id,
            "location_id": self.location_id,
            "stats": self.stats,
            "inventory": self.inventory, # Assuming items are dicts or simple serializable objects
            "current_action": self.current_action,
            "action_queue": self.action_queue,
            "party_id": self.party_id,
            "state_variables": self.state_variables,
            "hp": self.hp, # Redundant if always in stats, but good for direct access
            "max_health": self.max_health, # Redundant if always in stats
            "is_alive": self.is_alive,
            "status_effects": self.status_effects, # Assuming status effects are dicts or serializable
            "level": self.level,
            "experience": self.experience,
            "unspent_xp": self.unspent_xp,
            "active_quests": self.active_quests,
            "known_spells": self.known_spells,
            "spell_cooldowns": self.spell_cooldowns,
            "skills": self.skills,
            
            # Ability-related fields
            "known_abilities": self.known_abilities,
            "ability_cooldowns": self.ability_cooldowns,
            "flags": self.flags,
            "char_class": self.char_class,

            # New fields
            "selected_language": self.selected_language,
            "current_game_status": self.current_game_status,
            "collected_actions_json": self.collected_actions_json,
            "current_party_id": self.current_party_id,
        }

    # TODO: Other methods for character logic, e.g.,
    # def take_damage(self, amount: float): ...
    # def heal(self, amount: float): ...
    # def add_item_to_inventory(self, item_data: Dict[str, Any]): ...
    # def learn_new_spell(self, spell_id: str): ...
    # def set_cooldown(self, spell_id: str, cooldown_end_time: float): ...
    # def get_skill_level(self, skill_name: str) -> int: ...