from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock # For placeholder if i18n_utils is not available

# Assuming managers and i18n_utils are importable
# from bot.game.managers.character_manager import CharacterManager
# from bot.game.managers.npc_manager import NpcManager
# from bot.game.managers.item_manager import ItemManager
# import bot.utils.i18n_utils as i18n_utils # Direct module import
import json # For parsing description_params_json

# Placeholder for actual imports if not available in subtask environment
CharacterManager = Any
NpcManager = Any
ItemManager = Any
i18n_utils_actual_module = None # Will be replaced by actual import or remain None
import json # Added for format_comparison_report fallback

try:
    import bot.utils.i18n_utils as i18n_utils_module_loader
    i18n_utils_actual_module = i18n_utils_module_loader
except ImportError:
    print("Warning: bot.utils.i18n_utils module not found. ReportFormatter will use a mock.")
    i18n_utils_actual_module = MagicMock()


class I18nUtilsWrapper:
    def __init__(self, i18n_module: Any, default_lang: str = "en"):
        self.module = i18n_module
        self.default_lang = default_lang
        if not hasattr(self.module, 'get_localized_string'):
            # If the actual module was loaded but doesn't have the function, make it a mock for safety.
            if not isinstance(self.module, MagicMock):
                print(f"Warning: i18n_module ({type(i18n_module)}) missing 'get_localized_string'. Using mock behavior.")
                self.module = MagicMock()


    def get_localized_string(self, key: str, lang: str, **kwargs: Any) -> str:
        if hasattr(self.module, 'get_localized_string') and not isinstance(self.module, MagicMock):
            try:
                # Pass default_lang to actual utility if it supports it
                if "default_lang" in self.module.get_localized_string.__code__.co_varnames:
                    return self.module.get_localized_string(key, lang, default_lang=self.default_lang, **kwargs)
                else:
                    return self.module.get_localized_string(key, lang, **kwargs) # type: ignore
            except Exception as e:
                print(f"Error calling actual i18n_utils.get_localized_string: {e}")

        # Fallback for testing or if module/function not fully available
        formatted_args = ", ".join([f"{k}={v}" for k,v in kwargs.items()])
        return f"i18n[{lang}]:{key} ({formatted_args})" if kwargs else f"i18n[{lang}]:{key}"


class ReportFormatter:
    def __init__(
        self,
        character_manager: CharacterManager,
        npc_manager: NpcManager,
        item_manager: Optional[ItemManager] = None,
        i18n_module: Optional[Any] = i18n_utils_actual_module # Use loaded or mock module
    ):
        self.character_manager = character_manager
        self.npc_manager = npc_manager
        self.item_manager = item_manager

        # Initialize i18n wrapper
        self.i18n = I18nUtilsWrapper(i18n_module)
        if isinstance(i18n_module, MagicMock):
             # This check is mostly for when the global i18n_utils_actual_module itself is a MagicMock
             print("Warning: ReportFormatter initialized with a mock i18n module via default parameter.")


    async def _get_entity_name(self, entity_id: Optional[str], entity_type: Optional[str], lang: str, guild_id: Optional[str]) -> Optional[str]:
        """ Helper to fetch entity name based on type, now requiring guild_id. """
        if not entity_id or not entity_type:
            return None

        name = entity_id

        if not guild_id: # Required for most manager calls
            print(f"Warning: _get_entity_name called without guild_id for {entity_type} {entity_id}. Name resolution may fail.")
            # Depending on manager implementation, some might work with None guild_id if IDs are globally unique
            # but it's safer to require it.

        try:
            if entity_type.upper() == "PLAYER" and self.character_manager:
                # Assuming CharacterManager.get_character takes guild_id and character_id
                char = await self.character_manager.get_character(guild_id, entity_id)
                if char:
                    if hasattr(char, 'name_i18n') and isinstance(char.name_i18n, dict):
                         name = char.name_i18n.get(lang, char.name_i18n.get(self.i18n.default_lang, char.id))
                    elif hasattr(char, 'name'): # Fallback to simple name attribute
                         name = char.name
            elif entity_type.upper() == "NPC" and self.npc_manager:
                npc = await self.npc_manager.get_npc(guild_id, entity_id)
                if npc:
                    if hasattr(npc, 'name_i18n') and isinstance(npc.name_i18n, dict):
                        name = npc.name_i18n.get(lang, npc.name_i18n.get(self.i18n.default_lang, npc.id))
                    elif hasattr(npc, 'name'):
                        name = npc.name
            elif entity_type.upper() == "ITEM" and self.item_manager:
                item = await self.item_manager.get_item_template_by_id(entity_id)
                if item:
                    if hasattr(item, 'name_i18n') and isinstance(item.name_i18n, dict):
                        name = item.name_i18n.get(lang, item.name_i18n.get(self.i18n.default_lang, item.id))
                    elif hasattr(item, 'name'):
                        name = item.name
            # Add more entity types (FACTION, LOCATION, etc.) if needed
        except Exception as e:
            print(f"Error fetching name for {entity_type} {entity_id} in guild {guild_id}: {e}")
        return name


    async def format_story_log_entry(self, log_entry_row: Dict[str, Any], lang: str) -> str:
        base_description = "An event occurred." # Fallback
        description_key = log_entry_row.get('description_key')
        description_params_json = log_entry_row.get('description_params_json')

        params_for_i18n: Dict[str, Any] = {}
        if description_params_json:
            try:
                params_for_i18n = json.loads(description_params_json)
                if not isinstance(params_for_i18n, dict): # Ensure it's a dict after loading
                    print(f"Warning: Parsed description_params_json is not a dict: {params_for_i18n}")
                    params_for_i18n = {"raw_params": str(description_params_json)} # Fallback
            except json.JSONDecodeError:
                print(f"Warning: Could not parse description_params_json: {description_params_json}")
                params_for_i18n = {"raw_params": str(description_params_json)}

        current_guild_id = log_entry_row.get("guild_id") # Crucial for _get_entity_name

        source_id = log_entry_row.get('source_entity_id')
        source_type = log_entry_row.get('source_entity_type')
        if source_id and source_type: # Only add if both are present
            source_name = await self._get_entity_name(source_id, source_type, lang, current_guild_id)
            params_for_i18n['source_name'] = source_name or source_id # Use ID as fallback if name not found
        elif source_id: # If only ID is present
             params_for_i18n['source_name'] = source_id


        target_id = log_entry_row.get('target_entity_id')
        target_type = log_entry_row.get('target_entity_type')
        if target_id and target_type: # Only add if both are present
            target_name = await self._get_entity_name(target_id, target_type, lang, current_guild_id)
            params_for_i18n['target_name'] = target_name or target_id # Use ID as fallback
        elif target_id: # If only ID is present
            params_for_i18n['target_name'] = target_id


        if description_key:
            base_description = self.i18n.get_localized_string(
                description_key,
                lang,
                **params_for_i18n
            )
        elif params_for_i18n.get('source_name'): # Generic message if no key but we have a source
            target_part = f" involving {params_for_i18n['target_name']}" if params_for_i18n.get('target_name') else ""
            base_description = f"{params_for_i18n['source_name']} did something{target_part}."

        ai_narrative = None
        details_str = log_entry_row.get('details')
        if details_str:
            details_data = {}
            if isinstance(details_str, str):
                try:
                    details_data = json.loads(details_str)
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse log entry details JSON: {details_str}")
            elif isinstance(details_str, dict):
                details_data = details_str

            narrative_key = f'ai_narrative_{lang}'
            narrative_error_key = f'ai_narrative_{lang}_error'

            # Try to get narrative for the requested language
            if narrative_key in details_data:
                ai_narrative = details_data[narrative_key]
            # Fallback to default language narrative if specific lang not found
            elif f'ai_narrative_{self.i18n.default_lang}' in details_data:
                ai_narrative = details_data[f'ai_narrative_{self.i18n.default_lang}']
            # If there was an error generating narrative for the requested lang, show it
            elif narrative_error_key in details_data:
                ai_narrative = f"(Narrative generation error: {details_data[narrative_error_key]})"
            # Fallback to error for default language if specific lang error not found
            elif f'ai_narrative_{self.i18n.default_lang}_error' in details_data:
                ai_narrative = f"(Narrative generation error for {self.i18n.default_lang}: {details_data[f'ai_narrative_{self.i18n.default_lang}_error']})"


        if ai_narrative:
            return f"{base_description} {ai_narrative}"
        else:
            return base_description

    async def generate_turn_report(self, guild_id: str, lang: str, recent_log_entries: List[Dict[str, Any]]) -> str:
        if not recent_log_entries:
            return self.i18n.get_localized_string("report.nothing_happened", lang)

        report_lines = []
        for log_entry in recent_log_entries:
            if 'guild_id' not in log_entry and guild_id:
                log_entry['guild_id'] = guild_id

            formatted_line = await self.format_story_log_entry(log_entry, lang)
            report_lines.append(formatted_line)

        return "\n".join(report_lines)


# New SimpleReportFormatter class, adapted from gm_app_cmds.py
class SimpleReportFormatter:
    def __init__(self, game_mngr: Any, guild_id: str): # Use Any for GameManager to avoid circular import if GameManager imports this
        self.game_mngr = game_mngr
        self.guild_id = guild_id
        # In a real scenario, ensure i18n utilities are properly accessible here
        # For now, direct string formatting or a placeholder for i18n.
        # from bot.utils.i18n_utils import get_i18n_text as i18n_get_text_util # Example
        # self.i18n_get_text = i18n_get_text_util

    def _get_entity_name(self, entity_id: str, entity_type: str, lang: str = "en") -> str:
        if not self.game_mngr or not self.guild_id:
            return f"{entity_type} ID: {entity_id}"

        name, res_name = entity_id, entity_id
        try:
            if entity_type.lower() == 'character' and hasattr(self.game_mngr, 'character_manager') and self.game_mngr.character_manager:
                char = self.game_mngr.character_manager.get_character(self.guild_id, entity_id)
                if char:
                    res_name = (char.name_i18n.get(lang, char.name_i18n.get("en", char.id))
                                if hasattr(char, 'name_i18n') and char.name_i18n else getattr(char, "name", char.id))
            elif entity_type.lower() == 'npc' and hasattr(self.game_mngr, 'npc_manager') and self.game_mngr.npc_manager:
                npc = self.game_mngr.npc_manager.get_npc(self.guild_id, entity_id)
                if npc:
                    res_name = (npc.name_i18n.get(lang, npc.name_i18n.get("en", npc.id))
                                if hasattr(npc, 'name_i18n') and npc.name_i18n else getattr(npc, "name", npc.id))
            elif entity_type.lower() == 'location' and hasattr(self.game_mngr, 'location_manager') and self.game_mngr.location_manager:
                loc = self.game_mngr.location_manager.get_location_instance(self.guild_id, entity_id)
                if loc:
                    res_name = (loc.name_i18n.get(lang, loc.name_i18n.get("en", loc.id))
                                if hasattr(loc, 'name_i18n') and loc.name_i18n else getattr(loc, "name", loc.id))
            name = res_name if res_name != entity_id else entity_id
        except Exception as e:
            print(f"SimpleReportFormatter._get_entity_name error for {entity_type} {entity_id} in guild {self.guild_id}: {e}")
        return f"{name} (`{entity_id}`)"

    def format_battle_report(self, report_data: Dict[str, Any], lang: str = "en") -> str:
        lines = [
            f"**Battle Report (ID: {report_data.get('battle_instance_id', 'N/A')})**",
            f"Winning Team: {report_data.get('winning_team', 'N/A')}",
            f"Total Rounds: {report_data.get('total_rounds', 0)}",
            "\n**Participants Summary:**"
        ]
        participants_summary = report_data.get('participants_summary', [])
        if not participants_summary:
            lines.append("No participant data available.")
        for p_summary in participants_summary:
            p_name = self._get_entity_name(p_summary.get('id', '?'), p_summary.get('type', '?'), lang)
            lines.append(
                f"- {p_name} (Team {p_summary.get('team', '?')}, Type: {p_summary.get('type', '?')}) | "
                f"Survived: {p_summary.get('survived', False)} | "
                f"HP: {p_summary.get('hp_remaining', 0)}/{p_summary.get('max_hp', 0)} | "
                f"Damage Dealt: {p_summary.get('damage_dealt', 0)}"
            )
        return "\n".join(lines)

    def format_quest_report(self, report_data: Dict[str, Any], lang: str = "en") -> str:
        # Assuming quest_id in report_data refers to a template_id that might have i18n name
        quest_template_id = report_data.get('quest_id', 'Unknown Quest')
        quest_name = quest_template_id # Fallback
        if hasattr(self.game_mngr, 'quest_manager') and self.game_mngr.quest_manager:
            q_tpl = self.game_mngr.quest_manager.get_quest_definition(self.guild_id, quest_template_id)
            if q_tpl and hasattr(q_tpl, 'name_i18n') and isinstance(q_tpl.name_i18n, dict):
                quest_name = q_tpl.name_i18n.get(lang, q_tpl.name_i18n.get("en", quest_template_id))
            elif q_tpl and hasattr(q_tpl, 'name'):
                 quest_name = q_tpl.name


        lines = [
            f"**Quest Report (Simulation ID: {report_data.get('simulation_instance_id', 'N/A')})**",
            f"Quest: {quest_name} (`{quest_template_id}`)",
            f"Final Status: {report_data.get('final_status', 'N/A')}",
            f"Stages Simulated: {report_data.get('stages_simulated_count', 0)}",
            f"Final Stage Reached: {report_data.get('final_stage_reached', 'N/A')}"
        ]
        # Add more details if present in report_data, e.g., outcomes, rewards
        return "\n".join(lines)

    def format_action_consequence_report(self, report_data: List[Dict[str, Any]], lang: str = "en") -> str:
        lines = ["**Action Consequence Analysis**"]
        if not report_data:
            lines.append("No consequence data available.")
            return "\n".join(lines)

        for i, outcome in enumerate(report_data):
            if outcome.get("error"):
                lines.append(f"\n**Outcome {i+1} (Error):** {outcome.get('error_message', 'Unknown error')}")
                continue

            lines.append(f"\n**Outcome {i+1}:** Likelihood: {outcome.get('likelihood', 'N/A')}")
            # Assuming description might be an i18n key or already localized
            lines.append(f"  Description: {outcome.get('description', 'N/A')}")

            state_changes = outcome.get('state_changes')
            if state_changes and isinstance(state_changes, dict):
                lines.append("  Changes:")
                for k, v in state_changes.items():
                    lines.append(f"    - {k}: {v}")

            tags = outcome.get('tags')
            if tags and isinstance(tags, list):
                lines.append(f"  Tags: {', '.join(tags)}")
        return "\n".join(lines)

    def format_generic_report(self, report_data: Any, lang: str = "en") -> str:
        # Fallback for unknown report types or when detailed formatting is not available
        try:
            return f"```json\n{json.dumps(report_data, indent=2, ensure_ascii=False)}\n```"
        except TypeError:
            return f"```\n{str(report_data)}\n```"

    def format_comparison_report(self, comparison_details: Dict[str, Any], sim_type: str, lang: str = "en") -> str:
        lines = [f"**Comparison Report for {sim_type.capitalize()} Simulations**\n"]

        error = comparison_details.get("error")
        if error:
            lines.append(f"Error: {error}")
            return "\n".join(lines)

        report1_metrics = comparison_details.get("report_1_metrics", {})
        report2_metrics = comparison_details.get("report_2_metrics", {})
        diff_metrics = comparison_details.get("diff", {})

        lines.append(f"Report 1 ID: {comparison_details.get('report_id_1', 'N/A')}")
        lines.append(f"Report 2 ID: {comparison_details.get('report_id_2', 'N/A')}\n")

        if sim_type == "battle":
            lines.append("**Battle Metrics Comparison:**")
            # Common metrics
            lines.append(f"- Winning Team: R1: {report1_metrics.get('winning_team', 'N/A')} | R2: {report2_metrics.get('winning_team', 'N/A')}")
            lines.append(f"- Total Rounds: R1: {report1_metrics.get('total_rounds', 'N/A')} | R2: {report2_metrics.get('total_rounds', 'N/A')}")

            # Diff section for battle
            if diff_metrics:
                lines.append("\n**Differences:**")
                for key, value_diff in diff_metrics.items():
                    lines.append(f"- {key.replace('_', ' ').capitalize()}: R1: {value_diff.get('report_1')} | R2: {value_diff.get('report_2')}")

            # Could add more detailed sections for participant summaries if needed
            # E.g. comparing survivor counts, total damage by team etc.

        elif sim_type == "quest":
            lines.append("**Quest Metrics Comparison:**")
            lines.append(f"- Final Status: R1: {report1_metrics.get('final_status', 'N/A')} | R2: {report2_metrics.get('final_status', 'N/A')}")
            lines.append(f"- Stages Simulated: R1: {report1_metrics.get('stages_simulated_count', 'N/A')} | R2: {report2_metrics.get('stages_simulated_count', 'N/A')}")
            lines.append(f"- Final Stage Reached: R1: {report1_metrics.get('final_stage_reached', 'N/A')} | R2: {report2_metrics.get('final_stage_reached', 'N/A')}")
            if diff_metrics:
                lines.append("\n**Differences:**")
                for key, value_diff in diff_metrics.items():
                     lines.append(f"- {key.replace('_', ' ').capitalize()}: R1: {value_diff.get('report_1')} | R2: {value_diff.get('report_2')}")

        elif sim_type == "action_consequence":
            lines.append("**Action Consequence Comparison:**")
            # Comparing lists of outcomes can be complex. This is a simplified version.
            # It might list outcomes side-by-side or highlight differing numbers of outcomes.
            outcomes1 = report1_metrics.get("outcomes", [])
            outcomes2 = report2_metrics.get("outcomes", [])
            lines.append(f"- Number of Outcomes: R1: {len(outcomes1)} | R2: {len(outcomes2)}")
            # Could try to compare outcomes if they have unique IDs or matching descriptions.
            # For now, just showing counts.
            if diff_metrics.get("outcome_count_diff") is not None:
                 lines.append(f"  - Difference in outcome count: {diff_metrics.get('outcome_count_diff')}")
            # A more detailed comparison would involve iterating through outcomes and matching them.

        else:
            lines.append(f"Comparison formatting for simulation type '{sim_type}' is not fully implemented.")
            lines.append(f"Report 1 Data: {json.dumps(report1_metrics, indent=2, ensure_ascii=False)}")
            lines.append(f"Report 2 Data: {json.dumps(report2_metrics, indent=2, ensure_ascii=False)}")

        return "\n".join(lines)

# Ensure GameManager type hint is forward-referenced if defined later or in a different module not directly imported
# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
#     from bot.game.managers.game_manager import GameManager
