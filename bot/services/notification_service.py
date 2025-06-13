import logging
import json
from typing import Callable, Awaitable, Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.utils.i18n_utils import I18nUtils # For type hinting
    from bot.game.managers.character_manager import CharacterManager # For type hinting

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Handles sending notifications, including game master alerts and player feedback.
    """
    def __init__(self,
                 send_callback_factory: Callable[[int], Callable[..., Awaitable[Any]]],
                 settings: Dict[str, Any],
                 i18n_utils: Optional["I18nUtils"] = None, # Added
                 character_manager: Optional["CharacterManager"] = None # Added
                ):
        """
        Initializes the NotificationService.

        Args:
            send_callback_factory: A factory function that takes a channel ID (int) and
                                   returns an awaitable function (e.g., a Discord channel's send method)
                                   which can be called with `content` or `embed`.
            settings: The application settings dictionary.
            i18n_utils: An instance of I18nUtils for localization.
            character_manager: An instance of CharacterManager to resolve player Discord IDs.
        """
        self.send_callback_factory = send_callback_factory
        self.settings = settings
        self._i18n_utils = i18n_utils # Added
        self._character_manager = character_manager # Added
        logger.info("NotificationService initialized.")


    async def send_relationship_influence_feedback(
        self,
        guild_id: str,
        player_id: str, # This is the in-game entity ID (e.g., character_id)
        feedback_key: str,
        context_params: Dict[str, Any],
        language: str,
        channel_id: Optional[int] = None
    ) -> None:
        """
        Sends localized feedback to a player regarding relationship influences.
        Attempts to DM the player if channel_id is not provided.
        """
        if not self._i18n_utils:
            logger.error("NotificationService: I18nUtils not available. Cannot send relationship feedback.")
            return

        try:
            formatted_message = self._i18n_utils.get_localized_string(feedback_key, language, **context_params)
            if not formatted_message:
                logger.warning(f"NotificationService: Could not find or format message for key '{feedback_key}' in language '{language}'.")
                return

            if channel_id is not None:
                try:
                    send_func = self.send_callback_factory(channel_id)
                    await send_func(content=formatted_message)
                    logger.info(f"Sent relationship feedback '{feedback_key}' to channel {channel_id} for player {player_id}.")
                except Exception as e:
                    logger.error(f"Failed to send relationship feedback to channel {channel_id}: {e}", exc_info=True)
            elif self._character_manager:
                char_obj = await self._character_manager.get_character(guild_id, player_id)
                if char_obj and hasattr(char_obj, 'discord_user_id') and char_obj.discord_user_id:
                    await self.send_player_direct_message(str(char_obj.discord_user_id), formatted_message)
                    logger.info(f"Attempted to DM relationship feedback '{feedback_key}' to player {player_id} (Discord ID: {char_obj.discord_user_id}).")
                else:
                    logger.warning(f"NotificationService: Cannot DM player {player_id} for feedback '{feedback_key}': Character not found or no discord_user_id.")
            else:
                logger.warning(f"NotificationService: No channel_id provided and CharacterManager not available for DM. Cannot send feedback '{feedback_key}' to player {player_id}.")

        except Exception as e:
            logger.error(f"NotificationService: Error sending relationship influence feedback (key: {feedback_key}): {e}", exc_info=True)


    async def send_moderation_request_alert(self, guild_id: str, request_id: str, content_type: str, user_id: str, content_summary: Dict[str, Any], moderation_interface_link: str) -> None:
        """
        Sends an alert to GMs about new AI-generated content pending moderation.
        """
        logger.info(f"Attempting to send moderation request alert for {content_type} {request_id} in guild {guild_id}")

        gm_notification_channel_id_str: Optional[str] = None
        # Prioritize guild-specific channel, then global
        guild_specific_settings = self.settings.get('guild_specific_settings', {}).get(str(guild_id), {})
        if guild_specific_settings:
            gm_notification_channel_id_str = guild_specific_settings.get('gm_notification_channel_id')

        if not gm_notification_channel_id_str:
            gm_notification_channel_id_str = self.settings.get('gm_notification_channel_id')

        if gm_notification_channel_id_str:
            try:
                gm_notification_channel_id = int(gm_notification_channel_id_str)
                send_func = self.send_callback_factory(gm_notification_channel_id)

                summary_lines = [f"**{key.replace('_', ' ').title()}:** {value}" for key, value in content_summary.items()]
                summary_text = "\n".join(summary_lines)

                embed_msg_content = (
                    f"**New AI Content for Moderation**\n\n"
                    f"**Type:** `{content_type.capitalize()}`\n"
                    f"**Request ID:** `{request_id}`\n"
                    f"**Guild ID:** `{guild_id}`\n"
                    f"**Initiated by User:** `{user_id}`\n\n"
                    f"**Content Summary:**\n{summary_text}\n\n"
                    f"**Action:** {moderation_interface_link}"
                )

                if len(embed_msg_content) > 1900: # Basic truncation
                    embed_msg_content = embed_msg_content[:1900] + "...\n(Message truncated)"

                await send_func(content=embed_msg_content)
                logger.info(f"Successfully sent moderation request alert for {content_type} {request_id} to channel {gm_notification_channel_id}")
            except ValueError:
                logger.error(f"Invalid gm_notification_channel_id format: '{gm_notification_channel_id_str}' for guild {guild_id}. Must be an integer.")
            except Exception as e:
                logger.error(f"Failed to send moderation request alert for {content_type} {request_id} to channel {gm_notification_channel_id_str}: {e}", exc_info=True)
        else:
            logger.warning(f"No GM notification channel configured for guild {guild_id} (or globally). Cannot send moderation alert for {content_type} {request_id}.")

    async def send_player_direct_message(self, user_discord_id: str, message_content: str) -> None:
        """
        Sends a direct message to a player.
        NOTE: This is a placeholder. Actual implementation requires resolving user_discord_id
        to a DM channel, likely via a Discord user object cache or API call, which is
        outside the current scope of NotificationService's send_callback_factory.
        For now, it will log the intent.
        """
        # In a full implementation:
        # 1. Get the discord.User object for user_discord_id (e.g., from bot.get_user() or a cache).
        # 2. Get/create a DM channel with that user (user.create_dm()).
        # 3. Use self.send_callback_factory(dm_channel.id)(content=message_content).
        # This simplified version will just log.
        logger.info(f"Intended to send DM to user {user_discord_id}: '{message_content}'. "
                    f"Full DM implementation in NotificationService.send_player_direct_message is pending.")
        # Simulate a successful send for now for flows that check the return,
        # or change its signature if it should indicate success/failure.
        # For now, no explicit return, implies fire-and-forget style.

    async def send_master_alert(self, conflict_id: str, guild_id: str, message: str, conflict_details: Dict[str, Any]) -> None:
        """
        Sends an alert message to the configured Game Master notification channel for a specific guild.

        Args:
            conflict_id: The ID of the conflict.
            guild_id: The ID of the guild where the conflict occurred.
            message: A summary message for the alert.
            conflict_details: A dictionary containing details of the conflict.
        """
        logger.info(f"Attempting to send GM alert for conflict {conflict_id} in guild {guild_id}")

        gm_notification_channel_id_str: Optional[str] = None
        guild_settings = self.settings.get('guild_specific_settings', {}).get(guild_id)
        if guild_settings:
            gm_notification_channel_id_str = guild_settings.get('gm_notification_channel_id')

        if not gm_notification_channel_id_str:
            gm_notification_channel_id_str = self.settings.get('gm_notification_channel_id') # Check global setting

        if gm_notification_channel_id_str:
            try:
                gm_notification_channel_id = int(gm_notification_channel_id_str)
                send_func = self.send_callback_factory(gm_notification_channel_id)

                # For simplicity, sending as a formatted string.
                # In a real Discord bot, you'd likely use an Embed object for better formatting.
                # Prepare a more detailed message, potentially using an embed for conflict_details
                embed_msg_content = (
                    f"**Conflict Alert**\n\n"
                    f"**Conflict ID:** `{conflict_id}`\n"
                    f"**Guild ID:** `{guild_id}`\n"
                    f"**Message:** {message}\n\n"
                    f"**Conflict Details:**\n"
                    f"```json\n{json.dumps(conflict_details, indent=2, ensure_ascii=False)}\n```"
                )

                # Discord messages have a character limit (e.g., 2000 for content, 6000 total for embeds)
                # This is a simplified approach. For production, you might need to truncate or use embeds properly.
                if len(embed_msg_content) > 1900: # Leave some room
                    details_dump = json.dumps(conflict_details, indent=2, ensure_ascii=False)
                    if len(details_dump) > 1000: # If details are too long, truncate them
                        details_dump = details_dump[:1000] + "..."
                    embed_msg_content = (
                        f"**Conflict Alert**\n\n"
                        f"**Conflict ID:** `{conflict_id}`\n"
                        f"**Guild ID:** `{guild_id}`\n"
                        f"**Message:** {message}\n\n"
                        f"**Conflict Details (truncated):**\n"
                        f"```json\n{details_dump}\n```"
                    )

                await send_func(content=embed_msg_content)
                logger.info(f"Successfully sent GM alert for conflict {conflict_id} to channel {gm_notification_channel_id}")
            except ValueError:
                logger.error(f"Invalid gm_notification_channel_id format: '{gm_notification_channel_id_str}' for guild {guild_id}. Must be an integer.")
            except Exception as e:
                logger.error(f"Failed to send GM alert for conflict {conflict_id} to channel {gm_notification_channel_id_str}: {e}", exc_info=True)
        else:
            logger.warning(f"No GM notification channel configured for guild {guild_id} (or globally). Cannot send alert for conflict {conflict_id}.")
