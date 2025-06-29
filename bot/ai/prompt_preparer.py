from bot.database.database import get_db_session
from bot.database import crud
from bot.database import models
from bot import rules

async def prepare_ai_prompt(guild_id: int, location_id: int, player_id: int = None, party_id: int = None):
    async with get_db_session() as db:
        # Get game terms
        game_terms = rules.get_rule(guild_id, "game_terms", {})

        # Get world state
        world_state = rules.get_rule(guild_id, "world_state", {})

        # Get relationships
        relationships = await crud.get_entities(db, models.Relationship, guild_id)

        # Get quests
        quests = await crud.get_entities(db, models.GeneratedQuest, guild_id)

        # Get lore
        lore = rules.get_rule(guild_id, "lore", {})

        # Get player and party info
        player_info = None
        if player_id:
            player = await crud.get_entity_by_id(db, models.Player, player_id, guild_id)
            if player:
                player_info = player.__dict__

        party_info = None
        if party_id:
            party = await crud.get_entity_by_id(db, models.Party, party_id, guild_id)
            if party:
                party_info = party.__dict__
        
        # Get location info
        location_info = None
        if location_id:
            location = await crud.get_entity_by_id(db, models.Location, location_id, guild_id)
            if location:
                location_info = location.__dict__
                
        # Get game entities
        game_entities = {}
        for model in [models.Player, models.GeneratedNpc, models.Item, models.Location]:
            entities = await crud.get_entities(db, model, guild_id)
            game_entities[model.__tablename__] = [e.__dict__ for e in entities]
            
        # Get game rules
        game_rules = rules.get_rule(guild_id, "game_rules", {})
        
        # Get recent events
        recent_events = await crud.get_entities(db, models.StoryLog, guild_id, order_by=[models.StoryLog.timestamp.desc()], limit=10)

        # Prepare prompt
        prompt = f"""
        Game Terms: {game_terms}
        World State: {world_state}
        Relationships: {relationships}
        Quests: {quests}
        Lore: {lore}
        Player: {player_info}
        Party: {party_info}
        Location: {location_info}
        Game Entities: {game_entities}
        Game Rules: {game_rules}
        Recent Events: {recent_events}
        """

        return prompt

def generate_factions_and_relationships(guild_id: int):
    # ...
    return {"success": True}

def generate_quest(guild_id: int):
    # ...
    return {"success": True}

def generate_trader(guild_id: int):
    # ...
    return {"success": True}
