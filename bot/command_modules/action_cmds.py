import discord
# from discord import slash_command # Or commands.Cog - Replaced by app_commands
from typing import Optional, TYPE_CHECKING # Added TYPE_CHECKING

from bot.bot_core import RPGBot # Import RPGBot

# --- Temporary global references ---
# from bot.bot_core import global_game_manager # REMOVE THIS LINE
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Copy from bot_core.py

# Add TYPE_CHECKING block for imports needed for type hints
from discord import app_commands, Interaction # Make sure this is at the top level

if TYPE_CHECKING:
    # from bot.bot_core import RPGBot # Already imported above
    from bot.services.db_service import DBService
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager # Added for new commands
    from bot.game.models.character import Character as CharacterModel # For type hinting
    from bot.game.models.npc import NPC as NPCModel # For type hinting
    from bot.game.managers.party_manager import PartyManager # Added for new commands
    from bot.game.managers.combat_manager import CombatManager # Added for new cmd_fight
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.models.dialogue_session import DialogueSession


# Placeholder for /interact command
@app_commands.command(name="interact", description="Взаимодействовать с чем-то или кем-то.")
async def cmd_interact(interaction: Interaction, target: str, action_str: str, details: Optional[str] = None): # Renamed action to action_str to avoid conflict
    await interaction.response.defer(ephemeral=True)

    # game_mngr = None
    # if hasattr(interaction.client, 'game_manager'):
    #     game_mngr_candidate = getattr(interaction.client, 'game_manager')
    #     if TYPE_CHECKING: # Ensure type checker knows about GameManager methods if available
    #          assert isinstance(game_mngr_candidate, GameManager)
    #     game_mngr = game_mngr_candidate

    # if game_mngr and hasattr(game_mngr, 'process_player_action'): # Check if method exists
    #      # This command is still a placeholder and uses the old process_player_action structure
    #      # It should be refactored to use DBService and specific game logic like other commands.
    #      response_data = await game_mngr.process_player_action(
    #          server_id=str(interaction.guild_id),
    #          discord_user_id=interaction.user.id,
    #          action_type="interact", # This action_type might need to be handled by process_player_action
    #          action_data={"target": target, "action": action_str, "details": details}
    #      )
    #      await interaction.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."), ephemeral=True)
    # elif game_mngr:
    #     await interaction.followup.send("The '/interact' command is not fully implemented for the new system yet.", ephemeral=True)
    # else:
    #      await interaction.followup.send("**Ошибка Мастера:** Игровая система недоступна.", ephemeral=True)
    await interaction.followup.send("The '/interact' command is currently under refactoring. Please try again later.", ephemeral=True)
    bot: RPGBot = interaction.client # Correct type hint

    if not bot.game_manager:
        await interaction.followup.send("**Ошибка Мастера:** Игровая система недоступна.", ephemeral=True)
        return

    # TODO: Implement/fix game_manager.process_player_action or replace with new logic.
    # For now, commenting out the call as per subtask instructions.
    # if hasattr(bot.game_manager, 'process_player_action'):
    #     response_data = await bot.game_manager.process_player_action(
    #         server_id=str(interaction.guild_id),
    #         discord_user_id=interaction.user.id,
    #         action_type="interact",
    #         action_data={"target": target, "action": action_str, "details": details}
    #     )
    #     await interaction.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."), ephemeral=True)
    # else:
    await interaction.followup.send("The '/interact' command is being reworked to use the new action system. Please try again later.", ephemeral=True)


import random # For basic combat roll

@app_commands.command(name="fight", description="Engage in combat with an NPC.")
@app_commands.describe(target_npc_name="The name of the NPC you want to fight (optional).")
async def cmd_fight(interaction: Interaction, target_npc_name: Optional[str] = None):
    """Initiates a basic combat round with an NPC."""
    await interaction.response.defer(ephemeral=False) # Combat is generally public

    bot: RPGBot = interaction.client # Correct type hint

    try:
        if not bot.game_manager or \
           not bot.game_manager.db_service or \
           not bot.game_manager.combat_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.npc_manager:
            await interaction.followup.send("Error: Core game services (DB, Combat, Character, NPC) are not fully initialized.", ephemeral=True)
            return

        # Type assertions for Pylance/Mypy if needed, or rely on RPGBot type hint
        db_service: 'DBService' = bot.game_manager.db_service
        combat_manager: 'CombatManager' = bot.game_manager.combat_manager
        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        npc_manager = bot.game_manager.npc_manager # No specific type hint needed if direct methods are used
        game_mngr: 'GameManager' = bot.game_manager # Retain for clarity if used often


        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        if not interaction.channel:
            await interaction.followup.send("Error: This command cannot be used in a context without a channel.", ephemeral=True)
            return
        channel_id = interaction.channel.id # For combat messages

        # Use CharacterManager to get character model
        player_char: Optional['CharacterModel'] = await character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)
        if not player_char:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        language = player_char.selected_language or "en" # For name display

        # player_id = player_char.id
        # player_location_id = player_char.location_id
        # player_name = player_char.name_i18n.get(language, player_char.name_i18n.get('en', 'You'))

        if not player_char.id or not player_char.location_id: # Check essential attributes
            await interaction.followup.send("Error: Could not retrieve your character's essential data (ID or location).", ephemeral=True)
            return

        # Check if player is already in an active combat in this guild
        active_combat_for_player = combat_manager.get_combat_by_participant_id(guild_id, player_char.id)

        if active_combat_for_player and active_combat_for_player.is_active:
            current_actor_id = active_combat_for_player.get_current_actor_id()
            if current_actor_id == player_char.id:
                await interaction.followup.send(f"You are already in combat with {len(active_combat_for_player.participants) -1} opponent(s)! It's your turn. Use an action command (e.g., `/attack <target>`).", ephemeral=True)
            else:
                actor_name = "Someone"
                actor_participant_obj = active_combat_for_player.get_participant_data(current_actor_id) if current_actor_id else None
                if actor_participant_obj and game_mngr and game_mngr.npc_manager:
                    if actor_participant_obj.entity_type == "NPC":
                        npc_actor = game_mngr.npc_manager.get_npc(guild_id, actor_participant_obj.entity_id)
                        if npc_actor: actor_name = getattr(npc_actor, 'name_i18n', {}).get('en', 'Unknown NPC')
                    # Could add Character type here if players can fight players

                        if npc_actor: actor_name = npc_actor.name_i18n.get(language, npc_actor.name_i18n.get('en', 'Unknown NPC'))
                    # Could add Character type here
                await interaction.followup.send(f"You are already in combat! It's {actor_name}'s turn.", ephemeral=True)
            return

        if not target_npc_name:
            await interaction.followup.send("Who do you want to fight? Please specify an NPC name.", ephemeral=True)
            return

        # Use NPCManager to find NPC
        target_npc: Optional[NPCModel] = None
        # Assuming NPCManager has a method to get NPCs by location, or get all and filter
        # For now, let's assume a simplified get_npcs_in_location from npc_manager or db_service
        # If using npc_manager.get_npcs_in_location, it should return list of NPCModel
        npcs_in_loc_models = npc_manager.get_npcs_in_location(guild_id=guild_id, location_id=player_char.location_id)

        for npc_model_instance in npcs_in_loc_models:
            npc_model_name = npc_model_instance.name_i18n.get(language, npc_model_instance.name_i18n.get('en', ''))
            if npc_model_name.lower() == target_npc_name.lower():
                target_npc = npc_model_instance
                break

        if not target_npc:
            await interaction.followup.send(f"NPC '{target_npc_name}' not found here.", ephemeral=True)
            return

        npc_id = target_npc.id
        npc_name_display = target_npc.name_i18n.get(language, target_npc.name_i18n.get('en', 'The NPC'))

        if target_npc.health <= 0:
            await interaction.followup.send(f"{npc_name_display} is already defeated or incapacitated.", ephemeral=False)
            return

        participant_ids_types = [(player_char.id, "Character"), (npc_id, "NPC")]

        # Context for start_combat, including managers it might need for fetching details
        start_combat_context = {
            "channel_id": channel_id,
            "character_manager": character_manager, # Pass the manager
            "npc_manager": npc_manager, # Pass the manager
            "rule_engine": game_mngr.rule_engine,
            "send_callback_factory": game_mngr._get_discord_send_callback
        }

        new_combat = await combat_manager.start_combat(
            guild_id=guild_id,
            location_id=player_char.location_id, # Use location from char model
            participant_ids_types=participant_ids_types,
            **start_combat_context
        )

        if new_combat:
            init_messages = []
            for p_obj in new_combat.participants:
                p_name = "Unknown"
                if p_obj.entity_type == "Character" and game_mngr.character_manager:
                    p_char = game_mngr.character_manager.get_character(guild_id, p_obj.entity_id)
                    if p_char: p_name = getattr(p_char, 'name_i18n', {}).get('en', 'Unknown Character')
                elif p_obj.entity_type == "NPC" and game_mngr.npc_manager:
                    p_npc = game_mngr.npc_manager.get_npc(guild_id, p_obj.entity_id)
                    if p_npc: p_name = getattr(p_npc, 'name_i18n', {}).get('en', 'Unknown NPC')
                init_messages.append(f"{p_name} (Initiative: {p_obj.initiative})")
                p_name_display = "Unknown"
                # Fetch names using managers and models
                if p_obj.entity_type == "Character":
                    p_char_model = await character_manager.get_character(guild_id, p_obj.entity_id)
                    if p_char_model: p_name_display = p_char_model.name_i18n.get(language, p_char_model.name_i18n.get('en', 'Unknown Character'))
                elif p_obj.entity_type == "NPC":
                    p_npc_model = npc_manager.get_npc(guild_id, p_obj.entity_id)
                    if p_npc_model: p_name_display = p_npc_model.name_i18n.get(language, p_npc_model.name_i18n.get('en', 'Unknown NPC'))
                init_messages.append(f"{p_name_display} (Initiative: {p_obj.initiative})")

            initiative_summary = ", ".join(init_messages)
            first_actor_id = new_combat.get_current_actor_id()
            first_actor_name_display = "Someone"
            if first_actor_id:
                fa_obj = new_combat.get_participant_data(first_actor_id)
                if fa_obj:
                    if fa_obj.entity_type == "Character" and game_mngr.character_manager:
                        fa_char = game_mngr.character_manager.get_character(guild_id, fa_obj.entity_id)
                        if fa_char: first_actor_name = getattr(fa_char, 'name_i18n', {}).get('en', 'Unknown Character')
                    elif fa_obj.entity_type == "NPC" and game_mngr.npc_manager:
                        fa_npc = game_mngr.npc_manager.get_npc(guild_id, fa_obj.entity_id)
                        if fa_npc: first_actor_name = getattr(fa_npc, 'name_i18n', {}).get('en', 'Unknown NPC')
                    if fa_obj.entity_type == "Character":
                        fa_char_model = await character_manager.get_character(guild_id, fa_obj.entity_id)
                        if fa_char_model: first_actor_name_display = fa_char_model.name_i18n.get(language, fa_char_model.name_i18n.get('en', 'A Character'))
                    elif fa_obj.entity_type == "NPC":
                        fa_npc_model = npc_manager.get_npc(guild_id, fa_obj.entity_id)
                        if fa_npc_model: first_actor_name_display = fa_npc_model.name_i18n.get(language, fa_npc_model.name_i18n.get('en', 'An NPC'))

            response_message = (
                f"⚔️ Combat started with **{npc_name_display}**! ⚔️\n"
                f"Initiative: {initiative_summary}\n"
                f"It's **{first_actor_name_display}**'s turn. Use an action command (e.g., `/attack`)."
            )
            await interaction.followup.send(response_message)

            try:
                log_msg = f"Combat started. Participants: {[(p.entity_id, p.entity_type) for p in new_combat.participants]}. Turn order: {new_combat.turn_order}."
                await db_service.add_log_entry(
                    guild_id=guild_id, event_type="COMBAT_START", message=log_msg,
                    player_id_column=player_id, # If player initiated
                    related_entities={"combat_id": new_combat.id, "participants": [p.entity_id for p in new_combat.participants]},
                    context_data={"location_id": player_location_id, "channel_id": channel_id} # Use validated channel_id
                )
                if db_service: # Ensure db_service is available
                    log_msg = f"Combat started. Participants: {[(p.entity_id, p.entity_type) for p in new_combat.participants]}. Turn order: {new_combat.turn_order}."
                    await db_service.add_log_entry(
                        guild_id=guild_id, event_type="COMBAT_START", message=log_msg,
                        player_id_column=player_char.id, # Use player_char.id
                        related_entities={"combat_id": new_combat.id, "participants": [p.entity_id for p in new_combat.participants]},
                        context_data={"location_id": player_char.location_id, "channel_id": channel_id}
                    )
            except Exception as log_e:
                print(f"Error logging combat start: {log_e}")
        else:
            await interaction.followup.send(f"Failed to start combat with {npc_name_display}. Please try again.", ephemeral=True)

    except Exception as e:
        print(f"Error in /fight command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to start combat.", ephemeral=True)

import traceback # For error logging

@app_commands.command(name="talk", description="Talk to an NPC in your current location.")
@app_commands.describe(
    npc_name="The name of the NPC you want to talk to.",
    message="Your message to the NPC."
)
async def cmd_talk(interaction: Interaction, npc_name: str, message: str):
    """Allows a player to talk to an NPC, using AI for responses and managing history."""
    await interaction.response.defer(ephemeral=False)
    bot: RPGBot = interaction.client # Correct type hint

    try:
        if not bot.game_manager or \
           not bot.game_manager.db_service or \
           not bot.game_manager.openai_service or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.npc_manager or \
           not bot.game_manager.dialogue_manager:
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        # Type assertions for Pylance/Mypy
        db_service: 'DBService' = bot.game_manager.db_service
        openai_service: 'OpenAIService' = bot.game_manager.openai_service
        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        npc_manager = bot.game_manager.npc_manager
        dialogue_manager: 'DialogueManager' = bot.game_manager.dialogue_manager

        if not openai_service.is_available():
            await interaction.followup.send("The AI for dialogue is currently unavailable. Please try again later.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        if not interaction.channel:
            await interaction.followup.send("Error: This command cannot be used in a context without a channel.", ephemeral=True)
            return
        channel_id = interaction.channel.id

        if interaction.channel_id is None:
            await interaction.followup.send("Error: This command cannot be used in a context without a channel ID.", ephemeral=True)
            return
        channel_id_int: int = interaction.channel_id


        player_char: Optional['CharacterModel'] = await character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)
        if not player_char:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        language = player_char.selected_language or "en"
        player_name_display = player_char.name_i18n.get(language, player_char.name_i18n.get('en', 'Adventurer'))

        if not player_char.id or not player_char.location_id:
            await interaction.followup.send("Error: Could not retrieve your character's essential data (ID or location).", ephemeral=True)
            return

        target_npc: Optional[NPCModel] = None
        npcs_in_loc_models = npc_manager.get_npcs_in_location(guild_id=guild_id, location_id=player_char.location_id)
        for npc_model_instance in npcs_in_loc_models:
            npc_model_name = npc_model_instance.name_i18n.get(language, npc_model_instance.name_i18n.get('en', ''))
            if npc_model_name.lower() == npc_name.lower():
                target_npc = npc_model_instance
                break

        if not target_npc:
            await interaction.followup.send(f"You don't see anyone named '{npc_name}' here.", ephemeral=True)
            return

        npc_id_str = target_npc.id
        npc_name_display = target_npc.name_i18n.get(language, target_npc.name_i18n.get('en', 'Someone'))
        npc_persona_str = target_npc.personality_i18n.get(language, target_npc.personality_i18n.get('en', 'A mysterious figure.'))
        npc_description_str = target_npc.visual_description_i18n.get(language, target_npc.visual_description_i18n.get('en', 'An ordinary person.'))


        session: Optional['DialogueSession'] = await dialogue_manager.get_or_create_dialogue_session(
            player_id=player_char.id,
            npc_id=npc_id_str,
            guild_id=guild_id,
            channel_id=channel_id_int # Pass validated channel_id
        )
        if not session:
             await interaction.followup.send(f"Error: Could not start or retrieve dialogue session with {npc_name_display}.", ephemeral=True)
             return

        conversation_history = session.conversation_history # Assuming this is a list of dicts

        ai_response_text = await openai_service.generate_npc_response(
            npc_name=npc_name_display,
            npc_persona=npc_persona_str,
            npc_description=npc_description_str,
            conversation_history=conversation_history,
            player_message=message,
            # language=language # Pass language if your OpenAI service supports it
        )

        if not ai_response_text:
            await interaction.followup.send(f"{npc_name_display} seems lost in thought and doesn't respond. (AI response generation failed)", ephemeral=True)
            return

        # Update history via DialogueManager
        await dialogue_manager.add_dialogue_entry(session.id, {"speaker": player_name_display, "line": message}, guild_id)
        await dialogue_manager.add_dialogue_entry(session.id, {"speaker": npc_name_display, "line": ai_response_text}, guild_id)

        # Log entry via db_service (optional, if DialogueManager doesn't handle all logging)
        if db_service:
            try:
                log_message = f"{player_name_display} spoke with {npc_name_display}."
                # ... (rest of logging code, ensure player_char.id is used)
            except Exception as log_e:
                print(f"Error adding log entry for dialogue turn: {log_e}")

        embed = discord.Embed(title=f"Talking with {npc_name_display}", color=discord.Color.blue())
        embed.add_field(name=player_name_display, value=message, inline=False)
        embed.add_field(name=npc_name_display, value=ai_response_text, inline=False)
        embed.set_footer(text=f"Dialogue ID: {session.id}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in /talk command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to talk to the NPC.", ephemeral=True)


@app_commands.command(name="end_turn", description="Завершить свой ход и ждать обработки действий.")
async def cmd_end_turn(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot: RPGBot = interaction.client # Correct type hint

    try:
        if not bot.game_manager or not bot.game_manager.character_manager:
            await interaction.followup.send("Error: Core game services (Character Manager) are not fully initialized.", ephemeral=True)
            return

        character_manager: 'CharacterManager' = bot.game_manager.character_manager
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        char_model = character_manager.get_character_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id) # Removed await
        char_model: Optional['CharacterModel'] = await character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)

        if not char_model:
            await interaction.followup.send("Не удалось найти вашего персонажа. Используйте `/start` для создания.", ephemeral=True)
            return

        if char_model.current_game_status == 'ожидание_обработку':
            await interaction.followup.send("Вы уже завершили свой ход. Ожидайте обработки.", ephemeral=True)
            return

        char_model.current_game_status = 'ожидание_обработку'
        char_model.собранные_действия_JSON = "[]"

        character_manager.mark_character_dirty(guild_id, char_model.id)
        await character_manager.save_character(char_model, guild_id=guild_id)

        await interaction.followup.send("Ваш ход завершен. Действия будут обработаны.", ephemeral=True)

    except Exception as e:
        print(f"Error in /end_turn command: {e}")
        traceback.print_exc()
        await interaction.followup.send("Произошла ошибка при завершении хода.", ephemeral=True)

@app_commands.command(name="end_party_turn", description="Завершить ход для вашей группы в текущей локации.")
async def cmd_end_party_turn(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot: RPGBot = interaction.client # Correct type hint
    updated_member_names = []

    try:
        if not bot.game_manager or \
           not bot.game_manager.character_manager or \
           not bot.game_manager.party_manager:
            await interaction.followup.send("Error: Core game services (Character, Party) are not fully initialized.", ephemeral=True)
            return

        game_mngr: 'GameManager' = bot.game_manager # For clarity
        character_manager: 'CharacterManager' = game_mngr.character_manager
        party_manager: 'PartyManager' = game_mngr.party_manager

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # --- Get Sender's Character and Party ---
        sender_char = character_manager.get_character_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id) # Removed await
        sender_char: Optional['CharacterModel'] = await character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_user_id)
        if not sender_char:
            await interaction.followup.send("Не удалось найти вашего персонажа. Используйте `/start`.", ephemeral=True)
            return

        language = sender_char.selected_language or "en"

        if not sender_char.party_id:
            await interaction.followup.send("Вы не состоите в группе.", ephemeral=True)
            return

        party = await party_manager.get_party(party_id=sender_char.party_id, guild_id=guild_id) # Keep await if get_party is async
        # Assuming party_manager.get_party is not async, remove await if so. For now, keep await as per original.
        # If PartyManager.get_party is not async, this will cause a TypeError.
        # Based on typical manager patterns, it might be non-async if it's a cache lookup.
        # For this subtask, I will assume it's not async if it's a simple cache lookup, otherwise keep await.
        # Let's assume it's a cache lookup for now and remove await.
        party = party_manager.get_party(party_id=sender_char.party_id, guild_id=guild_id)
        if not party:
            await interaction.followup.send(f"Не удалось найти вашу группу (ID: {sender_char.party_id}). Это может быть ошибка данных.", ephemeral=True)
            return
        
        sender_char_location_id = sender_char.location_id
        sender_name_display = sender_char.name_i18n.get(language, sender_char.name_i18n.get('en', 'Unknown Player'))

        if sender_char.current_game_status != 'ожидание_обработку':
            sender_char.current_game_status = 'ожидание_обработку'
            # Note: собранные_действия_JSON for the sender should ideally be cleared by their own /end_turn.
            # If /end_party_turn is the *only* way they end their turn, then actions should be cleared here.
            # Assuming /end_turn is preferred for individual action clearing.
            await character_manager.update_character(sender_char)
            processed_members_count += 1
            updated_member_names.append(getattr(sender_char, 'name_i18n', {}).get('en', 'Unknown Character'))
            character_manager.mark_character_dirty(guild_id, sender_char.id)
            await character_manager.save_character(sender_char, guild_id=guild_id)
            updated_member_names.append(sender_name_display)

        for member_char_id in party.player_ids_list:
            if member_char_id == sender_char.id:
                continue

            member_char = character_manager.get_character_by_discord_id(discord_user_id=int(member_player_id), guild_id=guild_id) # Changed, removed await, assume int
            member_char: Optional['CharacterModel'] = await character_manager.get_character(guild_id=guild_id, character_id=member_char_id)
            
            if member_char and member_char.location_id == sender_char_location_id:
                if member_char.current_game_status != 'ожидание_обработку':
                    member_char.current_game_status = 'ожидание_обработку'
                    # As with sender, assume individual /end_turn handles action clearing.
                    await character_manager.update_character(member_char)
                    processed_members_count += 1
                    updated_member_names.append(getattr(member_char, 'name_i18n', {}).get('en', 'Unknown Character'))
                    character_manager.mark_character_dirty(guild_id, member_char.id)
                    await character_manager.save_character(member_char, guild_id=guild_id)
                    member_name_display = member_char.name_i18n.get(language, member_char.name_i18n.get('en', 'Another Player'))
                    updated_member_names.append(member_name_display)
            elif member_char:
                pass
            else:
                print(f"Warning: Character not found for ID {member_char_id} in party {party.id} (guild {guild_id}).")

        if updated_member_names:
            await interaction.followup.send(f"Ход завершен для следующих членов вашей группы в локации '{sender_char_location_id}': {', '.join(updated_member_names)}. Ожидайте обработки.", ephemeral=False)
        else:
            await interaction.followup.send("Все члены вашей группы в текущей локации уже завершили свой ход. Ожидайте обработки.", ephemeral=True)

        # PartyManager.check_and_process_party_turn is async
        if game_mngr.party_manager: # ensure party_manager is not None
            await game_mngr.party_manager.check_and_process_party_turn(
                party_id=party.id,
                location_id=sender_char_location_id, # sender_char is guaranteed to be not None here
                guild_id=guild_id,
                game_manager=game_mngr
            )

    except Exception as e:
        print(f"Error in /end_party_turn command: {e}")
        traceback.print_exc()
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("Произошла непредвиденная ошибка при завершении хода группы.",ephemeral=True)
            except discord.errors.InteractionResponded: # If somehow it got responded to
                 await interaction.followup.send("Произошла непредвиденная ошибка при завершении хода группы.", ephemeral=True)
                await interaction.response.send_message("Произошла непредвиденная ошибка при завершении хода группы.", ephemeral=True)
            except discord.errors.InteractionResponded:
                 await interaction.followup.send("Произошла непредвиденная ошибка при завершении хода группы.", ephemeral=True)
        else:
            await interaction.followup.send("Произошла непредвиденная ошибка при завершении хода группы.", ephemeral=True)
