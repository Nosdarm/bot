from bot.ai.prompt_preparer import prepare_ai_prompt
from bot.services.openai_service import OpenAIService

def generate_narrative(guild_id: int, context: dict):
    prompt = prepare_ai_prompt(guild_id, context.get('location_id'), context.get('player_id'), context.get('party_id'))
    
    # In a real application, you would have a configured OpenAI service
    # openai_service = OpenAIService(api_key="YOUR_API_KEY")
    # narrative = openai_service.generate_text(prompt)
    
    # For now, we'll return a placeholder
    narrative = f"A narrative for guild {guild_id} with context: {context}"
    
    return narrative
