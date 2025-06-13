from __future__ import annotations
import uuid
import json
import traceback # Will be removed
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.game.models.faction import Faction

if TYPE_CHECKING:
    from bot.services.db_service import DBService

logger = logging.getLogger(__name__) # Added

class FactionManager:
    """
    Manages factions within a guild.
    """
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]

    def __init__(self,
                 db_service: Optional[DBService] = None,
                 settings: Optional[Dict[str, Any]] = None):
        self._db_service: Optional[DBService] = db_service
        self._settings: Optional[Dict[str, Any]] = settings
        self._factions: Dict[str, Dict[str, Faction]] = {}
        self._dirty_factions: Dict[str, Set[str]] = {}
        self._deleted_faction_ids: Dict[str, Set[str]] = {}
        logger.info("FactionManager initialized.") # Added

    def _ensure_guild_cache_exists(self, guild_id: str):
        """Ensures the cache structure for a given guild_id exists."""
        guild_id_str = str(guild_id)
        if guild_id_str not in self._factions:
            self._factions[guild_id_str] = {}
        if guild_id_str not in self._dirty_factions:
            self._dirty_factions[guild_id_str] = set()
        if guild_id_str not in self._deleted_faction_ids:
            self._deleted_faction_ids[guild_id_str] = set()

    def mark_faction_dirty(self, guild_id: str, faction_id: str) -> None:
        """Marks a faction as dirty for saving."""
        guild_id_str, faction_id_str = str(guild_id), str(faction_id)
        self._ensure_guild_cache_exists(guild_id_str)
        self._dirty_factions[guild_id_str].add(faction_id_str)
        self._deleted_faction_ids[guild_id_str].discard(faction_id_str) # Ensure it's not also marked for deletion

    def mark_faction_for_deletion(self, guild_id: str, faction_id: str) -> None:
        """Marks a faction for deletion from the database and cache."""
        guild_id_str, faction_id_str = str(guild_id), str(faction_id)
        self._ensure_guild_cache_exists(guild_id_str)
        self._deleted_faction_ids[guild_id_str].add(faction_id_str)
        self._dirty_factions[guild_id_str].discard(faction_id_str)
        if faction_id_str in self._factions.get(guild_id_str, {}):
            del self._factions[guild_id_str][faction_id_str]
            logger.info("FactionManager: Faction %s removed from active cache for guild %s and marked for DB deletion.", faction_id_str, guild_id_str) # Added
        else:
            logger.debug("FactionManager: Faction %s marked for deletion in guild %s, but was not in active cache.", faction_id_str, guild_id_str) # Added


    async def create_faction(self, guild_id: str, name_i18n: Dict[str, str],
                             description_i18n: Dict[str, str], leader_id: Optional[str] = None,
                             alignment: Optional[str] = None, member_ids: Optional[List[str]] = None,
                             state_variables: Optional[Dict[str, Any]] = None) -> Optional[Faction]:
        guild_id_str = str(guild_id)
        self._ensure_guild_cache_exists(guild_id_str)
        try:
            faction = Faction(
                guild_id=guild_id_str, name_i18n=name_i18n, description_i18n=description_i18n,
                leader_id=leader_id, alignment=alignment,
                member_ids=member_ids if member_ids is not None else [],
                state_variables=state_variables if state_variables is not None else {}
            )
            self._factions[guild_id_str][faction.id] = faction
            self.mark_faction_dirty(guild_id_str, faction.id)
            logger.info("FactionManager: Created faction %s (%s) in guild %s.", faction.id, name_i18n.get('en', 'N/A'), guild_id_str) # Added
            return faction
        except ValueError as e: # Assuming Faction model might raise ValueError for invalid data
            logger.error("FactionManager: Error creating faction in guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            return None
        except Exception as e: # Catch any other unexpected errors
            logger.error("FactionManager: Unexpected error creating faction in guild %s: %s", guild_id_str, e, exc_info=True) # Added
            return None


    def get_faction(self, guild_id: str, faction_id: str) -> Optional[Faction]:
        guild_id_str, faction_id_str = str(guild_id), str(faction_id)
        return self._factions.get(guild_id_str, {}).get(faction_id_str)

    def get_factions_for_guild(self, guild_id: str) -> List[Faction]:
        guild_id_str = str(guild_id)
        return list(self._factions.get(guild_id_str, {}).values())

    async def delete_faction(self, guild_id: str, faction_id: str) -> bool:
        """Marks a faction for deletion."""
        guild_id_str, faction_id_str = str(guild_id), str(faction_id)
        if self.get_faction(guild_id_str, faction_id_str):
            self.mark_faction_for_deletion(guild_id_str, faction_id_str)
            logger.info("FactionManager: Marked faction %s for deletion in guild %s.", faction_id_str, guild_id_str) # Added
            return True
        logger.warning("FactionManager: Attempted to delete non-existent faction %s in guild %s.", faction_id_str, guild_id_str) # Added
        return False

    async def add_member_to_faction(self, guild_id: str, faction_id: str, member_id: str) -> bool:
        faction = self.get_faction(guild_id, faction_id)
        member_id_str = str(member_id)
        if faction:
            if member_id_str not in faction.member_ids:
                faction.member_ids.append(member_id_str)
                self.mark_faction_dirty(guild_id, faction_id)
                logger.info("FactionManager: Added member %s to faction %s in guild %s.", member_id_str, faction_id, guild_id) # Added
                return True
            logger.debug("FactionManager: Member %s already in faction %s in guild %s.", member_id_str, faction_id, guild_id) # Added
        else:
            logger.warning("FactionManager: Faction %s not found in guild %s to add member %s.", faction_id, guild_id, member_id_str) # Added
        return False

    async def remove_member_from_faction(self, guild_id: str, faction_id: str, member_id: str) -> bool:
        faction = self.get_faction(guild_id, faction_id)
        member_id_str = str(member_id)
        if faction and member_id_str in faction.member_ids:
            faction.member_ids.remove(member_id_str)
            logger.info("FactionManager: Removed member %s from faction %s in guild %s.", member_id_str, faction_id, guild_id) # Added
            if faction.leader_id == member_id_str:
                faction.leader_id = None
                logger.info("FactionManager: Leader %s removed from faction %s in guild %s; leader set to None.", member_id_str, faction_id, guild_id) # Added
            self.mark_faction_dirty(guild_id, faction_id)
            return True
        elif faction:
            logger.debug("FactionManager: Member %s not found in faction %s (guild %s) for removal.", member_id_str, faction_id, guild_id) # Added
        else:
            logger.warning("FactionManager: Faction %s not found in guild %s to remove member %s.", faction_id, guild_id, member_id_str) # Added
        return False

    async def update_faction_details(self, guild_id: str, faction_id: str,
                                     name_i18n: Optional[Dict[str, str]] = None,
                                     description_i18n: Optional[Dict[str, str]] = None,
                                     leader_id: Optional[str] = None,
                                     alignment: Optional[str] = None,
                                     state_variables: Optional[Dict[str, Any]] = None) -> Optional[Faction]:
        faction = self.get_faction(guild_id, faction_id)
        if not faction:
            logger.warning("FactionManager: Faction %s not found in guild %s for update.", faction_id, guild_id) # Added
            return None

        updated = False
        updated_fields_log = []
        if name_i18n is not None: faction.name_i18n = name_i18n; updated = True; updated_fields_log.append("name_i18n")
        if description_i18n is not None: faction.description_i18n = description_i18n; updated = True; updated_fields_log.append("description_i18n")

        args_passed = locals()
        if 'leader_id' in args_passed: faction.leader_id = leader_id; updated = True; updated_fields_log.append(f"leader_id to {leader_id}")
        if 'alignment' in args_passed: faction.alignment = alignment; updated = True; updated_fields_log.append(f"alignment to {alignment}") # Changed to check if passed
        if state_variables is not None: faction.state_variables = state_variables; updated = True; updated_fields_log.append("state_variables")

        if updated:
            self.mark_faction_dirty(guild_id, faction_id)
            logger.info("FactionManager: Updated faction %s in guild %s. Changes: %s", faction_id, guild_id, ", ".join(updated_fields_log)) # Added
        else:
            logger.debug("FactionManager: No details updated for faction %s in guild %s.", faction_id, guild_id) # Added
        return faction

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("FactionManager: Loading state for guild %s.", guild_id_str) # Added
        if not self._db_service or not self._db_service.adapter:
            logger.error("FactionManager: DB service or adapter missing for guild %s. Cannot load factions.", guild_id_str) # Changed
            return

        self._ensure_guild_cache_exists(guild_id_str)
        self._factions[guild_id_str].clear()
        self._dirty_factions[guild_id_str].clear()
        self._deleted_faction_ids[guild_id_str].clear()

        query = "SELECT id, guild_id, name_i18n, description_i18n, leader_id, alignment, member_ids, state_variables FROM factions WHERE guild_id = $1"
        try:
            rows = await self._db_service.adapter.fetchall(query, (guild_id_str,))
        except Exception as e:
            logger.error("FactionManager: DB error fetching factions for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            return

        for row in rows:
            try:
                data = dict(row)
                for field_name in ["name_i18n", "description_i18n", "member_ids", "state_variables"]:
                    if data[field_name] is not None and isinstance(data[field_name], str):
                        try: data[field_name] = json.loads(data[field_name])
                        except json.JSONDecodeError:
                            logger.warning("FactionManager: Failed to decode JSON for field '%s' in faction %s, guild %s. Data: %s", field_name, data.get('id'), guild_id_str, data[field_name]) # Added
                            if field_name in ["name_i18n", "description_i18n", "state_variables"]: data[field_name] = {}
                            elif field_name == "member_ids": data[field_name] = []
                    elif data[field_name] is None:
                        if field_name in ["name_i18n", "description_i18n", "state_variables"]: data[field_name] = {}
                        elif field_name == "member_ids": data[field_name] = []
                faction = Faction.from_dict(data)
                self._factions[guild_id_str][faction.id] = faction
            except Exception as e:
                logger.error("FactionManager: Error loading faction %s for guild %s: %s", data.get('id', 'N/A'), guild_id_str, e, exc_info=True) # Changed
        logger.info("FactionManager: Loaded %s factions for guild %s.", len(self._factions[guild_id_str]), guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if not self._db_service or not self._db_service.adapter:
            logger.error("FactionManager: DB service or adapter missing for guild %s. Cannot save factions.", guild_id_str) # Changed
            return

        self._ensure_guild_cache_exists(guild_id_str) # Ensure sets exist even if empty
        logger.debug("FactionManager: Saving state for guild %s.", guild_id_str) # Added

        ids_to_delete = list(self._deleted_faction_ids.get(guild_id_str, set()))
        if ids_to_delete:
            placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete))])
            delete_sql = f"DELETE FROM factions WHERE guild_id = $1 AND id IN ({placeholders})"
            try:
                await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                logger.info("FactionManager: Deleted %s factions for guild %s.", len(ids_to_delete), guild_id_str) # Added
                self._deleted_faction_ids[guild_id_str].clear()
            except Exception as e:
                logger.error("FactionManager: DB error deleting factions for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

        dirty_faction_ids = list(self._dirty_factions.get(guild_id_str, set()))
        if not dirty_faction_ids:
            # logger.debug("FactionManager: No dirty factions to save for guild %s.", guild_id_str) # Too noisy
            return

        factions_to_save_data = []
        successfully_prepared_ids = set()
        for faction_id in dirty_faction_ids:
            faction = self.get_faction(guild_id_str, faction_id)
            if faction:
                try:
                    factions_to_save_data.append((
                        faction.id, faction.guild_id, json.dumps(faction.name_i18n),
                        json.dumps(faction.description_i18n), faction.leader_id, faction.alignment,
                        json.dumps(faction.member_ids), json.dumps(faction.state_variables)
                    ))
                    successfully_prepared_ids.add(faction_id)
                except Exception as e:
                    logger.error("FactionManager: Error preparing faction %s for save in guild %s: %s", faction_id, guild_id_str, e, exc_info=True) # Changed
        if not factions_to_save_data:
            return

        upsert_sql = """
            INSERT INTO factions (id, guild_id, name_i18n, description_i18n, leader_id,
                                  alignment, member_ids, state_variables)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                guild_id = EXCLUDED.guild_id, name_i18n = EXCLUDED.name_i18n,
                description_i18n = EXCLUDED.description_i18n, leader_id = EXCLUDED.leader_id,
                alignment = EXCLUDED.alignment, member_ids = EXCLUDED.member_ids,
                state_variables = EXCLUDED.state_variables
        """
        try:
            await self._db_service.adapter.execute_many(upsert_sql, factions_to_save_data)
            logger.info("FactionManager: Saved %s factions for guild %s.", len(factions_to_save_data), guild_id_str) # Added
            if guild_id_str in self._dirty_factions:
                 self._dirty_factions[guild_id_str].difference_update(successfully_prepared_ids)
                 if not self._dirty_factions[guild_id_str]: del self._dirty_factions[guild_id_str]
        except Exception as e:
            logger.error("FactionManager: DB error saving factions for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
        # logger.debug("FactionManager: Save state complete for guild %s.", guild_id_str) # Too noisy for info
