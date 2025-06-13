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
    from bot.game.managers.game_log_manager import GameLogManager # Added for logging relationship changes

from copy import deepcopy # Added for safely handling event_data copies

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
        details_i18n: Optional[Dict[str, str]] = None, # Optional extra data, internationalized
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
                relationship.details_i18n = details_i18n # This might need more complex merging logic in a real app

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
            'details_i18n': details_i18n if details_i18n is not None else {},
        }
        try:
            # Relationship.from_dict will use details_i18n.
            # If an old 'details' field were present in relationship_data (it's not here),
            # the model's from_dict and __init__ would handle it for backward compatibility.
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
                          relationship_type, strength, details_i18n
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
                # Deserialize JSON fields if needed (e.g., 'details_i18n')
                # The model's from_dict expects details_i18n to be a dict or None.
                # If details_i18n is stored as JSON string in DB:
                if 'details_i18n' in data and isinstance(data['details_i18n'], str):
                     try: data['details_i18n'] = json.loads(data['details_i18n'])
                     except json.JSONDecodeError: 
                         print(f"RelationshipManager: Warning - Failed to parse JSON for 'details_i18n' in relationship {data.get('id')}. Defaulting to None.");
                         data['details_i18n'] = None # Or an empty dict {} if preferred by model for missing
                elif 'details_i18n' not in data or data['details_i18n'] is None:
                    # This handles cases where column might be missing or explicitly NULL
                    # Model's __init__ will default to {"en": ""} if details_i18n is None and details (legacy) is also None.
                    data['details_i18n'] = None

                # Ensure entity IDs are strings for consistency
                data['entity1_id'] = str(data['entity1_id'])
                data['entity2_id'] = str(data['entity2_id'])
                data['guild_id'] = str(data['guild_id'])
                data['id'] = str(data['id'])
                data['relationship_type'] = str(data['relationship_type'])
                
                # Timestamps (created_at, updated_at) are not in the model, so no processing needed here.

                relationship = Relationship.from_dict(data) # This will handle details_i18n or legacy 'details'
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
                        json.dumps(relationship.details_i18n) if relationship.details_i18n is not None else '{}',
                        # created_at is not part of the model or this data tuple anymore
                    )
                    relationships_to_save_data.append(data_tuple)
                    successfully_prepared_ids.add(rel_id)
                except Exception as e:
                    print(f"RelationshipManager: Error preparing relationship {rel_id} for save: {e}"); traceback.print_exc()

        if relationships_to_save_data:
            # Assuming DB handles updated_at via NOW() on its own if desired.
            # created_at is not in the model, so not inserting/updating it from client.
            # If DB has auto-created_at, it will handle it.
            upsert_sql = """
                INSERT INTO relationships
                (id, guild_id, entity1_id, entity1_type, entity2_id, entity2_type,
                 relationship_type, strength, details_i18n)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (id) DO UPDATE SET
                    guild_id = EXCLUDED.guild_id,
                    entity1_id = EXCLUDED.entity1_id,
                    entity1_type = EXCLUDED.entity1_type,
                    entity2_id = EXCLUDED.entity2_id,
                    entity2_type = EXCLUDED.entity2_type,
                    relationship_type = EXCLUDED.relationship_type,
                    strength = EXCLUDED.strength,
                    details_i18n = EXCLUDED.details_i18n
            """
            # Note: If your DB schema has an `updated_at` column managed by a trigger (e.g., `DEFAULT NOW()` or `ON UPDATE NOW()`),
            # you don't need to specify it in the `DO UPDATE SET` part unless you want to override it.
            # If it's not managed by a trigger, and you want to update it, add `updated_at = NOW()` to the SET clause.
            # For this subtask, based on model, we are removing explicit handling of created_at/updated_at from client side.

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
            # updated_at is not a field in the Relationship model

            self.mark_relationship_dirty(guild_id_str, relationship_to_adjust.id)
            print(f"RelationshipManager: Adjusted strength of relationship {relationship_to_adjust.id} by {amount} to {relationship_to_adjust.strength} in guild {guild_id_str}.")
            return relationship_to_adjust
        else:
            # If no relationship exists, should we create a default one?
            # For now, just report not found.
            print(f"RelationshipManager: Relationship '{rel_type_str}' not found between {entity1_id_str} and {entity2_id_str} in guild {guild_id_str} for adjustment.")
            return None

    async def update_relationship(
        self,
        guild_id: str,
        event_type: str,
        rule_engine: "RuleEngine",
        game_log_manager: "GameLogManager",
        **event_data: Any
    ) -> List[Relationship]:
        """
        Updates relationships based on game events and rules.
        """
        guild_id_str = str(guild_id)
        updated_relationships: List[Relationship] = []

        if not rule_engine or not rule_engine._rules_data:
            print("RelationshipManager: Rule engine or rules data not available.")
            return updated_relationships

        all_relation_change_rules = rule_engine._rules_data.get("relation_rules", []) # This is now a list

        if not all_relation_change_rules:
            # print(f"RelationshipManager: No relation_rules found in rule_engine._rules_data.")
            return updated_relationships

        # Filter rules for the current event_type
        applicable_rules = [
            rule for rule in all_relation_change_rules
            if rule.get("event_type") == event_type
        ]

        if not applicable_rules:
            # print(f"RelationshipManager: No relationship change rules found for event type '{event_type}'.")
            return updated_relationships

        # Safe builtins for eval
        safe_builtins = {
            "True": True, "False": False, "None": None,
            "int": int, "float": float, "str": str,
            "list": list, "dict": dict, "set": set,
            "len": len, "abs": abs, "min": min, "max": max, "round": round,
            # Add other safe functions as needed by rules
        }
        # Provide event_data directly in the local scope for eval
        eval_globals = {"__builtins__": safe_builtins}
        # Provide event_data directly in the local scope for eval
        base_eval_locals = {"event_data": deepcopy(event_data)} # Use a copy to prevent modification by eval


        for rule_definition in applicable_rules: # Iterate through filtered rules
            condition_str = rule_definition.get("condition")
            # Create a fresh eval_locals for each rule to avoid interference, though deepcopy helps
            eval_locals = {"event_data": deepcopy(base_eval_locals["event_data"])}


            try:
                condition_met = eval(condition_str, eval_globals, eval_locals) if condition_str else True
            except Exception as e:
                print(f"RelationshipManager: Error evaluating condition '{condition_str}' for event '{event_type}': {e}")
                traceback.print_exc()
                continue # Skip this rule definition

            if not condition_met:
                continue

            changes = rule_definition.get("changes", [])
            for change_instruction in changes:
                try:
                    entity1_ref = change_instruction.get("entity1_ref")
                    entity2_ref = change_instruction.get("entity2_ref")
                    entity1_type_ref = change_instruction.get("entity1_type_ref")
                    entity2_type_ref = change_instruction.get("entity2_type_ref")

                    # Resolve entities from event_data
                    # Assuming refs are direct keys in event_data
                    resolved_entity1_id = eval_locals['event_data'].get(entity1_ref)
                    resolved_entity2_id = eval_locals['event_data'].get(entity2_ref)

                    # Resolve entity types: can be direct from event_data or a literal string in the rule
                    if entity1_type_ref and entity1_type_ref.startswith("'") and entity1_type_ref.endswith("'"):
                        resolved_entity1_type = entity1_type_ref[1:-1] # Use as literal
                    else:
                        resolved_entity1_type = eval_locals['event_data'].get(entity1_type_ref)

                    if entity2_type_ref and entity2_type_ref.startswith("'") and entity2_type_ref.endswith("'"):
                        resolved_entity2_type = entity2_type_ref[1:-1] # Use as literal
                    else:
                        resolved_entity2_type = eval_locals['event_data'].get(entity2_type_ref)

                    if not all([resolved_entity1_id, resolved_entity2_id, resolved_entity1_type, resolved_entity2_type]):
                        print(f"RelationshipManager: Could not resolve all entity IDs/types for rule '{rule_definition.get('name', 'Unnamed Rule')}'. Entity Refs: e1_id='{entity1_ref}', e2_id='{entity2_ref}', e1_type_ref='{entity1_type_ref}', e2_type_ref='{entity2_type_ref}'. Resolved Values: e1_val='{resolved_entity1_id}', e2_val='{resolved_entity2_id}', e1_type_val='{resolved_entity1_type}', e2_type_val='{resolved_entity2_type}'. Skipping this change.")
                        continue

                    # Ensure IDs are strings
                    resolved_entity1_id = str(resolved_entity1_id)
                    resolved_entity2_id = str(resolved_entity2_id)

                    if resolved_entity1_id == resolved_entity2_id: # Cannot have relationship with oneself
                        print(f"RelationshipManager: Entity1 and Entity2 are the same ('{resolved_entity1_id}'). Skipping self-relationship change.")
                        continue

                    magnitude_formula = change_instruction.get("magnitude_formula", "0")
                    # Add current_strength to eval_locals if formula needs it.
                    # This requires fetching the relationship *before* evaluating magnitude.
                    # For now, assume magnitude_formula primarily uses event_data.
                    # If current_strength is needed, it will be fetched below.

                    new_relationship_type_from_rule = change_instruction.get("relation_type", "neutral") # Matches RelationChangeInstruction.relation_type
                    update_type = change_instruction.get("update_type", "add") # Matches RelationChangeInstruction.update_type

                    # Find existing relationship of the target type to get base strength
                    # Normalizing order for lookup:
                    norm_e1_id, norm_e1_type, norm_e2_id, norm_e2_type = resolved_entity1_id, resolved_entity1_type, resolved_entity2_id, resolved_entity2_type
                    if norm_e1_id > norm_e2_id:
                        norm_e1_id, norm_e2_id = norm_e2_id, norm_e1_id
                        norm_e1_type, norm_e2_type = norm_e2_type, norm_e1_type

                    current_relationship_of_target_type = None
                    for rel_obj in self._relationships.get(guild_id_str, {}).values():
                        if str(rel_obj.entity1_id) == norm_e1_id and \
                           str(rel_obj.entity2_id) == norm_e2_id and \
                           rel_obj.relationship_type.lower() == new_relationship_type_from_rule.lower():
                            current_relationship_of_target_type = rel_obj
                            break

                    old_strength = current_relationship_of_target_type.strength if current_relationship_of_target_type else 0.0
                    old_type_for_log = current_relationship_of_target_type.relationship_type if current_relationship_of_target_type else "none"

                    # Prepare eval_locals for magnitude_formula, potentially including current_strength
                    magnitude_eval_locals = deepcopy(eval_locals) # Use a fresh copy for this specific eval
                    magnitude_eval_locals["current_strength"] = old_strength
                    # Add other potentially relevant context if formulas need them, e.g. entity1.name, entity2.stats.XYZ etc.
                    # This would require fetching entity objects if not already in event_data.
                    # For now, keeping it simple with event_data and current_strength.

                    magnitude_value = float(eval(magnitude_formula, eval_globals, magnitude_eval_locals))


                    if update_type == "add": new_strength = old_strength + magnitude_value
                    elif update_type == "subtract": new_strength = old_strength - magnitude_value
                    elif update_type == "set": new_strength = magnitude_value
                    elif update_type == "multiply": new_strength = old_strength * magnitude_value # e.g. current_strength * 0.1
                    else:
                        print(f"RelationshipManager: Unknown update_type '{update_type}'. Defaulting to 'add'.")
                        new_strength = old_strength + magnitude_value

                    # Clamp strength
                    new_strength = max(-100.0, min(100.0, new_strength))

                    # Persist the change using create_or_update_relationship
                    # Pass original (un-normalized) entity IDs and types
                    updated_rel = await self.create_or_update_relationship(
                        guild_id=guild_id_str,
                        entity1_id=resolved_entity1_id,
                        entity1_type=resolved_entity1_type,
                        entity2_id=resolved_entity2_id,
                        entity2_type=resolved_entity2_type,
                        relationship_type=new_relationship_type_from_rule,
                        strength=new_strength,
                        details_i18n=None # Details not handled by this rule process for now
                    )

                    if updated_rel:
                        updated_relationships.append(updated_rel)
                        # Log the change
                        rule_name_for_log = rule_definition.get('name', 'Unnamed Rule')
                        change_instr_name_for_log = change_instruction.get('name')
                        log_name_suffix = f" (Instruction: {change_instr_name_for_log})" if change_instr_name_for_log else ""

                        log_message = (
                            f"Relationship between {resolved_entity1_type} {resolved_entity1_id} and "
                            f"{resolved_entity2_type} {resolved_entity2_id} changed due to event '{event_type}'. "
                            f"Type: {old_type_for_log} -> {updated_rel.relationship_type}. "
                            f"Strength: {old_strength:.2f} -> {updated_rel.strength:.2f} (Change: {magnitude_value:.2f} via {update_type}). Rule: {rule_name_for_log}{log_name_suffix}."
                        )
                        if game_log_manager: # Check if game_log_manager is provided
                           await game_log_manager.log_event(guild_id_str, "RELATIONSHIP_CHANGE", {"message": log_message, "details": updated_rel.to_dict()})
                        else:
                            print(f"RelationshipManager Log (guild {guild_id_str}): {log_message}")

                except Exception as e:
                    print(f"RelationshipManager: Error processing change instruction for event '{event_type}': {e}")
                    traceback.print_exc()
                    # Continue to next change instruction or rule

        return updated_relationships

    async def get_relationship_strength(self, guild_id: str, entity1_id: str, entity1_type: str, entity2_id: str, entity2_type: str) -> float:
        """
        Gets the strength of the first found relationship between two entities.
        Returns 0.0 if no specific relationship is found.
        """
        guild_id_str = str(guild_id)
        guild_relationships = self._relationships.get(guild_id_str, {})

        # Normalize ID order for lookup, as relationship keys might be stored with ordered IDs.
        # The create_or_update_relationship method already normalizes entity1_id and entity2_id
        # ensuring entity1_id < entity2_id before creating the Relationship object.
        # So, the Relationship objects in self._relationships should have rel.entity1_id < rel.entity2_id.

        e1_lookup_id_str = str(entity1_id)
        e2_lookup_id_str = str(entity2_id)
        e1_lookup_type = entity1_type
        e2_lookup_type = entity2_type

        # Ensure consistent ordering for the lookup pair, matching storage convention
        if e1_lookup_id_str > e2_lookup_id_str:
            e1_lookup_id_str, e2_lookup_id_str = e2_lookup_id_str, e1_lookup_id_str
            e1_lookup_type, e2_lookup_type = e2_lookup_type, e1_lookup_type

        # Iterate through all relationships for the guild
        for rel in guild_relationships.values():
            # Check if the current relationship involves the two specified entities,
            # respecting the normalized order stored in the Relationship object.
            if rel.entity1_id == e1_lookup_id_str and \
               rel.entity1_type == e1_lookup_type and \
               rel.entity2_id == e2_lookup_id_str and \
               rel.entity2_type == e2_lookup_type:
                # This assumes we are looking for *any* direct relationship.
                # If multiple relationship types can exist (e.g., "ally" and "trade_partner")
                # and a specific one is needed, this logic would need refinement or
                # the calling function would need to specify the relationship_type.
                # For now, return the strength of the first one found.
                return rel.strength

        return 0.0 # Default if no specific relationship found

print("DEBUG: RelationshipManager module defined.")
