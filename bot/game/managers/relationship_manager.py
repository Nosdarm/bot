# bot/game/managers/relationship_manager.py

from __future__ import annotations
import uuid
import json # Not strictly needed for Relationship model as defined, but good for future complex details
import time # For updated_at, though DB can handle it.
import traceback # For error handling

from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

# Assuming the Relationship model is defined in bot.game.models.relationship
from bot.game.models.relationship import Relationship
# Assuming Character model is defined in bot.game.models.character for type hints
from bot.game.models.character import Character

if TYPE_CHECKING:
    from bot.services.db_service import DBService # Changed
    from bot.game.managers.character_manager import CharacterManager # If directly interacting with characters
    from bot.game.rules.rule_engine import RuleEngine # If checking rules related to relationships

print("DEBUG: relationship_manager.py module loading...")


class RelationshipManager:
    """
    Manages relationships between characters and/or NPCs within a guild.
    """
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    def __init__(self,
                 db_service: Optional["DBService"] = None, # Changed
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional["CharacterManager"] = None, # Added CharacterManager
                 rule_engine: Optional["RuleEngine"] = None, # Added RuleEngine for checks
                 ):
        print("Initializing RelationshipManager...")
        self._db_service: Optional["DBService"] = db_service # Changed
        self._settings: Optional[Dict[str, Any]] = settings
        self._character_manager: Optional["CharacterManager"] = character_manager # Store it
        self._rule_engine: Optional["RuleEngine"] = rule_engine # Store it

        # Runtime cache for relationships, indexed by guild_id, then relationship_id
        # Note: Storing Relationships as objects
        self._relationships: Dict[str, Dict[str, Relationship]] = {} # {guild_id: {relationship_id: Relationship}}

        # To track changes for persistence
        self._dirty_relationships: Dict[str, Set[str]] = {} # {guild_id: set_of_relationship_ids}
        self._deleted_relationship_ids: Dict[str, Set[str]] = {} # {guild_id: set_of_relationship_ids}

        print("RelationshipManager initialized.")

    # --- Helper methods for managing cache state ---

    def get_relationship(self, guild_id: str, relationship_id: str) -> Optional[Relationship]:
        """Gets a relationship object from the cache."""
        guild_id_str = str(guild_id)
        return self._relationships.get(guild_id_str, {}).get(str(relationship_id))

    def get_relationships_for_entity(self, guild_id: str, entity_id: str) -> List[Relationship]:
        """Gets all relationships involving a specific entity (character or NPC) in a guild."""
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        guild_relationships = self._relationships.get(guild_id_str, {})
        return [rel for rel in guild_relationships.values() 
                if str(rel.entity1_id) == entity_id_str or str(rel.entity2_id) == entity_id_str]

    def add_relationship_to_cache(self, guild_id: str, relationship: Relationship) -> None:
        """Adds or updates a relationship in the cache and marks it dirty."""
        guild_id_str = str(guild_id)
        self._relationships.setdefault(guild_id_str, {})[str(relationship.id)] = relationship
        self.mark_relationship_dirty(guild_id_str, relationship.id)

    def mark_relationship_dirty(self, guild_id: str, relationship_id: str) -> None:
        """Marks a relationship as dirty for saving."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        self._dirty_relationships.setdefault(guild_id_str, set()).add(relationship_id_str)
        # If marked dirty, ensure it's not marked for deletion
        self._deleted_relationship_ids.get(guild_id_str, set()).discard(relationship_id_str)


    def mark_relationship_for_deletion(self, guild_id: str, relationship_id: str) -> None:
        """Marks a relationship for deletion from the database."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        self._deleted_relationship_ids.setdefault(guild_id_str, set()).add(relationship_id_str)
        # If marked for deletion, ensure it's not marked dirty
        self._dirty_relationships.get(guild_id_str, set()).discard(relationship_id_str)
        # Remove from cache immediately
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
             del self._relationships[guild_id_str][relationship_id_str]

    # --- Core Logic Methods ---

    async def create_or_update_relationship(
        self,
        guild_id: str,
        entity1_id: str,
        entity1_type: str, # e.g., 'character', 'npc', 'location'
        entity2_id: str,
        entity2_type: str, # e.g., 'character', 'npc', 'location'
        relationship_type: str, # e.g., 'friend', 'enemy', 'neutral'
        strength: float = 0.0, # -100.0 to 100.0
        details: Optional[Dict[str, Any]] = None, # Optional extra data
    ) -> Relationship:
        """
        Creates a new relationship or updates an existing one between two entities.
        Automatically handles ensuring entity1_id < entity2_id for consistent lookup.
        """
        guild_id_str = str(guild_id)
        # Ensure consistent order of entity IDs for unique relationship lookup
        # Assume string comparison is sufficient for ordering IDs
        if str(entity1_id) > str(entity2_id):
            entity1_id, entity2_id = entity2_id, entity1_id
            entity1_type, entity2_type = entity2_type, entity1_type

        entity1_id_str, entity2_id_str = str(entity1_id), str(entity2_id)
        rel_type_str = str(relationship_type).lower() # Standardize relationship type string

        # Check if a relationship of this type already exists between these entities
        existing_relationship_id = None
        for rel_id, rel in self._relationships.get(guild_id_str, {}).items():
            if (str(rel.entity1_id) == entity1_id_str and str(rel.entity2_id) == entity2_id_str) and \
               rel.relationship_type.lower() == rel_type_str:
                existing_relationship_id = rel_id
                break

        if existing_relationship_id:
            # Update existing relationship
            relationship = self.get_relationship(guild_id_str, existing_relationship_id)
            if relationship:
                # Update fields, being careful not to overwrite necessary data if details are merged
                # For simplicity here, let's assume details overwrite or are added
                relationship.strength = strength
                relationship.details = details # This might need more complex merging logic in a real app
                relationship.updated_at = int(time.time()) # Update timestamp

                self.mark_relationship_dirty(guild_id_str, relationship.id)
                print(f"RelationshipManager: Updated relationship {relationship.id} in guild {guild_id_str}.")
                return relationship
            else:
                 # Should not happen if existing_relationship_id was found in cache
                 print(f"RelationshipManager: WARNING - Existing relationship ID {existing_relationship_id} found in cache but object not retrievable.")


        # No existing relationship of this type, create a new one
        new_relationship_id = str(uuid.uuid4())
        relationship_data = {
            'id': new_relationship_id,
            'guild_id': guild_id_str,
            'entity1_id': entity1_id_str,
            'entity1_type': entity1_type,
            'entity2_id': entity2_id_str,
            'entity2_type': entity2_type,
            'relationship_type': rel_type_str,
            'strength': strength,
            'details': details if details is not None else {},
            'created_at': int(time.time()),
            'updated_at': int(time.time()),
        }
        try:
            relationship = Relationship.from_dict(relationship_data)
            self.add_relationship_to_cache(guild_id_str, relationship)
            print(f"RelationshipManager: Created new relationship {relationship.id} in guild {guild_id_str}.")
            return relationship
        except Exception as e:
            print(f"RelationshipManager: Error creating Relationship object: {e}, data: {relationship_data}"); traceback.print_exc()
            return None


    async def delete_relationship(self, guild_id: str, relationship_id: str) -> bool:
        """Deletes a relationship by ID."""
        guild_id_str = str(guild_id)
        relationship_id_str = str(relationship_id)
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
            self.mark_relationship_for_deletion(guild_id_str, relationship_id_str)
            print(f"RelationshipManager: Marked relationship {relationship_id_str} for deletion in guild {guild_id_str}.")
            return True
        print(f"RelationshipManager: Relationship {relationship_id_str} not found in cache for deletion in guild {guild_id_str}.")
        return False

    # --- Persistence Integration ---

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Loads relationships for a guild from the database."""
        guild_id_str = str(guild_id)
        print(f"RelationshipManager: Loading relationships for guild {guild_id_str} from DB...")
        if not self._db_service or not self._db_service.adapter: # Changed
            print(f"RelationshipManager: DB service or adapter missing for {guild_id_str}. Cannot load relationships.")
            return

        # Clear existing cache for the guild
        self._relationships[guild_id_str] = {}
        self._dirty_relationships.pop(guild_id_str, None)
        self._deleted_relationship_ids.pop(guild_id_str, None)

        # Example query (adjust table/column names as per your actual DB schema)
        query = """SELECT id, guild_id, entity1_id, entity1_type, entity2_id, entity2_type, 
                          relationship_type, strength, details, created_at, updated_at 
                   FROM relationships WHERE guild_id = $1""" # Changed placeholder
        try:
            rows = await self._db_service.adapter.fetchall(query, (guild_id_str,)) # Changed
        except Exception as e:
            print(f"RelationshipManager: DB error fetching relationships for {guild_id_str}: {e}")
            traceback.print_exc()
            return

        loaded_count = 0
        guild_cache = self._relationships[guild_id_str]
        for row in rows:
            try:
                data = dict(row)
                # Deserialize JSON fields if needed (e.g., 'details')
                if 'details' in data and isinstance(data['details'], str):
                     try: data['details'] = json.loads(data['details'])
                     except json.JSONDecodeError: 
                         print(f"RelationshipManager: Warning - Failed to parse JSON for 'details' in relationship {data.get('id')}. Defaulting to empty dict.");
                         data['details'] = {}
                elif 'details' not in data or data['details'] is None:
                    data['details'] = {}

                # Ensure entity IDs are strings for consistency
                data['entity1_id'] = str(data['entity1_id'])
                data['entity2_id'] = str(data['entity2_id'])
                data['guild_id'] = str(data['guild_id'])
                data['id'] = str(data['id'])
                data['relationship_type'] = str(data['relationship_type'])
                
                # Convert timestamps if necessary (if stored as strings/ints)
                # data['created_at'] = int(data['created_at']) if isinstance(data.get('created_at'), (int, float, str)) else None
                # data['updated_at'] = int(data['updated_at']) if isinstance(data.get('updated_at'), (int, float, str)) else None


                relationship = Relationship.from_dict(data)
                guild_cache[relationship.id] = relationship
                loaded_count += 1
            except Exception as e:
                print(f"RelationshipManager: Error loading relationship {data.get('id', 'N/A')} for guild {guild_id_str}: {e}"); traceback.print_exc()

        print(f"RelationshipManager: Loaded {loaded_count} relationships for guild {guild_id_str}.")

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Saves dirty relationships for a guild to the database and deletes marked ones."""
        guild_id_str = str(guild_id)
        if not self._db_service or not self._db_service.adapter:
            print(f"RelationshipManager: DB service or adapter missing for {guild_id_str}. Cannot save relationships.")
            return

        # --- Handle Deletions ---
        ids_to_delete = list(self._deleted_relationship_ids.get(guild_id_str, set()))
        if ids_to_delete:  # Proceed only if the list is not empty
            placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete))])
            delete_sql = f"DELETE FROM relationships WHERE guild_id = $1 AND id IN ({placeholders})"
            try:
                await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                print(f"RelationshipManager: Deleted {len(ids_to_delete)} relationships for guild {guild_id_str}.")
                self._deleted_relationship_ids.pop(guild_id_str, None)  # Clear set for the guild on success
            except Exception as e:
                print(f"RelationshipManager: DB error deleting relationships for {guild_id_str}: {e}"); traceback.print_exc()
                # Do NOT pop from _deleted_relationship_ids on error, to allow retry.
        # else: # No explicit 'else' needed if list was initially empty or for successful no-op.
            # If ids_to_delete was empty, self._deleted_relationship_ids.get(guild_id_str, set()) was empty.
            # Popping a non-existent key with a default is fine: self._deleted_relationship_ids.pop(guild_id_str, None)
            # However, we only want to pop if the guild's set was processed (either successfully deleted or was empty initially).
            # The current logic correctly pops only on successful DB deletion. If ids_to_delete is empty, nothing happens here,
            # and the guild_id key might remain in _deleted_relationship_ids with an empty set, which is harmless.

        # --- Handle Dirty (Inserts/Updates) ---
        dirty_ids = list(self._dirty_relationships.get(guild_id_str, set()))
        relationships_to_save_data = []
        successfully_prepared_ids = set()

        guild_relationships_cache = self._relationships.get(guild_id_str, {})

        for rel_id in dirty_ids:
            relationship = guild_relationships_cache.get(rel_id)
            if relationship and str(getattr(relationship, 'guild_id', None)) == guild_id_str:
                try:
                    data_tuple = (
                        relationship.id,
                        relationship.guild_id,
                        relationship.entity1_id,
                        relationship.entity1_type,
                        relationship.entity2_id,
                        relationship.entity2_type,
                        relationship.relationship_type,
                        relationship.strength,
                        json.dumps(relationship.details) if relationship.details is not None else '{}',
                        relationship.created_at,
                    )
                    relationships_to_save_data.append(data_tuple)
                    successfully_prepared_ids.add(rel_id)
                except Exception as e:
                    print(f"RelationshipManager: Error preparing relationship {rel_id} for save: {e}"); traceback.print_exc()

        if relationships_to_save_data:
            upsert_sql = """
                INSERT INTO relationships
                (id, guild_id, entity1_id, entity1_type, entity2_id, entity2_type,
                 relationship_type, strength, details, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    guild_id = EXCLUDED.guild_id,
                    entity1_id = EXCLUDED.entity1_id,
                    entity1_type = EXCLUDED.entity1_type,
                    entity2_id = EXCLUDED.entity2_id,
                    entity2_type = EXCLUDED.entity2_type,
                    relationship_type = EXCLUDED.relationship_type,
                    strength = EXCLUDED.strength,
                    details = EXCLUDED.details,
                    created_at = EXCLUDED.created_at,
                    updated_at = NOW()
            """
            try:
                await self._db_service.adapter.execute_many(upsert_sql, relationships_to_save_data)
                print(f"RelationshipManager: Successfully saved/updated {len(relationships_to_save_data)} relationships for guild {guild_id_str}.")
                if guild_id_str in self._dirty_relationships:
                    self._dirty_relationships[guild_id_str].difference_update(successfully_prepared_ids)
                    if not self._dirty_relationships[guild_id_str]:
                        del self._dirty_relationships[guild_id_str]
            except Exception as e:
                print(f"RelationshipManager: DB error saving relationships for {guild_id_str}: {e}"); traceback.print_exc()

        print(f"RelationshipManager: Save state complete for guild {guild_id_str}.")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Rebuilds any runtime caches if necessary (e.g., relationship graphs)."""
        guild_id_str = str(guild_id)
        print(f"RelationshipManager: Rebuilding runtime caches for guild {guild_id_str} (currently no complex caches to rebuild).")
        # Example: If you had a graph structure for quick relationship lookups
        # between any two entities, you would rebuild it here based on _relationships cache.
        print(f"RelationshipManager: Rebuild runtime caches complete for guild {guild_id_str}.")

    # --- Example Usage / Utility ---

    async def adjust_relationship_strength(self, guild_id: str, entity1_id: str, entity2_id: str, relationship_type: str, amount: float) -> Optional[Relationship]:
        """Adjusts the strength of an existing relationship."""
        guild_id_str = str(guild_id)
        # Ensure consistent order
        if str(entity1_id) > str(entity2_id):
            entity1_id, entity2_id = entity2_id, entity1_id

        entity1_id_str, entity2_id_str = str(entity1_id), str(entity2_id)
        rel_type_str = str(relationship_type).lower()

        # Find the specific relationship instance
        relationship_to_adjust = None
        for rel in self._relationships.get(guild_id_str, {}).values():
            if (str(rel.entity1_id) == entity1_id_str and str(rel.entity2_id) == entity2_id_str) and \
               rel.relationship_type.lower() == rel_type_str:
                relationship_to_adjust = rel
                break

        if relationship_to_adjust:
            relationship_to_adjust.strength += amount
            # Optional: Clamp strength between -100.0 and 100.0
            relationship_to_adjust.strength = max(-100.0, min(100.0, relationship_to_adjust.strength))
            relationship_to_adjust.updated_at = int(time.time())

            self.mark_relationship_dirty(guild_id_str, relationship_to_adjust.id)
            print(f"RelationshipManager: Adjusted strength of relationship {relationship_to_adjust.id} by {amount} to {relationship_to_adjust.strength} in guild {guild_id_str}.")
            return relationship_to_adjust
        else:
            # If no relationship exists, should we create a default one?
            # For now, just report not found.
            print(f"RelationshipManager: Relationship '{rel_type_str}' not found between {entity1_id_str} and {entity2_id_str} in guild {guild_id_str} for adjustment.")
            return None

print("DEBUG: RelationshipManager module defined.")
