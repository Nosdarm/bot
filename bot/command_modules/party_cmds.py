import discord
import traceback
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, cast

# Direct import for isinstance check in setup
from bot.bot_core import RPGBot

if TYPE_CHECKING:
    # from bot.bot_core import RPGBot # Now imported directly above
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.models.character import Character # Use Character directly
    from bot.game.models.party import Party # Use Party directly

class PartyCog(commands.Cog, name="Party Commands"):
    party_group = app_commands.Group(name="party", description="Manage player parties.")

    def __init__(self, bot: "RPGBot"): # init already expects RPGBot
        self.bot = bot

    @party_group.command(name="create", description="Create a new party, making you the leader.")
    async def cmd_party_create(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot due to __init__ and setup check
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services are not fully initialized.", ephemeral=True)
            return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager:
            await interaction.followup.send("Error: Character or Party services are not fully initialized.", ephemeral=True)
            return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int) # Use Character
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character. Use `/start_new_character`.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None) # Use current_party_id
            if current_party_id: # Check if already in a party
                await interaction.followup.send(f"Already in a party (`{current_party_id}`). Leave first.", ephemeral=True); return

            current_location_id = getattr(player_char, 'current_location_id', None)
            if not current_location_id:
                await interaction.followup.send("Character not in a valid location.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager} # Ensure GM has char_mgr if needed
            new_party_obj: Optional["Party"] = await party_manager.create_party(
                leader_id=player_char.id, member_ids=[player_char.id], guild_id=guild_id_str,
                current_location_id=current_location_id, **context_kwargs
            )
            if new_party_obj and new_party_obj.id:
                # Use set_current_party_id on CharacterManager
                update_success = await char_manager.set_current_party_id(guild_id_str, player_char.id, new_party_obj.id)
                if update_success:
                    await interaction.followup.send(f"Party created! ID: `{new_party_obj.id}`.", ephemeral=False)
                else:
                    await party_manager.remove_party(new_party_obj.id, guild_id_str, **context_kwargs) # Pass context for member cleanup
                    await interaction.followup.send("Party created, but failed to assign you. Party removed.", ephemeral=True)
            else:
                await interaction.followup.send("Failed to create party (internal error).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error creating party: {e}", ephemeral=True); traceback.print_exc()


    @party_group.command(name="disband", description="Disband your current party (leader only).")
    async def cmd_party_disband(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True); return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager:
            await interaction.followup.send("Error: Character or Party services are not fully initialized.", ephemeral=True); return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int)
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None)
            if not current_party_id:
                await interaction.followup.send("Not in a party.", ephemeral=True); return

            party_to_disband: Optional["Party"] = party_manager.get_party(guild_id_str, current_party_id) # Use Party
            if not party_to_disband:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None) # Clear inconsistent data
                await interaction.followup.send("Party info inconsistent, cleared your status.", ephemeral=True); return

            if party_to_disband.leader_id != player_char.id:
                await interaction.followup.send("Only the party leader can disband the party.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
            disband_success = await party_manager.remove_party(current_party_id, guild_id_str, **context_kwargs)
            if disband_success:
                party_name_display = getattr(party_to_disband, 'name_i18n', {}).get(player_char.selected_language or 'en', current_party_id) if hasattr(party_to_disband, 'name_i18n') else getattr(party_to_disband, 'name', current_party_id)
                await interaction.followup.send(f"Party '{party_name_display}' disbanded.", ephemeral=False)
            else:
                await interaction.followup.send("Error disbanding party.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True); traceback.print_exc()


    @party_group.command(name="join", description="Join an existing party.")
    @app_commands.describe(party_identifier="The ID of the party you want to join.")
    async def cmd_party_join(self, interaction: Interaction, party_identifier: str):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True); return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager or not game_mngr.location_manager:
            await interaction.followup.send("Error: Character, Party or Location services are not fully initialized.", ephemeral=True); return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        loc_manager: "LocationManager" = game_mngr.location_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int) # Use Character
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None)
            if current_party_id:
                await interaction.followup.send(f"Already in a party (`{current_party_id}`). Leave first.", ephemeral=True); return

            current_location_id = getattr(player_char, 'current_location_id', None)
            if not current_location_id:
                await interaction.followup.send("Character not in a valid location.", ephemeral=True); return

            target_party: Optional["Party"] = party_manager.get_party(guild_id_str, party_identifier) # Use Party
            if not target_party:
                await interaction.followup.send(f"Party '{party_identifier}' not found.", ephemeral=True); return

            if target_party.current_location_id is None: # Explicit None check for party's location
                await interaction.followup.send(f"Party '{party_identifier}' is not currently at a known location.", ephemeral=True)
                return

            if current_location_id != target_party.current_location_id:
                player_loc_name = loc_manager.get_location_name(guild_id_str, current_location_id) or current_location_id
                party_loc_name = loc_manager.get_location_name(guild_id_str, target_party.current_location_id) or target_party.current_location_id # target_party.current_location_id is now checked not to be None
                await interaction.followup.send(f"Must be in same location. You: '{player_loc_name}', Party: '{party_loc_name}'.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
            join_success = await party_manager.add_member_to_party(target_party.id, player_char.id, guild_id_str, context_kwargs)
            if join_success:
                update_char_success = await char_manager.set_current_party_id(guild_id_str, player_char.id, target_party.id)
                if update_char_success:
                    party_name_display = getattr(target_party, 'name_i18n', {}).get(player_char.selected_language or 'en', target_party.id) if hasattr(target_party, 'name_i18n') else getattr(target_party, 'name', target_party.id)
                    await interaction.followup.send(f"Joined '{party_name_display}'!", ephemeral=False)
                else:
                    await party_manager.remove_member_from_party(target_party.id, player_char.id, guild_id_str, context_kwargs)
                    await interaction.followup.send("Joined party, but failed to update char. Reverted.", ephemeral=True)
            else:
                await interaction.followup.send("Failed to join party (full or error).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error joining party: {e}", ephemeral=True); traceback.print_exc()

    @party_group.command(name="leave", description="Leave your current party.")
    async def cmd_party_leave(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # Assuming self.bot is already RPGBot
        bot_instance: RPGBot = self.bot
        if not hasattr(bot_instance, 'game_manager') or bot_instance.game_manager is None:
            await interaction.followup.send("Error: Core game services not initialized.", ephemeral=True); return

        game_mngr: "GameManager" = bot_instance.game_manager
        if not game_mngr.character_manager or not game_mngr.party_manager or not game_mngr.location_manager:
            await interaction.followup.send("Error: Character, Party or Location services are not fully initialized.", ephemeral=True); return

        char_manager: "CharacterManager" = game_mngr.character_manager
        party_manager: "PartyManager" = game_mngr.party_manager
        loc_manager: "LocationManager" = game_mngr.location_manager
        guild_id_str = str(interaction.guild_id)
        discord_user_id_int = interaction.user.id
        try:
            player_char: Optional["Character"] = char_manager.get_character_by_discord_id(guild_id_str, discord_user_id_int) # Use Character
            if not player_char or not player_char.id:
                await interaction.followup.send("You need a character.", ephemeral=True); return

            current_party_id = getattr(player_char, 'current_party_id', None)
            if not current_party_id:
                await interaction.followup.send("Not in a party.", ephemeral=True); return

            party_to_leave: Optional["Party"] = party_manager.get_party(guild_id_str, current_party_id) # Use Party
            if not party_to_leave:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None)
                await interaction.followup.send("Party info inconsistent, cleared your status.", ephemeral=True); return

            current_location_id = getattr(player_char, 'current_location_id', None)
            if not current_location_id:
                 await interaction.followup.send("Character not in a valid location.", ephemeral=True); return

            party_location_id = getattr(party_to_leave, 'current_location_id', None)
            if party_location_id is None: # Explicit None check
                 await interaction.followup.send(f"Party '{current_party_id}' is not currently at a known location.", ephemeral=True); return

            if current_location_id != party_location_id:
                player_loc_name = loc_manager.get_location_name(guild_id_str, current_location_id) or current_location_id
                party_loc_name = loc_manager.get_location_name(guild_id_str, party_location_id) or party_location_id # party_location_id is now checked not to be None
                await interaction.followup.send(f"Must be in same location to leave. You: '{player_loc_name}', Party: '{party_loc_name}'.", ephemeral=True); return

            context_kwargs = {"guild_id": guild_id_str, "character_manager": char_manager}
            leave_success = await party_manager.remove_member_from_party(current_party_id, player_char.id, guild_id_str, context_kwargs)
            if leave_success:
                await char_manager.set_current_party_id(guild_id_str, player_char.id, None) # No context needed for set_current_party_id as it's direct attribute
                party_name_display = getattr(party_to_leave, 'name_i18n', {}).get(player_char.selected_language or 'en', current_party_id) if hasattr(party_to_leave, 'name_i18n') else getattr(party_to_leave, 'name', current_party_id)
                await interaction.followup.send(f"Left '{party_name_display}'.", ephemeral=False)
            else:
                await interaction.followup.send("Error leaving party.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True); traceback.print_exc()


async def setup(bot: commands.Bot):
    if not isinstance(bot, RPGBot):
        print("Error: PartyCommands setup received a bot instance that is not RPGBot.")
        return
    await bot.add_cog(PartyCog(bot))
    print("PartyCog loaded.")
