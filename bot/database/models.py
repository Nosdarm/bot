from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text, PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    location = relationship("Location")
    party = relationship("Party", foreign_keys=[current_party_id])
    characters = relationship("Character", back_populates="player", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint('discord_id', 'guild_id', name='uq_player_discord_guild'),)


class Character(Base):
    __tablename__ = 'characters'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String, ForeignKey('players.id'), nullable=False, index=True)
    guild_id = Column(String, nullable=False, index=True) # Denormalized for easier querying

    name_i18n = Column(JSON, nullable=False)  # e.g., {"en": "Valerius", "ru": "Валериус"}
    class_i18n = Column(JSON, nullable=True)   # e.g., {"en": "Warrior", "ru": "Воин"}
    description_i18n = Column(JSON, nullable=True) # e.g., {"en": "A brave warrior.", "ru": "Храбрый воин."}

    level = Column(Integer, default=1, nullable=False)
    xp = Column(Integer, default=0, nullable=False)

    stats = Column(JSON, nullable=True) # e.g., {"strength": 10, "dexterity": 8, "intelligence": 5}
    current_hp = Column(Float, nullable=True)
    max_hp = Column(Float, nullable=True)

    abilities = Column(JSON, nullable=True) # Could be a list of IDs or more complex objects
    inventory = Column(JSON, nullable=True) # Could be a list of item IDs or more complex objects

    # Stores relationships with NPCs, e.g., {"npc_id_1": "friendly", "npc_id_2": "hostile"}
    npc_relationships = Column(JSON, nullable=True)

    # Indicates if this is the currently selected/active character for the player in this guild
    is_active_char = Column(Boolean, default=False, nullable=False, index=True)

    # Relationship to Player
    player = relationship("Player", back_populates="characters")
    new_items_association = relationship("NewCharacterItem", back_populates="character", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_character_guild_player', 'guild_id', 'player_id'),
        # Optional: A unique constraint to prevent a player from having multiple characters with the exact same name_i18n JSON object.
        # This is tricky with JSON objects. A better approach might be a unique constraint on (player_id, name_en)
        # if 'en' name is always required, or handle this at the application layer.
        # For now, omitting DB-level name uniqueness beyond the primary key `id`.
        # UniqueConstraint('player_id', 'name_i18n', name='uq_character_player_name'), # Example if desired
    )

    def __repr__(self):
        return f"<Character(id='{self.id}', name_i18n='{self.name_i18n}', player_id='{self.player_id}', guild_id='{self.guild_id}')>"


class Location(Base):
    __tablename__ = 'locations'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    static_name = Column(String, nullable=True)
    name_i18n = Column(JSON, nullable=False)
    descriptions_i18n = Column(JSON, nullable=False)
    type_i18n = Column(JSON, nullable=False)
    coordinates = Column(JSON, nullable=True)
    static_connections = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False, index=True)
    exits = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    npc_ids = Column(JSON, nullable=True, default=lambda: [])
    event_triggers = Column(JSON, nullable=True, default=lambda: [])
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
    guild_id = Column(String, nullable=False, index=True)

class Party(Base):
    __tablename__ = 'parties'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    player_ids = Column(JSON, nullable=True)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)
    guild_id = Column(String, nullable=False, index=True)
    leader_id = Column(String, ForeignKey('players.id'), nullable=True)
    state_variables = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True) # Was JSON, should be String if it's just action type/ID
    location = relationship("Location")
    leader = relationship("Player", foreign_keys=[leader_id])

class RulesConfig(Base):
    __tablename__ = 'rules_config'
    guild_id = Column(String, primary_key=True)
    config_data = Column(JSON)

class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    descriptions_i18n = Column(JSON, nullable=True)
    details_i18n = Column(JSON, nullable=True)
    tags_i18n = Column(JSON, nullable=True)
    atmosphere_i18n = Column(JSON, nullable=True)
    features_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    __table_args__ = (Index('idx_generatedlocation_guild_id', 'guild_id'),)

class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=False)
    description_i18n = Column(JSON, nullable=True)
    type = Column(String, nullable=True)
    properties = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    __table_args__ = (Index('idx_itemtemplate_guild_id', 'guild_id'),)

class LocationTemplate(Base): __tablename__ = 'location_templates'; id = Column(String, primary_key=True); name = Column(String, nullable=False); description = Column(Text, nullable=True); properties = Column(JSON, nullable=True); guild_id = Column(String, nullable=False, index=True)

class NPC(Base):
    __tablename__ = 'npcs'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    backstory_i18n = Column(JSON, nullable=True)
    persona_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False, index=True)
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
    guild_id = Column(String, nullable=False)
    __table_args__ = (Index('idx_generatednpc_guild_id', 'guild_id'),)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    __table_args__ = (Index('idx_generatedfaction_guild_id', 'guild_id'),)

class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    name_i18n = Column(JSON, nullable=True)
    __table_args__ = (Index('idx_generatedquest_guild_id', 'guild_id'),)

class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    guild_id = Column(String, nullable=False)
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
    __table_args__ = (Index('idx_item_guild_id', 'guild_id'),)


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
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    participants = Column(JSON, nullable=False, default=lambda: [])
    initial_positions = Column(JSON, nullable=True)
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True) # Legacy text log
    turn_log_structured = Column(JSON, nullable=True, default=lambda: []) # New structured log
    state_variables = Column(JSON, nullable=True)
    combat_rules_snapshot = Column(JSON, nullable=True)
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
    description_i18n = Column(JSON, nullable=True)
    consequences_data = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    channel_id = Column(String, nullable=True)
    player = relationship("Player")
    party = relationship("Party")
    location = relationship("Location")

class Relationship(Base):
    __tablename__ = 'relationships'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    entity1_id = Column(String, nullable=False)
    entity1_type = Column(String, nullable=False)
    entity2_id = Column(String, nullable=False)
    entity2_type = Column(String, nullable=False)
    relationship_type_i18n = Column(JSON, nullable=True)
    status_i18n = Column(JSON, nullable=True)
    __table_args__ = (Index('idx_relationship_guild_id', 'guild_id'),)

class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memory'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    player_id = Column(String, ForeignKey('players.id'), nullable=False)
    npc_id = Column(String, ForeignKey('npcs.id'), nullable=False)
    memory_details_i18n = Column(JSON, nullable=True)
    __table_args__ = (
        Index('idx_playernpcmemory_guild_id', 'guild_id'),
        Index('idx_playernpcmemory_player_id', 'player_id'),
        Index('idx_playernpcmemory_npc_id', 'npc_id'),
    )

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSON, nullable=False)
    description_i18n = Column(JSON, nullable=False)
    guild_id = Column(String, nullable=False)
    effect_i18n = Column(JSON, nullable=False)
    cost = Column(JSON, nullable=True)
    requirements = Column(JSON, nullable=True)
    type_i18n = Column(JSON, nullable=False)
    __table_args__ = (Index('idx_ability_guild_id', 'guild_id'),)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    __table_args__ = (Index('idx_skill_guild_id', 'guild_id'),)

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
    guild_id = Column(String, nullable=False, index=True)
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

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    description_i18n = Column(JSON, nullable=True)
    guild_id = Column(String, nullable=False)
    __table_args__ = (Index('idx_itemproperty_guild_id', 'guild_id'),)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    name_i18n = Column(JSON, nullable=True)
    __table_args__ = (Index('idx_questline_guild_id', 'guild_id'),)

class QuestStep(Base):
    __tablename__ = 'quest_steps'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    questline_id = Column(String, ForeignKey('questlines.id'), nullable=False)
    step_details_i18n = Column(JSON, nullable=True)
    __table_args__ = (
        Index('idx_queststep_guild_id', 'guild_id'),
        Index('idx_queststep_questline_id', 'questline_id'),
    )

class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True)
    guild_id = Column(String, nullable=False)
    name_i18n = Column(JSON, nullable=True)
    __table_args__ = (Index('idx_mobilegroup_guild_id', 'guild_id'),)

class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    conflict_data_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True)
    resolution_data_json = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)


class NewItem(Base):
    __tablename__ = 'new_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    item_type = Column(String, nullable=False)  # e.g., "weapon", "armor", "consumable"
    item_metadata = Column(JSONB, name="metadata", nullable=True) # Renamed attribute to item_metadata, column name remains 'metadata'
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # For global items, unique constraint on name only
    __table_args__ = (UniqueConstraint('name', name='uq_new_item_name'),)

    def __repr__(self):
        return f"<NewItem(id={self.id}, name='{self.name}', item_type='{self.item_type}')>"


class NewCharacterItem(Base):
    __tablename__ = 'new_character_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Character.id is String, so character_id must be String for FK
    character_id = Column(String, ForeignKey('characters.id'), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey('new_items.id'), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    character = relationship("Character", back_populates="new_items_association")
    item = relationship("NewItem")

    __table_args__ = (CheckConstraint('quantity > 0', name='check_new_char_item_quantity_positive'),)

    def __repr__(self):
        return f"<NewCharacterItem(id={self.id}, character_id='{self.character_id}', item_id='{self.item_id}', quantity={self.quantity})>"


class RPGCharacter(Base):
    __tablename__ = 'rpg_characters'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    class_name = Column(String, nullable=False) # Renamed from 'class' to avoid keyword conflict
    level = Column(Integer, default=1, nullable=False)
    health = Column(Integer, nullable=False)
    mana = Column(Integer, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint('level >= 0', name='check_level_non_negative'),
        CheckConstraint('health >= 0', name='check_health_non_negative'),
        CheckConstraint('mana >= 0', name='check_mana_non_negative'),
    )

    def __repr__(self):
        return f"<RPGCharacter(id={self.id}, name='{self.name}', class_name='{self.class_name}')>"
