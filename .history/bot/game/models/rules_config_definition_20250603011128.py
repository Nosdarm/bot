"""
Defines the structure for rules_config, which holds conflict types and resolution rules.
"""

RULES_CONFIG_STRUCTURE = {
    "conflict_type_id": {  # Unique identifier for the conflict type (e.g., "simultaneous_move_to_limited_space")
        "description": "A human-readable description of the conflict type.",
        "manual_resolution_required": True,  # Boolean: True if manual intervention is needed
        "notification_format": {  # Required if manual_resolution_required is True
            "message": "Player {actor_id} and Player {target_id} are attempting to move to the same limited space: {space_id}. Please resolve.",
            "placeholders": ["actor_id", "target_id", "space_id"] # List of placeholders used in the message
        },
        "automatic_resolution": {  # Required if manual_resolution_required is False
            "check_type": "skill_check",  # e.g., "skill_check", "stat_check", "opposed_check", "random"
            "actor_check_details": { # Details for the actor initiating the action
                "skill_or_stat_to_use": "dexterity", # e.g., "dexterity", "strength", "negotiation_skill"
                "modifiers": ["status_effect_agility_buff"] # List of potential modifiers (buffs/debuffs)
            },
            "target_check_details": { # Details for the target of the action (if applicable, e.g., in opposed_check)
                "skill_or_stat_to_use": "dexterity",
                "modifiers": []
            },
            "outcome_rules": {
                "success_threshold": 10, # For single player checks (skill_check, stat_check)
                "higher_wins": True, # For opposed checks
                "tie_breaker_rule": "actor_priority", # e.g., "actor_priority", "target_priority", "random", "re_roll"
                "outcomes": {
                    "actor_wins": {
                        "description": "Actor successfully performs the action.",
                        "effects": ["apply_effect_move_to_space_actor", "apply_effect_stun_target_short"]
                    },
                    "target_wins": { # Or "actor_fails" for single player checks
                        "description": "Target successfully defends or actor fails the action.",
                        "effects": ["apply_effect_move_to_space_target"]
                    },
                    "tie": {
                        "description": "The conflict results in a stalemate or a specific tie outcome.",
                        "effects": ["apply_effect_both_remain_in_place"]
                    }
                }
            }
        }
    }
}

# --- Example Configurations ---

EXAMPLE_RULES_CONFIG = {
    "simultaneous_move_to_limited_space": {
        "description": "Two entities attempt to move into the same space that can only occupy one.",
        "manual_resolution_required": False,
        "automatic_resolution": {
            "check_type": "opposed_check",
            "actor_check_details": {
                "skill_or_stat_to_use": "agility_score",
                "modifiers": ["haste_buff", "encumbered_debuff"]
            },
            "target_check_details": {
                "skill_or_stat_to_use": "agility_score",
                "modifiers": ["terrain_advantage_buff"]
            },
            "outcome_rules": {
                "higher_wins": True,
                "tie_breaker_rule": "random", # If agility scores are equal, a random roll decides
                "outcomes": {
                    "actor_wins": {
                        "description": "The actor reaches the space first.",
                        "effects": ["actor_moves_to_space", "target_remains_previous_space"]
                    },
                    "target_wins": {
                        "description": "The target reaches the space first.",
                        "effects": ["target_moves_to_space", "actor_remains_previous_space"]
                    },
                    "tie": { # Only if tie_breaker_rule was something like "specific_outcome_on_tie"
                        "description": "Both entities are momentarily stunned by the near collision.",
                        "effects": ["apply_stun_brief_actor", "apply_stun_brief_target"]
                    }
                }
            }
        }
    },
    "simultaneous_action_priority": { # New example for automatic resolution
        "description": "Two or more entities' actions are about to occur simultaneously, determine priority.",
        "manual_resolution_required": False,
        "automatic_resolution": {
            # This check_type will be passed to RuleEngine.resolve_check as 'check_key'
            # It assumes a configuration exists in RuleEngine._rules_data.checks for "initiative_check"
            "check_type": "initiative_check", 
            "actor_check_details": {
                # 'skill_or_stat_to_use' might be implicitly defined by "initiative_check" in RuleEngine,
                # or could be specified here if "initiative_check" is generic.
                # For this example, assume "initiative_check" in RuleEngine knows to use 'dexterity' or 'perception'.
                "skill_or_stat_to_use": "dexterity", # Example, could be derived from rule_engine's check config
                "modifiers": ["quick_reflexes_buff", "surprised_debuff"],
                "role_in_check": "primary_actor" # Helps RuleEngine interpret who is who
            },
            "target_check_details": { # Assuming the conflict involves two main parties (actor vs target)
                                      # For multi-party, this model would need adjustment or sequential opposed checks.
                "skill_or_stat_to_use": "dexterity", # Example
                "modifiers": ["combat_awareness_buff"],
                "role_in_check": "opposing_actor"
            },
            "outcome_rules": {
                "higher_wins": True, # Highest initiative roll wins priority
                "tie_breaker_rule": "stat_comparison:dexterity", # If rolls tie, compare dexterity stat.
                                                               # Other options: "random", "actor_preference", "target_preference"
                "outcomes": { # These keys ('actor_wins', 'target_wins', 'tie') are conventions.
                              # The resolver will map the check's winner to these keys.
                    "actor_wins": { # Corresponds to the 'primary_actor' winning the check
                        "description": "{actor_name}'s action happens first.",
                        "effects": ["actor_action_priority_high", "target_action_priority_low"] # Game engine tags/effects
                    },
                    "target_wins": { # Corresponds to the 'opposing_actor' winning
                        "description": "{target_name}'s action happens first.",
                        "effects": ["target_action_priority_high", "actor_action_priority_low"]
                    },
                    "tie": { # Only if tie_breaker_rule leads to a defined tie state (e.g. "simultaneous_if_exact_tie")
                             # If tie_breaker_rule resolves the tie (e.g. "stat_comparison"), this outcome might not be used.
                        "description": "Actions are simultaneous due to tie. Following tie-breaker: {actor_name} preferred.",
                        "effects": ["actor_action_priority_high", "target_action_priority_low"] # Example: actor wins tie
                    }
                }
            }
        }
    },
    "contested_resource_grab": {
        "description": "Two or more players attempt to grab the same limited resource.",
        "manual_resolution_required": True, # Changed to True for this example
        "notification_format": {
            "message": "Conflict ID {conflict_id}: Players {player_ids_str} are trying to grab '{resource_name}' at {location_name}. Who gets it?",
            "placeholders": ["conflict_id", "player_ids_str", "resource_name", "location_name"] # player_ids_str will be a comma-separated string
        }
        # No automatic_resolution as manual_resolution_required is True
    },
    "diplomatic_negotiation_dispute": {
        "description": "Two factions are in a dispute that requires diplomatic intervention.",
        "manual_resolution_required": True,
        "notification_format": {
            "message": "Conflict ID {conflict_id}: Faction {faction1_id} and Faction {faction2_id} are in a diplomatic dispute over {dispute_subject}. A moderator is required to resolve this. Conflict ID: {conflict_id}",
            "placeholders": ["faction1_id", "faction2_id", "dispute_subject", "conflict_id"]
        }
        # No automatic_resolution needed as manual_resolution_required is True
    },
    "critical_system_hack": {
        "description": "An entity attempts to hack a critical system, opposed by system security.",
        "manual_resolution_required": False,
        "automatic_resolution": {
            "check_type": "opposed_check",
            "actor_check_details": { # The hacker
                "skill_or_stat_to_use": "hacking_skill",
                "modifiers": ["ice_pick_tool_buff", "firewall_debuff_on_actor"]
            },
            "target_check_details": { # The system's security
                "skill_or_stat_to_use": "system_security_level_stat", # This could be a fixed stat of the system
                "modifiers": ["active_countermeasures_buff"]
            },
            "outcome_rules": {
                "higher_wins": True,
                "tie_breaker_rule": "target_priority", # System wins on a tie
                "outcomes": {
                    "actor_wins": {
                        "description": "Hacker successfully breaches the system.",
                        "effects": ["system_access_granted_to_actor", "log_suspicious_activity_minor"]
                    },
                    "target_wins": {
                        "description": "System security repels the hacking attempt.",
                        "effects": ["hacking_attempt_blocked", "log_suspicious_activity_major", "trigger_alert_system_admin"]
                    },
                    "tie": { # Based on tie_breaker_rule, this might not be reachable if target always wins.
                             # If tie_breaker was "specific_outcome_on_tie", this could be used.
                        "description": "Hacker is detected but not fully repelled; limited access granted or alert raised.",
                        "effects": ["log_suspicious_activity_moderate", "trigger_alert_system_admin_medium_priority"]
                    }
                }
            }
        }
    }
}

# It is expected that the actual rules_config.json or Python dict used by the game
# will be a dictionary where keys are specific conflict type IDs (like the examples above)
# and values are dictionaries conforming to the RULES_CONFIG_STRUCTURE["conflict_type_id"].
#
# For example:
# game_config = {
#     "simultaneous_move_to_limited_space": EXAMPLE_RULES_CONFIG["simultaneous_move_to_limited_space"],
#     "contested_resource_grab": EXAMPLE_RULES_CONFIG["contested_resource_grab"],
#     # ... other conflict types
# }
#
# The list of `effects` within outcomes would correspond to function names or identifiers
# that the game engine knows how to execute. For example, "actor_moves_to_space"
# would trigger a game logic function responsible for moving the actor.
#
# Modifiers like "haste_buff" or "encumbered_debuff" would be looked up on the character/entity
# involved in the conflict, and their values (e.g., +2 agility, -10% speed) would be applied
# to the relevant skill/stat check.
