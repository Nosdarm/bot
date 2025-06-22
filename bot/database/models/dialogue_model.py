from sqlalchemy import Column, Text, JSON, BOOLEAN, DOUBLE_PRECISION, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from ..base import Base # Assuming your Base is in bot/database/base.py

class Dialogue(Base):
    __tablename__ = 'dialogues'

    id = Column(Text, primary_key=True)
    template_id = Column(Text, nullable=True)
    guild_id = Column(Text, ForeignKey('guild_configs.guild_id', ondelete='CASCADE'), nullable=False, index=True)
    participants = Column(JSONB, nullable=True)
    channel_id = Column(Text, nullable=True)
    current_stage_id = Column(Text, nullable=True)
    state_variables = Column(JSONB, nullable=True)
    last_activity_game_time = Column(DOUBLE_PRECISION, nullable=True)
    event_id = Column(Text, nullable=True)
    is_active = Column(BOOLEAN, default=True, nullable=False, index=True)

    # __table_args__ can be used for additional composite indexes or constraints if needed later.
    # For example:
    # __table_args__ = (
    #     Index('idx_dialogue_guild_active', 'guild_id', 'is_active'),
    # )

    def __repr__(self):
        return f"<Dialogue(id='{self.id}', guild_id='{self.guild_id}', is_active='{self.is_active}')>"
