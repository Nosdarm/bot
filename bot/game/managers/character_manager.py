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

from bot.database.models import Player, Character
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
    _discord_to_player_map: Dict[str, Dict[int, str]]
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
        game_manager: Optional["GameManager"] = None
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
        self._game_manager = game_manager

        self._characters = {}
        self._discord_to_player_map = {}
        self._entities_with_active_action = {}
        self._dirty_characters = {}
        self._deleted_characters_ids = {}
        logger.info("CharacterManager initialized.")

    async def _recalculate_and_store_effective_stats(self, guild_id: str, character_id: str, char_model: Character, session_for_db: Optional[AsyncSession] = None) -> None:
        if not self._game_manager:
            logger.warning(f"CM: GameManager NA for stats recalc: char {character_id}, guild {guild_id}.")
            char_model.effective_stats_json = json.dumps({"error": "game_manager_unavailable"})
            if session_for_db: flag_modified(char_model, "effective_stats_json")
            return
        try:
            effective_stats_dict = await stats_calculator.calculate_effective_stats(entity=char_model, guild_id=guild_id, game_manager=self._game_manager)
            char_model.effective_stats_json = json.dumps(effective_stats_dict or {})
            if session_for_db: flag_modified(char_model, "effective_stats_json")
            logger.debug(f"CM: Recalculated effective_stats for char {character_id}, guild {guild_id}.")
        except Exception as es_ex:
            logger.error(f"CM: ERROR recalculating stats for char {character_id}, guild {guild_id}: {es_ex}", exc_info=True)
            char_model.effective_stats_json = json.dumps({"error": "calculation_failed"})
            if session_for_db: flag_modified(char_model, "effective_stats_json")

    async def trigger_stats_recalculation(self, guild_id: str, character_id: str, session: Optional[AsyncSession] = None) -> None:
        char_model: Optional[Character] = None
        if session:
            char_model = await session.get(Character, character_id)
            if char_model and str(char_model.guild_id) != guild_id: char_model = None
        else: char_model = self.get_character(guild_id, character_id)

        if char_model:
            await self._recalculate_and_store_effective_stats(guild_id, character_id, char_model, session_for_db=session)
            if session: session.add(char_model)
            else: self.mark_character_dirty(guild_id, character_id)
            logger.info(f"CM: Stats recalc triggered for char {character_id}, guild {guild_id}. Session used: {'Yes' if session else 'No'}.")
        else: logger.warning(f"CM.trigger_stats_recalculation: Character {character_id} not found in guild {guild_id}.")

    def get_character(self, guild_id: str, character_id: str) -> Optional[Character]:
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars: return guild_chars.get(character_id)
        return None

    async def get_character_by_discord_id(self, guild_id: str, discord_user_id: int, session: Optional[AsyncSession] = None) -> Optional[Character]:
        guild_id_str = str(guild_id)
        # Attempt to retrieve player_id from the discord_to_player_map cache first
        player_id_in_cache = self._discord_to_player_map.get(guild_id_str, {}).get(discord_user_id)
        active_char_id: Optional[str] = None  # To store the active character ID once resolved

        # Helper function to perform the core logic given an active session
        async def _fetch_character_logic(current_session: AsyncSession, cached_player_id: Optional[str]) -> Optional[Character]:
            nonlocal active_char_id
            resolved_player_id = cached_player_id
            fetched_player_obj: Optional[Player] = None

            logger.debug(f"_fetch_character_logic: Start. discord_user_id={discord_user_id}, cached_player_id={resolved_player_id}, guild_id_str={guild_id_str}")

            # Path 1: Try cache for player_id, then session.get(Player, player_id)
            if resolved_player_id:
                logger.debug(f"_fetch_character_logic: Path A - Using cached_player_id: {resolved_player_id}")
                player = await current_session.get(Player, resolved_player_id)
                logger.debug(f"_fetch_character_logic: Path A - current_session.get(Player, '{resolved_player_id}') returned: {repr(player)}")
                if player:
                    logger.debug(f"_fetch_character_logic: Path A - Player object found: ID {getattr(player, 'id', 'N/A')}, Guild ID {getattr(player, 'guild_id', 'N/A')}. Expected guild: {guild_id_str}")
                    if str(getattr(player, 'guild_id', 'None')) == guild_id_str:
                        fetched_player_obj = player
                        logger.debug(f"_fetch_character_logic: Path A - Guild match. fetched_player_obj assigned: {getattr(fetched_player_obj, 'id', 'None')}")
                    else:
                        logger.warning(f"_fetch_character_logic: Path A - Guild mismatch for Player {getattr(player, 'id', 'N/A')}. Actual: {getattr(player, 'guild_id', 'N/A')}, Expected: {guild_id_str}. Invalidating cache.")
                        if guild_id_str in self._discord_to_player_map and discord_user_id in self._discord_to_player_map[guild_id_str]:
                            del self._discord_to_player_map[guild_id_str][discord_user_id]
                        resolved_player_id = None # Force DB lookup by attributes
                else:
                    logger.debug(f"_fetch_character_logic: Path A - Player with ID {resolved_player_id} (from cache) not found via session.get(). Invalidating cache.")
                    if guild_id_str in self._discord_to_player_map and discord_user_id in self._discord_to_player_map[guild_id_str]:
                        del self._discord_to_player_map[guild_id_str][discord_user_id]
                    resolved_player_id = None # Force DB lookup by attributes

            logger.debug(f"_fetch_character_logic: After Path A. resolved_player_id: {resolved_player_id}. fetched_player_obj is {'NOT None' if fetched_player_obj else 'None'}")

            # Path 2: If Path 1 failed (resolved_player_id became None) or no cached player_id initially
            if not resolved_player_id:
                logger.debug(f"_fetch_character_logic: Path B - resolved_player_id is None or was invalidated. Fetching by attributes for discord_id: {discord_user_id}, guild_id: {guild_id_str}")
                from bot.database.crud_utils import get_entity_by_attributes
                player_account = await get_entity_by_attributes(current_session, Player,
                                                               {"discord_id": str(discord_user_id)},
                                                               guild_id=guild_id_str)
                logger.debug(f"_fetch_character_logic: Path B - get_entity_by_attributes returned: {repr(player_account)}")
                if player_account: # Ensure player_account is not None and is a Player instance
                    logger.debug(f"_fetch_character_logic: Path B - Player {getattr(player_account, 'id', 'N/A')} found via attributes. Updating cache.")
                    self._discord_to_player_map.setdefault(guild_id_str, {})[discord_user_id] = player_account.id
                    fetched_player_obj = player_account
                    resolved_player_id = player_account.id
                    logger.debug(f"_fetch_character_logic: Path B - fetched_player_obj assigned: {getattr(fetched_player_obj, 'id', 'None')}")
                else:
                    logger.info(f"_fetch_character_logic: Path B - Player account not found by attributes for Discord ID {discord_user_id} in guild {guild_id_str}.")
                    # fetched_player_obj remains as it was (None if Path A also failed/didn't set it)

            logger.debug(f"_fetch_character_logic: FINAL PRE-CHECK before refresh block. fetched_player_obj: {repr(fetched_player_obj)}, type: {type(fetched_player_obj)}")

            # Explicitly refresh the Player object to get the latest active_character_id
            logger.debug(f"_fetch_character_logic: Checkpoint before 'isinstance' and 'is not None'. fetched_player_obj is {repr(fetched_player_obj)}, type: {type(fetched_player_obj)}")
            if fetched_player_obj is not None and isinstance(fetched_player_obj, Player): # Doubly sure it's a Player instance
                player_id_log = fetched_player_obj.id
                pre_refresh_ac_id_log = fetched_player_obj.active_character_id
                logger.debug(f"_fetch_character_logic: Player {player_id_log} (Discord: {discord_user_id}) confirmed as Player instance. Pre-refresh active_char_id: {pre_refresh_ac_id_log}")

                try:
                    # logger.debug(f"_fetch_character_logic: Attempting to EXPIRE Player {player_id_log}. Object: {repr(fetched_player_obj)}")
                    # await current_session.expire(fetched_player_obj) # Intentionally commented out to isolate TypeError
                    # logger.debug(f"_fetch_character_logic: EXPIRE successful for Player {player_id_log}. Object state after expire: {repr(fetched_player_obj)}")

                    logger.debug(f"_fetch_character_logic: Attempting to REFRESH Player {player_id_log} (all attributes). Object state before refresh: {repr(fetched_player_obj)}")
                    await current_session.refresh(fetched_player_obj) # Refresh all attributes

                    active_char_id = fetched_player_obj.active_character_id
                    logger.debug(f"_fetch_character_logic: Player {fetched_player_obj.id} (Discord: {discord_user_id}) REFRESHED. Post-refresh active_char_id: {active_char_id}")
                except Exception as refresh_exc:
                    logger.error(f"_fetch_character_logic: Exception during refresh for Player {player_id_log}: {refresh_exc}", exc_info=True)
                    # If refresh fails, use the active_char_id we had before attempting refresh
                    active_char_id = pre_refresh_ac_id_log
            elif fetched_player_obj is None:
                 logger.error(f"_fetch_character_logic: fetched_player_obj IS NONE before refresh block for Discord ID {discord_user_id}. Returning None.")
                 return None
            else:
                logger.error(f"_fetch_character_logic: fetched_player_obj is not a Player instance (type: {type(fetched_player_obj)}) but was not None for Discord ID {discord_user_id}. Cannot fetch character.")
                return None

            # Step 2: Fetch Character if active_char_id is known
            if active_char_id:
                # Check local Character object cache (self._characters) first
                character_in_cm_cache = self._characters.get(guild_id_str, {}).get(active_char_id)
                if character_in_cm_cache:
                    # logger.debug(f"Character {active_char_id} found in CharacterManager's character cache for player {resolved_player_id}.")
                    return character_in_cm_cache

                # If not in CM's character cache, fetch from DB using the current session
                character_from_db = await current_session.get(Character, active_char_id)
                if character_from_db and str(character_from_db.guild_id) == guild_id_str:
                    # Add to CharacterManager's character cache
                    self._characters.setdefault(guild_id_str, {})[character_from_db.id] = character_from_db
                    # logger.debug(f"Character {active_char_id} fetched from DB for player {resolved_player_id} and cached in CharacterManager.")
                    return character_from_db
                else:
                    # This case means player.active_character_id points to a non-existent/mismatched character
                    logger.warning(f"Active character ID {active_char_id} for player {resolved_player_id} (Discord: {discord_user_id}) "
                                   f"either not found in DB or belongs to a different guild. Expected guild: {guild_id_str}, "
                                   f"character's guild: {getattr(character_from_db, 'guild_id', 'N/A') if character_from_db else 'Not Found In DB'}.")
                    # Future enhancement: Consider clearing player.active_character_id in the DB if it's invalid.
                    # This would require fetching the player object again if not already available, marking field dirty, and flushing.
                    return None # Character not found or does not match guild
            else:
                # This means the player exists but has no active character (active_character_id is None or empty)
                logger.info(f"No active character ID associated with player {resolved_player_id} (Discord: {discord_user_id}) in guild {guild_id_str}.")
                return None

        # Main execution flow for get_character_by_discord_id:
        # Determines whether to use a provided session or create an internal one.
        try:
            if session:
                # An external session was provided by the caller. Use it directly.
                # logger.debug(f"Using provided external session for get_character_by_discord_id (Discord: {discord_user_id}, Guild: {guild_id_str}).")
                return await _fetch_character_logic(session, player_id_in_cache)
            else:
                # No external session was provided. Create and manage one internally.
                if not self._db_service:
                    logger.error("CM.get_character_by_discord_id: DBService not available and no external session passed. Cannot create internal session.")
                    return None
                # logger.debug(f"Creating internal session for get_character_by_discord_id (Discord: {discord_user_id}, Guild: {guild_id_str}).")
                async with self._db_service.get_session() as internal_session: # type: ignore
                    # internal_session is the actual AsyncSession object yielded by the context manager
                    return await _fetch_character_logic(internal_session, player_id_in_cache)
        except Exception as e:
            # Catch any unexpected errors during the process and log them.
            logger.error(f"Unexpected error in get_character_by_discord_id for Discord User {discord_user_id}, Guild {guild_id_str}: {e}", exc_info=True)
            return None

    async def update_health(
        self,
        guild_id: str,
        character_id: str,
        amount: float, # This is the amount to change health by (can be negative for damage)
        session: Optional[AsyncSession] = None,
        **kwargs: Any # For potential future use, e.g., source of damage/healing
    ) -> Optional[UpdateHealthResult]:
        if not self._db_service:
            logger.error(f"CM: DBService not available for update_health: char {character_id}.")
            return None

        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore

        async with actual_session.begin() if manage_session else actual_session.begin_nested(): # type: ignore
            char_model = await actual_session.get(Character, character_id)
            if not char_model or str(char_model.guild_id) != guild_id:
                logger.warning(f"CM.update_health: Character {character_id} not found in guild {guild_id}.")
                return None

            original_hp = float(char_model.current_hp)

            char_model.current_hp = float(char_model.current_hp) + amount

            # Ensure max_hp is float for comparison and storage
            char_model.max_hp = float(char_model.max_hp)
            if char_model.current_hp < 0:
                char_model.current_hp = 0.0
            if char_model.current_hp > char_model.max_hp:
                char_model.current_hp = char_model.max_hp

            actual_hp_change = char_model.current_hp - original_hp

            char_model.is_alive = char_model.current_hp > 0

            flag_modified(char_model, "current_hp")
            flag_modified(char_model, "is_alive")

            logger.info(f"Character {character_id} health updated by {amount}. Original: {original_hp}, New: {char_model.current_hp}, Max: {char_model.max_hp}. Applied in session.")

            # char_model is already part of the session and changes are tracked.
            # If manage_session is true, session.commit() will be called by async with.

            return UpdateHealthResult(
                applied_amount=amount,
                actual_hp_change=actual_hp_change,
                current_hp=char_model.current_hp,
                max_hp=char_model.max_hp,
                is_alive=char_model.is_alive,
                original_hp=original_hp
            )


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None:
            logger.error(f"CharacterManager: DB service not available for save_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        dirty_ids = self._dirty_characters.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_characters_ids.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            logger.debug(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id_str}.")
            return

        # Ensure db_service and its session_factory are available
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CharacterManager: DB service or session factory not available for save_state in guild {guild_id_str}.")
            return

        # Use GuildTransaction for saving state
        from bot.database.guild_transaction import GuildTransaction
        try:
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str) as session:
                if deleted_ids:
                    ids_to_delete_list = list(deleted_ids)
                    if ids_to_delete_list:
                        from sqlalchemy import delete as sqlalchemy_delete
                        stmt = sqlalchemy_delete(Character).where(
                            Character.id.in_(ids_to_delete_list)
                            # Guild ID check is implicitly handled by GuildTransaction's pre-commit checks
                            # if we were fetching and then deleting, or if Character model had a before_delete hook.
                            # For a bulk delete like this, ensuring the IDs actually BELONG to the guild
                            # before adding to deleted_ids is important.
                            # The GuildTransaction won't catch deleting an object from another guild if it's not loaded.
                            # However, mark_character_deleted operates on cache which is guild-segregated.
                        )
                        await session.execute(stmt)
                        logger.info(f"CharacterManager: Executed delete for {len(ids_to_delete_list)} characters in DB for guild {guild_id_str}: {ids_to_delete_list}")

                guild_cache = self._characters.get(guild_id_str, {})
                processed_dirty_ids_in_transaction = set()
                for char_id in dirty_ids:
                    if char_id in guild_cache:
                        char_obj = guild_cache[char_id]
                        # Ensure the character object's guild_id matches before merging.
                        # GuildTransaction pre-commit check will also verify this.
                        if hasattr(char_obj, 'guild_id') and str(getattr(char_obj, 'guild_id')) != guild_id_str:
                            logger.error(f"CRITICAL: Character {char_id} in guild {guild_id_str} cache has mismatched guild_id {getattr(char_obj, 'guild_id')}. Skipping save.")
                            continue
                        await session.merge(char_obj)
                        processed_dirty_ids_in_transaction.add(char_id)
                    else:
                        logger.warning(f"Character {char_id} marked dirty but not found in cache for guild {guild_id_str}.")

                logger.info(f"CharacterManager: Processed {len(processed_dirty_ids_in_transaction)} dirty characters for guild {guild_id_str} via merge.")
                # No explicit session.commit() needed due to GuildTransaction

            # Cleanup local dirty/deleted sets only after successful transaction
            if guild_id_str in self._deleted_characters_ids:
                    self._deleted_characters_ids[guild_id_str].clear()
            if guild_id_str in self._dirty_characters:
                self._dirty_characters[guild_id_str].difference_update(processed_dirty_ids_in_transaction)
                if not self._dirty_characters[guild_id_str]: del self._dirty_characters[guild_id_str]
            logger.info(f"CharacterManager: Successfully saved state for guild {guild_id_str}.")

        except ValueError as ve: # Catch GuildTransaction specific errors
            logger.error(f"CharacterManager: GuildTransaction integrity error during save_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: Error during save_state for guild {guild_id_str}: {e}", exc_info=True)


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        if self._db_service is None or not hasattr(self._db_service, 'get_session_factory'):
            logger.error(f"CharacterManager: DB service or session factory not available for load_state in guild {guild_id}.")
            return

        guild_id_str = str(guild_id)
        logger.info(f"CharacterManager: Loading state for guild {guild_id_str}.")

        self._characters[guild_id_str] = {}
        self._discord_to_player_map[guild_id_str] = {}
        self._entities_with_active_action.pop(guild_id_str, None)
        self._dirty_characters.pop(guild_id_str, None)
        self._deleted_characters_ids.pop(guild_id_str, None)

        from bot.database.crud_utils import get_entities
        from bot.database.guild_transaction import GuildTransaction # Recommended for consistency, though reads might use simpler session

        try:
            # Using GuildTransaction for consistency, though for pure reads, a simpler session might also work
            # if crud_utils are used which internally apply guild_id filtering.
            # GuildTransaction ensures session.info["current_guild_id"] is set, which crud_utils can use for verification.
            async with GuildTransaction(self._db_service.get_session_factory, guild_id_str, commit_on_exit=False) as session: # commit_on_exit=False for read-only
                all_players_in_guild = await get_entities(session, Player, guild_id=guild_id_str)
                for player_obj in all_players_in_guild:
                    if player_obj.discord_id:
                        try:
                            self._discord_to_player_map.setdefault(guild_id_str, {})[int(player_obj.discord_id)] = player_obj.id
                        except ValueError:
                            logger.warning(f"Could not parse discord_id '{player_obj.discord_id}' to int for player mapping for player {player_obj.id}.")
                logger.info(f"CharacterManager: Loaded {len(self._discord_to_player_map.get(guild_id_str, {}))} player ID mappings for guild {guild_id_str}.")

                all_characters_in_guild = await get_entities(session, Character, guild_id=guild_id_str)
                loaded_char_count = 0
                for char_obj in all_characters_in_guild:
                    self._characters.setdefault(guild_id_str, {})[char_obj.id] = char_obj
                    current_action_q_str = char_obj.action_queue_json or "[]"
                    current_action_q = []
                    try:
                        current_action_q = json.loads(current_action_q_str)
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt action_queue_json for char {char_obj.id}: {current_action_q_str}")

                    if char_obj.current_action_json or current_action_q: # Check if current_action_json is not None or empty
                        if isinstance(char_obj.current_action_json, str) and not char_obj.current_action_json.strip(): # handle empty string case for JSON
                             pass # treat empty string as no action
                        elif char_obj.current_action_json or current_action_q: # check again after potential empty string handling
                            self._entities_with_active_action.setdefault(guild_id_str, set()).add(char_obj.id)

                    loaded_char_count += 1
                logger.info(f"CharacterManager: Loaded {loaded_char_count} characters for guild {guild_id_str}.")

        except ValueError as ve: # Catch GuildTransaction specific errors if they arise
            logger.error(f"CharacterManager: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"CharacterManager: DB error during load_state for guild {guild_id_str}: {e}", exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"CharacterManager: Rebuilding runtime caches for guild {guild_id} (currently a pass-through).")
        pass

    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         if str(guild_id) in self._characters and character_id in self._characters[str(guild_id)]:
              self._dirty_characters.setdefault(str(guild_id), set()).add(character_id)
    async def save_state(self, guild_id: str, **kwargs: Any) -> None: pass # Assumes DB writes are transactional per method now
    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # Needs full DB load
        if self._db_service is None: logger.error(f"CM: DB service NA for load_state guild {guild_id}."); return
        # ... (full load logic as previously provided) ...
    async def get_character_details_context(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None # Placeholder

    # Other methods would need similar review for direct DB interaction with sessions or cache management
    def get_character_by_name(self, guild_id: str, name: str) -> Optional[Character]: return None
    def get_all_characters(self, guild_id: str) -> List[Character]: return []
    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List[Character]: return []
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]: return set()
    def is_busy(self, guild_id: str, character_id: str) -> bool: return False
    def mark_character_deleted(self, guild_id: str, character_id: str) -> None: pass
    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional[Character]: return None
    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool: return False
    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None: pass
    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None: pass
    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]: return None
    async def save_character(self, character: Character, guild_id: str) -> bool: return False
    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool: return False
    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool: return False
    async def gain_xp(self, guild_id: str, character_id: str, amount: int, session: Optional[AsyncSession] = None) -> Optional[Dict[str, Any]]: return None # Placeholder
    async def update_character_stats(self, guild_id: str, character_id: str, stats_update: Dict[str, Any], session: Optional[AsyncSession] = None, **kwargs: Any) -> bool: return False

    async def create_new_character(
        self,
        guild_id: str,
        user_id: int,  # Discord User ID
        character_name: str,
        language: str, # Effective language for character
        session: Optional[AsyncSession] = None # Optional session for transaction control
    ) -> Optional[Character]:
        """
        Creates a new character for a given player (user_id) in a guild.
        """
        if not self._db_service or not self._game_manager or not self._rule_engine or not self._location_manager:
            logger.error(f"CM.create_new_character: Required services (DB, GameManager, RuleEngine, LocationManager) not available for guild {guild_id}.")
            return None

        guild_id_str = str(guild_id)
        discord_id_str = str(user_id)
        
        manage_session = session is None
        active_db_session: AsyncSession 
        new_char_orm_instance: Optional[Character] = None 
        final_player_record_for_caching: Optional[Player] = None


        if manage_session:
            if not self._db_service:
                logger.error(f"CM.create_new_character (managed session): DBService not available.")
                return None

            transaction_successful = False
            player_record_in_scope: Optional[Player] = None # To hold player_record for this scope

            async with self._db_service.get_session() as active_db_session:
                async with active_db_session.begin():
                    try:
                        from bot.database.crud_utils import get_entity_by_attributes
                        player_record = await get_entity_by_attributes(active_db_session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)
                        player_record_in_scope = player_record

                        if not player_record:
                            logger.error(f"CM.create_new_character: Player record not found for Discord ID {discord_id_str} in guild {guild_id_str}. Character creation aborted.")
                            return None

                        if player_record.active_character_id:
                            existing_char_check = await active_db_session.get(Character, player_record.active_character_id)
                            if existing_char_check and str(existing_char_check.guild_id) == guild_id_str:
                                raise CharacterAlreadyExistsError(f"Player {player_record.id} (Discord: {discord_id_str}) already has an active character {player_record.active_character_id}.")
                            else:
                                logger.warning(f"CM.create_new_character: Player {player_record.id} had an invalid active_character_id {player_record.active_character_id}. Clearing.")
                                player_record.active_character_id = None
                                flag_modified(player_record, "active_character_id")

                        new_character_id = str(uuid.uuid4())
                        default_hp = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.hp", 100.0)
                        default_max_hp = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.max_hp", 100.0)
                        default_location_id = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.starting_location_id", "default_start_location")

                        starting_location_obj = await self._location_manager.get_location_by_static_id(guild_id_str, default_location_id, session=active_db_session)
                        if not starting_location_obj:
                            logger.error(f"CM.create_new_character: Default starting location '{default_location_id}' (static_id) not found for guild {guild_id_str}. Aborting creation.")
                            raise ValueError(f"Starting location '{default_location_id}' not found.")

                        character_data = {
                            "id": new_character_id, "player_id": player_record.id, "guild_id": guild_id_str,
                            "name_i18n": {language: character_name, "en": character_name},
                            "description_i18n": {"en": "A new adventurer.", language: "Новый искатель приключений."},
                            "current_hp": float(default_hp), "max_hp": float(default_max_hp), "mp": 0,
                            "level": 1, "xp": 0, "unspent_xp": 0,
                            "gold": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.gold", 10),
                            "stats_json": json.dumps(await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.base_stats", {"strength":10, "dexterity":10, "constitution":10, "intelligence":10, "wisdom":10, "charisma":10})),
                            "skills_data_json": "{}", "inventory_json": "[]", "equipment_slots_json": "{}",
                            "status_effects_json": "[]", "current_location_id": starting_location_obj.id,
                            "action_queue_json": "[]", "current_action_json": None, "is_alive": True,
                            "current_party_id": None, "effective_stats_json": "{}",
                            "abilities_data_json": "[]", "spells_data_json": "{}", "known_spells_json": "[]",
                            "race_key": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.race", "human"),
                            "character_class_i18n": { language: await self._game_manager.get_rule(guild_id_str, f"character_creation.defaults.char_class.{language}", "Adventurer"), "en": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.char_class.en", "Adventurer")},
                            "flags_json": json.dumps({"appearance": {"description": "An ordinary looking individual."}, "backstory": {"summary": "A mysterious past."}, "personality": {"traits": ["brave"]},}),
                            "active_quests_json": "[]", "state_variables_json": "{}"
                        }

                        char_orm_to_add = Character(**character_data)
                        await self._recalculate_and_store_effective_stats(guild_id_str, char_orm_to_add.id, char_orm_to_add, session_for_db=active_db_session)
                        active_db_session.add(char_orm_to_add)

                        player_record.active_character_id = char_orm_to_add.id
                        flag_modified(player_record, "active_character_id")
                        active_db_session.add(player_record)

                        new_char_orm_instance = char_orm_to_add
                        transaction_successful = True
                    
                    except CharacterAlreadyExistsError as caee_managed:
                        logger.info(f"CM.create_new_character (managed session): CharacterAlreadyExistsError for Discord ID {discord_id_str}. Transaction will roll back.")
                        raise caee_managed
                    except ValueError as ve_managed:
                         logger.error(f"CM.create_new_character (managed session): ValueError (likely starting location for {default_location_id}) for Discord ID {discord_id_str}: {ve_managed}. Transaction will roll back.")
                    except Exception as e_managed:
                        logger.error(f"CM.create_new_character (managed session): General Exception for Discord ID {discord_id_str}: {e_managed}. Transaction will roll back.", exc_info=True)

            final_player_record_for_caching = player_record_in_scope # Use the record from the transaction scope
            if transaction_successful and new_char_orm_instance:
                logger.info(f"CM.create_new_character (managed session): Transaction for Discord ID {discord_id_str} COMMITTED successfully. Character ID: {new_char_orm_instance.id}")
            elif not new_char_orm_instance :
                 logger.warning(f"CM.create_new_character (managed session): Transaction for Discord ID {discord_id_str} ROLLED BACK or character not created (new_char_orm_instance is None).")

        else: # manage_session is False, session was passed in
            active_db_session = session
            # player_record_external_session will be used here, and then assigned to final_player_record_for_caching
            player_record_external_session: Optional[Player] = None
            try:
                async with active_db_session.begin_nested():
                    from bot.database.crud_utils import get_entity_by_attributes
                    player_record_external_session = await get_entity_by_attributes(active_db_session, Player, {"discord_id": discord_id_str}, guild_id=guild_id_str)

                    if not player_record_external_session:
                        logger.error(f"CM.create_new_character (external session): Player record not found for Discord ID {discord_id_str} in guild {guild_id_str}.")
                        return None

                    if player_record_external_session.active_character_id:
                        existing_char_check = await active_db_session.get(Character, player_record_external_session.active_character_id)
                        if existing_char_check and str(existing_char_check.guild_id) == guild_id_str:
                            raise CharacterAlreadyExistsError(f"Player {player_record_external_session.id} (Discord: {discord_id_str}) already has an active character.")
                        else:
                            logger.warning(f"CM.create_new_character (external session): Player {player_record_external_session.id} had an invalid active_character_id {player_record_external_session.active_character_id}. Clearing.")
                            player_record_external_session.active_character_id = None
                            flag_modified(player_record_external_session, "active_character_id")
                    
                    new_character_id = str(uuid.uuid4())
                    default_hp = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.hp", 100.0)
                    default_max_hp = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.max_hp", 100.0)
                    default_location_id = await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.starting_location_id", "default_start_location")
                    starting_location_obj = await self._location_manager.get_location_by_static_id(guild_id_str, default_location_id, session=active_db_session)
                    if not starting_location_obj:
                        logger.error(f"CM.create_new_character (external session): Default starting location '{default_location_id}' (static_id) not found. Aborting creation in nested transaction.")
                        raise ValueError(f"Starting location '{default_location_id}' not found in external session.")

                    character_data = {
                        "id": new_character_id, "player_id": player_record_external_session.id, "guild_id": guild_id_str,
                        "name_i18n": {language: character_name, "en": character_name},
                        "description_i18n": {"en": "A new adventurer.", language: "Новый искатель приключений."},
                        "current_hp": float(default_hp), "max_hp": float(default_max_hp), "mp": 0,
                        "level": 1, "xp": 0, "unspent_xp": 0,
                        "gold": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.gold", 10),
                        "stats_json": json.dumps(await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.base_stats", {"strength":10, "dexterity":10, "constitution":10, "intelligence":10, "wisdom":10, "charisma":10})),
                        "skills_data_json": "{}", "inventory_json": "[]", "equipment_slots_json": "{}",
                        "status_effects_json": "[]", "current_location_id": starting_location_obj.id,
                        "action_queue_json": "[]", "current_action_json": None, "is_alive": True, "current_party_id": None,
                        "effective_stats_json": "{}", "abilities_data_json": "[]", "spells_data_json": "{}", "known_spells_json": "[]",
                        "race_key": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.race", "human"),
                        "character_class_i18n": { language: await self._game_manager.get_rule(guild_id_str, f"character_creation.defaults.char_class.{language}", "Adventurer"), "en": await self._game_manager.get_rule(guild_id_str, "character_creation.defaults.char_class.en", "Adventurer")},
                        "flags_json": json.dumps({"appearance": {"description": "An ordinary looking individual."}, "backstory": {"summary": "A mysterious past."}, "personality": {"traits": ["brave"]},}),
                        "active_quests_json": "[]", "state_variables_json": "{}"
                    }
                    char_orm_to_add = Character(**character_data)
                    await self._recalculate_and_store_effective_stats(guild_id_str, char_orm_to_add.id, char_orm_to_add, session_for_db=active_db_session)
                    active_db_session.add(char_orm_to_add)
                    
                    player_record_external_session.active_character_id = char_orm_to_add.id
                    flag_modified(player_record_external_session, "active_character_id")
                    active_db_session.add(player_record_external_session)
                    new_char_orm_instance = char_orm_to_add

                final_player_record_for_caching = player_record_external_session # Set it from this scope
            
            except CharacterAlreadyExistsError as caee_external:
                logger.info(f"CM.create_new_character (external session): CharacterAlreadyExistsError for Discord ID {discord_id_str}. Nested transaction will roll back.")
                raise caee_external
            except ValueError as ve_external:
                 logger.error(f"CM.create_new_character (external session): ValueError for Discord ID {discord_id_str}: {ve_external}. Nested transaction will roll back.")
                 return None
            except Exception as e_external:
                logger.error(f"CM.create_new_character (external session): General Exception for Discord ID {discord_id_str}: {e_external}. Nested transaction will roll back.", exc_info=True)
                return None

        # Cache update happens after successful operation.
        if (new_char_orm_instance is not None) and (final_player_record_for_caching is not None):
            self._characters.setdefault(guild_id_str, {})[new_char_orm_instance.id] = new_char_orm_instance
            self._discord_to_player_map.setdefault(guild_id_str, {})[user_id] = final_player_record_for_caching.id
            logger.info(f"CM.create_new_character: Successfully created and cached Character {new_char_orm_instance.id} for Player {final_player_record_for_caching.id} in guild {guild_id_str}. DB transaction outcome depends on session management context.")
        
        return new_char_orm_instance


