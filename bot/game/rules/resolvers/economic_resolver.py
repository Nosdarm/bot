# bot/game/rules/resolvers/economic_resolver.py
from typing import TYPE_CHECKING, Any, Dict, Optional, Callable, Awaitable

if TYPE_CHECKING:
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.npc_manager import NpcManager # If needed for trader's faction

async def calculate_market_price(
    rules_data: Dict[str, Any],
    guild_id: str,
    location_id: str,
    item_template_id: str,
    quantity: float,
    is_selling_to_market: bool,
    actor_entity_id: str,
    actor_entity_type: str,
    economy_manager: Optional["EconomyManager"], # Passed from RuleEngine's kwargs or self
    character_manager: Optional["CharacterManager"], # Passed from RuleEngine
    location_manager: Optional["LocationManager"], # Passed from RuleEngine
    relationship_manager: Optional["RelationshipManager"], # Passed from RuleEngine
    npc_manager: Optional["NpcManager"], # Passed from RuleEngine
    **kwargs: Any # To catch any other context items if necessary
) -> Optional[float]:
    """
    Calculates the market price for an item considering various economic factors.
    """
    print(f"economic_resolver: calculate_market_price: Called for item '{item_template_id}' (qty: {quantity}) in loc '{location_id}', player selling: {is_selling_to_market}, actor: {actor_entity_id} ({actor_entity_type})")

    economy_rules = rules_data.get("economy_rules")
    if not economy_rules:
        print("economic_resolver: calculate_market_price: ERROR - 'economy_rules' not found in rules_data.")
        return None

    item_definitions = rules_data.get("item_definitions") # Assuming item base prices are in rules_data
    if not item_definitions:
        print("economic_resolver: calculate_market_price: ERROR - 'item_definitions' not found in rules_data.")
        return None

    item_def = item_definitions.get(str(item_template_id))
    if not item_def:
        print(f"economic_resolver: calculate_market_price: ERROR - Item template '{item_template_id}' not found in item_definitions.")
        return None

    base_price = item_def.get("base_price")
    if base_price is None or not isinstance(base_price, (int, float)) or base_price < 0:
        print(f"economic_resolver: calculate_market_price: ERROR - Invalid or missing 'base_price' for item '{item_template_id}'. Found: {base_price}")
        return None

    current_price_per_unit = float(base_price)
    # ... (rest of the logic from RuleEngine.calculate_market_price, ensuring self._rules_data is replaced by rules_data,
    # and manager calls are made through passed-in managers) ...

    # 2. Apply Base Multipliers
    if is_selling_to_market:
        multiplier = economy_rules.get("base_sell_price_multiplier", 0.75)
        current_price_per_unit *= multiplier
    else: # Player is buying from market
        multiplier = economy_rules.get("base_buy_price_multiplier", 1.25)
        current_price_per_unit *= multiplier

    # 3. Apply Regional Modifiers (simplified example, full logic would be here)
    regional_modifiers_all = economy_rules.get("regional_price_modifiers", {})
    regional_mod_for_location = regional_modifiers_all.get(str(location_id))
    if regional_mod_for_location:
        base_mult = economy_rules.get("base_sell_price_multiplier", 0.75) if is_selling_to_market else economy_rules.get("base_buy_price_multiplier", 1.25)
        effective_multiplier = base_mult
        if is_selling_to_market:
            effective_multiplier += regional_mod_for_location.get("sell_price_multiplier_adj", 0.0)
        else:
            effective_multiplier += regional_mod_for_location.get("buy_price_multiplier_adj", 0.0)
        current_price_per_unit = float(base_price) * effective_multiplier
        # ... (add category specific logic here too)

    # 4. Apply Supply/Demand Modifiers
    if economy_manager and hasattr(economy_manager, 'get_market_inventory_level_ratio'):
        inventory_level_ratio = await economy_manager.get_market_inventory_level_ratio(guild_id, location_id, item_template_id)
        if inventory_level_ratio is not None:
            supply_demand_rules = economy_rules.get("supply_demand_rules", {})
            low_supply_thresh = supply_demand_rules.get("low_supply_threshold_percent", 0.2)
            high_supply_thresh = supply_demand_rules.get("high_supply_threshold_percent", 0.8)
            price_adj_factor = 1.0
            if inventory_level_ratio < low_supply_thresh:
                markup_percent = supply_demand_rules.get("min_supply_markup_percent", 200.0) - 100.0
                clamped_ratio = max(0.0, inventory_level_ratio)
                markup_factor = ( (low_supply_thresh - clamped_ratio) / low_supply_thresh ) if low_supply_thresh > 0 else 1.0
                price_adj_factor = 1.0 + (markup_factor * (markup_percent / 100.0))
            elif inventory_level_ratio > high_supply_thresh:
                discount_percent = supply_demand_rules.get("max_supply_discount_percent", 50.0)
                max_relevant_supply_ratio = high_supply_thresh * 1.5
                if inventory_level_ratio > max_relevant_supply_ratio : inventory_level_ratio = max_relevant_supply_ratio
                if max_relevant_supply_ratio > high_supply_thresh:
                    discount_factor_scale = (inventory_level_ratio - high_supply_thresh) / (max_relevant_supply_ratio - high_supply_thresh)
                    price_adj_factor = 1.0 - (discount_factor_scale * (discount_percent / 100.0))
                else:
                    price_adj_factor = 1.0 - (discount_percent / 100.0)
            current_price_per_unit *= price_adj_factor

    # 5. Relationship Modifiers
    trader_entity_id: Optional[str] = None
    trader_entity_type: Optional[str] = None
    if location_manager: # Use passed manager
        location_obj = await location_manager.get_location(guild_id, location_id)
        if location_obj and hasattr(location_obj, 'owner_id') and getattr(location_obj, 'owner_id'):
            trader_entity_id = str(getattr(location_obj, 'owner_id'))
            trader_entity_type = str(getattr(location_obj, 'owner_type', "Faction"))
    trader_entity_id = kwargs.get('trader_entity_id', trader_entity_id)
    trader_entity_type = kwargs.get('trader_entity_type', trader_entity_type)

    if relationship_manager and trader_entity_id and trader_entity_type: # Use passed manager
        relationship_strength = await relationship_manager.get_relationship_strength(
            guild_id, actor_entity_id, actor_entity_type, trader_entity_id, trader_entity_type
        )
        rel_influence_rules = economy_rules.get("relationship_price_influence", {})
        tiers = rel_influence_rules.get("trading_discount_per_tier", [])
        applicable_tiers = [tier for tier in tiers if relationship_strength >= tier.get("relationship_threshold", float('-inf'))]
        if applicable_tiers:
            applicable_tiers.sort(key=lambda t: t.get("relationship_threshold", float('-inf')), reverse=True)
            best_tier_effect = applicable_tiers[0]
            price_adj_percentage = 0.0
            if is_selling_to_market:
                price_adj_percentage += best_tier_effect.get("sell_bonus_percent", 0.0)
                price_adj_percentage -= best_tier_effect.get("sell_penalty_percent", 0.0)
            else:
                price_adj_percentage -= best_tier_effect.get("buy_discount_percent", 0.0)
                price_adj_percentage += best_tier_effect.get("buy_markup_percent", 0.0)
            current_price_per_unit *= (1 + (price_adj_percentage / 100.0))

    # 6. Skill/Reputation Modifiers
    actor_entity_obj = None
    if character_manager and actor_entity_type == "Character": # Use passed manager
        actor_entity_obj = await character_manager.get_character(guild_id, actor_entity_id)

    if actor_entity_obj: # Simplified skill logic
        skill_rep_rules = economy_rules.get("skill_reputation_price_influence", {})
        bartering_rules = skill_rep_rules.get("bartering_skill_influence")
        if bartering_rules and hasattr(actor_entity_obj, 'skills_data_json'): # Check actual attribute
            actor_skills = getattr(actor_entity_obj, 'skills_data_json', {}) or {}
            skill_id = bartering_rules.get("skill_id", "bartering")
            skill_level = actor_skills.get(skill_id, 0)
            if skill_level > 0:
                total_skill_effect_percent = 0.0
                if is_selling_to_market:
                    bonus_per_point = bartering_rules.get("sell_bonus_percent_per_skill_point", 0.0)
                    max_bonus = bartering_rules.get("max_total_sell_bonus_percent", float('inf'))
                    total_skill_effect_percent = min(skill_level * bonus_per_point, max_bonus)
                else:
                    discount_per_point = bartering_rules.get("buy_discount_percent_per_skill_point", 0.0)
                    max_discount = bartering_rules.get("max_total_discount_percent", float('inf'))
                    total_skill_effect_percent = -min(skill_level * discount_per_point, max_discount)
                current_price_per_unit *= (1 + (total_skill_effect_percent / 100.0))
        # Faction reputation logic would also go here, similar structure

    final_total_price = current_price_per_unit * quantity
    final_total_price = max(0, final_total_price)
    return float(final_total_price)


async def process_economy_tick(
    rules_data: Dict[str, Any],
    guild_id: str,
    game_time_delta: float,
    economy_manager: Optional["EconomyManager"], # Passed from RuleEngine's kwargs or self
    **kwargs: Any # To catch any other context items
) -> None:
    guild_id_str = str(guild_id)
    print(f"economic_resolver: process_economy_tick called for guild '{guild_id_str}', game_time_delta: {game_time_delta}s.")

    economy_rules = rules_data.get("economy_rules")
    if not economy_rules:
        print(f"economic_resolver: process_economy_tick: No 'economy_rules' found for guild '{guild_id_str}'. Skipping.")
        return

    if not economy_manager:
        print(f"economic_resolver: process_economy_tick: 'economy_manager' not found. Cannot process economy tick for guild '{guild_id_str}'.")
        return

    # Placeholder for actual tick processing logic
    # print(f"economic_resolver: process_economy_tick: Placeholder for guild '{guild_id_str}'.")
    if not economy_rules.get("supply_demand_rules"):
        print(f"economic_resolver: process_economy_tick: No 'supply_demand_rules' in 'economy_rules' for guild '{guild_id_str}'. No detailed simulation.")

    print(f"economic_resolver: process_economy_tick completed for guild '{guild_id_str}'.")
