# bot/game/services/campaign_loader.py
from __future__ import annotations
import json
import os # For path operations
import traceback # For more detailed error logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    # No specific manager dependencies for basic loader,
    # but could have if it interacts with settings or a DB for campaign sources
    pass

class CampaignLoader:
    def __init__(self, settings: Optional[Dict[str, Any]] = None, **kwargs: Any):
        self._settings = settings if settings is not None else {}
        # Default base path can be configured in settings or hardcoded
        self._campaign_base_path = self._settings.get('campaign_data_path', 'data/campaigns')
        print(f"CampaignLoader initialized. Base campaign path: '{self._campaign_base_path}'")

    async def load_campaign_data_from_source(self, campaign_identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads campaign data from a source (e.g., JSON file).
        
        Args:
            campaign_identifier: An optional identifier for a specific campaign. 
                                 If None, a default might be loaded.

        Returns:
            A dictionary containing the loaded campaign data, or an empty dict on error.
        """
        effective_campaign_identifier = campaign_identifier
        if effective_campaign_identifier is None:
            effective_campaign_identifier = self._settings.get('default_campaign_identifier', 'default_campaign')
        
        file_path = os.path.join(self._campaign_base_path, f"{effective_campaign_identifier}.json")
        
        print(f"CampaignLoader: Attempting to load campaign data from '{file_path}'...")
        
        if not os.path.exists(file_path):
            print(f"CampaignLoader: Error - Campaign file not found at '{file_path}'.")
            # If the requested campaign was not found, and it wasn't already the default we're trying,
            # attempt to load the 'default_campaign' as a fallback.
            if campaign_identifier is not None and effective_campaign_identifier != 'default_campaign':
                 print(f"CampaignLoader: Fallback - Attempting to load 'default_campaign.json'.")
                 # Call recursively with 'default_campaign'. Pass None to avoid infinite loop if default is also missing.
                 return await self.load_campaign_data_from_source(campaign_identifier='default_campaign')
            return {} # Return empty if default is also missing or if it was the initial request

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"CampaignLoader: Successfully loaded and parsed campaign data from '{file_path}'.")
            return data
        except FileNotFoundError: # Should be caught by os.path.exists, but as a safeguard.
            print(f"CampaignLoader: Error (safeguard) - Campaign file not found at '{file_path}'.")
            return {}
        except json.JSONDecodeError as e:
            print(f"CampaignLoader: Error - Failed to parse JSON from campaign file '{file_path}': {e}")
            traceback.print_exc()
            return {}
        except Exception as e:
            print(f"CampaignLoader: Error - Could not read campaign file '{file_path}': {e}")
            traceback.print_exc()
            return {}

    async def list_available_campaigns(self) -> List[str]:
        """
        Lists available campaign identifiers by scanning the campaign data directory.
        """
        campaigns = []
        try:
            if os.path.exists(self._campaign_base_path) and os.path.isdir(self._campaign_base_path):
                for filename in os.listdir(self._campaign_base_path):
                    if filename.endswith(".json"):
                        campaigns.append(filename[:-5]) # Remove .json extension
            if not campaigns: # If directory is empty or doesn't exist
                print(f"CampaignLoader: No campaign files found in '{self._campaign_base_path}'. Returning placeholder.")
                return ["default_campaign"] # Return a placeholder if none found
            return campaigns
        except Exception as e:
            print(f"CampaignLoader: Error listing available campaigns from '{self._campaign_base_path}': {e}")
            traceback.print_exc()
            return ["default_campaign"] # Return placeholder on error