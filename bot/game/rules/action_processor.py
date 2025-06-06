# bot/game/rules/action_processor.py

import json
import traceback # Added
from typing import Dict, Any, Optional, List, TYPE_CHECKING

# Import models
from bot.game.models.game_state import GameState
from bot.game.models.character import Character
from bot.game.models.location import Location
# Import other models as needed for type hints

if TYPE_CHECKING:
    # Import managers for type hinting
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.event_manager import EventManager
    # from bot.game.managers.npc_manager import NpcManager # Example
    # from bot.game.managers.item_manager import ItemManager # Example
    # Import services and rules for type hinting
    from bot.services.openai_service import OpenAIService
    from bot.game.rules.rule_engine import RuleEngine
    # from bot.services.discord_service import DiscordService # Example if used

# Import rules module directly for skill_rules.get_base_dc
from bot.game.rules import skill_rules


class ActionProcessor:
    def __init__(self,
                 character_manager: "CharacterManager",
                 location_manager: "LocationManager",
                 event_manager: "EventManager",
                 rule_engine: "RuleEngine",
                 openai_service: Optional["OpenAIService"] = None, # OpenAI can be optional
                 # discord_service: Optional["DiscordService"] = None, # Example
                 # npc_manager: Optional["NpcManager"] = None, # Example
                 # item_manager: Optional["ItemManager"] = None # Example
                 ):
        print("ActionProcessor initialized with managers.")
        self._character_manager = character_manager
        self._location_manager = location_manager
        self._event_manager = event_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service
        # self._discord_service = discord_service
        # self._npc_manager = npc_manager
        # self._item_manager = item_manager

    async def process(self,
                      game_state: GameState, # GameState should contain guild_id (as server_id)
                      # Managers are now self attributes
                      ctx_channel_id: int,
                      discord_user_id: int, # ID of the user performing the action
                      action_type: str,
                      action_data: Dict[str, Any] # Data specific to the action
                      ) -> Dict[str, Any]:
        """
        Processes a player action, calculates outcomes, and generates narrative response.
        Uses internal managers and services initialized with the class.
        Returns a dictionary: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool}
        """

        # Ensure mandatory managers are available
        if not self._character_manager or not self._location_manager or not self._event_manager or not self._rule_engine:
            error_msg = "Основные игровые модули (Character, Location, Event, or RuleEngine) не инициализированы в ActionProcessor."
            print(f"ActionProcessor: ERROR - {error_msg}")
            return {"success": False, "message": f"**Мастер:** {error_msg} Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # --- Initial Checks ---
        # guild_id is available from game_state.server_id
        guild_id = str(game_state.server_id) # Ensure string

        actor_char = self._character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)
        if not actor_char:
            return {"success": False, "message": "**Мастер:** У вас еще нет персонажа в этой игре. Используйте `/join_game`.", "target_channel_id": ctx_channel_id, "state_changed": False}

        current_char_location_id = getattr(actor_char, 'current_location_id', None)
        if not current_char_location_id:
             return {"success": False, "message": "**Мастер:** Ваш персонаж находится в неизвестной локации (нет current_location_id). Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # Use get_location_instance if it returns a model object, or get_location if it returns dict for model hydration
        # Assuming get_location returns the data dict needed for Location model or direct use.
        # LocationManager.get_location expects (self, location_id: str, guild_id: Optional[str] = None)
        source_location_data = await self._location_manager.get_location(location_id=current_char_location_id, guild_id=guild_id)
        if not source_location_data:
            return {"success": False, "message": f"**Мастер:** Текущая локация персонажа ({current_char_location_id}) не найдена. Обратитесь к администратору.", "target_channel_id": ctx_channel_id, "state_changed": False}

        # Assuming source_location_data is a dict that can be used to make a Location model or directly.
        # For simplicity, we'll use it as a dict. If it's a model, adjust access.
        source_location_name = source_location_data.get('name', current_char_location_id)
        source_location_id = source_location_data.get('id', current_char_location_id)


        # LocationManager.get_location_channel expects (self, guild_id: str, instance_id: str)
        output_channel_id = self._location_manager.get_location_channel(guild_id=guild_id, instance_id=source_location_id) or ctx_channel_id


        # --- Check for actions targeting an event first (Same Logic, may need refined relevancy check) ---
        # This part assumes basic event handling exists and can potentially process the action.
        # EventManager.get_active_events_in_location needs (self, guild_id: str, location_id: str)
        active_events = await self._event_manager.get_active_events_in_location(guild_id=guild_id, location_id=source_location_id) # TODO: Implement in EventManager
        relevant_event_id = None

        # Placeholder for event relevancy check
        if action_type in ["interact", "attack", "use_skill", "skill_check", "move", "use_item"] and active_events:
             relevant_event = active_events[0]
             relevant_event_id = relevant_event.id

        if relevant_event_id and self._event_manager:
             print(f"Action {action_type} for {actor_char.name} routed to event {relevant_event_id}")

             # TODO: CRITICAL - The method 'process_player_action_within_event' is missing from EventManager or has different signature.
             # Assuming it exists and takes these params for now.
             event_response = await self._event_manager.process_player_action_within_event(
                 event_id=relevant_event_id,
                 player_id=actor_char.id,
                 action_type=action_type,
                 action_data=action_data,
                 guild_id=guild_id,
                 character_manager=self._character_manager,
                 loc_manager=self._location_manager,
                 rule_engine=self._rule_engine,
                 openai_service=self._openai_service,
                 ctx_channel_id=ctx_channel_id
             )
             # EventManager should return {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool?}
             # Ensure the response dict includes the required keys and types
             if 'target_channel_id' not in event_response: event_response['target_channel_id'] = output_channel_id # Fallback
             if 'state_changed' not in event_response: event_response['state_changed'] = False # Default if event logic didn't set it

             return event_response


        # --- If not an Event Action, Process as Regular World Interaction ---
        print(f"Processing regular action {action_type} for player {actor_char.name} at {source_location_name}")

        # --- Handle Specific Action Types ---

        if action_type == "look":
            # ... (Same look logic) ...
            if not self._openai_service:
                return {"success": False, "message": "**Мастер:** Сервис AI недоступен для генерации описания.", "target_channel_id": output_channel_id, "state_changed": False}
            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай локации атмосферно и мрачно."
            user_prompt = (
                f"Опиши локацию для персонажа '{actor_char.name}' в мрачном фэнтези. "
                f"Учитывай: Локация '{source_location_name}', Шаблон описания: '''{source_location_data.get('description_template')}'''. "
                f"Активные события здесь: {', '.join([e.name for e in active_events]) if active_events else 'нет'}. "
                # CharacterManager.get_characters_in_location needs guild_id, location_id
                f"Видимые персонажи/NPC (пример): {', '.join([c.name for c in self._character_manager.get_characters_in_location(guild_id=guild_id, location_id=source_location_id) if c.id != actor_char.id][:3]) if self._character_manager.get_characters_in_location(guild_id=guild_id, location_id=source_location_id) else 'нет'}. "
            )
            description = await self._openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=400)
            return {"success": True, "message": f"**Локация:** {source_location_name}\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": False}


        elif action_type == "move":
            destination_input = action_data.get('destination')
            if not destination_input:
                 return {"success": False, "message": "**Мастер:** Укажите, куда именно вы хотите идти.", "target_channel_id": ctx_channel_id, "state_changed": False}

            # --- Movement Logic Implementation ---

            # Attempt to find the target location by its name or ID first
            # Need a method in LocationManager for this (added it in Step 3 above: find_location_by_name_or_id)
            # However, '/move north' implies using an EXIT, not knowing the *name* of the target location beforehand.
            # So let's prioritize finding an EXIT by direction.
            # TODO: Implement LocationManager.get_exit_target(guild_id, current_location_id, exit_name)
            target_location_data = await self._location_manager.get_exit_target(guild_id=guild_id, current_location_id=source_location_id, exit_name=destination_input)

            # If not found by exit direction, try finding a location by the input name as a fallback
            if not target_location_data:
                 # TODO: Implement LocationManager.find_location_by_name_or_id(guild_id, name_or_id)
                 target_location_data = await self._location_manager.find_location_by_name_or_id(guild_id=guild_id, name_or_id=destination_input)
                 # If found by name/ID, check if it's accessible via *any* exit from the current location
                 if target_location_data:
                      # Location.exits is expected to be List[Dict[str, str]] where dict has 'target_location_id'
                      current_location_exits = source_location_data.get('exits', [])
                      is_accessible_via_exit = any(exit_data.get("target_location_id") == target_location_data.get('id') for exit_data in current_location_exits if isinstance(exit_data, dict))
                      if not is_accessible_via_exit:
                          # Found location by name, but not directly accessible from here via an exit
                          return {"success": False, "message": f"**Мастер:** Прямого пути к '{target_location_data.get('name', destination_input)}' ({destination_input}) отсюда нет. Проверьте выходы.", "target_channel_id": output_channel_id, "state_changed": False}
                      # If it *is* accessible, we proceed as if the exit was found
                      # We don't need the direction explicitly for the update, just for description
                 else:
                     # Input name/ID doesn't match any location
                     return {"success": False, "message": f"**Мастер:** Неизвестное направление или место: '{destination_input}'.", "target_channel_id": output_channel_id, "state_changed": False}

            target_location_id = target_location_data.get('id')
            target_location_name = target_location_data.get('name', target_location_id)
            target_location_desc_template = target_location_data.get('description_template', '')


            # --- If we reached here, target_location_data is valid and accessible ---
            # Optional: Add RuleEngine check for movement cost, obstacles, etc.
            # context_for_rule_engine = {"guild_id": guild_id, "character": actor_char, "source_location": source_location_data, "target_location": target_location_data}
            # move_check_result = await self._rule_engine.perform_check("movement", context=context_for_rule_engine)
            # if not move_check_result.get("success"):
            #     return {"success": False, "message": f"**Мастер:** {move_check_result.get('message', 'Не удалось переместиться.')}", "target_channel_id": output_channel_id, "state_changed": False}

            # Update character's location using CharacterManager
            # CharacterManager.update_character_location needs (self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any)
            await self._character_manager.update_character_location(character_id=actor_char.id, location_id=target_location_id, guild_id=guild_id, context=action_data) # Pass action_data as context

            # --- Use AI to describe the movement ---
            exit_direction_name = destination_input # Fallback to user input
            # TODO: A more robust way to get exit_direction_name if it's based on a specific exit chosen.

            system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай перемещение между локациями. Учитывай стиль и атмосферу."
            user_prompt = (
                f"Персонаж '{actor_char.name}' перемещается из локации '{source_location_name}' (через {exit_direction_name}) "
                f"в локацию '{target_location_name}'. "
                f"Краткое описание начальной локации: {source_location_data.get('description_template', '')[:100]}. "
                f"Краткое описание конечной локации: {target_location_desc_template[:100]}. "
                f"Опиши краткое путешествие и прибытие в '{target_location_name}'. Будь атмосферным и мрачным. Укажи, что персонаж теперь находится в новой локации."
            )
            if not self._openai_service:
                description = f"Вы прибыли в {target_location_name}." # Fallback
            else:
                description = await self._openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=200)

            # Determine where to send the description
            destination_channel_id = self._location_manager.get_location_channel(guild_id=guild_id, instance_id=target_location_id)
            final_output_channel_id = destination_channel_id if destination_channel_id else output_channel_id

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
             # Need method: self._character_manager.get_status_skill_modifiers(actor_char.id, skill_name)
             # status_modifiers = await self._character_manager.get_status_skill_modifiers(guild_id, actor_char.id, skill_name)

             final_modifiers = {**env_modifiers, **status_modifiers, **base_modifiers}


             if not skill_name:
                  return {"success": False, "message": "**Мастер:** Укажите название навыка для проверки.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Check if character has the skill
             # Assuming actor_char.skills is a dict or list of skill names/objects
             if not hasattr(actor_char, 'skills') or skill_name not in actor_char.skills:
                 return {"success": False, "message": f"**Мастер:** Ваш персонаж не владеет навыком '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             base_dc = skill_rules.get_base_dc(skill_name, target_level=None, context=action_data) # Using placeholder

             # Perform the skill check using the RuleEngine
             # TODO: RuleEngine.perform_check needs implementation or signature adjustment.
             # Assuming it takes: guild_id, character, skill_name, dc, context
             check_result = await self._rule_engine.perform_check(
                 guild_id=guild_id,
                 character=actor_char,
                 skill_name=skill_name,
                 base_dc=base_dc,
                 modifiers=final_modifiers
             )

             if not check_result:
                  return {"success": False, "message": f"**Мастер:** Произошла ошибка при выполнении проверки навыка '{skill_name}'.", "target_channel_id": ctx_channel_id, "state_changed": False}

             # Use AI to describe the outcome
             system_prompt = "Ты - Мастер текстовой RPG в мире темного фэнтези. Описывай действия и их результаты детализированно и атмосферно."
             user_prompt = (
                 f"Персонаж '{actor_char.name}' (Навыки: {list(actor_char.skills.keys())}, Статы: {list(actor_char.stats.keys())}) "
                 f"попытался совершить действие, связанное с навыком '{skill_name}', целью было {target_description}. "
                 f"Ситуация: локация '{source_location_name}', атмосферное описание: {source_location_data.get('description_template', '')[:100]}..."
                 f"Механический результат проверки:\n{json.dumps(check_result, indent=2, ensure_ascii=False)}\n"
                 f"Опиши, КАК это выглядело и ощущалось в мире. Учитывай результат (Успех/Провал/Крит) и контекст. Будь мрачным и детальным."
             )
             if not self._openai_service:
                description = f"Результат проверки {skill_name}: {check_result.get('outcome', 'неизвестно')}." # Fallback
             else:
                description = await self._openai_service.generate_master_response(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=300)

             mech_summary = check_result.get("description", "Проверка выполнена.")
             # Skill checks typically don't change state unless there's a critical failure consequence
             state_changed = check_result.get("is_critical_failure", False) # Example: Crit fail might change state (injury etc.)

             return {"success": True, "message": f"_{mech_summary}_\n\n**Мастер:** {description}", "target_channel_id": output_channel_id, "state_changed": state_changed}


        # Add other action types here...

        else:
            return {"success": False, "message": f"**Мастер:** Действие '{action_type}' не поддерживается.", "target_channel_id": ctx_channel_id, "state_changed": False}
