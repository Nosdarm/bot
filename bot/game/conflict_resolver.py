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
    from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition, ConflictResolutionRules
    from bot.services.notification_service import NotificationService
    from bot.game.rules.rule_engine import RuleEngine


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
            config_any = await self.rule_engine.get_rules_config(guild_id)

            from bot.ai.rules_schema import CoreGameRulesConfig as RuntimeCoreGameRulesConfig

            if isinstance(config_any, RuntimeCoreGameRulesConfig):
                return config_any
            elif isinstance(config_any, dict):
                try:
                    return RuntimeCoreGameRulesConfig(**config_any)
                except Exception as e:
                    logger.error(f"Failed to parse dict rules_config into CoreGameRulesConfig for guild {guild_id}: {e}")
                    return None
            elif hasattr(config_any, 'model_dump') and callable(getattr(config_any, 'model_dump')):
                try:
                    return RuntimeCoreGameRulesConfig(**config_any.model_dump())
                except Exception as e_parse:
                    logger.error(f"Failed to re-parse Pydantic model into CoreGameRulesConfig for guild {guild_id}: {e_parse}")
                    return None
        logger.warning(f"Could not retrieve valid CoreGameRulesConfig from rule_engine for guild {guild_id}.")
        return None

    async def create_conflict(self, guild_id: str, conflict_type: str, involved_entities_data: Dict[str, Any],
                              details_for_master: Optional[Dict[str, Any]] = None,
                              escalation_message: Optional[str] = None) -> str:
        conflict_id = f"conflict_{uuid.uuid4().hex[:12]}"
        timestamp_val = 'timestamp_unavailable'
        if self.rule_engine and hasattr(self.rule_engine, 'get_game_time') and callable(getattr(self.rule_engine, 'get_game_time')):
            timestamp_val_any = await self.rule_engine.get_game_time()
            timestamp_val = str(timestamp_val_any) if timestamp_val_any is not None else 'timestamp_unavailable'

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
        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            log_details_payload: Dict[str, Any] = {
                "conflict_id": conflict_id, "conflict_type": conflict_type,
                "message": escalation_message or f"Conflict '{conflict_type}' created."
            }
            related_entities_list: List[Dict[str,str]] = [{"type": k.replace("_id",""), "id": str(v)} for k,v in involved_entities_data.items() if k.endswith("_id") and v is not None]

            await self.game_log_manager.log_event(
                guild_id=guild_id, event_type="conflict_created_pending_manual",
                details=log_details_payload,
                related_entities=related_entities_list
            )
        return conflict_id

    async def resolve_conflict_automatically(self, guild_id: str, player_id: Optional[str], target_id: Optional[str], conflict_type: str, conflict_id: str) -> Dict[str, Any]:
        resolution_details: Dict[str, Any] = {}
        message_str = ""

        str_player_id = str(player_id) if player_id is not None else None
        str_target_id = str(target_id) if target_id is not None else None

        related_entities_for_log: List[Dict[str,str]] = []
        if str_player_id: related_entities_for_log.append({"type": "player", "id": str_player_id})
        if str_target_id: related_entities_for_log.append({"type": "npc", "id": str_target_id})

        if conflict_type == "battle_player_vs_npc":
            resolution_details = {"winner": "player", "loser": "npc", "loot_awarded": "gold_coins_10"}
            message_str = f"Player {str_player_id or 'N/A'} won the battle against NPC {str_target_id or 'N/A'}."
            if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
                await self.game_log_manager.log_event(
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_player_win_battle", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=related_entities_for_log
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        elif conflict_type == "dialogue_persuasion_check":
            resolution_details = {"outcome": "failure", "reason": "npc_unconvinced"}
            message_str = f"Player {str_player_id or 'N/A'} failed to persuade NPC {str_target_id or 'N/A'}."
            if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
                await self.game_log_manager.log_event(
                    guild_id=guild_id, event_type="conflict_auto_resolved",
                    details={"message": message_str, "resolution_type": "auto_dialogue_fail", "conflict_id": conflict_id},
                    player_id=str_player_id,
                    related_entities=related_entities_for_log
                )
            return {"success": True, "message": message_str, "details": resolution_details}

        context_for_escalation = {}
        if str_player_id: context_for_escalation["player_id"] = str_player_id
        if str_target_id: context_for_escalation["target_id"] = str_target_id

        return await self.escalate_for_manual_resolution(
            guild_id, conflict_id, conflict_type,
            "Auto-resolution rule not found or prefers manual.",
            context_for_escalation
        )

    async def _handle_battle_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id")
        npc_id_any = conflict_data.get("npc_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        npc_id = str(npc_id_any) if npc_id_any is not None else None

        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Battle conflict {conflict_id} between Player {player_id or 'N/A'} and NPC {npc_id or 'N/A'} resolved by GM. Outcome: {outcome}."

        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str }
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if npc_id: related_entities_for_log.append({"type": "npc", "id": npc_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(
                guild_id=guild_id, event_type="battle_conflict_resolved_by_gm", details=log_event_details,
                player_id=player_id,
                related_entities=related_entities_for_log )
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_dialogue_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); npc_id_any = conflict_data.get("npc_id"); stage = conflict_data.get("dialogue_stage", "unknown")
        player_id = str(player_id_any) if player_id_any is not None else None
        npc_id = str(npc_id_any) if npc_id_any is not None else None

        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Dialogue conflict {conflict_id} (Player {player_id or 'N/A'}, NPC {npc_id or 'N/A'}, Stage {stage}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "npc_id": npc_id, "dialogue_stage": stage, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if npc_id: related_entities_for_log.append({"type": "npc", "id": npc_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "dialogue_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_skill_check_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); skill_name = conflict_data.get("skill_name", "unknown_skill"); dc = conflict_data.get("dc", "N/A")
        player_id = str(player_id_any) if player_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Skill check conflict {conflict_id} (Player {player_id or 'N/A'}, Skill {skill_name}, DC {dc}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "skill_name": skill_name, "dc": dc, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "skill_check_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_item_interaction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); item_id_any = conflict_data.get("item_id"); interaction_type = conflict_data.get("interaction_type")
        player_id = str(player_id_any) if player_id_any is not None else None
        item_id = str(item_id_any) if item_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Item interaction conflict {conflict_id} (Player {player_id or 'N/A'}, Item {item_id or 'N/A'}, Type {interaction_type}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "item_id": item_id, "interaction_type": interaction_type, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if item_id: related_entities_for_log.append({"type": "item", "id": item_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "item_interaction_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_environmental_hazard_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); hazard_type = conflict_data.get("hazard_type", "unknown_hazard"); location_id_any = conflict_data.get("location_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        location_id = str(location_id_any) if location_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Environmental hazard conflict {conflict_id} (Player {player_id or 'N/A'}, Hazard {hazard_type} at Loc {location_id or 'N/A'}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "hazard_type": hazard_type, "location_id": location_id, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_for_log: List[Dict[str,str]] = []
        if player_id: related_entities_for_log.append({"type": "player", "id": player_id})
        if location_id: related_entities_for_log.append({"type": "location", "id": location_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "environmental_hazard_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_for_log)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_faction_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        player_id_any = conflict_data.get("player_id"); faction1_id_any = conflict_data.get("faction1_id"); faction2_id_any = conflict_data.get("faction2_id")
        player_id = str(player_id_any) if player_id_any is not None else None
        faction1_id = str(faction1_id_any) if faction1_id_any is not None else None
        faction2_id = str(faction2_id_any) if faction2_id_any is not None else None

        action = conflict_data.get("action_taken", "unknown_action"); outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Faction conflict {conflict_id} (Faction1 {faction1_id or 'N/A'}, Faction2 {faction2_id or 'N/A'}, Action {action}) resolved by GM. Outcome: {outcome}."
        if player_id: message_str = f"Faction conflict involving Player {player_id}: {message_str}"
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "player_id": player_id, "faction1_id": faction1_id, "faction2_id": faction2_id, "action_taken": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_list: List[Dict[str,str]] = []
        if faction1_id: related_entities_list.append({"type": "faction", "id": faction1_id})
        if faction2_id: related_entities_list.append({"type": "faction", "id": faction2_id})
        if player_id: related_entities_list.append({"type": "player", "id": player_id})

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "faction_conflict_resolved_by_gm", details=log_event_details, player_id=player_id, related_entities=related_entities_list)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def _handle_generic_conflict(self, guild_id: str, conflict_id: str, conflict_data: Dict[str, Any], resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        actor_id_any = conflict_data.get("actor_id"); target_id_any = conflict_data.get("target_id"); action = conflict_data.get("action_description", "unknown_action")
        actor_id = str(actor_id_any) if actor_id_any is not None else None
        target_id = str(target_id_any) if target_id_any is not None else None
        outcome = resolution_params.get("outcome_type", "unknown") if resolution_params else "unknown"
        message_str = f"Generic conflict {conflict_id} (Actor {actor_id or 'N/A'}, Target {target_id or 'N/A'}, Action: {action}) resolved by GM. Outcome: {outcome}."
        log_event_details: Dict[str, Any] = {"conflict_id": conflict_id, "actor_id": actor_id, "target_id": target_id, "action_description": action, "resolution_outcome": outcome, "gm_resolved": True, "original_message": message_str}
        if resolution_params: log_event_details["resolution_params"] = resolution_params

        related_entities_list: List[Dict[str,str]] = []
        actor_type = conflict_data.get("actor_type")
        target_type = conflict_data.get("target_type")
        if actor_id and actor_type: related_entities_list.append({"type": str(actor_type), "id": actor_id})
        if target_id and target_type: related_entities_list.append({"type": str(target_type), "id": target_id})

        player_id_for_log = actor_id if actor_id and actor_type == "player" else None

        if self.game_log_manager and hasattr(self.game_log_manager, 'log_event') and callable(getattr(self.game_log_manager, 'log_event')):
            await self.game_log_manager.log_event(guild_id, "generic_conflict_resolved_by_gm", details=log_event_details, player_id=player_id_for_log, related_entities=related_entities_list)
        return {"success": True, "message": message_str, "details": {"resolved_outcome": outcome}}

    async def get_pending_conflict_details_for_master(self, guild_id: str, conflict_id: str) -> Optional[Dict[str, Any]]:
        pending_conflict_data_mem = self.pending_manual_resolutions.get(guild_id, {}).get(conflict_id)

        pending_conflict_data: Optional[Dict[str, Any]] = None
        if pending_conflict_data_mem and isinstance(pending_conflict_data_mem, dict):
            pending_conflict_data = pending_conflict_data_mem

        if not pending_conflict_data:
            db_data_any = None
            if hasattr(self.db_service, 'get_pending_conflict') and callable(getattr(self.db_service, 'get_pending_conflict')):
                db_data_any = await self.db_service.get_pending_conflict(conflict_id)
            else:
                logger.warning(f"DBService missing 'get_pending_conflict', cannot fetch conflict {conflict_id} from DB.")

            if db_data_any and isinstance(db_data_any, dict):
                raw_conflict_json = db_data_any.get("conflict_data")
                if isinstance(raw_conflict_json, str):
                    try: pending_conflict_data = json.loads(raw_conflict_json)
                    except json.JSONDecodeError: logger.error(f"Failed to parse conflict_data from DB for {conflict_id}"); return None
                elif isinstance(raw_conflict_json, dict):
                    pending_conflict_data = raw_conflict_json

                if pending_conflict_data and isinstance(pending_conflict_data, dict):
                    if guild_id not in self.pending_manual_resolutions: self.pending_manual_resolutions[guild_id] = {}
                    self.pending_manual_resolutions[guild_id][conflict_id] = pending_conflict_data
            else: return None

        if not pending_conflict_data or not isinstance(pending_conflict_data, dict): return None

        details_for_gm: Dict[str, Any] = {
            "conflict_id": conflict_id, "conflict_type": pending_conflict_data.get("type"),
            "details_for_master": pending_conflict_data.get("details_for_master", {}),
            "escalation_message": pending_conflict_data.get("escalation_message"),
            "escalated_at": pending_conflict_data.get("timestamp"),
            "suggested_resolution_options": []
        }
        conflict_type = pending_conflict_data.get("type")

        rules_config: Optional['CoreGameRulesConfig'] = await self._get_rules_config_from_engine(guild_id)

        conflict_rules_map: Optional[Dict[str, 'ActionConflictDefinition']] = None
        from bot.ai.rules_schema import ConflictResolutionRules as RuntimeConflictResolutionRules # Import for runtime
        if rules_config and hasattr(rules_config, 'conflict_resolution_rules') and \
           isinstance(rules_config.conflict_resolution_rules, RuntimeConflictResolutionRules) and \
           hasattr(rules_config.conflict_resolution_rules, 'action_conflicts_map'):
             conflict_rules_map = rules_config.conflict_resolution_rules.action_conflicts_map

        if conflict_rules_map and isinstance(conflict_rules_map, dict) and conflict_type and conflict_type in conflict_rules_map:
            type_specific_rules_any = conflict_rules_map.get(conflict_type)
            from bot.ai.rules_schema import ActionConflictDefinition as RuntimeActionConflictDefinition # Import for runtime
            if isinstance(type_specific_rules_any, RuntimeActionConflictDefinition):
                type_specific_rules: RuntimeActionConflictDefinition = type_specific_rules_any
                if type_specific_rules.manual_resolution_options:
                    details_for_gm["suggested_resolution_options"] = [opt.model_dump() for opt in type_specific_rules.manual_resolution_options if hasattr(opt, 'model_dump')]
            elif isinstance(type_specific_rules_any, dict) and "manual_resolution_options" in type_specific_rules_any:
                options = type_specific_rules_any["manual_resolution_options"]
                if isinstance(options, list): details_for_gm["suggested_resolution_options"] = options

        if not details_for_gm["suggested_resolution_options"]:
            if conflict_type == "battle_player_vs_npc":
                details_for_gm["suggested_resolution_options"] = [{"outcome_type": "player_wins_battle", "description": "Player wins, gets rewards."}, {"outcome_type": "npc_wins_battle", "description": "NPC wins, player faces consequences."}, {"outcome_type": "battle_draw", "description": "Draw, both disengage."}]
            elif conflict_type == "dialogue_persuasion_check":
                 details_for_gm["suggested_resolution_options"] = [{"outcome_type": "persuasion_success_minor", "description": "Minor success."}, {"outcome_type": "persuasion_success_major", "description": "Major success."}, {"outcome_type": "persuasion_failure", "description": "Persuasion fails."}]
        return details_for_gm

    async def get_all_pending_conflicts_for_guild(self, guild_id: str) -> List[Dict[str, Any]]:
        guild_conflicts = self.pending_manual_resolutions.get(guild_id, {})
        summaries = [{"conflict_id": cid, "type": data.get("type", "unknown"), "escalation_message_snippet": str(data.get("escalation_message", ""))[:100] + "...", "timestamp": data.get("timestamp")} for cid, data in guild_conflicts.items() if isinstance(data, dict)]
        return sorted(summaries, key=lambda x: x.get("timestamp", "0") or "0", reverse=True)

    async def process_master_resolution(self, conflict_id: str, outcome_type: str, resolution_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        guild_id_for_conflict: Optional[str] = None
        conflict_data: Optional[Dict[str, Any]] = None

        for gid, conflicts_in_guild in self.pending_manual_resolutions.items():
            if conflict_id in conflicts_in_guild:
                guild_id_for_conflict = gid
                conflict_data_mem = conflicts_in_guild.pop(conflict_id)
                if isinstance(conflict_data_mem, dict): conflict_data = conflict_data_mem
                if not conflicts_in_guild:
                    del self.pending_manual_resolutions[gid]
                break

        if not guild_id_for_conflict or not conflict_data:
            db_data_any = None
            if hasattr(self.db_service, 'get_pending_conflict') and callable(getattr(self.db_service, 'get_pending_conflict')):
                db_data_any = await self.db_service.get_pending_conflict(conflict_id)

            if db_data_any and isinstance(db_data_any, dict):
                guild_id_for_conflict = str(db_data_any.get("guild_id")) if db_data_any.get("guild_id") else None
                conflict_data_json_str = db_data_any.get("conflict_data")
                if isinstance(conflict_data_json_str, str):
                    try: conflict_data = json.loads(conflict_data_json_str)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse conflict_data from DB for {conflict_id} during master resolution.")
                        return {"success": False, "message": f"Conflict {conflict_id} data in DB is corrupted."}
                elif isinstance(conflict_data_json_str, dict):
                    conflict_data = conflict_data_json_str

                if guild_id_for_conflict and conflict_data and isinstance(conflict_data, dict):
                    if hasattr(self.db_service, 'delete_pending_conflict') and callable(getattr(self.db_service, 'delete_pending_conflict')):
                        await self.db_service.delete_pending_conflict(conflict_id)
                    else:
                        logging.warning(f"DBService missing 'delete_pending_conflict', cannot remove {conflict_id} from DB.")
                else:
                    return {"success": False, "message": f"Conflict {conflict_id} not found or data unusable from DB."}
            else:
                 return {"success": False, "message": f"Conflict {conflict_id} not found and DBService cannot fetch it."}

        if not guild_id_for_conflict or not conflict_data or not isinstance(conflict_data, dict): # Final check
            return {"success": False, "message": f"Conflict {conflict_id} not found or data invalid."}


        conflict_type = conflict_data.get("type", "unknown_type")
        involved_entities = conflict_data.get("involved_entities_data", {})
        if not isinstance(involved_entities, dict): involved_entities = {}


        handler_map: Dict[str, Any] = {
            "battle_player_vs_npc": self._handle_battle_conflict,
            "dialogue_persuasion_check": self._handle_dialogue_conflict,
            "skill_check": self._handle_skill_check_conflict,
            "item_interaction": self._handle_item_interaction_conflict,
            "environmental_hazard": self._handle_environmental_hazard_conflict,
            "faction_dispute": self._handle_faction_conflict,
            "generic_conflict": self._handle_generic_conflict
        }

        handler = handler_map.get(str(conflict_type), self._handle_generic_conflict) # Ensure conflict_type is str

        handler_conflict_data = {k: str(v) if isinstance(v, (int, uuid.UUID)) else v for k,v in involved_entities.items()}
        handler_conflict_data.update(conflict_data)

        return await handler(guild_id_for_conflict, conflict_id, handler_conflict_data, resolution_params)

    async def escalate_for_manual_resolution(self, guild_id: str, conflict_id: str, conflict_type: str,
                                             message: str, context_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"Escalating conflict {conflict_id} ({conflict_type}) for manual GM resolution in guild {guild_id}.")


        if guild_id not in self.pending_manual_resolutions: self.pending_manual_resolutions[guild_id] = {}

        current_record = self.pending_manual_resolutions[guild_id].get(conflict_id, {})
        if not isinstance(current_record, dict): current_record = {} # Ensure it's a dict

        current_record.update({
            "id": conflict_id, "guild_id": guild_id, "type": conflict_type,
            "status": "pending_manual_resolution",
            "escalation_message": message,
            "details_for_master": context_data or current_record.get("details_for_master", {}),
            "timestamp": current_record.get("timestamp") or (await self.rule_engine.get_game_time() if self.rule_engine and hasattr(self.rule_engine, 'get_game_time') and callable(getattr(self.rule_engine, 'get_game_time')) else 'timestamp_unavailable')
        })
        if "involved_entities_data" not in current_record and context_data:
            current_record["involved_entities_data"] = {k:v for k,v in context_data.items() if k.endswith("_id")}

        self.pending_manual_resolutions[guild_id][conflict_id] = current_record

        if hasattr(self.db_service, 'save_pending_conflict') and callable(getattr(self.db_service, 'save_pending_conflict')):
            await self.db_service.save_pending_conflict(guild_id, conflict_id, json.dumps(current_record))
        else:
            logger.error(f"DBService missing 'save_pending_conflict'. Cannot persist escalated conflict {conflict_id} for guild {guild_id}.")


        if self.notification_service and hasattr(self.notification_service, 'notify_master_of_conflict') and callable(getattr(self.notification_service, 'notify_master_of_conflict')):
            await self.notification_service.notify_master_of_conflict(guild_id, conflict_id, conflict_type, message)
        else:
            logger.warning("NotificationService or notify_master_of_conflict method not available.")

        return {"success": False, "message": f"Conflict escalated for GM: {message}", "conflict_id": conflict_id, "status": "pending_manual_resolution"}

    async def load_pending_conflicts_from_db(self, guild_id: str):
        if hasattr(self.db_service, 'get_all_pending_conflicts_for_guild') and callable(getattr(self.db_service, 'get_all_pending_conflicts_for_guild')):
            pending_db_conflicts = await self.db_service.get_all_pending_conflicts_for_guild(guild_id)
            if pending_db_conflicts:
                if guild_id not in self.pending_manual_resolutions:
                    self.pending_manual_resolutions[guild_id] = {}
                for conflict_row in pending_db_conflicts:
                    conflict_id = conflict_row.get("id")
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
                            logger.error(f"Failed to parse conflict_data from DB for conflict {conflict_id} in guild {guild_id}.")
            logger.info(f"Finished loading pending conflicts from DB for guild {guild_id}. Total in memory: {len(self.pending_manual_resolutions.get(guild_id, {}))}")
        else:
            logger.warning(f"DBService missing 'get_all_pending_conflicts_for_guild'. Cannot load pending conflicts for guild {guild_id}.")
