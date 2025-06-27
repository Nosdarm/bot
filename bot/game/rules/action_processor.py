# bot/game/rules/action_processor.py

import json
import traceback
from typing import Dict, Any, Optional, List, TYPE_CHECKING, cast

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character
from bot.game.models.location import Location
from bot.game.models.event import Event # Added for active_events type

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.event_manager import EventManager
    from bot.services.openai_service import OpenAIService
    from bot.game.rules.rule_engine import RuleEngine

from bot.game.rules import skill_rules # Direct import for skill_rules.get_base_dc

class ActionProcessor:
    def __init__(self,
                 character_manager: "CharacterManager",
                 location_manager: "LocationManager",
                 event_manager: "EventManager",
                 rule_engine: "RuleEngine",
                 openai_service: Optional["OpenAIService"] = None,
                 ):
        print("ActionProcessor initialized with managers.")
        self._character_manager = character_manager
        self._location_manager = location_manager
        self._event_manager = event_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service

    async def process(self,
                      game_state: GameState,
                      ctx_channel_id: int,
                      discord_user_id: int,
                      action_type: str,
                      action_data: Dict[str, Any]
                      ) -> Dict[str, Any]:

        error_prefix = "**Мастер:** "
        default_error_msg = f"{error_prefix}Действие '{action_type}' не может быть выполнено из-за внутренней ошибки."

        if not all([self._character_manager, self._location_manager, self._event_manager, self._rule_engine]):
            err_msg = "Основные игровые модули не инициализированы."
            print(f"ActionProcessor: ERROR - {err_msg}")
            return {"success": False, "message": f"{error_prefix}{err_msg}", "target_channel_id": ctx_channel_id, "state_changed": False}

        guild_id = str(game_state.server_id)
        actor_char: Optional[Character] = None
        if hasattr(self._character_manager, 'get_character_by_discord_id') and callable(getattr(self._character_manager, 'get_character_by_discord_id')):
            actor_char = await self._character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)

        if not actor_char or not hasattr(actor_char, 'id'):
            return {"success": False, "message": f"{error_prefix}У вас нет персонажа.", "target_channel_id": ctx_channel_id, "state_changed": False}

        actor_char_id = str(actor_char.id) # Ensure string
        actor_char_name = str(getattr(actor_char, 'name', actor_char_id))


        current_char_loc_id_attr = getattr(actor_char, 'location_id', getattr(actor_char, 'current_location_id', None))
        if not current_char_loc_id_attr:
             return {"success": False, "message": f"{error_prefix}Ваш персонаж в неизвестной локации.", "target_channel_id": ctx_channel_id, "state_changed": False}
        current_char_loc_id = str(current_char_loc_id_attr)

        source_location_data: Optional[Dict[str, Any]] = None
        if hasattr(self._location_manager, 'get_location') and callable(getattr(self._location_manager, 'get_location')):
            source_location_data = await self._location_manager.get_location(location_id=current_char_loc_id, guild_id=guild_id)

        if not source_location_data or not isinstance(source_location_data, dict): # Ensure it's a dict
            return {"success": False, "message": f"{error_prefix}Текущая локация ({current_char_loc_id}) не найдена.", "target_channel_id": ctx_channel_id, "state_changed": False}

        source_loc_name = str(source_location_data.get('name', current_char_loc_id))
        source_loc_id = str(source_location_data.get('id', current_char_loc_id))

        output_channel_id = ctx_channel_id # Default to context channel
        if hasattr(self._location_manager, 'get_location_channel') and callable(getattr(self._location_manager, 'get_location_channel')):
            loc_chan_id = self._location_manager.get_location_channel(guild_id=guild_id, instance_id=source_loc_id)
            if loc_chan_id: output_channel_id = loc_chan_id


        active_events: List[Event] = []
        if hasattr(self._event_manager, 'get_active_events_in_location') and callable(getattr(self._event_manager, 'get_active_events_in_location')):
            active_events_result = await self._event_manager.get_active_events_in_location(guild_id=guild_id, location_id=source_loc_id)
            if active_events_result: active_events = active_events_result

        relevant_event_id: Optional[str] = None
        if action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"] and active_events:
             relevant_event = active_events[0] # Simplistic: pick first event
             if hasattr(relevant_event, 'id'): relevant_event_id = str(relevant_event.id)

        if relevant_event_id and self._event_manager and hasattr(self._event_manager, 'process_player_action_within_event') and callable(getattr(self._event_manager, 'process_player_action_within_event')):
             print(f"Action {action_type} for {actor_char_name} routed to event {relevant_event_id}")
             event_response = await self._event_manager.process_player_action_within_event(relevant_event_id, actor_char_id, action_type, action_data, guild_id, self._character_manager, self._location_manager, self._rule_engine, self._openai_service, ctx_channel_id)
             event_response.setdefault('target_channel_id', output_channel_id)
             event_response.setdefault('state_changed', False)
             return event_response

        print(f"Processing regular action {action_type} for player {actor_char_name} at {source_loc_name}")

        if action_type == "look":
            if not self._openai_service or not hasattr(self._openai_service, 'generate_master_response') or not callable(getattr(self._openai_service, 'generate_master_response')):
                return {"success": False, "message": f"{error_prefix}AI сервис недоступен.", "target_channel_id": output_channel_id, "state_changed": False}

            chars_in_loc: List[Character] = []
            if hasattr(self._character_manager, 'get_characters_in_location') and callable(getattr(self._character_manager, 'get_characters_in_location')):
                chars_in_loc_result = self._character_manager.get_characters_in_location(guild_id=guild_id, location_id=source_loc_id)
                if chars_in_loc_result: chars_in_loc = chars_in_loc_result

            system_prompt = "Ты - Мастер текстовой RPG..." # Truncated for brevity
            user_prompt = f"Опиши локацию для '{actor_char_name}'... Локация '{source_loc_name}', Шаблон: '''{source_location_data.get('description_template')}'''... Активные события: {', '.join([str(e.name) for e in active_events if hasattr(e, 'name')]) if active_events else 'нет'}. Видимые персонажи: {', '.join([str(c.name) for c in chars_in_loc if hasattr(c,'id') and c.id != actor_char_id][:3]) if chars_in_loc else 'нет'}."
            description = await self._openai_service.generate_master_response(system_prompt, user_prompt, 400)
            return {"success": True, "message": f"**Локация:** {source_loc_name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}

        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input: return {"success": False, "message": f"{error_prefix}Укажите направление.", "target_channel_id": ctx_channel_id, "state_changed": False}

            target_loc_data: Optional[Dict[str,Any]] = None
            if hasattr(self._location_manager, 'get_exit_target') and callable(getattr(self._location_manager, 'get_exit_target')):
                target_loc_data = await self._location_manager.get_exit_target(guild_id, source_loc_id, str(destination_input))

            if not target_loc_data and hasattr(self._location_manager, 'find_location_by_name_or_id') and callable(getattr(self._location_manager, 'find_location_by_name_or_id')):
                 target_loc_data = await self._location_manager.find_location_by_name_or_id(guild_id, str(destination_input))
                 if target_loc_data:
                      current_exits = source_location_data.get('exits', [])
                      if not any(isinstance(ex,dict) and ex.get("target_location_id") == target_loc_data.get('id') for ex in current_exits):
                          return {"success": False, "message": f"{error_prefix}Прямого пути к '{target_loc_data.get('name', destination_input)}' нет.", "target_channel_id": output_channel_id, "state_changed": False}

            if not target_loc_data or not isinstance(target_loc_data, dict) or not target_loc_data.get('id'):
                return {"success": False, "message": f"{error_prefix}Неизвестное направление: '{destination_input}'.", "target_channel_id": output_channel_id, "state_changed": False}

            target_loc_id = str(target_loc_data['id'])
            target_loc_name = str(target_loc_data.get('name', target_loc_id))

            if hasattr(self._character_manager, 'update_character_location') and callable(getattr(self._character_manager, 'update_character_location')):
                await self._character_manager.update_character_location(character_id=actor_char_id, location_id=target_loc_id, guild_id=guild_id, context=action_data) # type: ignore[call-arg] # context is fine if method accepts **kwargs
            else: return {"success": False, "message": f"{error_prefix}Система перемещения недоступна.", "target_channel_id": output_channel_id, "state_changed": False}

            description = f"Вы прибыли в {target_loc_name}." # Fallback
            if self._openai_service and hasattr(self._openai_service, 'generate_master_response'):
                # Prompts truncated for brevity
                description = await self._openai_service.generate_master_response("Мастер RPG...", f"'{actor_char_name}' перемещается из '{source_loc_name}' в '{target_loc_name}'. Опиши.", 200)

            dest_chan_id = output_channel_id # Default
            if hasattr(self._location_manager, 'get_location_channel') and callable(getattr(self._location_manager, 'get_location_channel')):
                new_chan_id = self._location_manager.get_location_channel(guild_id, target_loc_id)
                if new_chan_id: dest_chan_id = new_chan_id
            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": dest_chan_id, "state_changed": True}

        elif action_type == "skill_check":
            skill_name = action_data.get("skill_name")
            if not skill_name: return {"success": False, "message": f"{error_prefix}Укажите навык.", "target_channel_id": ctx_channel_id, "state_changed": False}

            actor_skills = getattr(actor_char, 'skills', {}) # Assuming skills is a dict on Pydantic Character
            if not isinstance(actor_skills, dict) or skill_name not in actor_skills:
                 return {"success": False, "message": f"{error_prefix}У вас нет навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

            base_dc = skill_rules.get_base_dc(str(skill_name), target_level=None, context=action_data)

            check_result: Optional[Dict[str, Any]] = None
            if hasattr(self._rule_engine, 'perform_check') and callable(getattr(self._rule_engine, 'perform_check')):
                check_result = await self._rule_engine.perform_check(guild_id, actor_char, str(skill_name), base_dc, action_data.get("modifiers", {}))

            if not check_result: return {"success": False, "message": f"{error_prefix}Ошибка проверки навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

            description = f"Результат {skill_name}: {check_result.get('outcome', 'неизвестно')}." # Fallback
            if self._openai_service and hasattr(self._openai_service, 'generate_master_response'):
                # Prompts truncated
                description = await self._openai_service.generate_master_response("Мастер RPG...", f"'{actor_char_name}' (Навыки: {list(actor_skills.keys())}) попытался {action_data.get('target_description', 'что-то')}, используя '{skill_name}'. Результат: {json.dumps(check_result)}. Опиши.", 300)

            mech_summary = str(check_result.get("description", "Проверка выполнена."))
            state_changed_flag = bool(check_result.get("is_critical_failure", False))
            return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed_flag}

        else:
            return {"success": False, "message": f"{error_prefix}Действие '{action_type}' не поддерживается.", "target_channel_id": ctx_channel_id, "state_changed": False}
