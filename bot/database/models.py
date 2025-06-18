from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text, PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List

Base: DeclarativeMeta = declarative_base()

class Player(Base): # Represents the player's account in a guild
    __tablename__ = 'players'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_id = Column(String, nullable=False, index=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n = Column(JSONB, nullable=True)
    selected_language = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    active_character_id = Column(String, ForeignKey('characters.id', name='fk_player_active_character', use_alter=True, ondelete='SET NULL'), nullable=True, index=True)

    characters = relationship("Character", back_populates="player_account", cascade="all, delete-orphan", foreign_keys="Character.player_id")
    active_character = relationship("Character", foreign_keys=[active_character_id], post_update=True, lazy="joined")

    __table_args__ = (
        UniqueConstraint('discord_id', 'guild_id', name='uq_player_discord_guild'),
        Index('idx_player_guild_discord', 'guild_id', 'discord_id'),
    )

    def __repr__(self):
        return f"<Player(id='{self.id}', discord_id='{self.discord_id}', guild_id='{self.guild_id}', active_char_id='{self.active_character_id}')>"


class Character(Base):
    __tablename__ = 'characters'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n = Column(JSONB, nullable=False)
    character_class_i18n = Column(JSONB, nullable=True)
    race_key = Column(String, nullable=True)
    race_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)

    level = Column(Integer, default=1, nullable=False)
    xp = Column(Integer, default=0, nullable=False)
    unspent_xp = Column(Integer, default=0, nullable=False)
    gold = Column(Integer, default=0, nullable=False)

    current_hp = Column(Float, nullable=True)
    max_hp = Column(Float, nullable=True)
    mp = Column(Integer, nullable=True) # Renamed from current_mp to just mp, max_mp can be in stats
    base_attack = Column(Integer, nullable=True)
    base_defense = Column(Integer, nullable=True)
    is_alive = Column(Boolean, default=True, nullable=False)

    stats_json = Column(JSONB, nullable=True) # Renamed from 'stats' to 'stats_json' to be explicit
    effective_stats_json = Column(JSONB, nullable=True)

    status_effects_json = Column(JSONB, nullable=True)
    skills_data_json = Column(JSONB, nullable=True)
    abilities_data_json = Column(JSONB, nullable=True)
    spells_data_json = Column(JSONB, nullable=True)
    known_spells_json = Column(JSONB, nullable=True)
    spell_cooldowns_json = Column(JSONB, nullable=True)

    inventory_json = Column(JSONB, nullable=True)
    equipment_slots_json = Column(JSONB, nullable=True, default=lambda: {})

    active_quests_json = Column(JSONB, nullable=True)
    flags_json = Column(JSONB, nullable=True)
    state_variables_json = Column(JSONB, nullable=True)

    current_game_status = Column(String, nullable=True)
    current_action_json = Column(JSONB, nullable=True)
    action_queue_json = Column(JSONB, nullable=True)
    collected_actions_json = Column(JSONB, nullable=True)

    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True, index=True)
    current_party_id = Column(String, ForeignKey('parties.id', name='fk_character_current_party'), nullable=True, index=True)

    player_account = relationship("Player", back_populates="characters", foreign_keys=[player_id])
    current_location = relationship("Location", foreign_keys=[current_location_id], lazy="joined")
    current_party = relationship("Party", foreign_keys=[current_party_id], lazy="joined")

    __table_args__ = (
        Index('idx_character_guild_player', 'guild_id', 'player_id'),
        Index('idx_character_location', 'current_location_id'),
        Index('idx_character_party', 'current_party_id'),
    )

    def __repr__(self):
        name_en = self.name_i18n.get('en', self.id) if isinstance(self.name_i18n, dict) else self.id
        return f"<Character(id='{self.id}', name='{name_en}', player_id='{self.player_id}', guild_id='{self.guild_id}')>"


class Location(Base):
    __tablename__ = 'locations'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    static_id = Column(String, nullable=True, index=True)
    name_i18n = Column(JSONB, nullable=False)
    descriptions_i18n = Column(JSONB, nullable=False)
    type_i18n = Column(JSONB, nullable=False)
    coordinates = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    neighbor_locations_json = Column(JSONB, nullable=True, comment="Stores {target_location_id: 'connection_type_i18n_key'}")
    inventory = Column(JSONB, nullable=True)
    npc_ids = Column(JSONB, nullable=True, default=lambda: [])
    event_triggers = Column(JSONB, nullable=True, default=lambda: [])
    template_id = Column(String, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    details_i18n = Column(JSONB, nullable=True)
    tags_i18n = Column(JSONB, nullable=True)
    atmosphere_i18n = Column(JSONB, nullable=True)
    features_i18n = Column(JSONB, nullable=True)
    channel_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    ai_metadata_json = Column(JSONB, nullable=True, comment="Stores metadata for AI generation purposes")
    points_of_interest_json = Column(JSONB, nullable=True, comment="List of Points of Interest objects/dictionaries")
    on_enter_events_json = Column(JSONB, nullable=True, default=lambda: [])

    __table_args__ = (
        UniqueConstraint('guild_id', 'static_id', name='uq_location_guild_static_id'),
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Location':
        if 'id' not in data or 'guild_id' not in data:
            raise ValueError("Location data must include 'id' and 'guild_id'.")

        i18n_fields = ['name_i18n', 'descriptions_i18n', 'details_i18n',
                       'tags_i18n', 'atmosphere_i18n', 'features_i18n']
        for field in i18n_fields:
            data.setdefault(field, {})

        json_fields_default_dict = ['inventory', 'state_variables',
                                    'neighbor_locations_json', 'ai_metadata_json',
                                    'npc_ids', 'event_triggers']
        for field in json_fields_default_dict:
            data.setdefault(field, {})

        data.setdefault('points_of_interest_json', [])
        data.setdefault('on_enter_events_json', [])

        if data.get('is_active') is None:
            data['is_active'] = True

        data.pop('exits', None)
        data.pop('static_connections', None)
        if 'static_name' in data and 'static_id' not in data:
            data['static_id'] = data.pop('static_name')

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "guild_id": self.guild_id, "template_id": self.template_id,
            "static_id": self.static_id, "name_i18n": self.name_i18n or {},
            "descriptions_i18n": self.descriptions_i18n or {}, "details_i18n": self.details_i18n or {},
            "tags_i18n": self.tags_i18n or {}, "atmosphere_i18n": self.atmosphere_i18n or {},
            "features_i18n": self.features_i18n or {},
            "neighbor_locations_json": self.neighbor_locations_json or {},
            "inventory": self.inventory or {},
            "state_variables": self.state_variables or {},
            "ai_metadata_json": self.ai_metadata_json or {},
            "is_active": self.is_active,
            "channel_id": self.channel_id,
            "image_url": self.image_url,
            "npc_ids": self.npc_ids or [],
            "event_triggers": self.event_triggers or [],
            "type_i18n": self.type_i18n or {},
            "coordinates": self.coordinates or {},
            "points_of_interest_json": self.points_of_interest_json or [],
            "on_enter_events_json": self.on_enter_events_json or []
        }

class Timer(Base):
    __tablename__ = 'timers'
    id = Column(String, primary_key=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    type = Column(String, nullable=False)
    ends_at = Column(Float, nullable=False)
    callback_data = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    def __repr__(self): return f"<Timer(id='{self.id}', type='{self.type}', ends_at={self.ends_at}, active={self.is_active}, guild_id='{self.guild_id}')>"

class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    channel_id = Column(String, nullable=True)
    current_stage_id = Column(String, nullable=True)
    players = Column(JSONB, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    stages_data = Column(JSONB, nullable=True)
    end_message_template_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

class Party(Base):
    __tablename__ = 'parties'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True)
    player_ids_json = Column(JSONB, nullable=True) # Will store Character IDs
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    leader_id = Column(String, ForeignKey('characters.id', name='fk_party_leader_character'), nullable=True)
    state_variables = Column(JSONB, nullable=True)
    current_action = Column(String, nullable=True)

    location = relationship("Location", foreign_keys=[current_location_id])
    leader = relationship("Character", foreign_keys=[leader_id])

class RulesConfig(Base):
    __tablename__ = 'rules_config'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    value = Column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint('guild_id', 'key', name='uq_guild_rule_key'),
        Index('idx_rulesconfig_guild_key', 'guild_id', 'key')
    )

class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True)
    descriptions_i18n = Column(JSONB, nullable=True)
    details_i18n = Column(JSONB, nullable=True)
    tags_i18n = Column(JSONB, nullable=True)
    atmosphere_i18n = Column(JSONB, nullable=True)
    features_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatedlocation_guild_id', 'guild_id'),)

class ItemTemplate(Base):
    __tablename__ = 'item_templates'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=True)
    type = Column(String, nullable=True)
    properties = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemtemplate_guild_id', 'guild_id'),)

class LocationTemplate(Base):
    __tablename__ = 'location_templates'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description_i18n = Column(JSONB, nullable=True)
    properties = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

class NPC(Base):
    __tablename__ = 'npcs'
    id = Column(String, primary_key=True)
    template_id = Column(String, nullable=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    backstory_i18n = Column(JSONB, nullable=True)
    persona_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    stats = Column(JSONB, nullable=True)
    inventory = Column(JSONB, nullable=True)
    current_action = Column(String, nullable=True)
    action_queue = Column(JSONB, nullable=True)
    party_id = Column(String, ForeignKey('parties.id'), nullable=True)
    state_variables = Column(JSONB, nullable=True)
    health = Column(Float, nullable=True)
    max_health = Column(Float, nullable=True)
    is_alive = Column(Boolean, default=True)
    status_effects = Column(JSONB, nullable=True)
    is_temporary = Column(Boolean, default=False)
    archetype = Column(String, nullable=True)
    traits = Column(JSONB, nullable=True)
    desires = Column(JSONB, nullable=True)
    motives = Column(JSONB, nullable=True)
    skills_data = Column(JSONB, nullable=True)
    equipment_data = Column(JSONB, nullable=True)
    abilities_data = Column(JSONB, nullable=True)
    faction = Column(JSONB, nullable=True)
    behavior_tags = Column(JSONB, nullable=True)
    loot_table_id = Column(String, nullable=True)
    effective_stats_json = Column(JSONB, nullable=True)
    faction_id = Column(String, nullable=True, index=True)

    location = relationship("Location")
    party = relationship("Party")

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    backstory_i18n = Column(JSONB, nullable=True)
    persona_i18n = Column(JSONB, nullable=True)
    effective_stats_json = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatednpc_guild_id', 'guild_id'),)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(String, primary_key=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_generatedfaction_guild_id', 'guild_id'),)


class GlobalNpc(Base):
    __tablename__ = 'global_npcs'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=True)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    npc_template_id = Column(String, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    faction_id = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    current_location = relationship("Location")

    __table_args__ = (
        Index('idx_globalnpc_guild_id', 'guild_id'),
        Index('idx_globalnpc_faction_id', 'faction_id'),
        Index('idx_globalnpc_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<GlobalNpc(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


class QuestTable(Base):
    __tablename__ = 'quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    status = Column(String, default='available', nullable=False)
    influence_level = Column(String, default='local', nullable=True)
    prerequisites_json_str = Column(Text, nullable=True)
    connections_json = Column(JSONB, nullable=True)
    rewards_json_str = Column(Text, nullable=True)
    npc_involvement_json = Column(JSONB, nullable=True)
    consequences_json_str = Column(Text, nullable=True)
    quest_giver_details_i18n = Column(JSONB, nullable=True)
    consequences_summary_i18n = Column(JSONB, nullable=True)
    ai_prompt_context_json_str = Column(Text, nullable=True)
    is_ai_generated = Column(Boolean, default=False, nullable=False)
    __table_args__ = (Index('idx_quests_guild_id', 'guild_id'),)


class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    status = Column(String, default='available', nullable=True)
    suggested_level = Column(Integer, nullable=True)
    rewards_json = Column(Text, nullable=True)
    prerequisites_json = Column(Text, nullable=True)
    consequences_json = Column(Text, nullable=True)
    quest_giver_npc_id = Column(String, nullable=True)
    ai_prompt_context_json = Column(Text, nullable=True)
    quest_giver_details_i18n = Column(JSONB, nullable=True)
    consequences_summary_i18n = Column(JSONB, nullable=True)

    steps = relationship("QuestStepTable", back_populates="quest", cascade="all, delete-orphan")

    __table_args__ = (Index('idx_generatedquest_guild_id', 'guild_id'),)


class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    template_id = Column(String, ForeignKey('item_templates.id'), nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    owner_id = Column(String, nullable=True)
    owner_type = Column(String, nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    quantity = Column(Integer, default=1)
    state_variables = Column(JSONB, nullable=True)
    is_temporary = Column(Boolean, default=False)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    properties = Column(JSONB, nullable=True)
    slot = Column(String, nullable=True)
    value = Column(Integer, nullable=True)
    __table_args__ = (Index('idx_item_guild_id', 'guild_id'),)


class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # This should ideally be character_id. For now, leaving as player_id.
    # If Character.inventory_json is used, this table might be for something else or deprecated for characters.
    player_id = Column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True)
    item_id = Column(String, ForeignKey('items.id', ondelete='CASCADE'), nullable=False, index=True)
    quantity = Column(Integer, default=1)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    player = relationship("Player")
    item = relationship("Item")

    __table_args__ = (
        UniqueConstraint('player_id', 'item_id', name='uq_player_item_inventory'),
        Index('idx_inventory_guild_player', 'guild_id', 'player_id')
    )


class Combat(Base):
    __tablename__ = 'combats'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    participants = Column(JSONB, nullable=False, default=lambda: [])
    initial_positions = Column(JSONB, nullable=True)
    current_round = Column(Integer, default=0)
    combat_log = Column(Text, nullable=True)
    turn_log_structured = Column(JSONB, nullable=True, default=lambda: [])
    state_variables = Column(JSONB, nullable=True)
    combat_rules_snapshot = Column(JSONB, nullable=True)
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

class PlayerNpcMemory(Base): # Already updated above, this is just to ensure it's not duplicated
    __tablename__ = 'player_npc_memory'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    character_id = Column(String, ForeignKey('characters.id', ondelete='CASCADE'), nullable=False, index=True)
    npc_id = Column(String, ForeignKey('npcs.id', ondelete='CASCADE'), nullable=False, index=True)
    memory_details_i18n = Column(JSONB, nullable=True)

    __table_args__ = (
        Index('idx_playernpcmemory_guild_char_npc', 'guild_id', 'character_id', 'npc_id'),
        Index('idx_playernpcmemory_character_id', 'character_id'),
        Index('idx_playernpcmemory_npc_id', 'npc_id'),
    )

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effect_i18n = Column(JSONB, nullable=False)
    cost = Column(JSONB, nullable=True)
    requirements = Column(JSONB, nullable=True)
    type_i18n = Column(JSONB, nullable=False)
    __table_args__ = (Index('idx_ability_guild_id', 'guild_id'),)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_skill_guild_id', 'guild_id'),)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    status_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    duration_turns = Column(Float, nullable=True)
    applied_at = Column(Float, nullable=True)
    source_id = Column(String, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    effects = Column(JSONB, nullable=True)
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)


class CraftingRecipe(Base):
    __tablename__ = 'crafting_recipes'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=True)

    ingredients_json = Column(JSONB, nullable=False, default=lambda: [])

    output_item_template_id = Column(String, ForeignKey('item_templates.id'), nullable=False)
    output_quantity = Column(Integer, default=1, nullable=False)

    required_skill_id = Column(String, ForeignKey('skills.id'), nullable=True)
    required_skill_level = Column(Integer, nullable=True)

    other_requirements_json = Column(JSONB, nullable=True, default=lambda: {})
    ai_metadata_json = Column(JSONB, nullable=True, default=lambda: {})

    __table_args__ = (
        Index('idx_craftingrecipe_guild_output_item', 'guild_id', 'output_item_template_id'),
        Index('idx_craftingrecipe_guild_skill', 'guild_id', 'required_skill_id'),
    )

    def __repr__(self):
        name_en = self.name_i18n.get('en', 'Unnamed Recipe') if isinstance(self.name_i18n, dict) else 'Unnamed Recipe (i18n error)'
        return f"<CraftingRecipe(id='{self.id}', name_en='{name_en}', guild_id='{self.guild_id}')>"


class CraftingQueue(Base):
    __tablename__ = 'crafting_queues'
    entity_id = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    queue = Column(JSONB, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    __table_args__ = (PrimaryKeyConstraint('entity_id', 'entity_type', 'guild_id'),)

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    __table_args__ = (Index('idx_itemproperty_guild_id', 'guild_id'),)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=True)
    __table_args__ = (Index('idx_questline_guild_id', 'guild_id'),)


class QuestStepTable(Base):
    __tablename__ = 'quest_steps'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    quest_id = Column(String, ForeignKey('generated_quests.id', ondelete='CASCADE'), nullable=False, index=True)

    quest = relationship("GeneratedQuest", back_populates="steps")

    title_i18n = Column(JSONB, nullable=True)
    description_i18n = Column(JSONB, nullable=True)
    requirements_i18n = Column(JSONB, nullable=True)

    required_mechanics_json = Column(JSONB, default=lambda: {}, nullable=False)
    abstract_goal_json = Column(JSONB, default=lambda: {}, nullable=False)
    conditions_json = Column(JSONB, default=lambda: {}, nullable=False)
    consequences_json = Column(JSONB, default=lambda: {}, nullable=False)

    step_order = Column(Integer, default=0, nullable=False)
    status = Column(String, default='pending', nullable=False)

    assignee_type = Column(String, nullable=True)
    assignee_id = Column(String, nullable=True)

    linked_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    linked_npc_id = Column(String, ForeignKey('npcs.id'), nullable=True)
    linked_item_id = Column(String, ForeignKey('items.id'), nullable=True)
    linked_guild_event_id = Column(String, ForeignKey('events.id'), nullable=True)

    __table_args__ = (
        Index('idx_queststep_guild_quest', 'guild_id', 'quest_id'),
    )


class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n = Column(JSONB, nullable=False)
    description_i18n = Column(JSONB, nullable=True)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    member_ids = Column(JSONB, nullable=True)
    destination_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    state_variables = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    current_location = relationship("Location", foreign_keys=[current_location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])

    __table_args__ = (
        Index('idx_mobilegroup_guild_id', 'guild_id'),
        Index('idx_mobilegroup_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<MobileGroup(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"

class PendingConflict(Base):
    __tablename__ = 'pending_conflicts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    conflict_data_json = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default='pending_gm_resolution', index=True)
    resolution_data_json = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)


class PendingGeneration(Base):
    __tablename__ = 'pending_generations'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    request_type = Column(String, nullable=False, index=True)
    request_params_json = Column(JSONB, nullable=True)

    raw_ai_output_text = Column(Text, nullable=True)
    parsed_data_json = Column(JSONB, nullable=True)
    validation_issues_json = Column(JSONB, nullable=True)

    status = Column(String, nullable=False, default="pending_validation", index=True)

    created_by_user_id = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    moderated_by_user_id = Column(String, nullable=True)
    moderated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    moderator_notes_i18n = Column(JSONB, nullable=True)

    __table_args__ = (
        Index('idx_pendinggeneration_guild_status', 'guild_id', 'status'),
    )

    def __repr__(self):
        return f"<PendingGeneration(id='{self.id}', guild_id='{self.guild_id}', type='{self.request_type}', status='{self.status}')>"


class NewItem(Base):
    __tablename__ = 'new_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    item_type = Column(String, nullable=False)
    item_metadata = Column(JSONB, name="metadata", nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint('name', name='uq_new_item_name'),)

    def __repr__(self):
        return f"<NewItem(id={self.id}, name='{self.name}', item_type='{self.item_type}')>"


class NewCharacterItem(Base):
    __tablename__ = 'new_character_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id = Column(String, ForeignKey('characters.id'), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey('new_items.id'), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship to Character needs to be defined on the Character model if using back_populates
    # character = relationship("Character", back_populates="new_items_association")
    item = relationship("NewItem")

    __table_args__ = (CheckConstraint('quantity > 0', name='check_new_char_item_quantity_positive'),)

    def __repr__(self):
        return f"<NewCharacterItem(id={self.id}, character_id='{self.character_id}', item_id='{self.item_id}', quantity={self.quantity})>"


class RPGCharacter(Base):
    __tablename__ = 'rpg_characters'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    class_name = Column(String, nullable=False)
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
    type_i18n = Column(JSON, nullable=True)
    inventory = Column(JSON, nullable=True)
    owner_id = Column(String, ForeignKey('npcs.id'), nullable=True)
    location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    economic_parameters_override = Column(JSON, nullable=True)

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
    )

    def __repr__(self):
        return f"<Currency(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}', is_default={self.is_default})>"


class UserSettings(Base):
    __tablename__ = 'user_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey('players.discord_id'), nullable=False)
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    language_code = Column(String(10), nullable=True)
    timezone = Column(String(50), nullable=True)

    player = relationship("Player", foreign_keys=[user_id], primaryjoin="UserSettings.user_id == Player.discord_id")


    __table_args__ = (
        UniqueConstraint('user_id', 'guild_id', name='uq_user_guild_settings'),
        Index('idx_user_settings_user_guild', 'user_id', 'guild_id')
    )

    def __repr__(self):
        return f"<UserSettings(id={self.id}, user_id='{self.user_id}', guild_id='{self.guild_id}', language_code='{self.language_code}')>"


class GuildConfig(Base):
    __tablename__ = 'guild_configs'

    guild_id = Column(String, primary_key=True, nullable=False, index=True)
    bot_language = Column(String, default='en', nullable=False)
    game_channel_id = Column(String, nullable=True)
    master_channel_id = Column(String, nullable=True)
    system_channel_id = Column(String, nullable=True)
    notification_channel_id = Column(String, nullable=True)

    def __repr__(self):
        return f"<GuildConfig(guild_id='{self.guild_id}', bot_language='{self.bot_language}')>"


class WorldState(Base):
    __tablename__ = 'world_states'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id = Column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    global_narrative_state_i18n = Column(JSONB, nullable=True)
    current_era_i18n = Column(JSONB, nullable=True)
    custom_flags = Column(JSONB, nullable=True)

    guild = relationship("GuildConfig")

    def __repr__(self):
        return f"<WorldState(id='{self.id}', guild_id='{self.guild_id}')>"

# Relationship on NewCharacterItem to Character needs to be updated if Character model name or back_populates changes.
# Check Character model: `new_items_association = relationship("NewCharacterItem", back_populates="character", cascade="all, delete-orphan")`
# In NewCharacterItem: `character = relationship("Character", back_populates="new_items_association")`
# This seems consistent.

# Final check for FKs pointing to `players.id` that should now point to `characters.id`:
# - Party.leader_id: Updated.
# - PlayerNpcMemory.player_id: Updated to character_id.
# - Inventory.player_id: Left as is for this subtask, as per instruction.
# - GameLog.player_id: Left as is, refers to Player account.
# - UserSettings.user_id: Refers to Player.discord_id, which is fine.
# - Relationship.entity1_id/entity2_id: These are generic and store IDs. If they store a player/character ID, the `entity_type`
#   field would differentiate. If `entity_type` is 'player' but now means 'character', then data migration for those
#   specific rows in the `relationships` table would be needed, changing `entity_id` to the `character_id` and
#   potentially `entity_type` to 'character'. The model itself doesn't need to change for this, but data does.
#   This is outside the scope of `models.py` changes but relevant for the migration.
#   For now, I'll assume the `Relationship` table structure itself is okay.
