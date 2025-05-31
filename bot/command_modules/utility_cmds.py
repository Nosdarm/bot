# bot/command_modules/utility_cmds.py
import discord
from discord import app_commands, Interaction
from typing import Optional, TYPE_CHECKING, Dict, Any, List
import traceback

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.services.db_service import DBService

# TEST_GUILD_IDS can be used if you want to restrict commands to specific guilds during testing
# from bot.bot_core import LOADED_TEST_GUILD_IDS as TEST_GUILD_IDS
# TEST_GUILD_IDS = [] # Or leave empty for global / controlled by RPGBot debug_guilds

@app_commands.command(name="undo", description="Reverts your last game action.")
async def cmd_undo(interaction: Interaction):
    """Allows a player to undo their last recorded game action."""
    await interaction.response.defer(ephemeral=True) # Start ephemeral, can make public if action is public

    try:
        if not hasattr(interaction.client, 'game_manager') or \
           not hasattr(interaction.client.game_manager, 'db_service'):
            await interaction.followup.send("Error: Game systems are not fully initialized.", ephemeral=True)
            return

        client_bot: 'RPGBot' = interaction.client
        db_service: 'DBService' = client_bot.game_manager.db_service
        guild_id = str(interaction.guild_id)
        discord_user_id = interaction.user.id

        player_data = await db_service.get_player_by_discord_id(discord_user_id=discord_user_id, guild_id=guild_id)
        if not player_data:
            await interaction.followup.send("You need to create a character first! Use `/start`.", ephemeral=True)
            return

        player_id = player_data.get('id')
        if not player_id:
            await interaction.followup.send("Error retrieving your character ID.", ephemeral=True)
            return

        log_entry = await db_service.get_last_undoable_player_action(player_id=player_id, guild_id=guild_id)

        if not log_entry:
            await interaction.followup.send("No action available to undo.", ephemeral=True)
            return

        event_type = log_entry.get('event_type')
        context_data = log_entry.get('context_data', {})
        log_id_to_mark = log_entry.get('log_id')

        success = False
        undo_message = f"Could not undo action: '{event_type}'."

        if event_type == "PLAYER_MOVE":
            old_loc_id = context_data.get('old_location_id')
            if old_loc_id:
                await db_service.update_player_location(player_id=player_id, new_location_id=old_loc_id)
                # Fetch old location name for a better message
                old_loc_data = await db_service.get_location(location_id=old_loc_id, guild_id=guild_id)
                old_loc_name = old_loc_data.get('name', 'your previous location') if old_loc_data else 'your previous location'
                undo_message = f"You have moved back to {old_loc_name}."
                success = True
            else:
                undo_message = "Error: Move action context data is missing old location ID."

        elif event_type == "PLAYER_PICKUP_ITEM":
            item_template_id = context_data.get('item_template_id')
            quantity = context_data.get('quantity')
            # original_item_instance_id = context_data.get('original_item_instance_id') # Not needed for recreate
            original_location_id = context_data.get('original_location_id')

            if item_template_id and quantity is not None and original_location_id:
                # 1. Remove from inventory (this needs to be exact)
                # Assuming remove_item_from_inventory can handle if item partially used/gone
                # For simplicity, this assumes the exact quantity is still there.
                # A more robust undo might need to check current quantity.
                await db_service.remove_item_from_inventory(player_id, item_template_id, quantity)

                # 2. Recreate item instance in the original location
                # We don't have the original_item_instance_id's specific state_variables here,
                # so we recreate a fresh instance from template.
                new_instance_id = await db_service.create_item_instance(
                    template_id=item_template_id,
                    guild_id=guild_id,
                    quantity=quantity,
                    location_id=original_location_id,
                    owner_id=original_location_id, # Assuming items on ground owned by location
                    owner_type='location'
                )
                if new_instance_id:
                    item_def = await db_service.get_item_definition(item_template_id)
                    item_name_disp = item_def.get('name', 'The item') if item_def else 'The item'
                    loc_def = await db_service.get_location(original_location_id, guild_id)
                    loc_name_disp = loc_def.get('name', 'its previous location') if loc_def else 'its previous location'
                    undo_message = f"{item_name_disp} (x{quantity}) removed from your inventory and returned to {loc_name_disp}."
                    success = True
                else:
                    undo_message = "Error: Failed to return item to its location. Inventory may be incorrect."
                    # Here, a compensating action might be to try and give item back to player if it was removed.
            else:
                undo_message = "Error: Pickup action context data is incomplete."

        elif event_type == "PLAYER_COMBAT_ROUND":
            player_hp_before = context_data.get('player_hp_before_round')
            npc_id_fought = context_data.get('npc_id')
            npc_hp_before = context_data.get('npc_hp_before_round')

            if player_hp_before is not None and npc_id_fought and npc_hp_before is not None:
                await db_service.update_player_hp(player_id=player_id, new_hp=int(player_hp_before), guild_id=guild_id)
                await db_service.update_npc_hp(npc_id=npc_id_fought, new_hp=int(npc_hp_before), guild_id=guild_id)

                npc_data_for_name = await db_service.get_npc(npc_id_fought, guild_id)
                npc_name_disp = npc_data_for_name.get('name', 'the NPC') if npc_data_for_name else 'the NPC'
                undo_message = f"Combat round with {npc_name_disp} undone. HP for both participants restored to pre-round values."
                success = True
            else:
                undo_message = "Error: Combat action context data is incomplete."

        elif event_type == "PLAYER_DIALOGUE_TURN":
            dialogue_id = context_data.get('dialogue_id')
            entries_to_remove_count = context_data.get('entries_added', 0)

            if dialogue_id and entries_to_remove_count > 0:
                # Fetch the session, which includes current history
                # get_or_create will work, but ideally, a get_session_by_id would be better if it exists
                # For now, this is fine as it will fetch the existing one.
                session = await db_service.get_or_create_dialogue_session(player_id, context_data.get('npc_id', ''), guild_id, interaction.channel_id or 0)

                if session and session['id'] == dialogue_id : # Ensure we got the correct session
                    current_history: List[Dict[str,str]] = session.get('conversation_history', [])
                    if len(current_history) >= entries_to_remove_count:
                        new_history = current_history[:-entries_to_remove_count]
                        await db_service.set_dialogue_history(dialogue_id, new_history)
                        undo_message = "Last part of your conversation undone."
                        success = True
                    else:
                        undo_message = "Error: Not enough dialogue entries to remove for undo."
                else:
                    undo_message = "Error: Could not retrieve dialogue session for undo."
            else:
                undo_message = "Error: Dialogue action context data is incomplete."
        else:
            undo_message = f"Action type '{event_type}' cannot be undone at this time."

        if success and log_id_to_mark:
            await db_service.mark_log_as_undone(log_id_to_mark, guild_id)
            await interaction.followup.send(undo_message, ephemeral=False) # Make successful undos public
        else:
            await interaction.followup.send(undo_message, ephemeral=True) # Errors or non-undoable are ephemeral

    except Exception as e:
        print(f"Error in /undo command: {e}")
        traceback.print_exc()
        await interaction.followup.send("An unexpected error occurred while trying to undo your action.", ephemeral=True)
