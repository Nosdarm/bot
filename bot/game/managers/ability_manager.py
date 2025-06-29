# bot/game/managers/ability_manager.py
from __future__ import annotations
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from bot.services.db_service import DBService

if TYPE_CHECKING:
    from bot.database.models import Ability
    from bot.game.managers.status_manager import StatusManager

class AbilityManager:
    def __init__(self, db_service: DBService, status_manager: StatusManager):
        self.db_service = db_service
        self.status_manager = status_manager

    async def create_ability(self, guild_id: int, static_id: str, name_i18n: Dict[str, str], description_i18n: Dict[str, str], properties_json: Dict[str, Any]) -> Ability:
        async with self.db_service.get_session() as session:
            from bot.database.models import Ability
            
            new_ability = Ability(
                guild_id=guild_id,
                static_id=static_id,
                name_i18n=name_i18n,
                description_i18n=description_i18n,
                properties_json=properties_json
            )
            session.add(new_ability)
            await session.commit()
            return new_ability

    async def activate_ability(self, guild_id: int, entity_id: int, entity_type: str, ability_id: int, target_ids: Optional[List[int]] = None) -> None:
        async with self.db_service.get_session() as session:
            from bot.database.models import Ability
            from sqlalchemy.future import select

            stmt = select(Ability).where(Ability.id == ability_id, Ability.guild_id == guild_id)
            result = await session.execute(stmt)
            ability = result.scalars().first()

            if ability:
                if ability.properties_json:
                    for effect in ability.properties_json.get("effects", []):
                        if effect.get("type") == "apply_status":
                            status_id = effect.get("status_id")
                            duration = effect.get("duration")
                            if status_id and duration and target_ids:
                                for target_id in target_ids:
                                    await self.status_manager.apply_status(
                                        guild_id=guild_id,
                                        entity_id=target_id,
                                        entity_type="character", # Assuming character for now
                                        status_id=status_id,
                                        duration=duration,
                                        source_ability_id=ability.id
                                    )