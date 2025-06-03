# bot/game/command_handlers/party_handler.py

from __future__ import annotations
# Import necessary types
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union
from collections import Counter # Added for example in Party info

# Import discord for embeds if needed
import discord

# Import managers/processors used by party commands (use string literals if they cause cycles)
if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    # Add other managers/services needed for party commands (e.g. PartyViewService)
    # from bot.game.party_processors.party_view_service import PartyViewService
    from bot.game.managers.npc_manager import NpcManager # Needed for fallback in info
    # Add any other managers/processors used directly by this handler in __init__ or methods
    # from bot.game.managers.some_other_manager import SomeOtherManager


# Define callback types if needed (can be same as in CommandRouter)
SendToChannelCallback = Callable[..., Awaitable[Any]]


class PartyCommandHandler:
    """
    Обработчик команд для управления группами (пати).
    Реализует логику субкоманд /party.
    """
    def __init__(self,
                 # İSPRAVLENIE: Move all non-default arguments to the start
                 character_manager: "CharacterManager",
                 party_manager: "PartyManager",
                 party_action_processor: "PartyActionProcessor",
                 settings: Dict[str, Any], # <-- Moved settings here

                 # İSPRAVLENIE: All default arguments follow non-default ones
                 # party_view_service: Optional["PartyViewService"] = None, # Keep Optional and default
                 npc_manager: Optional["NpcManager"] = None, # Keep Optional and default
                 # Add other dependencies here, keeping Optional and default = None
                 # some_other_manager: Optional["SomeOtherManager"] = None,

                ):
        print("Initializing PartyCommandHandler...")
        # Store injected dependencies
        self._char_manager = character_manager
        self._party_manager = party_manager
        self._party_action_processor = party_action_processor
        # self._party_view_service = party_view_service # Store if used
        self._npc_manager = npc_manager # Store if used
        self._settings = settings

        # Get command prefix from settings (needed for usage messages)
        self._command_prefix = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
             self._command_prefix = '/'


        print("PartyCommandHandler initialized.")

    # This single method handles the "/party" command and delegates to subcommands
    async def handle(self, message: discord.Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Обрабатывает команду /party и ее субкоманды.
        Перемещена логика из CommandRouter.handle_party.
        """
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id = context.get('author_id')


        if guild_id is None:
            await send_callback("❌ Команды партии доступны только на сервере.")
            return

        if not args:
             help_message_content = """
Управляет группами персонажей (пати).
Использование:
`{prefix}party create` - Создать новую партию (вы становитесь лидером).
`{prefix}party join <ID партии>` - Присоединиться к существующей партии.
`{prefix}party leave` - Покинуть текущую партию.
`{prefix}party info [<ID партии>]` - Показать информацию о вашей партии или партии по ID.
             """.format(prefix=self._command_prefix)

             await send_callback(help_message_content)
             print(f"PartyCommandHandler: Processed party command (help) for guild {guild_id}.")
             return


        subcommand = args[0].lower()
        subcommand_args = args[1:]

        player_char = None
        player_char_id: Optional[str] = None

        author_id_int: Optional[int] = None
        if author_id is not None:
            try: author_id_int = int(author_id)
            except (ValueError, TypeError): pass

        if author_id_int is not None and self._char_manager:
             player_char = self._char_manager.get_character_by_discord_id(guild_id, author_id_int)
             player_char_id = getattr(player_char, 'id', None) if player_char else None


        if subcommand == "create":
             await self._handle_create_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)

        elif subcommand == "join":
             await self._handle_join_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)

        elif subcommand == "leave":
             await self._handle_leave_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)

        elif subcommand == "info":
             await self._handle_info_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)


        else:
            await send_callback(f"Неизвестное действие для партии: `{subcommand}`. Доступные действия: `create`, `join`, `leave`, `info` (и другие, если реализованы).\nИспользование: `{self._command_prefix}party <действие> [аргументы]`".format(prefix=self._command_prefix))
            print(f"PartyCommandHandler: Unknown party subcommand: '{subcommand}' in guild {guild_id}.")


    async def _handle_create_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party create' subcommand logic."""
        print(f"PartyCommandHandler: Handling create subcommand for user {author_id} in guild {guild_id}...")

        if player_char is None:
             await send_callback("❌ Для создания партии необходим персонаж.")
             print(f"PartyCommandHandler: Create failed for user {author_id} in guild {guild_id}: No character.")
             return

        if player_char_id is None:
             await send_callback("❌ Произошла ошибка: Не удалось получить ID вашего персонажа.")
             print(f"PartyCommandHandler Error: Player character object has no ID attribute for user {author_id} in guild {guild_id}.")
             return


        player_current_party = await self._party_manager.get_party_by_member_id(player_char_id, guild_id)
        if player_current_party:
             await send_callback(f"❌ Вы уже состоите в партии (ID `{getattr(player_current_party, 'id', 'N/A')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).".format(prefix=self._command_prefix))
             print(f"PartyCommandHandler: Create failed for char {player_char_id} in guild {guild_id}: Already in party {getattr(player_current_party, 'id', 'N/A')}.")
             return

        try:
             new_party_id = await self._party_manager.create_party(
                 leader_id=player_char_id,
                 member_ids=[player_char_id],
                 guild_id=guild_id,
                 **context
             )

             if new_party_id:
                  if self._char_manager and hasattr(self._char_manager, 'set_party_id'):
                      await self._char_manager.set_party_id(
                          guild_id=guild_id,
                          character_id=player_char_id,
                          party_id=new_party_id,
                          **context
                      )

                  await send_callback(f"🎉 Вы успешно создали новую партию! ID партии: `{new_party_id}`")
                  print(f"PartyCommandHandler: Party {new_party_id} created by user {author_id} (char {player_char_id}) in guild {guild_id}.")

             else:
                  await send_callback("❌ Не удалось создать партию. Возможно, произошла внутренняя ошибка.")
                  print(f"PartyCommandHandler: party_manager.create_party returned None for user {author_id} (char {player_char_id}) in guild {guild_id}.")

        except Exception as e:
             print(f"PartyCommandHandler Error creating party for user {author_id} (char {player_char_id}) in guild {guild_id}: {e}")
             import traceback
             traceback.print_exc()
             await send_callback(f"❌ Произошла ошибка при создании партии: {e}")


    async def _handle_join_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party join <ID>' subcommand logic."""
        print(f"PartyCommandHandler: Handling join subcommand for user {author_id} in guild {guild_id}...")

        if not subcommand_args:
             await send_callback(f"Использование: `{self._command_prefix}party join <ID партии>`".format(prefix=self._command_prefix))
             return
        if player_char is None:
            await send_callback("❌ Для присоединения к партии необходим персонаж.")
            print(f"PartyCommandHandler: Join failed for user {author_id} in guild {guild_id}: No character.")
            return
        if player_char_id is None:
             await send_callback("❌ Произошла ошибка: Не удалось получить ID вашего персонажа.")
             print(f"PartyCommandHandler Error: Player character object has no ID attribute for user {author_id} in guild {guild_id}.")
             return

        target_party_id_arg = subcommand_args[0]

        target_party = self._party_manager.get_party(guild_id, target_party_id_arg)
        if not target_party:
             await send_callback(f"❌ Партия с ID `{target_party_id_arg}` не найдена в этой гильдии.")
             print(f"PartyCommandHandler: Join failed for char {player_char_id} in guild {guild_id}: Target party {target_party_id_arg} not found.")
             return

        player_current_party = await self._party_manager.get_party_by_member_id(player_char_id, guild_id)
        if player_current_party:
             if getattr(player_current_party, 'id', None) == getattr(target_party, 'id', None):
                  await send_callback(f"❌ Вы уже состоите в этой партии (ID `{target_party_id_arg}`).")
                  print(f"PartyCommandHandler: Join failed for char {player_char_id} in guild {guild_id}: Already in target party {target_party_id_arg}.")
             else:
                  await send_callback(f"❌ Вы уже состоите в другой партии (ID `{getattr(player_current_party, 'id', 'N/A')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).".format(prefix=self._command_prefix))
                  print(f"PartyCommandHandler: Join failed for char {player_char_id} in guild {guild_id}: Already in different party {getattr(player_current_party, 'id', 'N/A')}.")
             return

        try:
             join_successful = await self._party_action_processor.process_join_party(
                 character_id=player_char_id,
                 party_id=getattr(target_party, 'id'),
                 context=context
             )
             if join_successful:
                  print(f"PartyCommandHandler: Join party action processed successfully in processor for char {player_char_id} to party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")
             else:
                  print(f"PartyCommandHandler: Join party action failed in processor for char {player_char_id} to party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")

        except Exception as e:
             print(f"PartyCommandHandler Error joining party for char {player_char_id} to party {target_party_id_arg} in guild {guild_id}: {e}")
             import traceback
             traceback.print_exc()
             await send_callback(f"❌ Произошла ошибка при присоединении к партии: {e}")


    async def _handle_leave_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party leave' subcommand logic."""
        print(f"PartyCommandHandler: Handling leave subcommand for user {author_id} in guild {guild_id}...")

        if player_char_id is None:
            await send_callback("❌ У вас нет персонажа, чтобы покинуть партию.")
            print(f"PartyCommandHandler: Leave failed for user {author_id} in guild {guild_id}: No character.")
            return

        player_current_party = await self._party_manager.get_party_by_member_id(player_char_id, guild_id)
        if not player_current_party:
             await send_callback("❌ Вы не состоите в партии.")
             print(f"PartyCommandHandler: Leave failed for char {player_char_id} in guild {guild_id}: Not in a party.")
             return

        try:
             party_id_to_leave = getattr(player_current_party, 'id')
             if party_id_to_leave is None:
                  print(f"PartyCommandHandler Error: Player's party object has no ID attribute for char {player_char_id} in guild {guild_id}. Party object: {player_current_party}")
                  await send_callback("❌ Произошла ошибка: Не удалось получить ID вашей партии.")
                  return

             leave_successful = await self._party_action_processor.process_leave_party(
                 character_id=player_char_id,
                 party_id=party_id_to_leave,
                 context=context
             )
             if leave_successful:
                  print(f"PartyCommandHandler: Leave party action processed successfully in processor for char {player_char_id} from party {party_id_to_leave} in guild {guild_id}.")
             else:
                  print(f"PartyCommandHandler: Leave party action failed in processor for char {player_char_id} from party {party_id_to_leave} in guild {guild_id}.")

        except Exception as e:
              print(f"PartyCommandHandler Error leaving party for char {player_char_id} from party {getattr(player_current_party, 'id', 'N/A')} in guild {guild_id}: {e}")
              import traceback
              traceback.print_exc()
              await send_callback(f"❌ Произошла ошибка при попытке покинуть партию: {e}")


    async def _handle_info_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party info [<ID>]' subcommand logic."""
        print(f"PartyCommandHandler: Handling info subcommand for user {author_id} in guild {guild_id}...")

        target_party: Optional[Any] = None
        party_id_arg: Optional[str] = None

        if subcommand_args:
             party_id_arg = subcommand_args[0]
             target_party = self._party_manager.get_party(guild_id, party_id_arg)

             if not target_party:
                  await send_callback(f"❌ Партия с ID `{party_id_arg}` не найдена в этой гильдии.")
                  print(f"PartyCommandHandler: Party info failed for user {author_id} in guild {guild_id}: Target party {party_id_arg} not found.")
                  return
        else:
             if player_char_id is None:
                  await send_callback(f"❌ У вас нет персонажа. Укажите ID партии для просмотра (`{self._command_prefix}party info <ID партии>`).".format(prefix=self._command_prefix))
                  print(f"PartyCommandHandler: Party info failed for user {author_id} in guild {guild_id}: No character and no party ID provided.")
                  return

             target_party = await self._party_manager.get_party_by_member_id(player_char_id, guild_id)
             if not target_party:
                  await send_callback(f"❌ Вы не состоите в партии. Укажите ID партии для просмотра (`{self._command_prefix}party info <ID партии>`).".format(prefix=self._command_prefix))
                  print(f"PartyCommandHandler: Party info failed for char {player_char_id} in guild {guild_id}: Not in a party and no party ID provided.")
                  return
             party_id_arg = getattr(target_party, 'id', 'N/A')


        if target_party is None:
            await send_callback("❌ Произошла ошибка при определении партии для просмотра.")
            print(f"PartyCommandHandler Error: target_party is None after lookup logic for user {author_id} in guild {guild_id}.")
            return

        # TODO: Call a PartyViewService method to generate party info embed
        party_view_service = context.get('party_view_service') # Type: Optional["PartyViewService"]

        if party_view_service and hasattr(party_view_service, 'get_party_info_embed'):
             try:
                 party_embed = await party_view_service.get_party_info_embed(target_party, context=context)
                 if party_embed:
                      await send_callback(embed=party_embed)
                      print(f"PartyCommandHandler: Sent party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")
                 else:
                      print(f"PartyCommandHandler: Failed to generate party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}. PartyViewService returned None or invalid.")
                      await send_callback(f"❌ Не удалось сгенерировать информацию для партии **{getattr(target_party, 'name', 'N/A')}**. Проверьте логи бота.")

             except Exception as e:
                  print(f"PartyCommandHandler Error generating party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}: {e}")
                  import traceback
                  traceback.print_exc()
                  await send_callback(f"❌ Произошла ошибка при получении информации о партии: {e}")

        else: # Fallback if PartyViewService is not available
             party_id = getattr(target_party, 'id', 'N/A')
             leader_id = getattr(target_party, 'leader_id', 'N/A')
             member_ids = getattr(target_party, 'member_ids', [])
             party_name = getattr(target_party, 'name', 'Безымянная партия')

             member_names = []
             if isinstance(member_ids, list) and member_ids:
                  char_mgr = self._char_manager # Use injected manager
                  npc_mgr = self._npc_manager # Use injected manager
                  for member_id in member_ids:
                       name = str(member_id)
                       # Pass guild_id to get_character/get_npc
                       if char_mgr and isinstance(member_id, str):
                            char = char_mgr.get_character(guild_id, member_id)
                            if char: name = getattr(char, 'name', name)
                       if name == str(member_id) and npc_mgr and isinstance(member_id, str):
                            npc = npc_mgr.get_npc(guild_id, member_id)
                            if npc: name = getattr(npc, 'name', name)
                       truncated_id = str(member_id)[:6] if isinstance(member_id, (str, int)) else 'N/A'
                       member_names.append(f"`{truncated_id}` ({name})")


             info_message = f"Информация о партии **{party_name}** (ID: `{party_id}`).\n"
             truncated_leader_id = str(leader_id)[:6] if isinstance(leader_id, (str, int)) and leader_id is not None else 'Нет'
             info_message += f"Лидер: `{truncated_leader_id}`\n"
             info_message += f"Участники ({len(member_ids)}): " + (", ".join(member_names) if member_names else "Нет.")

             await send_callback(info_message)
             print(f"PartyCommandHandler: Sent fallback party info for party {party_id} in guild {guild_id}.")
