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

class GlobalState(Base):
    __tablename__ = 'global_state'
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


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
