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
        if 'hp' not in self.stats:
            self.stats['hp'] = self.hp
        else:
            self.hp = float(self.stats['hp'])

        if 'max_health' not in self.stats:
            self.stats['max_health'] = self.max_health
        else:
            self.max_health = float(self.stats['max_health'])

        if 'mana' not in self.stats:
            self.stats['mana'] = self.stats.get('max_mana', 50)
        if 'max_mana' not in self.stats:
            self.stats['max_mana'] = self.stats.get('mana', 50)
        if 'intelligence' not in self.stats:
            self.stats['intelligence'] = 10

        if self.collected_actions_json is not None and not isinstance(self.collected_actions_json, str):
            self.collected_actions_json = json.dumps(self.collected_actions_json)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        if 'guild_id' not in data:
            raise ValueError("Missing 'guild_id' key in data for Character.from_dict")
        if 'id' not in data or 'discord_user_id' not in data or ('name' not in data and 'name_i18n' not in data):
            raise ValueError("Missing core fields (id, discord_user_id, and name/name_i18n) for Character.from_dict")

        data_copy = data.copy()

        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        elif "name" in data_copy and "name_i18n" in data_copy:
            data_copy.pop("name")

        init_data = {
            'id': data_copy.get('id'),
            'discord_user_id': data_copy.get('discord_user_id'),
            'name_i18n': data_copy.get('name_i18n'),
            'guild_id': data_copy.get('guild_id'),
            'location_id': data_copy.get('location_id'),
            'stats': data_copy.get('stats', {}),
            'inventory': data_copy.get('inventory', []),
            'current_action': data_copy.get('current_action'),
            'action_queue': data_copy.get('action_queue', []),
            'party_id': data_copy.get('party_id'),
            'state_variables': data_copy.get('state_variables', {}),
            'hp': float(data_copy.get('hp', 100.0)),
            'max_health': float(data_copy.get('max_health', 100.0)),
            'is_alive': bool(data_copy.get('is_alive', True)),
            'status_effects': data_copy.get('status_effects', []),
            'level': int(data_copy.get('level', 1)),
            'experience': int(data_copy.get('experience', 0)),
            'unspent_xp': int(data_copy.get('unspent_xp', 0)),
            'active_quests': data_copy.get('active_quests', []),

            'known_spells': data_copy.get('known_spells', []),
            'spell_cooldowns': data_copy.get('spell_cooldowns', {}),
            'skills': data_copy.get('skills', {}),

            'known_abilities': data_copy.get('known_abilities', []),
            'ability_cooldowns': data_copy.get('ability_cooldowns', {}),
            'flags': data_copy.get('flags', []),
            'char_class': data_copy.get('char_class'),

            'selected_language': data_copy.get('selected_language'),
            'current_game_status': data_copy.get('current_game_status'),
            'collected_actions_json': data_copy.get('collected_actions_json') or data_copy.get('собранные_действия_JSON'),
            'current_party_id': data_copy.get('current_party_id'),
        }

        if 'hp' not in init_data['stats'] and 'hp' in data_copy:
            init_data['stats']['hp'] = init_data['hp']
        if 'max_health' not in init_data['stats'] and 'max_health' in data_copy:
            init_data['stats']['max_health'] = init_data['max_health']

        return cls(**init_data)

    def to_dict(self) -> Dict[str, Any]:
        if self.stats is None:
            self.stats = {}
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health

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
            "party_id": self.party_id,
            "state_variables": self.state_variables,
            "hp": self.hp,
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
            "collected_actions_json": self.collected_actions_json,
            "current_party_id": self.current_party_id,
        }
