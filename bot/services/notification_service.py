import logging
import json
from typing import Callable, Awaitable, Any, Dict, Optional

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Handles sending notifications, particularly for game master alerts.
    """
    def __init__(self, send_callback_factory: Callable[[int], Callable[..., Awaitable[Any]]], settings: Dict[str, Any]):
        """
        Initializes the NotificationService.

        Args:
            send_callback_factory: A factory function that takes a channel ID (int) and
                                   returns an awaitable function (e.g., a Discord channel's send method)
                                   which can be called with `content` or `embed`.
            settings: The application settings dictionary.
        """
        self.send_callback_factory = send_callback_factory
        self.settings = settings

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
