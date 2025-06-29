from . import turn_queue
from . import check_resolver
from . import dice_roller
from bot.database.database import get_db_session
from bot.database import crud_utils as crud
from bot.database import models
from bot import rules

def process_turn(guild_id: int):
    with get_db_session() as db:
        queue = turn_queue.TurnQueue()
        action = queue.get_next_action(guild_id)
        while action:
            # Process action
            if action['type'] == 'intra_location':
                handle_intra_location_action(guild_id, db, action['player_id'], action['action_data'])
            elif action['type'] == 'skill_check':
                result = check_resolver.resolve_check(guild_id, action['check_type'], action['player_id'], 'Player')
                # Handle result
                if result['succeeded']:
                    # ...
                    pass
                else:
                    # ...
                    pass

            action = queue.get_next_action(guild_id)

def handle_intra_location_action(guild_id: int, db: any, player_id: int, action_data: dict):
    player = crud.get_entity_by_id(db, guild_id, models.Player, player_id)
    if player:
        location = crud.get_entity_by_id(db, guild_id, models.Location, player.current_location_id)
        if location and location.points_of_interest_json:
            for poi in location.points_of_interest_json:
                if poi['name_i18n']['en'].lower() == action_data['target'].lower():
                    # For now, just send the description
                    # In the future, this will be more complex
                    # and will involve checks, consequences, etc.
                    # We will also need to send this message to the player
                    # through the notification service.
                    print(poi['description_i18n']['en'])
                    break