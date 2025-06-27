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

    effective_stats_json: Optional[str] = None # For storing calculated effective stats as JSON


    def __post_init__(self):
        # print(f"Character.__post_init__: Character {self.id} initialized. self.location_id: {self.location_id}, type: {type(self.location_id)}")
        # Ensure basic stats are present if not provided, especially health/max_health
        # This also helps bridge the gap if health/max_health were not in stats from older data.
        if not isinstance(self.stats, dict): # Ensure stats is a dict
            self.stats = {}

        if 'hp' not in self.stats:
            self.stats['hp'] = self.hp
        else:
            try: self.hp = float(self.stats['hp'])
            except (ValueError, TypeError): self.hp = 100.0 # Default if conversion fails

        if 'max_health' not in self.stats:
            self.stats['max_health'] = self.max_health
        else:
            try: self.max_health = float(self.stats['max_health'])
            except (ValueError, TypeError): self.max_health = 100.0 # Default

        # Ensure mana and intelligence are present for spellcasting if not already
        if 'mana' not in self.stats:
            self.stats['mana'] = self.stats.get('max_mana', 50)
        if 'max_mana' not in self.stats:
            self.stats['max_mana'] = self.stats.get('mana', 50)
        if 'intelligence' not in self.stats:
            self.stats['intelligence'] = 10

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
    def from_db_model(cls, db_model: Any) -> Character: # db_model is CharacterDBModel from .database.models
        """Creates a Pydantic Character instance from a CharacterDBModel (SQLAlchemy) instance."""
        if not db_model:
            raise ValueError("db_model cannot be None for Character.from_db_model")

        data = {field_name: getattr(db_model, field_name, None) for field_name in cls.__annotations__}

        # Handle JSON string fields that need parsing
        json_fields = ["stats", "inventory", "status_effects", "spell_cooldowns",
                       "skills_data", "abilities_data", "spells_data", "flags",
                       "state_variables", "name_i18n", "current_action", "action_queue", "effective_stats_json"]

        for field_name in json_fields:
            json_str_val = getattr(db_model, field_name, None)
            if isinstance(json_str_val, str):
                try:
                    data[field_name] = json.loads(json_str_val)
                except json.JSONDecodeError:
                    # Default to empty dict/list based on expected type if parsing fails
                    if field_name in ["inventory", "status_effects", "skills_data", "abilities_data", "spells_data"]:
                        data[field_name] = []
                    else:
                        data[field_name] = {}
                    # print(f"Warning: Character '{db_model.id}' has malformed JSON in '{field_name}'. Using default.")
            elif json_str_val is None: # If None in DB, ensure correct default for Pydantic model
                 if field_name in ["inventory", "status_effects", "skills_data", "abilities_data", "spells_data"]: data[field_name] = []
                 elif field_name == "effective_stats_json": data[field_name] = None # This specific field is Optional[str]
                 else: data[field_name] = {}


        # Ensure required fields that might not be direct DB columns are set
        data['id'] = str(db_model.id) # Ensure ID is string
        data['discord_user_id'] = int(db_model.discord_user_id) if db_model.discord_user_id is not None else 0
        data['guild_id'] = str(db_model.guild_id)
        data['selected_language'] = db_model.selected_language or "en"
        data['location_id'] = str(db_model.location_id) if db_model.location_id is not None else None
        data['hp'] = float(db_model.hp)
        data['max_health'] = float(db_model.max_health)
        data['level'] = int(db_model.level)
        data['experience'] = int(db_model.xp) # map xp from DB to experience
        data['unspent_xp'] = int(db_model.unspent_xp)
        data['gold'] = int(db_model.gold)
        data['is_alive'] = bool(db_model.is_alive)

        # Ensure name_i18n is a dict
        if not isinstance(data.get('name_i18n'), dict):
            data['name_i18n'] = {'en': str(db_model.id)} # Fallback

        # collected_actions_json is already a string, keep as is
        data['collected_actions_json'] = db_model.collected_actions_json

        # Filter out keys not in Pydantic model to prevent unexpected argument errors
        # This is important if db_model has more fields than Pydantic model
        model_fields = cls.__annotations__.keys()
        init_data = {k: v for k, v in data.items() if k in model_fields}

        return cls(**init_data)

    def to_db_dict(self) -> Dict[str, Any]:
        """Converts the Pydantic Character instance to a dictionary suitable for CharacterDBModel."""
        db_dict = self.to_dict() # Start with the existing to_dict for most fields

        # Fields that need to be JSON strings for the database
        json_string_fields = [
            "stats", "inventory", "status_effects", "spell_cooldowns",
            "skills_data", "abilities_data", "spells_data", "flags",
            "state_variables", "name_i18n", "current_action", "action_queue", "effective_stats_json"
        ]
        for field_name in json_string_fields:
            if field_name in db_dict and db_dict[field_name] is not None:
                db_dict[field_name] = json.dumps(db_dict[field_name])
            elif field_name == "effective_stats_json": # This one can be None
                 db_dict[field_name] = None
            else: # For other fields that might be None but DB expects string (e.g. "[]" or "{}")
                # Default to empty JSON string if None, unless it's truly nullable in DB
                # For simplicity, let's assume most are "{}", "[]" if not None
                if field_name in ["inventory", "status_effects", "skills_data", "abilities_data", "spells_data"]:
                    db_dict[field_name] = json.dumps(db_dict.get(field_name) or [])
                else:
                    db_dict[field_name] = json.dumps(db_dict.get(field_name) or {})


        # Map Pydantic field names to DB column names if they differ
        # Example: Pydantic 'experience' maps to DB 'xp'
        if 'experience' in db_dict:
            db_dict['xp'] = db_dict.pop('experience')

        # Remove fields from db_dict that are not direct columns in CharacterDBModel
        # (e.g., 'name' property if it's not a column)
        db_model_columns = [
            "id", "discord_user_id", "name_i18n", "guild_id", "selected_language",
            "location_id", "stats", "inventory", "current_action", "action_queue",
            "party_id", "state_variables", "hp", "max_health", "is_alive",
            "status_effects", "level", "xp", "unspent_xp", "active_quests",
            "known_spells", "spell_cooldowns", "skills_data", "abilities_data",
            "spells_data", "character_class", "flags", "gold", "skills", "known_abilities",
            "current_game_status", "collected_actions_json", "current_party_id",
            "player_id", "effective_stats_json" # player_id is a DB column
        ]
        final_db_dict = {k: v for k, v in db_dict.items() if k in db_model_columns}

        return final_db_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character: # Kept for compatibility if used elsewhere
        """Creates a Character instance from a dictionary. (Legacy or for non-DB sources)"""
        # This from_dict is more for generic dicts, not specifically DB models
        # The new from_db_model is preferred for SQLAlchemy instances.

        # Simplified: assumes data keys match dataclass fields mostly.
        # More robust parsing/validation might be needed if structure varies wildly.

        # Ensure essential IDs are present and correctly typed
        data['id'] = str(data.get('id', uuid.uuid4()))
        data['discord_user_id'] = int(data.get('discord_user_id', 0))
        data['guild_id'] = str(data.get('guild_id', 'unknown_guild'))

        # Handle name_i18n carefully
        if 'name_i18n' not in data or not isinstance(data['name_i18n'], dict):
            name_val = data.get('name', data['id']) # Fallback to name, then id
            data['name_i18n'] = {'en': str(name_val)}

        # Default selected_language
        data['selected_language'] = data.get('selected_language', 'en')

        # Ensure numeric types
        for key in ['hp', 'max_health']:
            data[key] = float(data.get(key, 100.0))
        for key in ['level', 'experience', 'unspent_xp', 'gold']:
            data[key] = int(data.get(key, 0 if key != 'level' else 1))
        data['is_alive'] = bool(data.get('is_alive', True))

        # Ensure list/dict types for JSON-like fields
        list_fields = ['inventory', 'status_effects', 'active_quests', 'known_spells',
                       'skills_data', 'abilities_data', 'spells_data', 'known_abilities', 'action_queue']
        dict_fields = ['stats', 'spell_cooldowns', 'flags', 'state_variables', 'current_action']

        for lf in list_fields:
            val = data.get(lf)
            if isinstance(val, str): data[lf] = json.loads(val) if val else []
            elif not isinstance(val, list): data[lf] = []

        for df in dict_fields:
            val = data.get(df)
            if isinstance(val, str): data[df] = json.loads(val) if val else {}
            elif not isinstance(val, dict): data[df] = {}

        # Ensure location_id is string or None
        loc_id = data.get('location_id', data.get('current_location_id'))
        data['location_id'] = str(loc_id) if loc_id is not None else None

        # Filter to only include fields defined in the dataclass
        model_fields = cls.__annotations__.keys()
        init_data = {k: v for k, v in data.items() if k in model_fields}

        # print(f"Character.from_dict (generic): Initializing Character {init_data.get('id')}. location_id: {init_data.get('location_id')}")
        return cls(**init_data)


    def to_dict(self) -> Dict[str, Any]:
        """Converts the Character instance to a dictionary for general serialization."""
        if self.stats is None: self.stats = {} # Ensure stats is not None
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health

        return {
            "id": self.id, "discord_user_id": self.discord_user_id,
            "name": self.name, "name_i18n": self.name_i18n, "guild_id": self.guild_id,
            "selected_language": self.selected_language, "location_id": self.location_id,
            "stats": self.stats, "inventory": self.inventory,
            "current_action": self.current_action, "action_queue": self.action_queue,
            "party_id": self.party_id, "state_variables": self.state_variables,
            "hp": self.hp, "max_health": self.max_health, "is_alive": self.is_alive,
            "status_effects": self.status_effects, "level": self.level,
            "experience": self.experience, "unspent_xp": self.unspent_xp,
            "active_quests": self.active_quests, "known_spells": self.known_spells,
            "spell_cooldowns": self.spell_cooldowns, "skills_data": self.skills_data,
            "abilities_data": self.abilities_data, "spells_data": self.spells_data,
            "character_class": self.character_class, "flags": self.flags, "gold": self.gold,
            "skills": self.skills, "known_abilities": self.known_abilities,
            "current_game_status": self.current_game_status,
            "collected_actions_json": self.collected_actions_json,
            "current_party_id": self.current_party_id,
            "effective_stats_json": self.effective_stats_json
        }

    def clear_collected_actions(self) -> None:
        """Clears the collected_actions_json attribute."""
        self.collected_actions_json = None
