from __future__ import annotations
import uuid
import json
import traceback
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.game.models.faction import Faction

if TYPE_CHECKING:
    from bot.services.db_service import DBService

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

        # Runtime cache for factions, indexed by guild_id, then faction_id
        self._factions: Dict[str, Dict[str, Faction]] = {}
        # To track changes for persistence
        self._dirty_factions: Dict[str, Set[str]] = {}
        self._deleted_faction_ids: Dict[str, Set[str]] = {}

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
        self._deleted_faction_ids[guild_id_str].discard(faction_id_str)

    def mark_faction_for_deletion(self, guild_id: str, faction_id: str) -> None:
        """Marks a faction for deletion from the database and cache."""
        guild_id_str, faction_id_str = str(guild_id), str(faction_id)
        self._ensure_guild_cache_exists(guild_id_str)
        self._deleted_faction_ids[guild_id_str].add(faction_id_str)
        self._dirty_factions[guild_id_str].discard(faction_id_str)
        if faction_id_str in self._factions.get(guild_id_str, {}):
            del self._factions[guild_id_str][faction_id_str]

    async def create_faction(self, guild_id: str, name_i18n: Dict[str, str],
                             description_i18n: Dict[str, str], leader_id: Optional[str] = None,
                             alignment: Optional[str] = None, member_ids: Optional[List[str]] = None,
                             state_variables: Optional[Dict[str, Any]] = None) -> Optional[Faction]:
        guild_id_str = str(guild_id)
        self._ensure_guild_cache_exists(guild_id_str)
        try:
            faction = Faction(
                guild_id=guild_id_str,
                name_i18n=name_i18n,
                description_i18n=description_i18n,
                leader_id=leader_id,
                alignment=alignment,
                member_ids=member_ids if member_ids is not None else [],
                state_variables=state_variables if state_variables is not None else {}
            )
            self._factions[guild_id_str][faction.id] = faction
            self.mark_faction_dirty(guild_id_str, faction.id)
            return faction
        except ValueError as e:
            print(f"FactionManager: Error creating faction: {e}")
            traceback.print_exc()
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
            return True
        return False

    async def add_member_to_faction(self, guild_id: str, faction_id: str, member_id: str) -> bool:
        faction = self.get_faction(guild_id, faction_id)
        member_id_str = str(member_id)
        if faction:
            if member_id_str not in faction.member_ids:
                faction.member_ids.append(member_id_str)
                self.mark_faction_dirty(guild_id, faction_id)
                return True
        return False

    async def remove_member_from_faction(self, guild_id: str, faction_id: str, member_id: str) -> bool:
        faction = self.get_faction(guild_id, faction_id)
        member_id_str = str(member_id)
        if faction and member_id_str in faction.member_ids:
            faction.member_ids.remove(member_id_str)
            # If the removed member was the leader, set leader_id to None or handle promotion logic
            if faction.leader_id == member_id_str:
                faction.leader_id = None # Simplest approach
            self.mark_faction_dirty(guild_id, faction_id)
            return True
        return False

    async def update_faction_details(self, guild_id: str, faction_id: str,
                                     name_i18n: Optional[Dict[str, str]] = None,
                                     description_i18n: Optional[Dict[str, str]] = None,
                                     leader_id: Optional[str] = None, # Use a special value like "__CLEAR__" to set to None
                                     alignment: Optional[str] = None,
                                     state_variables: Optional[Dict[str, Any]] = None) -> Optional[Faction]:
        faction = self.get_faction(guild_id, faction_id)
        if not faction:
            return None

        updated = False
        if name_i18n is not None:
            faction.name_i18n = name_i18n
            updated = True
        if description_i18n is not None:
            faction.description_i18n = description_i18n
            updated = True

        # To allow explicitly setting leader_id to None, one might pass a unique sentinel.
        # For this implementation, if leader_id is provided (even if None), it's updated.
        # This means to clear leader_id, pass leader_id=None.
        # If a parameter is not provided, it means no change to that field.
        args_passed = locals() # Gets current scope's local variables, including parameters
        if 'leader_id' in args_passed: # Check if leader_id was actually passed
             faction.leader_id = leader_id # leader_id can be None to clear it
             updated = True
        if alignment is not None: # Alignment can also be set to None explicitly by passing alignment=None
            faction.alignment = alignment
            updated = True
        if state_variables is not None: # To update, not overwrite, or clear specific keys
            # This will overwrite existing state_variables.
            # For partial updates: faction.state_variables.update(state_variables)
            faction.state_variables = state_variables
            updated = True

        if updated:
            self.mark_faction_dirty(guild_id, faction_id)
        return faction

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if not self._db_service or not self._db_service.adapter:
            print(f"FactionManager: DB service or adapter missing for {guild_id_str}. Cannot load factions.")
            return

        self._ensure_guild_cache_exists(guild_id_str)
        self._factions[guild_id_str].clear()
        self._dirty_factions[guild_id_str].clear()
        self._deleted_faction_ids[guild_id_str].clear()

        query = """
            SELECT id, guild_id, name_i18n, description_i18n, leader_id,
                   alignment, member_ids, state_variables
            FROM factions WHERE guild_id = $1
        """
        try:
            rows = await self._db_service.adapter.fetchall(query, (guild_id_str,))
        except Exception as e:
            print(f"FactionManager: DB error fetching factions for {guild_id_str}: {e}")
            traceback.print_exc()
            return

        for row in rows:
            try:
                data = dict(row)
                # Deserialize JSON fields
                for field_name in ["name_i18n", "description_i18n", "member_ids", "state_variables"]:
                    if data[field_name] is not None and isinstance(data[field_name], str):
                        data[field_name] = json.loads(data[field_name])
                    elif data[field_name] is None: # Handle cases where DB might return NULL for JSON fields
                        if field_name in ["name_i18n", "description_i18n", "state_variables"]:
                            data[field_name] = {}
                        elif field_name == "member_ids":
                            data[field_name] = []

                faction = Faction.from_dict(data)
                self._factions[guild_id_str][faction.id] = faction
            except Exception as e:
                print(f"FactionManager: Error loading faction {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                traceback.print_exc()
        print(f"FactionManager: Loaded {len(self._factions[guild_id_str])} factions for guild {guild_id_str}.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if not self._db_service or not self._db_service.adapter:
            print(f"FactionManager: DB service or adapter missing for {guild_id_str}. Cannot save factions.")
            return

        self._ensure_guild_cache_exists(guild_id_str)

        # Handle Deletions
        ids_to_delete = list(self._deleted_faction_ids.get(guild_id_str, set()))
        if ids_to_delete:
            placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete))])
            delete_sql = f"DELETE FROM factions WHERE guild_id = $1 AND id IN ({placeholders})"
            try:
                await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                self._deleted_faction_ids[guild_id_str].clear()
            except Exception as e:
                print(f"FactionManager: DB error deleting factions for {guild_id_str}: {e}")
                traceback.print_exc() # Keep IDs in set for retry if error

        # Handle Inserts/Updates
        dirty_faction_ids = list(self._dirty_factions.get(guild_id_str, set()))
        if not dirty_faction_ids:
            return

        factions_to_save_data = []
        successfully_prepared_ids = set()
        for faction_id in dirty_faction_ids:
            faction = self.get_faction(guild_id_str, faction_id)
            if faction:
                try:
                    factions_to_save_data.append((
                        faction.id, faction.guild_id,
                        json.dumps(faction.name_i18n), json.dumps(faction.description_i18n),
                        faction.leader_id, faction.alignment,
                        json.dumps(faction.member_ids), json.dumps(faction.state_variables)
                    ))
                    successfully_prepared_ids.add(faction_id)
                except Exception as e:
                    print(f"FactionManager: Error preparing faction {faction_id} for save: {e}")
                    traceback.print_exc()

        if not factions_to_save_data:
            return

        upsert_sql = """
            INSERT INTO factions (id, guild_id, name_i18n, description_i18n, leader_id,
                                  alignment, member_ids, state_variables)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                guild_id = EXCLUDED.guild_id,
                name_i18n = EXCLUDED.name_i18n,
                description_i18n = EXCLUDED.description_i18n,
                leader_id = EXCLUDED.leader_id,
                alignment = EXCLUDED.alignment,
                member_ids = EXCLUDED.member_ids,
                state_variables = EXCLUDED.state_variables
        """
        try:
            await self._db_service.adapter.execute_many(upsert_sql, factions_to_save_data)
            if guild_id_str in self._dirty_factions: # Check existence before operation
                 self._dirty_factions[guild_id_str].difference_update(successfully_prepared_ids)
                 if not self._dirty_factions[guild_id_str]: # If set becomes empty
                     del self._dirty_factions[guild_id_str]

        except Exception as e:
            print(f"FactionManager: DB error saving factions for {guild_id_str}: {e}")
            traceback.print_exc()

        # print(f"FactionManager: Save state complete for guild {guild_id_str}.")
