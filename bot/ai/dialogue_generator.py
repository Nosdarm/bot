from bot.ai.prompt_preparer import prepare_ai_prompt
from bot.services.openai_service import OpenAIService

def generate_npc_dialogue(guild_id: int, context: dict):
    location_id = context.get('location_id')
    player_id = context.get('player_id')
    party_id = context.get('party_id')

    if location_id is None or player_id is None or party_id is None:
        raise ValueError("location_id, player_id, and party_id must be provided in the context.")

    prompt = prepare_ai_prompt(guild_id, int(location_id), int(player_id), int(party_id))
    
    # In a real application, you would have a configured OpenAI service
    # openai_service = OpenAIService(api_key="YOUR_API_KEY")
    # dialogue = openai_service.generate_text(prompt)
    
    # For now, we'll return a placeholder
    dialogue = f"A dialogue for guild {guild_id} with context: {context}"
    
    return dialogue
