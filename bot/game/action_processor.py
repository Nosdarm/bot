# bot/game/action_processor.py
import json
import traceback
from typing import Dict, Any, Optional, List, Tuple

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character
from bot.game.models.location import Location

# Import managers
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.event_manager import EventManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.conflict_resolver import ConflictResolver

# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine

# Assume CharacterModel is imported from bot.game.models.character or similar
from bot.game.models.character import Character as CharacterModel

class ActionProcessor:
    def __init__(self):
        print("ActionProcessor initialized.")
        self._conflict_resolver: Optional[ConflictResolver] = None

    def set_conflict_resolver(self, resolver: ConflictResolver):
        self._conflict_resolver = resolver

    async def process(self,
                      game_state: GameState,
                      char_manager: Optional[CharacterManager],
                      loc_manager: Optional[LocationManager],
                      event_manager: Optional[EventManager],
                      rule_engine: Optional[RuleEngine],
                      openai_service: Optional[OpenAIService],
                      ctx_channel_id: int,
                      discord_user_id: int,
                      action_type: str,
                      action_data: Dict[str, Any],
                      game_log_manager: Optional[GameLogManager] = None
                      ) -> Dict[str, Any]:
        """
        Processes a player action. Determines target, calls rules/managers, involves event manager,
        uses AI for narrative, and returns structured response data including message and target channel.
        Receives all necessary managers, services, and context for the specific action.
        Returns: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # --- Initial Manager Checks ---
        if not char_manager:
            return {"success": False, "message": "**Мастер:** Система персонажей недоступна.", "target_channel_id": ctx_channel_id, "state_changed": False}
        if not loc_manager:
            return {"success": False, "message": "**Мастер:** Система локаций недоступна.", "target_channel_id": ctx_channel_id, "state_changed": False}
        if not event_manager:
            return {"success": False, "message": "**Мастер:** Система событий недоступна.", "target_channel_id": ctx_channel_id, "state_changed": False}
        if not rule_engine:
            return {"success": False, "message": "**Мастер:** Система правил недоступна.", "target_channel_id": ctx_channel_id, "state_changed": False}
        if not openai_service:
            return {"success": False, "message": "**Мастер:** Сервис AI недоступен.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # --- Character and Location Fetch ---
        character = char_manager.get_character_by_discord_id(guild_id=str(game_state.server_id), discord_user_id=discord_user_id)
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        current_location_id = getattr(character, 'location_id', None)
        location_instance_dict = loc_manager.get_location_instance(str(game_state.server_id), current_location_id) if current_location_id else None

        if not location_instance_dict:
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        output_channel_id = loc_manager.get_location_channel(str(game_state.server_id), location_instance_dict['id']) or ctx_channel_id

        # --- Event Handling Simulation ---
        all_guild_events = event_manager.get_active_events(guild_id=str(game_state.server_id))
        active_events = []
        if location_instance_dict:
            current_loc_id = location_instance_dict['id']
            for event_obj in all_guild_events:
                event_location_id = getattr(event_obj, 'location_id', event_obj.state_variables.get('location_id'))
                if event_location_id == current_loc_id:
                    active_events.append(event_obj)
        print(f"ActionProcessor: Found {len(active_events)} active events specific to location {location_instance_dict['id'] if location_instance_dict else 'N/A'}.")

        relevant_event_id = None
        is_potentially_event_interactive = action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"]
        if is_potentially_event_interactive and active_events:
             relevant_event_id = active_events[0].id

        if relevant_event_id:
             character_name_i18n = getattr(character, 'name_i18n', {})
             character_name = character_name_i18n.get('en', 'Unknown Character')
             print(f"Action {action_type} for {character_name} routed to event {relevant_event_id}.")

             # TODO: CRITICAL - The method 'process_player_action_within_event' is missing from EventManager.
             # This functionality is essential for routing player actions to active events.
             # It needs to be implemented in EventManager or the event handling logic here needs a redesign.
             event_response = await event_manager.process_player_action_within_event(
                 event_id=relevant_event_id,
                 player_id=character.id,
                 action_type=action_type,
                 action_data=action_data,
                 guild_id=str(game_state.server_id), # Added guild_id
                 # Pass other managers and context variables as kwargs
                 character_manager=char_manager,
                 loc_manager=loc_manager,
                 rule_engine=rule_engine,
                 openai_service=openai_service,
                 event_manager=event_manager, # Can be passed if needed by the method
                 game_log_manager=game_log_manager, # Pass game_log_manager
                 ctx_channel_id=ctx_channel_id # For fallback channel ID
             )
             # Ensure the response from the event processing has the necessary keys.
             if 'target_channel_id' not in event_response or event_response['target_channel_id'] is None:
                 event_response['target_channel_id'] = output_channel_id # Fallback to location channel
             if 'state_changed' not in event_response:
                 event_response['state_changed'] = False # Default if not specified

             # If the event processing was successful and it handled the action, return its response.
             # The event processing method should indicate if it fully handled the action.
             # For now, we assume if an event is relevant, it handles the action.
             return event_response
             # print(f"ActionProcessor: TODO - EventManager.process_player_action_within_event call is commented out as method does not exist.") # Remove this line


        # --- Regular World Interaction ---
        character_name_i18n = getattr(character, 'name_i18n', {})
        character_name = character_name_i18n.get('en', 'Unknown Character')
        location_name_from_dict = location_instance_dict.get('name', 'Unknown Location')
        print(f"Processing regular action '{action_type}' for player '{character_name}' at '{location_name_from_dict}'.")

        if action_type == "look":
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{character.name_i18n.get('en', character.id)}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location_instance_dict.get('name', 'N/A')}', Описание: '''{location_instance_dict.get('description', '')[:200]}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name_i18n.get('en', c.id) for c in char_manager.get_characters_in_location(guild_id=str(game_state.server_id), location_id=location_instance_dict['id']) if c.id != character.id][:3]) if char_manager.get_characters_in_location(guild_id=str(game_state.server_id), location_id=location_instance_dict['id']) else 'нет'}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)
            return {"success": True, "message": f"**Локация:** {location_instance_dict.get('name', 'N/A')}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}

        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            target_location_instance_id: Optional[str] = None
            current_loc_template_id = location_instance_dict.get('template_id')

            if current_loc_template_id and current_location_id:
                valid_exits = loc_manager.get_connected_locations(guild_id=str(game_state.server_id), instance_id=current_location_id)
                target_exit_template_id_candidate: Optional[str] = None
                for exit_name, exit_tpl_id in valid_exits.items():
                    if exit_name.lower() == destination_input.lower():
                        target_exit_template_id_candidate = exit_tpl_id
                        break
                    target_template_candidate = loc_manager.get_location_static(str(game_state.server_id), exit_tpl_id)
                    if target_template_candidate and target_template_candidate.get('name','').lower() == destination_input.lower():
                        target_exit_template_id_candidate = exit_tpl_id
                        break

                if target_exit_template_id_candidate:
                    all_instances = loc_manager._location_instances.get(str(game_state.server_id), {}).values()
                    for inst_data in all_instances:
                        if inst_data.get('template_id') == target_exit_template_id_candidate and inst_data.get('is_active', True):
                            target_location_instance_id = inst_data.get('id')
                            break

            if not target_location_instance_id:
                return {"success": False, "message": f"**Мастер:** Неизвестное направление или путь: '{destination_input}'. Отсюда туда нельзя попасть.", "target_channel_id": output_channel_id, "state_changed": False}

            target_location_instance_dict = loc_manager.get_location_instance(str(game_state.server_id), target_location_instance_id)
            if not target_location_instance_dict:
                 return {"success": False, "message": f"**Мастер:** Ошибка при поиске данных целевой локации.", "target_channel_id": output_channel_id, "state_changed": False}

            await char_manager.update_character_location(character_id=character.id, location_id=target_location_instance_id, guild_id=str(game_state.server_id))

            exit_description_for_prompt = destination_input
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt = (
                f"Персонаж '{character.name_i18n.get('en', character.id)}' перемещается из локации '{location_instance_dict.get('name', 'N/A')}' через '{exit_description_for_prompt}' "
                f"в локацию '{target_location_instance_dict.get('name', 'N/A')}'. "
                f"Краткое описание начальной локации: {location_instance_dict.get('description', '')[:150]}. "
                f"Краткое описание конечной локации: {target_location_instance_dict.get('description', '')[:150]}. "
                f"Опиши краткое путешествие и прибытие в '{target_location_instance_dict.get('name', 'N/A')}'. Будь атмосферным и мрачным. В конце явно укажи, что персонаж теперь находится в '{target_location_instance_dict.get('name', 'N/A')}'."
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=250)
            destination_channel_id = loc_manager.get_location_channel(str(game_state.server_id), target_location_instance_id)
            final_output_channel_id = destination_channel_id if destination_channel_id else output_channel_id
            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": final_output_channel_id, "state_changed": True}

        elif action_type == "skill_check":
             skill_name = action_data.get("skill_name")
             complexity = action_data.get("complexity", "medium")
             base_modifiers = action_data.get("modifiers", {})
             target_description = action_data.get("target_description", "чего-то")
             env_modifiers = {}
             status_modifiers = {}
             final_modifiers = {**env_modifiers, **status_modifiers, **base_modifiers}

             if not skill_name:
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}
             character_skills = getattr(character, 'skills', {})
             if skill_name not in character_skills:
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # TODO: Review if skill check DC should come from RuleEngine instead of local map.
             COMPLEXITY_TO_DC_MAP = {"easy": 10, "medium": 15, "hard": 20, "heroic": 25, "legendary": 30}
             base_dc = COMPLEXITY_TO_DC_MAP.get(complexity.lower(), 15)

             check_success, total_value, d20_roll, crit_status = await rule_engine.resolve_skill_check(
                character=character, skill_name=skill_name,
                difficulty_class=base_dc, situational_modifier=sum(final_modifiers.values())
             )

             check_result_for_ai = {
                "is_success": check_success, "roll": d20_roll, "total_value": total_value,
                "dc": base_dc, "crit_status": crit_status, "skill_name": skill_name,
                "modifiers_applied_sum": sum(final_modifiers.values())
             }
             mech_summary = f"Проверка: {skill_name.capitalize()} СЛ {base_dc}. Бросок: {d20_roll} + Модификаторы: {sum(final_modifiers.values())} = Итог: {total_value}. Результат: {crit_status or ('Успех' if check_success else 'Провал')}"
             check_result_for_ai["description"] = mech_summary

             character_name_for_ai = character.name_i18n.get('en', character.id)
             character_stats = getattr(character, 'stats', {})
             location_name_for_ai = location_instance_dict.get('name', 'N/A')
             location_description_template = location_instance_dict.get('description', 'A non-descript area.')
             system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай действия и их результаты детализированно и атмосферно."
             user_prompt = (
                 f"Персонаж '{character_name_for_ai}' (Навыки: {list(character_skills.keys())}, Статы: {list(character_stats.keys())}) "
                 f"попытался совершить действие, связанное с навыком '{skill_name}', целью было {target_description}. "
                 f"Ситуация: локация '{location_name_for_ai}', атмосферное описание: {location_description_template[:150]}..."
                 f"Механический результат проверки:\n{json.dumps(check_result_for_ai, ensure_ascii=False)}\n"
                 f"Опиши, КАК это выглядело и ощущалось в мире. Учитывай результат (Успех/Провал/Крит) и контекст. Будь мрачным и детализированным."
             )
             description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=300)
             state_changed_from_check = crit_status == "critical_failure"

             if game_log_manager and character:
                channel_id_to_log: Optional[int] = ctx_channel_id
                await game_log_manager.log_event(
                    guild_id=str(game_state.server_id), event_type="player_action",
                    message=f"{character_name_for_ai} attempted skill check {skill_name} for {target_description}. Success: {check_success}. Details: {mech_summary}",
                    related_entities=[{"id": str(character.id), "type": "character"}],
                    channel_id=channel_id_to_log, metadata={"skill_name": skill_name, "complexity": complexity, "result": check_result_for_ai}
                )
             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed_from_check}

        print(f"Action type '{action_type}' not handled by any specific processor in self.process.")
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается или не распознано.", "target_channel_id": ctx_channel_id, "state_changed": False}


    async def process_party_actions(self,
                                game_state: GameState,
                                char_manager: CharacterManager, # Made non-optional as it's critical
                                loc_manager: LocationManager,   # Made non-optional
                                event_manager: EventManager,  # Made non-optional
                                rule_engine: RuleEngine,      # Made non-optional
                                openai_service: OpenAIService, # Made non-optional
                                party_actions_data: List[Tuple[str, str]],
                                ctx_channel_id_fallback: int,
                                conflict_resolver: Optional[ConflictResolver] = None,
                                game_log_manager: Optional[GameLogManager] = None
                                ) -> Dict[str, Any]:

        current_conflict_resolver = conflict_resolver if conflict_resolver else self._conflict_resolver

        if current_conflict_resolver:
            print(f"ActionProcessor: Using ConflictResolver for party actions.")
            parsed_actions_map: Dict[str, List[Dict[str, Any]]] = {}
            for char_id_loop, collected_actions_json_loop in party_actions_data:
                character_obj: Optional[CharacterModel] = char_manager.get_character(guild_id=str(game_state.server_id), character_id=char_id_loop)
                if not character_obj:
                    print(f"ActionProcessor: Character {char_id_loop} not found during conflict analysis. Skipping.")
                    parsed_actions_map[char_id_loop] = []
                    continue
                if not collected_actions_json_loop or collected_actions_json_loop.strip() == "[]":
                    parsed_actions_map[char_id_loop] = []
                    continue
                try:
                    actions_list = json.loads(collected_actions_json_loop)
                    if isinstance(actions_list, list):
                        parsed_actions_map[char_id_loop] = actions_list
                    else:
                         print(f"ActionProcessor: Malformed actions data for character {char_id_loop}: Not a list.")
                         parsed_actions_map[char_id_loop] = []
                except json.JSONDecodeError:
                    print(f"ActionProcessor: Invalid JSON for character {char_id_loop}. Skipping actions.")
                    parsed_actions_map[char_id_loop] = []
                except Exception as e:
                     print(f"ActionProcessor: Unexpected error parsing actions for character {char_id_loop}: {e}")
                     traceback.print_exc()
                     parsed_actions_map[char_id_loop] = []

            print(f"ActionProcessor: Calling ConflictResolver.analyze_actions_for_conflicts with map for players: {list(parsed_actions_map.keys())}")
            identified_conflicts = current_conflict_resolver.analyze_actions_for_conflicts(player_actions_map=parsed_actions_map)

            if identified_conflicts:
                print(f"ActionProcessor: Identified {len(identified_conflicts)} conflicts.")
                if game_log_manager:
                    await game_log_manager.log_event(
                        guild_id=str(game_state.server_id),
                        event_type="conflict_identification",
                        message=f"{len(identified_conflicts)} conflicts identified for party.",
                        related_entities=[{"id": p_id, "type": "character"} for p_id in parsed_actions_map.keys()],
                    )
                return {"success": True, "message": f"Conflict analysis initiated. {len(identified_conflicts)} potential conflicts found.", "identified_conflicts": identified_conflicts, "individual_action_results": [], "overall_state_changed": False}
            else:
                print("ActionProcessor: No conflicts identified.")
                return {"success": True, "message": "No conflicts identified. Actions not processed further in this path yet.", "individual_action_results": [], "overall_state_changed": False}
        else:
            print(f"ActionProcessor: Starting process_party_actions (individual processing) for {len(party_actions_data)} characters.")
            all_individual_results = []
            overall_state_changed_for_party = False
            for char_id_loop_ind, collected_actions_json_loop_ind in party_actions_data:
                character_obj_ind: Optional[CharacterModel] = char_manager.get_character(guild_id=str(game_state.server_id), character_id=char_id_loop_ind)
                if not character_obj_ind:
                    print(f"ActionProcessor: Character {char_id_loop_ind} not found. Skipping.")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Character not found.", "state_changed": False})
                    continue
                if not collected_actions_json_loop_ind or collected_actions_json_loop_ind.strip() == "[]":
                    language_ind = character_obj_ind.selected_language or "en"
                    char_name_i18n_ind = getattr(character_obj_ind, 'name_i18n', {})
                    char_name_ind = char_name_i18n_ind.get(language_ind, char_id_loop_ind)
                    print(f"ActionProcessor: No actions for {char_name_ind}. Skipping.")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": True, "message": "No actions submitted.", "state_changed": False})
                    continue
                try:
                    actions_list_ind = json.loads(collected_actions_json_loop_ind)
                    if not isinstance(actions_list_ind, list):
                        all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Malformed actions data (not a list).", "state_changed": False})
                        continue
                    for action_item_ind in actions_list_ind:
                        if not isinstance(action_item_ind, dict):
                            print(f"ActionProcessor: Skipping malformed action item for char {char_id_loop_ind}: {action_item_ind}")
                            continue
                        action_type_ind = action_item_ind.get("intent")
                        action_data_ind = action_item_ind.get("entities", {})
                        original_text_ind = action_item_ind.get("original_text", "N/A")
                        if not action_type_ind:
                            all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, "success": False, "message": "Action intent missing.", "state_changed": False})
                            continue

                        char_loc_id = getattr(character_obj_ind, 'location_id', None)
                        char_location_instance_ind: Optional[Dict[str,Any]] = loc_manager.get_location_instance(guild_id=str(game_state.server_id), instance_id=char_loc_id) if char_loc_id else None

                        ctx_channel_id_for_action_ind = ctx_channel_id_fallback
                        if char_location_instance_ind and char_location_instance_ind.get("channel_id"):
                            try:
                                ctx_channel_id_for_action_ind = int(char_location_instance_ind["channel_id"])
                            except ValueError:
                                print(f"Warning: Could not convert location channel_id '{char_location_instance_ind['channel_id']}' to int for action processing.")

                        raw_discord_id = getattr(character_obj_ind, 'discord_user_id', None)
                        processed_discord_id: Optional[int] = None
                        if raw_discord_id is not None:
                            try:
                                processed_discord_id = int(raw_discord_id)
                            except ValueError:
                                print(f"ActionProcessor: Could not convert discord_user_id '{raw_discord_id}' to int for char {character_obj_ind.id}. Passing None.")

                        single_action_result = await self.process(
                            game_state=game_state, char_manager=char_manager, loc_manager=loc_manager,
                            event_manager=event_manager, rule_engine=rule_engine, openai_service=openai_service,
                            ctx_channel_id=ctx_channel_id_for_action_ind, discord_user_id=processed_discord_id,
                            action_type=action_type_ind, action_data=action_data_ind, game_log_manager=game_log_manager
                        )
                        all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, **single_action_result})
                        if single_action_result.get("state_changed", False):
                            overall_state_changed_for_party = True
                except json.JSONDecodeError:
                    print(f"ActionProcessor: Invalid actions JSON for character {char_id_loop_ind}. Skipping actions.")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Invalid actions JSON.", "state_changed": False})
                except Exception as e_inner:
                    print(f"ActionProcessor: Unexpected error processing actions for character {char_id_loop_ind}.")
                    traceback.print_exc()
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": f"Unexpected error: {e_inner}", "state_changed": False})
            return {
                "success": True,
                "individual_action_results": all_individual_results,
                "overall_state_changed": overall_state_changed_for_party
            }