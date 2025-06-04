# bot/game/action_processor.py (updated process method implementation for 'move')
import json
from typing import Dict, Any, Optional, List
from typing import Dict, Any, Optional, List
from typing import Dict, Any, Optional, List

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character
from bot.game.models.location import Location

# Import managers
from bot.game.managers.character_manager import CharacterManager # Used to update character
from bot.game.managers.location_manager import LocationManager # Used to find locations/exits
from bot.game.managers.event_manager import EventManager

# Import other managers if needed (e.g. for action_type = "combat")
# from bot.game.managers.npc_manager import NpcManager


# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine # If movement needs rule checks
from bot.game.rules import skill_rules # If skill_check rule is needed


class ActionProcessor:
    def __init__(self):
        print("ActionProcessor initialized.")
    def __init__(self):
        print("ActionProcessor initialized.")
    def __init__(self):
        print("ActionProcessor initialized.")


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
                      action_data: Dict[str, Any]
                      action_data: Dict[str, Any]
                      action_data: Dict[str, Any]
                      ) -> Dict[str, Any]:
"""
        Processes a player action. Determines target, calls rules/managers, involves event manager,
        uses AI for narrative, and returns structured response data including message and target channel.
        Receives all necessary managers, services, and context for the specific action.
        Returns: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # --- Initial Checks (Same) ---
        character = char_manager.get_character_by_discord_id(discord_user_id)
        # --- Initial Checks (Same) ---
        character = char_manager.get_character_by_discord_id(discord_user_id)
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        current_location_id = getattr(character, 'current_location_id', None)
        location = await loc_manager.get_location(current_location_id, guild_id=game_state.guild_id) if current_location_id else None
        if not location:
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        output_channel_id = loc_manager.get_location_channel(game_state, location.id) or ctx_channel_id


        # --- Check for actions targeting an event first (Logic might be in EventManager's process method) ---
        # ActionProcessor determines if the action is relevant to *any* active event in the location.
        # If relevant, it passes ALL handling to EventManager.process_player_action_within_event.
        # EventManager must return a compatible dict structure.

        active_events = event_manager.get_active_events_in_location(location.id)
        relevant_event_id = None
        # Basic relevancy check: if ANY event is active and action *could* be interactive with it.
        location = loc_manager.get_location(character.current_location_id)
        if not location:
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        output_channel_id = loc_manager.get_location_channel(game_state, location.id) or ctx_channel_id


        # --- Check for actions targeting an event first (Logic might be in EventManager's process method) ---
        # ActionProcessor determines if the action is relevant to *any* active event in the location.
        # If relevant, it passes ALL handling to EventManager.process_player_action_within_event.
        # EventManager must return a compatible dict structure.

        active_events = event_manager.get_active_events_in_location(location.id)
        relevant_event_id = None
        # Basic relevancy check: if ANY event is active and action *could* be interactive with it.
        is_potentially_event_interactive = action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"]

        # Simple: if interactive and there are events, pick the first. Needs refinement!
        if is_potentially_event_interactive and active_events:
             relevant_event_id = active_events[0].id # simplistic

        if relevant_event_id:
             character_name = getattr(character, 'name', 'Unknown Character')
             print(f"Action {action_type} for {character_name} routed to event {relevant_event_id}.")
             # Pass all needed components to EventManager method
             # This signature must match what EventManager.process_player_action_within_event expects!
             event_response = await event_manager.process_player_action_within_event( # Assuming this method is async
                 event_id=relevant_event_id,
                 player_id=character.id, # Assuming character.id is correct
                 action_type=action_type,
                 action_data=action_data,
                 character_manager=char_manager,
                 loc_manager=loc_manager,
                 rule_engine=rule_engine,
                 openai_service=openai_service,
                 ctx_channel_id=ctx_channel_id, # Still needed for event manager to potentially return this as fallback
                 # Pass other managers needed by EventManager here (e.g., NpcManager)
                 # npc_manager = npc_manager,
                 # combat_manager = combat_manager,
             )
             # EventManager must return a dict: {"success":bool, "message":str, "target_channel_id":int, "state_changed":bool, ...}
             # ActionProcessor just returns whatever EventManager returned.
             if 'target_channel_id' not in event_response: event_response['target_channel_id'] = output_channel_id
             if 'state_changed' not in event_response: event_response['state_changed'] = False
             return event_response
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
             print(f"Action {action_type} for {character.name} routed to event {relevant_event_id}.")
             # Pass all needed components to EventManager method
             # This signature must match what EventManager.process_player_action_within_event expects!
             event_response = await event_manager.process_player_action_within_event(
                 event_id=relevant_event_id,
                 player_id=character.id,
                 action_type=action_type,
                 action_data=action_data,
                 character_manager=char_manager,
                 loc_manager=loc_manager,
                 rule_engine=rule_engine,
                 openai_service=openai_service,
                 ctx_channel_id=ctx_channel_id, # Still needed for event manager to potentially return this as fallback
                 # Pass other managers needed by EventManager here (e.g., NpcManager)
                 # npc_manager = npc_manager,
                 # combat_manager = combat_manager,
             )
             # EventManager must return a dict: {"success":bool, "message":str, "target_channel_id":int, "state_changed":bool, ...}
             # ActionProcessor just returns whatever EventManager returned.
             if 'target_channel_id' not in event_response: event_response['target_channel_id'] = output_channel_id
             if 'state_changed' not in event_response: event_response['state_changed'] = False
             return event_response


        # --- Process as Regular World Interaction if not Event Action ---
        print(f"Processing regular action '{action_type}' for player '{character.name}' at '{location.name}'.")

        # --- Process as Regular World Interaction if not Event Action ---
        character_name = getattr(character, 'name', 'Unknown Character')
        location_name = getattr(location, 'name', 'Unknown Location')
        print(f"Processing regular action '{action_type}' for player '{character_name}' at '{location_name}'.")

        # --- Handle Specific Action Types ---
        # Initialize common response variables
        response_success: bool = False
        response_message: str = ""
        response_target_channel_id: int = output_channel_id
        response_state_changed: bool = False
        # --- Handle Specific Action Types ---

        if action_type == "look":
            # ... (Same look logic, returns standard dict format) ...
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{character.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location.name}', Шаблон описания: '''{location.description_template[:200]}'''. "
                f"Опиши локацию для персонажа '{character.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location.name}', Шаблон описания: '''{location.description_template[:200]}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in char_manager.get_characters_in_location(location.id) if c.id != character.id][:3]) if char_manager.get_characters_in_location(location.id) else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in char_manager.get_characters_in_location(location.id) if c.id != character.id][:3]) if char_manager.get_characters_in_location(location.id) else 'нет'}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)
            return {"success": True, "message": f"**Локация:** {location.name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}


        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # TODO: Implement loc_manager.get_exit_target and ensure parameters are correct
            # target_location_instance_data = loc_manager.get_exit_target(character.location_id, destination_input, guild_id=str(game_state.server_id))
            target_location_instance_data: Optional[Dict[str,Any]] = None # Placeholder

            # Use LocationManager to find target location by exit direction or name/ID
            target_location = loc_manager.get_exit_target(location.id, destination_input) # Checks direction AND accessible by name/ID

            if not target_location:
                # LocationManager.get_exit_target handles the checks if the input is a valid/accessible exit or connected location by name.
                # If it returns None, the destination input doesn't match any valid exit from the current location.
            # --- FULL Movement Logic Implementation ---

            # Use LocationManager to find target location by exit direction or name/ID
            target_location = loc_manager.get_exit_target(location.id, destination_input) # Checks direction AND accessible by name/ID

            if not target_location:
                # LocationManager.get_exit_target handles the checks if the input is a valid/accessible exit or connected location by name.
                # If it returns None, the destination input doesn't match any valid exit from the current location.
                return {"success": False, "message": f"**Мастер:** Неизвестное направление или путь: '{destination_input}'. Отсюда туда нельзя попасть.", "target_channel_id": output_channel_id, "state_changed": False}


            # --- If reached here, target_location is a valid and accessible destination ---
            # Optional: Add RuleEngine check for movement cost, obstacles, checks (e.g., Stealth check to move quietly)
            # This would involve calling RuleEngine.perform_check()
            # if (movement needs a skill check, e.g. stealth_move):
            #     check_result = rule_engine.perform_check(...)
            #     if check_result['is_success']: actual move, else fail move or consequence

            # For now, basic move is always successful (no checks, no cost)

            # Update character's location using CharacterManager
            char_manager.update_character_location(character.id, target_location.id)
            # State has changed -> GameManager will be signaled by "state_changed": True


            # --- Use AI to describe the movement ---
            # Determine the specific exit description used for prompt
            exit_description_for_prompt = destination_input # Default to user input
            # Find the *exact* exit object used, if possible, to use its defined direction
            found_exit = next((exit for exit in location.exits if exit.get("target_location_id") == target_location.id), None)
            if found_exit:
                exit_description_for_prompt = found_exit.get("direction") # Use the defined exit direction


            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt = (
                f"Персонаж '{character.name}' перемещается из локации '{location.name}' через '{exit_description_for_prompt}' "
                f"в локацию '{target_location.name}'. "
                f"Краткое описание начальной локации: {location.description_template[:150]}. "
                f"Краткое описание конечной локации: {target_location.description_template[:150]}. "
                # Add current weather, time of day from GameState/TimeManager if available
                # Mention any visible details about the path or destination from this approach
                f"Опиши краткое путешествие и прибытие в '{target_location.name}'. Будь атмосферным и мрачным. В конце явно укажи, что персонаж теперь находится в '{target_location.name}'." # Make AI clearly state new location
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=250)

            # Determine where to send the description (usually the destination location's mapped channel)
            destination_channel_id = loc_manager.get_location_channel(game_state, target_location.id)
            # If destination channel is not mapped, use the channel where command was issued
            final_output_channel_id = destination_channel_id if destination_channel_id else output_channel_id


            # Send description and indicate state change for GameManager to save
            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": final_output_channel_id, "state_changed": True}


        elif action_type == "skill_check":
             # ... (Same skill_check logic, uses RuleEngine and returns dict with state_changed=False/True) ...
             skill_name = action_data.get("skill_name")
             complexity = action_data.get("complexity", "medium")
             base_modifiers = action_data.get("modifiers", {})
             target_description = action_data.get("target_description", "чего-то")

             # Get Environment Modifiers (Needs method in LocManager)
             env_modifiers = {}
             # if loc_manager method exists: env_modifiers = loc_manager.get_environmental_skill_modifiers(location.id, skill_name)

             # Get Status Modifiers (Needs method in CharManager)
             status_modifiers = {}
             # if char_manager method exists: status_modifiers = char_manager.get_status_skill_modifiers(character.id, skill_name)

             final_modifiers = {**env_modifiers, **status_modifiers, **base_modifiers}


             if not skill_name:
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Basic skill existence check using CharacterManager (better than checking raw dict)
             # Need method char_manager.character_has_skill(character.id, skill_name)
             # For now, directly check the character object's skills dict
             character_skills = getattr(character, 'skills', {})
             if skill_name not in character_skills:
             # Basic skill existence check using CharacterManager (better than checking raw dict)
             # Need method char_manager.character_has_skill(character.id, skill_name)
             # For now, directly check the character object's skills dict
             if skill_name not in character.skills:
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Get base DC from rules or helper (RuleEngine.get_base_dc might be better location for helper)
             base_dc = skill_rules.get_base_dc(complexity)

             # Perform the skill check using the RuleEngine
             # RuleEngine needs Character data -> Pass the character object OR its ID
             # The current RuleEngine.perform_check expects char_id and fetches data internally.
             check_result = rule_engine.perform_check(
                 character_id=character.id, # Pass character ID
                 check_type="skill",
                 skill_name=skill_name,
                 base_dc=base_dc,
                 modifiers=final_modifiers
             )

             if not check_result:
                  return {"success": False, "message": f"**Мастер:** Произошла ошибка при выполнении проверки навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Use AI to describe the outcome
             character_name = getattr(character, 'name', 'Unknown Character')
             character_stats = getattr(character, 'stats', {})
             location_name = getattr(location, 'name', 'Unknown Location')
             location_description_template = getattr(location, 'description_template', 'A non-descript area.')
             system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай действия и их результаты детализированно и атмосферно."
             user_prompt = (
                 f"Персонаж '{character_name}' (Навыки: {list(character_skills.keys())}, Статы: {list(character_stats.keys())}) "
                 f"попытался совершить действие, связанное с навыком '{skill_name}', целью было {target_description}. "
                 f"Ситуация: локация '{location_name}', атмосферное описание: {location_description_template[:150]}..."
                 f"Механический результат проверки:\n{json.dumps(check_result, ensure_ascii=False)}\n"
                 f"Опиши, КАК это выглядело и ощущалось в мире. Учитывай результат (Успех/Провал/Крит) и контекст. Будь мрачным и детализированным."
             )
             description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=300)

             mech_summary = check_result.get("description", "Проверка выполнена.")
             state_changed = check_result.get("is_critical_failure", False) # Crit fail might change state


             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed}
             # OpenAI call (uses openai_service passed to process)
             # ... (OpenAI prompt generation logic, ensure location_name_display and current_location_instance.get('description_template') are used) ...
             description = "Результат проверки навыка (placeholder AI description)." # Placeholder AI description, already initialized

             mech_summary = check_result.get("description", "Проверка выполнена.") # Already initialized
             state_changed_from_check = check_result.get("is_critical_failure", False) # Already initialized

             if game_log_manager and character:
                # Ensure channel_id is int or None for log_event
                channel_id_to_log: Optional[int] = None
                if isinstance(ctx_channel_id, int):
                    channel_id_to_log = ctx_channel_id
                elif isinstance(ctx_channel_id, str):
                    try:
                        channel_id_to_log = int(ctx_channel_id)
                    except ValueError:
                        print(f"Warning: Could not convert channel_id '{ctx_channel_id}' to int for logging skill check.")

                await game_log_manager.log_event(
                    guild_id=str(game_state.server_id),
                    event_type="player_action",
                    message=f"{character_name_display} attempted skill check {skill_name} for {target_description}. Success: {check_result.get('is_success')}. Details: {mech_summary}", # Added mech_summary to log
                    related_entities=[{"id": str(character.id), "type": "character"}],
                    channel_id=channel_id_to_log, # Use converted value
                    metadata={"skill_name": skill_name, "complexity": complexity, "result": check_result}
                )
            # Ensure correct indentation for this return if it was the unindent issue. The log_msg was above it.
            # The log_msg variable is not used here, so the unindent issue might have been about this block.
            # Assuming the log_msg was meant for the string below, and its construction was unindented.
            # The prompt seems to indicate the log_msg = f"..." line itself was unindented.
            # If this log_msg was for a different logging system, it's now correctly part of game_log_manager.
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
                character_obj: Optional[CharacterModel] = char_manager.get_character(guild_id=str(game_state.server_id), character_id=character_id_str) # Removed await, added guild_id
                if not character_obj:
                    print(f"ActionProcessor: Character {character_id_str} not found during conflict analysis. Skipping.")
                    # continue # This was a "continue can be used only within a loop" error source if this loop was removed/refactored.
                               # Now it's fine as it's inside the for loop.
                    parsed_actions_map[character_id_str] = [] # Ensure key exists even if char not found or no actions
                    continue


        # --- Add Handlers for other core Action Types (placeholder) ---
        # elif action_type == "interact": ...
        # elif action_type == "attack": ...
        # elif action_type == "use_item": ...
        # elif action_type == "craft": ...


        # Placeholder response for unhandled action types
        print(f"Action type '{action_type}' not handled by any specific processor.")
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается.", "target_channel_id": ctx_channel_id, "state_changed": False}
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
            character_obj_ind: Optional[CharacterModel] = char_manager.get_character(guild_id=str(game_state.server_id), character_id=char_id_loop_ind) # Removed await, added guild_id
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
