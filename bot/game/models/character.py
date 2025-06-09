# В bot/game/models/character.py
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field # Import dataclass and field
from bot.utils.i18n_utils import get_i18n_text # Import the new utility

# TODO: Импортировать другие модели, если Character имеет на них ссылки (напр., Item)
# from bot.game.models.item import Item

@dataclass
class Character:
    id: str
    discord_user_id: int
    # name: str # This will become a property
    name_i18n: Dict[str, str] # e.g., {"en": "Name", "ru": "Имя"}
    guild_id: str
    selected_language: Optional[str] = "en" # Player's preferred language, default to 'en'
    
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

    # New data fields (replacing/enhancing old 'skills', 'flags')
    skills_data: List[Dict[str, Any]] = field(default_factory=list) # e.g., [{"skill_id": "mining", "level": 5, "xp": 120}]
    abilities_data: List[Dict[str, Any]] = field(default_factory=list) # e.g., [{"ability_id": "power_strike", "rank": 1}]
    spells_data: List[Dict[str, Any]] = field(default_factory=list) # e.g., [{"spell_id": "fireball", "mastery": 75}]
    character_class: Optional[str] = None # Character class, e.g., "warrior", "mage" - (already existed, just confirming)
    flags: Dict[str, bool] = field(default_factory=dict) # More structured flags, e.g., {"is_poison_immune": True}
    gold: int = 0

    # Old fields that might be superseded or need review if they are still populated from DB in CharacterManager
    skills: Dict[str, int] = field(default_factory=dict) # skill_name -> level, (Potentially redundant if skills_data is primary)
    known_abilities: List[str] = field(default_factory=list) # List of ability_ids (Potentially redundant if abilities_data is primary)
    # 'flags' above is now Dict[str, bool], old 'flags: List[str]' is replaced.
    # 'char_class' is fine.

    # New fields for player status and preferences
    # selected_language: Optional[str] = None # Player's preferred language - MOVED UP
    current_game_status: Optional[str] = None # E.g., "active", "paused", "in_tutorial"
    collected_actions_json: Optional[str] = None # JSON string of collected actions (DB column name)
    current_party_id: Optional[str] = None # ID of the party the player is currently in (fk to parties table)

    # Catch-all for any other fields that might come from data
    # This is less common with dataclasses as fields are explicit, but can be used if __post_init__ handles it.
    # For now, we'll assume all relevant fields are explicitly defined.
    # extra_fields: Dict[str, Any] = field(default_factory=dict)


    def __post_init__(self):
        print(f"Character.__post_init__: Character {self.id} initialized. self.location_id: {self.location_id}, type: {type(self.location_id)}")
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

    @property
    def name(self) -> str:
        """Returns the internationalized name of the character."""
        # Assumes GameManager.get_default_bot_language() will be the ultimate source for default_lang.
        # For now, hardcoding "en" as a fallback if self.selected_language is None.
        # A more robust solution would involve passing game_manager or settings to access the global default.
        # However, selected_language should ideally always be set for a character.
        character_specific_lang = self.selected_language if self.selected_language else "en"
        # The default_lang for get_i18n_text should ideally be the global default ("en" typically)
        return get_i18n_text(self.to_dict_for_i18n_name(), "name", character_specific_lang, "en")

    def to_dict_for_i18n_name(self) -> Dict[str, Any]:
        """Helper to provide a dictionary structure for get_i18n_text for the name property."""
        return {"name_i18n": self.name_i18n, "id": self.id}


    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        """Creates a Character instance from a dictionary."""
        if 'guild_id' not in data:
            raise ValueError("Missing 'guild_id' key in data for Character.from_dict")
        if 'id' not in data or 'discord_user_id' not in data:
            raise ValueError("Missing core fields (id, discord_user_id) for Character.from_dict")

        if 'name_i18n' not in data:
            if 'name' in data: # Backwards compatibility if only 'name' (string) is provided
                print(f"Warning: Character '{data.get('id')}' is missing 'name_i18n', creating from 'name'. Consider updating data source.")
                data['name_i18n'] = {'en': data['name']} # Default to English
            else: # If neither name_i18n nor name is present
                print(f"Warning: Character '{data.get('id')}' is missing 'name_i18n' and 'name'. Using ID as fallback name.")
                data['name_i18n'] = {'en': data['id']}


        # Populate known fields, providing defaults for new/optional ones if missing in data
        init_data = {
            'id': data.get('id'),
            'discord_user_id': data.get('discord_user_id'),
            # 'name' is now a property, not passed to __init__
            'name_i18n': data.get('name_i18n'),
            'guild_id': data.get('guild_id'),
            'selected_language': data.get('selected_language', "en"), # Default to "en"
            'location_id': data.get('location_id'),
            'stats': data.get('stats', {}),
            'inventory': data.get('inventory', []),
            'current_action': data.get('current_action'),
            'action_queue': data.get('action_queue', []),
            'party_id': data.get('party_id'),
            'state_variables': data.get('state_variables', {}),
            'hp': float(data.get('hp', 100.0)),
            'max_health': float(data.get('max_health', 100.0)),
            'is_alive': bool(data.get('is_alive', True)),
            'status_effects': data.get('status_effects', []),
            'level': int(data.get('level', 1)),
            'experience': int(data.get('experience', 0)),
            'unspent_xp': int(data.get('unspent_xp', 0)),
            'active_quests': data.get('active_quests', []),
            
            'known_spells': data.get('known_spells', []),
            'spell_cooldowns': data.get('spell_cooldowns', {}),

            # Updated/New fields
            'skills_data': data.get('skills_data', []), # Expecting list from manager
            'abilities_data': data.get('abilities_data', []), # Expecting list from manager
            'spells_data': data.get('spells_data', []), # Expecting list from manager
            'character_class': data.get('character_class'),
            'flags': data.get('flags', {}), # Expecting dict from manager (was List[str] before)
            'gold': int(data.get('gold', 0)),

            # Old fields that might be populated by manager for backward compatibility from DB
            'skills': data.get('skills', {}),
            'known_abilities': data.get('known_abilities', []),

            # 'selected_language' moved up
            'current_game_status': data.get('current_game_status'),
            'collected_actions_json': data.get('collected_actions_json', data.get('собранные_действия_JSON')), # Handle old key
            'current_party_id': data.get('current_party_id'),
        }
        
        # If stats from data doesn't have health/max_health, use the top-level ones
        if 'hp' not in init_data['stats'] and 'hp' in init_data :
             init_data['stats']['hp'] = init_data['hp']
        if 'max_health' not in init_data['stats'] and 'max_health' in init_data:
             init_data['stats']['max_health'] = init_data['max_health']
        print(f"Character.from_dict: Initializing Character {init_data.get('id')}. location_id in init_data: {init_data.get('location_id')}, type: {type(init_data.get('location_id'))}")
        return cls(**init_data)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Character instance to a dictionary for serialization."""
        # Ensure stats reflects current health/max_health before saving
        if self.stats is None: self.stats = {}
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health
        
        # name_i18n is the source of truth. The 'name' property handles dynamic lookup.
        # When serializing, we primarily need name_i18n.
        # Including 'name' (the resolved one) can be useful for debugging or direct display if lang is fixed.
        return {
            "id": self.id,
            "discord_user_id": self.discord_user_id,
            "name": self.name, # Include the resolved name for convenience
            "name_i18n": self.name_i18n,
            "guild_id": self.guild_id,
            "selected_language": self.selected_language,
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
            "status_effects": self.status_effects,
            "level": self.level,
            "experience": self.experience,
            "unspent_xp": self.unspent_xp,
            "active_quests": self.active_quests,
            "known_spells": self.known_spells,
            "spell_cooldowns": self.spell_cooldowns,
            
            # Updated/New fields
            "skills_data": self.skills_data,
            "abilities_data": self.abilities_data,
            "spells_data": self.spells_data,
            "character_class": self.character_class, # Was char_class before, standardizing to character_class
            "flags": self.flags, # Now Dict[str, bool]
            "gold": self.gold,

            # Old fields that might still be part of the model for some reason (review if needed)
            "skills": self.skills, # Potentially redundant
            "known_abilities": self.known_abilities, # Potentially redundant

            "selected_language": self.selected_language,
            "current_game_status": self.current_game_status,
            "collected_actions_json": self.collected_actions_json, # Using standardized key
            "current_party_id": self.current_party_id,
        }

    def clear_collected_actions(self) -> None:
        """Clears the collected_actions_json attribute."""
        self.collected_actions_json = None

    # TODO: Other methods for character logic, e.g.,
    # def take_damage(self, amount: float): ...
    # def heal(self, amount: float): ...
    # def add_item_to_inventory(self, item_data: Dict[str, Any]): ...
    # def learn_new_spell(self, spell_id: str): ...
    # def set_cooldown(self, spell_id: str, cooldown_end_time: float): ...
    # def get_skill_level(self, skill_name: str) -> int: ...
