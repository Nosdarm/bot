import discord
from discord import slash_command # Or commands.Cog
from typing import Optional

# --- Temporary global references ---
from bot.bot_core import global_game_manager
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Copy from bot_core.py


# Placeholder for /interact command
@slash_command(name="interact", description="Взаимодействовать с чем-то или кем-то.", guild_ids=TEST_GUILD_IDS)
async def cmd_interact(ctx: discord.ApplicationContext, target: str, action: str, *, details: Optional[str] = None):
    await ctx.defer()
    if global_game_manager:
         response_data = await global_game_manager.process_player_action(
             server_id=ctx.guild.id,
             discord_user_id=ctx.author.id,
             action_type="interact",
             action_data={"target": target, "action": action, "details": details}
         )
         await ctx.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."))
    else:
         await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

import random # For basic combat roll

@app_commands.command(name="fight", description="Engage in combat with an NPC.")
@app_commands.describe(target_npc_name="The name of the NPC you want to fight (optional).")
async def cmd_fight(interaction: Interaction, target_npc_name: Optional[str] = None):
    """Initiates a basic combat round with an NPC."""
    await interaction.response.defer(ephemeral=False) # Combat is generally public

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: The game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        # 1. Get Player Information
        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        player_location_id = player_data.get('location_id')
        player_hp = player_data.get('hp', 0)
        player_attack = player_data.get('attack', 0) # Direct stat from players table
        player_defense = player_data.get('defense', 0) # Direct stat from players table

        if not player_id or not player_location_id:
            await interaction.followup.send("Error: Could not retrieve your character or location data.", ephemeral=True)
            return

        # 2. Find Target NPC in Location
        npcs_in_location = await db_service.get_npcs_in_location(location_id=player_location_id, guild_id=guild_id)

        if not npcs_in_location:
            await interaction.followup.send("There's nothing to fight here.", ephemeral=True)
            return

        target_npc_data = None
        if target_npc_name:
            for npc in npcs_in_location:
                if npc.get('name', '').lower() == target_npc_name.lower():
                    target_npc_data = npc
                    break
            if not target_npc_data:
                await interaction.followup.send(f"NPC '{target_npc_name}' not found here.", ephemeral=True)
                return
        else: # No target specified
            if len(npcs_in_location) == 1:
                target_npc_data = npcs_in_location[0]
                target_npc_name = target_npc_data.get('name', 'the creature') # Get name for messages
                await interaction.followup.send(f"You engage the only available target: {target_npc_name}!", ephemeral=False)
            else:
                npc_names = ", ".join([npc['name'] for npc in npcs_in_location])
                await interaction.followup.send(f"Please specify which NPC to fight. Available targets: {npc_names}", ephemeral=True)
                return

        npc_id = target_npc_data.get('id')
        npc_hp = target_npc_data.get('health', 0) # 'health' column for npcs
        npc_stats = target_npc_data.get('stats', {})
        npc_attack = npc_stats.get('attack', 0) # Attack from NPC's stats
        npc_defense = npc_stats.get('defense', 0) # Defense from NPC's stats (assuming it exists)

        if npc_hp <= 0:
            await interaction.followup.send(f"{target_npc_data.get('name', 'The target')} is already defeated or incapacitated.", ephemeral=False)
            return

        combat_messages = []
        player_name_for_msg = player_data.get('name', 'You')
        npc_name_for_msg = target_npc_data.get('name', 'The NPC')

        # Store initial HP for logging context
        player_hp_before_round = player_hp
        npc_hp_before_round = npc_hp

        player_damage_dealt = 0
        npc_damage_dealt = 0
        npc_defeated = False
        player_defeated = False

        # 3. Basic Combat Round (One Exchange)
        # Player's Turn
        player_damage_dealt = max(1, player_attack - npc_defense + random.randint(-2,2))
        npc_hp_after_player_attack = npc_hp_before_round - player_damage_dealt
        await db_service.update_npc_hp(npc_id=npc_id, new_hp=npc_hp_after_player_attack, guild_id=guild_id)
        combat_messages.append(f"{player_name_for_msg} attacks {npc_name_for_msg} for {player_damage_dealt} damage! {npc_name_for_msg} has {max(0, npc_hp_after_player_attack)} HP remaining.")

        if npc_hp_after_player_attack <= 0:
            combat_messages.append(f"**{npc_name_for_msg} has been defeated!**")
            npc_defeated = True
            # current_player_hp_for_log remains player_hp_before_round as NPC didn't attack
            # current_npc_hp_for_log is max(0, npc_hp_after_player_attack)
        else:
            # NPC's Turn (only if not defeated)
            npc_damage_dealt = max(1, npc_attack - player_defense + random.randint(-1,1))
            player_hp_after_npc_attack = player_hp_before_round - npc_damage_dealt
            await db_service.update_player_hp(player_id=player_id, new_hp=player_hp_after_npc_attack, guild_id=guild_id)
            combat_messages.append(f"{npc_name_for_msg} retaliates, attacking {player_name_for_msg} for {npc_damage_dealt} damage! You have {max(0, player_hp_after_npc_attack)} HP remaining.")

            if player_hp_after_npc_attack <= 0:
                combat_messages.append(f"**You have been defeated by {npc_name_for_msg}!**")
                player_defeated = True

        # Determine final HPs for log message
        final_player_hp = max(0, player_hp_after_npc_attack if not npc_defeated else player_hp_before_round)
        final_npc_hp = max(0, npc_hp_after_player_attack)

        # Add log entry for the combat round
        try:
            log_message = (
                f"{player_name_for_msg} (HP: {final_player_hp}) fought {npc_name_for_msg} (HP: {final_npc_hp}). "
                f"Player dealt {player_damage_dealt} damage. "
                f"NPC dealt {npc_damage_dealt if not npc_defeated else 0} damage."
            )
            log_related_entities = {"npc_id": npc_id, "player_id": player_id} # player_id also in direct column
            log_context_data = {
                "player_id": player_id,
                "player_hp_before_round": player_hp_before_round,
                "player_hp_after_round": final_player_hp,
                "npc_id": npc_id,
                "npc_hp_before_round": npc_hp_before_round,
                "npc_hp_after_round": final_npc_hp,
                "player_damage_dealt": player_damage_dealt,
                "npc_damage_dealt": npc_damage_dealt if not npc_defeated else 0
            }
            await db_service.add_log_entry(
                guild_id=guild_id,
                event_type="PLAYER_COMBAT_ROUND",
                message=log_message,
                player_id_column=player_id,
                related_entities=log_related_entities,
                context_data=log_context_data,
                channel_id=interaction.channel_id if interaction.channel else None
            )
            print(f"Log entry added for combat round: Player {player_id} vs NPC {npc_id}")
        except Exception as log_e:
            print(f"Error adding log entry for combat round: {log_e}")
            # Non-fatal to the command execution itself

        if not npc_defeated and not player_defeated:
            combat_messages.append("The fight continues...")

        await interaction.followup.send("\n".join(combat_messages))

    except Exception as e:
        print(f"Error in /fight command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred during combat.", ephemeral=True)

# Add other action commands here (/use, /talk, etc.)

import traceback # For error logging
from discord import app_commands, Interaction # Use Interaction for type hinting
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
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
        embed.add_field(name=player_name (or interaction.user.display_name), value=message, inline=False)
        embed.add_field(name=npc_actual_name, value=ai_response_text, inline=False)

        # Optionally, add a footer or timestamp
        embed.set_footer(text=f"Dialogue ID: {session_data['id']}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in /talk command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to talk to the NPC.", ephemeral=True)