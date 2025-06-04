# bot/command_modules/party_cmds.py
import discord
from discord import app_commands, Interaction
from typing import Optional, TYPE_CHECKING, cast

from bot.bot_core import RPGBot

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.models.character import Character as CharacterModel
    from bot.game.models.party import Party as PartyModel
    # from bot.game.command_handlers.party_handler import PartyCommandHandler # Decide if to use directly

# Define the command group
party_group = app_commands.Group(name="party", description="Manage player parties.")

@party_group.command(name="create", description="Create a new party, making you the leader.")
async def cmd_party_create(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or not bot.game_manager.character_manager or not bot.game_manager.party_manager:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    party_manager: "PartyManager" = bot.game_manager.party_manager
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        player_char: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not player_char or not player_char.id:
            await interaction.followup.send("You need to have a character to create a party. Use `/start`.", ephemeral=True)
            return

        if player_char.party_id:
            await interaction.followup.send(f"You are already in a party (ID: `{player_char.party_id}`). Please leave it first using `/party leave`.", ephemeral=True)
            return

        if not player_char.location_id:
            await interaction.followup.send("Your character is not in a valid location. Cannot create a party.", ephemeral=True)
            return

        # Context for PartyManager methods (though create_party might not use much from it directly for this call)
        context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}


        new_party_obj: Optional[PartyModel] = await party_manager.create_party(
            leader_id=player_char.id,
            member_ids=[player_char.id],
            guild_id=guild_id_str,
            current_location_id=player_char.location_id,
            **context_kwargs
        )

        if new_party_obj and new_party_obj.id:
            update_success = await char_manager.set_party_id(guild_id_str, player_char.id, new_party_obj.id, **context_kwargs)
            if update_success:
                await interaction.followup.send(f"Party created successfully! Your party ID is `{new_party_obj.id}`.", ephemeral=False)
            else:
                # Attempt to clean up the created party if character update failed
                await party_manager.remove_party(new_party_obj.id, guild_id_str, **context_kwargs)
                await interaction.followup.send("Party was created, but failed to assign you to it. The party has been removed. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("Failed to create the party due to an internal error.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred while creating the party: {e}", ephemeral=True)
        traceback.print_exc()

@party_group.command(name="disband", description="Disband your current party (leader only).")
async def cmd_party_disband(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or not bot.game_manager.character_manager or not bot.game_manager.party_manager:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    party_manager: "PartyManager" = bot.game_manager.party_manager
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        player_char: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not player_char or not player_char.id:
            await interaction.followup.send("You need to have a character. Use `/start`.", ephemeral=True)
            return

        current_party_id = player_char.party_id
        if not current_party_id:
            await interaction.followup.send("You are not currently in a party.", ephemeral=True)
            return

        party_to_disband = party_manager.get_party(guild_id_str, current_party_id)
        if not party_to_disband:
            await char_manager.set_party_id(guild_id_str, player_char.id, None) # Clean inconsistent state
            await interaction.followup.send("Your party information was inconsistent and has been cleared. You are not in a party.", ephemeral=True)
            return

        if party_to_disband.leader_id != player_char.id:
            await interaction.followup.send("Only the party leader can disband the party.", ephemeral=True)
            return

        context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
        disband_success = await party_manager.remove_party(current_party_id, guild_id_str, **context_kwargs)

        if disband_success:
            party_name = party_to_disband.name or f"Party {current_party_id}"
            await interaction.followup.send(f"Party '{party_name}' has been disbanded.", ephemeral=False)
        else:
            await interaction.followup.send("An error occurred while trying to disband the party.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
        traceback.print_exc()

@party_group.command(name="join", description="Join an existing party.")
@app_commands.describe(party_identifier="The ID of the party you want to join.")
async def cmd_party_join(interaction: Interaction, party_identifier: str):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or not bot.game_manager.character_manager or not bot.game_manager.party_manager or not bot.game_manager.location_manager:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    party_manager: "PartyManager" = bot.game_manager.party_manager
    loc_manager: "LocationManager" = bot.game_manager.location_manager
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        player_char: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not player_char or not player_char.id:
            await interaction.followup.send("You need to have a character to join a party. Use `/start`.", ephemeral=True)
            return

        if player_char.party_id:
            await interaction.followup.send(f"You are already in a party (ID: `{player_char.party_id}`). Please leave it first.", ephemeral=True)
            return

        if not player_char.location_id:
            await interaction.followup.send("Your character is not in a valid location.", ephemeral=True)
            return

        target_party: Optional[PartyModel] = party_manager.get_party(guild_id_str, party_identifier)
        if not target_party:
            await interaction.followup.send(f"Party with ID or leader name '{party_identifier}' not found.", ephemeral=True)
            return

        if player_char.location_id != target_party.current_location_id:
            player_loc_name = loc_manager.get_location_name(guild_id_str, player_char.location_id) or player_char.location_id
            party_loc_name = loc_manager.get_location_name(guild_id_str, target_party.current_location_id) or target_party.current_location_id
            await interaction.followup.send(f"You must be in the same location as the party. You are in '{player_loc_name}', the party is in '{party_loc_name}'.", ephemeral=True)
            return

        context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
        join_success = await party_manager.add_member_to_party(target_party.id, player_char.id, guild_id_str, context_kwargs)

        if join_success:
            update_char_success = await char_manager.set_party_id(guild_id_str, player_char.id, target_party.id, **context_kwargs)
            if update_char_success:
                party_name_display = target_party.name or f"Party {target_party.id}"
                await interaction.followup.send(f"Successfully joined '{party_name_display}'!", ephemeral=False)
            else:
                # Revert adding to party if char update fails
                await party_manager.remove_member_from_party(target_party.id, player_char.id, guild_id_str, context_kwargs)
                await interaction.followup.send("Joined party, but failed to update your character status. The action has been reverted. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("Failed to join the party. It might be full or an internal error occurred.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred while joining the party: {e}", ephemeral=True)
        traceback.print_exc()

@party_group.command(name="leave", description="Leave your current party.")
async def cmd_party_leave(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    bot = cast(RPGBot, interaction.client)

    if not bot.game_manager or not bot.game_manager.character_manager or not bot.game_manager.party_manager or not bot.game_manager.location_manager:
        await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
        return

    char_manager: "CharacterManager" = bot.game_manager.character_manager
    party_manager: "PartyManager" = bot.game_manager.party_manager
    loc_manager: "LocationManager" = bot.game_manager.location_manager
    guild_id_str = str(interaction.guild_id)
    discord_user_id_int = interaction.user.id

    try:
        player_char: Optional[CharacterModel] = await char_manager.get_character_by_discord_id(
            guild_id=guild_id_str,
            discord_user_id=discord_user_id_int
        )

        if not player_char or not player_char.id:
            await interaction.followup.send("You need to have a character. Use `/start`.", ephemeral=True)
            return

        current_party_id = player_char.party_id
        if not current_party_id:
            await interaction.followup.send("You are not currently in a party.", ephemeral=True)
            return

        party_to_leave = party_manager.get_party(guild_id_str, current_party_id)
        if not party_to_leave:
            await char_manager.set_party_id(guild_id_str, player_char.id, None) # Clean inconsistent state
            await interaction.followup.send("Your party information was inconsistent and has been cleared. You are not in a party.", ephemeral=True)
            return

        if not player_char.location_id:
            await interaction.followup.send("Your character is not in a valid location. Cannot leave party now.", ephemeral=True)
            return

        if player_char.location_id != party_to_leave.current_location_id:
            player_loc_name = loc_manager.get_location_name(guild_id_str, player_char.location_id) or player_char.location_id
            party_loc_name = loc_manager.get_location_name(guild_id_str, party_to_leave.current_location_id) or party_to_leave.current_location_id
            await interaction.followup.send(f"You must be in the same location as your party to leave it. You are in '{player_loc_name}', the party is in '{party_loc_name}'.", ephemeral=True)
            return

        context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
        # remove_member_from_party handles leader migration or disbanding if last member.
        leave_success = await party_manager.remove_member_from_party(current_party_id, player_char.id, guild_id_str, context_kwargs)

        if leave_success:
            # Character's party_id should be set to None by PartyManager if successful (either directly or via remove_party)
            # but we ensure it here for the CharacterManager's cache too.
            await char_manager.set_party_id(guild_id_str, player_char.id, None, **context_kwargs)
            party_name_display = party_to_leave.name or f"Party {current_party_id}"
            await interaction.followup.send(f"You have left '{party_name_display}'.", ephemeral=False)
        else:
            await interaction.followup.send("An error occurred while trying to leave the party.", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
        traceback.print_exc()

def setup(bot: RPGBot):
    bot.tree.add_command(party_group)
