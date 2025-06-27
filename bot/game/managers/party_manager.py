# bot/game/managers/party_manager.py

from __future__ import annotations
import json
import uuid
import logging
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.database.models import Party, Character # SQLAlchemy Models
from bot.database.crud_utils import create_entity, get_entity_by_id, get_entities, update_entity, delete_entity
from bot.database.guild_transaction import GuildTransaction

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.game_manager import GameManager # For rule access

logger = logging.getLogger(__name__)

class PartyNotFoundError(Exception):
    pass

class CharacterNotInPartyError(Exception):
    pass

class CharacterAlreadyInPartyError(Exception):
    pass

class PartyFullError(Exception):
    pass

class NotPartyLeaderError(Exception):
    pass


class PartyManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _parties_cache: Dict[str, Dict[str, Party]] # GuildID -> PartyID -> SQLAlchemy Party model
    _dirty_parties: Dict[str, Set[str]] # GuildID -> Set of dirty PartyIDs
    _deleted_party_ids: Dict[str, Set[str]] # GuildID -> Set of PartyIDs to delete
    _member_to_party_map: Dict[str, Dict[str, str]] # GuildID -> CharacterID -> PartyID

    def __init__(self,
                 db_service: DBService, # Made non-optional as it's crucial
                 settings: Dict[str, Any], # Made non-optional
                 character_manager: CharacterManager, # Made non-optional
                 game_manager: GameManager # Made non-optional
                ):
        logger.info("Initializing PartyManager...")
        self._db_service = db_service
        self._settings = settings
        self._character_manager = character_manager
        self._game_manager = game_manager

        self._parties_cache = {}
        self._dirty_parties = {}
        self._deleted_party_ids = {}
        self._member_to_party_map = {}
        logger.info("PartyManager initialized.")

    def _get_session_factory(self):
        if not self._db_service or not hasattr(self._db_service, 'get_session_factory'):
            # This indicates a setup problem if DBService is correctly initialized.
            logger.critical("PartyManager: DBService not available or does not have get_session_factory.")
            raise RuntimeError("DBService or session factory not available in PartyManager.")
        return self._db_service.get_session_factory

    def _add_to_cache(self, guild_id: str, party: Party) -> None:
        """Adds or updates a party in the cache and updates member map."""
        if not isinstance(party, Party):
            logger.warning(f"PartyManager: Attempted to add non-Party object to cache for guild {guild_id}.")
            return

        self._parties_cache.setdefault(guild_id, {})[party.id] = party
        guild_member_map = self._member_to_party_map.setdefault(guild_id, {})

        # Clear old mappings for this party's members first
        # This is important if members list changed to avoid stale entries in _member_to_party_map
        # A more efficient way might be to track old members if player_ids_json was just updated
        ids_to_remove_from_map = [char_id for char_id, p_id in guild_member_map.items() if p_id == party.id]
        for char_id in ids_to_remove_from_map:
            del guild_member_map[char_id]

        if party.player_ids_json:
            player_ids_val = party.player_ids_json
            if not isinstance(player_ids_val, str): # Ensure it's a string before json.loads
                logger.error(f"PartyManager: player_ids_json for party {party.id} in guild {guild_id} is not a string: {type(player_ids_val)}. Attempting str conversion.")
                player_ids_val = str(player_ids_val)

            try:
                member_ids = json.loads(player_ids_val)
                if isinstance(member_ids, list): # Ensure it's a list after loading
                    for member_id in member_ids:
                        if member_id in guild_member_map and guild_member_map[member_id] != party.id:
                             logger.warning(f"PartyManager: Character {member_id} in guild {guild_id} was in party {guild_member_map[member_id]}, now being mapped to party {party.id}.")
                        guild_member_map[str(member_id)] = party.id
                else:
                    logger.error(f"PartyManager: Decoded player_ids_json for party {party.id} in guild {guild_id} is not a list: {type(member_ids)}")
            except json.JSONDecodeError:
                logger.error(f"PartyManager: Invalid JSON in player_ids_json for party {party.id} in guild {guild_id}: {player_ids_val}")


    def _remove_from_cache(self, guild_id: str, party_id: str) -> Optional[Party]:
        """Removes a party from the cache and updates member map."""
        party = self._parties_cache.get(guild_id, {}).pop(party_id, None)
        if party and party.player_ids_json:
            player_ids_val = party.player_ids_json
            if not isinstance(player_ids_val, str):
                logger.error(f"PartyManager: player_ids_json for party {party.id} (cache removal) in guild {guild_id} is not a string: {type(player_ids_val)}. Attempting str conversion.")
                player_ids_val = str(player_ids_val)
            try:
                member_ids = json.loads(player_ids_val)
                if isinstance(member_ids, list):
                    guild_member_map = self._member_to_party_map.get(guild_id, {})
                    for member_id in member_ids:
                        if guild_member_map.get(str(member_id)) == party.id:
                            del guild_member_map[str(member_id)]
                else:
                    logger.error(f"PartyManager: Decoded player_ids_json for party {party.id} (cache removal) in guild {guild_id} is not a list: {type(member_ids)}")
            except json.JSONDecodeError:
                logger.error(f"PartyManager: Invalid JSON in player_ids_json for party {party.id} during cache removal in guild {guild_id}.")
        return party

    def mark_party_dirty(self, guild_id: str, party_id: str) -> None:
        if guild_id in self._parties_cache and party_id in self._parties_cache[guild_id]:
            self._dirty_parties.setdefault(guild_id, set()).add(party_id)
        else:
            logger.warning(f"PartyManager: Attempted to mark non-cached party {party_id} in guild {guild_id} as dirty.")


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.info(f"PartyManager: Loading state for guild {guild_id}.")
        self._parties_cache[guild_id] = {}
        self._member_to_party_map[guild_id] = {}
        self._dirty_parties.pop(guild_id, None)
        self._deleted_party_ids.pop(guild_id, None)

        try:
            async with GuildTransaction(self._get_session_factory(), guild_id, commit_on_exit=False) as session:
                all_parties_in_guild = await get_entities(session, Party, guild_id=guild_id)
                for party in all_parties_in_guild:
                    self._add_to_cache(guild_id, party) # This also updates _member_to_party_map
                logger.info(f"PartyManager: Loaded {len(all_parties_in_guild)} parties for guild {guild_id}.")
        except Exception as e:
            logger.error(f"PartyManager: Error loading state for guild {guild_id}: {e}", exc_info=True)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.debug(f"PartyManager: Saving state for guild {guild_id}.")
        dirty_ids = list(self._dirty_parties.get(guild_id, set()))
        deleted_ids = list(self._deleted_party_ids.get(guild_id, set()))

        if not dirty_ids and not deleted_ids:
            logger.debug(f"PartyManager: No dirty or deleted parties to save for guild {guild_id}.")
            return

        processed_dirty_ids_in_transaction = set()
        processed_deleted_ids_in_transaction = set()

        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                for party_id_to_delete in deleted_ids:
                    party_to_delete = await get_entity_by_id(session, Party, party_id_to_delete, guild_id=guild_id) # Verify guild ownership before delete
                    if party_to_delete:
                        await delete_entity(session, party_to_delete, guild_id=guild_id)
                        logger.info(f"PartyManager: Deleted party {party_id_to_delete} from DB for guild {guild_id}.")
                        processed_deleted_ids_in_transaction.add(party_id_to_delete)
                    else:
                        logger.warning(f"PartyManager: Party {party_id_to_delete} marked for deletion not found in DB for guild {guild_id}.")
                        processed_deleted_ids_in_transaction.add(party_id_to_delete) # Remove from set even if not found

                for party_id_to_save in dirty_ids:
                    party_instance = self._parties_cache.get(guild_id, {}).get(party_id_to_save)
                    if party_instance:
                        if str(party_instance.guild_id) != guild_id: # Should be caught by GuildTransaction too
                            logger.error(f"CRITICAL: Party {party_instance.id} in guild {guild_id} cache has mismatched guild_id {party_instance.guild_id}. Skipping save.")
                            continue
                        await session.merge(party_instance)
                        logger.info(f"PartyManager: Merged party {party_instance.id} to DB for guild {guild_id}.")
                        processed_dirty_ids_in_transaction.add(party_id_to_save)
                    else:
                        logger.warning(f"PartyManager: Party {party_id_to_save} marked dirty but not found in cache for guild {guild_id}. Skipping save.")

            # Cleanup sets after successful transaction
            if guild_id in self._dirty_parties:
                self._dirty_parties[guild_id].difference_update(processed_dirty_ids_in_transaction)
                if not self._dirty_parties[guild_id]: del self._dirty_parties[guild_id]

            if guild_id in self._deleted_party_ids:
                self._deleted_party_ids[guild_id].difference_update(processed_deleted_ids_in_transaction)
                if not self._deleted_party_ids[guild_id]: del self._deleted_party_ids[guild_id]

            logger.info(f"PartyManager: Successfully saved state for guild {guild_id}.")
        except ValueError as ve: # Catch GuildTransaction specific errors
            logger.error(f"PartyManager: GuildTransaction integrity error during save_state for guild {guild_id}: {ve}", exc_info=True)
        except Exception as e:
            logger.error(f"PartyManager: Error during save_state for guild {guild_id}: {e}", exc_info=True)


    async def create_party(self, guild_id: str, leader_character_id: str, party_name_i18n: Dict[str, str]) -> Optional[Party]:
        logger.info(f"PartyManager: Attempting to create party in guild {guild_id} by leader {leader_character_id}.")

        leader_char_pydantic = await self._character_manager.get_character(guild_id, leader_character_id)
        if not leader_char_pydantic:
            logger.warning(f"PartyManager: Leader character Pydantic model {leader_character_id} not found in guild {guild_id}.")
            return None

        leader_char_name_i18n = getattr(leader_char_pydantic, 'name_i18n', {"en": "Unknown"})
        leader_char_current_party_id = getattr(leader_char_pydantic, 'current_party_id', None)
        leader_char_current_location_id = getattr(leader_char_pydantic, 'current_location_id', None)


        if leader_char_current_party_id:
            logger.warning(f"PartyManager: Leader character {leader_character_id} is already in party {leader_char_current_party_id}.")
            # Ensure leader_char_name_i18n is a dict before .get()
            char_name_for_error = leader_char_name_i18n.get('en', 'Unknown') if isinstance(leader_char_name_i18n, dict) else "Unknown"
            raise CharacterAlreadyInPartyError(f"Character {leader_character_id} (name: {char_name_for_error}) is already in a party.")

        party_id = str(uuid.uuid4())
        party_data = {
            "id": party_id,
            "guild_id": guild_id,
            "name_i18n": party_name_i18n,
            "leader_id": leader_character_id,
            "player_ids_json": json.dumps([leader_character_id]), # Ensure this is a JSON string
            "current_location_id": leader_char_current_location_id,
            "turn_status": "active", # Default or fetch from rules
            "state_variables": {} # Default or fetch from rules
        }

        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                created_party = await create_entity(session, Party, party_data, guild_id=guild_id)
                if not created_party: # Should not happen if create_entity raises on failure
                    raise Exception("Party creation returned None from create_entity.")

                update_success = False
                if hasattr(self._character_manager, 'save_character_field') and callable(self._character_manager.save_character_field):
                    update_success = await self._character_manager.save_character_field(
                        guild_id, leader_character_id, "current_party_id", created_party.id, session=session
                    )

                if not update_success:
                    logger.error(f"PartyManager: Failed to set current_party_id for leader {leader_character_id} after party creation.")
                    # Consider rollback or specific error handling if this fails within transaction
                    raise Exception(f"Failed to update leader's party ID for party {created_party.id}")

                self._add_to_cache(guild_id, created_party)
                logger.info(f"PartyManager: Party '{created_party.id}' created successfully for leader {leader_character_id} in guild {guild_id}.")
                return created_party
        except CharacterAlreadyInPartyError: # Re-raise if it came from CharacterManager during set_party_id, though unlikely for leader
            raise
        except Exception as e:
            logger.error(f"PartyManager: Error creating party for leader {leader_character_id} in guild {guild_id}: {e}", exc_info=True)
            return None

    async def get_party(self, guild_id: str, party_id: str) -> Optional[Party]:
        party = self._parties_cache.get(guild_id, {}).get(party_id)
        if party:
            return party

        logger.debug(f"PartyManager: Party {party_id} not in cache for guild {guild_id}. Fetching from DB.")
        try:
            async with GuildTransaction(self._get_session_factory(), guild_id, commit_on_exit=False) as session:
                party_db = await get_entity_by_id(session, Party, party_id, guild_id=guild_id)
                if party_db:
                    self._add_to_cache(guild_id, party_db) # Add to cache after fetching
                    return party_db
                # logger.info(f"PartyManager: Party {party_id} not found in DB for guild {guild_id}.") # INFO is too verbose for not found
                return None
        except Exception as e:
            logger.error(f"PartyManager: Error fetching party {party_id} for guild {guild_id} from DB: {e}", exc_info=True)
            return None

    def get_party_by_member_character_id(self, guild_id: str, character_id: str) -> Optional[Party]:
        """Gets the party a specific character is in from cache."""
        party_id = self._member_to_party_map.get(guild_id, {}).get(character_id)
        if party_id:
            return self._parties_cache.get(guild_id, {}).get(party_id)
        return None

    async def get_party_members(self, guild_id: str, party_id: str) -> List[Character]:
        """ Returns a list of Character model instances for the members of the party. """
        party = await self.get_party(guild_id, party_id) # Ensures party is fetched if not in cache
        members: List[Character] = []
        if party and party.player_ids_json:
            try:
                member_ids = json.loads(party.player_ids_json)
                for char_id in member_ids:
                    char = await self._character_manager.get_character(guild_id, char_id) # Fetches from CharacterManager cache or DB
                    if char:
                        members.append(char)
                    else:
                        logger.warning(f"PartyManager: Character {char_id} listed in party {party_id} not found via CharacterManager.")
            except json.JSONDecodeError:
                 logger.error(f"PartyManager: Invalid JSON in player_ids_json for party {party.id} in get_party_members.")
        return members

    async def update_party_location(self, guild_id: str, party_id: str, new_location_id: Optional[str]) -> bool:
        """Updates the party's current location. Typically called by other services like LocationManager during entity moves."""
        # This method assumes the party object might not be in cache or needs to be updated transactionally.
        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                party = await get_entity_by_id(session, Party, party_id, guild_id=guild_id)
                if not party:
                    logger.warning(f"PartyManager: Party {party_id} not found in guild {guild_id} for location update.")
                    return False

                party.current_location_id = new_location_id
                # session.add(party) # GuildTransaction and crud_utils.update_entity would handle this if we used update_entity
                # For direct attribute change on a fetched entity, it's part of the session's UOW.

                # Update cache after successful transaction (or rely on save_state to refresh if this was a direct DB op)
                # For now, update cache directly and mark dirty.
                self._add_to_cache(guild_id, party) # Update cache with modified object
                self.mark_party_dirty(guild_id, party.id)
                logger.info(f"PartyManager: Updated location for party {party_id} to {new_location_id} in guild {guild_id}.")
                return True
        except Exception as e:
            logger.error(f"PartyManager: Error updating party location for {party_id} in guild {guild_id}: {e}", exc_info=True)
            return False

    # --- Implementations for join_party, leave_party, disband_party ---

    async def join_party(self, guild_id: str, character_id: str, party_id: str) -> bool:
        logger.info(f"PartyManager: Character {character_id} attempting to join party {party_id} in guild {guild_id}.")
        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                character_to_join = await self._character_manager.get_character_for_update(session, guild_id, character_id) # Needs a method that gets char for update
                party_to_join = await get_entity_by_id(session, Party, party_id, guild_id=guild_id)

                character_to_join_pydantic = await self._character_manager.get_character(guild_id, character_id) # Changed to get_character
                if not character_to_join_pydantic: # Check Pydantic model
                    raise ValueError(f"Character Pydantic model {character_id} not found.")

                party_to_join = await get_entity_by_id(session, Party, party_id, guild_id=guild_id)
                if not party_to_join:
                    raise PartyNotFoundError(f"Party {party_id} not found.")

                char_current_party_id = getattr(character_to_join_pydantic, 'current_party_id', None)
                if char_current_party_id:
                    raise CharacterAlreadyInPartyError(f"Character {character_id} is already in party {char_current_party_id}.")

                max_size = await self._game_manager.get_rule(guild_id, "max_party_size", default=4)

                player_ids_json_str = party_to_join.player_ids_json
                if not isinstance(player_ids_json_str, str): player_ids_json_str = "[]"
                member_ids = json.loads(player_ids_json_str)

                if not isinstance(member_ids, list): # Ensure it's a list
                    logger.error(f"PartyManager: Decoded player_ids_json for party {party_id} is not a list: {type(member_ids)}. Defaulting to empty list.")
                    member_ids = []


                if len(member_ids) >= int(max_size): # Ensure max_size is int for comparison
                    raise PartyFullError(f"Party {party_id} is full (max size: {max_size}).")

                member_ids.append(character_id)
                party_to_join.player_ids_json = json.dumps(member_ids) # Save back as JSON string

                if hasattr(self._character_manager, 'save_character_field') and callable(self._character_manager.save_character_field):
                    await self._character_manager.save_character_field(guild_id, character_id, "current_party_id", party_id, session=session)
                else:
                    # Fallback or error if method not found
                    logger.error(f"PartyManager: save_character_field not found on CharacterManager. Cannot update character's party ID for {character_id}.")
                    raise Exception("CharacterManager is missing save_character_field method.")


                self._add_to_cache(guild_id, party_to_join)
                self.mark_party_dirty(guild_id, party_to_join.id)

                logger.info(f"PartyManager: Character {character_id} successfully joined party {party_id} in guild {guild_id}.")
                return True
        except (PartyNotFoundError, CharacterAlreadyInPartyError, PartyFullError, ValueError) as e:
            logger.warning(f"PartyManager: Failed to join party - {e}")
            raise # Re-raise specific errors for command handler to catch
        except Exception as e:
            logger.error(f"PartyManager: Unexpected error in join_party for char {character_id}, party {party_id}: {e}", exc_info=True)
            return False # Or raise a generic error

    async def leave_party(self, guild_id: str, character_id: str) -> bool:
        logger.info(f"PartyManager: Character {character_id} attempting to leave party in guild {guild_id}.")
        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                # Get Pydantic model first to check current_party_id from cache/consistent source
                character_leaving_pydantic = await self._character_manager.get_character(guild_id, character_id)
                if not character_leaving_pydantic:
                    raise ValueError(f"Character Pydantic model {character_id} not found.")

                party_id_to_leave = getattr(character_leaving_pydantic, 'current_party_id', None)
                if not party_id_to_leave:
                    raise CharacterNotInPartyError(f"Character {character_id} is not in a party.")

                party = await get_entity_by_id(session, Party, party_id_to_leave, guild_id=guild_id)
                if not party:
                    logger.error(f"PartyManager: Character {character_id} in party {party_id_to_leave}, but party not found in DB. Clearing char's party_id.")
                    if hasattr(self._character_manager, 'save_character_field') and callable(self._character_manager.save_character_field):
                        await self._character_manager.save_character_field(guild_id, character_id, "current_party_id", None, session=session)
                    self._member_to_party_map.get(guild_id, {}).pop(character_id, None)
                    return True

                player_ids_json_str = party.player_ids_json
                if not isinstance(player_ids_json_str, str): player_ids_json_str = "[]"
                member_ids = json.loads(player_ids_json_str)
                if not isinstance(member_ids, list): member_ids = []


                if character_id in member_ids:
                    member_ids.remove(character_id)
                    party.player_ids_json = json.dumps(member_ids) # Save back as JSON

                if hasattr(self._character_manager, 'save_character_field') and callable(self._character_manager.save_character_field):
                    await self._character_manager.save_character_field(guild_id, character_id, "current_party_id", None, session=session)
                else:
                    logger.error(f"PartyManager: save_character_field not found on CharacterManager. Cannot clear character's party ID for {character_id}.")
                    # Continue with party logic, but character might remain inconsistent if this fails.

                if not member_ids:
                    logger.info(f"PartyManager: Party {party.id} is now empty after {character_id} left. Disbanding.")
                    await delete_entity(session, party, guild_id=guild_id)
                    self._remove_from_cache(guild_id, party.id)
                elif party.leader_id == character_id:
                    party.leader_id = member_ids[0]
                    logger.info(f"PartyManager: Leader {character_id} left party {party.id}. New leader is {party.leader_id}.")
                    self._add_to_cache(guild_id, party)
                    self.mark_party_dirty(guild_id, party.id)
                else:
                    self._add_to_cache(guild_id, party)
                    self.mark_party_dirty(guild_id, party.id)

                self._member_to_party_map.get(guild_id, {}).pop(character_id, None)
                logger.info(f"PartyManager: Character {character_id} successfully left party {party_id_to_leave} in guild {guild_id}.")
                return True
        except (CharacterNotInPartyError, ValueError) as e:
            logger.warning(f"PartyManager: Failed to leave party - {e}")
            raise
        except Exception as e:
            logger.error(f"PartyManager: Unexpected error in leave_party for char {character_id}: {e}", exc_info=True)
            return False

    async def disband_party(self, guild_id: str, party_id: str, disbanding_character_id: str) -> bool:
        logger.info(f"PartyManager: Character {disbanding_character_id} attempting to disband party {party_id} in guild {guild_id}.")
        try:
            async with GuildTransaction(self._get_session_factory(), guild_id) as session:
                party_to_disband = await get_entity_by_id(session, Party, party_id, guild_id=guild_id)
                if not party_to_disband:
                    raise PartyNotFoundError(f"Party {party_id} not found to disband.")

                if party_to_disband.leader_id != disbanding_character_id:
                    # Add GM override check here in future if GMs can disband any party
                    raise NotPartyLeaderError(f"Character {disbanding_character_id} is not the leader of party {party_id}.")

                member_ids = json.loads(party_to_disband.player_ids_json or "[]")
                for member_id in member_ids:
                    await self._character_manager.save_character_field(guild_id, member_id, "current_party_id", None, session=session)
                    self._member_to_party_map.get(guild_id, {}).pop(member_id, None) # Update member map

                await delete_entity(session, party_to_disband, guild_id=guild_id)
                self._remove_from_cache(guild_id, party_id) # Remove from cache
                # If save_state handles deletions based on _deleted_party_ids, mark it here instead of direct delete_entity
                # self._deleted_party_ids.setdefault(guild_id, set()).add(party_id)

                logger.info(f"PartyManager: Party {party_id} successfully disbanded by leader {disbanding_character_id}.")
                return True
        except (PartyNotFoundError, NotPartyLeaderError) as e:
            logger.warning(f"PartyManager: Failed to disband party - {e}")
            raise
        except Exception as e:
            logger.error(f"PartyManager: Unexpected error in disband_party for party {party_id}: {e}", exc_info=True)
            return False

# logger.debug("PartyManager class defined.")
