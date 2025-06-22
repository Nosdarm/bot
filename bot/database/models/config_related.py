from sqlalchemy import (
    Column, Integer, String, JSON, ForeignKey, Boolean, Text,
    PrimaryKeyConstraint, Float, TIMESTAMP, Index, UniqueConstraint, CheckConstraint,
    ForeignKeyConstraint, and_
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column, backref
from sqlalchemy.sql import func
import uuid
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from ..base import Base

if TYPE_CHECKING:
    from .character_related import Player # Assuming Player is in character_related
    # If GuildConfig is related to Player or UserSettings via relationship, it should be here too.
    # For now, GuildConfig is mostly standalone or referenced by simple FKs.

class RulesConfig(Base):
    __tablename__ = 'rules_config'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships if any, e.g., to GuildConfig
    # guild_config: Mapped["GuildConfig"] = relationship(back_populates="rules_configs") # Example

    __table_args__ = (
        UniqueConstraint('guild_id', 'key', name='uq_guild_rule_key'),
        Index('idx_rulesconfig_guild_key', 'guild_id', 'key')
    )

class GlobalState(Base):
    __tablename__ = 'global_state'
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UserSettings(Base):
    __tablename__ = 'user_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    guild_id: Mapped[str] = mapped_column(String, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    player: Mapped["Player"] = relationship(
        "Player",
        foreign_keys=[user_id, guild_id],
        primaryjoin=lambda: and_(UserSettings.user_id == Player.discord_id, UserSettings.guild_id == Player.guild_id),
        back_populates="user_settings_entry"
    )

    # Relationship to GuildConfig (many UserSettings to one GuildConfig)
    # guild_config: Mapped["GuildConfig"] = relationship(back_populates="user_settings_entries") # Example

    __table_args__ = (
        ForeignKeyConstraint(
            ['user_id', 'guild_id'],
            ['players.discord_id', 'players.guild_id'],
            name='fk_user_settings_player_discord_guild',
            ondelete='CASCADE'
        ),
        UniqueConstraint('user_id', 'guild_id', name='uq_user_guild_settings'),
        Index('idx_user_settings_user_guild', 'user_id', 'guild_id')
    )

    def __repr__(self):
        return f"<UserSettings(id={self.id}, user_id='{self.user_id}', guild_id='{self.guild_id}', language_code='{self.language_code}')>"


class GuildConfig(Base):
    __tablename__ = 'guild_configs'

    guild_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False, index=True)
    bot_language: Mapped[str] = mapped_column(String, default='en', nullable=False)
    game_channel_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    master_channel_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    system_channel_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notification_channel_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Example relationships if GuildConfig has many RulesConfig or UserSettings
    # rules_configs: Mapped[List["RulesConfig"]] = relationship(back_populates="guild_config", cascade="all, delete-orphan")
    # user_settings_entries: Mapped[List["UserSettings"]] = relationship(back_populates="guild_config", cascade="all, delete-orphan")
    # players: Mapped[List["Player"]] = relationship(back_populates="guild_config", cascade="all, delete-orphan")


    def __repr__(self):
        return f"<GuildConfig(guild_id='{self.guild_id}', bot_language='{self.bot_language}')>"
