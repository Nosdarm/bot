# bot/game/action_processor.py (updated process method implementation for 'move')
import json
import traceback # Needed for printing exceptions
from typing import Dict, Any, Optional, List, Tuple # Added Tuple

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character # Assuming Character is the model class
from bot.game.models.location import Location # Assuming Location is the model class

# Import managers
from bot.game.managers.character_manager import CharacterManager # Used to update character
from bot.game.managers.location_manager import LocationManager # Used to find locations/exits
from bot.game.managers.event_manager import EventManager
# Assume imports for GameLogManager and ConflictResolver exist if needed
from bot.game.managers.game_log_manager import GameLogManager # Assuming path
from bot.game.conflict_resolver import ConflictResolver # Assuming path


# Import other managers if needed (e.g. for action_type = "combat")
# from bot.game.managers.npc_manager import NpcManager
# from bot.game.managers.item_manager import ItemManager
# from bot.game.managers.combat_manager import CombatManager
# from bot.game.managers.time_manager import TimeManager


# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine # If movement needs rule checks
from bot.game.rules import skill_rules # If skill_check rule is needed

# Assume CharacterModel is imported from bot.game.models.character or similar
from bot.game.models.character import Character as CharacterModel

class ActionProcessor:
    # Removed duplicate __init__ methods
    def __init__(self):
        print("ActionProcessor initialized.")
        # Assume conflict_resolver is an optional dependency, maybe set later
        self._conflict_resolver: Optional[ConflictResolver] = None

    # Method to set conflict resolver if needed
    def set_conflict_resolver(self, resolver: ConflictResolver):
        self._conflict_resolver = resolver

    # Removed duplicate parameters
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
                      discord_user_id: int, # Ensure this is an int
                      action_type: str,
                      action_data: Dict[str, Any],
                      game_log_manager: Optional[GameLogManager] = None # Added as per usage
                      ) -> Dict[str, Any]:
        """
        Processes a player action. Determines target, calls rules/managers, involves event manager,
        uses AI for narrative, and returns structured response data including message and target channel.
        Receives all necessary managers, services, and context for the specific action.
        Returns: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # --- Initial Checks ---
        # Removed duplicate checks
        character = char_manager.get_character_by_discord_id(discord_user_id)
        if not character:
            # Correct indentation for return
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # Ensure guild_id is consistently string
        guild_id_str_process = str(game_state.server_id)

        current_location_id = getattr(character, 'current_location_id', None)
        # Assuming get_location is async
        location = await loc_manager.get_location(current_location_id, guild_id=guild_id_str_process) if current_location_id else None
        if not location:
            # Correct indentation for return
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        output_channel_id = loc_manager.get_location_channel(game_state, location.id) or ctx_channel_id

        # Log start of action processing
        if game_log_manager and character:
            char_name_log = getattr(character, 'name_i18n', {}).get(character.selected_language, getattr(character, 'name', character.id))
            loc_name_log = getattr(location, 'name_i18n', {}).get(character.selected_language, getattr(location, 'name', location.id))
            await game_log_manager.log_event(
                guild_id=guild_id_str_process,
                event_type="player_action_start",
                message=f"Processing action '{action_type}' for {char_name_log} in {loc_name_log}.",
                related_entities=[{"id": str(character.id), "type": "character"}, {"id": str(location.id), "type": "location"}],
                channel_id=ctx_channel_id,
                metadata={"action_type": action_type, "action_data": action_data}
            )


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

        # Correct indentation for the event handling block
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
             # Correct indentation for return inside the if block
             return event_response

        # --- Regular World Interaction ---
        # Use character.name_i18n, location.name
        # Language lookup is complex, keeping simple name for now unless i18n is fully implemented
        character_name = getattr(character, 'name', 'Unknown Character')
        location_name = getattr(location, 'name', 'Unknown Location')
        print(f"Processing regular action '{action_type}' for player '{character_name}' at '{location_name}'.")

        # --- Handle Specific Action Types ---

        if action_type == "look":
            # ... (Same look logic, returns standard dict format) ...
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{character.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location.name}', Шаблон описания: '''{getattr(location, 'description_template', '')[:200]}'''. " # Use getattr for safety
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in char_manager.get_characters_in_location(location.id) if c.id != character.id][:3]) if char_manager.get_characters_in_location(location.id) else 'нет'}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)
            # Correct indentation for return inside the if block
            return {"success": True, "message": f"**Локация:** {location.name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}


        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 # Correct indentation for return inside the if block
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # Use LocationManager to find target location by exit direction or name/ID
            # Assuming get_exit_target is sync or returns a Location object
            target_location = loc_manager.get_exit_target(location.id, destination_input) # Checks direction AND accessible by name/ID

            if not target_location:
                # LocationManager.get_exit_target handles the checks if the input is a valid/accessible exit or connected location by name.
                # If it returns None, the destination input doesn't match any valid exit from the current location.
                # Correct indentation for return inside the if block
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
            # Assuming location.exits is a list of dicts or similar
            found_exit = next((exit for exit in getattr(location, 'exits', []) if exit.get("target_location_id") == target_location.id), None) # Use getattr for safety
            if found_exit:
                exit_description_for_prompt = found_exit.get("direction", destination_input) # Use the defined exit direction, fallback to input


            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt = (
                f"Персонаж '{character.name}' перемещается из локации '{location.name}' через '{exit_description_for_prompt}' "
                f"в локацию '{target_location.name}'. "
                f"Краткое описание начальной локации: {getattr(location, 'description_template', '')[:150]}. " # Use getattr
                f"Краткое описание конечной локации: {getattr(target_location, 'description_template', '')[:150]}. " # Use getattr
                # Add current weather, time of day from GameState/TimeManager if available
                # Mention any visible details about the path or destination from this approach
                f"Опиши краткое путешествие и прибытие в '{target_location.name}'. Будь атмосферным и мрачным. В конце явно укажи, что персонаж теперь находится в '{target_location.name}'." # Make AI clearly state new location
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=250)

            # Determine where to send the description (usually the destination location's mapped channel)
            # Assuming get_location_channel is sync
            destination_channel_id = loc_manager.get_location_channel(game_state, target_location.id)
            # If destination channel is not mapped, use the channel where command was issued
            final_output_channel_id = destination_channel_id if destination_channel_id else output_channel_id

            # Correct indentation for return inside the elif block
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
                  # Correct indentation for return inside the if block
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Basic skill existence check using CharacterManager (better than checking raw dict)
             # Need method char_manager.character_has_skill(character.id, skill_name)
             # For now, directly check the character object's skills dict
             character_skills = getattr(character, 'skills', {}) # Use getattr for safety
             # Removed duplicate skill check
             if skill_name not in character_skills:
                 # Correct indentation for return inside the if block
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Get base DC from rules or helper (RuleEngine.get_base_dc might be better location for helper)
             base_dc = skill_rules.get_base_dc(complexity)

             # Perform the skill check using the RuleEngine
             # RuleEngine needs Character data -> Pass the character object OR its ID
             # The current RuleEngine.perform_check expects char_id and fetches data internally.
             # Assuming perform_check is sync
             check_result = rule_engine.perform_check(
                 character_id=character.id, # Pass character ID
                 check_type="skill",
                 skill_name=skill_name,
                 base_dc=base_dc,
                 modifiers=final_modifiers
             )

             if not check_result:
                  # Correct indentation for return inside the if block
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
             state_changed_from_check = check_result.get("is_critical_failure", False) # Crit fail might change state


             if game_log_manager and character:
                # Ensure channel_id is int or None for log_event
                channel_id_to_log: Optional[int] = None
                # ctx_channel_id is already int in the signature
                channel_id_to_log = ctx_channel_id

                await game_log_manager.log_event(
                    guild_id=str(game_state.server_id), # Use game_state.server_id
                    event_type="player_action",
                    message=f"{character_name} attempted skill check {skill_name} for {target_description}. Success: {check_result.get('is_success')}. Details: {mech_summary}", # Added mech_summary to log
                    related_entities=[{"id": str(character.id), "type": "character"}],
                    channel_id=channel_id_to_log, # Use converted value
                    metadata={"skill_name": skill_name, "complexity": complexity, "result": check_result}
                )
             # Correct indentation for return inside the elif block
             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed_from_check}

        # --- Add Handlers for other core Action Types (placeholder) ---
        # elif action_type == "interact": ...
        # elif action_type == "attack": ...
        # elif action_type == "use_item": ...
        # elif action_type == "craft": ...


        # Fallback for unhandled actions - Correct indentation
        print(f"Action type '{action_type}' not handled by any specific processor in self.process.")
        # Correct indentation for return
        return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается или не распознано.", "target_channel_id": ctx_channel_id, "state_changed": False}


    async def process_party_actions(self,
                                game_state: GameState,
                                char_manager: CharacterManager,
                                loc_manager: LocationManager,
                                event_manager: EventManager,
                                rule_engine: RuleEngine,
                                openai_service: OpenAIService, # openai_service is passed in
                                party_actions_data: List[Tuple[str, str]], # List of (char_id_str, actions_json_string)
                                ctx_channel_id_fallback: int,
                                conflict_resolver: Optional[ConflictResolver] = None,
                                game_log_manager: Optional[GameLogManager] = None
                                ) -> Dict[str, Any]:
        guild_id_str = str(game_state.server_id)
        all_individual_results = []
        overall_state_changed_for_party = False

        if game_log_manager:
            await game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="party_actions_start",
                message=f"Starting processing for party actions. Characters involved: {len(party_actions_data)}.",
                channel_id=ctx_channel_id_fallback, # This channel is a fallback, actual actions might use location channels
                metadata={"num_characters_with_actions": len(party_actions_data)}
            )

        # Use the passed conflict_resolver or the instance attribute
        current_conflict_resolver = conflict_resolver if conflict_resolver else self._conflict_resolver

        if current_conflict_resolver:
            print(f"ActionProcessor: Using ConflictResolver for party actions in guild {guild_id_str}.")
            parsed_actions_map: Dict[str, List[Dict[str, Any]]] = {}
            for char_id_loop, collected_actions_json_loop in party_actions_data:
                character_obj: Optional[CharacterModel] = char_manager.get_character(guild_id=guild_id_str, character_id=char_id_loop)
                if not character_obj:
                    print(f"ActionProcessor: Character {char_id_loop} not found during conflict analysis prep. Skipping.")
                    parsed_actions_map[char_id_loop] = []
                    continue
                if not collected_actions_json_loop or collected_actions_json_loop.strip() == "[]":
                    parsed_actions_map[char_id_loop] = []
                    continue
                try:
                    actions_list = json.loads(collected_actions_json_loop)
                    parsed_actions_map[char_id_loop] = actions_list if isinstance(actions_list, list) else []
                except json.JSONDecodeError:
                    print(f"ActionProcessor: Invalid JSON for character {char_id_loop}. Skipping actions.")
                    parsed_actions_map[char_id_loop] = []

            conflict_resolution_bundle = await current_conflict_resolver.analyze_actions_for_conflicts(
                player_actions_map=parsed_actions_map,
                guild_id=guild_id_str
                # context can be passed here if analyze_actions_for_conflicts uses it
            )

            if conflict_resolution_bundle.get("requires_manual_resolution"):
                print(f"ActionProcessor: Conflicts require manual resolution for guild {guild_id_str}. Actions deferred.")
                # Log pending conflicts if GameLogManager is available
                if game_log_manager:
                    for conflict_detail in conflict_resolution_bundle.get("pending_conflict_details", []):
                        await game_log_manager.log_event(
                            guild_id=guild_id_str,
                            event_type="conflict_manual_pending",
                            message=f"Conflict ID {conflict_detail.get('conflict_id')} requires manual GM resolution.",
                            related_entities=conflict_detail.get("involved_entities", []),
                            metadata=conflict_detail
                        )
                return {
                    "success": True, # The process_party_actions itself succeeded in deferring
                    "message": "Actions involve conflicts that require GM intervention.",
                    "identified_conflicts": conflict_resolution_bundle.get("pending_conflict_details", []),
                    "individual_action_results": [], # No actions executed yet
                    "overall_state_changed": False
                }

            actions_to_execute_ordered = conflict_resolution_bundle.get("actions_to_execute", [])
            # Log auto-resolution outcomes if any
            if game_log_manager:
                 for auto_outcome in conflict_resolution_bundle.get("auto_resolution_outcomes", []):
                        await game_log_manager.log_event(
                            guild_id=guild_id_str,
                            event_type="conflict_auto_resolved",
                            message=f"Conflict ID {auto_outcome.get('conflict_id')} auto-resolved. Outcome: {auto_outcome.get('outcome',{}).get('description')}",
                            related_entities=auto_outcome.get("involved_entities", []),
                            metadata=auto_outcome
                        )

            print(f"ActionProcessor: Executing {len(actions_to_execute_ordered)} actions after conflict resolution for guild {guild_id_str}.")
            # This list `actions_to_execute_ordered` now contains dicts like:
            # {"character_id": str, "action_data": Dict}
            # where action_data is {"intent": ..., "entities": ..., "original_text": ...}

            for action_to_execute in actions_to_execute_ordered:
                char_id_exec = action_to_execute["character_id"]
                action_data_exec = action_to_execute["action_data"] # This is the NLU output
                original_text_log = action_data_exec.get("original_text", "N/A")
                action_intent_log = action_data_exec.get("intent", "N/A")

                character_obj_exec: Optional[CharacterModel] = char_manager.get_character(guild_id=guild_id_str, character_id=char_id_exec)
                if not character_obj_exec:
                    msg = f"Character {char_id_exec} not found for execution of action '{action_intent_log}' ('{original_text_log}')."
                    if game_log_manager:
                        await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_exec, "type": "character"}], metadata={"action_data": action_data_exec})
                    all_individual_results.append({"character_id": char_id_exec, "action_original_text": original_text_log, "success": False, "message": "Character not found for execution.", "state_changed": False})
                    continue

                char_location_instance_exec: Optional[Dict[str,Any]] = loc_manager.get_location_instance(guild_id=guild_id_str, instance_id=getattr(character_obj_exec, 'location_id', None))
                ctx_channel_id_for_action_exec = ctx_channel_id_fallback
                if char_location_instance_exec and char_location_instance_exec.get("channel_id"):
                    try: ctx_channel_id_for_action_exec = int(char_location_instance_exec["channel_id"])
                    except ValueError: pass

                if game_log_manager:
                    char_name_log_exec = getattr(character_obj_exec, 'name_i18n', {}).get(character_obj_exec.selected_language, getattr(character_obj_exec, 'name', char_id_exec))
                    await game_log_manager.log_event(
                        guild_id=guild_id_str,
                        event_type="party_action_item_start",
                        message=f"Executing action '{action_intent_log}' for {char_name_log_exec} (Original: '{original_text_log}') via conflict resolver.",
                        related_entities=[{"id": char_id_exec, "type": "character"}],
                        channel_id=ctx_channel_id_for_action_exec,
                        metadata={"action_data": action_data_exec}
                    )

                single_action_result = await self.process(
                    game_state=game_state, char_manager=char_manager, loc_manager=loc_manager,
                    event_manager=event_manager, rule_engine=rule_engine, openai_service=openai_service,
                    ctx_channel_id=ctx_channel_id_for_action_exec, discord_user_id=getattr(character_obj_exec, 'discord_user_id', None),
                    action_type=action_intent_log, action_data=action_data_exec.get("entities", {}),
                    game_log_manager=game_log_manager
                )

                if game_log_manager:
                     await game_log_manager.log_event(
                        guild_id=guild_id_str,
                        event_type="party_action_item_result",
                        message=f"Action '{action_intent_log}' for {char_name_log_exec} result: Success={single_action_result.get('success')}, StateChanged={single_action_result.get('state_changed')}. Message: {single_action_result.get('message')}",
                        related_entities=[{"id": char_id_exec, "type": "character"}],
                        channel_id=single_action_result.get('target_channel_id', ctx_channel_id_for_action_exec),
                        metadata={"action_result": single_action_result, "original_action_data": action_data_exec}
                    )

                all_individual_results.append({"character_id": char_id_exec, "action_original_text": original_text_log, **single_action_result})
                if single_action_result.get("state_changed", False):
                    overall_state_changed_for_party = True
                    # Persist changes immediately after this action if state changed
                    print(f"ActionProcessor: State changed after action by {char_id_exec}. Persisting relevant manager states for guild {guild_id_str}.")
                    if char_manager: await char_manager.save_state(guild_id=guild_id_str)
                    if loc_manager: await loc_manager.save_state(guild_id=guild_id_str)
                    # Add other relevant managers that might have been affected and need immediate persistence
                    # For example, if ItemManager or NpcManager were passed in and used by self.process:
                    # if item_manager: await item_manager.save_state(guild_id=guild_id_str)
                    # if npc_manager: await npc_manager.save_state(guild_id=guild_id_str)
                    # PartyManager state likely changes at a higher level (e.g. turn status) or if party structure changes.

            # Fall through to the common return structure

        else: # No conflict resolver, process actions sequentially as before
            if game_log_manager:
                await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_actions_no_conflict_resolver", message="No conflict resolver available. Processing actions sequentially.", metadata={"num_characters": len(party_actions_data)})
            print(f"ActionProcessor: No ConflictResolver. Processing party actions individually for {len(party_actions_data)} characters in guild {guild_id_str}.")
            for char_id_loop_ind, collected_actions_json_loop_ind in party_actions_data:
                character_obj_ind: Optional[CharacterModel] = char_manager.get_character(guild_id=guild_id_str, character_id=char_id_loop_ind)

                if not character_obj_ind:
                    msg = f"Character {char_id_loop_ind} not found. Skipping actions."
                    if game_log_manager:
                        await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}])
                    print(f"ActionProcessor: {msg}")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Character not found.", "state_changed": False})
                    continue

                char_name_log_ind = getattr(character_obj_ind, 'name_i18n', {}).get(character_obj_ind.selected_language, getattr(character_obj_ind, 'name', char_id_loop_ind))

                if not collected_actions_json_loop_ind or collected_actions_json_loop_ind.strip() == "[]":
                    msg = f"No actions submitted for {char_name_log_ind} ({char_id_loop_ind}). Skipping."
                    # This is normal, maybe don't log to game_log_manager unless verbose mode
                    print(f"ActionProcessor: {msg}")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": True, "message": "No actions submitted.", "state_changed": False})
                    continue
                try:
                    actions_list_ind = json.loads(collected_actions_json_loop_ind)
                    if not isinstance(actions_list_ind, list):
                        msg = f"Malformed actions data (not a list) for {char_name_log_ind} ({char_id_loop_ind})."
                        if game_log_manager:
                            await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}], metadata={"raw_actions": collected_actions_json_loop_ind})
                        all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Malformed actions data (not a list).", "state_changed": False})
                        continue

                    for action_item_ind in actions_list_ind:
                        if not isinstance(action_item_ind, dict):
                            msg = f"Skipping malformed action item for {char_name_log_ind} ({char_id_loop_ind}): {action_item_ind}"
                            if game_log_manager:
                                 await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}], metadata={"action_item": action_item_ind})
                            print(f"ActionProcessor: {msg}")
                            continue
                        action_type_ind = action_item_ind.get("intent")
                        action_data_ind = action_item_ind.get("entities", {})
                        original_text_ind = action_item_ind.get("original_text", "N/A")

                        if not action_type_ind:
                            msg = f"Action intent missing for {char_name_log_ind} ({char_id_loop_ind}). Original: '{original_text_ind}'"
                            if game_log_manager:
                                 await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}], metadata={"action_item": action_item_ind})
                            all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, "success": False, "message": "Action intent missing.", "state_changed": False})
                            continue

                        char_location_instance_ind: Optional[Dict[str,Any]] = loc_manager.get_location_instance(guild_id=guild_id_str, instance_id=getattr(character_obj_ind, 'location_id', None))
                        ctx_channel_id_for_action_ind = ctx_channel_id_fallback
                        if char_location_instance_ind and char_location_instance_ind.get("channel_id"):
                            try: ctx_channel_id_for_action_ind = int(char_location_instance_ind["channel_id"])
                            except ValueError: pass

                        if game_log_manager:
                            await game_log_manager.log_event(
                                guild_id=guild_id_str,
                                event_type="party_action_item_start",
                                message=f"Executing action '{action_type_ind}' for {char_name_log_ind} (Original: '{original_text_ind}') sequentially.",
                                related_entities=[{"id": char_id_loop_ind, "type": "character"}],
                                channel_id=ctx_channel_id_for_action_ind,
                                metadata={"action_item": action_item_ind}
                            )

                        single_action_result = await self.process(
                            game_state=game_state, char_manager=char_manager, loc_manager=loc_manager,
                            event_manager=event_manager, rule_engine=rule_engine, openai_service=openai_service,
                            ctx_channel_id=ctx_channel_id_for_action_ind, discord_user_id=getattr(character_obj_ind, 'discord_user_id', None),
                            action_type=action_type_ind, action_data=action_data_ind, game_log_manager=game_log_manager
                        )

                        if game_log_manager:
                            await game_log_manager.log_event(
                                guild_id=guild_id_str,
                                event_type="party_action_item_result",
                                message=f"Action '{action_type_ind}' for {char_name_log_ind} result: Success={single_action_result.get('success')}, StateChanged={single_action_result.get('state_changed')}. Message: {single_action_result.get('message')}",
                                related_entities=[{"id": char_id_loop_ind, "type": "character"}],
                                channel_id=single_action_result.get('target_channel_id', ctx_channel_id_for_action_ind),
                                metadata={"action_result": single_action_result, "original_action_item": action_item_ind}
                            )

                        all_individual_results.append({"character_id": char_id_loop_ind, "action_original_text": original_text_ind, **single_action_result})
                        if single_action_result.get("state_changed", False):
                            overall_state_changed_for_party = True
                            # Persist changes immediately after this action if state changed
                            print(f"ActionProcessor: State changed after action by {char_id_loop_ind}. Persisting relevant manager states for guild {guild_id_str}.")
                            if char_manager: await char_manager.save_state(guild_id=guild_id_str)
                            if loc_manager: await loc_manager.save_state(guild_id=guild_id_str)
                            # Add other relevant managers that might have been affected and need immediate persistence
                            # For example, if ItemManager or NpcManager were passed in and used by self.process:
                            # if item_manager: await item_manager.save_state(guild_id=guild_id_str)
                            # if npc_manager: await npc_manager.save_state(guild_id=guild_id_str)
                            # PartyManager state likely changes at a higher level (e.g. turn status) or if party structure changes.
                except json.JSONDecodeError:
                    msg = f"Invalid actions JSON for {char_name_log_ind} ({char_id_loop_ind}). Skipping actions. Error: {e}"
                    if game_log_manager:
                        await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}], metadata={"raw_actions": collected_actions_json_loop_ind, "error": str(e)})
                    print(f"ActionProcessor: {msg}")
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": "Invalid actions JSON.", "state_changed": False})
                except Exception as e_inner:
                    msg = f"Unexpected error processing actions for {char_name_log_ind} ({char_id_loop_ind}): {e_inner}"
                    if game_log_manager:
                        await game_log_manager.log_event(guild_id=guild_id_str, event_type="party_action_unexpected_error", message=msg, related_entities=[{"id": char_id_loop_ind, "type": "character"}], metadata={"error": str(e_inner), "trace": traceback.format_exc()})
                    print(f"ActionProcessor: {msg}")
                    traceback.print_exc()
                    all_individual_results.append({"character_id": char_id_loop_ind, "success": False, "message": f"Unexpected error: {e_inner}", "state_changed": False})

        if game_log_manager:
            await game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="party_actions_end",
                message=f"Finished processing party actions. Overall state changed: {overall_state_changed_for_party}. Results count: {len(all_individual_results)}.",
                channel_id=ctx_channel_id_fallback,
                metadata={"overall_state_changed": overall_state_changed_for_party, "num_results": len(all_individual_results)}
            )
        # This return is now common for both paths (with or without conflict resolver, if no manual resolution)
        return {
            "success": True, # Indicates the batch processing itself completed. Individual actions have their own success.
            "individual_action_results": all_individual_results,
            "overall_state_changed": overall_state_changed_for_party # Renamed from "overall_state_changed_for_party"
        }