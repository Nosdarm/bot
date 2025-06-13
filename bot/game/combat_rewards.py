# bot/game/combat_rewards.py
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload # Ensure selectinload is imported

from bot.database.models import Combat, Character, Player, RulesConfig, GameLog
from bot.api.schemas.game_log_schemas import GameLogEntryCreate, ParticipatingEntity # For logging

logger = logging.getLogger(__name__)

async def apply_post_combat_updates(
    db: AsyncSession,
    guild_id: str,
    combat: Combat,
    # winning_team_id: Optional[str] # May not be directly used if outcome is in combat.status
):
    """
    Applies post-combat updates to characters (XP, loot, injuries, etc.)
    and logs these changes.
    """
    logger.info(f"Applying post-combat updates for combat {combat.id} in guild {guild_id}, status: {combat.status}")

    # Fetch RulesConfig for reward calculations
    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    rules_result = await db.execute(rules_stmt)
    rules_config = rules_result.scalars().first()
    if not rules_config:
        logger.error(f"Cannot apply post-combat rewards: RulesConfig not found for guild {guild_id}")
        # Log this failure as a system event?
        return

    config_data = rules_config.config_data or {}
    base_xp_reward = config_data.get("combat_xp_base", 50) # Example: base XP from rules

    log_entries_to_add = []

    # Determine winning team and losing team based on combat.status
    # Example: status "completed_victory_team_a" means team "A" won.
    winning_team_id = None
    if combat.status and "completed_victory_" in combat.status:
        try:
            winning_team_id = combat.status.split("completed_victory_")[1]
            logger.info(f"Combat {combat.id}: Winning team identified as '{winning_team_id}'")
        except IndexError:
            logger.warning(f"Could not parse winning team from combat status: {combat.status}")


    for participant_data in combat.participants: # This is List[Dict] from the JSON field
        entity_id = participant_data.get("entity_id")
        entity_type = participant_data.get("entity_type")
        team_id = participant_data.get("team_id")

        if entity_type != "character": # Only process characters for XP, loot etc. for now
            continue

        # Eager load player when fetching character
        char_stmt = select(Character).options(selectinload(Character.player)).where(Character.id == entity_id, Character.guild_id == guild_id)
        char_result = await db.execute(char_stmt)
        db_character = char_result.scalars().first()

        if not db_character:
            logger.warning(f"Post-combat: Character {entity_id} not found in guild {guild_id}. Skipping.")
            continue

        db_player = db_character.player # Eager loaded
        if not db_player:
            logger.warning(f"Post-combat: Player not found for character {entity_id}. Skipping rewards that require player model.")
            # Continue processing character-specific updates if any, but skip player-specific ones like gold.


        # --- Apply XP ---
        xp_change = 0
        if winning_team_id and team_id == winning_team_id:
            xp_change = base_xp_reward # Simplified: winners get base XP
            # TODO: More complex XP: based on enemies defeated, character contribution, etc.
        elif winning_team_id and team_id != winning_team_id:
            xp_change = base_xp_reward // 4 # Simplified: losers get less XP (consolation)
        else: # Draw or other outcomes
            xp_change = base_xp_reward // 2

        if xp_change > 0:
            db_character.xp = (db_character.xp or 0) + xp_change
            # TODO: Implement level up logic if db_character.xp >= xp_for_next_level(db_character.level, rules_config)
            logger.info(f"Character {db_character.id} awarded {xp_change} XP. New XP: {db_character.xp}")
            db.add(db_character) # Mark for update

            # Ensure player_id for logging is available
            player_id_for_log = db_player.id if db_player else None

            log_desc_xp = {"en": f"Character {db_character.name_i18n.get('en', db_character.id)} gained {xp_change} XP."}
            log_xp = GameLogEntryCreate(
                event_type="character_xp_change",
                player_id=player_id_for_log,
                description_i18n=log_desc_xp,
                involved_entities_ids=[ParticipatingEntity(type="character", id=db_character.id)],
                consequences_data={"xp_gained": xp_change, "new_total_xp": db_character.xp},
                details={"combat_id": combat.id, "reason": "combat_completion"}
            )
            log_entries_to_add.append(GameLog(guild_id=guild_id, **log_xp.dict(exclude_none=True)))


        # --- Apply Loot (Placeholder) ---
        # TODO: Determine loot based on defeated enemies, RuleConfig drop rates
        # Add items to db_character.inventory (which is JSON) or a linked Inventory table
        if db_player and winning_team_id and team_id == winning_team_id:
            # Example: give 10 gold
            db_player.gold = (db_player.gold or 0) + 10
            db.add(db_player)
            log_desc_gold = {"en": f"Player {db_player.name_i18n.get('en', db_player.id)} received 10 gold as loot."}
            log_gold = GameLogEntryCreate(
                event_type="player_gold_change",
                player_id=db_player.id,
                description_i18n=log_desc_gold,
                involved_entities_ids=[ParticipatingEntity(type="player", id=db_player.id)],
                consequences_data={"gold_added": 10, "new_total_gold": db_player.gold},
                details={"combat_id": combat.id, "reason": "combat_loot"}
            )
            log_entries_to_add.append(GameLog(guild_id=guild_id, **log_gold.dict(exclude_none=True)))


        # --- Apply Injuries/Status Effects (Placeholder) ---
        # TODO: Based on final HP, specific abilities used in combat, etc.
        # Update db_character.current_hp or db_character.status_effects (JSON)
        if participant_data.get("current_hp", 0) <= 0:
            # Character was defeated
            # Apply injury, e.g., a temporary negative status effect or stat reduction
            player_id_for_log = db_player.id if db_player else None
            log_desc_injury = {"en": f"Character {db_character.name_i18n.get('en', db_character.id)} was defeated and sustained injuries."}
            log_injury = GameLogEntryCreate(
                event_type="character_injury",
                player_id=player_id_for_log,
                description_i18n=log_desc_injury,
                involved_entities_ids=[ParticipatingEntity(type="character", id=db_character.id)],
                details={"combat_id": combat.id, "final_hp": participant_data.get("current_hp")}
            )
            log_entries_to_add.append(GameLog(guild_id=guild_id, **log_injury.dict(exclude_none=True)))

    if log_entries_to_add:
        db.add_all(log_entries_to_add)

    # The calling function (in combat router) should commit the session
    # which includes Character/Player updates and new GameLog entries.
    logger.info(f"Finished processing post-combat updates for combat {combat.id}.")
