# bot/game/managers/relationship_manager.py

from __future__ import annotations
import uuid
import json
import time
import traceback # Will be removed
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.game.models.relationship import Relationship
from bot.game.models.character import Character

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.game_log_manager import GameLogManager

from copy import deepcopy

logger = logging.getLogger(__name__) # Added
logger.debug("DEBUG: relationship_manager.py module loading...") # Changed


class RelationshipManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    def __init__(self,
                 db_service: Optional["DBService"] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 rule_engine: Optional["RuleEngine"] = None,
                 ):
        logger.info("Initializing RelationshipManager...") # Changed
        self._db_service: Optional["DBService"] = db_service
        self._settings: Optional[Dict[str, Any]] = settings
        self._character_manager: Optional["CharacterManager"] = character_manager
        self._rule_engine: Optional["RuleEngine"] = rule_engine
        self._relationships: Dict[str, Dict[str, Relationship]] = {}
        self._dirty_relationships: Dict[str, Set[str]] = {}
        self._deleted_relationship_ids: Dict[str, Set[str]] = {}
        logger.info("RelationshipManager initialized.") # Changed

    def get_relationship(self, guild_id: str, relationship_id: str) -> Optional[Relationship]:
        guild_id_str = str(guild_id)
        return self._relationships.get(guild_id_str, {}).get(str(relationship_id))

    def get_relationships_for_entity(self, guild_id: str, entity_id: str) -> List[Relationship]:
        guild_id_str, entity_id_str = str(guild_id), str(entity_id)
        guild_relationships = self._relationships.get(guild_id_str, {})
        return [rel for rel in guild_relationships.values() 
                if str(rel.entity1_id) == entity_id_str or str(rel.entity2_id) == entity_id_str]

    def add_relationship_to_cache(self, guild_id: str, relationship: Relationship) -> None:
        guild_id_str = str(guild_id)
        self._relationships.setdefault(guild_id_str, {})[str(relationship.id)] = relationship
        self.mark_relationship_dirty(guild_id_str, relationship.id)

    def mark_relationship_dirty(self, guild_id: str, relationship_id: str) -> None:
        guild_id_str, relationship_id_str = str(guild_id), str(relationship_id)
        self._dirty_relationships.setdefault(guild_id_str, set()).add(relationship_id_str)
        self._deleted_relationship_ids.get(guild_id_str, set()).discard(relationship_id_str)

    def mark_relationship_for_deletion(self, guild_id: str, relationship_id: str) -> None:
        guild_id_str, relationship_id_str = str(guild_id), str(relationship_id)
        self._deleted_relationship_ids.setdefault(guild_id_str, set()).add(relationship_id_str)
        self._dirty_relationships.get(guild_id_str, set()).discard(relationship_id_str)
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
             del self._relationships[guild_id_str][relationship_id_str]
             logger.info("RelationshipManager: Relationship %s removed from cache for guild %s and marked for DB deletion.", relationship_id_str, guild_id_str) # Added
        # else: logger.debug for already removed or not found

    async def create_or_update_relationship(
        self, guild_id: str, entity1_id: str, entity1_type: str,
        entity2_id: str, entity2_type: str, relationship_type: str,
        strength: float = 0.0, details_i18n: Optional[Dict[str, str]] = None,
    ) -> Optional[Relationship]: # Added Optional return
        guild_id_str = str(guild_id)
        if str(entity1_id) > str(entity2_id):
            entity1_id, entity2_id = entity2_id, entity1_id
            entity1_type, entity2_type = entity2_type, entity1_type
        entity1_id_str, entity2_id_str = str(entity1_id), str(entity2_id)
        rel_type_str = str(relationship_type).lower()

        existing_relationship_id = None
        for rel_id, rel in self._relationships.get(guild_id_str, {}).items():
            if (str(rel.entity1_id) == entity1_id_str and str(rel.entity2_id) == entity2_id_str) and \
               rel.relationship_type.lower() == rel_type_str:
                existing_relationship_id = rel_id; break

        if existing_relationship_id:
            relationship = self.get_relationship(guild_id_str, existing_relationship_id)
            if relationship:
                relationship.strength = strength
                relationship.details_i18n = details_i18n if details_i18n is not None else relationship.details_i18n # Preserve if None
                self.mark_relationship_dirty(guild_id_str, relationship.id)
                logger.info("RelationshipManager: Updated relationship %s in guild %s. Strength: %.2f", relationship.id, guild_id_str, strength) # Changed
                return relationship
            else:
                 logger.warning("RelationshipManager: Existing relationship ID %s found in cache but object not retrievable for guild %s.", existing_relationship_id, guild_id_str) # Changed

        new_relationship_id = str(uuid.uuid4())
        relationship_data = {
            'id': new_relationship_id, 'guild_id': guild_id_str,
            'entity1_id': entity1_id_str, 'entity1_type': entity1_type,
            'entity2_id': entity2_id_str, 'entity2_type': entity2_type,
            'relationship_type': rel_type_str, 'strength': strength,
            'details_i18n': details_i18n if details_i18n is not None else {},
        }
        try:
            relationship = Relationship.from_dict(relationship_data)
            self.add_relationship_to_cache(guild_id_str, relationship)
            logger.info("RelationshipManager: Created new relationship %s in guild %s between %s (%s) and %s (%s) of type %s, strength %.2f.", new_relationship_id, guild_id_str, entity1_id_str, entity1_type, entity2_id_str, entity2_type, rel_type_str, strength) # Changed
            return relationship
        except Exception as e:
            logger.error("RelationshipManager: Error creating Relationship object for guild %s: %s, data: %s", guild_id_str, e, relationship_data, exc_info=True) # Changed
            return None

    async def delete_relationship(self, guild_id: str, relationship_id: str) -> bool:
        guild_id_str, relationship_id_str = str(guild_id), str(relationship_id)
        if guild_id_str in self._relationships and relationship_id_str in self._relationships[guild_id_str]:
            self.mark_relationship_for_deletion(guild_id_str, relationship_id_str)
            # Log is handled by mark_relationship_for_deletion
            return True
        logger.warning("RelationshipManager: Relationship %s not found in cache for deletion in guild %s.", relationship_id_str, guild_id_str) # Changed
        return False

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("RelationshipManager: Loading relationships for guild %s from DB...", guild_id_str) # Changed
        if not self._db_service or not self._db_service.adapter:
            logger.error("RelationshipManager: DB service or adapter missing for guild %s. Cannot load relationships.", guild_id_str) # Changed
            return

        self._relationships[guild_id_str] = {}
        self._dirty_relationships.pop(guild_id_str, None)
        self._deleted_relationship_ids.pop(guild_id_str, None)

        query = "SELECT id, guild_id, entity1_id, entity1_type, entity2_id, entity2_type, relationship_type, strength, details_i18n FROM relationships WHERE guild_id = $1"
        try:
            rows = await self._db_service.adapter.fetchall(query, (guild_id_str,))
        except Exception as e:
            logger.error("RelationshipManager: DB error fetching relationships for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            return

        loaded_count = 0
        guild_cache = self._relationships[guild_id_str]
        for row in rows:
            try:
                data = dict(row)
                if 'details_i18n' in data and isinstance(data['details_i18n'], str):
                     try: data['details_i18n'] = json.loads(data['details_i18n'])
                     except json.JSONDecodeError: 
                         logger.warning("RelationshipManager: Failed to parse JSON for 'details_i18n' in relationship %s for guild %s. Defaulting to None.", data.get('id'), guild_id_str, exc_info=True); # Added guild_id
                         data['details_i18n'] = None
                elif 'details_i18n' not in data or data['details_i18n'] is None: data['details_i18n'] = None
                data['entity1_id'] = str(data['entity1_id']); data['entity2_id'] = str(data['entity2_id'])
                data['guild_id'] = str(data['guild_id']); data['id'] = str(data['id'])
                data['relationship_type'] = str(data['relationship_type'])
                relationship = Relationship.from_dict(data)
                guild_cache[relationship.id] = relationship
                loaded_count += 1
            except Exception as e:
                logger.error("RelationshipManager: Error loading relationship %s for guild %s: %s", data.get('id', 'N/A'), guild_id_str, e, exc_info=True) # Changed
        logger.info("RelationshipManager: Loaded %s relationships for guild %s.", loaded_count, guild_id_str) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.debug("RelationshipManager: Saving state for guild %s.", guild_id_str) # Changed to debug
        if not self._db_service or not self._db_service.adapter:
            logger.error("RelationshipManager: DB service or adapter missing for guild %s. Cannot save relationships.", guild_id_str) # Changed
            return

        ids_to_delete = list(self._deleted_relationship_ids.get(guild_id_str, set()))
        if ids_to_delete:
            placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete))])
            delete_sql = f"DELETE FROM relationships WHERE guild_id = $1 AND id IN ({placeholders})"
            try:
                await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                logger.info("RelationshipManager: Deleted %s relationships for guild %s.", len(ids_to_delete), guild_id_str) # Changed
                self._deleted_relationship_ids.pop(guild_id_str, None)
            except Exception as e:
                logger.error("RelationshipManager: DB error deleting relationships for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

        dirty_ids = list(self._dirty_relationships.get(guild_id_str, set()))
        relationships_to_save_data = []
        successfully_prepared_ids = set()
        guild_relationships_cache = self._relationships.get(guild_id_str, {})
        for rel_id in dirty_ids:
            relationship = guild_relationships_cache.get(rel_id)
            if relationship and str(getattr(relationship, 'guild_id', None)) == guild_id_str:
                try:
                    data_tuple = (
                        relationship.id, relationship.guild_id, relationship.entity1_id, relationship.entity1_type,
                        relationship.entity2_id, relationship.entity2_type, relationship.relationship_type,
                        relationship.strength, json.dumps(relationship.details_i18n) if relationship.details_i18n is not None else '{}',
                    )
                    relationships_to_save_data.append(data_tuple)
                    successfully_prepared_ids.add(rel_id)
                except Exception as e:
                    logger.error("RelationshipManager: Error preparing relationship %s for save in guild %s: %s", rel_id, guild_id_str, e, exc_info=True) # Changed
        if relationships_to_save_data:
            upsert_sql = """
                INSERT INTO relationships (id, guild_id, entity1_id, entity1_type, entity2_id, entity2_type, relationship_type, strength, details_i18n)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (id) DO UPDATE SET
                    guild_id = EXCLUDED.guild_id, entity1_id = EXCLUDED.entity1_id, entity1_type = EXCLUDED.entity1_type,
                    entity2_id = EXCLUDED.entity2_id, entity2_type = EXCLUDED.entity2_type,
                    relationship_type = EXCLUDED.relationship_type, strength = EXCLUDED.strength, details_i18n = EXCLUDED.details_i18n
            """
            try:
                await self._db_service.adapter.execute_many(upsert_sql, relationships_to_save_data)
                logger.info("RelationshipManager: Successfully saved/updated %s relationships for guild %s.", len(relationships_to_save_data), guild_id_str) # Changed
                if guild_id_str in self._dirty_relationships:
                    self._dirty_relationships[guild_id_str].difference_update(successfully_prepared_ids)
                    if not self._dirty_relationships[guild_id_str]: del self._dirty_relationships[guild_id_str]
            except Exception as e:
                logger.error("RelationshipManager: DB error saving relationships for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
        # logger.debug("RelationshipManager: Save state complete for guild %s.", guild_id_str) # Too noisy

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("RelationshipManager: Rebuilding runtime caches for guild %s (currently no complex caches to rebuild).", guild_id_str) # Changed
        logger.info("RelationshipManager: Rebuild runtime caches complete for guild %s.", guild_id_str) # Changed

    async def adjust_relationship_strength(self, guild_id: str, entity1_id: str, entity2_id: str, relationship_type: str, amount: float) -> Optional[Relationship]:
        guild_id_str = str(guild_id)
        if str(entity1_id) > str(entity2_id): entity1_id, entity2_id = entity2_id, entity1_id
        entity1_id_str, entity2_id_str = str(entity1_id), str(entity2_id)
        rel_type_str = str(relationship_type).lower()
        relationship_to_adjust = None
        for rel in self._relationships.get(guild_id_str, {}).values():
            if (str(rel.entity1_id) == entity1_id_str and str(rel.entity2_id) == entity2_id_str) and \
               rel.relationship_type.lower() == rel_type_str:
                relationship_to_adjust = rel; break
        if relationship_to_adjust:
            relationship_to_adjust.strength += amount
            relationship_to_adjust.strength = max(-100.0, min(100.0, relationship_to_adjust.strength))
            self.mark_relationship_dirty(guild_id_str, relationship_to_adjust.id)
            logger.info("RelationshipManager: Adjusted strength of relationship %s by %.2f to %.2f in guild %s.", relationship_to_adjust.id, amount, relationship_to_adjust.strength, guild_id_str) # Changed
            return relationship_to_adjust
        else:
            logger.warning("RelationshipManager: Relationship '%s' not found between %s and %s in guild %s for adjustment.", rel_type_str, entity1_id_str, entity2_id_str, guild_id_str) # Changed
            return None

    async def update_relationship(
        self, guild_id: str, event_type: str, rule_engine: "RuleEngine",
        game_log_manager: "GameLogManager", **event_data: Any
    ) -> List[Relationship]:
        guild_id_str = str(guild_id)
        updated_relationships: List[Relationship] = []
        log_prefix = f"RelationshipManager.update_relationship(guild='{guild_id_str}', event='{event_type}'):" # Added

        if not rule_engine or not rule_engine._rules_data:
            logger.error("%s Rule engine or rules data not available.", log_prefix) # Changed
            return updated_relationships
        all_relation_change_rules = rule_engine._rules_data.get("relation_rules", [])
        if not all_relation_change_rules:
            logger.debug("%s No relation_rules found in rule_engine._rules_data.", log_prefix) # Changed
            return updated_relationships

        applicable_rules = [rule for rule in all_relation_change_rules if rule.get("event_type") == event_type]
        if not applicable_rules:
            logger.debug("%s No relationship change rules found for event type '%s'.", log_prefix, event_type) # Changed
            return updated_relationships

        safe_builtins = {"True": True, "False": False, "None": None, "int": int, "float": float, "str": str, "list": list, "dict": dict, "set": set, "len": len, "abs": abs, "min": min, "max": max, "round": round}
        eval_globals = {"__builtins__": safe_builtins}
        base_eval_locals = {"event_data": deepcopy(event_data)}

        for rule_definition in applicable_rules:
            condition_str = rule_definition.get("condition")
            eval_locals = {"event_data": deepcopy(base_eval_locals["event_data"])}
            try:
                condition_met = eval(condition_str, eval_globals, eval_locals) if condition_str else True
            except Exception as e:
                logger.error("%s Error evaluating condition '%s': %s", log_prefix, condition_str, e, exc_info=True) # Changed
                continue
            if not condition_met: continue

            changes = rule_definition.get("changes", [])
            for change_instruction in changes:
                try:
                    # ... (Entity resolution logic as before) ...
                    resolved_entity1_id_str = str(eval_locals['event_data'].get(change_instruction.get("entity1_ref")))
                    resolved_entity2_id_str = str(eval_locals['event_data'].get(change_instruction.get("entity2_ref")))

                    # Get types directly from the rule's change instruction
                    resolved_entity1_type = change_instruction.get("entity1_type")
                    resolved_entity2_type = change_instruction.get("entity2_type")

                    if not all([resolved_entity1_id_str, resolved_entity1_type, resolved_entity2_id_str, resolved_entity2_type]) or \
                       resolved_entity1_id_str == 'None' or resolved_entity2_id_str == 'None': # Added None check for stringified IDs
                        logger.warning(f"{log_prefix} Could not resolve all entity IDs/types for rule '{rule_definition.get('name', 'Unnamed Rule')}' from change instruction: {change_instruction}. Resolved IDs: e1='{resolved_entity1_id_str}' (type='{resolved_entity1_type}'), e2='{resolved_entity2_id_str}' (type='{resolved_entity2_type}'). Skipping this change.")
                        continue

                    relationship_type = change_instruction.get("relationship_type", "neutral")
                    strength_change_str = str(change_instruction.get("strength_change", "0")) # Ensure it's a string for eval

                    # Evaluate strength_change using event_data context
                    try:
                        strength_change = float(eval(strength_change_str, eval_globals, eval_locals))
                    except Exception as e_eval_strength:
                        logger.error(f"{log_prefix} Error evaluating strength_change '{strength_change_str}' for rule '{rule_definition.get('name', 'Unnamed Rule')}': {e_eval_strength}. Defaulting to 0.", exc_info=True)
                        strength_change = 0.0

                    # Create or update the relationship
                    # The adjust_relationship_strength method finds existing or creates new if not found with 0 base, then adjusts.
                    # Or, create_or_update_relationship can be used if we want to set absolute strength or provide details.
                    # For now, let's assume adjust_relationship_strength is suitable if it creates new one with 0 initial strength.
                    # However, the current adjust_relationship_strength WARNS if not found.
                    # So, it's better to use create_or_update_relationship or ensure adjust creates.

                    # Let's refine the logic: get existing, if not, create, then adjust.
                    # Normalizing entity order for lookup/creation
                    norm_e1_id, norm_e2_id = resolved_entity1_id_str, resolved_entity2_id_str
                    norm_e1_type, norm_e2_type = resolved_entity1_type, resolved_entity2_type
                    if norm_e1_id > norm_e2_id:
                        norm_e1_id, norm_e2_id = norm_e2_id, norm_e1_id
                        norm_e1_type, norm_e2_type = norm_e2_type, norm_e1_type

                    existing_rel = None
                    for rel_obj in self._relationships.get(guild_id_str, {}).values():
                        if rel_obj.entity1_id == norm_e1_id and rel_obj.entity2_id == norm_e2_id and \
                           rel_obj.entity1_type == norm_e1_type and rel_obj.entity2_type == norm_e2_type and \
                           rel_obj.relationship_type == relationship_type:
                            existing_rel = rel_obj
                            break

                    current_strength = 0.0
                    if existing_rel:
                        current_strength = existing_rel.strength

                    new_strength = current_strength + strength_change
                    new_strength = max(-100.0, min(100.0, new_strength)) # Clamp

                    updated_rel = await self.create_or_update_relationship(
                        guild_id=guild_id_str,
                        entity1_id=resolved_entity1_id_str, # Use original resolved IDs for clarity in method call
                        entity1_type=resolved_entity1_type,
                        entity2_id=resolved_entity2_id_str,
                        entity2_type=resolved_entity2_type,
                        relationship_type=relationship_type,
                        strength=new_strength,
                        details_i18n=change_instruction.get("details_i18n") # Pass details if rule provides them
                    )
                    if updated_rel:
                        updated_relationships.append(updated_rel)
                        logger.info(f"{log_prefix} Relationship between {resolved_entity1_id_str}({resolved_entity1_type}) and {resolved_entity2_id_str}({resolved_entity2_type}) of type '{relationship_type}' changed by {strength_change} to {new_strength} due to rule '{rule_definition.get('name', 'Unnamed Rule')}'.")
                    else:
                        logger.error(f"{log_prefix} Failed to create/update relationship for rule '{rule_definition.get('name', 'Unnamed Rule')}' between {resolved_entity1_id_str} and {resolved_entity2_id_str}.")

                except Exception as e_instr:
                    logger.error("%s Error processing change instruction: %s", log_prefix, e_instr, exc_info=True)
        return updated_relationships

    async def get_relationship_strength(self, guild_id: str, entity1_id: str, entity1_type: str, entity2_id: str, entity2_type: str) -> float:
        # ... (logic as before)
        return 0.0 # Placeholder

logger.debug("DEBUG: RelationshipManager module defined.") # Changed
