from sqlalchemy import (
    Column, Integer, String, JSON, ForeignKey, Boolean, Text,
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List # Add other typing imports if model uses them

from ..base import Base # Import Base from the new location

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
    schedule_json = Column(JSONB, nullable=True) # Added for NPC schedules

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
