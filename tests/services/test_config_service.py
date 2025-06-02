import unittest
from unittest.mock import patch, mock_open
import json

from bot.services.config_service import ConfigService

class TestConfigService(unittest.TestCase):

    @patch("builtins.open", new_callable=mock_open, read_data='{"section1": {"key": "value"}, "section2": [1, 2, 3]}')
    @patch("json.load")
    def test_load_success_and_get_section(self, mock_json_load, mock_file_open):
        # Mock json.load to return specific data
        mock_json_load.return_value = {"section1": {"key": "value"}, "section2": [1, 2, 3]}
        
        config_service = ConfigService(settings_path="dummy_path.json")
        
        # Test getting an existing section
        section1_data = config_service.get_config_section("section1")
        self.assertEqual(section1_data, {"key": "value"})
        mock_file_open.assert_called_once_with("dummy_path.json", 'r')
        mock_json_load.assert_called_once()

        # Test getting another existing section
        section2_data = config_service.get_config_section("section2")
        self.assertEqual(section2_data, [1, 2, 3])
        
        # Test getting a non-existing section
        non_existent_section = config_service.get_config_section("non_existent")
        self.assertIsNone(non_existent_section)

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_load_file_not_found(self, mock_file_open):
        # Suppress print output during this test
        with patch('builtins.print') as mock_print:
            config_service = ConfigService(settings_path="non_existent_path.json")
            self.assertIsNone(config_service._config_data)
            # Verify that an error message was printed
            mock_print.assert_called_with("Error: Settings file not found at non_existent_path.json")
        mock_file_open.assert_called_once_with("non_existent_path.json", 'r')

    @patch("builtins.open", new_callable=mock_open, read_data='{"section1": "value", "invalid_json": "this is not json, then a value}')
    @patch("json.load", side_effect=json.JSONDecodeError("Expecting value", "doc", 0))
    def test_load_json_decode_error(self, mock_json_load, mock_file_open):
        # Suppress print output during this test
        with patch('builtins.print') as mock_print:
            config_service = ConfigService(settings_path="invalid_json_path.json")
            self.assertIsNone(config_service._config_data)
            # Verify that an error message was printed
            mock_print.assert_called_with("Error: Could not decode JSON from invalid_json_path.json")
            
        mock_file_open.assert_called_once_with("invalid_json_path.json", 'r')
        mock_json_load.assert_called_once()

if __name__ == '__main__':
    unittest.main()
