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
`{prefix}party disband` - Распустить партию (только лидер).
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
             # Ensure player_char is not None before trying to get 'id'
             if player_char:
                 player_char_id = getattr(player_char, 'id', None)


        if subcommand == "create":
             await self._handle_create_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)
        elif subcommand == "join":
             await self._handle_join_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)
        elif subcommand == "leave":
             await self._handle_leave_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)
        elif subcommand == "disband":
            await self._handle_disband_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)
        elif subcommand == "info":
             await self._handle_info_subcommand(send_callback, guild_id, author_id, player_char, player_char_id, subcommand_args, context)
        else:
            await send_callback(f"Неизвестное действие для партии: `{subcommand}`. Доступные действия: `create`, `join`, `leave`, `disband`, `info`.\nИспользование: `{self._command_prefix}party <действие> [аргументы]`".format(prefix=self._command_prefix))
            print(f"PartyCommandHandler: Unknown party subcommand: '{subcommand}' in guild {guild_id}.")


    async def _handle_create_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party create' subcommand logic."""
        print(f"PartyCommandHandler: Handling create subcommand for user {author_id} in guild {guild_id}...")

        if player_char is None or player_char_id is None:
            await send_callback("❌ Для создания партии необходим персонаж.")
            print(f"PartyCommandHandler: Create failed for user {author_id} in guild {guild_id}: No character or character ID missing.")
            return

        # Check if player is already in a party
        if getattr(player_char, 'party_id', None):
            await send_callback(f"❌ Вы уже состоите в партии (ID `{getattr(player_char, 'party_id')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).")
            print(f"PartyCommandHandler: Create failed for char {player_char_id} in guild {guild_id}: Already in party {getattr(player_char, 'party_id')}.")
            return

        try:
            player_location_id = getattr(player_char, 'location_id', None)
            if not player_location_id:
                await send_callback("❌ Не удалось определить вашу текущую локацию. Создание партии невозможно.")
                print(f"PartyCommandHandler: Create failed for char {player_char_id} in guild {guild_id}: Character has no location_id.")
                return

            # Create party with leader as the only member and set party location to leader's location
            new_party = await self._party_manager.create_party(
                leader_id=player_char_id,
                member_ids=[player_char_id], # Initial members list
                guild_id=guild_id,
                # Pass current_location_id for the party based on leader's location
                current_location_id=player_location_id,
                **context # Pass full context which might include other managers
            )

            if new_party and hasattr(new_party, 'id'):
                new_party_id = getattr(new_party, 'id')
                # Update player's current_party_id
                update_success = await self._char_manager.set_party_id(
                    guild_id=guild_id,
                    character_id=player_char_id,
                    party_id=new_party_id,
                    **context
                )
                if update_success:
                    await send_callback(f"🎉 Вы успешно создали новую партию! ID партии: `{new_party_id}`")
                    print(f"PartyCommandHandler: Party {new_party_id} created by user {author_id} (char {player_char_id}) in guild {guild_id}. Player party_id updated.")
                else:
                    # This case is tricky: party created but player update failed.
                    # Potentially try to roll back party creation or log inconsistency.
                    await send_callback("❌ Партия создана, но не удалось обновить ваш статус. Обратитесь к администратору.")
                    print(f"PartyCommandHandler: Party {new_party_id} created, but failed to update char {player_char_id}'s party_id in guild {guild_id}.")
            else:
                await send_callback("❌ Не удалось создать партию. Возможно, произошла внутренняя ошибка.")
                print(f"PartyCommandHandler: party_manager.create_party returned None or invalid object for user {author_id} (char {player_char_id}) in guild {guild_id}.")

        except Exception as e:
            print(f"PartyCommandHandler Error creating party for user {author_id} (char {player_char_id}) in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при создании партии: {str(e)}")


    async def _handle_join_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party join <ID>' subcommand logic."""
        print(f"PartyCommandHandler: Handling join subcommand for user {author_id} in guild {guild_id}...")

        if not subcommand_args:
            await send_callback(f"Использование: `{self._command_prefix}party join <ID партии>`")
            return
        
        if player_char is None or player_char_id is None:
            await send_callback("❌ Для присоединения к партии необходим персонаж.")
            print(f"PartyCommandHandler: Join failed for user {author_id} in guild {guild_id}: No character or character ID.")
            return

        if getattr(player_char, 'party_id', None):
            await send_callback(f"❌ Вы уже состоите в партии (ID `{getattr(player_char, 'party_id')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).")
            return

        target_party_id_arg = subcommand_args[0]
        target_party = self._party_manager.get_party(guild_id, target_party_id_arg)

        if not target_party:
            await send_callback(f"❌ Партия с ID `{target_party_id_arg}` не найдена.")
            return

        player_location_id = getattr(player_char, 'location_id', None)
        party_location_id = getattr(target_party, 'current_location_id', None)

        if not player_location_id:
            await send_callback("❌ Не удалось определить вашу текущую локацию.")
            return
        
        if player_location_id != party_location_id:
            # Optionally fetch location names for a friendlier message
            player_loc_name = player_location_id
            party_loc_name = party_location_id
            # Placeholder for fetching location names if LocationManager is available
            # loc_manager = context.get('location_manager')
            # if loc_manager:
            #    player_loc_obj = loc_manager.get_location(guild_id, player_location_id)
            #    if player_loc_obj: player_loc_name = player_loc_obj.name
            #    party_loc_obj = loc_manager.get_location(guild_id, party_location_id)
            #    if party_loc_obj: party_loc_name = party_loc_obj.name
            await send_callback(f"❌ Вы должны находиться в той же локации, что и партия, чтобы присоединиться. Вы в `{player_loc_name}`, партия в `{party_loc_name}`.")
            return

        try:
            # Assuming add_member_to_party will be created in PartyManager
            # add_member_to_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
            join_successful = await self._party_manager.add_member_to_party(
                party_id=target_party.id, # type: ignore
                character_id=player_char_id,
                guild_id=guild_id,
                context=context
            )

            if join_successful:
                update_char_party_success = await self._char_manager.set_party_id(guild_id, player_char_id, target_party.id, **context) # type: ignore
                if update_char_party_success:
                    await send_callback(f"🎉 Вы успешно присоединились к партии `{getattr(target_party, 'name', target_party.id)}`!") # type: ignore
                    print(f"PartyCommandHandler: Char {player_char_id} successfully joined party {target_party.id} in guild {guild_id}.") # type: ignore
                else:
                    await send_callback("❌ Удалось присоединиться к партии, но не удалось обновить ваш статус. Обратитесь к администратору.")
                    # Potentially roll back add_member_to_party or log inconsistency
                    print(f"PartyCommandHandler: Char {player_char_id} joined party {target_party.id}, but failed to update char's party_id in guild {guild_id}.") # type: ignore
            else:
                # add_member_to_party in PartyManager should ideally send specific error or return reason
                await send_callback(f"❌ Не удалось присоединиться к партии `{getattr(target_party, 'name', target_party.id)}`. Возможно, она заполнена или закрыта.") # type: ignore
                print(f"PartyCommandHandler: add_member_to_party failed for char {player_char_id} to party {target_party.id} in guild {guild_id}.") # type: ignore

        except Exception as e:
            print(f"PartyCommandHandler Error joining party for char {player_char_id} to party {target_party_id_arg} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при присоединении к партии: {str(e)}")


    async def _handle_leave_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party leave' subcommand logic."""
        print(f"PartyCommandHandler: Handling leave subcommand for user {author_id} in guild {guild_id}...")

        if player_char is None or player_char_id is None:
            await send_callback("❌ У вас нет персонажа, чтобы покинуть партию.")
            return

        current_party_id = getattr(player_char, 'party_id', None)
        if not current_party_id:
            await send_callback("❌ Вы не состоите в партии.")
            return

        party_to_leave = self._party_manager.get_party(guild_id, current_party_id)
        if not party_to_leave:
            # This implies inconsistency, character has a party_id but party doesn't exist
            await send_callback("❌ Вы состоите в партии, которая не найдена. Сбрасываю ваш статус партии...")
            await self._char_manager.set_party_id(guild_id, player_char_id, None, **context)
            print(f"PartyCommandHandler: Char {player_char_id} had party_id {current_party_id} but party not found in guild {guild_id}. Cleared char's party_id.")
            return

        player_location_id = getattr(player_char, 'location_id', None)
        party_location_id = getattr(party_to_leave, 'current_location_id', None)

        if not player_location_id:
            await send_callback("❌ Не удалось определить вашу текущую локацию. Выход из партии невозможен сейчас.")
            return

        if player_location_id != party_location_id:
            await send_callback(f"❌ Вы должны находиться в той же локации, что и партия, чтобы покинуть ее. Вы в `{player_location_id}`, партия в `{party_location_id}`.")
            return
            
        try:
            # remove_member_from_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
            # This method in PartyManager will handle leader migration or party disbandment.
            leave_successful = await self._party_manager.remove_member_from_party(
                party_id=current_party_id,
                character_id=player_char_id,
                guild_id=guild_id,
                context=context
            )

            if leave_successful:
                # PartyManager.remove_member_from_party might have already set char's party_id to None
                # if it handled leader migration and the char was the leader of a now-empty party that got disbanded.
                # However, to be safe, or if the char was not the leader, we set it here.
                await self._char_manager.set_party_id(guild_id, player_char_id, None, **context)
                await send_callback(f"✅ Вы покинули партию `{getattr(party_to_leave, 'name', current_party_id)}`.")
                print(f"PartyCommandHandler: Char {player_char_id} successfully left party {current_party_id} in guild {guild_id}.")
            else:
                # This might occur if remove_member_from_party had an internal failure
                # but didn't raise an exception.
                await send_callback(f"❌ Не удалось покинуть партию `{getattr(party_to_leave, 'name', current_party_id)}` из-за внутренней ошибки.")
                print(f"PartyCommandHandler: remove_member_from_party failed for char {player_char_id} from party {current_party_id} in guild {guild_id}.")

        except Exception as e:
            print(f"PartyCommandHandler Error leaving party for char {player_char_id} from party {current_party_id} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при попытке покинуть партию: {e}")

    async def _handle_disband_subcommand(self, send_callback: SendToChannelCallback, guild_id: str, author_id: str, player_char: Optional[Any], player_char_id: Optional[str], subcommand_args: List[str], context: Dict[str, Any]) -> None:
        """Handles the '/party disband' subcommand logic."""
        print(f"PartyCommandHandler: Handling disband subcommand for user {author_id} in guild {guild_id}...")

        if player_char is None or player_char_id is None:
            await send_callback("❌ У вас нет персонажа, чтобы распустить партию.")
            return

        current_party_id = getattr(player_char, 'party_id', None)
        if not current_party_id:
            await send_callback("❌ Вы не состоите в партии, чтобы ее распускать.")
            return

        party_to_disband = self._party_manager.get_party(guild_id, current_party_id)
        if not party_to_disband:
            await send_callback("❌ Ваша партия не найдена. Возможно, она уже распущена. Сбрасываю ваш статус партии...")
            await self._char_manager.set_party_id(guild_id, player_char_id, None, **context)
            print(f"PartyCommandHandler: Char {player_char_id} tried to disband party {current_party_id} but party not found in guild {guild_id}. Cleared char's party_id.")
            return

        if getattr(party_to_disband, 'leader_id', None) != player_char_id:
            await send_callback("❌ Только лидер партии может ее распустить.")
            return
        
        try:
            # remove_party(self, party_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
            # This method in PartyManager must handle setting party_id = None for all members.
            disband_successful = await self._party_manager.remove_party(
                party_id=current_party_id,
                guild_id=guild_id,
                context=context
            )

            if disband_successful:
                party_name = getattr(party_to_disband, 'name', current_party_id)
                await send_callback(f"✅ Партия `{party_name}` успешно распущена.")
                print(f"PartyCommandHandler: Party {current_party_id} in guild {guild_id} disbanded by leader {player_char_id}.")
            else:
                # This might occur if remove_party had an internal failure
                await send_callback(f"❌ Не удалось распустить партию `{getattr(party_to_disband, 'name', current_party_id)}` из-за внутренней ошибки.")
                print(f"PartyCommandHandler: remove_party failed for party {current_party_id} in guild {guild_id}, initiated by {player_char_id}.")

        except Exception as e:
            print(f"PartyCommandHandler Error disbanding party {current_party_id} in guild {guild_id} by {player_char_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при роспуске партии: {str(e)}")


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
