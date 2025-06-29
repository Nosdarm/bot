from bot.database.database import get_db_session
from bot.database import crud_utils as crud
from bot.database import models
import json

def initialize_guild_data(guild):
    with get_db_session() as db:
        # Create GuildConfig
        crud.create_entity(db, guild.id, models.GuildConfig, id=guild.id, main_language='en')

        # Create static locations
        with open('data/locations.json') as f:
            locations = json.load(f)
        for loc_data in locations:
            crud.create_entity(db, guild.id, models.Location, **loc_data)