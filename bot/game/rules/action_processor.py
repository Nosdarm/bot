# bot/game/action_processor.py (updated process method)

import json
from typing import Dict, Any, Optional, List

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character
from bot.game.models.location import Location

# Import managers
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.event_manager import EventManager
# Import other managers

# Import services and rules
from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine
from bot.game.rules import skill_rules


class ActionProcessor:
    def __init__(self):
        print("ActionProcessor initialized.")


    async def process(self,
                      game_state: GameState,
                      char_manager: CharacterManager,
                      loc_manager: LocationManager,
                      event_manager: EventManager,
                      # Add other managers here (npc_manager, item_manager, etc.)
                      rule_engine: RuleEngine,
                      openai_service: OpenAIService,
                      ctx_channel_id: int, # Passed the channel ID from context
                      discord_user_id: int,
                      action_type: str,
                      action_data: Dict[str, Any]
                      ) -> Dict[str, Any]:
        """
        Processes a player action, calculates outcomes, and generates narrative response.
        Receives managers, services, and context for the specific action.
        Returns a dictionary: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # --- Initial Checks ---
        if not char_manager:
            return {"success": False, "message": "**Мастер:** Менеджер персонажей недоступен.", "target_channel_id": ctx_channel_id, "state_changed": False}
        character = char_manager.get_character_by_discord_id(discord_user_id)
        if not character:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        if not loc_manager:
            return {"success": False, "message": "**Мастер:** Менеджер локаций недоступен.", "target_channel_id": ctx_channel_id, "state_changed": False}
        location = loc_manager.get_location(character.current_location_id)
        if not location:
            return {"success": False, "message": "**Мастер:** Ваш персонаж в неизвестной локации. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        output_channel_id = loc_manager.get_location_channel(game_state, location.id) or ctx_channel_id


        # --- Check for actions targeting an event first (Same Logic, may need refined relevancy check) ---
        # This part assumes basic event handling exists and can potentially process the action.
        if not event_manager:
            active_events = []
            relevant_event_id = None
        else:
            active_events = event_manager.get_active_events_in_location(location.id)
            relevant_event_id = None # Logic needed to determine event relevancy based on action_type, action_data, and active_events

            # Placeholder for event relevancy check (Simple: any event in location)
            if action_type in ["interact", "attack", "use_skill", "skill_check", "move"] and active_events: # Basic types that can interact with events
                 # More complex: Does the action target an entity *in* an event?
                 relevant_event = active_events[0] # Still taking the first one for simplicity if ANY event is active and action type *could* be relevant
                 relevant_event_id = relevant_event.id # Mark it as relevant if the action type matches list


        if relevant_event_id and event_manager: # Ensure event_manager is not None here
             # Delegate handling to the EventManager, providing required managers/services
             # EventManager needs to handle moving within/away from event, etc.
             # Its method process_player_action_within_event MUST also return the correct dict format
             print(f"Action {action_type} for {character.name} processed within event {relevant_event_id}")
             # EventManager.process_player_action_within_event needs manager/service deps
             # Ensure set_dependencies is called on event_manager *before* this point if it needs them.
             if hasattr(event_manager, 'set_dependencies') and openai_service : # Check if set_dependencies exists
                event_manager.set_dependencies(openai_service=openai_service) # Ensure AI is available if EventManager uses it
             # Event manager needs other managers too!
             # event_manager.set_other_managers(char_manager, loc_manager, rule_engine) # Example dependency setting for event_manager

             event_response = await event_manager.process_player_action_within_event(
                 event_id=relevant_event_id,
                 player_id=character.id, # Pass character ID, not Discord ID
                 action_type=action_type, # The original action type
                 action_data=action_data,
                 character_manager=char_manager, # Pass managers for EventManager's internal use
                 loc_manager=loc_manager,
                 rule_engine=rule_engine,
                 openai_service=openai_service,
                 ctx_channel_id=ctx_channel_id # Pass the context channel ID
             )
             # EventManager should return {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool?}
             # Ensure the response dict includes the required keys and types
             if 'target_channel_id' not in event_response: event_response['target_channel_id'] = output_channel_id # Fallback
             if 'state_changed' not in event_response: event_response['state_changed'] = False # Default if event logic didn't set it

             return event_response


        # --- If not an Event Action, Process as Regular World Interaction ---
        print(f"Processing regular action {action_type} for player {character.name} at {location.name}")

        # --- Handle Specific Action Types ---

        if action_type == "look":
            # ... (Same look logic) ...
            if not openai_service:
                return {"success": False, "message": "**Мастер:** Сервис AI недоступен для генерации описания.", "target_channel_id": output_channel_id, "state_changed": False}
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{character.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{location.name}', Шаблон описания: '''{location.description_template}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in char_manager.get_characters_in_location(location.id) if c.id != character.id][:3]) if char_manager.get_characters_in_location(location.id) else 'нет'}. "
            )
            description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)
            return {"success": True, "message": f"**Локация:** {location.name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}


        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # --- Movement Logic Implementation ---

            # Attempt to find the target location by its name or ID first
            # Need a method in LocationManager for this (added it in Step 3 above: find_location_by_name_or_id)
            # However, '/move north' implies using an EXIT, not knowing the *name* of the target location beforehand.
            # So let's prioritize finding an EXIT by direction.
            target_location = loc_manager.get_exit_target(location.id, destination_input)

            # If not found by exit direction, try finding a location by the input name as a fallback
            if not target_location:
                 target_location = loc_manager.find_location_by_name_or_id(destination_input)
                 # If found by name/ID, check if it's accessible via *any* exit from the current location
                 if target_location:
                      is_accessible_via_exit = any(exit.get("target_location_id") == target_location.id for exit in location.exits)
                      if not is_accessible_via_exit:
                          # Found location by name, but not directly accessible from here via an exit
                          return {"success": False, "message": f"**Мастер:** Прямого пути к '{target_location.name}' ({destination_input}) отсюда нет. Проверьте выходы.", "target_channel_id": output_channel_id, "state_changed": False}
                      # If it *is* accessible, we proceed as if the exit was found
                      # We don't need the direction explicitly for the update, just for description
                 else:
                     # Input name/ID doesn't match any location
                     return {"success": False, "message": f"**Мастер:** Неизвестное направление или место: '{destination_input}'.", "target_channel_id": output_channel_id, "state_changed": False}


            # --- If we reached here, target_location is a valid and accessible destination ---
            # Optional: Add RuleEngine check for movement cost, obstacles, checks to enter/exit a location.
            # e.g. check_result = rule_engine.perform_check(character.id, "movement_check", ...)
            # Based on result: success -> move, fail -> no move, crit fail -> consequence

            # For now, basic move is always successful (no checks)

            # Update character's location using CharacterManager
            char_manager.update_character_location(character.id, target_location.id)

            # State has changed -> GameManager will save

            # --- Use AI to describe the movement ---
            # Get the exit direction name for the prompt (if moved via directional exit)
            exit_direction_name = destination_input if target_location.id == (loc_manager.get_exit_target(location.id, destination_input).id if loc_manager.get_exit_target(location.id, destination_input) else None) else "новому месту"


            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt = (
                f"Персонаж '{character.name}' перемещается из локации '{location.name}' (через {exit_direction_name if exit_direction_name != target_location.id else 'прямо'}) "
                f"в локацию '{target_location.name}'. "
                f"Краткое описание начальной локации: {location.description_template[:100]}. "
                f"Краткое описание конечной локации: {target_location.description_template[:100]}. "
                f"Опиши краткое путешествие и прибытие в '{target_location.name}'. Будь атмосферным и мрачным. Укажи, что персонаж теперь находится в новой локации."
            )
            if not openai_service:
                description = f"Вы прибыли в {target_location.name}." # Fallback
            else:
                description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=200)

            # Determine where to send the description (usually the destination channel)
            destination_channel_id = loc_manager.get_location_channel(game_state, target_location.id)
            final_output_channel_id = destination_channel_id if destination_channel_id else output_channel_id # Fallback to source channel if destination unmapped

            # Send description and indicate state change
            return {"success": True, "message": f"**Мастер:** {description}", "target_channel_id": final_output_channel_id, "state_changed": True}


        elif action_type == "skill_check":
             # ... (Same skill_check logic, correctly passes modifiers) ...
             skill_name = action_data.get("skill_name")
             complexity = action_data.get("complexity", "medium")
             base_modifiers = action_data.get("modifiers", {})
             target_description = action_data.get("target_description", "чего-то")

             # Get Environment Modifiers from Location Manager
             env_modifiers = {}
             # Need method: loc_manager.get_environmental_skill_modifiers(location.id, skill_name)

             # Get Status Modifiers from Character Manager
             status_modifiers = {}
             # Need method: char_manager.get_status_skill_modifiers(character.id, skill_name)

             final_modifiers = {**env_modifiers, **status_modifiers, **base_modifiers}


             if not skill_name:
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}
             # Add more robust skill check using character object and RuleEngine
             # Need a method like RuleEngine.is_skill_available(character, skill_name) or RuleEngine handles invalid skill
             # For now, basic check on skill names list
             if skill_name not in character.skills:
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             base_dc = skill_rules.get_base_dc(complexity)

             if not rule_engine:
                return {"success": False, "message": "**Мастер:** Движок правил недоступен для проверки навыка.", "target_channel_id": ctx_channel_id, "state_changed": False}
             # Perform the skill check using the RuleEngine
             check_result = rule_engine.perform_check(
                 character_id=character.id,
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
                 f"Ситуация: локация '{location.name}', атмосферное описание: {location.description_template[:100]}..."
                 f"Механический результат проверки:\n{json.dumps(check_result, indent=2, ensure_ascii=False)}\n"
                 f"Опиши, КАК это выглядело и ощущалось в мире. Учитывай результат (Успех/Провал/Крит) и контекст. Будь мрачным и детальным."
             )
             if not openai_service:
                description = "Результат проверки навыка получен." # Fallback
             else:
                description = await openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=300)

             mech_summary = check_result.get("description", "Проверка выполнена.")
             # Skill checks typically don't change state unless there's a critical failure consequence
             state_changed = check_result.get("is_critical_failure", False) # Example: Crit fail might change state (injury etc.)

             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed}


        # Add other action types here...

        else:
            return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается.", "target_channel_id": ctx_channel_id, "state_changed": False}
