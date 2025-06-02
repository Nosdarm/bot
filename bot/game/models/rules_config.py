# bot/game/models/rules_config.py
from __future__ import annotations # For type hinting RulesConfig in from_dict
from typing import Optional, Dict, Any
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class RulesConfig(BaseModel):
    """
    Represents a configuration set for game rules.
    The 'id' attribute serves as the primary key (e.g., 'default_rules', 'v1_ruleset').
    'config_data' stores all rule details as a JSON string.
    """

    def __init__(self, id: str, config_data: Optional[str] = None):
        """
        Initializes a RulesConfig instance.
        
        Args:
            id (str): The unique identifier for this ruleset (e.g., 'default_config').
            config_data (Optional[str]): A JSON string containing the actual rule configurations.
                                         Defaults to None.
        """
        super().__init__(id=id)
        self.config_data: Optional[str] = config_data

    # to_dict and from_dict are inherited from BaseModel and should work directly
    # as attribute names 'id' and 'config_data' will match dictionary keys.

    # Example of a helper to get parsed data (optional, can be outside the model)
    # import json
    # def get_parsed_config(self) -> Optional[Dict[str, Any]]:
    #     if self.config_data:
    #         try:
    #             return json.loads(self.config_data)
    #         except json.JSONDecodeError:
    #             # Handle error or log appropriately
    #             return None
    #     return None

    def __repr__(self) -> str:
        return f"<RulesConfig(id='{self.id}', has_config_data={self.config_data is not None})>"

# Example usage (outside of class, for illustration):
# if __name__ == '__main__':
#     # Create a new rules config
#     rules1 = RulesConfig(id='default_v1', config_data='{"player_max_hp": 100, "movement_speed": 5}')
#     print(rules1)
#     dict_rules1 = rules1.to_dict()
#     print(dict_rules1)
#
#     # Create from dict
#     rules2 = RulesConfig.from_dict({'id': 'test_rules', 'config_data': '{"xp_multiplier": 1.5}'})
#     print(rules2)
#     print(rules2.config_data)
#
#     # Config with no data initially
#     rules3 = RulesConfig(id='empty_rules')
#     print(rules3)
#     rules3.config_data = '{"new_rule": "added_later"}'
#     print(rules3.to_dict())
