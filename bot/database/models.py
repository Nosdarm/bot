from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text, PrimaryKeyConstraint, Float, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any

Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'

    id = Column(String, primary_key=True)
    discord_id = Column(String, nullable=True)
    name_i18n = Column(JSON)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    selected_language = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    unspent_xp = Column(Integer, default=0)
    gold = Column(Integer, default=0)
    current_game_status = Column(String, nullable=True)
    collected_actions_json = Column(JSON, nullable=True)
    current_party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    guild_id = Column(String, nullable=False)
    stats = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True) # Was JSON, should be String if it's just action type/ID
    action_queue = Column(JSON, nullable=True)
    state_variables = Column(JSON, nullable=True)
    hp = Column(Float, nullable=True) # Changed to Float
    max_health = Column(Float, nullable=True) # Changed to Float
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSON, nullable=True)
    race = Column(String, nullable=True)
    mp = Column(Integer, nullable=True)
    attack = Column(Integer, nullable=True)
    defense = Column(Integer, nullable=True)
    skills_data_json = Column(JSON, nullable=True)
    abilities_data_json = Column(JSON, nullable=True)
    spells_data_json = Column(JSON, nullable=True)
    character_class = Column(String, nullable=True)
    flags_json = Column(JSON, nullable=True)
    active_quests = Column(JSON, nullable=True)
    known_spells = Column(JSON, nullable=True)
    spell_cooldowns = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    effective_stats_json = Column(JSON, nullable=True) # Verified already present

    location = relationship("Location")
    party = relationship("Party", foreign_keys=[current_party_id])

class Location(Base):
    __tablename__ = 'locations'
    id = Column(String, primary_key=True)
    static_name = Column(String, nullable=True)
    descriptions_i18n = Column(JSON, nullable=True)
    static_connections = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    exits = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    name_i18n = Column(JSON, nullable=True)
    template_id = Column(String, nullable=True)
    state_variables = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    details_i18n = Column(JSON, nullable=True)
    tags_i18n = Column(JSON, nullable=True)
    atmosphere_i18n = Column(JSON, nullable=True)
    features_i18n = Column(JSON, nullable=True)
    channel_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Location':
        if 'id' not in data or 'guild_id' not in data:
            raise ValueError("Location data must include 'id' and 'guild_id'.")
        i18n_fields = ['name_i18n', 'descriptions_i18n', 'details_i18n',
                       'tags_i18n', 'atmosphere_i18n', 'features_i18n']
        for field in i18n_fields: data.setdefault(field, {})
        json_fields_default_dict = ['exits', 'inventory', 'state_variables', 'static_connections']
        for field in json_fields_default_dict: data.setdefault(field, {})
        if data.get('is_active') is None: data['is_active'] = True
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "guild_id": self.guild_id, "template_id": self.template_id,
            "static_name": self.static_name, "name_i18n": self.name_i18n or {},
            "descriptions_i18n": self.descriptions_i18n or {}, "details_i18n": self.details_i18n or {},
            "tags_i18n": self.tags_i18n or {}, "atmosphere_i18n": self.atmosphere_i18n or {},
            "features_i18n": self.features_i18n or {}, "static_connections": self.static_connections or {},
            "exits": self.exits or {}, "inventory": self.inventory or {},
            "state_variables": self.state_variables or {}, "is_active": self.is_active,
            "channel_id": self.channel_id, "image_url": self.image_url,
        }

class Timer(Base):
    __tablename__ = 'timers'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)
    ends_at = Column(Float, nullable=False)
    callback_data = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    def __repr__(self): return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JSON, nullable=True)
    state_variables = Column(JSON, nullable=True)
    stages_data = Column(JSON, nullable=True)
    end_message_template_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)

class Party(Base):
    __tablename__ = 'parties'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    player_ids = Column(JSON, nullable=True)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)
    guild_id = Column(String, nullable=False)
    leader_id = Column(String, ForeignKey('players.id'), nullable=True)
    state_variables = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True) # Was JSON, should be String if it's just action type/ID
    location = relationship("Location")
    leader = relationship("Player", foreign_keys=[leader_id])

class RulesConfig(Base):
    __tablename__ = 'rules_config'
    id = Column(String, primary_key=True, default='main_config')
    config_data = Column(JSON)

class GeneratedLocation(Base): __tablename__ = 'generated_locations'; id = Column(String, primary_key=True); name_i18n = Column(JSON, nullable=True); descriptions_i18n = Column(JSON, nullable=True); details_i18n = Column(JSON, nullable=True); tags_i18n = Column(JSON, nullable=True); atmosphere_i18n = Column(JSON, nullable=True); features_i18n = Column(JSON, nullable=True)
class ItemTemplate(Base): __tablename__ = 'item_templates'; id = Column(String, primary_key=True); name_i18n = Column(JSON, nullable=False); description_i18n = Column(JSON, nullable=True); type = Column(String, nullable=True); properties = Column(JSON, nullable=True); guild_id = Column(String, nullable=True)
class LocationTemplate(Base): __tablename__ = 'location_templates'; id = Column(String, primary_key=True); name = Column(String, nullable=False); description = Column(Text, nullable=True); properties = Column(JSON, nullable=True); guild_id = Column(String, nullable=False)

class NPC(Base):
    __tablename__ = 'npcs'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    backstory_i18n = Column(JSON, nullable=True)
    persona_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    stats = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True) # Was JSON, should be String if it's just action type/ID
    action_queue = Column(JSON, nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    state_variables = Column(JSON, nullable=True)
    health = Column(Float, nullable=True) # Changed to Float
    max_health = Column(Float, nullable=True) # Changed to Float
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSON, nullable=True)
    is_temporary = Column(Boolean, default=False)
    archetype = Column(String, nullable=True)
    traits = Column(JSON, nullable=True)
    desires = Column(JSON, nullable=True)
    motives = Column(JSON, nullable=True)
    # Fields from migration v16 (ensure they are here)
    skills_data = Column(JSON, nullable=True)
    equipment_data = Column(JSON, nullable=True)
    abilities_data = Column(JSON, nullable=True)
    faction = Column(JSON, nullable=True) # Added from v16
    behavior_tags = Column(JSON, nullable=True) # Added from v16
    loot_table_id = Column(String, nullable=True) # Added from v16
    effective_stats_json = Column(JSON, nullable=True) # Added new field

    location = relationship("Location")
    party = relationship("Party")

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    backstory_i18n = Column(JSON, nullable=True)
    persona_i18n = Column(JSON, nullable=True)
    effective_stats_json = Column(JSON, nullable=True) # Already present

class GeneratedFaction(Base): __tablename__ = 'generated_factions'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)
class GeneratedQuest(Base): __tablename__ = 'generated_quests'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)

class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    guild_id = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    owner_type = Column(String, nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    quantity = Column(Integer, default=1)
    state_variables = Column(JSON, nullable=True)
    is_temporary = Column(Boolean, default=False)
    # Added from migration v16
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    properties = Column(JSON, nullable=True)
    slot = Column(String, nullable=True)
    value = Column(Integer, nullable=True)


class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True)
    player_id = Column(String, ForeignKey('players.id'), nullable=False)
    item_id = Column(String, ForeignKey('items.id'), nullable=False)
    quantity = Column(Integer, default=1)
    player = relationship("Player")
    item = relationship("Item")

class Combat(Base):
    __tablename__ = 'combats'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    is_active = Column(Boolean, default=True)
    participants = Column(JSON, nullable=True)
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True)
    state_variables = Column(JSON, nullable=True)
    channel_id = Column(String, nullable=True)
    event_id = Column(String, ForeignKey('events.id'), nullable=True)
    turn_order = Column(JSON, nullable=True)
    current_turn_index = Column(Integer, default=0)
    location = relationship("Location")
    event = relationship("Event")

class GlobalState(Base):
    __tablename__ = 'global_state'
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)

class GameLog(Base):
    __tablename__ = 'game_logs'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now())
    guild_id = Column(String, nullable=False, index=True)
    player_id = Column(String, ForeignKey('players.id'), nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    event_type = Column(String, nullable=False)
    message_key = Column(String, nullable=True)
    message_params = Column(JSON, nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    involved_entities_ids = Column(JSON, nullable=True)
    details = Column(JSON, nullable=False)
    channel_id = Column(String, nullable=True)
    player = relationship("Player")
    party = relationship("Party")
    location = relationship("Location")

class Relationship(Base): __tablename__ = 'relationships'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)
class PlayerNpcMemory(Base): __tablename__ = 'player_npc_memory'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)
class Ability(Base): __tablename__ = 'abilities'; id = Column(String, primary_key=True); name_i18n = Column(JSON, nullable=True); description_i18n = Column(JSON, nullable=True)
class Skill(Base): __tablename__ = 'skills'; id = Column(String, primary_key=True); name_i18n = Column(JSON, nullable=True); description_i18n = Column(JSON, nullable=True)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False) # Should be status_type or template_id
    status_type = Column(String, nullable=False) # Redundant with name if name is template_id
    target_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    duration_turns = Column(Float, nullable=True) # Changed to Float
    applied_at = Column(Float, nullable=True) # Changed to Float
    source_id = Column(String, nullable=True)
    state_variables = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    effects = Column(JSON, nullable=True) # This might be for dynamic effects, usually effects are from template
    name_i18n = Column(JSON, nullable=True) # Should come from template
    description_i18n = Column(JSON, nullable=True) # Should come from template

class CraftingQueue(Base):
    __tablename__ = 'crafting_queues'
    entity_id = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    guild_id = Column(String, nullable=False)
    queue = Column(JSON, nullable=True)
    state_variables = Column(JSON, nullable=True)
    __table_args__ = (PrimaryKeyConstraint('entity_id', 'entity_type', 'guild_id'),)

class ItemProperty(Base): __tablename__ = 'item_properties'; id = Column(String, primary_key=True); name_i18n = Column(JSON, nullable=True); description_i18n = Column(JSON, nullable=True)
class Questline(Base): __tablename__ = 'questlines'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)
class QuestStep(Base): __tablename__ = 'quest_steps'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)
class MobileGroup(Base): __tablename__ = 'mobile_groups'; id = Column(String, primary_key=True); placeholder = Column(Text, nullable=True)

class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    conflict_data_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True)
    resolution_data_json = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)
