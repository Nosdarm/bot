# bot/game/conflict_resolver.py
"""
Module for the ConflictResolver class, responsible for identifying and managing
game conflicts based on player actions and defined rules.
"""

import json
import logging
import uuid
import traceback
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union, Tuple, Set
from contextlib import asynccontextmanager


if TYPE_CHECKING:
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.db_service import DBService
    # Moved to local scope where needed to resolve circular import potential with RuleEngine
    # from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition, ConflictResolutionRules
    from bot.services.notification_service import NotificationService
    from bot.game.rules.rule_engine import RuleEngine # RuleEngine itself is fine here


logger = logging.getLogger(__name__)


class ConflictResolver:
    def __init__(self, rule_engine: 'Optional[RuleEngine]',
                 notification_service: 'Optional[NotificationService]',
                 db_service: 'DBService', # Assuming DBService is always provided
                 game_log_manager: Optional['GameLogManager'] = None):
        self.rule_engine: Optional['RuleEngine'] = rule_engine
        self.notification_service: Optional['NotificationService'] = notification_service
        self.db_service: 'DBService' = db_service # Ensure db_service is not None
        self.game_log_manager: Optional['GameLogManager'] = game_log_manager
        self.pending_manual_resolutions: Dict[str, Dict[str, Any]] = {}
        logger.info(f"ConflictResolver initialized. GameLogManager {'present' if game_log_manager else 'NOT present'}.")

    async def _get_rules_config_from_engine(self, guild_id: str) -> Optional['CoreGameRulesConfig']:
        if self.rule_engine and hasattr(self.rule_engine, 'get_rules_config') and callable(getattr(self.rule_engine, 'get_rules_config')):
            get_rules_config_method = getattr(self.rule_engine, 'get_rules_config')
            config_any = await get_rules_config_method(guild_id)

            # Import locally to avoid potential circular dependency issues at module load time
            from bot.ai.rules_schema import CoreGameRulesConfig as RuntimeCoreGameRulesConfig

            if isinstance(config_any, RuntimeCoreGameRulesConfig):
                return config_any
            elif isinstance(config_any, dict):
                try:
                    return RuntimeCoreGameRulesConfig(**config_any)
                except Exception as e:
                    logger.exception(f"Failed to parse dict rules_config into CoreGameRulesConfig for guild {guild_id}")
                    return None
            elif hasattr(config_any, 'model_dump') and callable(getattr(config_any, 'model_dump')): # For Pydantic v2+ models
                try:
                    dumped_data = config_any.model_dump()
                    return RuntimeCoreGameRulesConfig(**dumped_data)
                except Exception as e_parse:
                    logger.exception(f"Failed to re-parse Pydantic model into CoreGameRulesConfig for guild {guild_id}")
                    return None
            else:
                logger.warning(f"Retrieved rules_config for guild {guild_id} is not a CoreGameRulesConfig, dict, or compatible Pydantic model. Type: {type(config_any)}")
        else:
            logger.warning(f"RuleEngine or get_rules_config method not available for guild {guild_id}.")
        return None

    async def create_conflict(self, guild_id: str, conflict_type: str, involved_entities_data: Dict[str, Any],
                              details_for_master: Optional[Dict[str, Any]] = None,
                              escalation_message: Optional[str] = None) -> str:
        conflict_id = f"conflict_{uuid.uuid4().hex[:12]}"
        timestamp_val = 'timestamp_unavailable' # Default value
        if self.rule_engine and hasattr(self.rule_engine, 'get_game_time') and callable(getattr(self.rule_engine, 'get_game_time')):
            get_game_time_method = getattr(self.rule_engine, 'get_game_time')
            timestamp_val_any = await get_game_time_method()
            timestamp_val = str(timestamp_val_any) if timestamp_val_any is not None else 'timestamp_unavailable'
        else:
            logger.warning(f"RuleEngine or get_game_time not available for conflict {conflict_id} in guild {guild_id}, using default timestamp.")


        conflict_record: Dict[str, Any] = {
            "id": conflict_id, "guild_id": guild_id, "type": conflict_type,
            "involved_entities_data": involved_entities_data,
            "details_for_master": details_for_master or {},
            "escalation_message": escalation_message or f"Conflict of type '{conflict_type}' requires resolution.",
            "status": "pending_manual_resolution", "timestamp": timestamp_val
        }

        if guild_id not in self.pending_manual_resolutions:
            self.pending_manual_resolutions[guild_id] = {}
        self.pending_manual_resolutions[guild_id][conflict_id] = conflict_record

        logger.info(f"Created and stored pending conflict {conflict_id} for guild {guild_id}.")
        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            log_details_payload: Dict[str, Any] = {
                "conflict_id": conflict_id, "conflict_type": conflict_type,
                "message": escalation_message or f"Conflict '{conflict_type}' created."
            }
            # Ensure all IDs in involved_entities_data are strings for the log
            related_entities_list: List[Dict[str,str]] = []
            for k,v_any in involved_entities_data.items():
                if k.endswith("_id") and v_any is not None:
                    related_entities_list.append({"type": k.replace("_id",""), "id": str(v_any)})


            await log_event_method( # type: ignore[misc] # Pyright can't infer log_event_method type here
                guild_id=guild_id, event_type="conflict_created_pending_manual",
                details=log_details_payload,
                related_entities=related_entities_list
            )
        else:
            logger.warning(f"GameLogManager or log_event method not available for conflict creation logging in guild {guild_id}.")
        return conflict_id

    async def resolve_conflict_automatically(self, guild_id: str, player_id: Optional[str], target_id: Optional[str], conflict_type: str, conflict_id: str) -> Dict[str, Any]:
        resolution_details: Dict[str, Any] = {}
        message_str = ""

        str_player_id = str(player_id) if player_id is not None else None
        str_target_id = str(target_id) if target_id is not None else None

        related_entities_for_log: List[Dict[str,str]] = []
        if str_player_id: related_entities_for_log.append({"type": "player", "id": str_player_id})
        if str_target_id and conflict_type == "battle_player_vs_npc": # Assuming target is NPC for battle
             related_entities_for_log.append({"type": "npc", "id": str_target_id})
        elif str_target_id and conflict_type == "dialogue_persuasion_check": # Assuming target is NPC for dialogue
             related_entities_for_log.append({"type": "npc", "id": str_target_id})
        # Add more specific target type handling if needed for other conflict_types

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None

        if conflict_type == "battle_player_vs_npc":
            resolution_details = {"winner": "player", "loser": "npc", "loot_awarded": "gold_coins_10"}
            message_str = f"Player {str_player_id or 'N/A'} won the battle against NPC {str_target_id or 'N/A'}."
            if callable(log_event_method):
                await log_event_method( # type: ignore[misc]
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_player_win_battle", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=related_entities_for_log
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        elif conflict_type == "dialogue_persuasion_check":
            resolution_details = {"outcome": "failure", "reason": "npc_unconvinced"}
            message_str = f"Player {str_player_id or 'N/A'} failed to persuade NPC {str_target_id or 'N/A'}."
            if callable(log_event_method):
                await log_event_method( # type: ignore[misc]
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_dialogue_fail", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=related_entities_for_log
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        context_for_escalation: Dict[str, Any] = {} # Ensure type for context_for_escalation
        if str_player_id: context_for_escalation["player_id"] = str_player_id
        if str_target_id: context_for_escalation["target_id"] = str_target_id # Generic target_id

        return await self.escalate_for_manual_resolution(
            guild_id, conflict_id, conflict_type,
            "Auto-resolution rule not found or prefers manual.",
            context_for_escalation # Pass the typed dictionary
        )

    async def _handle_battle_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id")
        npc_id_any = conflict_data.get("npc_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        npc_id = str(npc_id_any) if npc_id_any is not None else None

        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Battle conflict {conflict_id} between Player {player_id or 'N/A'} and NPC {npc_id or 'N/A'} resolved by GM. Outcome: {outcome}."

        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str }
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if npc_id: related_entities_for_log.append({"type": "npc", "id": npc_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method( # type: ignore[misc]
                guild_id=guild_id, event_type="battle_conflict_resolved_by_gm", details=log_event_details,
                player_id=player_id,
                related_entities=related_entities_for_log )
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_dialogue_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); npc_id_any = conflict_data.get("npc_id"); stage = conflict_data.get("dialogue_stage", "unknown")
        player_id = str(player_id_any) if player_id_any is not None else None
        npc_id = str(npc_id_any) if npc_id_any is not None else None

        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Dialogue conflict {conflict_id} (Player {player_id or 'N/A'}, NPC {npc_id or 'N/A'}, Stage {stage}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "dialogue_stage": stage, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if npc_id: related_entities_for_log.append({"type": "npc", "id": npc_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "dialogue_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_skill_check_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); skill_name = conflict_data.get("skill_name", "unknown_skill"); dc = conflict_data.get("dc", "N/A")
        player_id = str(player_id_any) if player_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Skill check conflict {conflict_id} (Player {player_id or 'N/A'}, Skill {skill_name}, DC {dc}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "skill_name": skill_name, "dc": dc, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "skill_check_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_item_interaction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); item_id_any = conflict_data.get("item_id"); interaction_type = conflict_data.get("interaction_type")
        player_id = str(player_id_any) if player_id_any is not None else None
        item_id = str(item_id_any) if item_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Item interaction conflict {conflict_id} (Player {player_id or 'N/A'}, Item {item_id or 'N/A'}, Type {interaction_type}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "item_id": item_id, "interaction_type": interaction_type, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if item_id: related_entities_for_log.append({"type": "item", "id": item_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "item_interaction_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_environmental_hazard_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); hazard_type = conflict_data.get("hazard_type", "unknown_hazard"); location_id_any = conflict_data.get("location_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        location_id = str(location_id_any) if location_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Environmental hazard conflict {conflict_id} (Player {player_id or 'N/A'}, Hazard {hazard_type} at Loc {location_id or 'N/A'}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "hazard_type": hazard_type, "location_id": location_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if location_id: related_entities_for_log.append({"type": "location", "id": location_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "environmental_hazard_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_faction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); faction1_id_any = conflict_data.get("faction1_id"); faction2_id_any = conflict_data.get("faction2_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        faction1_id = str(faction1_id_any) if faction1_id_any is not None else None
        faction2_id = str(faction2_id_any) if faction2_id_any is not None else None

        action = conflict_data.get("action_taken", "unknown_action"); outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Faction conflict {conflict_id} (Faction1 {faction1_id or 'N/A'}, Faction2 {faction2_id or 'N/A'}, Action {action}) resolved by GM. Outcome: {outcome}."
        if player_id: message_str = f"Faction conflict involving Player {player_id}: {message_str}"
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "faction1_id": faction1_id, "faction2_id": faction2_id, "action_taken": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_list: List[Dict[str,str]] = []
        if faction1_id: related_entities_list.append({"type": "faction", "id": faction1_id})
        if faction2_id: related_entities_list.append({"type": "faction", "id": faction2_id})
        if player_id: related_entities_list.append({"type": "player", "id": player_id})

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "faction_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_list) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_generic_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        actor_id_any = conflict_data.get("actor_id"); target_id_any = conflict_data.get("target_id"); action = conflict_data.get("action_description", "unknown_action")
        actor_id = str(actor_id_any) if actor_id_any is not None else None
        target_id = str(target_id_any) if target_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params and isinstance(resolution_params, dict) else "unknown"
        message_str = f"Generic conflict {conflict_id} (Actor {actor_id or 'N/A'}, Target {target_id or 'N/A'}, Action: {action}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "actor_id": actor_id, "target_id": target_id, "action_description": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params and isinstance(resolution_params, dict): log_event_details["resolution_params"] = resolution_params

        related_entities_list: List[Dict[str,str]] = []
        actor_type = conflict_data.get("actor_type")
        target_type = conflict_data.get("target_type")
        if actor_id and actor_type: related_entities_list.append({"type": str(actor_type), "id": actor_id})
        if target_id and target_type: related_entities_list.append({"type": str(target_type), "id": target_id})

        player_id_for_log = actor_id if actor_id and actor_type == "player" else None

        log_event_method = getattr(self.game_log_manager, 'log_event', None) if self.game_log_manager else None
        if callable(log_event_method):
            await log_event_method(guild_id, "generic_conflict_resolved_by_gm", details=log_event_details, player_id=player_id_for_log, related_entities=related_entities_list) # type: ignore[misc]
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def get_pending_conflict_details_for_master(self, guild_id: str, conflict_id: str) -> Optional[Dict[str, Any]]:
        pending_conflict_data_mem = self.pending_manual_resolutions.get(guild_id, {}).get(conflict_id)

        pending_conflict_data: Optional[Dict[str, Any]] = None
        if pending_conflict_data_mem and isinstance(pending_conflict_data_mem, dict):
            pending_conflict_data = pending_conflict_data_mem

        if not pending_conflict_data_mem: # If not in memory, try DB
            db_data_any: Optional[Dict[str, Any]] = None
            get_pending_conflict_method = getattr(self.db_service, 'get_pending_conflict', None)
            if callable(get_pending_conflict_method):
                db_data_any = await get_pending_conflict_method(conflict_id)
            else:
                logger.warning(f"DBService missing 'get_pending_conflict', cannot fetch conflict {conflict_id} from DB for GM details.")

            if db_data_any and isinstance(db_data_any, dict):
                raw_conflict_json = db_data_any.get("conflict_data")
                if isinstance(raw_conflict_json, str):
                    try:
                        pending_conflict_data = json.loads(raw_conflict_json)
                    except json.JSONDecodeError:
                        logger.exception(f"Failed to parse conflict_data from DB for {conflict_id} in get_pending_conflict_details_for_master"); return None
                elif isinstance(raw_conflict_json, dict):
                    pending_conflict_data = raw_conflict_json
                else: # If raw_conflict_json is neither str nor dict
                    logger.error(f"Conflict data from DB for {conflict_id} is not a string or dict."); return None


                if pending_conflict_data and isinstance(pending_conflict_data, dict): # Ensure it's a dict after potential parsing
                    # Store in memory for future access if fetched from DB
                    if guild_id not in self.pending_manual_resolutions: self.pending_manual_resolutions[guild_id] = {}
                    self.pending_manual_resolutions[guild_id][conflict_id] = pending_conflict_data
                else: # If pending_conflict_data is still not a dict after parsing
                    logger.error(f"Parsed conflict_data for {conflict_id} is not a dict after DB fetch."); return None
            else: # If not found in DB or db_data_any is not a dict
                logger.info(f"Conflict {conflict_id} not found in memory or DB for guild {guild_id}.")
                return None
        elif isinstance(pending_conflict_data_mem, dict): # If found in memory and is a dict
            pending_conflict_data = pending_conflict_data_mem
        else: # If found in memory but not a dict (should not happen with proper storage)
            logger.error(f"In-memory conflict data for {conflict_id} in guild {guild_id} is not a dict: {type(pending_conflict_data_mem)}")
            return None


        # At this point, pending_conflict_data should be a valid dictionary
        conflict_type_val = pending_conflict_data.get("type")
        details_for_gm: Dict[str, Any] = {
            "conflict_id": conflict_id,
            "conflict_type": str(conflict_type_val) if conflict_type_val is not None else "unknown_type",
            "details_for_master": pending_conflict_data.get("details_for_master", {}),
            "escalation_message": pending_conflict_data.get("escalation_message"),
            "escalated_at": pending_conflict_data.get("timestamp"),
            "suggested_resolution_options": []
        }
        conflict_type_str = str(conflict_type_val) if conflict_type_val is not None else "unknown_type"


        rules_config: Optional['CoreGameRulesConfig'] = await self._get_rules_config_from_engine(guild_id)
        # Import Pydantic models locally for runtime checks
        from bot.ai.rules_schema import ConflictResolutionRules as RuntimeConflictResolutionRules
        from bot.ai.rules_schema import ActionConflictDefinition as RuntimeActionConflictDefinition

        conflict_rules_map: Optional[Dict[str, RuntimeActionConflictDefinition]] = None
        if rules_config and hasattr(rules_config, 'conflict_resolution_rules') and \
           isinstance(rules_config.conflict_resolution_rules, RuntimeConflictResolutionRules) and \
           hasattr(rules_config.conflict_resolution_rules, 'action_conflicts_map') and \
           isinstance(rules_config.conflict_resolution_rules.action_conflicts_map, dict):
             conflict_rules_map = rules_config.conflict_resolution_rules.action_conflicts_map


        if conflict_rules_map and conflict_type_str in conflict_rules_map:
            type_specific_rules_any = conflict_rules_map.get(conflict_type_str)
            if isinstance(type_specific_rules_any, RuntimeActionConflictDefinition):
                if type_specific_rules_any.manual_resolution_options:
                    details_for_gm["suggested_resolution_options"] = [opt.model_dump() for opt in type_specific_rules_any.manual_resolution_options if hasattr(opt, 'model_dump')]
            elif isinstance(type_specific_rules_any, dict) and "manual_resolution_options" in type_specific_rules_any: # Fallback for dict representation
                options_list = type_specific_rules_any["manual_resolution_options"]
                if isinstance(options_list, list): details_for_gm["suggested_resolution_options"] = options_list


        if not details_for_gm["suggested_resolution_options"]: # Default suggestions if none found in rules
            if conflict_type_str == "battle_player_vs_npc":
                details_for_gm["suggested_resolution_options"] = [{"outcome_type": "player_wins_battle", "description": "Player wins, gets rewards."}, {"outcome_type": "npc_wins_battle", "description": "NPC wins, player faces consequences."}, {"outcome_type": "battle_draw", "description": "Draw, both disengage."}]
            elif conflict_type_str == "dialogue_persuasion_check":
                 details_for_gm["suggested_resolution_options"] = [{"outcome_type": "persuasion_success_minor", "description": "Minor success."}, {"outcome_type": "persuasion_success_major", "description": "Major success."}, {"outcome_type": "persuasion_failure", "description": "Persuasion fails."}]
        return details_for_gm

    async def get_all_pending_conflicts_for_guild(self, guild_id: str) -> List[Dict[str, Any]]:
        guild_conflicts = self.pending_manual_resolutions.get(guild_id, {})
        summaries: List[Dict[str, Any]] = []
        for cid, data_any in guild_conflicts.items():
            if isinstance(data_any, dict): # Ensure data is a dict
                 summaries.append({"conflict_id": cid, "type": data_any.get("type", "unknown"), "escalation_message_snippet": str(data_any.get("escalation_message", ""))[:100] + "...", "timestamp": data_any.get("timestamp")})
            else:
                logger.warning(f"Invalid data type for conflict {cid} in guild {guild_id} in memory: {type(data_any)}")
        return sorted(summaries, key=lambda x: x.get("timestamp", "0") or "0", reverse=True) # Handle None timestamp

    async def process_master_resolution(self, conflict_id: str, outcome_type: str, resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        guild_id_for_conflict: Optional[str] = None
        conflict_data: Optional[Dict[str, Any]] = None

        # Try to get from memory first
        for gid_mem, conflicts_in_guild_mem in self.pending_manual_resolutions.items():
            if conflict_id in conflicts_in_guild_mem:
                guild_id_for_conflict = gid_mem
                conflict_data_mem = conflicts_in_guild_mem.pop(conflict_id) # Remove from memory
                if isinstance(conflict_data_mem, dict): conflict_data = conflict_data_mem
                if not conflicts_in_guild_mem: # Clean up empty guild entry
                    del self.pending_manual_resolutions[gid_mem]
                break

        if not guild_id_for_conflict or not conflict_data: # If not in memory, try DB
            db_data_any: Optional[Dict[str, Any]] = None
            get_pending_conflict_method = getattr(self.db_service, 'get_pending_conflict', None)
            if callable(get_pending_conflict_method):
                db_data_any = await get_pending_conflict_method(conflict_id)
            else:
                logging.warning(f"DBService missing 'get_pending_conflict', cannot fetch {conflict_id} from DB for master resolution.")


            if db_data_any and isinstance(db_data_any, dict):
                guild_id_for_conflict = str(db_data_any.get("guild_id")) if db_data_any.get("guild_id") else None
                conflict_data_json_str = db_data_any.get("conflict_data")
                if isinstance(conflict_data_json_str, str):
                    try:
                        conflict_data = json.loads(conflict_data_json_str)
                    except json.JSONDecodeError:
                        logger.exception(f"Failed to parse conflict_data from DB for {conflict_id} during master resolution.")
                        return {"success": False, "message": f"Conflict {conflict_id} data in DB is corrupted."}
                elif isinstance(conflict_data_json_str, dict):
                    conflict_data = conflict_data_json_str
                # else: conflict_data remains None or its previous value if not str/dict

                if guild_id_for_conflict and conflict_data and isinstance(conflict_data, dict):
                    delete_pending_conflict_method = getattr(self.db_service, 'delete_pending_conflict', None)
                    if callable(delete_pending_conflict_method):
                        await delete_pending_conflict_method(conflict_id)
                    else:
                        logging.warning(f"DBService missing 'delete_pending_conflict', cannot remove {conflict_id} from DB after processing.")
                else: # If data from DB is still not usable
                    return {"success": False, "message": f"Conflict {conflict_id} not found or data unusable from DB."}
            else: # If not found in DB or DBService method missing
                 return {"success": False, "message": f"Conflict {conflict_id} not found in memory or DB."}

        if not guild_id_for_conflict or not conflict_data or not isinstance(conflict_data, dict):
            return {"success": False, "message": f"Conflict {conflict_id} data is invalid or missing critical info."}


        conflict_type_val = conflict_data.get("type", "unknown_type")
        conflict_type_str = str(conflict_type_val) if conflict_type_val is not None else "unknown_type"

        involved_entities = conflict_data.get("involved_entities_data", {})
        if not isinstance(involved_entities, dict): involved_entities = {} # Ensure it's a dict


        handler_map: Dict[str, Any] = { # Ensure keys are strings
            "battle_player_vs_npc": self._handle_battle_conflict,
            "dialogue_persuasion_check": self._handle_dialogue_conflict,
            "skill_check": self._handle_skill_check_conflict,
            "item_interaction": self._handle_item_interaction_conflict,
            "environmental_hazard": self._handle_environmental_hazard_conflict,
            "faction_dispute": self._handle_faction_conflict,
            "generic_conflict": self._handle_generic_conflict
        }

        handler = handler_map.get(conflict_type_str, self._handle_generic_conflict)

        # Ensure all IDs in involved_entities are strings before passing to handler
        handler_conflict_data = {k: str(v) if isinstance(v, (int, uuid.UUID)) else v for k,v in involved_entities.items()}
        handler_conflict_data.update(conflict_data) # Add other top-level conflict_data too

        return await handler(guild_id_for_conflict, conflict_id, handler_conflict_data, resolution_params)

    async def escalate_for_manual_resolution(self, guild_id: str, conflict_id: str, conflict_type: str,
                                             message: str, context_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"Escalating conflict {conflict_id} ({conflict_type}) for manual GM resolution in guild {guild_id}.")


        if guild_id not in self.pending_manual_resolutions: self.pending_manual_resolutions[guild_id] = {}

        current_record = self.pending_manual_resolutions[guild_id].get(conflict_id, {})
        if not isinstance(current_record, dict): current_record = {} # Ensure it's a dict

        timestamp_val = 'timestamp_unavailable' # Default value
        if self.rule_engine and hasattr(self.rule_engine, 'get_game_time') and callable(getattr(self.rule_engine, 'get_game_time')):
            get_game_time_method = getattr(self.rule_engine, 'get_game_time')
            timestamp_val_any = await get_game_time_method()
            timestamp_val = str(timestamp_val_any) if timestamp_val_any is not None else 'timestamp_unavailable'

        current_record.update({
            "id": conflict_id, "guild_id": guild_id, "type": conflict_type,
            "status": "pending_manual_resolution",
            "escalation_message": message,
            "details_for_master": context_data or current_record.get("details_for_master", {}),
            "timestamp": current_record.get("timestamp") or timestamp_val
        })
        if "involved_entities_data" not in current_record and context_data and isinstance(context_data, dict):
            current_record["involved_entities_data"] = {k:v for k,v in context_data.items() if k.endswith("_id")}

        self.pending_manual_resolutions[guild_id][conflict_id] = current_record

        save_conflict_method = getattr(self.db_service, 'save_pending_conflict', None)
        if callable(save_conflict_method):
            try:
                await save_conflict_method(guild_id, conflict_id, json.dumps(current_record)) # type: ignore[misc]
            except Exception as e_save:
                logger.exception(f"Error saving escalated conflict {conflict_id} to DB for guild {guild_id}: {e_save}")
        else:
            logger.error(f"DBService missing 'save_pending_conflict'. Cannot persist escalated conflict {conflict_id} for guild {guild_id}.")


        notify_method = getattr(self.notification_service, 'notify_master_of_conflict', None) if self.notification_service else None
        if callable(notify_method):
            try:
                await notify_method(guild_id, conflict_id, conflict_type, message) # type: ignore[misc]
            except Exception as e_notify:
                logger.exception(f"Error notifying master of conflict {conflict_id} for guild {guild_id}: {e_notify}")
        else:
            logger.warning("NotificationService or notify_master_of_conflict method not available.")

        return {"success": False, "message": f"Conflict escalated for GM: {message}", "conflict_id": conflict_id, "status": "pending_manual_resolution"}

    async def load_pending_conflicts_from_db(self, guild_id: str):
        get_all_conflicts_method = getattr(self.db_service, 'get_all_pending_conflicts_for_guild', None)
        if callable(get_all_conflicts_method):
            pending_db_conflicts = await get_all_conflicts_method(guild_id) # type: ignore[misc]
            if pending_db_conflicts and isinstance(pending_db_conflicts, list):
                if guild_id not in self.pending_manual_resolutions:
                    self.pending_manual_resolutions[guild_id] = {}
                for conflict_row_any in pending_db_conflicts:
                    if not isinstance(conflict_row_any, dict):
                        logger.warning(f"Skipping non-dict conflict row from DB for guild {guild_id}: {conflict_row_any}")
                        continue
                    conflict_row: Dict[str, Any] = conflict_row_any

                    conflict_id = str(conflict_row.get("id")) if conflict_row.get("id") else None
                    conflict_data_json = conflict_row.get("conflict_data")
                    if conflict_id and conflict_data_json:
                        try:
                            conflict_data = json.loads(conflict_data_json) if isinstance(conflict_data_json, str) else conflict_data_json
                            if isinstance(conflict_data, dict): # Ensure it's a dict after loading
                                self.pending_manual_resolutions[guild_id][conflict_id] = conflict_data
                                logger.info(f"Loaded pending conflict {conflict_id} from DB for guild {guild_id}.")
                            else:
                                logger.error(f"Parsed conflict_data for {conflict_id} is not a dict. Guild: {guild_id}")
                        except json.JSONDecodeError:
                            logger.exception(f"Failed to parse conflict_data from DB for conflict {conflict_id} in guild {guild_id}.")
            logger.info(f"Finished loading pending conflicts from DB for guild {guild_id}. Total in memory: {len(self.pending_manual_resolutions.get(guild_id, {}))}")
        else:
            logger.warning(f"DBService missing 'get_all_pending_conflicts_for_guild'. Cannot load pending conflicts for guild {guild_id}.")
