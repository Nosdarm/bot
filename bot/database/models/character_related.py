import datetime # Moved to top
from sqlalchemy import (
    Column, Integer, String, JSON, ForeignKey, Boolean, Text,
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID # JSONB removed
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from ..base import Base, JsonVariant # Import Base and JsonVariant

if TYPE_CHECKING:
    from .config_related import UserSettings, GuildConfig # For type hinting
    from .world_related import Location
    # Forward declare Party for relationship hints because Party is defined later in this file
    class Party: pass
    # class Character: pass # Character is defined in this file, direct use is fine for self-refs if needed, or later refs


class Player(Base):
    __tablename__ = 'players'

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    discord_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    selected_language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    active_character_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('characters.id', name='fk_player_active_character', use_alter=True, ondelete='SET NULL'), nullable=True, index=True)

    characters: Mapped[List["Character"]] = relationship("Character", back_populates="player_account", cascade="all, delete-orphan", foreign_keys="Character.player_id")
    active_character: Mapped[Optional["Character"]] = relationship("Character", foreign_keys=[active_character_id], post_update=True, lazy="joined") # type: ignore

    user_settings_entry: Mapped[Optional["UserSettings"]] = relationship(
        "UserSettings",
        back_populates="player",
        uselist=False,
        cascade="all, delete-orphan"
    )

    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref like 'players'

    __table_args__ = (
        UniqueConstraint('discord_id', 'guild_id', name='uq_player_discord_guild'),
        Index('idx_player_guild_discord', 'guild_id', 'discord_id'),
    )

    def __repr__(self):
        return f"<Player(id='{self.id}', discord_id='{self.discord_id}', guild_id='{self.guild_id}', active_char_id='{self.active_character_id}')>"


class Character(Base):
    __tablename__ = 'characters'

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id: Mapped[str] = mapped_column(String, ForeignKey('players.id', ondelete='CASCADE'), nullable=False, index=True)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    name_i18n: Mapped[Dict[str, Any]] = mapped_column(JsonVariant, nullable=False)
    character_class_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    race_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    race_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    description_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unspent_xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gold: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    current_hp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_hp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_attack: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_defense: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    stats_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    effective_stats_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    status_effects_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing
    skills_data_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    abilities_data_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    spells_data_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    known_spells_json: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing
    spell_cooldowns_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    inventory_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing
    equipment_slots_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True, default=lambda: {})

    active_quests_json: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing
    flags_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    state_variables_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    current_game_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_action_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    action_queue_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing
    collected_actions_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted typing

    current_location_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('locations.id'), nullable=True, index=True)
    current_party_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('parties.id', name='fk_character_current_party'), nullable=True, index=True)

    player_account: Mapped["Player"] = relationship("Player", back_populates="characters", foreign_keys=[player_id])
    current_location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[current_location_id], lazy="select") # type: ignore
    current_party: Mapped[Optional["Party"]] = relationship("Party", foreign_keys=[current_party_id], lazy="select") # type: ignore

    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref

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
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    player_ids_json: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True)
    current_location_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('locations.id'), nullable=True)
    turn_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    leader_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('characters.id', name='fk_party_leader_character'), nullable=True)
    state_variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    current_action: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[current_location_id]) # type: ignore
    leader: Mapped[Optional["Character"]] = relationship("Character", foreign_keys=[leader_id]) # type: ignore
    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref

    # If Character.current_party relationship needs a back_populates:
    # characters_in_party: Mapped[List["Character"]] = relationship(back_populates="current_party")


class NPC(Base):
    __tablename__ = 'npcs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    name_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    description_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    backstory_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    persona_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    location_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('locations.id'), nullable=True)
    stats: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    inventory: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    current_action: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action_queue: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    party_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('parties.id'), nullable=True)
    state_variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    health: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_health: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True)
    status_effects: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    archetype: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    traits: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    desires: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    motives: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    skills_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    equipment_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    abilities_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    faction: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True) # Or string if it's an ID
    behavior_tags: Mapped[Optional[List[str]]] = mapped_column(JsonVariant, nullable=True) # Adjusted
    loot_table_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    effective_stats_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    faction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True) # Assuming this might link to a Factions table later
    schedule_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[location_id]) # type: ignore
    party: Mapped[Optional["Party"]] = relationship("Party", foreign_keys=[party_id]) # type: ignore
    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref
    # player_memories: Mapped[List["PlayerNpcMemory"]] = relationship(back_populates="npc") # Example


class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    description_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    backstory_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    persona_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    effective_stats_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)

    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref

    __table_args__ = (Index('idx_generatednpc_guild_id', 'guild_id'),)


class GlobalNpc(Base):
    __tablename__ = 'global_npcs'

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    name_i18n: Mapped[Dict[str, Any]] = mapped_column(JsonVariant, nullable=False)
    description_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    current_location_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey('locations.id'), nullable=True)
    npc_template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state_variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)
    faction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    current_location: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[current_location_id]) # type: ignore
    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref

    __table_args__ = (
        Index('idx_globalnpc_guild_id', 'guild_id'),
        Index('idx_globalnpc_faction_id', 'faction_id'),
        Index('idx_globalnpc_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<GlobalNpc(id='{self.id}', name_i18n='{self.name_i18n}', guild_id='{self.guild_id}')>"


class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memory'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    character_id: Mapped[str] = mapped_column(String, ForeignKey('characters.id', ondelete='CASCADE'), nullable=False, index=True)
    npc_id: Mapped[str] = mapped_column(String, ForeignKey('npcs.id', ondelete='CASCADE'), nullable=False, index=True) # Assuming npcs.id is String
    memory_details_i18n: Mapped[Optional[Dict[str, Any]]] = mapped_column(JsonVariant, nullable=True)

    guild_config: Mapped["GuildConfig"] = relationship(foreign_keys=[guild_id]) # Assuming GuildConfig has a backref
    character: Mapped["Character"] = relationship(foreign_keys=[character_id]) # Add back_populates if Character has a memories list
    npc: Mapped["NPC"] = relationship(foreign_keys=[npc_id]) # Add back_populates if NPC has a memories list

    __table_args__ = (
        Index('idx_playernpcmemory_guild_char_npc', 'guild_id', 'character_id', 'npc_id'),
        Index('idx_playernpcmemory_character_id', 'character_id'),
        Index('idx_playernpcmemory_npc_id', 'npc_id'),
        UniqueConstraint('character_id', 'npc_id', 'guild_id', name='uq_char_npc_guild_memory') # Ensure one memory entry
    )


class RPGCharacter(Base): # This seems like a different style of model, maybe from another part or older.
    __tablename__ = 'rpg_characters'

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    class_name: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    health: Mapped[int] = mapped_column(Integer, nullable=False)
    mana: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now()) # type: ignore
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()) # type: ignore

    __table_args__ = (
        CheckConstraint('level >= 0', name='check_level_non_negative'),
        CheckConstraint('health >= 0', name='check_health_non_negative'),
        CheckConstraint('mana >= 0', name='check_mana_non_negative'),
    )

    def __repr__(self):
        return f"<RPGCharacter(id={self.id}, name='{self.name}', class_name='{self.class_name}')>"

# Removed the import datetime from the end as it's now at the top.
