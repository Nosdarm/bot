# bot/game/action_processor.py
import json
from typing import Dict, Any, Optional, List, Tuple # Added List and Tuple

# Import models
from bot.game.models.game_state import GameState
# Unused: from bot.game.models.character import Character
# Unused: from bot.game.models.location import Location

# Import managers
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.event_manager import EventManager
from bot.game.managers.game_log_manager import GameLogManager

# Import other managers if needed (e.g. for action_type = "combat")
# from bot.game.managers.npc_manager import NpcManager


# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine
from bot.game.rules import skill_rules


class ActionProcessor:
    def __init__(self):
        print("ActionProcessor initialized.")

    async def process(self,
                      game_state: GameState,
                      char_manager: Optional[CharacterManager],
                      loc_manager: Optional[LocationManager],
                      event_manager: Optional[EventManager],
                      rule_engine: Optional[RuleEngine],
                      openai_service: Optional[OpenAIService],
                      game_log_manager: Optional[GameLogManager], # Added
                      ctx_channel_id: int,
                      discord_user_id: int,
                      action_type: str,
                      action_data: Dict[str, Any]
                      ) -> Dict[str, Any]:
        """
        Processes a player action. Determines target, calls rules/managers, involves event manager,
        uses AI for narrative, and returns structured response data including message and target channel.
        Receives all necessary managers, services, and context for the specific action.
        Returns: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # --- Initial Checks (Same) ---
        if not char_manager:
            return {"success": False, "message": "**Мастер:** Менеджер персонажей недоступен.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # Ensure discord_user_id is string for get_character_by_discord_id if it expects string
        character = await char_manager.get_character_by_discord_id(str(game_state.server_id), str(discord_user_id))
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        guild_id_str_process = str(game_state.server_id)

        if not loc_manager:
            return {"success": False, "message": "**Мастер:** Менеджер локаций недоступен.", "target_channel_id": ctx_channel_id, "state_changed": False}

        current_location_id = getattr(character, 'current_location_id', None)
        if not current_location_id: # Check if current_location_id is None before using it
             return {"success": False, "message": "**Мастер:** Ваш персонаж не имеет текущей локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        location = await loc_manager.get_location_instance(guild_id_str_process, current_location_id)
        if not location:
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        location_name = getattr(location, 'name_i18n', {}).get(character.selected_language or 'en', 'Неизвестная локация')
        location_description_template = getattr(location, 'description_i18n', {}).get(character.selected_language or 'en', 'Пустота...')


        # Use a method on loc_manager to get the channel ID, or fallback
        output_channel_id_obj = getattr(loc_manager, 'get_location_channel_id', None)
        output_channel_id = ctx_channel_id # Default to context channel
        if callable(output_channel_id_obj):
            resolved_channel_id = await output_channel_id_obj(guild_id_str_process, location.id)
            if resolved_channel_id:
                output_channel_id = resolved_channel_id


        if not event_manager:
            active_events = []
            relevant_event_id = None
        else:
            # Ensure get_active_events_in_location is callable and awaited
            get_active_events_method = getattr(event_manager, 'get_active_events_in_location', None)
            active_events = []
            if callable(get_active_events_method):
                active_events_result = get_active_events_method(guild_id_str_process, location.id)
                if asyncio.iscoroutine(active_events_result):
                    active_events = await active_events_result
                else:
                    active_events = active_events_result if isinstance(active_events_result, list) else []

            relevant_event_id = None
            is_potentially_event_interactive = action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"]
            if is_potentially_event_interactive and active_events:
                 relevant_event_id = getattr(active_events[0], 'id', None) # Safe access

        if relevant_event_id and event_manager:
            character_name = getattr(character, 'name_i18n', {}).get(character.selected_language or 'en', 'Неизвестный персонаж')
            print(f"Action {action_type} for {character_name} routed to event {relevant_event_id}.")

            process_event_action_method = getattr(event_manager, 'process_player_action_within_event', None)
            if callable(process_event_action_method):
                event_response = await process_event_action_method(
                    event_id=relevant_event_id,
                    player_id=str(character.id), # Ensure string
                    action_type=action_type,
                    action_data=action_data,
                    guild_id=guild_id_str_process,
                    character_manager=char_manager,
                    loc_manager=loc_manager,
                    rule_engine=rule_engine,
                    openai_service=openai_service,
                    ctx_channel_id=ctx_channel_id,
                )
                if 'target_channel_id' not in event_response or event_response['target_channel_id'] is None:
                    event_response['target_channel_id'] = output_channel_id
                if 'state_changed' not in event_response:
                    event_response['state_changed'] = False
                return event_response
            else:
                logger.warning(f"EventManager is missing 'process_player_action_within_event' method.")
                # Fall through to regular processing if method is missing

        print(f"Processing regular action '{action_type}' for player '{getattr(character, 'name', 'N/A')}' at '{location_name}'.")


        if action_type == "look":
            if not openai_service:
                return {"success": False, "message": "**Мастер:** Сервис AI недоступен для генерации описания.", "target_channel_id": output_channel_id, "state_changed": False}
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."

            active_event_names = [getattr(e, 'name_i18n', {}).get(character.selected_language or 'en', 'активное событие') for e in active_events] if active_events else ['нет']

            # Fetch visible characters/NPCs correctly
            visible_chars_list = []
            if char_manager and hasattr(char_manager, 'get_characters_in_location'):
                chars_in_loc_result = char_manager.get_characters_in_location(guild_id=guild_id_str_process, location_id=location.id)
                if asyncio.iscoroutine(chars_in_loc_result): chars_in_loc_result = await chars_in_loc_result
                if isinstance(chars_in_loc_result, list):
                    visible_chars_list = [
                        getattr(c, 'name_i18n', {}).get(character.selected_language or 'en', getattr(c, 'id', 'неизвестный'))
                        for c in chars_in_loc_result if getattr(c, 'id', None) != character.id
                    ][:3]

            user_prompt_tuple = (
                f"Опиши локацию для персонажа '{getattr(character, 'name', 'N/A')}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location_name}', ",
                f"Шаблон описания: '''{location_description_template[:200]}'''. "
                f"Активные события здесь: {', '.join(active_event_names)}. "
                f"Видимые персонажи/NPC (пример): {', '.join(visible_chars_list) if visible_chars_list else 'нет'}. "
            )
            user_prompt_str = "".join(user_prompt_tuple) # Join tuple elements into a single string

            description = await openai_service.generate_master_response(
                system_prompt=system_prompt, user_prompt=user_prompt_str, max_tokens=400
            )
            return {"success": True, "message": f"**Локация:** {location_name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}

        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            get_exit_target_method = getattr(loc_manager, 'get_exit_target', None)
            target_location_pydantic = None
            if callable(get_exit_target_method):
                 target_location_pydantic = await get_exit_target_method(guild_id_str_process, location.id, destination_input)

            if not target_location_pydantic:
                return {"success": False, "message": f"**Мастер:** Неизвестное направление или путь: '{destination_input}'. Отсюда туда нельзя попасть.", "target_channel_id": output_channel_id, "state_changed": False}

            update_char_loc_method = getattr(char_manager, 'update_character_location', None)
            if callable(update_char_loc_method):
                await update_char_loc_method(str(character.id), str(target_location_pydantic.id), guild_id_str_process)
            else:
                logger.error("CharacterManager.update_character_location method not found or not callable.")
                return {"success": False, "message": "**Мастер:** Ошибка при обновлении локации персонажа.", "target_channel_id": output_channel_id, "state_changed": False}


            exit_description_for_prompt = destination_input
            location_exits = getattr(location, 'exits', [])
            if isinstance(location_exits, list):
                found_exit = next((exit_obj for exit_obj in location_exits if isinstance(exit_obj, dict) and exit_obj.get("target_location_id") == target_location_pydantic.id), None)
                if found_exit:
                    exit_direction = found_exit.get("direction_i18n", {}).get(character.selected_language or 'en')
                    if exit_direction: exit_description_for_prompt = exit_direction

            target_location_name = getattr(target_location_pydantic, 'name_i18n', {}).get(character.selected_language or 'en', 'Неизвестная локация')
            target_location_desc_template = getattr(target_location_pydantic, 'description_i18n', {}).get(character.selected_language or 'en', '...')


            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt_tuple_move = (
                f"Персонаж '{getattr(character, 'name', 'N/A')}' перемещается из локации '{location_name}' "
                f"через '{exit_description_for_prompt}' в локацию '{target_location_name}'. "
                f"Краткое описание начальной локации: {location_description_template[:150]}. "
                f"Краткое описание конечной локации: {target_location_desc_template[:150]}. "
                f"Опиши краткое путешествие и прибытие в '{target_location_name}'. "
                f"Будь атмосферным и мрачным. В конце явно укажи, что персонаж теперь "
                f"находится в '{target_location_name}'."
            )
            user_prompt_str_move = "".join(user_prompt_tuple_move)

            if not openai_service:
                description = f"Вы прибыли в {target_location_name}."
            else:
                description = await openai_service.generate_master_response(
                    system_prompt=system_prompt, user_prompt=user_prompt_str_move, max_tokens=250
                )

            final_output_channel_id = output_channel_id # Default to current location's channel
            if callable(output_channel_id_obj): # output_channel_id_obj is loc_manager.get_location_channel_id
                dest_channel_id_val = await output_channel_id_obj(guild_id_str_process, target_location_pydantic.id)
                if dest_channel_id_val:
                    final_output_channel_id = dest_channel_id_val


            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": final_output_channel_id, "state_changed": True}

        elif action_type == "skill_check":
            skill_name = action_data.get("skill_name")
            complexity = action_data.get("complexity", "medium")
            base_modifiers = action_data.get("modifiers", {})
            target_description = action_data.get("target_description", "чего-то")
            final_modifiers = {**base_modifiers} # Simplified for now

            if not skill_name:
                return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}

            character_skills = getattr(character, 'skills_data', []) # Pydantic Character.skills_data is List[Dict]
            if not isinstance(character_skills, list) or not any(s.get('skill_id') == skill_name for s in character_skills if isinstance(s, dict)):
                return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

            base_dc = skill_rules.get_base_dc(complexity)

            if not rule_engine:
                return {"success": False, "message": "**Мастер:** Движок правил недоступен для проверки навыка.", "target_channel_id": ctx_channel_id, "state_changed": False}

            perform_check_method = getattr(rule_engine, 'resolve_skill_check', None) # Changed to resolve_skill_check
            if not callable(perform_check_method):
                 logger.error("RuleEngine.resolve_skill_check method not found or not callable.")
                 return {"success": False, "message": "**Мастер:** Ошибка конфигурации движка правил.", "target_channel_id": ctx_channel_id, "state_changed": False}

            check_result = await perform_check_method( # Assuming resolve_skill_check is async
                character=character, # Pass the Pydantic Character model instance
                skill_name=skill_name,
                base_dc=base_dc,
                modifiers=final_modifiers,
                guild_id=guild_id_str_process
            )


            if not check_result: # check_result is now CheckResult object or similar
                return {"success": False, "message": f"**Мастер:** Произошла ошибка при выполнении проверки навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # Extract values from CheckResult object safely
            roll_val = getattr(check_result, 'roll', 'N/A')
            total_value_val = getattr(check_result, 'total_value', 'N/A')
            dc_val = getattr(check_result, 'dc', 'N/A')
            is_success_val = getattr(check_result, 'succeeded', False) # Assuming 'succeeded' attribute
            is_critical_success_val = getattr(check_result, 'is_critical_success', False)
            is_critical_failure_val = getattr(check_result, 'is_critical_failure', False)
            description_from_check = getattr(check_result, 'description', "Проверка выполнена.")


            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай действия и их результаты детализированно и атмосферно."

            char_skills_list = [s.get('skill_id') for s in character_skills if isinstance(s, dict) and s.get('skill_id')]
            # Assuming character.stats_json is a string that needs parsing or character.stats is a dict
            char_stats_dict = {}
            if hasattr(character, 'effective_stats_json') and isinstance(character.effective_stats_json, str):
                try: char_stats_dict = json.loads(character.effective_stats_json)
                except json.JSONDecodeError: pass
            elif hasattr(character, 'stats') and isinstance(character.stats, dict): # Fallback to base stats if effective not available
                char_stats_dict = character.stats


            user_prompt_tuple_skill = (
                f"Персонаж '{getattr(character, 'name', 'N/A')}' (Навыки: {char_skills_list}, "
                f"Статы: {list(char_stats_dict.keys())}) "
                f"попытался совершить действие, связанное с навыком '{skill_name}', "
                f"целью было {target_description}. "
                f"Ситуация: локация '{location_name}', "
                f"атмосферное описание: {location_description_template[:150]}...\n"
                f"Механический результат проверки: Успех={is_success_val}, Крит. успех={is_critical_success_val}, Крит. провал={is_critical_failure_val}, Бросок={roll_val}, Итог={total_value_val} против DC={dc_val}.\n"
                f"Опиши, КАК это выглядело и ощущалось в мире. "
                f"Учитывай результат и контекст. Будь мрачным и детализированным."
            )
            user_prompt_str_skill = "".join(user_prompt_tuple_skill)

            if not openai_service:
                description = "Результат проверки навыка получен."
            else:
                description = await openai_service.generate_master_response(
                    system_prompt=system_prompt, user_prompt=user_prompt_str_skill, max_tokens=300
                )

            state_changed = is_critical_failure_val

            if game_log_manager:
                log_details_skill_check = {
                    "skill_name": skill_name, "complexity": complexity, "base_dc": base_dc,
                    "modifiers_applied": final_modifiers, "roll_result": roll_val,
                    "total_with_bonus": total_value_val, "dc_target": dc_val,
                    "is_success": is_success_val, "is_critical_success": is_critical_success_val,
                    "is_critical_failure": is_critical_failure_val,
                    "description_generated": description,
                    "target_description_input": target_description
                }
                log_message_params_skill_check = {
                    "player_id": str(character.id), "skill_name": skill_name,
                    "outcome": "success" if is_success_val else "failure"
                }
                log_event_method = getattr(game_log_manager, 'log_event', None)
                if callable(log_event_method):
                    await log_event_method(
                        guild_id=guild_id_str_process, player_id=str(character.id),
                        party_id=getattr(character, 'current_party_id', None),
                        location_id=location.id, event_type="SKILL_CHECK_ACTION",
                        message_key="log.action.skill_check", # Ensure this key exists in i18n
                        message_params=log_message_params_skill_check,
                        details=log_details_skill_check, channel_id=str(output_channel_id)
                    )
                else:
                    logger.warning("GameLogManager.log_event method not found or not callable.")

            return {"success": True, "message": f"_{description_from_check}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed}

        # --- Add Handlers for other core Action Types (placeholder) ---
        # elif action_type == "interact": ...
        # elif action_type == "attack": ...
        # elif action_type == "use_item": ...
        # elif action_type == "craft": ...

        # Placeholder response for unhandled action types
        print(f"Action type '{action_type}' not handled by any specific processor.")
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается.", "target_channel_id": ctx_channel_id, "state_changed": False}

    async def process_party_actions(self,
                                   game_state: GameState,
                                   char_manager: Optional[CharacterManager],
                                   loc_manager: Optional[LocationManager],
                                   event_manager: Optional[EventManager],
                                   rule_engine: Optional[RuleEngine],
                                   openai_service: Optional[OpenAIService],
                                   # game_log_manager: Optional[GameLogManager], # Already in process, consider if needed here
                                   party_actions_data: List[tuple[str, str]], # List of (char_id, actions_json_str)
                                   ctx_channel_id_fallback: int,
                                   **kwargs: Any # For additional managers like NpcManager, CombatManager if actions require them
                                   ) -> Dict[str, Any]:
        """
        Processes a list of actions for a party, typically at the end of a turn.
        This method would iterate through each character's actions, call self.process()
        or a similar refined method for each, aggregate results, and orchestrate
        any party-wide consequences or narrative.

        For now, this is a placeholder to satisfy test mocks.
        A full implementation would be complex.
        """
        print(f"ActionProcessor.process_party_actions CALLED with {len(party_actions_data)} actions. Placeholder implementation.")
        # Placeholder: Process first action if available, for basic testing
        # In a real scenario, loop through all actions, handle interdependencies, etc.

        # This is a very simplified placeholder response.
        # A real implementation would aggregate results from individual action processing.
        individual_results = []
        overall_success = True
        any_state_changed = False

        # Example of how it *might* iterate, though self.process needs discord_user_id not char_id directly
        # for char_id, actions_json_str in party_actions_data:
        #     if char_manager:
        #         character = await char_manager.get_character(char_id) # Assuming get_character by internal ID
        #         if character and character.discord_user_id:
        #             try:
        #                 actions = json.loads(actions_json_str)
        #                 for action in actions: # Assuming actions_json_str can be a list of actions
        #                     action_type = action.get("intent") # Or however action type is defined
        #                     action_data = action # Pass the whole action dict as data
        #                     if action_type:
        #                         # TODO: game_log_manager is not passed here, self.process expects it.
        #                         # This highlights that process_party_actions needs careful design
        #                         # or self.process needs to be callable with slightly different params.
        #                         # For now, this part is effectively pseudo-code.
        #                         # res = await self.process(game_state, char_manager, loc_manager, event_manager, rule_engine, openai_service, game_log_manager,
        #                         #                          ctx_channel_id_fallback, character.discord_user_id, action_type, action_data)
        #                         # individual_results.append(res)
        #                         # if not res.get("success", False): overall_success = False
        #                         # if res.get("state_changed", False): any_state_changed = True
        #                         pass # Skipping actual call to self.process for placeholder
        #             except json.JSONDecodeError:
        #                 print(f"Error decoding actions for char_id {char_id}: {actions_json_str}")
        #                 individual_results.append({"success": False, "message": f"Error decoding actions for {char_id}"})
        #                 overall_success = False


        return {
            "success": overall_success,
            "message": "Party actions processed (placeholder response).", # Generic message
            "individual_action_results": individual_results, # Would be list of dicts from self.process
            "target_channel_id": ctx_channel_id_fallback, # Or determined dynamically
            "overall_state_changed": any_state_changed # Aggregated from individual actions
        }
