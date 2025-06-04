from sqlalchemy import Column, Integer, String, JSON, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'

    id = Column(String, primary_key=True)
    discord_id = Column(Integer, nullable=True)
    name = Column(String) # Assuming String for now, can be changed to JSON if needed
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    selected_language = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    unspent_xp = Column(Integer, default=0)
    gold = Column(Integer, default=0)
    current_game_status = Column(String, nullable=True)
    collected_actions_json = Column(JSON, nullable=True)
    current_party_id = Column(String, ForeignKey('parties.id'), nullable=True)

    location = relationship("Location")
    party = relationship("Party")

class Location(Base):
    __tablename__ = 'locations'

    id = Column(String, primary_key=True)
    static_name = Column(String, nullable=True)
    descriptions_i18n = Column(JSON, nullable=True)
    static_connections = Column(JSON, nullable=True)

class WorldState(Base):
    __tablename__ = 'world_state'

    key = Column(String, primary_key=True)
    value = Column(String)

class Party(Base):
    __tablename__ = 'parties'

    id = Column(String, primary_key=True)
    name_i18n = Column(JSON, nullable=True)
    player_ids = Column(JSON, nullable=True)
    current_location_id = Column(String, ForeignKey('locations.id'), nullable=True)
    turn_status = Column(String, nullable=True)

    location = relationship("Location")

class RulesConfig(Base):
    __tablename__ = 'rules_config'

    id = Column(String, primary_key=True, default='main_config')
    config_data = Column(JSON)

# Stub Tables
class GeneratedLocation(Base):
    __tablename__ = 'generated_locations'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class GeneratedNpc(Base):
    __tablename__ = 'generated_npcs'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class GeneratedFaction(Base):
    __tablename__ = 'generated_factions'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class GeneratedQuest(Base):
    __tablename__ = 'generated_quests'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(String, primary_key=True) # This might need to be a composite key or have a separate PK
    player_id = Column(String, ForeignKey('players.id'), nullable=False)
    item_id = Column(String, ForeignKey('items.id'), nullable=False)
    quantity = Column(Integer, default=1)
    placeholder = Column(Text, nullable=True) # To be removed later

    player = relationship("Player")
    item = relationship("Item")


class Log(Base): # Renamed from logs to avoid conflict with math.log if imported
    __tablename__ = 'logs'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Relationship(Base):
    __tablename__ = 'relationships'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class PlayerNpcMemory(Base):
    __tablename__ = 'player_npc_memory'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Ability(Base):
    __tablename__ = 'abilities'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Skill(Base):
    __tablename__ = 'skills'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Status(Base):
    __tablename__ = 'statuses'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class ItemProperty(Base):
    __tablename__ = 'item_properties'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class Questline(Base):
    __tablename__ = 'questlines'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class QuestStep(Base):
    __tablename__ = 'quest_steps'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)

class MobileGroup(Base):
    __tablename__ = 'mobile_groups'
    id = Column(String, primary_key=True)
    placeholder = Column(Text, nullable=True)
