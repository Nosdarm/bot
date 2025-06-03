# bot/game/action_processor.py (updated process method implementation for 'move')
import json
import traceback
from typing import Dict, Any, Optional, List, Tuple

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

        # --- Initial Checks (Same) ---
        character = char_manager.get_character_by_discord_id(discord_user_id)
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

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

        # --- Handle Specific Action Types ---

        if action_type == "look":
            # ... (Same look logic, returns standard dict format) ...
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{character.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location.name}', Шаблон описания: '''{location.description_template[:200]}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in char_manager.get_characters_in_location(location.id) if c.id != character.id][:3]) if char_manager.get_characters_in_location(location.id) else 'нет'}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)

            # Logging before return
            if game_log_manager and character:
                await game_log_manager.log_event(
                    guild_id=str(game_state.guild_id),
                    event_type="player_action",
                    message=f"{character.name} used {action_type} to look at {location.name}.",
                    related_entities=[{"id": str(character.id), "type": "character"}, {"id": str(location.id), "type": "location"}],
                    channel_id=str(ctx_channel_id)
                )
            return {"success": True, "message": f"**Локация:** {location.name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}


        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

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

            # Logging before return
            if game_log_manager and character and target_location:
                await game_log_manager.log_event(
                    guild_id=str(game_state.guild_id),
                    event_type="player_action",
                    message=f"{character.name} moved from {location.name} to {target_location.name}.",
                    related_entities=[
                        {"id": str(character.id), "type": "character"},
                        {"id": str(location.id), "type": "location"},
                        {"id": str(target_location.id), "type": "location"}
                    ],
                    channel_id=str(ctx_channel_id)
                )
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
             system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай действия и их результаты детализированно и атмосферно."
             user_prompt = (
                 f"Персонаж '{character.name}' (Навыки: {list(character.skills.keys())}, Статы: {list(character.stats.keys())}) "
                 f"попытался совершить действие, связанное с навыком '{skill_name}', целью было {target_description}. "
                 f"Ситуация: локация '{location.name}', атмосферное описание: {location.description_template[:150]}..."
                 f"Механический результат проверки:\n{json.dumps(check_result, ensure_ascii=False)}\n"
                 f"Опиши, КАК это выглядело и ощущалось в мире. Учитывай результат (Успех/Провал/Крит) и контекст. Будь мрачным и детализированным."
             )
             description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=300)

             mech_summary = check_result.get("description", "Проверка выполнена.")
             state_changed = check_result.get("is_critical_failure", False) # Crit fail might change state

             # Logging before return
             if game_log_manager and character:
                 await game_log_manager.log_event(
                     guild_id=str(game_state.guild_id),
                     event_type="player_action",
                     message=f"{character.name} attempted skill check {skill_name} for {target_description}. Success: {check_result.get('is_success')}",
                     related_entities=[{"id": str(character.id), "type": "character"}],
                     channel_id=str(ctx_channel_id),
                     metadata={"skill_name": skill_name, "complexity": complexity, "result": check_result}
                 )
             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed}


        # --- Add Handlers for other core Action Types (placeholder) ---
        # elif action_type == "interact": ...
        # elif action_type == "attack": ...
        # elif action_type == "use_item": ...
        # elif action_type == "craft": ...
        # ... other specific action handlers ...

        # Final catch-all for unhandled action types
        print(f"Action type '{action_type}' not handled by any specific processor in self.process.")
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается или не распознано.", "target_channel_id": ctx_channel_id, "state_changed": False}

    async def process_party_actions(self,
                                game_state: GameState,
                                char_manager: CharacterManager,
                                loc_manager: LocationManager,
                                event_manager: EventManager,
                                rule_engine: RuleEngine,
                                openai_service: OpenAIService,
                                party_actions_data: List[Tuple[str, str]],  # List[(character_id, collected_actions_json_string)]
                                ctx_channel_id_fallback: int,
                                conflict_resolver: Optional[ConflictResolver] = None,
                                game_log_manager: Optional[GameLogManager] = None
                                ) -> Dict[str, Any]:
        """
        Processes actions for a list of characters, typically a party.
        If a ConflictResolver is provided, it first analyzes actions for conflicts.
        Otherwise, it iterates through each character's collected actions and calls self.process for each.
        """
        # Prioritize argument-passed conflict_resolver, then instance's, then None
        current_conflict_resolver = conflict_resolver if conflict_resolver else self._conflict_resolver

        if current_conflict_resolver:
            print(f"ActionProcessor: Using ConflictResolver for party actions.")
            parsed_actions_map: Dict[str, List[Dict[str, Any]]] = {}
            character_objects: Dict[str, Character] = {} # Store fetched character objects

            for character_id, collected_actions_json_string in party_actions_data:
                # Assuming character_id from party_actions_data is the Character UUID.
                # CharacterManager's get_character is synchronous.
                character = char_manager.get_character(game_state.guild_id, character_id)
                if not character:
                    print(f"ActionProcessor: Character {character_id} not found during conflict analysis prep. Skipping.")
                    # Potentially log this as an issue or add to a list of unprocessed players
                    continue
                character_objects[character_id] = character # Store for potential later use by ConflictResolver

                if not collected_actions_json_string or collected_actions_json_string.strip() == "[]":
                    parsed_actions_map[character_id] = []
                    continue
                try:
                    actions_list = json.loads(collected_actions_json_string)
                    if not isinstance(actions_list, list):
                        print(f"ActionProcessor: Parsed actions for {character.name} is not a list (for conflict analysis). Skipping.")
                        parsed_actions_map[character_id] = [] # Or handle error appropriately
                        continue
                    
                    # Store actions with character_id for context, ConflictResolver might need it
                    # The 'intent' and 'entities' structure matches what ConflictResolver might expect
                    processed_actions_for_char = []
                    for action_item in actions_list:
                        if isinstance(action_item, dict) and "intent" in action_item:
                             # Add player_id to each action for easier lookup in ConflictResolver
                            action_with_context = {
                                "player_id": character_id, # Or character.id, ensure consistency
                                "type": action_item.get("intent"),
                                **action_item.get("entities", {}), # Spread entities like target_space
                                "original_text": action_item.get("original_text", "N/A")
                            }
                            processed_actions_for_char.append(action_with_context)
                        else:
                            print(f"Skipping malformed action item for {character_id}: {action_item}")
                    parsed_actions_map[character_id] = processed_actions_for_char

                except json.JSONDecodeError:
                    print(f"ActionProcessor: Failed to parse JSON for {character_id} during conflict analysis. Skipping.")
                    parsed_actions_map[character_id] = [] # Or handle error

            if not parsed_actions_map:
                print("ActionProcessor: No valid actions parsed for conflict analysis.")
                return {"success": True, "message": "No actions to analyze for conflicts.", "individual_action_results": [], "overall_state_changed": False}

            print(f"ActionProcessor: Calling ConflictResolver.analyze_actions_for_conflicts with map for players: {list(parsed_actions_map.keys())}")
            
            # Pass the character_objects map if your ConflictResolver needs full character data
            # For now, analyze_actions_for_conflicts expects Dict[str, List[Dict[str, Any]]]
            # analyze_actions_for_conflicts is currently synchronous.
            identified_conflicts = current_conflict_resolver.analyze_actions_for_conflicts(player_actions_map=parsed_actions_map)

            if identified_conflicts:
                print(f"ActionProcessor: Identified {len(identified_conflicts)} conflicts:")
                for conflict in identified_conflicts:
                    print(f"  - Conflict: {conflict}")
                # Further processing will involve iterating these conflicts and calling
                # resolve_conflict_automatically or prepare_for_manual_resolution.
                # For now, just log and return.
                if game_log_manager:
                    await game_log_manager.log_event(
                        guild_id=str(game_state.guild_id),
                        event_type="conflict_identification",
                        message=f"{len(identified_conflicts)} conflicts identified for party.",
                        related_entities=[{"id": p_id, "type": "character"} for p_id in parsed_actions_map.keys()],
                        # metadata={"conflicts": identified_conflicts} # This might be too verbose for logs
                    )
                return {"success": True, "message": f"Conflict analysis initiated. {len(identified_conflicts)} potential conflicts found.", "identified_conflicts": identified_conflicts, "individual_action_results": [], "overall_state_changed": False} # Placeholder
            else:
                print("ActionProcessor: No conflicts identified by ConflictResolver. Proceeding with individual action processing (or could stop here if desired).")
                # If no conflicts, you might choose to then process actions individually as before,
                # or this might be the end of the party turn if all actions must be conflict-free.
                # For now, returning a message indicating no conflicts.
                # To process individually, you'd call the original loop here.
                # This part of the logic (what to do if no conflicts) needs to be defined.
                # For this iteration, we'll assume if conflict resolver is on, its job is to find them,
                # and subsequent steps would handle resolution. If none, the turn might be "clean".
                return {"success": True, "message": "No conflicts identified. Actions not processed further in this path yet.", "individual_action_results": [], "overall_state_changed": False}

        # Original behavior if no conflict_resolver is available
        print(f"ActionProcessor: Starting process_party_actions (individual processing) for {len(party_actions_data)} characters.")
        all_individual_results = []
        overall_state_changed_for_party = False
        
        for character_id, collected_actions_json_string in party_actions_data:
            # Assuming character_id from party_actions_data is the Character UUID.
            # CharacterManager's get_character is synchronous.
            character = char_manager.get_character(game_state.guild_id, character_id)
            if not character:
                print(f"ActionProcessor: Character {character_id} not found. Skipping.")
                all_individual_results.append({"character_id": character_id, "success": False, "message": "Character not found.", "state_changed": False})
                continue

            if not collected_actions_json_string or collected_actions_json_string.strip() == "[]":
                print(f"ActionProcessor: No actions for {character.name}. Skipping.")
                all_individual_results.append({"character_id": character_id, "success": True, "message": "No actions submitted.", "state_changed": False})
                continue

            try:
                actions_list = json.loads(collected_actions_json_string)
                if not isinstance(actions_list, list):
                    all_individual_results.append({"character_id": character_id, "success": False, "message": "Malformed actions data.", "state_changed": False})
                    continue

                for action_item_idx, action_item in enumerate(actions_list):
                    if not isinstance(action_item, dict): continue
                    action_type = action_item.get("intent")
                    action_data = action_item.get("entities", {})
                    original_text = action_item.get("original_text", "N/A")
                    if not action_type:
                        all_individual_results.append({"character_id": character_id, "action_original_text": original_text, "success": False, "message": "Action intent missing.", "state_changed": False})
                        continue
                    
                    # loc_manager.get_location is likely synchronous if it uses a cache.
                    char_location = loc_manager.get_location(character.current_location_id, game_state.guild_id)
                    ctx_channel_id_for_action = ctx_channel_id_fallback
                    if char_location and char_location.channel_id:
                        try: ctx_channel_id_for_action = int(char_location.channel_id)
                        except ValueError: pass

                    single_action_result = await self.process(
                        game_state=game_state, char_manager=char_manager, loc_manager=loc_manager,
                        event_manager=event_manager, rule_engine=rule_engine, openai_service=openai_service,
                        ctx_channel_id=ctx_channel_id_for_action, discord_user_id=character.discord_user_id,
                        action_type=action_type, action_data=action_data, game_log_manager=game_log_manager
                    )
                    if game_state.game_manager:
                        await game_state.game_manager.save_game_state_after_action(game_state.guild_id)
                    all_individual_results.append({"character_id": character_id, "action_original_text": original_text, **single_action_result})
                    if single_action_result.get("state_changed", False):
                        overall_state_changed_for_party = True
            except json.JSONDecodeError:
                all_individual_results.append({"character_id": character_id, "success": False, "message": "Invalid actions JSON.", "state_changed": False})
            except Exception as e:
                traceback.print_exc()
                all_individual_results.append({"character_id": character_id, "success": False, "message": f"Unexpected error: {e}", "state_changed": False})

        return {
            "success": True,
            "individual_action_results": all_individual_results,
            "overall_state_changed": overall_state_changed_for_party
        }
