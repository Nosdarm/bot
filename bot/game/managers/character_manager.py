# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import logging
import asyncpg
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

from pydantic import BaseModel # Added for UpdateHealthResult

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified

from bot.database.models import Player, Character, PlayerDB, CharacterDB # Added PlayerDB, CharacterDB
from builtins import dict, set, list, int

from bot.game.utils import stats_calculator

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.npc_manager import NPCManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.game_manager import GameManager
    from bot.database.guild_transaction import GuildTransaction # Added for type hint

logger = logging.getLogger(__name__)

class CharacterAlreadyExistsError(Exception):
    pass

# Pydantic model for update_health return type
class UpdateHealthResult(BaseModel):
    applied_amount: float
    actual_hp_change: float
    current_hp: float
    max_hp: float
    is_alive: bool
    original_hp: float

class CharacterManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _characters: Dict[str, Dict[str, Character]]
    _discord_to_player_map: Dict[str, Dict[int, str]] # discord_user_id (int) -> player_id (str)
    _entities_with_active_action: Dict[str, Set[str]]
    _dirty_characters: Dict[str, Set[str]]
    _deleted_characters_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        npc_manager: Optional["NPCManager"] = None,
        inventory_manager: Optional["InventoryManager"] = None,
        equipment_manager: Optional["EquipmentManager"] = None,
        game_manager: Optional["GameManager"] = None # Added GameManager
    ):
        logger.info("Initializing CharacterManager...")
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._npc_manager = npc_manager
        self._inventory_manager = inventory_manager
        self._equipment_manager = equipment_manager
        self._game_manager = game_manager # Store GameManager

        self._characters = {}
        self._discord_to_player_map = {}
        self._entities_with_active_action = {}
        self._dirty_characters = {}
        self._deleted_characters_ids = {}
        logger.info("CharacterManager initialized.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Character, session_for_db: Optional[AsyncSession] = None) -> None:
        if not self._game_manager: # Check if game_manager is available
            logger.warning(f"CM: GameManager not available for stats recalculation of character {character_id} in guild {guild_id}.")
            char_model.effective_stats_json = json.dumps({"error": "game_manager_unavailable"})
            if session_for_db: # Only flag modified if a session is provided, otherwise it's an in-memory change
                flag_modified(char_model, "effective_stats_json")
            return
        try:
            # Assuming calculate_effective_stats is an async method or function
            effective_stats_dict = await stats_calculator.calculate_effective_stats(entity=char_model, guild_id=guild_id, game_manager=self._game_manager)
            char_model.effective_stats_json = json.dumps(effective_stats_dict or {}) # Ensure it's not None
            if session_for_db:
                flag_modified(char_model, "effective_stats_json")
            logger.debug(f"CM: Recalculated and stored effective_stats for character {character_id} in guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CM: ERROR recalculating effective_stats for character {character_id} in guild {guild_id}: {es_ex}", exc_info=True)
            char_model.effective_stats_json = json.dumps({"error": "calculation_failed"})
            if session_for_db:
                flag_modified(char_model, "effective_stats_json")


    async def trigger_stats_recalculation(self, guild_id: str, character_id: str, session: Optional[AsyncSession] = None) -> None:
        """Triggers recalculation of effective stats for a character and marks them dirty or updates in session."""
        char_model: Optional[Character] = None # Use the ORM model Character
        if session: # If a session is provided, try to get the character from the DB via session
            char_model = await session.get(Character, character_id)
            # Ensure the character belongs to the correct guild
            if char_model and str(char_model.guild_id) != guild_id:
                logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} found but belongs to different guild {char_model.guild_id} instead of {guild_id}.")
                char_model = None # Invalidate if guild mismatch
        else: # Otherwise, get from cache
            char_model = self.get_character(guild_id, character_id)

        if char_model:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model, session_for_db=session)
            if session: # If session was provided, the changes are part of the session
                session.add(char_model) # Ensure it's added if it was fetched/modified
            else: # If no session, mark as dirty for the main save loop
                self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CM: Stats recalculation triggered for character {character_id} in guild {guild_id}. Session used: {'Yes' if session else 'No'}.")
        else:
            logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} not found in guild {guild_id}.")


    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]:
        """Retrieves a character from the manager's cache."""
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
            return guild_chars.get(character_id)
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        """
        Retrieves the active character for a given Discord user ID within a guild.
        Uses cache first, then falls back to DB query.
        """
        guild_id_str = str(guild_id)
        active_char_id: Optional[str] = None

        # Try to find player_id from discord_to_player_map cache
        player_id_from_cache = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)

        db_session_is_external = session is not None
        actual_session: AsyncSession = session if db_session_is_external else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service:
             logger.error("CM.get_character_by_discord_id: DBService not available and no session passed.")
             return None

        try:
            if not db_session_is_external: await actual_session.__aenter__() # type: ignore

            if player_id_from_cache:
                # If player_id is cached, try to get Player from DB to confirm active_character_id
                player = await actual_session.get(Player, player_id_from_cache) # Use Player ORM model
                if player and str(player.guild_id) == guild_id_str:
                    active_char_id = player.active_character_id
                else:
                    logger.debug(f"Player {player_id_from_cache} (from cache for Discord {discord_user_id}) not found in DB or guild mismatch.")
                    # Clear potentially stale cache entry
                    if guild_id_str in self._discord_to_player_map and discord_user_id in self._discord_to_player_map[guild_id_str]:
                        del self._discord_to_player_map[guild_id_str][discord_user_id]
            else:
                # Player not in cache, query DB by discord_id and guild_id
                from bot.database.crud_utils import get_entity_by_attributes
                player_account = await get_entity_by_attributes(actual_session, Player, {"discord_id": str(discord_user_id)}, guild_id_str) # Use Player ORM model
                if player_account:
                    # Update cache
                    self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_account.id
                    active_char_id = player_account.active_character_id
                else:
                    logger.info(f"Player account not found in DB for Discord ID {discord_user_id} in guild {guild_id_str}.")
                    return None # No player, so no character

            if active_char_id:
                # Try to get character from cache first
                character = self.get_character(guild_id_str, active_char_id)
                if character:
                    return character
                # If not in cache, fetch from DB
                character = await actual_session.get(Character, active_char_id) # Use Character ORM model
                if character and str(character.guild_id) == guild_id_str:
                    # Add to cache if fetched from DB
                    self._characters.setdefault(guild_id_str, {})[active_char_id] = character
                    return character
                else:
                    logger.warning(f"Active character {active_char_id} for player (Discord: {discord_user_id}) not found in DB or guild mismatch.")
                    return None
            else: # No active_character_id set for the player
                logger.info(f"No active character set for player (Discord: {discord_user_id}) in guild {guild_id_str}.")
                return None

        except Exception as e:
            logger.error(f"Error in get_character_by_discord_id for {discord_user_id} in guild {guild_id_str}: {e}", exc_info=True)
            return None
        finally:
            if not db_session_is_external and actual_session : await actual_session.__aexit__(None, None, None) # type: ignore

    async def _create_and_activate_char_in_session(
        self, session: AsyncSession, guild_id: str, discord_user_id: int, character_name: str, player_language: Optional[str] = None
    ) -> Optional[Character]: # Return type is ORM Character model
        from bot.database.crud_utils import get_entity_by_attributes, create_entity
        # PlayerDB and CharacterDB are likely aliases or specific types for ORM models.
        # Assuming PlayerDB refers to the ORM model Player, and CharacterDB to Character.
        # If they are different, the import `from bot.database.models import Player, Character, PlayerDB, CharacterDB`
        # should make them available. For clarity, I'll use Player and Character where appropriate if PlayerDB/CharacterDB are just conceptual.
        # If PlayerDB/CharacterDB are distinct ORM models, those should be used. The log used PlayerDB.

        guild_id_str = str(guild_id)
        discord_user_id_str = str(discord_user_id)

        # 1. Find or Create Player
        # The error was here: guild_id was in the attributes dict.
        # Corrected: guild_id_str is now a separate argument. Model is PlayerDB (as per log).
        player_db_model = await get_entity_by_attributes(session, PlayerDB, {"discord_id": discord_user_id_str}, guild_id_str)
        if not player_db_model:
            logger.info(f"Player not found for Discord ID {discord_user_id_str}, guild {guild_id_str}. Creating new player.")
            player_data = {
                "discord_id": discord_user_id_str,
                "guild_id": guild_id_str, # guild_id is part of player data
                "settings_json": json.dumps({"language": player_language or self._settings.get("DEFAULT_LANGUAGE", "en")})
            }
            # create_entity's third arg is 'data', fourth is 'guild_id' for explicit override/check.
            player_db_model = await create_entity(session, PlayerDB, player_data, guild_id=guild_id_str)
            if not player_db_model:
                logger.error(f"Failed to create player for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
                return None
            logger.info(f"Player {player_db_model.id} created for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
        else:
            logger.info(f"Player {player_db_model.id} found for Discord ID {discord_user_id_str}, guild {guild_id_str}.")
            player_settings_str = player_db_model.settings_json if player_db_model.settings_json else '{}'
            player_settings = json.loads(player_settings_str)
            if player_language and player_settings.get('language') != player_language:
                player_settings['language'] = player_language
                player_db_model.settings_json = json.dumps(player_settings)
                flag_modified(player_db_model, "settings_json") # Mark as modified for SQLAlchemy
                logger.info(f"Updated language for player {player_db_model.id} to {player_language}.")

        # Check for existing character with the same name for this player
        # Corrected: guild_id_str is now a separate argument. Model is CharacterDB.
        existing_character_with_name = await get_entity_by_attributes(
            session,
            CharacterDB,
            {"name": character_name, "player_id": player_db_model.id}, # attributes dict
            guild_id_str # guild_id as separate parameter
        )
        if existing_character_with_name:
            logger.warning(f"Character with name '{character_name}' already exists for player {player_db_model.id} in guild {guild_id_str}.")
            # Consider raising CharacterAlreadyExistsError here to be caught by the caller
            # raise CharacterAlreadyExistsError(f"A character named '{character_name}' already exists for your player.")
            return None # Or specific error code/object

        # 2. Create Character
        default_stats = self._settings.get("new_character_defaults", {}).get("stats", {"health": 100, "attack": 10, "defense": 5})
        default_level_details = self._settings.get("new_character_defaults", {}).get("level_details", {"current_level": 1, "current_xp": 0, "xp_to_next_level": 100})
        default_status_effects = self._settings.get("new_character_defaults", {}).get("status_effects", [])
        default_location_id = self._settings.get("new_character_defaults", {}).get("location_id")

        character_id = str(uuid.uuid4())
        character_data = {
            "id": character_id,
            "player_id": player_db_model.id,
            "guild_id": guild_id_str, # guild_id is part of character data
            "name": character_name,
            "current_hp": float(default_stats.get("health", 100.0)),
            "max_hp": float(default_stats.get("health", 100.0)),
            "base_stats_json": json.dumps(default_stats),
            "level_details_json": json.dumps(default_level_details),
            "status_effects_json": json.dumps(default_status_effects),
            "action_queue_json": json.dumps([]),
            "is_npc": False,
            "is_alive": True,
        }
        if default_location_id:
            character_data["location_id"] = default_location_id

        # Create inventory and equipment if managers are available
        if self._inventory_manager:
            inv_id = await self._inventory_manager.create_inventory_for_entity(session, entity_id=character_id, entity_type="character", guild_id=guild_id_str)
            if inv_id: character_data["inventory_id"] = inv_id
        if self._equipment_manager:
            eq_id = await self._equipment_manager.create_equipment_for_entity(session, entity_id=character_id, entity_type="character", guild_id=guild_id_str)
            if eq_id: character_data["equipment_id"] = eq_id

        new_character_db = await create_entity(session, CharacterDB, character_data, guild_id=guild_id_str)
        if not new_character_db:
            logger.error(f"Failed to create character '{character_name}' for player {player_db_model.id}, guild {guild_id_str}.")
            return None
        logger.info(f"Character {new_character_db.id} ('{character_name}') created for player {player_db_model.id}, guild {guild_id_str}.")

        # Initialize effective stats
        await self._recalculate_and_store_effective_stats(guild_id_str, new_character_db.id, new_character_db, session_for_db=session)

        # 3. Activate Character for Player
        player_db_model.active_character_id = new_character_db.id
        # session.add(player_db_model) # Not strictly needed if already in session and GuildTransaction commits

        # 4. Update caches
        self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_db_model.id
        self._characters.setdefault(guild_id_str, {})[new_character_db.id] = new_character_db
        self.mark_character_dirty(guild_id_str, new_character_db.id) # Mark as dirty for next save cycle

        logger.info(f"Character {new_character_db.id} ('{character_name}') activated for player {player_db_model.id} (Discord: {discord_user_id_str}), guild {guild_id_str}.")
        return new_character_db # Return the ORM model instance


    async def create_and_activate_character_for_discord_user(
        self,
        guild_id: str,
        discord_user_id: int,
        character_name: str,
        player_language: Optional[str] = None
    ) -> Optional[Character]: # Return type is ORM Character model
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CM: DBService or session factory not available for character creation (guild {guild_id}).")
            return None

        from bot.database.guild_transaction import GuildTransaction # Local import
        guild_id_str = str(guild_id)

        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                created_char = await self._create_and_activate_char_in_session(
                    session, guild_id_str, discord_user_id, character_name, player_language
                )
                # Transaction commits automatically on successful exit of GuildTransaction context
                if created_char:
                    logger.info(f"CM: Successfully created and activated char '{character_name}' (ID: {created_char.id}) for user {discord_user_id} in guild {guild_id_str} within transaction.")
                else:
                    # If _create_and_activate_char_in_session returns None, it implies an issue like char already exists
                    # or failed to create player/char. The GuildTransaction will rollback if an unhandled exception occurred.
                    # If it's a "graceful" None return (e.g. char exists), the transaction might still commit if no error was raised.
                    # It's important that _create_and_activate_char_in_session raises an exception if the transaction should rollback.
                    logger.warning(f"CM: _create_and_activate_char_in_session returned None for '{character_name}', user {discord_user_id}, guild {guild_id_str}. Possible existing char or creation failure.")
                return created_char
        except IntegrityError as ie:
            logger.error(f"CM: Database integrity error (e.g. unique constraint) creating character '{character_name}' for user {discord_user_id} in guild {guild_id_str}: {ie}", exc_info=True)
            # Check if the error is due to character name uniqueness
            # This check is basic; more robust parsing might be needed depending on DB
            if "characters.name" in str(ie).lower() or "character_name_guild_idx" in str(ie).lower() : # Common unique constraint names
                 raise CharacterAlreadyExistsError(f"A character named '{character_name}' already exists in this guild.") from ie
            return None # Or re-raise a more generic error
        except CharacterAlreadyExistsError: # Re-raise if caught from _create_and_activate_char_in_session
             raise
        except Exception as e:
            logger.error(f"CM: Unexpected error in create_and_activate_character_for_discord_user for {discord_user_id} in {guild_id_str}: {e}", exc_info=True)
            return None

    async def update_health(
        self,
        guild_id: str,
        character_id: str,
        amount: float,
        session: Optional[AsyncSession] = None,
        **kwargs: Any
    ) -> Optional[UpdateHealthResult]:
        if not self._db_service and not session: # Need either DB service for new session or an existing one
            logger.error(f"CM: DBService not available and no session passed for update_health: char {character_id}.")
            return None

        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore

        try:
            # Begin transaction or nested block if session is managed, otherwise assume caller manages transaction
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1): # Dummy async context if not managing
                char_model = await actual_session.get(Character, character_id)
                if not char_model or str(char_model.guild_id) != guild_id:
                    logger.warning(f"CM.update_health: Character {character_id} not found or guild mismatch in guild {guild_id}.")
                    if manage_session: await actual_session.rollback() # Rollback if we started transaction
                    return None

                original_hp = float(char_model.current_hp)
                char_model.current_hp = float(char_model.current_hp) + amount
                char_model.max_hp = float(char_model.max_hp) # Ensure it's float

                if char_model.current_hp < 0: char_model.current_hp = 0.0
                if char_model.current_hp > char_model.max_hp: char_model.current_hp = char_model.max_hp

                actual_hp_change = char_model.current_hp - original_hp
                char_model.is_alive = char_model.current_hp > 0

                flag_modified(char_model, "current_hp")
                flag_modified(char_model, "is_alive")
                actual_session.add(char_model) # Add to session to ensure changes are tracked

                logger.info(f"Character {character_id} health updated by {amount}. Original: {original_hp}, New: {char_model.current_hp}, Max: {char_model.max_hp}. Applied in session.")

                # If we manage session, commit happens on exiting 'async with actual_session.begin()'
                # If not manage_session, caller is responsible for commit/rollback.

                return UpdateHealthResult(
                    applied_amount=amount,
                    actual_hp_change=actual_hp_change,
                    current_hp=char_model.current_hp,
                    max_hp=char_model.max_hp,
                    is_alive=char_model.is_alive,
                    original_hp=original_hp
                )
        except Exception as e:
            logger.error(f"CM: Error updating health for char {character_id} in guild {guild_id}: {e}", exc_info=True)
            # if manage_session and actual_session.in_transaction(): # Ensure rollback if we started it and error occurred
            #    await actual_session.rollback() # This might be tricky with begin_nested or if begin() already handles it
            return None
        finally:
            if manage_session and actual_session: # Close session only if CharacterManager created it
                 await actual_session.close()


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or not hasattr(self._db_service, 'get_session_factory'): # Added factory check
            logger.error(f"CharacterManager: DB service or session factory not available for save_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        # Create copies to avoid issues if sets are modified during iteration (though less likely here)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            logger.debug(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id_str}.")
            return

        from bot.database.guild_transaction import GuildTransaction # Local import
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                if deleted_ids:
                    from sqlalchemy import delete as sqlalchemy_delete # Renamed to avoid conflict
                    # Important: Ensure that deleted_ids only contains IDs that truly belong to this guild.
                    # The mark_character_deleted method should ensure this.
                    stmt = sqlalchemy_delete(Character).where(Character.id.in_(list(deleted_ids)), Character.guild_id == guild_id_str)
                    result = await session.execute(stmt)
                    logger.info(f"CharacterManager: Executed delete for {result.rowcount} characters in DB for guild {guild_id_str}.")

                guild_cache = self._characters.get(guild_id_str, {})
                merged_count = 0
                for char_id in dirty_ids:
                    if char_id in guild_cache:
                        char_obj_from_cache = guild_cache[char_id]
                        # Ensure guild_id matches before merge - GuildTransaction also checks this
                        if str(getattr(char_obj_from_cache, 'guild_id', 'DIFFERENT')) != guild_id_str:
                            logger.error(f"CRITICAL: Character {char_id} in guild {guild_id_str} cache has mismatched guild_id {getattr(char_obj_from_cache, 'guild_id')}. Skipping save for this character.")
                            continue
                        await session.merge(char_obj_from_cache) # Merge from cache
                        merged_count +=1
                    else:
                        logger.warning(f"Character {char_id} marked dirty but not found in local cache for guild {guild_id_str}. Cannot save.")
                if merged_count > 0:
                    logger.info(f"CharacterManager: Merged {merged_count} dirty characters for guild {guild_id_str}.")

            # Cleanup local dirty/deleted sets only after successful transaction
            if guild_id_str in self._deleted_characters_ids:
                self._deleted_characters_ids[guild_id_str].clear() # Clear all processed deleted IDs
            if guild_id_str in self._dirty_characters:
                self._dirty_characters[guild_id_str].clear() # Clear all processed dirty IDs
                if not self._dirty_characters[guild_id_str]: # Remove empty set
                    del self._dirty_characters[guild_id_str]

            logger.info(f"CharacterManager: Successfully saved state for guild {guild_id_str}.")

        except ValueError as ve:
            logger.error(f"CharacterManager: GuildTransaction integrity error during save_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: Error during save_state for guild {guild_id_str}: {e}", exc_info=True)


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or not hasattr(self._db_service, 'get_session_factory'): # Added factory check
            logger.error(f"CharacterManager: DB service or session factory not available for load_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        logger.info(f"CharacterManager: Loading state for guild {guild_id_str}.")

        # Reset guild-specific caches
        self._characters[guild_id_str] = {}
        self._discord_to_player_map[guild_id_str] = {}
        self._entities_with_active_action.pop(guild_id_str, None) # Remove or reset
        self._dirty_characters.pop(guild_id_str, None)
        self._deleted_characters_ids.pop(guild_id_str, None)

        from bot.database.crud_utils import get_entities
        from bot.database.guild_transaction import GuildTransaction # Local import

        try:
            # Use GuildTransaction for read-only operations to ensure session.info is set if crud_utils use it.
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str, commit_on_exit=False) as session:
                all_players_in_guild = await get_entities(session, Player, guild_id=guild_id_str) # Use Player ORM model
                for player_obj in all_players_in_guild:
                    if player_obj.discord_id: # Ensure discord_id is not None
                        try:
                            # discord_id from DB is string, map key is int
                            self._discord_to_player_map.setdefault(guild_id_str, {})[int(player_obj.discord_id)] = player_obj.id
                        except ValueError:
                             logger.warning(f"Could not parse discord_id '{player_obj.discord_id}' to int for player mapping (Player ID: {player_obj.id}).")
                logger.info(f"CharacterManager: Loaded {len(self._discord_to_player_map.get(guild_id_str, {}))} player ID mappings for guild {guild_id_str}.")

                all_characters_in_guild = await get_entities(session, Character, guild_id=guild_id_str) # Use Character ORM model
                loaded_char_count = 0
                for char_obj in all_characters_in_guild:
                    self._characters.setdefault(guild_id_str, {})[char_obj.id] = char_obj

                    # Check for active actions (current or queued)
                    current_action_q_str = char_obj.action_queue_json if char_obj.action_queue_json else "[]"
                    current_action_q = []
                    try:
                        current_action_q = json.loads(current_action_q_str)
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt action_queue_json for char {char_obj.id} in guild {guild_id_str}: {current_action_q_str}")

                    has_current_action = False
                    if char_obj.current_action_json:
                        if isinstance(char_obj.current_action_json, str) and char_obj.current_action_json.strip() and char_obj.current_action_json != "null":
                            try:
                                # Attempt to parse to ensure it's valid JSON and not just an empty string or "null"
                                if json.loads(char_obj.current_action_json): has_current_action = True
                            except json.JSONDecodeError:
                                logger.warning(f"Corrupt current_action_json for char {char_obj.id} in guild {guild_id_str}: {char_obj.current_action_json}")
                        elif isinstance(char_obj.current_action_json, dict) and char_obj.current_action_json: # if already a dict
                            has_current_action = True

                    if has_current_action or current_action_q:
                        self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_obj.id)
                    loaded_char_count += 1
                logger.info(f"CharacterManager: Loaded {loaded_char_count} characters for guild {guild_id_str}.")
                logger.info(f"CharacterManager: {len(self._entities_with_active_action.get(guild_id_str, set()))} entities with active actions in guild {guild_id_str}.")

        except ValueError as ve:
            logger.error(f"CharacterManager: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: DB error during load_state for guild {guild_id_str}: {e}", exc_info=True)


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Rebuilds runtime caches, e.g., after a bulk update or data migration."""
        logger.info(f"CharacterManager: Rebuilding runtime caches for guild {guild_id}. This involves reloading player maps and active action sets.")
        # This can be similar to parts of load_state, but focused on derived caches rather than primary data like self._characters.
        # For example, re-populating _discord_to_player_map and _entities_with_active_action from the current _characters cache.

        guild_id_str = str(guild_id)
        self._discord_to_player_map[guild_id_str] = {} # Reset player map for the guild
        self._entities_with_active_action[guild_id_str] = set() # Reset active action set

        # This part needs a session to fetch Players if _characters cache doesn't have player discord_id directly.
        # Assuming Character model has player_id, and Player model has discord_id.
        # For now, let's assume load_state would be called if a full refresh from DB is needed.
        # This rebuild will focus on caches derived from already loaded characters.

        guild_chars = self._characters.get(guild_id_str, {})
        if not guild_chars:
            logger.info(f"CharacterManager.rebuild_runtime_caches: No characters loaded for guild {guild_id_str}, nothing to rebuild caches from.")
            return

        # Rebuild _entities_with_active_action from current character objects in memory
        for char_id, char_obj in guild_chars.items():
            current_action_q_str = char_obj.action_queue_json or "[]"
            current_action_q = []
            try: current_action_q = json.loads(current_action_q_str)
            except json.JSONDecodeError: pass # Already logged in load_state

            has_current_action = False
            if char_obj.current_action_json:
                if isinstance(char_obj.current_action_json, str) and char_obj.current_action_json.strip() and char_obj.current_action_json != "null":
                    try:
                        if json.loads(char_obj.current_action_json): has_current_action = True
                    except json.JSONDecodeError: pass
                elif isinstance(char_obj.current_action_json, dict) and char_obj.current_action_json:
                    has_current_action = True

            if has_current_action or current_action_q:
                self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_id)

        logger.info(f"CharacterManager.rebuild_runtime_caches: Rebuilt _entities_with_active_action for guild {guild_id_str} ({len(self._entities_with_active_action.get(guild_id_str, set()))} active).")
        # Rebuilding _discord_to_player_map would require fetching Player objects or having discord_id on Character,
        # which is more involved than a simple cache rebuild from existing Character objects.
        # Typically, load_state handles the full population. If this method is needed for more, it might require DB access.
        logger.warning("CharacterManager.rebuild_runtime_caches: _discord_to_player_map not fully rebuilt by this method; rely on load_state for full DB sync.")
        pass


    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
        """Marks a character as needing to be saved to the database."""
        guild_id_str = str(guild_id)
        # Ensure the character actually exists in the cache for this guild before marking dirty
        if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
            self._dirty_characters.setdefault(guild_id_str, set()).add(character_id)
            logger.debug(f"Character {character_id} in guild {guild_id_str} marked as dirty.")
        else:
            logger.warning(f"Attempted to mark non-cached character {character_id} in guild {guild_id_str} as dirty.")

    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]:
        """Gets a character by name from the cache. Assumes names are unique within a guild for non-NPCs."""
        guild_id_str = str(guild_id)
        guild_chars = self._characters.get(guild_id_str)
        if guild_chars:
            for char in guild_chars.values():
                if char.name == name and not char.is_npc: # Example: only for player characters
                    return char
        return None

    async def get_character_by_name_async(self, session: AsyncSession, guild_id: str, name: str, is_npc: Optional[bool] = None) -> Optional[CharacterDB]:
        """ Fetches a character by name from the DB using the provided session. """
        from bot.database.crud_utils import get_entity_by_attributes
        # Uses CharacterDB as per original definition context of this example method

        attributes: Dict[str, Any] = {"name": name}
        if is_npc is not None:
            attributes["is_npc"] = is_npc

        # guild_id is a separate parameter for get_entity_by_attributes
        return await get_entity_by_attributes(session, CharacterDB, attributes, str(guild_id))


    def get_all_characters(self, guild_id: str, include_npcs: bool = True) -> List[Character]:
        """Returns a list of all characters (optionally including NPCs) in a guild from cache."""
        guild_id_str = str(guild_id)
        guild_chars = self._characters.get(guild_id_str, {})
        if include_npcs:
            return list(guild_chars.values())
        else:
            return [char for char in guild_chars.values() if not char.is_npc]

    def get_characters_in_location(self, guild_id: str, location_id: str, include_npcs: bool = True) -> List[Character]:
        """Returns characters from cache currently in the specified location."""
        guild_id_str = str(guild_id)
        location_id_str = str(location_id) # Ensure location_id is also string for comparison

        chars_in_location = []
        for char in self._characters.get(guild_id_str, {}).values():
            if str(char.location_id) == location_id_str:
                if include_npcs or not char.is_npc:
                    chars_in_location.append(char)
        return chars_in_location

    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        """Returns a set of character IDs that have an active action or items in their action queue."""
        return self._entities_with_active_action.get(str(guild_id), set()).copy() # Return a copy

    def is_busy(self, guild_id: str, character_id: str) -> bool:
        """Checks if a character is currently busy (has an active action or queued actions)."""
        guild_id_str = str(guild_id)
        return character_id in self._entities_with_active_action.get(guild_id_str, set())

    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        """Marks a character for deletion from the database and removes from cache."""
        guild_id_str = str(guild_id)

        # Remove from main character cache
        if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
            del self._characters[guild_id_str][character_id]
            if not self._characters[guild_id_str]: # Remove guild entry if empty
                del self._characters[guild_id_str]

            # Add to deleted set for DB operation
            self._deleted_characters_ids.setdefault(guild_id_str, set()).add(character_id)
            logger.info(f"Character {character_id} in guild {guild_id_str} marked for deletion and removed from cache.")

            # Clean up other caches
            self._dirty_characters.get(guild_id_str, set()).discard(character_id)
            self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)

            # Player's active_character_id should be cleared if this was their active character.
            # This requires finding the player linked to this character, typically via Player.active_character_id == character_id.
            # This operation might be better handled in a higher-level service that can update the Player model.
            # For now, this manager focuses on the Character entity itself.
            # Consider: if a player's active char is deleted, their active_character_id should be set to None.
            # This would typically be part of the same transaction deleting the character.

        else:
            logger.warning(f"Attempted to mark non-cached or already removed character {character_id} in guild {guild_id_str} for deletion.")


    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], session: Optional[AsyncSession] = None, **kwargs: Any) -> bool:
        """Sets or clears the party ID for a character both in cache and DB (if session provided)."""
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)

        if char:
            char.party_id = party_id
            self.mark_character_dirty(guild_id_str, character_id)
            logger.debug(f"Character {character_id} party_id set to {party_id} in cache for guild {guild_id_str}.")

            if session: # If a DB session is provided, update in DB as well
                db_char = await session.get(Character, character_id)
                if db_char and str(db_char.guild_id) == guild_id_str:
                    db_char.party_id = party_id
                    session.add(db_char) # Add to session to track changes
                    flag_modified(db_char, "party_id")
                    logger.debug(f"Character {character_id} party_id updated in DB session for guild {guild_id_str}.")
                elif db_char: # Found but guild mismatch
                     logger.warning(f"set_party_id: Character {character_id} found in DB but guild mismatch ({db_char.guild_id} vs {guild_id_str}).")
                else: # Not found in DB
                    logger.warning(f"set_party_id: Character {character_id} not found in DB for guild {guild_id_str} during session update.")
            return True
        else:
            logger.warning(f"Character {character_id} not found in cache for guild {guild_id_str}. Cannot set party ID.")
            return False

    async def update_character_location(
        self, character_id: str, new_location_id: Optional[str], guild_id: str, session: Optional[AsyncSession] = None, **kwargs: Any
    ) -> Optional[Character]:
        """Updates a character's location in cache and optionally in DB if session is provided."""
        guild_id_str = str(guild_id)
        char_in_cache = self.get_character(guild_id_str, character_id)

        if char_in_cache:
            char_in_cache.location_id = new_location_id
            self.mark_character_dirty(guild_id_str, character_id)
            logger.info(f"Character {character_id} location updated to {new_location_id} in cache (Guild: {guild_id_str}).")

            if session:
                db_char = await session.get(Character, character_id)
                if db_char and str(db_char.guild_id) == guild_id_str:
                    db_char.location_id = new_location_id
                    session.add(db_char)
                    flag_modified(db_char, "location_id")
                    logger.info(f"Character {character_id} location updated in DB session (Guild: {guild_id_str}).")
                    return db_char # Return the DB model if updated in session
                else:
                    logger.warning(f"update_character_location: Character {character_id} not found in DB or guild mismatch during session update (Guild: {guild_id_str}).")
                    return None # DB update failed
            return char_in_cache # Return cache model if no session
        else:
            logger.warning(f"update_character_location: Character {character_id} not found in cache (Guild: {guild_id_str}).")
            return None

    # Inventory and Equipment related methods would typically delegate to InventoryManager and EquipmentManager
    # For example:
    # async def add_item_to_inventory(...) -> bool:
    #     if self._inventory_manager:
    #         return await self._inventory_manager.add_item_to_character_inventory(...)
    #     logger.warning("InventoryManager not available.")
    #     return False
    # Similar for remove_item_from_inventory, equip_item, unequip_item etc.


    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        """Sets the current action for a character in cache and updates active action tracking."""
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_action_json_str = json.dumps(action_details) if action_details else None
            char.current_action_json = current_action_json_str
            self.mark_character_dirty(guild_id_str, character_id)

            active_actions_set = self._entities_with_active_action.setdefault(guild_id_str, set())
            action_queue = json.loads(char.action_queue_json or "[]")

            if action_details: # If setting a new action
                active_actions_set.add(character_id)
                logger.debug(f"Active action set for {character_id} in guild {guild_id_str}: {action_details}")
            elif not action_queue: # If clearing action AND queue is empty
                active_actions_set.discard(character_id)
                logger.debug(f"Active action cleared for {character_id} (no queued actions) in guild {guild_id_str}.")
            else: # Clearing current action but queue still has items
                logger.debug(f"Active action cleared for {character_id}, but queue still has actions in guild {guild_id_str}.")
        else:
            logger.warning(f"Cannot set active action: Character {character_id} not found in guild {guild_id_str}.")


    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None:
        """Adds an action to a character's action queue in cache."""
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            current_queue.append(action_details)
            char.action_queue_json = json.dumps(current_queue)
            self.mark_character_dirty(guild_id_str, character_id)

            # Entity is now busy if it wasn't before
            self._entities_with_active_action.setdefault(guild_id_str, set()).add(character_id)
            logger.debug(f"Action added to queue for {character_id} in guild {guild_id_str}: {action_details}")
        else:
            logger.warning(f"Cannot add action to queue: Character {character_id} not found in guild {guild_id_str}.")


    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and removes the next action from a character's queue in cache."""
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if char:
            current_queue = json.loads(char.action_queue_json or "[]")
            if current_queue:
                next_action = current_queue.pop(0)
                char.action_queue_json = json.dumps(current_queue)
                self.mark_character_dirty(guild_id_str, character_id)

                # If queue becomes empty AND there's no current action, mark not busy
                if not current_queue and not (char.current_action_json and json.loads(char.current_action_json)):
                    self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
                logger.debug(f"Retrieved next action for {character_id} from queue in guild {guild_id_str}: {next_action}")
                return next_action
            else: # Queue is empty
                # Ensure is_busy status is correct if current_action is also null
                if not (char.current_action_json and json.loads(char.current_action_json)):
                     self._entities_with_active_action.get(guild_id_str, set()).discard(character_id)
                logger.debug(f"Action queue empty for {character_id} in guild {guild_id_str}.")
                return None
        else:
            logger.warning(f"Cannot get next action: Character {character_id} not found in guild {guild_id_str}.")
            return None

    async def save_character(self, character: Character, guild_id: str) -> bool:
        """Saves a single character object to DB using a new session/transaction."""
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CM.save_character: DBService or session factory not available (guild {guild_id}).")
            return False

        guild_id_str = str(guild_id)
        if str(character.guild_id) != guild_id_str:
            logger.error(f"CM.save_character: Character {character.id} guild_id ({character.guild_id}) does not match target guild_id ({guild_id_str}). Aborting save.")
            return False

        from bot.database.guild_transaction import GuildTransaction # Local import
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                await session.merge(character)
            # Update cache after successful save
            self._characters.setdefault(guild_id_str, {})[character.id] = character
            self._dirty_characters.get(guild_id_str, set()).discard(character.id) # Remove from dirty set
            logger.info(f"Character {character.id} saved successfully to DB and cache updated for guild {guild_id_str}.")
            return True
        except Exception as e:
            logger.error(f"CM.save_character: Error saving character {character.id} for guild {guild_id_str}: {e}", exc_info=True)
            return False


    async def gain_xp(self, guild_id: str, character_id: str, amount: int, session: Optional[AsyncSession] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Adds XP to a character, handles level ups, and updates in cache/DB."""
        if amount <= 0:
            logger.debug(f"gain_xp: Non-positive XP amount ({amount}) for char {character_id}, no change.")
            return None

        guild_id_str = str(guild_id)

        # Determine if we need to manage the session
        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service :
             logger.error(f"CM.gain_xp: DBService not available and no session passed for char {character_id}.")
             return None

        try:
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1): # Dummy async context if not managing
                # Get character - try cache first, then DB if using own session
                char_model: Optional[Character] = None
                if not manage_session: # If session is passed, assume it might have the latest char
                    char_model = await actual_session.get(Character, character_id)
                    if char_model and str(char_model.guild_id) != guild_id_str: char_model = None # Guild mismatch

                if not char_model: # If not found via passed session or if we manage session
                    char_model = self.get_character(guild_id_str, character_id)
                    if char_model and manage_session: # If from cache and we manage session, ensure it's attached
                        char_model = await actual_session.merge(char_model)

                if not char_model:
                    logger.warning(f"gain_xp: Character {character_id} not found in guild {guild_id_str}.")
                    # if manage_session : await actual_session.rollback() # Rollback if we started transaction. begin() might handle this.
                    return None

                level_details = json.loads(char_model.level_details_json or '{}')
                original_level = level_details.get('current_level', 1)
                current_xp = level_details.get('current_xp', 0)
                xp_to_next = level_details.get('xp_to_next_level', 100) # Default from settings if not present

                current_xp += amount
                leveled_up = False
                levels_gained = 0

                # TODO: Incorporate RuleEngine for level progression if available
                # xp_to_next_level calculation might be dynamic (e.g., self._rule_engine.get_xp_for_level(new_level))
                while current_xp >= xp_to_next:
                    current_xp -= xp_to_next
                    level_details['current_level'] += 1
                    leveled_up = True
                    levels_gained +=1
                    # Get XP for the *new* next level
                    # Placeholder: simple doubling, replace with RuleEngine logic
                    xp_to_next = self._settings.get("xp_per_level_map", {}).get(str(level_details['current_level'] +1), xp_to_next * 2)
                    level_details['xp_to_next_level'] = xp_to_next

                level_details['current_xp'] = current_xp
                char_model.level_details_json = json.dumps(level_details)
                flag_modified(char_model, "level_details_json")

                if manage_session: # If we manage the session, model is already part of it via merge or get
                    pass
                else: # If session is passed, ensure char_model is added if it came from cache
                    actual_session.add(char_model)

                # Update cache directly
                self.mark_character_dirty(guild_id_str, character_id) # Mark dirty for save_state if session not managed by this call directly

                logger.info(f"Character {character_id} gained {amount} XP. New XP: {current_xp}, Level: {level_details['current_level']}.")
                if leveled_up:
                    logger.info(f"Character {character_id} leveled up to {level_details['current_level']}!")
                    # Potentially trigger stats update or other level-up events
                    await self.trigger_stats_recalculation(guild_id_str, character_id, session=actual_session)


                return {
                    "character_id": character_id,
                    "xp_gained": amount,
                    "current_xp": current_xp,
                    "current_level": level_details['current_level'],
                    "xp_to_next_level": xp_to_next,
                    "leveled_up": leveled_up,
                    "levels_gained": levels_gained,
                    "original_level": original_level
                }
        except Exception as e:
            logger.error(f"CM.gain_xp: Error processing XP for char {character_id} in guild {guild_id_str}: {e}", exc_info=True)
            return None
        finally:
            if manage_session and actual_session: # Close session only if CharacterManager created it
                 await actual_session.close()


    async def update_character_stats(
        self, guild_id: str, character_id: str, stats_update: Dict[str, Any],
        session: Optional[AsyncSession] = None, recalculate_effective: bool = True, **kwargs: Any
    ) -> bool:
        """
        Updates base stats for a character and optionally recalculates effective stats.
        Stats_update should be a dict like {"attack": 10, "defense": 5}.
        """
        guild_id_str = str(guild_id)
        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore
        if not actual_session and not self._db_service:
             logger.error(f"CM.update_character_stats: DBService not available and no session passed for char {character_id}.")
             return False

        try:
            async with actual_session.begin() if manage_session else asyncio.Semaphore(1): # Dummy async context
                char_model: Optional[Character] = None
                if not manage_session:
                    char_model = await actual_session.get(Character, character_id)
                    if char_model and str(char_model.guild_id) != guild_id_str: char_model = None

                if not char_model:
                    char_model = self.get_character(guild_id_str, character_id)
                    if char_model and manage_session:
                        char_model = await actual_session.merge(char_model) # Attach to session if managing

                if not char_model:
                    logger.warning(f"update_character_stats: Character {character_id} not found in guild {guild_id_str}.")
                    return False

                base_stats = json.loads(char_model.base_stats_json or '{}')
                updated_any = False
                for stat_name, value in stats_update.items():
                    if stat_name in base_stats and base_stats[stat_name] != value:
                        base_stats[stat_name] = value
                        updated_any = True
                    elif stat_name not in base_stats: # New stat being added
                        base_stats[stat_name] = value
                        updated_any = True

                if updated_any:
                    char_model.base_stats_json = json.dumps(base_stats)
                    flag_modified(char_model, "base_stats_json")
                    if not manage_session: actual_session.add(char_model) # Add if session passed

                    self.mark_character_dirty(guild_id_str, character_id) # Mark dirty for cache state
                    logger.info(f"Base stats updated for character {character_id} in guild {guild_id_str}. Update: {stats_update}")

                    if recalculate_effective:
                        await self.trigger_stats_recalculation(guild_id_str, character_id, session=actual_session)
                else:
                    logger.debug(f"No change in base stats for character {character_id} with update: {stats_update}")

                return True
        except Exception as e:
            logger.error(f"CM.update_character_stats: Error for char {character_id}, guild {guild_id_str}: {e}", exc_info=True)
            return False
        finally:
            if manage_session and actual_session:
                 await actual_session.close()
