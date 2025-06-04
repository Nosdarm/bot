# bot/command_modules/master_cmds.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands # For Bot type hint if needed in future
import json
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.game_manager import GameManager

# Assuming is_master_or_admin can be adapted or is available in game_setup_cmds
# For now, let's use a placeholder structure and adapt the call.
from bot.command_modules.game_setup_cmds import is_master_or_admin

# Placeholder/Adapter check function for app_commands
async def is_master_or_admin_check_for_app_command(interaction: discord.Interaction) -> bool:
    """
    Checks if the user invoking the command is a Master or Admin.
    Adapter for app_commands to use the existing logic from game_setup_cmds.
    """
    # The original is_master_or_admin expects a Context-like object and a GameManager.
    # We need to simulate this or adapt is_master_or_admin if it's strictly for Context.
    # For now, assuming interaction.client has game_manager and is_master_or_admin can handle it.
    if not hasattr(interaction.client, 'game_manager'):
        print("is_master_or_admin_check_for_app_command: RPGBot instance (interaction.client) does not have game_manager.")
        return False

    # Create a lightweight object that mimics discord.ext.commands.Context enough for is_master_or_admin
    class MockContext:
        def __init__(self, interaction_obj: discord.Interaction):
            self.author = interaction_obj.user
            self.guild = interaction_obj.guild
            self.channel = interaction_obj.channel
            # Add other attributes if is_master_or_admin needs them

    mock_ctx = MockContext(interaction)
    bot_instance = interaction.client
    # Type cast to RPGBot to satisfy type hints for game_manager
    if TYPE_CHECKING:
        bot_instance = typing.cast(RPGBot, bot_instance)

    return await is_master_or_admin(mock_ctx, bot_instance.game_manager)


class MasterCommandsCog(commands.Cog):
    def __init__(self, bot: RPGBot):
        self.bot = bot

    @app_commands.command(name="approve_generated_content", description="Одобрить ожидающий модерации контент по ID запроса.")
    @app_commands.check(is_master_or_admin_check_for_app_command)
    async def approve_generated_content(self, interaction: discord.Interaction, request_id: str):
        """
        Одобрить ожидающий модерации контент (например, локацию) по ID запроса.
        """
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = interaction.client
        if not bot_instance or not hasattr(bot_instance, 'game_manager'):
            await interaction.followup.send("Ошибка: Экземпляр бота или игровой менеджер не найден.", ephemeral=True)
            return

        db_adapter: SqliteAdapter = bot_instance.game_manager._db_adapter
        loc_manager: LocationManager = bot_instance.game_manager.location_manager
        status_manager: StatusManager = bot_instance.game_manager.status_manager
        char_manager: CharacterManager = bot_instance.game_manager.character_manager

        if not all([db_adapter, loc_manager, status_manager, char_manager]):
            await interaction.followup.send("Ошибка: Один или несколько менеджеров не инициализированы.", ephemeral=True)
            return

        try:
            moderation_request_row = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request_row:
                await interaction.followup.send(f"Ошибка: Запрос на модерацию с ID '{request_id}' не найден.", ephemeral=True)
                return

            if moderation_request_row['status'] != 'pending':
                await interaction.followup.send(f"Ошибка: Запрос '{request_id}' уже обработан (статус: {moderation_request_row['status']}).", ephemeral=True)
                return

            content_type = moderation_request_row['content_type']
            if content_type != 'location':
                await interaction.followup.send(f"Ошибка: Обработка контента типа '{content_type}' пока не поддерживается. Поддерживается только 'location'.", ephemeral=True)
                return

            location_data = json.loads(moderation_request_row['data'])
            user_id_str = moderation_request_row['user_id'] # This is Discord User ID as string

            # Prepare context for create_location_instance_from_moderated_data
            # This context might need more data depending on the method's requirements
            creation_context = {
                "guild_id": str(interaction.guild_id),
                "user_id": user_id_str, # Creator's Discord ID
                "approver_id": str(interaction.user.id), # Master/Admin's Discord ID
                "db_adapter": db_adapter,
                "location_manager": loc_manager,
                "status_manager": status_manager,
                "character_manager": char_manager,
                # Add other managers if they become necessary for create_location_instance_from_moderated_data
            }

            created_instance_data = await loc_manager.create_location_instance_from_moderated_data(
                guild_id=str(interaction.guild_id),
                location_data=location_data,
                user_id=user_id_str, # Pass creator's user_id for logging/attribution
                context=creation_context
            )

            if created_instance_data and not created_instance_data.get("error"):
                new_instance_id = created_instance_data.get('id', 'N/A')

                # Remove 'waiting_moderation' status from the player who created the content
                try:
                    # User ID from the request is the Discord User ID.
                    # StatusManager might expect Character ID.
                    player_char = await char_manager.get_character_by_discord_id(
                        discord_user_id=int(user_id_str),
                        guild_id=str(interaction.guild_id)
                    )
                    if player_char and player_char.id:
                        # Assuming StatusManager uses character_id for 'Character' target_type
                        status_removal_context = {"source": "moderation_approval"} # Example context
                        await status_manager.remove_status_effects_by_type(
                            target_id=player_char.id,
                            target_type='Character', # Make sure this matches StatusManager's expectation
                            status_type_to_remove='waiting_moderation',
                            guild_id=str(interaction.guild_id),
                            context=status_removal_context
                        )
                        print(f"MasterCmds: Removed 'waiting_moderation' status from character {player_char.id} (User: {user_id_str}).")
                    elif not player_char:
                         print(f"MasterCmds: Could not find character for user ID {user_id_str} to remove 'waiting_moderation' status.")
                except Exception as e_status:
                    print(f"MasterCmds: Error removing 'waiting_moderation' status for user {user_id_str}: {e_status}")
                    # Non-critical, log and continue

                await db_adapter.delete_pending_moderation_request(request_id)

                # --- Trigger post-save logic (14) for approved location ---
                if player_char and created_instance_data: # player_char fetched for status removal
                    arrival_context = {
                        'guild_id': str(interaction.guild_id),
                        'player_id': player_char.id,
                        'character': player_char,
                        'location_manager': loc_manager,
                        'character_manager': char_manager,
                        'npc_manager': bot_instance.game_manager.npc_manager,
                        'item_manager': bot_instance.game_manager.item_manager,
                        'event_manager': bot_instance.game_manager.event_manager,
                        'status_manager': status_manager,
                        'rule_engine': bot_instance.game_manager.rule_engine,
                        'time_manager': bot_instance.game_manager.time_manager,
                        'send_callback_factory': bot_instance.game_manager.send_callback_factory,
                        'location_instance_data': created_instance_data,
                         # Add other managers from bot_instance.game_manager if available and relevant
                        'event_stage_processor': bot_instance.game_manager.event_stage_processor,
                        'event_action_processor': bot_instance.game_manager.event_action_processor,
                        'on_enter_action_executor': bot_instance.game_manager.on_enter_action_executor,
                        'stage_description_generator': bot_instance.game_manager.stage_description_generator,
                    }
                    try:
                        print(f"MasterCmds: Triggering handle_entity_arrival for approved location {new_instance_id} for character {player_char.id}.")
                        await loc_manager.handle_entity_arrival(
                            location_id=new_instance_id,
                            entity_id=player_char.id,
                            entity_type='Character',
                            **arrival_context
                        )
                    except Exception as e_arrival:
                        print(f"MasterCmds: ERROR during post-approval logic (handle_entity_arrival) for location {new_instance_id}: {e_arrival}")
                        # Log error, but the main approval process was successful.
                elif not player_char:
                    print(f"MasterCmds: WARNING - player_char not found for post-approval logic (handle_entity_arrival) for location {new_instance_id}. User ID: {user_id_str}")
                # --- End of post-save logic ---

                await interaction.followup.send(f"Контент для запроса '{request_id}' (тип: {content_type}) одобрен и создан. ID нового инстанса: {new_instance_id}", ephemeral=True)
            else:
                error_detail = created_instance_data.get("error", "Неизвестная ошибка") if isinstance(created_instance_data, dict) else "Неизвестная ошибка"
                await interaction.followup.send(f"Ошибка при создании контента из одобренного запроса '{request_id}': {error_detail}", ephemeral=True)

        except json.JSONDecodeError:
            await interaction.followup.send(f"Ошибка: Не удалось декодировать данные для запроса '{request_id}'.", ephemeral=True)
        except Exception as e:
            print(f"MasterCmds: An unexpected error occurred in approve_generated_content: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Произошла непредвиденная ошибка при обработке запроса '{request_id}'.", ephemeral=True)

    @app_commands.command(name="reject_generated_content", description="Отклонить ожидающий модерации контент по ID запроса.")
    @app_commands.check(is_master_or_admin_check_for_app_command)
    async def reject_generated_content(self, interaction: discord.Interaction, request_id: str):
        """
        Отклонить ожидающий модерации контент по ID запроса.
        """
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = interaction.client
        if not bot_instance or not hasattr(bot_instance, 'game_manager'):
            await interaction.followup.send("Ошибка: Экземпляр бота или игровой менеджер не найден.", ephemeral=True)
            return

        db_adapter: SqliteAdapter = bot_instance.game_manager._db_adapter
        status_manager: StatusManager = bot_instance.game_manager.status_manager
        char_manager: CharacterManager = bot_instance.game_manager.character_manager

        if not all([db_adapter, status_manager, char_manager]):
            await interaction.followup.send("Ошибка: Один или несколько менеджеров не инициализированы.", ephemeral=True)
            return

        try:
            moderation_request_row = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request_row:
                await interaction.followup.send(f"Ошибка: Запрос на модерацию с ID '{request_id}' не найден.", ephemeral=True)
                return

            if moderation_request_row['status'] != 'pending':
                await interaction.followup.send(f"Ошибка: Запрос '{request_id}' уже обработан (статус: {moderation_request_row['status']}).", ephemeral=True)
                return

            user_id_str = moderation_request_row['user_id'] # Discord User ID as string

            # Delete the request from pending moderation first
            # Assuming delete_pending_moderation_request returns True on success, False/0 on failure or raises error
            deleted_count = await db_adapter.delete_pending_moderation_request(request_id)

            if deleted_count and deleted_count > 0: # Check if deletion was successful (e.g., returns number of rows deleted)
                player_char_id_log = "N/A"
                try:
                    player_char = await char_manager.get_character_by_discord_id(
                        discord_user_id=int(user_id_str),
                        guild_id=str(interaction.guild_id)
                    )
                    if player_char and player_char.id:
                        player_char_id_log = player_char.id
                        status_removal_context = {"source": "moderation_rejection"} # Example context
                        await status_manager.remove_status_effects_by_type(
                            target_id=player_char.id,
                            target_type='Character',
                            status_type_to_remove='waiting_moderation',
                            guild_id=str(interaction.guild_id),
                            context=status_removal_context
                        )
                        print(f"MasterCmds: Removed 'waiting_moderation' status from character {player_char.id} (User: {user_id_str}) due to rejection.")
                    elif not player_char:
                         print(f"MasterCmds: Could not find character for user ID {user_id_str} to remove 'waiting_moderation' status after rejection.")
                except Exception as e_status:
                    print(f"MasterCmds: Error removing 'waiting_moderation' status for user {user_id_str} after rejection: {e_status}")
                    # Log and continue, as the main action (rejection) is done.

                # Placeholder for player notification
                print(f"TODO: Notify player {user_id_str} (character {player_char_id_log}) that their content request {request_id} was rejected by Master {interaction.user.id}.")

                await interaction.followup.send(f"Контент для запроса '{request_id}' успешно отклонен и удален из очереди.", ephemeral=True)
            else:
                # This case means db_adapter.delete_pending_moderation_request indicated no rows were deleted
                # which could mean the request was already deleted by another process, or an issue with the delete method.
                await interaction.followup.send(f"Ошибка: Не удалось удалить запрос '{request_id}'. Возможно, он уже был обработан или удален.", ephemeral=True)

        except Exception as e:
            print(f"MasterCmds: An unexpected error occurred in reject_generated_content: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Произошла непредвиденная ошибка при обработке запроса на отклонение '{request_id}'.", ephemeral=True)

    @app_commands.command(name="edit_generated_content", description="Отредактировать и одобрить контент по ID запроса, предоставив JSON с правками.")
    @app_commands.check(is_master_or_admin_check_for_app_command)
    async def edit_generated_content(self, interaction: discord.Interaction, request_id: str, edited_data_json: str):
        """
        Отредактировать и одобрить ожидающий модерации контент (например, локацию) по ID запроса.
        """
        await interaction.response.defer(ephemeral=True)

        bot_instance: RPGBot = interaction.client
        if not bot_instance or not hasattr(bot_instance, 'game_manager'):
            await interaction.followup.send("Ошибка: Экземпляр бота или игровой менеджер не найден.", ephemeral=True)
            return

        db_adapter: SqliteAdapter = bot_instance.game_manager._db_adapter
        loc_manager: LocationManager = bot_instance.game_manager.location_manager
        status_manager: StatusManager = bot_instance.game_manager.status_manager
        char_manager: CharacterManager = bot_instance.game_manager.character_manager
        # ai_validator = bot_instance.game_manager.ai_validator # Needed for re-validation

        if not all([db_adapter, loc_manager, status_manager, char_manager]): # ai_validator removed for now
            await interaction.followup.send("Ошибка: Один или несколько менеджеров не инициализированы.", ephemeral=True)
            return

        try:
            moderation_request_row = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request_row:
                await interaction.followup.send(f"Ошибка: Запрос на модерацию с ID '{request_id}' не найден.", ephemeral=True)
                return

            if moderation_request_row['status'] != 'pending':
                await interaction.followup.send(f"Ошибка: Запрос '{request_id}' уже обработан (статус: {moderation_request_row['status']}).", ephemeral=True)
                return

            content_type = moderation_request_row['content_type']
            if content_type != 'location':
                await interaction.followup.send(f"Ошибка: Обработка контента типа '{content_type}' пока не поддерживается для редактирования. Поддерживается только 'location'.", ephemeral=True)
                return

            try:
                edited_location_data = json.loads(edited_data_json)
            except json.JSONDecodeError as e_json:
                await interaction.followup.send(f"Ошибка: Некорректный JSON предоставлен для правок. Детали: {e_json}", ephemeral=True)
                return

            user_id_str = moderation_request_row['user_id'] # Creator's Discord ID

            # --- TODO: Re-validation of edited_location_data ---
            # if ai_validator:
            #     print(f"MasterCmds: Attempting re-validation for edited data of request {request_id} by {interaction.user.id}")
            #     # Assuming guild_id is needed for context in validation, e.g. for existing IDs
            #     # The validator might need specific existing IDs sets (NPCs, quests, items, locations)
            #     # For simplicity, these are empty or fetched broadly if critical.
            #     existing_location_tpl_ids = set(loc_manager._location_templates.get(str(interaction.guild_id), {}).keys())
            #
            #     validation_result = await ai_validator.validate_ai_response(
            #         ai_json_string=edited_data_json, # Pass the raw JSON string
            #         expected_structure="single_location", # Assuming 'single_location' structure
            #         # Pass relevant existing IDs if validator uses them for context
            #         existing_npc_ids=set(), # Placeholder for actual NPCs in guild
            #         existing_quest_ids=set(), # Placeholder
            #         existing_item_template_ids=set(), # Placeholder
            #         existing_location_template_ids=existing_location_tpl_ids
            #     )
            #
            #     if validation_result.get('global_errors') or \
            #        validation_result.get('overall_status') == "failure" or \
            #        (validation_result.get('entities') and validation_result['entities'][0].get('errors')):
            #         # Check requires_moderation as well, as some auto-corrections might still need review
            #         # or if the Master's edit introduced something the validator flags.
            #         # For edits, we might be stricter: if validator flags *anything* (errors, needs moderation again), then fail.
            #         val_errors = validation_result.get('global_errors', [])
            #         if validation_result.get('entities') and validation_result['entities'][0].get('errors'):
            #             val_errors.extend(validation_result['entities'][0]['errors'])
            #
            #         await interaction.followup.send(f"Ошибка: Предоставленный JSON с правками не прошел валидацию. Обнаружены проблемы: {val_errors}. Пожалуйста, исправьте JSON и попробуйте снова.", ephemeral=True)
            #         return
            #     # If validation was successful, `edited_location_data` could potentially be updated from `validation_result['entities'][0]['validated_data']`
            #     # For now, we use the parsed `edited_location_data` directly.
            # else:
            #     print("MasterCmds: AI Validator not available for re-validating edited content.")
            print(f"TODO: Re-validate edited_location_data for request {request_id} using AIResponseValidator by Master {interaction.user.id}.")
            # Proceeding with Master's JSON as is for now.

            creation_context = {
                "guild_id": str(interaction.guild_id),
                "user_id": user_id_str,
                "approver_id": str(interaction.user.id), # Master/Admin's Discord ID
                "db_adapter": db_adapter, "location_manager": loc_manager,
                "status_manager": status_manager, "character_manager": char_manager,
            }

            created_instance_data = await loc_manager.create_location_instance_from_moderated_data(
                guild_id=str(interaction.guild_id),
                location_data=edited_location_data, # Use the Master's edited data
                user_id=user_id_str,
                context=creation_context
            )

            if created_instance_data and not created_instance_data.get("error"):
                new_instance_id = created_instance_data.get('id', 'N/A')

                # Remove 'waiting_moderation' status from the player
                try:
                    player_char = await char_manager.get_character_by_discord_id(
                        discord_user_id=int(user_id_str), guild_id=str(interaction.guild_id)
                    )
                    if player_char and player_char.id:
                        status_removal_context = {"source": "moderation_edit_approval"}
                        await status_manager.remove_status_effects_by_type(
                            target_id=player_char.id, target_type='Character',
                            status_type_to_remove='waiting_moderation',
                            guild_id=str(interaction.guild_id), context=status_removal_context
                        )
                        print(f"MasterCmds: Removed 'waiting_moderation' status from char {player_char.id} (User: {user_id_str}) after edit/approval.")
                except Exception as e_status:
                    print(f"MasterCmds: Error removing 'waiting_moderation' status for user {user_id_str} after edit/approval: {e_status}")

                # Update request to 'edited' and then delete (or just update if audit log needed)
                try:
                    await db_adapter.update_pending_moderation_request(
                        request_id,
                        status='edited', # Mark as 'edited'
                        moderator_id=str(interaction.user.id),
                        data_json=json.dumps(edited_location_data) # Save the edited version
                    )
                    # Now delete as it's processed. If an audit log of edits is desired,
                    # the delete operation might be skipped, and 'edited' status would signify a processed state.
                    await db_adapter.delete_pending_moderation_request(request_id)
                    print(f"MasterCmds: Moderation request {request_id} updated to 'edited' and then deleted after processing.")
                except Exception as e_db_update:
                    print(f"MasterCmds: Error updating/deleting moderation request {request_id} after edit: {e_db_update}")
                    # Non-critical for instance creation, but log it.

                # --- Trigger post-save logic (14) for edited and approved location ---
                # player_char should be available from the status removal step.
                # created_instance_data is the dict of the newly created location.
                if player_char and created_instance_data:
                    arrival_context = {
                        'guild_id': str(interaction.guild_id),
                        'player_id': player_char.id,
                        'character': player_char,
                        'location_manager': loc_manager,
                        'character_manager': char_manager,
                        'npc_manager': bot_instance.game_manager.npc_manager,
                        'item_manager': bot_instance.game_manager.item_manager,
                        'event_manager': bot_instance.game_manager.event_manager,
                        'status_manager': status_manager,
                        'rule_engine': bot_instance.game_manager.rule_engine,
                        'time_manager': bot_instance.game_manager.time_manager,
                        'send_callback_factory': bot_instance.game_manager.send_callback_factory,
                        'location_instance_data': created_instance_data,
                        'event_stage_processor': bot_instance.game_manager.event_stage_processor,
                        'event_action_processor': bot_instance.game_manager.event_action_processor,
                        'on_enter_action_executor': bot_instance.game_manager.on_enter_action_executor,
                        'stage_description_generator': bot_instance.game_manager.stage_description_generator,
                    }
                    try:
                        print(f"MasterCmds: Triggering handle_entity_arrival for edited/approved location {new_instance_id} for character {player_char.id}.")
                        await loc_manager.handle_entity_arrival(
                            location_id=new_instance_id,
                            entity_id=player_char.id,
                            entity_type='Character',
                            **arrival_context
                        )
                    except Exception as e_arrival:
                        print(f"MasterCmds: ERROR during post-edit/approval logic (handle_entity_arrival) for location {new_instance_id}: {e_arrival}")
                elif not player_char:
                     print(f"MasterCmds: WARNING - player_char not found for post-edit/approval logic (handle_entity_arrival) for location {new_instance_id}. User ID: {user_id_str}")
                # --- End of post-save logic ---

                await interaction.followup.send(f"Контент для запроса '{request_id}' (тип: {content_type}) успешно отредактирован, одобрен и создан. ID нового инстанса: {new_instance_id}", ephemeral=True)
            else:
                error_detail = created_instance_data.get("error", "Неизвестная ошибка") if isinstance(created_instance_data, dict) else "Неизвестная ошибка"
                await interaction.followup.send(f"Ошибка при создании контента из отредактированного и одобренного запроса '{request_id}': {error_detail}", ephemeral=True)

        except json.JSONDecodeError as e_json_outer: # Should be caught by inner try-except for edited_data_json
            await interaction.followup.send(f"Критическая ошибка: Не удалось обработать JSON. Детали: {e_json_outer}", ephemeral=True)
        except Exception as e:
            print(f"MasterCmds: An unexpected error occurred in edit_generated_content: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"Произошла непредвиденная ошибка при обработке редактирования запроса '{request_id}'.", ephemeral=True)


async def setup(bot: RPGBot):
    await bot.add_cog(MasterCommandsCog(bot))
    print("MasterCommandsCog has been loaded.")

# Example of how you might need to adapt is_master_or_admin if it's strictly for discord.ext.commands.Context
# This is illustrative. The actual is_master_or_admin from game_setup_cmds would need to be reviewed.
#
# from bot.game.game_manager import GameManager # Assuming GameManager is importable
# from bot.config_reader import Config # Assuming Config is importable
#
# async def is_master_or_admin_adapted(interaction: discord.Interaction, game_manager: GameManager) -> bool:
#    if not interaction.guild:
#        return False # Master commands are guild-specific
#
#    user = interaction.user
#    guild_id_str = str(interaction.guild.id)
#
#    # Check for Discord Admin permission
#    if isinstance(user, discord.Member) and user.guild_permissions.administrator:
#        return True
#
#    # Check for Bot Admin (from config)
#    if game_manager.config and user.id in game_manager.config.get_admin_ids():
#        return True
#
#    # Check for Game Master (from guild settings in DB or cache)
#    # This part depends on how Game Masters are stored and retrieved.
#    # Example: using a method in GameManager or directly accessing settings.
#    # guild_settings = await game_manager.get_guild_settings(guild_id_str)
#    # if guild_settings and user.id in guild_settings.get_master_ids():
#    # return True
#    #
#    # For this example, let's assume game_manager has a direct way to check:
#    if hasattr(game_manager, 'is_user_game_master') and await game_manager.is_user_game_master(user.id, guild_id_str):
#        return True
#
#    return False
#
# And then the check decorator would be:
# @app_commands.check(lambda interaction: is_master_or_admin_adapted(interaction, interaction.client.game_manager))
#
# The current implementation uses a MockContext to try and directly use the existing is_master_or_admin.
# This might need refinement based on the exact signature and requirements of the original is_master_or_admin.
