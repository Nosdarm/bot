from sqlalchemy import Column, Text, BOOLEAN, ForeignKey, Index, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from ..base import Base # Assuming your Base is in bot/database/base.py
import uuid

class GameLogEntry(Base):
    __tablename__ = 'game_logs'

    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)
    guild_id = Column(Text, ForeignKey('guild_configs.guild_id', name='fk_game_logs_guild_id_guild_configs', ondelete='CASCADE'), nullable=False, index=True)

    player_id = Column(Text, ForeignKey('players.id', name='fk_game_logs_player_id_players'), nullable=True, index=True)
    party_id = Column(Text, ForeignKey('parties.id', name='fk_game_logs_party_id_parties'), nullable=True, index=True)
    location_id = Column(Text, ForeignKey('locations.id', name='fk_game_logs_location_id_locations'), nullable=True, index=True)

    event_type = Column(Text, nullable=False, index=True)
    description_key = Column(Text, nullable=True)
    description_params_json = Column(JSONB, nullable=True)

    involved_entities_ids = Column(JSONB, nullable=True, comment='JSON array or object of involved entity IDs, e.g., {"characters": [], "npcs": []}')
    details = Column(JSONB, nullable=True, comment='Flexible JSON field for additional structured data about the event')
    channel_id = Column(Text, nullable=True)

    source_entity_id = Column(Text, nullable=True)
    source_entity_type = Column(Text, nullable=True)
    target_entity_id = Column(Text, nullable=True)
    target_entity_type = Column(Text, nullable=True)

    # Example of how a more specific index might be useful, though individual indexes above are good
    # __table_args__ = (
    #     Index('idx_game_logs_event_type_timestamp', 'guild_id', 'event_type', 'timestamp'),
    # )

    def __repr__(self):
        return f"<GameLogEntry(id='{self.id}', guild_id='{self.guild_id}', event_type='{self.event_type}')>"
