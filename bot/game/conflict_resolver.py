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
import enum
from contextlib import asynccontextmanager


if TYPE_CHECKING:
    from .managers.game_log_manager import GameLogManager
    from bot.services.db_service import DBService
    from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition
    from ..services.notification_service import NotificationService
    from ..core.rule_engine import RuleEngine


logger = logging.getLogger(__name__)


class ConflictResolver:
    def __init__(self, rule_engine: 'Optional[RuleEngine]',
                 notification_service: 'Optional[NotificationService]',
                 db_service: 'DBService',
                 game_log_manager: Optional['GameLogManager'] = None):
        self.rule_engine = rule_engine
        self.notification_service = notification_service
        self.db_service = db_service
        self.game_log_manager = game_log_manager
        self.pending_manual_resolutions: Dict[str, Dict[str, Any]] = {}
        logger.info(f"ConflictResolver initialized. GameLogManager {'present' if game_log_manager else 'NOT present'}.")

    async def _get_rules_config_from_engine(self, guild_id: str) -> Optional['CoreGameRulesConfig']: # Added await potentially
        if self.rule_engine and hasattr(self.rule_engine, 'get_rules_config'):
            config = await self.rule_engine.get_rules_config(guild_id) # type: ignore[attr-defined] # Assuming get_rules_config is async
            if isinstance(config, CoreGameRulesConfig): # type: ignore[name-defined]
                return config
            elif isinstance(config, dict):
                try:
                    return CoreGameRulesConfig(**config) # type: ignore[name-defined]
                except Exception as e:
                    logger.error(f"Failed to parse dict rules_config into CoreGameRulesConfig for guild {guild_id}: {e}")
                    return None
        logger.warning(f"Could not retrieve valid CoreGameRulesConfig from rule_engine for guild {guild_id}.")
        return None

    async def create_conflict(self, guild_id: str, conflict_type: str, involved_entities_data: Dict[str, Any],
                              details_for_master: Optional[Dict[str, Any]] = None,
                              escalation_message: Optional[str] = None) -> str:
        conflict_id = f"conflict_{uuid.uuid4().hex[:12]}"

        timestamp_val = 'timestamp_unavailable'
        if self.rule_engine and hasattr(self.rule_engine, 'get_game_time'):
            timestamp_val = await self.rule_engine.get_game_time() # type: ignore[attr-defined]


        conflict_record = {
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
        if self.game_log_manager:
            log_details = {
                "conflict_id": conflict_id, "conflict_type": conflict_type,
                "message": escalation_message or f"Conflict '{conflict_type}' created."
            }
            related_entities_list = [{"type": k.replace("_id",""), "id": str(v)} for k,v in involved_entities_data.items() if k.endswith("_id")]
            await self.game_log_manager.log_event(
                guild_id=guild_id, event_type="conflict_created_pending_manual",
                details=log_details, related_entities=related_entities_list
            )
        return conflict_id

    async def resolve_conflict_automatically(self, guild_id: str, player_id: str, target_id: str, conflict_type: str, conflict_id: str) -> Dict[str, Any]:
        resolution_details = {}
        message_str = ""
        # Ensure IDs are strings for logging and comparison
        str_player_id = str(player_id) if player_id is not None else None
        str_target_id = str(target_id) if target_id is not None else None

        if conflict_type == "battle_player_vs_npc":
            resolution_details = {"winner": "player", "loser": "npc", "loot_awarded": "gold_coins_10"}
            message_str = f"Player {str_player_id} won the battle against NPC {str_target_id}."
            if self.game_log_manager:
                await self.game_log_manager.log_event(
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_player_win_battle", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=[{"type": "player", "id": str_player_id or ""}, {"type": "npc", "id": str_target_id or ""}]
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        elif conflict_type == "dialogue_persuasion_check":
            resolution_details = {"outcome": "failure", "reason": "npc_unconvinced"}
            message_str = f"Player {str_player_id} failed to persuade NPC {str_target_id}."
            if self.game_log_manager:
                await self.game_log_manager.log_event(
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_dialogue_fail", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=[{"type": "player", "id": str_player_id or ""}, {"type": "npc", "id": str_target_id or ""}]
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        return await self.escalate_for_manual_resolution(guild_id, conflict_id, conflict_type, "Auto-resolution rule not found or prefers manual.", {"player_id": str_player_id, "target_id": str_target_id})

    async def _handle_battle_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id")
        npc_id = conflict_data.get("npc_id")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Battle conflict {conflict_id} between Player {player_id} and NPC {npc_id} resolved by GM. Outcome: {outcome}."

        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str }
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id, event_type="battle_conflict_resolved_by_gm", details=log_event_details,
                player_id=str(player_id) if player_id else None,
                related_entities=[ {"type": "player", "id": str(player_id or "")}, {"type": "npc", "id": str(npc_id or "")} ])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_dialogue_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id"); npc_id = conflict_data.get("npc_id"); stage = conflict_data.get("dialogue_stage", "unknown")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Dialogue conflict {conflict_id} (Player {player_id}, NPC {npc_id}, Stage {stage}) resolved by GM. Outcome: {outcome}."
        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "dialogue_stage": stage, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "dialogue_conflict_resolved_by_gm", details=log_event_details, player_id=str(player_id) if player_id else None, related_entities=[{"type": "player", "id": str(player_id or "")}, {"type": "npc", "id": str(npc_id or "")}])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_skill_check_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id"); skill_name = conflict_data.get("skill_name", "unknown_skill"); dc = conflict_data.get("dc", "N/A")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Skill check conflict {conflict_id} (Player {player_id}, Skill {skill_name}, DC {dc}) resolved by GM. Outcome: {outcome}."
        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "skill_name": skill_name, "dc": dc, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "skill_check_conflict_resolved_by_gm", details=log_event_details, player_id=str(player_id) if player_id else None, related_entities=[{"type": "player", "id": str(player_id or "")}])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_item_interaction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id"); item_id = conflict_data.get("item_id"); interaction_type = conflict_data.get("interaction_type")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Item interaction conflict {conflict_id} (Player {player_id}, Item {item_id}, Type {interaction_type}) resolved by GM. Outcome: {outcome}."
        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "item_id": item_id, "interaction_type": interaction_type, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "item_interaction_conflict_resolved_by_gm", details=log_event_details, player_id=str(player_id) if player_id else None, related_entities=[{"type": "player", "id": str(player_id or "")}, {"type": "item", "id": str(item_id or "")}])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_environmental_hazard_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id"); hazard_type = conflict_data.get("hazard_type", "unknown_hazard"); location_id = conflict_data.get("location_id")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Environmental hazard conflict {conflict_id} (Player {player_id}, Hazard {hazard_type} at Loc {location_id}) resolved by GM. Outcome: {outcome}."
        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "hazard_type": hazard_type, "location_id": location_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "environmental_hazard_conflict_resolved_by_gm", details=log_event_details, player_id=str(player_id) if player_id else None, related_entities=[{"type": "player", "id": str(player_id or "")}, {"type": "location", "id": str(location_id or "")}])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_faction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id = conflict_data.get("player_id"); faction1_id = conflict_data.get("faction1_id"); faction2_id = conflict_data.get("faction2_id")
        action = conflict_data.get("action_taken", "unknown_action"); outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Faction conflict {conflict_id} (Faction1 {faction1_id}, Faction2 {faction2_id}, Action {action}) resolved by GM. Outcome: {outcome}."
        if player_id: message_str = f"Faction conflict involving Player {player_id}: {message_str}"
        log_event_details = {"conflict_id": conflict_id, "player_id": player_id, "faction1_id": faction1_id, "faction2_id": faction2_id, "action_taken": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "faction_conflict_resolved_by_gm", details=log_event_details, player_id=str(player_id) if player_id else None, related_entities=[{"type": "faction", "id": str(faction1_id or "")}, {"type": "faction", "id": str(faction2_id or "")}] + ([{"type": "player", "id": str(player_id or "")}] if player_id else []))
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_generic_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        actor_id = conflict_data.get("actor_id"); target_id = conflict_data.get("target_id"); action = conflict_data.get("action_description", "unknown_action")
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Generic conflict {conflict_id} (Actor {actor_id}, Target {target_id}, Action: {action}) resolved by GM. Outcome: {outcome}."
        log_event_details = {"conflict_id": conflict_id, "actor_id": actor_id, "target_id": target_id, "action_description": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params
        if self.game_log_manager:
            await self.game_log_manager.log_event(guild_id, "generic_conflict_resolved_by_gm", details=log_event_details, player_id=str(actor_id) if actor_id and conflict_data.get("actor_type") == "player" else None, related_entities=[{"type": str(conflict_data.get("actor_type")), "id": str(actor_id or "")} if actor_id and conflict_data.get("actor_type") else {}, {"type": str(conflict_data.get("target_type")), "id": str(target_id or "")} if target_id and conflict_data.get("target_type") else {}])
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def get_pending_conflict_details_for_master(self, guild_id: str, conflict_id: str) -> Optional[Dict[str, Any]]:
        pending_conflict_data_mem = self.pending_manual_resolutions.get(guild_id, {}).get(conflict_id)

        # Initialize pending_conflict_data with memory version or None
        pending_conflict_data: Optional[Dict[str, Any]] = None
        if pending_conflict_data_mem and isinstance(pending_conflict_data_mem, dict):
            pending_conflict_data = pending_conflict_data_mem

        if not pending_conflict_data: # If not in memory, try DB
            db_data = await self.db_service.get_pending_conflict(conflict_id) # This should be awaited
            if db_data:
                raw_conflict_json = db_data.get("conflict_data")
                if isinstance(raw_conflict_json, str):
                    try: pending_conflict_data = json.loads(raw_conflict_json)
                    except json.JSONDecodeError: logger.error(f"Failed to parse conflict_data from DB for {conflict_id}"); return None
                elif isinstance(raw_conflict_json, dict): # Already parsed (e.g. JSONB)
                    pending_conflict_data = raw_conflict_json

                if pending_conflict_data and guild_id not in self.pending_manual_resolutions: self.pending_manual_resolutions[guild_id] = {}
                if pending_conflict_data: self.pending_manual_resolutions[guild_id][conflict_id] = pending_conflict_data
            else: return None # Not found in DB either

        if not pending_conflict_data: return None # Still not found after DB check

        details_for_gm = {
            "conflict_id": conflict_id, "conflict_type": pending_conflict_data.get("type"),
            "details_for_master": pending_conflict_data.get("details_for_master", {}),
            "escalation_message": pending_conflict_data.get("escalation_message"),
            "escalated_at": pending_conflict_data.get("timestamp"),
            "suggested_resolution_options": []
        }
        conflict_type = pending_conflict_data.get("type")

        rules: Optional[CoreGameRulesConfig] = None # type: ignore[name-defined]
        if self.rule_engine and hasattr(self.rule_engine, "get_rules_config"):
            rules = await self.rule_engine.get_rules_config(guild_id) # type: ignore[attr-defined]

        conflict_rules_map = None
        if rules and hasattr(rules, 'conflict_resolution_rules') and rules.conflict_resolution_rules:
             if hasattr(rules.conflict_resolution_rules, 'action_conflicts_map'):
                conflict_rules_map = rules.conflict_resolution_rules.action_conflicts_map

        if conflict_rules_map and isinstance(conflict_rules_map, dict) and conflict_type in conflict_rules_map:
            type_specific_rules = conflict_rules_map.get(conflict_type)
            if isinstance(type_specific_rules, dict) and "manual_resolution_options" in type_specific_rules:
                options = type_specific_rules["manual_resolution_options"]
                if isinstance(options, list): details_for_gm["suggested_resolution_options"] = options

        if not details_for_gm["suggested_resolution_options"]:
            if conflict_type == "battle_player_vs_npc":
                details_for_gm["suggested_resolution_options"] = [{"outcome_type": "player_wins_battle", "description": "Player wins, gets rewards."}, {"outcome_type": "npc_wins_battle", "description": "NPC wins, player faces consequences."}, {"outcome_type": "battle_draw", "description": "Draw, both disengage."}]
            elif conflict_type == "dialogue_persuasion_check":
                 details_for_gm["suggested_resolution_options"] = [{"outcome_type": "persuasion_success_minor", "description": "Minor success."}, {"outcome_type": "persuasion_success_major", "description": "Major success."}, {"outcome_type": "persuasion_failure", "description": "Persuasion fails."}]
        return details_for_gm

    async def get_all_pending_conflicts_for_guild(self, guild_id: str) -> List[Dict[str, Any]]:
        guild_conflicts = self.pending_manual_resolutions.get(guild_id, {})
        # TODO: Optionally, augment with DB data if memory cache is not exhaustive
        # db_pending_list = await self.db_service.get_all_pending_conflicts_for_guild(guild_id)
        # Merge logic here if needed. For now, using memory cache.
        summaries = [{"conflict_id": cid, "type": data.get("type", "unknown"), "escalation_message_snippet": str(data.get("escalation_message", ""))[:100] + "...", "timestamp": data.get("timestamp")} for cid, data in guild_conflicts.items()]
        return sorted(summaries, key=lambda x: x.get("timestamp", ""), reverse=True)


class ActionStatus(enum.Enum):
    PENDING_ANALYSIS = "pending_analysis"; MANUAL_PENDING = "manual_pending"; AUTO_RESOLVED_PROCEED = "auto_resolved_proceed"
    AUTO_RESOLVED_FAILED_CONFLICT = "auto_resolved_failed_conflict"; PENDING_EXECUTION = "pending_execution"
    EXECUTED = "executed"; FAILED = "failed"

class ActionWrapper:
    def __init__(self, player_id: str, action_data: Dict[str, Any], action_id: str, original_intent: str, status: ActionStatus = ActionStatus.PENDING_ANALYSIS):
        self.player_id: str = player_id; self.action_data: Dict[str, Any] = action_data; self.action_id: str = action_id
        self.original_intent: str = original_intent; self._status: ActionStatus = status
        self.participated_in_conflict_resolution: bool = False; self.is_resolved: bool = False
    @property
    def status(self) -> ActionStatus: return self._status
    @status.setter
    def status(self, value: ActionStatus): self._status = value
    def __repr__(self) -> str: return f"<ActionWrapper id={self.action_id} player={self.player_id} intent={self.original_intent} status={self.status.value}>"
