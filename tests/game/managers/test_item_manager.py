import unittest
from unittest.mock import MagicMock, patch
import json
import sys # Added for logging
import logging # Added for logging

from bot.game.managers.item_manager import ItemManager
# No DB adapter needed if we only test loading from settings for templates

class TestItemManagerTemplateLoading(unittest.TestCase):

    def test_load_item_templates_i18n_conversion_and_name_derivation(self):
        # Configure logging to be visible for this test
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, force=True)
        print("DEBUG_TEST: Logging configured for test_load_item_templates_i18n_conversion_and_name_derivation", file=sys.stderr)
        sys.stderr.flush()

        """
        Test _load_item_templates correctly processes i18n fields from settings
        and derives a plain 'name'.
        """
        mock_settings = {
            "default_language": "en",
            "item_templates": {
                "sword1": {
                    "id": "sword1",
                    "name": "Basic Sword", # Legacy plain name
                    "description_i18n": {"en": "A simple sword for beginners.", "ru": "Простой меч для новичков."},
                    "type": "weapon",
                    "properties": {"slot": "main_hand"}
                },
                "potion_health": {
                    "id": "potion_health",
                    "name_i18n": {"en": "Health Potion", "ru": "Зелье Здоровья"},
                    # Missing description_i18n, should default
                    "type": "consumable",
                    "properties": {"heals": 25}
                },
                "book_lore": {
                    "id": "book_lore",
                    "name_i18n": {"de": "Buch des Wissens"}, # Non-default language only
                    "description": "Ein Buch voller Weisheiten.", # Legacy plain description
                    "type": "readable"
                },
                "arrow_generic": { # Test case with no i18n fields, only ID
                    "id": "arrow_generic",
                    "type": "ammo"
                }
            }
        }

        # Patch _settings directly on an instance or pass it in __init__
        # For this test, let's assume ItemManager uses self._settings

        item_manager = ItemManager(settings=mock_settings, db_service=None) # Changed db_adapter to db_service
        # _load_item_templates is called in __init__

        # Debug step: Check if templates are loaded into the internal cache
        internal_templates_cache = item_manager._item_templates
        self.assertIn("sword1", internal_templates_cache, "sword1 should be loaded into _item_templates by _load_item_templates")

        #Sword
        sword1_template = item_manager.get_item_template("sword1")
        self.assertIsNotNone(sword1_template)
        self.assertEqual(sword1_template["name_i18n"], {"en": "Basic Sword"}) # Converted from plain "name"
        self.assertEqual(sword1_template["name"], "Basic Sword") # Derived name
        self.assertEqual(sword1_template["description_i18n"], {"en": "A simple sword for beginners.", "ru": "Простой меч для новичков."})

        # Potion
        potion_template = item_manager.get_item_template("potion_health")
        self.assertIsNotNone(potion_template)
        self.assertEqual(potion_template["name_i18n"], {"en": "Health Potion", "ru": "Зелье Здоровья"})
        self.assertEqual(potion_template["name"], "Health Potion")
        self.assertEqual(potion_template["description_i18n"], {"en": ""}) # Defaulted

        # Book
        book_template = item_manager.get_item_template("book_lore")
        self.assertIsNotNone(book_template)
        self.assertEqual(book_template["name_i18n"], {"de": "Buch des Wissens"})
        self.assertEqual(book_template["name"], "Buch des Wissens") # Derived, falls back to first available
        self.assertEqual(book_template["description_i18n"], {"en": "Ein Buch voller Weisheiten."}) # Converted from plain "description" using default_lang 'en'

        # Arrow
        arrow_template = item_manager.get_item_template("arrow_generic")
        self.assertIsNotNone(arrow_template)
        self.assertEqual(arrow_template["name_i18n"], {"en": "arrow_generic"}) # Fallback to ID with default_lang
        self.assertEqual(arrow_template["name"], "arrow_generic") # Derived
        self.assertEqual(arrow_template["description_i18n"], {"en": ""}) # Defaulted

if __name__ == '__main__':
    unittest.main()
