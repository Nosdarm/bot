# bot/game/action_processor.py (updated process method implementation for 'move')
import json
import traceback
from typing import Dict, Any, Optional, List, Tuple

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character as CharacterModel # Use alias
from bot.game.models.location import Location as LocationModel # Use alias

# Import managers
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.event_manager import EventManager
# from bot.game.managers.npc_manager import NpcManager # Uncomment if used


# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine # If movement needs rule checks
from bot.game.rules import skill_rules # If skill_check rule is needed

# Import ConflictResolver
from bot.game.conflict_resolver import ConflictResolver
from bot.game.managers.game_log_manager import GameLogManager


class ActionProcessor:
    def __init__(self, conflict_resolver: Optional[ConflictResolver] = None):
        self._conflict_resolver = conflict_resolver
        print(f"ActionProcessor initialized. ConflictResolver {'present' if self._conflict_resolver else 'not present'}.")


    async def process(self,
                      game_state: GameState,
                      char_manager: CharacterManager,
                      loc_manager: LocationManager,
                      event_manager: EventManager,
                      # Add other managers required for specific action processing logic
                      # npc_manager: NpcManager,
                      # item_manager: ItemManager,
                      # combat_manager: CombatManager,
                      # time_manager: TimeManager,
                      rule_engine: RuleEngine,
                      openai_service: OpenAIService,
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

        # --- Initial Checks ---
        # Character is fetched using char_manager passed into the method
        character: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=str(game_state.server_id), # Use game_state.server_id
            discord_user_id=discord_user_id
        )
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/start`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # Location is fetched using loc_manager passed into the method
        # Character.location_id should store the instance_id of the character's current location
        if not character.location_id:
             return {"success": False, "message": "**Мастер:** У вашего персонажа не указана локация. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        current_location_instance: Optional[Dict[str, Any]] = loc_manager.get_location_instance(
            guild_id=str(game_state.server_id), # Use game_state.server_id
            instance_id=character.location_id
        )
        if not current_location_instance:
            return {"success": False, "message": f"**Мастер:** Ваш персонаж в неизвестной локации (ID: {character.location_id}). Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # TODO: Determine output_channel_id. Location model might have a 'channel_id' attribute.
        # output_channel_id = loc_manager.get_location_channel(game_state, location.id) or ctx_channel_id
        output_channel_id = int(current_location_instance.get("channel_id", 0)) or ctx_channel_id


        # --- Event Processing ---
        # TODO: Implement event_manager.get_active_events_in_location
        # active_events = event_manager.get_active_events_in_location(character.location_id, guild_id=str(game_state.server_id))
        active_events: List[Any] = [] # Placeholder
        relevant_event_id: Optional[str] = None

        is_potentially_event_interactive = action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"]
        if is_potentially_event_interactive and active_events:
             relevant_event_id = active_events[0].id # Simplistic placeholder

        if relevant_event_id:
             # TODO: Implement event_manager.process_player_action_within_event
             # event_response = await event_manager.process_player_action_within_event(
             #     event_id=relevant_event_id,
             #     player_id=character.id,
             #     guild_id=str(game_state.server_id), # Pass guild_id
             #     action_type=action_type,
             #     action_data=action_data,
             #     character_manager=char_manager,
             #     loc_manager=loc_manager,
             #     rule_engine=rule_engine,
             #     openai_service=openai_service, # openai_service is passed to process method
             #     ctx_channel_id=ctx_channel_id,
             # )
             # if 'target_channel_id' not in event_response: event_response['target_channel_id'] = output_channel_id
             # if 'state_changed' not in event_response: event_response['state_changed'] = False
             # return event_response
             pass # Placeholder for event processing

        # --- Regular World Interaction ---
        # Use character.name_i18n, current_location_instance.get('name')
        language = character.selected_language or "en"
        character_name_display = character.name_i18n.get(language, character.id)
        location_name_display = current_location_instance.get('name', "неизвестная локация")
        print(f"Processing regular action '{action_type}' for player '{character_name_display}' at '{location_name_display}'.")

        # Initialize common response variables
        response_success: bool = False
        response_message: str = ""
        response_target_channel_id: int = output_channel_id
        response_state_changed: bool = False

        if action_type == "look":
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            # TODO: char_manager.get_characters_in_location needs guild_id
            # characters_in_loc = await char_manager.get_characters_in_location(location_id=character.location_id, guild_id=str(game_state.server_id))
            # visible_chars_str = ', '.join([c.name_i18n.get(language, c.id) for c in characters_in_loc if c.id != character.id][:3]) if characters_in_loc else 'нет'
            visible_chars_str = "нет" # Placeholder
            location_description_template = current_location_instance.get('description_template', 'Здесь ничего особенного.')

            user_prompt = (
                f"Опиши локацию для персонажа '{character_name_display}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location_name_display}', Шаблон описания: '''{location_description_template[:200]}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {visible_chars_str}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)

            if game_log_manager and character:
                await game_log_manager.log_event(
                    guild_id=str(game_state.server_id), # Use game_state.server_id
                    event_type="player_action",
                    message=f"{character_name_display} used {action_type} to look at {location_name_display}.",
                    related_entities=[{"id": str(character.id), "type": "character"}, {"id": str(character.location_id), "type": "location"}],
                    channel_id=str(ctx_channel_id)
                )
            return {"success": True, "message": f"**Локация:** {location_name_display}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}
        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # TODO: Implement loc_manager.get_exit_target and ensure parameters are correct
            # target_location_instance_data = loc_manager.get_exit_target(character.location_id, destination_input, guild_id=str(game_state.server_id))
            target_location_instance_data: Optional[Dict[str,Any]] = None # Placeholder

            # Example of how get_connected_locations MIGHT be used if get_exit_target isn't available/suitable
            # current_location_template_id = current_location_instance.get('template_id')
            # if current_location_template_id and character.location_id:
            #    connected_exits = loc_manager.get_connected_locations(
            #        guild_id=str(game_state.server_id),
            #        location_id=current_location_template_id,
            #        instance_id=character.location_id
            #    )
            #    # ... logic to find target_location_instance_data using connected_exits and destination_input ...
            # else:
            #    return {"success": False, "message": "**Мастер:** Ошибка определения текущей локации для выходов.", "target_channel_id": output_channel_id, "state_changed": False}


            if not target_location_instance_data:
                return {"success": False, "message": f"**Мастер:** Неизвестное направление или путь: '{destination_input}'. Отсюда туда нельзя попасть.", "target_channel_id": output_channel_id, "state_changed": False}

            # TODO: RuleEngine check for movement if needed
            # await char_manager.update_character_location(character.id, target_location_instance_data['id'], guild_id=str(game_state.server_id))
            # For now, assume direct update on character model, then save
            character.location_id = target_location_instance_data['id']
            char_manager.mark_character_dirty(str(game_state.server_id), character.id) # Mark dirty
            await char_manager.save_character(character, guild_id=str(game_state.server_id)) # Save

            response_state_changed = True

            # OpenAI call for description (uses openai_service passed to process)
            # ... (OpenAI prompt generation logic) ...
            # description = await openai_service.generate_master_response(...)
            description = f"Вы переместились в {target_location_instance_data.get('name', 'новое место')}." # Placeholder AI description

            # TODO: Determine destination_channel_id correctly
            # destination_channel_id = loc_manager.get_location_channel(target_location_instance_data['id'], guild_id=str(game_state.server_id))
            destination_channel_id = int(target_location_instance_data.get("channel_id",0)) or output_channel_id
            response_target_channel_id = destination_channel_id

            if game_log_manager and character:
                await game_log_manager.log_event(
                    guild_id=str(game_state.server_id),
                    event_type="player_action",
                    message=f"{character_name_display} moved from {location_name_display} to {target_location_instance_data.get('name', 'новое место')}.",
                    related_entities=[
                        {"id": str(character.id), "type": "character"},
                        {"id": str(current_location_instance['id']), "type": "location"},
                        {"id": str(target_location_instance_data['id']), "type": "location"}
                    ],
                    channel_id=str(ctx_channel_id)
                )
            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": response_target_channel_id, "state_changed": response_state_changed}

        elif action_type == "skill_check":
             skill_name = action_data.get("skill_name")
             complexity = action_data.get("complexity", "medium")
             # base_modifiers = action_data.get("modifiers", {}) # This was unbound
             # target_description = action_data.get("target_description", "чего-то") # This was unbound
             base_modifiers: Dict[str, Any] = action_data.get("modifiers", {})
             target_description: str = action_data.get("target_description", "чего-то")


             env_modifiers: Dict[str, Any] = {}
             status_modifiers: Dict[str, Any] = {}
             final_modifiers = {**env_modifiers, **status_modifiers, **base_modifiers}

             if not skill_name:
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}

             if skill_name not in character.skills: # skills is Dict[str, int] on CharacterModel
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             base_dc = skill_rules.get_base_dc(complexity) # Corrected function name

             # TODO: Implement rule_engine.perform_check if it's missing or fix signature
             # For now, assume it exists and works with passed rule_engine instance
             # check_result = await rule_engine.perform_check( # perform_check might be async
             check_result: Dict[str, Any] = {"description": "Проверка выполнена (placeholder).", "is_success": True, "is_critical_failure": False} # Placeholder
             #    character_id=character.id,
             #    guild_id=str(game_state.server_id), # Pass guild_id
             #    check_type="skill",
             #    skill_name=skill_name,
             #    base_dc=base_dc,
             #    modifiers=final_modifiers
             # )

             if not check_result: # Should not happen with placeholder
                  return {"success": False, "message": f"**Мастер:** Произошла ошибка при выполнении проверки навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # description variable was unbound
             description: str = ""
             # OpenAI call (uses openai_service passed to process)
             # ... (OpenAI prompt generation logic, ensure location_name_display and current_location_instance.get('description_template') are used) ...
             # description = await openai_service.generate_master_response(...)
             description = "Результат проверки навыка (placeholder AI description)." # Placeholder AI description

             # mech_summary and state_changed were unbound
             mech_summary: str = check_result.get("description", "Проверка выполнена.")
             state_changed_from_check: bool = check_result.get("is_critical_failure", False)

             if game_log_manager and character:
                 await game_log_manager.log_event(
                     guild_id=str(game_state.server_id), # Use game_state.server_id
                     event_type="player_action",
                     message=f"{character_name_display} attempted skill check {skill_name} for {target_description}. Success: {check_result.get('is_success')}",
                     related_entities=[{"id": str(character.id), "type": "character"}],
                     channel_id=str(ctx_channel_id),
                     metadata={"skill_name": skill_name, "complexity": complexity, "result": check_result}
                 )
            return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed_from_check}

        # Fallback for unhandled actions
        print(f"Action type '{action_type}' not handled by any specific processor in self.process.")
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается или не распознано.", "target_channel_id": ctx_channel_id, "state_changed": False}


    async def process_party_actions(self,
                                game_state: GameState,
                                char_manager: CharacterManager,
                                loc_manager: LocationManager,
                                event_manager: EventManager,
                                rule_engine: RuleEngine,
                                openai_service: OpenAIService, # openai_service is passed in
                                party_actions_data: List[Tuple[str, str]],
                                ctx_channel_id_fallback: int,
                                conflict_resolver: Optional[ConflictResolver] = None,
                                game_log_manager: Optional[GameLogManager] = None
                                ) -> Dict[str, Any]:
        current_conflict_resolver = conflict_resolver if conflict_resolver else self._conflict_resolver

        if current_conflict_resolver:
            print(f"ActionProcessor: Using ConflictResolver for party actions.")
            parsed_actions_map: Dict[str, List[Dict[str, Any]]] = {}
            # character_objects: Dict[str, CharacterModel] = {} # Corrected type
            character_id_str: str = "" # Initialize character_id_str
            collected_actions_json_string_str: str = "" # Initialize

            for char_id_loop, collected_actions_json_loop in party_actions_data:
                character_id_str = char_id_loop # Assign to initialized var
                collected_actions_json_string_str = collected_actions_json_loop # Assign

                # Use await for async get_character
                character_obj: Optional[CharacterModel] = await char_manager.get_character(guild_id=str(game_state.server_id), character_id=character_id_str)
                if not character_obj:
                    print(f"ActionProcessor: Character {character_id_str} not found during conflict analysis. Skipping.")
                    # continue # This was a "continue can be used only within a loop" error source if this loop was removed/refactored.
                               # Now it's fine as it's inside the for loop.
                    parsed_actions_map[character_id_str] = [] # Ensure key exists even if char not found or no actions
                    continue


                # character_objects[character_id_str] = character_obj # This was potentially unbound if continue was hit

                if not collected_actions_json_string_str or collected_actions_json_string_str.strip() == "[]":
                    parsed_actions_map[character_id_str] = []
                    continue # Correct use of continue
                try:
                    actions_list = json.loads(collected_actions_json_string_str)
                    if not isinstance(actions_list, list):
                        print(f"ActionProcessor: Parsed actions for {character_obj.name_i18n.get('en', character_id_str)} is not a list. Skipping.")
                        parsed_actions_map[character_id_str] = []
                        continue # Correct use of continue
                    
                    processed_actions_for_char = []
                    for action_item in actions_list:
                        if isinstance(action_item, dict) and "intent" in action_item:
                            action_with_context = {
                                "player_id": character_id_str,
                                "type": action_item.get("intent"),
                                **action_item.get("entities", {}),
                                "original_text": action_item.get("original_text", "N/A")
                            }
                            processed_actions_for_char.append(action_with_context)
                        else:
                            print(f"Skipping malformed action item for {character_id_str}: {action_item}")
                    parsed_actions_map[character_id_str] = processed_actions_for_char
                except json.JSONDecodeError:
                    print(f"ActionProcessor: Failed to parse JSON for {character_id_str}. Skipping.")
                    parsed_actions_map[character_id_str] = []

            if not parsed_actions_map: # Check after loop
                 print("ActionProcessor: No valid actions or characters parsed for conflict analysis.")
                 return {"success": True, "message": "No actions to analyze for conflicts.", "individual_action_results": [], "overall_state_changed": False}


            print(f"ActionProcessor: Calling ConflictResolver.analyze_actions_for_conflicts with map for players: {list(parsed_actions_map.keys())}")
            identified_conflicts = current_conflict_resolver.analyze_actions_for_conflicts(player_actions_map=parsed_actions_map)

            if identified_conflicts:
                print(f"ActionProcessor: Identified {len(identified_conflicts)} conflicts:")
                # ... (rest of conflict handling logic) ...
                if game_log_manager: # Check if game_log_manager is not None
                    await game_log_manager.log_event(
                        guild_id=str(game_state.server_id), # Use game_state.server_id
                        event_type="conflict_identification",
                        message=f"{len(identified_conflicts)} conflicts identified for party.",
                        related_entities=[{"id": p_id, "type": "character"} for p_id in parsed_actions_map.keys()],
                    )
                return {"success": True, "message": f"Conflict analysis initiated. {len(identified_conflicts)} potential conflicts found.", "identified_conflicts": identified_conflicts, "individual_action_results": [], "overall_state_changed": False}
            else: # No conflicts
                # ... (logic for no conflicts) ...
                return {"success": True, "message": "No conflicts identified. Actions not processed further in this path yet.", "individual_action_results": [], "overall_state_changed": False}

        # Fallback: Original behavior if no conflict_resolver
        print(f"ActionProcessor: Starting process_party_actions (individual processing) for {len(party_actions_data)} characters.")
        all_individual_results = []
        overall_state_changed_for_party = False
        
        # Initialize character_id and collected_actions_json before loop if they were used after loop
        # However, they are only used *inside* this loop, so initialization outside is not strictly needed here.
        # character_id: str = "" (Not needed here)
        # collected_actions_json: str = "" (Not needed here)

        for char_id_loop_ind, collected_actions_json_loop_ind in party_actions_data:
            # Use loop variables directly
            character_obj_ind: Optional[CharacterModel] = await char_manager.get_character(guild_id=str(game_state.server_id), character_id=char_id_loop_ind)
            if not character_obj_ind:
                print(f"ActionProcessor: Character {char_id_loop_ind} not found. Skipping.")
                all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Character not found.", "state_changed": False})
                continue # Correct use of continue

            if not collected_actions_json_loop_ind or collected_actions_json_loop_ind.strip() == "[]":
                # language_ind = character_obj_ind.selected_language or "en" # This was an unindent error source
                # char_name_ind = character_obj_ind.name_i18n.get(language_ind, char_id_loop_ind) # This was an unindent error source
                # print(f"ActionProcessor: No actions for {char_name_ind}. Skipping.") # This was an unindent error source
                all_individual_results.append({"character_id": char_id_loop_ind, "success": True, "message": "No actions submitted.", "state_changed": False})
                continue # Correct use of continue

            # Corrected indentation for these lines:
            language_ind = character_obj_ind.selected_language or "en"
            char_name_ind = character_obj_ind.name_i18n.get(language_ind, char_id_loop_ind)
            print(f"ActionProcessor: No actions for {char_name_ind}. Skipping.")


            try: # This try block was mis-indented
                actions_list_ind = json.loads(collected_actions_json_loop_ind)
                if not isinstance(actions_list_ind, list):
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Malformed actions data.", "state_changed": False})
                    continue # Correct use of continue

                for action_item_ind in actions_list_ind: # Corrected variable name
                    if not isinstance(action_item_ind, dict): continue # Correct use of continue
                    action_type_ind = action_item_ind.get("intent")
                    action_data_ind = action_item_ind.get("entities", {})
                    original_text_ind = action_item_ind.get("original_text", "N/A")
                    if not action_type_ind:
                        all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, "success": False, "message": "Action intent missing.", "state_changed": False})
                        continue # Correct use of continue

                    # TODO: Fix loc_manager.get_location - it expects template_id and optional guild_id
                    # This should use character_obj_ind.location_id (instance_id)
                    # char_location_instance_ind = loc_manager.get_location_instance(guild_id=str(game_state.server_id), instance_id=character_obj_ind.location_id)
                    char_location_instance_ind: Optional[Dict[str,Any]] = None # Placeholder
                    
                    ctx_channel_id_for_action_ind = ctx_channel_id_fallback
                    if char_location_instance_ind and char_location_instance_ind.get("channel_id"):
                        try: ctx_channel_id_for_action_ind = int(char_location_instance_ind["channel_id"])
                        except ValueError: pass

                    single_action_result = await self.process(
                        game_state=game_state, char_manager=char_manager, loc_manager=loc_manager,
                        event_manager=event_manager, rule_engine=rule_engine, openai_service=openai_service,
                        ctx_channel_id=ctx_channel_id_for_action_ind, discord_user_id=character_obj_ind.discord_user_id, # Ensure discord_user_id is int
                        action_type=action_type_ind, action_data=action_data_ind, game_log_manager=game_log_manager
                    )
                    # TODO: game_state.game_manager does not exist. save_game_state_after_action needs to be called differently if needed.
                    # if bot.game_manager: # Assuming bot instance is available here, or pass it.
                    #     await bot.game_manager.save_game_state_after_action(str(game_state.server_id))
                    all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, **single_action_result})
                    if single_action_result.get("state_changed", False):
                        overall_state_changed_for_party = True
            except json.JSONDecodeError: # This was mis-indented
                all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Invalid actions JSON.", "state_changed": False})
            except Exception as e_inner: # This was mis-indented
                traceback.print_exc()
                all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": f"Unexpected error: {e_inner}", "state_changed": False})

        return { # This was mis-indented
            "success": True,
            "individual_action_results": all_individual_results,
            "overall_state_changed": overall_state_changed_for_party
        }