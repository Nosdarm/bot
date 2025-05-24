# bot/game/managers/relationship_manager.py
<<<<<<< HEAD
from __future__ import annotations
import json
import uuid
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    # from bot.game.models.relationship import Relationship # If you create a model

class RelationshipManager:
=======

from __future__ import annotations
import uuid
import json # Not strictly needed for Relationship model as defined, but good for future complex details
import time # For updated_at, though DB can handle it.
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.game.models.relationship import Relationship

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter

print("DEBUG: relationship_manager.py module loaded.")

class RelationshipManager:
    """
    Manages relationships between entities in the game.
    """
>>>>>>> origin/fix-quest-manager-lint
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

<<<<<<< HEAD
    def __init__(self, db_adapter: Optional[SqliteAdapter] = None, settings: Optional[Dict[str, Any]] = None, **kwargs):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        # {guild_id: {entity1_id: {entity2_id: {"type": "friendly", "strength": 70.5, ...}}}}
        self._relationships: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
        self._dirty_relationships: Dict[str, Set[str]] = {} # {guild_id: {entity_id_whose_relations_changed}}
        print("RelationshipManager initialized.")

    async def get_relationships_for_entity(self, guild_id: str, entity_id: str, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Placeholder - to be implemented
        print(f"RelationshipManager: Fetching relationships for {entity_id} in guild {guild_id} (Placeholder).")
        # In a real implementation, this would query self._relationships or the DB.
        # It should also try to get names for target_ids using CharacterManager/NpcManager from context.
        return list(self._relationships.get(str(guild_id), {}).get(str(entity_id), {}).values())


    async def get_relationship_between_entities(
        self, guild_id: str, entity1_id: str, entity2_id: str, context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        # Placeholder
        print(f"RelationshipManager: Fetching relationship between {entity1_id} and {entity2_id} in guild {guild_id} (Placeholder).")
        guild_rels = self._relationships.get(str(guild_id), {})
        entity1_rels = guild_rels.get(str(entity1_id), {})
        return entity1_rels.get(str(entity2_id)) # Returns None if not found

    async def adjust_relationship(
        self, guild_id: str, entity1_id: str, entity2_id: str, 
        relationship_type: str, change: float, 
        min_val: float = -100.0, max_val: float = 100.0,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        # Placeholder
        guild_id_str, e1_str, e2_str = str(guild_id), str(entity1_id), str(entity2_id)
        print(f"RelationshipManager: Adjusting relationship ({relationship_type}) between {e1_str} and {e2_str} by {change} in guild {guild_id_str} (Placeholder).")
        
        guild_rels = self._relationships.setdefault(guild_id_str, {})
        
        # Ensure symmetrical relationships are considered if your model implies it.
        # For now, just one way for simplicity in placeholder.
        entity1_rels = guild_rels.setdefault(e1_str, {})
        
        current_rel = entity1_rels.get(e2_str)
        if not current_rel:
            current_rel = {'type': relationship_type, 'strength': 0.0} # Default new relationship
            entity1_rels[e2_str] = current_rel
        
        # If type changes or is different, might reset strength or handle differently
        if current_rel.get('type') != relationship_type:
            current_rel['type'] = relationship_type
            # current_rel['strength'] = 0.0 # Optional: reset strength if type changes

        current_rel['strength'] = max(min_val, min(max_val, current_rel.get('strength', 0.0) + change))
        
        self._dirty_relationships.setdefault(guild_id_str, set()).add(e1_str)
        # If relationships are symmetrical, also mark e2_str as dirty and update its relationship toward e1_str
        # entity2_rels = guild_rels.setdefault(e2_str, {})
        # entity2_rels[e1_str] = current_rel.copy() # Example of symmetry
        # self._dirty_relationships.setdefault(guild_id_str, set()).add(e2_str)
        
        return True # Placeholder

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        # Placeholder: Load relationships from DB for the guild
        # Example: SELECT entity1_id, entity2_id, type, strength FROM relationships WHERE guild_id = ?
        print(f"RelationshipManager: Load state for guild {str(guild_id)} (Placeholder - DB load not implemented).")
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        # Placeholder: Save dirty relationships to DB for the guild
        # Example: Iterate self._dirty_relationships for the guild, then self._relationships
        # For each dirty entity, get their relationships and INSERT/UPDATE them.
        print(f"RelationshipManager: Save state for guild {str(guild_id)} (Placeholder - DB save not implemented).")
        if guild_id in self._dirty_relationships:
            self._dirty_relationships[guild_id].clear() # Clear dirty set after "saving"
        pass
            
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        print(f"RelationshipManager: Rebuild runtime caches for guild {str(guild_id)} (no complex runtime caches).")
        pass
=======
    def __init__(self, db_adapter: Optional["SqliteAdapter"], settings: Optional[Dict[str, Any]]):
        print("Initializing RelationshipManager...")
        self._db_adapter: Optional["SqliteAdapter"] = db_adapter
        self._settings: Optional[Dict[str, Any]] = settings

        self._relationships: Dict[str, Dict[str, Relationship]] = {} # guild_id -> relationship_id -> Relationship
        self._relationships_by_entity: Dict[str, Dict[str, Set[str]]] = {} # guild_id -> entity_id -> set of relationship_ids

        self._dirty_relationships: Dict[str, Set[str]] = {} # guild_id -> set of relationship_ids
        self._deleted_relationship_ids: Dict[str, Set[str]] = {} # guild_id -> set of relationship_ids
        print("RelationshipManager initialized.")

    def _get_entity_pair_key(self, entity1_id: str, entity2_id: str) -> str:
        """Creates a sorted, unique key for a pair of entity IDs."""
        return tuple(sorted((str(entity1_id), str(entity2_id)))) # type: ignore

    async def create_relationship(self,
                                  guild_id: str,
                                  entity1_id: str,
                                  entity1_type: str,
                                  entity2_id: str,
                                  entity2_type: str,
                                  relationship_type: str = "neutral",
                                  strength: float = 0.0,
                                  details: str = "") -> Optional[Relationship]:
        """
        Creates a new Relationship object.
        Prevents duplicate relationships (same two entities in any order).
        """
        guild_id_str = str(guild_id)
        entity1_id_str = str(entity1_id)
        entity2_id_str = str(entity2_id)

        if entity1_id_str == entity2_id_str:
            print(f"RelationshipManager: Attempted to create a relationship between an entity and itself ({entity1_id_str}). Skipping.")
            return None

        # Check for existing relationship between these two entities
        existing_rel = self.get_relationship_between_entities(guild_id_str, entity1_id_str, entity2_id_str)
        if existing_rel:
            print(f"RelationshipManager: Relationship already exists between {entity1_id_str} and {entity2_id_str} (ID: {existing_rel.id}) for guild {guild_id_str}. Skipping creation.")
            return existing_rel # Or None, depending on desired behavior for "already exists"

        print(f"RelationshipManager: Creating new relationship for guild {guild_id_str} between {entity1_id_str} ({entity1_type}) and {entity2_id_str} ({entity2_type}).")
        
        try:
            # Ensure guild_id is passed to the Relationship constructor
            rel_id = str(uuid.uuid4())
            relationship = Relationship(
                id=rel_id,
                entity1_id=entity1_id_str,
                entity1_type=entity1_type,
                entity2_id=entity2_id_str,
                entity2_type=entity2_type,
                relationship_type=relationship_type,
                strength=strength,
                details=details,
                guild_id=guild_id_str # Pass guild_id here
            )
        except ValueError as ve: # Catch validation errors from Relationship model
            print(f"RelationshipManager: Error creating Relationship object: {ve}")
            return None


        guild_rels = self._relationships.setdefault(guild_id_str, {})
        guild_rels[relationship.id] = relationship

        guild_entity_map = self._relationships_by_entity.setdefault(guild_id_str, {})
        guild_entity_map.setdefault(entity1_id_str, set()).add(relationship.id)
        guild_entity_map.setdefault(entity2_id_str, set()).add(relationship.id)

        self.mark_relationship_dirty(guild_id_str, relationship.id)
        print(f"RelationshipManager: Relationship {relationship.id} created and cached for guild {guild_id_str}.")
        return relationship

    def get_relationship(self, guild_id: str, relationship_id: str) -> Optional[Relationship]:
        """Returns a relationship by its ID for a specific guild."""
        guild_id_str = str(guild_id)
        return self._relationships.get(guild_id_str, {}).get(str(relationship_id))

    def get_relationships_for_entity(self, guild_id: str, entity_id: str) -> List[Relationship]:
        """Returns all relationships involving a specific entity in a guild."""
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        
        rels_for_entity: List[Relationship] = []
        rel_ids = self._relationships_by_entity.get(guild_id_str, {}).get(entity_id_str, set())
        
        guild_rels_cache = self._relationships.get(guild_id_str, {})
        for rel_id in rel_ids:
            rel = guild_rels_cache.get(rel_id)
            if rel:
                rels_for_entity.append(rel)
        return rels_for_entity

    def get_relationship_between_entities(self, guild_id: str, entity1_id: str, entity2_id: str) -> Optional[Relationship]:
        """Finds if a direct relationship exists between two entities (order shouldn't matter)."""
        guild_id_str = str(guild_id)
        entity1_id_str = str(entity1_id)
        entity2_id_str = str(entity2_id)

        rels_for_entity1 = self.get_relationships_for_entity(guild_id_str, entity1_id_str)
        for rel in rels_for_entity1:
            if (rel.entity1_id == entity1_id_str and rel.entity2_id == entity2_id_str) or \
               (rel.entity1_id == entity2_id_str and rel.entity2_id == entity1_id_str):
                return rel
        return None

    async def update_relationship(self,
                                  guild_id: str,
                                  relationship_id: str,
                                  new_type: Optional[str] = None,
                                  new_strength: Optional[float] = None,
                                  new_details: Optional[str] = None) -> Optional[Relationship]:
        """Updates an existing relationship."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        
        relationship = self.get_relationship(guild_id_str, relationship_id_str)
        if not relationship:
            print(f"RelationshipManager: Relationship {relationship_id_str} not found in guild {guild_id_str} for update.")
            return None

        updated = False
        if new_type is not None and relationship.relationship_type != new_type:
            relationship.relationship_type = new_type
            updated = True
        if new_strength is not None and relationship.strength != new_strength:
            relationship.strength = new_strength
            updated = True
        if new_details is not None and relationship.details != new_details:
            relationship.details = new_details
            updated = True

        if updated:
            self.mark_relationship_dirty(guild_id_str, relationship.id)
            print(f"RelationshipManager: Relationship {relationship.id} updated for guild {guild_id_str}.")
        else:
            print(f"RelationshipManager: No changes applied to relationship {relationship.id} for guild {guild_id_str}.")
            
        return relationship

    async def delete_relationship(self, guild_id: str, relationship_id: str) -> bool:
        """Removes a relationship from caches and marks for deletion from DB."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        
        relationship = self.get_relationship(guild_id_str, relationship_id_str)
        if not relationship:
            print(f"RelationshipManager: Relationship {relationship_id_str} not found in guild {guild_id_str} for deletion.")
            return False

        # Remove from main cache
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
            del self._relationships[guild_id_str][relationship_id_str]
            if not self._relationships[guild_id_str]: # if guild's dict is empty
                del self._relationships[guild_id_str]


        # Remove from entity lookup cache
        guild_entity_map = self._relationships_by_entity.get(guild_id_str, {})
        
        entity1_rels = guild_entity_map.get(relationship.entity1_id)
        if entity1_rels:
            entity1_rels.discard(relationship_id_str)
            if not entity1_rels: del guild_entity_map[relationship.entity1_id]

        entity2_rels = guild_entity_map.get(relationship.entity2_id)
        if entity2_rels:
            entity2_rels.discard(relationship_id_str)
            if not entity2_rels: del guild_entity_map[relationship.entity2_id]
        
        if not guild_entity_map and guild_id_str in self._relationships_by_entity: # if guild's dict is empty
             del self._relationships_by_entity[guild_id_str]


        # Mark for deletion from DB
        self._deleted_relationship_ids.setdefault(guild_id_str, set()).add(relationship_id_str)
        # Remove from dirty set if it was there
        self._dirty_relationships.get(guild_id_str, set()).discard(relationship_id_str)
        
        print(f"RelationshipManager: Relationship {relationship_id_str} removed from cache and marked for deletion for guild {guild_id_str}.")
        return True

    def mark_relationship_dirty(self, guild_id: str, relationship_id: str) -> None:
        """Marks a relationship as changed for subsequent persistence."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
            self._dirty_relationships.setdefault(guild_id_str, set()).add(relationship_id_str)
        else:
            print(f"RelationshipManager: Warning: Attempted to mark non-existent relationship {relationship_id_str} in guild {guild_id_str} as dirty.")

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Loads relationships for the guild from the DB."""
        guild_id_str = str(guild_id)
        print(f"RelationshipManager: Loading relationships for guild {guild_id_str} from DB...")
        if not self._db_adapter:
            print(f"RelationshipManager: DB adapter not available for guild {guild_id_str}. Cannot load relationships.")
            return

        # Clear existing cache for this guild
        self._relationships[guild_id_str] = {}
        self._relationships_by_entity[guild_id_str] = {}
        self._dirty_relationships.pop(guild_id_str, None)
        self._deleted_relationship_ids.pop(guild_id_str, None)

        query = "SELECT id, entity1_id, entity1_type, entity2_id, entity2_type, relationship_type, strength, details, guild_id FROM relationships WHERE guild_id = ?"
        try:
            rows = await self._db_adapter.fetchall(query, (guild_id_str,))
        except Exception as e:
            print(f"RelationshipManager: Error fetching relationships for guild {guild_id_str} from DB: {e}")
            return

        loaded_count = 0
        for row_data in rows:
            try:
                rel_data_dict = dict(row_data) # Convert aiosqlite.Row to dict
                # Ensure guild_id from DB matches the requested guild_id
                if str(rel_data_dict.get('guild_id')) != guild_id_str:
                    print(f"RelationshipManager: Warning: Loaded relationship {rel_data_dict.get('id')} with mismatched guild_id {rel_data_dict.get('guild_id')}, expected {guild_id_str}. Skipping.")
                    continue

                relationship = Relationship.from_dict(rel_data_dict)
                
                self._relationships.setdefault(guild_id_str, {})[relationship.id] = relationship
                
                entity_map = self._relationships_by_entity.setdefault(guild_id_str, {})
                entity_map.setdefault(relationship.entity1_id, set()).add(relationship.id)
                entity_map.setdefault(relationship.entity2_id, set()).add(relationship.id)
                loaded_count += 1
            except Exception as e:
                print(f"RelationshipManager: Error parsing relationship data for guild {guild_id_str}, row {row_data}: {e}")
        
        print(f"RelationshipManager: Loaded {loaded_count} relationships for guild {guild_id_str}.")
        # No need to call rebuild_runtime_caches here if load_state correctly populates _relationships_by_entity

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Saves dirty relationships and deletes marked ones for the guild."""
        guild_id_str = str(guild_id)
        if not self._db_adapter:
            print(f"RelationshipManager: DB adapter not available for guild {guild_id_str}. Cannot save relationships.")
            return

        # Handle deletions
        ids_to_delete = list(self._deleted_relationship_ids.get(guild_id_str, set()))
        if ids_to_delete:
            placeholders = ','.join(['?'] * len(ids_to_delete))
            delete_sql = f"DELETE FROM relationships WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                print(f"RelationshipManager: Deleted {len(ids_to_delete)} relationships for guild {guild_id_str} from DB.")
                self._deleted_relationship_ids.pop(guild_id_str, None) # Clear after successful deletion
            except Exception as e:
                print(f"RelationshipManager: Error deleting relationships for guild {guild_id_str}: {e}")
                # Do not clear if deletion fails, to retry next time.

        # Handle upserts (insert or replace)
        dirty_ids = list(self._dirty_relationships.get(guild_id_str, set()))
        if not dirty_ids:
            # print(f"RelationshipManager: No dirty relationships to save for guild {guild_id_str}.") # Can be noisy
            self._dirty_relationships.pop(guild_id_str, None) # Ensure empty set is removed
            return
            
        rels_to_save_data = []
        successfully_prepared_ids = set()

        guild_rels_cache = self._relationships.get(guild_id_str, {})

        for rel_id in dirty_ids:
            relationship = guild_rels_cache.get(rel_id)
            if relationship:
                if str(relationship.guild_id) != guild_id_str: # Integrity check
                    print(f"RelationshipManager: ERROR - Attempting to save relationship {rel_id} with guild_id {relationship.guild_id} under wrong guild_id {guild_id_str}. Skipping.")
                    continue
                try:
                    rels_to_save_data.append((
                        relationship.id, relationship.entity1_id, relationship.entity1_type,
                        relationship.entity2_id, relationship.entity2_type,
                        relationship.relationship_type, relationship.strength,
                        relationship.details, guild_id_str # Ensure guild_id is correct
                    ))
                    successfully_prepared_ids.add(rel_id)
                except Exception as e:
                    print(f"RelationshipManager: Error preparing relationship {rel_id} for saving in guild {guild_id_str}: {e}")
            else:
                 print(f"RelationshipManager: Warning - Dirty relationship ID {rel_id} not found in cache for guild {guild_id_str}. Cannot save.")


        if rels_to_save_data:
            upsert_sql = """
                INSERT OR REPLACE INTO relationships 
                (id, entity1_id, entity1_type, entity2_id, entity2_type, relationship_type, strength, details, guild_id, updated_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            """
            try:
                await self._db_adapter.execute_many(upsert_sql, rels_to_save_data)
                print(f"RelationshipManager: Upserted {len(rels_to_save_data)} relationships for guild {guild_id_str} to DB.")
                # Clear only successfully prepared and presumably saved dirty relationships
                if guild_id_str in self._dirty_relationships:
                    self._dirty_relationships[guild_id_str].difference_update(successfully_prepared_ids)
                    if not self._dirty_relationships[guild_id_str]: # if set is empty
                        del self._dirty_relationships[guild_id_str]
            except Exception as e:
                print(f"RelationshipManager: Error upserting relationships for guild {guild_id_str}: {e}")
                # Do not clear dirty set if upsert fails, to retry next time.
        elif dirty_ids: # If there were dirty IDs but none could be prepared
            print(f"RelationshipManager: No valid relationship data prepared for saving for guild {guild_id_str}, though {len(dirty_ids)} were marked dirty.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Rebuilds _relationships_by_entity from _relationships for the guild."""
        guild_id_str = str(guild_id)
        print(f"RelationshipManager: Rebuilding runtime caches for guild {guild_id_str}...")
        
        self._relationships_by_entity[guild_id_str] = {} # Clear or initialize for the guild
        
        guild_rels_cache = self._relationships.get(guild_id_str, {})
        entity_map = self._relationships_by_entity.setdefault(guild_id_str, {})

        for rel_id, relationship in guild_rels_cache.items():
            if str(relationship.guild_id) != guild_id_str: # Integrity check
                print(f"RelationshipManager: Warning - Relationship {rel_id} in main cache has mismatched guild_id {relationship.guild_id} during rebuild for guild {guild_id_str}. Skipping.")
                continue
            entity_map.setdefault(relationship.entity1_id, set()).add(rel_id)
            entity_map.setdefault(relationship.entity2_id, set()).add(rel_id)
            
        print(f"RelationshipManager: Runtime caches rebuilt for guild {guild_id_str}. Entities in map: {len(entity_map)}")

```
>>>>>>> origin/fix-quest-manager-lint
