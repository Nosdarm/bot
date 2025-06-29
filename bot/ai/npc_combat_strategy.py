from bot.database.database import get_db_session
from bot.database import crud
from bot.database import models
from bot import rules

def get_npc_combat_action(guild_id: int, npc_id: int, combat_instance_id: int):
    # ...
    return {"action": "attack", "target": "player"}
