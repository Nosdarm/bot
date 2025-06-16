from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text, PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.declarative.api import DeclarativeMeta
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any

Base: DeclarativeMeta = declarative_base()

class Player(Base):
    __tablename__ = 'players'

    id = Column(String, primary_key=True)
    discord_id = Column(String, nullable=True) # Discord User ID
    name_i18n = Column(JSONB) # Standardized to JSONB
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    selected_language = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    unspent_xp = Column(Integer, default=0)
    gold = Column(Integer, default=0)
    current_game_status = Column(String, nullable=True)
    collected_actions_json = Column(JSONB, nullable=True) # Standardized to JSONB
    current_party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    stats = Column(JSONB, nullable=True) # Standardized to JSONB
    current_action = Column(String, nullable=True)
    action_queue = Column(JSONB, nullable=True) # Standardized to JSONB
    state_variables = Column(JSONB, nullable=True) # Standardized to JSONB
    hp = Column(Float, nullable=True)
    max_health = Column(Float, nullable=True)
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSONB, nullable=True) # Standardized to JSONB
    race = Column(String, nullable=True)
    mp = Column(Integer, nullable=True)
    attack = Column(Integer, nullable=True)
    defense = Column(Integer, nullable=True)
    skills_data_json = Column(JSONB, nullable=True) # Standardized to JSONB
    abilities_data_json = Column(JSONB, nullable=True) # Standardized to JSONB
    spells_data_json = Column(JSONB, nullable=True) # Standardized to JSONB
    character_class = Column(String, nullable=True)
    flags_json = Column(JSONB, nullable=True) # Standardized to JSONB
    active_quests = Column(JSONB, nullable=True) # Standardized to JSONB
    known_spells = Column(JSONB, nullable=True) # Standardized to JSONB
    spell_cooldowns = Column(JSONB, nullable=True) # Standardized to JSONB
    inventory = Column(JSONB, nullable=True) # Standardized to JSONB
    effective_stats_json = Column(JSONB, nullable=True) # Standardized to JSONB
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    location = relationship("Location")
    party = relationship("Party", foreign_keys=[current_party_id])
    characters = relationship("Character", back_populates="player", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint('discord_id', 'guild_id', name='uq_player_discord_guild'),)


class Character(Base):
    __tablename__ = 'characters'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True) # Added FK and ondelete

    name_i18n = Column(JSONB, nullable=False)  # Standardized to JSONB
    class_i18n = Column(JSONB, nullable=True)   # Standardized to JSONB
    description_i18n = Column(JSONB, nullable=True) # Standardized to JSONB

    level = Column(Integer, default=1, nullable=False)
    xp = Column(Integer, default=0, nullable=False)

    stats = Column(JSONB, nullable=True) # Standardized to JSONB
    current_hp = Column(Float, nullable=True)
    max_hp = Column(Float, nullable=True)

    abilities = Column(JSONB, nullable=True) # Standardized to JSONB
    inventory = Column(JSONB, nullable=True) # Standardized to JSONB

    # Stores relationships with NPCs, e.g., {"npc_id_1": "friendly", "npc_id_2": "hostile"}
    npc_relationships = Column(JSONB, nullable=True) # Standardized to JSONB

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
    static_name = Column(String, nullable=True) # Not i18n as it's an internal static name
    name_i18n = Column(JSONB, nullable=False) # Standardized to JSONB
    descriptions_i18n = Column(JSONB, nullable=False) # Standardized to JSONB
    type_i18n = Column(JSONB, nullable=False) # Standardized to JSONB
    coordinates = Column(JSONB, nullable=True) # Standardized to JSONB
    static_connections = Column(JSONB, nullable=True) # Standardized to JSONB
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    exits = Column(JSONB, nullable=True) # Standardized to JSONB
    inventory = Column(JSONB, nullable=True) # Standardized to JSONB
    npc_ids = Column(JSONB, nullable=True, default=lambda: []) # Standardized to JSONB
    event_triggers = Column(JSONB, nullable=True, default=lambda: []) # Standardized to JSONB
    template_id = Column(String, nullable=True)
    state_variables = Column(JSONB, nullable=True) # Standardized to JSONB
    is_active = Column(Boolean, default=True, nullable=False)
    details_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    tags_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    atmosphere_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    features_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
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
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String, nullable=False)
    ends_at = Column(Float, nullable=False)
    callback_data = Column(JSONB, nullable=True) # Standardized to JSONB
    is_active = Column(Boolean, default=True, nullable=False)
    def __repr__(self): return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JSONB, nullable=True) # Standardized to JSONB
    state_variables = Column(JSONB, nullable=True) # Standardized to JSONB
    stages_data = Column(JSONB, nullable=True) # Standardized to JSONB
    end_message_template_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

class Party(Base):
    __tablename__ = 'parties'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    player_ids = Column(JSONB, nullable=True) # Standardized to JSONB
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    leader_id = Column(String, ForeignKey('players.id'), nullable=True) # FK to Player.id
    state_variables = Column(JSONB, nullable=True) # Standardized to JSONB
    current_action = Column(String, nullable=True)
    location = relationship("Location")
    leader = relationship("Player", foreign_keys=[leader_id]) # Correct

class RulesConfig(Base):
    __tablename__ = 'rules_config'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id'), nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    value = Column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint('guild_id', 'key', name='uq_guild_rule_key'),
        Index('idx_rulesconfig_guild_key', 'guild_id', 'key')
    )

class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    descriptions_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    details_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    tags_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    atmosphere_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    features_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatedlocation_guild_id', 'guild_id'),)

class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=False) # Standardized to JSONB
    description_i18n = Column(JSONB, nullable=True) # Standardized to JSONB
    type = Column(String, nullable=True) # Not i18n
    properties = Column(JSONB, nullable=True) # Standardized to JSONB
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemtemplate_guild_id', 'guild_id'),)

class LocationTemplate(Base): # Name is not i18n as it's a template name
    __tablename__ = 'location_templates'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True) # Template names should be unique
    description_i18n = Column(JSONB, nullable=True) # Standardized
    properties = Column(JSONB, nullable=True) # Standardized
    # guild_id can be nullable if there are global templates, or non-nullable if templates are guild-specific
    # For now, assuming guild_id specific as per general rule. If global, this needs adjustment.
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

class NPC(Base):
    __tablename__ = 'npcs'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True) # Could be FK to an NpcTemplate table later
    name_i18n = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    backstory_i18n = Column(JSONB, nullable=True) # Standardized
    persona_i18n = Column(JSONB, nullable=True) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    stats = Column(JSONB, nullable=True) # Standardized
    inventory = Column(JSONB, nullable=True) # Standardized
    current_action = Column(String, nullable=True)
    action_queue = Column(JSONB, nullable=True) # Standardized
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    state_variables = Column(JSONB, nullable=True) # Standardized
    health = Column(Float, nullable=True)
    max_health = Column(Float, nullable=True)
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSONB, nullable=True) # Standardized
    is_temporary = Column(Boolean, default=False)
    archetype = Column(String, nullable=True) # Not i18n
    traits = Column(JSONB, nullable=True) # Standardized
    desires = Column(JSONB, nullable=True) # Standardized
    motives = Column(JSONB, nullable=True) # Standardized
    skills_data = Column(JSONB, nullable=True) # Standardized
    equipment_data = Column(JSONB, nullable=True) # Standardized
    abilities_data = Column(JSONB, nullable=True) # Standardized
    faction = Column(JSONB, nullable=True) # Standardized (assuming faction name/details might be i18n)
    behavior_tags = Column(JSONB, nullable=True) # Standardized (if tags are free text and need i18n)
    loot_table_id = Column(String, nullable=True) # Not i18n
    effective_stats_json = Column(JSONB, nullable=True) # Standardized
    faction_id = Column(String, nullable=True, index=True) # Not i18n, refers to a Faction table ID

    location = relationship("Location")
    party = relationship("Party")

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    backstory_i18n = Column(JSONB, nullable=True) # Standardized
    persona_i18n = Column(JSONB, nullable=True) # Standardized
    effective_stats_json = Column(JSONB, nullable=True) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatednpc_guild_id', 'guild_id'),)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatedfaction_guild_id', 'guild_id'),)


class GlobalNpc(Base):
    __tablename__ = 'global_npcs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=False) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    npc_template_id = Column(String, nullable=True) # Not i18n
    state_variables = Column(JSONB, nullable=True) # Standardized
    faction_id = Column(String, nullable=True, index=True) # Not i18n
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    current_location = relationship("Location")

    __table_args__ = (
        Index('idx_globalnpc_guild_id', 'guild_id'),
        Index('idx_globalnpc_faction_id', 'faction_id'), # Added index for faction_id
        Index('idx_globalnpc_is_active', 'is_active'), # Added index for is_active
    )

    def __repr__(self):
        return f"<GlobalNpc(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


# New QuestTable
class QuestTable(Base):
    __tablename__ = 'quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    status = Column(String, default='available', nullable=False)
    influence_level = Column(String, default='local', nullable=True)
    prerequisites_json_str = Column(Text, nullable=True) # Stores JSON as string
    connections_json = Column(JSONB, nullable=True) # Stores parsed JSON
    rewards_json_str = Column(Text, nullable=True) # Stores JSON as string
    npc_involvement_json = Column(JSONB, nullable=True) # Stores parsed JSON
    consequences_json_str = Column(Text, nullable=True) # Stores JSON as string
    quest_giver_details_i18n = Column(JSONB, nullable=True)
    consequences_summary_i18n = Column(JSONB, nullable=True)
    ai_prompt_context_json_str = Column(Text, nullable=True)
    is_ai_generated = Column(Boolean, default=False, nullable=False)
    # steps are in QuestStepTable
    __table_args__ = (Index('idx_quests_guild_id', 'guild_id'),)


class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title_i18n = Column(JSONB, nullable=True) # MODIFIED from name_i18n
    description_i18n = Column(JSONB, nullable=True) # Ensure JSONB
    guild_id = Column(String, nullable=False, index=True)
    status = Column(String, default='available', nullable=True) # ADDED
    suggested_level = Column(Integer, nullable=True) # ADDED
    rewards_json = Column(Text, nullable=True) # ADDED (Storing as JSON string)
    prerequisites_json = Column(Text, nullable=True) # ADDED (Storing as JSON string)
    consequences_json = Column(Text, nullable=True) # ADDED (Storing as JSON string)
    quest_giver_npc_id = Column(String, nullable=True) # ADDED
    ai_prompt_context_json = Column(Text, nullable=True) # ADDED (Storing as JSON string)
    quest_giver_details_i18n = Column(JSONB, nullable=True) # ADDED
    consequences_summary_i18n = Column(JSONB, nullable=True) # ADDED
    # stages_json or steps_json_str is omitted, steps will be in QuestStepTable
    __table_args__ = (Index('idx_generatedquest_guild_id', 'guild_id'),)


class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True) # This should be item instance ID
    template_id = Column(String, ForeignKey('item_templates.id'), nullable=True) # FK to ItemTemplate
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    owner_id = Column(String, nullable=True) # Could be Player.id or NPC.id or Location.id (if in a container)
    owner_type = Column(String, nullable=True) # 'player', 'npc', 'location'
    location_id = Column(String, ForeignKey('locations.id'), nullable=True) # If directly in a location (not in an inventory)
    quantity = Column(Integer, default=1)
    state_variables = Column(JSONB, nullable=True) # Standardized
    is_temporary = Column(Boolean, default=False)
    name_i18n = Column(JSONB, nullable=True) # Denormalized from template, or for unique items
    description_i18n = Column(JSONB, nullable=True) # Denormalized from template
    properties = Column(JSONB, nullable=True) # Denormalized or instance-specific properties
    slot = Column(String, nullable=True) # Not i18n
    value = Column(Integer, nullable=True) # Not i18n
    __table_args__ = (Index('idx_item_guild_id', 'guild_id'),)


class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Inventory entry unique ID
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete
    item_id = Column(String, ForeignKey('items.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete, index
    quantity = Column(Integer, default=1)
    # Adding guild_id for easier querying and partitioning, though derivable from player.
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    player = relationship("Player") # Relationship to Player
    item = relationship("Item") # Relationship to Item instance

    __table_args__ = (
        UniqueConstraint('player_id', 'item_id', name='uq_player_item_inventory'), # Player can only have one stack of a given item_id
        Index('idx_inventory_guild_player', 'guild_id', 'player_id') # Index for guild-specific inventory queries
    )


class Combat(Base):
    __tablename__ = 'combats'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True) # Not i18n
    participants = Column(JSONB, nullable=False, default=lambda: []) # Standardized
    initial_positions = Column(JSONB, nullable=True) # Standardized
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True) # Legacy, not i18n
    turn_log_structured = Column(JSONB, nullable=True, default=lambda: []) # Standardized
    state_variables = Column(JSONB, nullable=True) # Standardized
    combat_rules_snapshot = Column(JSONB, nullable=True) # Standardized
    channel_id = Column(String, nullable=True) # Not i18n
    event_id = Column(String, ForeignKey('events.id'), nullable=True) # Not i18n
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
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    player_id = Column(String, ForeignKey('players.id'), nullable=True) # Can be null if system log
    party_id = Column(String, ForeignKey('parties.id'), nullable=True) # Can be null
    event_type = Column(String, nullable=False) # Not i18n
    message_key = Column(String, nullable=True) # Key for localization, not i18n itself
    message_params = Column(JSONB, nullable=True) # Standardized
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    involved_entities_ids = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    consequences_data = Column(JSONB, nullable=True) # Standardized
    details = Column(JSONB, nullable=True) # Standardized
    channel_id = Column(String, nullable=True)
    player = relationship("Player")
    party = relationship("Party")
    location = relationship("Location")

class Relationship(Base):
    __tablename__ = 'relationships'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Added default
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    entity1_id = Column(String, nullable=False) # Not i18n
    entity1_type = Column(String, nullable=False) # Not i18n
    entity2_id = Column(String, nullable=False) # Not i18n
    entity2_type = Column(String, nullable=False) # Not i18n
    relationship_type_i18n = Column(JSONB, nullable=True) # Standardized
    status_i18n = Column(JSONB, nullable=True) # Standardized
    __table_args__ = (
        Index('idx_relationship_guild_id', 'guild_id'),
        Index('idx_relationship_entity1', 'guild_id', 'entity1_id', 'entity1_type'),
        Index('idx_relationship_entity2', 'guild_id', 'entity2_id', 'entity2_type'),
    )

class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Added default
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete, index
    npc_id = Column(String, ForeignKey('npcs.id', ondelete='CASCADE'), nullable=False, index=True) # Added ondelete, index
    memory_details_i18n = Column(JSONB, nullable=True) # Standardized
    __table_args__ = (
        Index('idx_playernpcmemory_guild_player_npc', 'guild_id', 'player_id', 'npc_id'),
        Index('idx_playernpcmemory_player_id', 'player_id'), # Keep existing index if still needed
        Index('idx_playernpcmemory_npc_id', 'npc_id'), # Keep existing index if still needed
    )

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=False) # Standardized
    description_i18n = Column(JSONB, nullable=False) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effect_i18n = Column(JSONB, nullable=False) # Standardized
    cost = Column(JSONB, nullable=True) # Standardized
    requirements = Column(JSONB, nullable=True) # Standardized
    type_i18n = Column(JSONB, nullable=False) # Standardized
    __table_args__ = (Index('idx_ability_guild_id', 'guild_id'),)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Added default
    name_i18n = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_skill_guild_id', 'guild_id'),)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Added default
    name = Column(String, nullable=False) # This is the effect key/template_id, not i18n
    status_type = Column(String, nullable=False) # e.g. buff, debuff, dot. Not i18n
    target_id = Column(String, nullable=False) # ID of entity affected
    target_type = Column(String, nullable=False) # 'player', 'npc', etc. Not i18n
    duration_turns = Column(Float, nullable=True)
    applied_at = Column(Float, nullable=True) # Game time or turn number
    source_id = Column(String, nullable=True) # ID of entity that applied status
    state_variables = Column(JSONB, nullable=True) # For specific status effect data, standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effects = Column(JSONB, nullable=True) # Actual effects, e.g. {"stat_change": {"strength": -2}}, standardized
    name_i18n = Column(JSONB, nullable=True) # Display name of status, standardized
    description_i18n = Column(JSONB, nullable=True) # Display description, standardized

class CraftingQueue(Base):
    __tablename__ = 'crafting_queues'
    entity_id = Column(String, nullable=False) # ID of player/npc/location
    entity_type = Column(String, nullable=False) # 'player', 'npc', 'location'
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    queue = Column(JSONB, nullable=True) # List of crafting tasks, standardized
    state_variables = Column(JSONB, nullable=True) # e.g. current progress, standardized
    __table_args__ = (PrimaryKeyConstraint('entity_id', 'entity_type', 'guild_id'),)

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Added default
    name_i18n = Column(JSONB, nullable=True) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemproperty_guild_id', 'guild_id'),)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Ensure default
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True) # Already JSONB
    __table_args__ = (Index('idx_questline_guild_id', 'guild_id'),)


class QuestStepTable(Base): # RENAMED from QuestStep
    __tablename__ = 'quest_steps' # Tablename remains quest_steps
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    quest_id = Column(String, ForeignKey('quests.id', ondelete='CASCADE'), nullable=False, index=True) # FK to QuestTable.id

    title_i18n = Column(JSONB, nullable=True) # Already JSONB
    description_i18n = Column(JSONB, nullable=True) # Already JSONB
    requirements_i18n = Column(JSONB, nullable=True) # Standardized

    # JSON fields for complex structured data, use JSONB
    required_mechanics_json = Column(JSONB, default=lambda: {}, nullable=False) # Standardized
    abstract_goal_json = Column(JSONB, default=lambda: {}, nullable=False) # Standardized
    conditions_json = Column(JSONB, default=lambda: {}, nullable=False) # Standardized
    consequences_json = Column(JSONB, default=lambda: {}, nullable=False) # Standardized

    step_order = Column(Integer, default=0, nullable=False) # Not i18n
    status = Column(String, default='pending', nullable=False) # Not i18n

    assignee_type = Column(String, nullable=True) # Not i18n
    assignee_id = Column(String, nullable=True) # Not i18n

    linked_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    linked_npc_id = Column(String, ForeignKey('npcs.id'), nullable=True)
    linked_item_id = Column(String, ForeignKey('items.id'), nullable=True)
    linked_guild_event_id = Column(String, ForeignKey('events.id'), nullable=True)

    __table_args__ = (
        # Index('idx_queststep_guild_questline', 'guild_id', 'questline_id'), # REMOVED
        Index('idx_queststep_guild_quest', 'guild_id', 'quest_id'), # ADDED
    )


class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=False) # Standardized
    description_i18n = Column(JSONB, nullable=True) # Standardized
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    member_ids = Column(JSONB, nullable=True) # Standardized (list of IDs)
    destination_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    state_variables = Column(JSONB, nullable=True) # Standardized
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    current_location = relationship("Location", foreign_keys=[current_location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])

    __table_args__ = (
        Index('idx_mobilegroup_guild_id', 'guild_id'),
        Index('idx_mobilegroup_is_active', 'is_active'), # Added index for is_active
    )

    def __repr__(self):
        return f"<MobileGroup(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"

class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    conflict_data_json = Column(JSONB, nullable=False) # Standardized
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True) # Not i18n
    resolution_data_json = Column(JSONB, nullable=True) # Standardized
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


class Shop(Base):
    __tablename__ = 'shops'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    name_i18n = Column(JSON, nullable=False)
    description_i18n = Column(JSON, nullable=True)
    type_i18n = Column(JSON, nullable=True)  # e.g., "General Store", "Blacksmith"
    inventory = Column(JSON, nullable=True)  # Structure: {"item_template_id_1": {"quantity": 10, "buy_price": 100, "sell_price": 50, "restock_rules": {...}}, ...}
    owner_id = Column(String, ForeignKey('npcs.id'), nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    economic_parameters_override = Column(JSON, nullable=True)  # e.g., custom markups, available item types/rarities

    # Relationships
    owner = relationship("NPC")
    location = relationship("Location")

    __table_args__ = (
        Index('idx_shop_guild_id', 'guild_id'),
    )

    def __repr__(self):
        return f"<Shop(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


class Currency(Base):
    __tablename__ = 'currencies'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    name_i18n = Column(JSON, nullable=False)
    symbol_i18n = Column(JSON, nullable=True)
    exchange_rate_to_standard = Column(Float, nullable=False, default=1.0)
    is_default = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index('idx_currency_guild_id', 'guild_id'),
        # As discussed, skipping complex unique constraint on (guild_id, name_i18n) for now.
        # UniqueConstraint('guild_id', 'name_i18n', name='uq_currency_guild_name'), # Example if JSON unique constraint was simple
        # The partial unique constraint for is_default=True is DB specific and complex.
        # For now, this logic should be handled at the application level.
        # UniqueConstraint('guild_id', 'is_default', name='uq_guild_default_currency', postgresql_where=(is_default == True)), # Example for PostgreSQL
    )

    def __repr__(self):
        return f"<Currency(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}', is_default={self.is_default})>"


class UserSettings(Base):
    __tablename__ = 'user_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey('players.discord_id'), nullable=False) # FK to Player.discord_id
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    language_code = Column(String(10), nullable=True)  # This is being deprecated in favor of Player.selected_language
    timezone = Column(String(50), nullable=True)  # Not i18n

    player = relationship("Player", foreign_keys=[user_id], primaryjoin="UserSettings.user_id == Player.discord_id")


    __table_args__ = (
        UniqueConstraint('user_id', 'guild_id', name='uq_user_guild_settings'),
        Index('idx_user_settings_user_guild', 'user_id', 'guild_id') # Redundant with UniqueConstraint? Check DB specifics.
    )

    def __repr__(self):
        return f"<UserSettings(id={self.id}, user_id='{self.user_id}', guild_id='{self.guild_id}', language_code='{self.language_code}')>"


class GuildConfig(Base):
    __tablename__ = 'guild_configs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Internal UUID PK
    guild_id = Column(String, unique=True, nullable=False, index=True) # Discord Guild ID, used for FKs from other tables
    bot_language = Column(String, default='en', nullable=False) # Not i18n, it's a language code
    game_channel_id = Column(String, nullable=True) # Not i18n
    master_channel_id = Column(String, nullable=True) # Not i18n
    system_notifications_channel_id = Column(String, nullable=True) # Not i18n

    def __repr__(self):
        return f"<GuildConfig(id='{self.id}', guild_id='{self.guild_id}', bot_language='{self.bot_language}')>"


# New WorldState model
class WorldState(Base):
    __tablename__ = 'world_states'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # Internal UUID PK
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    global_narrative_state_i18n = Column(JSONB, nullable=True) # Standardized
    current_era_i18n = Column(JSONB, nullable=True) # Standardized
    custom_flags = Column(JSONB, nullable=True) # Standardized

    guild = relationship("GuildConfig") # Relationship to GuildConfig

    def __repr__(self):
        return f"<WorldState(id='{self.id}', guild_id='{self.guild_id}')>"
