import discord
# from discord import slash_command # Or commands.Cog - Replaced by app_commands
from typing import Optional, TYPE_CHECKING # Added TYPE_CHECKING

# --- Temporary global references ---
# from bot.bot_core import global_game_manager # REMOVE THIS LINE
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Copy from bot_core.py

# Add TYPE_CHECKING block for imports needed for type hints
from discord import app_commands, Interaction # Make sure this is at the top level

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.combat_manager import CombatManager # Added for new cmd_fight


# Placeholder for /interact command
@app_commands.command(name="interact", description="Взаимодействовать с чем-то или кем-то.")
async def cmd_interact(interaction: Interaction, target: str, action_str: str, details: Optional[str] = None): # Renamed action to action_str to avoid conflict
    await interaction.response.defer(ephemeral=True)

    game_mngr = None
    if hasattr(interaction.client, 'game_manager'):
        game_mngr_candidate = getattr(interaction.client, 'game_manager')
        if TYPE_CHECKING: # Ensure type checker knows about GameManager methods if available
             assert isinstance(game_mngr_candidate, GameManager)
        game_mngr = game_mngr_candidate

    if game_mngr and hasattr(game_mngr, 'process_player_action'): # Check if method exists
         # This command is still a placeholder and uses the old process_player_action structure
         # It should be refactored to use DBService and specific game logic like other commands.
         response_data = await game_mngr.process_player_action(
             server_id=str(interaction.guild_id),
             discord_user_id=interaction.user.id,
             action_type="interact", # This action_type might need to be handled by process_player_action
             action_data={"target": target, "action": action_str, "details": details}
         )
         await interaction.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."), ephemeral=True)
    elif game_mngr:
        await interaction.followup.send("The '/interact' command is not fully implemented for the new system yet.", ephemeral=True)
    else:
         await interaction.followup.send("**Ошибка Мастера:** Игровая система недоступна.", ephemeral=True)

import random # For basic combat roll

@app_commands.command(name="fight", description="Engage in combat with an NPC.")
@app_commands.describe(target_npc_name="The name of the NPC you want to fight (optional).")
# guild_ids=TEST_GUILD_IDS # Removed, ensure RPGBot handles it
async def cmd_fight(interaction: Interaction, target_npc_name: Optional[str] = None):
    """Initiates a basic combat round with an NPC."""
    await interaction.response.defer(ephemeral=False) # Combat is generally public

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service') or \
           not hasattr(interaction.client.game_manager, 'combat_manager'): # Check for combat_manager
            await interaction.followup.send("Error: Core game services (DB or Combat) are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        combat_manager: 'CombatManager' = client_bot.game_manager.combat_manager # Get CombatManager
        # game_manager for other calls if needed (though combat_manager should handle most combat logic)
        game_mngr: 'GameManager' = client_bot.game_manager


        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id
        channel_id = interaction.channel_id # For combat messages

        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        player_location_id = player_data.get('location_id')
        player_name = player_data.get('name', 'You')

        if not player_id or not player_location_id:
            await interaction.followup.send("Error: Could not retrieve your character or location data.", ephemeral=True)
            return

        # Check if player is already in an active combat in this guild
        active_combat_for_player = combat_manager.get_combat_by_participant_id(guild_id, player_id)

        if active_combat_for_player and active_combat_for_player.is_active:
            current_actor_id = active_combat_for_player.get_current_actor_id()
            if current_actor_id == player_id:
                await interaction.followup.send(f"You are already in combat with {len(active_combat_for_player.participants) -1} opponent(s)! It's your turn. Use an action command (e.g., `/attack <target>`).", ephemeral=True)
            else:
                # Try to get current actor's name
                actor_name = "Someone"
                actor_participant_obj = active_combat_for_player.get_participant_data(current_actor_id) if current_actor_id else None
                if actor_participant_obj and game_mngr: # Need GameManager to access other entity managers
                    if actor_participant_obj.entity_type == "NPC" and game_mngr.npc_manager:
                        npc_actor = game_mngr.npc_manager.get_npc(guild_id, actor_participant_obj.entity_id)
                        if npc_actor: actor_name = npc_actor.name
                    # Could add Character type here if players can fight players

                await interaction.followup.send(f"You are already in combat! It's {actor_name}'s turn.", ephemeral=True)
            return

        # If not in active combat, proceed to start a new one
        if not target_npc_name:
            await interaction.followup.send("Who do you want to fight? Please specify an NPC name.", ephemeral=True)
            return

        npcs_in_location = await db_service.get_npcs_in_location(location_id=player_location_id, guild_id=guild_id)
        target_npc_data = None
        for npc in npcs_in_location:
            if npc.get('name', '').lower() == target_npc_name.lower():
                target_npc_data = npc
                break

        if not target_npc_data:
            await interaction.followup.send(f"NPC '{target_npc_name}' not found here.", ephemeral=True)
            return

        npc_id = target_npc_data.get('id')
        npc_name = target_npc_data.get('name', 'The NPC')

        if getattr(target_npc_data, 'hp', target_npc_data.get('health', 0)) <= 0: # Check NPC health (NPC model uses .health or .hp if it's a dict from db)
            await interaction.followup.send(f"{npc_name} is already defeated or incapacitated.", ephemeral=False)
            return

        # Initiate combat via CombatManager
        participant_ids_types = [(player_id, "Character"), (npc_id, "NPC")]

        # Context for start_combat, including managers it might need for fetching details
        start_combat_context = {
            "channel_id": channel_id,
            "character_manager": game_mngr.character_manager,
            "npc_manager": game_mngr.npc_manager,
            "rule_engine": game_mngr.rule_engine, # For initiative roll if it's moved there
            "send_callback_factory": game_mngr._get_discord_send_callback # If start_combat sends messages
        }

        new_combat = await combat_manager.start_combat(
            guild_id=guild_id,
            location_id=player_location_id,
            participant_ids_types=participant_ids_types,
            **start_combat_context
        )

        if new_combat:
            # Announce combat start and who goes first
            # Construct initiative message
            init_messages = []
            for p_obj in new_combat.participants:
                p_name = "Unknown"
                if p_obj.entity_type == "Character" and game_mngr.character_manager:
                    p_char = game_mngr.character_manager.get_character(guild_id, p_obj.entity_id)
                    if p_char: p_name = p_char.name
                elif p_obj.entity_type == "NPC" and game_mngr.npc_manager:
                    p_npc = game_mngr.npc_manager.get_npc(guild_id, p_obj.entity_id)
                    if p_npc: p_name = p_npc.name
                init_messages.append(f"{p_name} (Initiative: {p_obj.initiative})")

            initiative_summary = ", ".join(init_messages)

            first_actor_id = new_combat.get_current_actor_id()
            first_actor_name = "Someone"
            if first_actor_id:
                fa_obj = new_combat.get_participant_data(first_actor_id)
                if fa_obj:
                    if fa_obj.entity_type == "Character" and game_mngr.character_manager:
                        fa_char = game_mngr.character_manager.get_character(guild_id, fa_obj.entity_id)
                        if fa_char: first_actor_name = fa_char.name
                    elif fa_obj.entity_type == "NPC" and game_mngr.npc_manager:
                        fa_npc = game_mngr.npc_manager.get_npc(guild_id, fa_obj.entity_id)
                        if fa_npc: first_actor_name = fa_npc.name

            response_message = (
                f"⚔️ Combat started with **{npc_name}**! ⚔️\n"
                f"Initiative: {initiative_summary}\n"
                f"It's **{first_actor_name}**'s turn. Use an action command (e.g., `/attack`)."
            )
            await interaction.followup.send(response_message)

            # Log combat start
            try:
                log_msg = f"Combat started. Participants: {[(p.entity_id, p.entity_type) for p in new_combat.participants]}. Turn order: {new_combat.turn_order}."
                await db_service.add_log_entry(
                    guild_id=guild_id, event_type="COMBAT_START", message=log_msg,
                    player_id_column=player_id, # If player initiated
                    related_entities={"combat_id": new_combat.id, "participants": [p.entity_id for p in new_combat.participants]},
                    context_data={"location_id": player_location_id, "channel_id": channel_id}
                )
            except Exception as log_e:
                print(f"Error logging combat start: {log_e}")

        else:
            await interaction.followup.send(f"Failed to start combat with {npc_name}. Please try again.", ephemeral=True)

    except Exception as e:
        print(f"Error in /fight command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to start combat.", ephemeral=True)

# Add other action commands here (/use, /talk, etc.)

import traceback # For error logging
# from discord import app_commands, Interaction # Already imported at the top
from typing import Optional, TYPE_CHECKING # TYPE_CHECKING is fine here

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # Keep these for type hints within functions
    from bot.services.db_service import DBService
    from bot.services.openai_service import OpenAIService


@app_commands.command(name="talk", description="Talk to an NPC in your current location.")
@app_commands.describe(
    npc_name="The name of the NPC you want to talk to.",
    message="Your message to the NPC."
)
async def cmd_talk(interaction: Interaction, npc_name: str, message: str):
    """Allows a player to talk to an NPC, using AI for responses and managing history."""
    await interaction.response.defer(ephemeral=False)

    try:
        # --- Setup and Checks ---
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service') or \
           not hasattr(interaction.client.game_manager, 'openai_service'): # Check for openai_service
            await interaction.followup.send("Error: Core game services (DB or AI) are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        openai_service: 'OpenAIService' = client_bot.game_manager.openai_service # Get OpenAI service

        if not openai_service.is_available():
            await interaction.followup.send("The AI for dialogue is currently unavailable. Please try again later.", ephemeral=True)
            # Optionally, could fall back to a simpler pre-defined dialogue system here.
            return

        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id
        channel_id = interaction.channel_id if interaction.channel else 0 # Fallback if channel is None

        # --- Get Player Data ---
        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        player_name = player_data.get('name', 'Adventurer')
        player_location_id = player_data.get('location_id')

        if not player_id or not player_location_id:
            await interaction.followup.send("Error: Could not retrieve your character or location data.", ephemeral=True)
            return

        # --- Find NPC ---
        npcs_in_location = await db_service.get_npcs_in_location(location_id=player_location_id, guild_id=guild_id)
        target_npc_data = None
        for npc in npcs_in_location:
            if npc.get('name', '').lower() == npc_name.lower():
                target_npc_data = npc
                break

        if not target_npc_data:
            await interaction.followup.send(f"You don't see anyone named '{npc_name}' here.", ephemeral=True)
            return

        npc_id = target_npc_data.get('id')
        npc_actual_name = target_npc_data.get('name', 'Someone')
        npc_persona = target_npc_data.get('persona', 'A mysterious figure.')
        npc_description = target_npc_data.get('description')

        if not npc_id:
             await interaction.followup.send(f"Error: NPC '{npc_name}' has invalid data. Contact an admin.", ephemeral=True)
             return


        # --- Dialogue Session & AI Response ---
        session_data = await db_service.get_or_create_dialogue_session(
            player_id=player_id, npc_id=npc_id, guild_id=guild_id, channel_id=channel_id
        )
        conversation_history = session_data.get('conversation_history', [])

        # Player's current message is not yet in history for AI generation context
        ai_response_text = await openai_service.generate_npc_response(
            npc_name=npc_actual_name,
            npc_persona=npc_persona,
            npc_description=npc_description,
            conversation_history=conversation_history, # Pass existing history
            player_message=message
        )

        if not ai_response_text:
            await interaction.followup.send(f"{npc_actual_name} seems lost in thought and doesn't respond. (AI response generation failed)", ephemeral=True)
            return

        # --- Update History and Respond ---
        # Record player's message
        player_log_success = await db_service.update_dialogue_history(session_data['id'], {"speaker": player_name, "line": message})
        # Record NPC's response
        npc_log_success = await db_service.update_dialogue_history(session_data['id'], {"speaker": npc_actual_name, "line": ai_response_text})

        if player_log_success and npc_log_success:
            # Add log entry for the dialogue turn
            try:
                log_message = f"{player_name} spoke with {npc_actual_name}."
                log_related_entities = {"npc_id": npc_id, "dialogue_id": session_data['id']}
                log_context_data = {"dialogue_id": session_data['id'], "entries_added": 2}

                await db_service.add_log_entry(
                    guild_id=guild_id,
                    event_type="PLAYER_DIALOGUE_TURN",
                    message=log_message,
                    player_id_column=player_id,
                    related_entities=log_related_entities,
                    context_data=log_context_data,
                    channel_id=interaction.channel_id if interaction.channel else None
                )
                print(f"Log entry added for dialogue turn: Player {player_id}, NPC {npc_id}, Dialogue {session_data['id']}")
            except Exception as log_e:
                print(f"Error adding log entry for dialogue turn: {log_e}")
                # Non-fatal to command execution

        embed = discord.Embed(
            title=f"Talking with {npc_actual_name}",
            color=discord.Color.blue() # Or any other color
        )
        name_to_display = player_name or interaction.user.display_name
        embed.add_field(name=name_to_display, value=message, inline=False)
        embed.add_field(name=npc_actual_name, value=ai_response_text, inline=False)

        # Optionally, add a footer or timestamp
        embed.set_footer(text=f"Dialogue ID: {session_data['id']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in /talk command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to talk to the NPC.", ephemeral=True)