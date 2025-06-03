# bot/services/openai_service.py

import json
from typing import Dict, Optional, Any, List, TYPE_CHECKING # Added TYPE_CHECKING
import traceback # For better error logging

# Runtime import with aliasing
try:
    from openai import OpenAI as RuntimeOpenAI, AsyncOpenAI as RuntimeAsyncOpenAI
    OPENAI_LIB_AVAILABLE = True
except ImportError:
    RuntimeOpenAI = None # Define placeholders for runtime
    RuntimeAsyncOpenAI = None
    OPENAI_LIB_AVAILABLE = False
    print("OpenAIService WARNING: OpenAI library not found. Service will run in placeholder mode.")

# Import for static type checking (Pylance)
if TYPE_CHECKING:
    from openai import OpenAI, AsyncOpenAI # These are for type hints if needed directly


class OpenAIService:
    """
    A service class to interact with the OpenAI API.
    Can operate in placeholder mode if API key is missing or library is not installed.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-3.5-turbo", default_max_tokens: int = 500, **kwargs):
        """
        Initializes the OpenAIService.
        """
        print(f"Initializing OpenAIService (Model: {model})...")
        self._api_key = api_key
        self._model = model
        self._default_max_tokens = default_max_tokens
        self._client: Optional['AsyncOpenAI'] = None # Type hint remains string literal

        if self._api_key and RuntimeAsyncOpenAI: # Use runtime alias for check
            try:
                self._client = RuntimeAsyncOpenAI(api_key=self._api_key) # Use runtime alias for instantiation
                print("OpenAIService: OpenAI AsyncClient initialized successfully.")
            except Exception as e:
                print(f"OpenAIService ERROR: Failed to initialize OpenAI AsyncClient: {e}")
                self._client = None
        else:
            if not self._api_key:
                print("OpenAIService WARNING: API key not provided. Service will operate in placeholder mode.")
            if not RuntimeAsyncOpenAI: # Check runtime alias
                 print("OpenAIService WARNING: AsyncOpenAI client not available (openai library issue?). Service will operate in placeholder mode.")

        print(f"OpenAIService initialized. API available: {self.is_available()}")

    def is_available(self) -> bool:
        """Checks if the OpenAI service is configured and the client is initialized."""
        return self._client is not None

    # --- Core Method for Master Responses ---
    # This signature must match what StageDescriptionGenerator and OnEnterActionExecutor expect.
    async def generate_master_response(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None, temperature: float = 0.7) -> str:
        """
        Generates a narrative response simulating an AI game master.
        In this placeholder, it returns a simple predefined string.
        :param system_prompt: Instructions for the AI's persona.
        :param user_prompt: The specific request or context for the description.
        :param max_tokens: The maximum length of the response (optional).
        :param temperature: Controls creativity (optional).
        Returns a generated text string.
        """
        print(f"OpenAIService PLACEHOLDER: generate_master_response called (Model: {self._model}, Max Tokens: {max_tokens or self._default_max_tokens}, Temp: {temperature})")
        if not self.is_available() or not self._client:
            print(f"OpenAIService PLACEHOLDER: generate_master_response called (Model: {self._model})")
            if "Описание проверки" in system_prompt or "Проверка " in user_prompt:
                 return "Placeholder: Проверка проведена с предсказуемым успехом, мастер тонко подметил это в тенях."
            elif "опиши сцену" in system_prompt.lower() or "опиши текущую локацию" in user_prompt.lower():
                 return "Placeholder: Перед вами предстает зрелище, рожденное воображением мастера... туман сгущается, а воздух кажется наэлектризованным."
            else:
                 return "Placeholder: Мастер многозначительно кивает в ответ."

        print(f"OpenAIService: generate_master_response called (Model: {self._model}, Max Tokens: {max_tokens or self._default_max_tokens}, Temp: {temperature})")
        try:
            response = await self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self._model,
                max_tokens=max_tokens if max_tokens is not None else self._default_max_tokens,
                temperature=temperature,
            )
            generated_text = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else "Error: Empty response from API."
            print("OpenAIService: Successfully generated master response.")
            return generated_text
        except Exception as e:
            print(f"OpenAIService ERROR: Error calling OpenAI API for master response: {e}")
            traceback.print_exc()
            return f"Internal error with AI Master: {e}"

    async def generate_npc_response(
        self,
        npc_name: str,
        npc_persona: str,
        npc_description: Optional[str],
        conversation_history: List[Dict[str, str]],
        player_message: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.75
    ) -> Optional[str]:
        """
        Generates an NPC dialogue response using OpenAI.
        """
        if not self.is_available() or not self._client:
            print(f"OpenAIService PLACEHOLDER: generate_npc_response for {npc_name} (Model: {self._model})")
            # Simple placeholder response
            return f"{npc_name} ponders your words ('{player_message}') and nods slowly, lost in thought. (AI response not available)"

        print(f"OpenAIService: Generating NPC response for {npc_name} (Model: {self._model})")

        system_prompt_lines = [
            f"You are {npc_name}.",
            f"Your persona: {npc_persona}.",
        ]
        if npc_description:
            system_prompt_lines.append(f"Additional details: {npc_description}")

        system_prompt_lines.append("Focus on roleplaying based on your persona and the conversation history. Keep responses concise and in character.")
        system_prompt = " ".join(system_prompt_lines)

        messages = [{"role": "system", "content": system_prompt}]
        for entry in conversation_history:
            role = "user" if entry["speaker"].lower() == "player" else "assistant" # Assuming player is user, NPC is assistant
            # If using actual player/NPC names in history, need to map them.
            # For simplicity, let's assume history uses "Player" and the NPC's name.
            if entry["speaker"].lower() == "player": # Or matches player_data['name']
                role = "user"
            elif entry["speaker"].lower() == npc_name.lower():
                role = "assistant"
            else: # Could be another NPC, or system message. For now, map to user if not assistant.
                role = "user"
            messages.append({"role": role, "content": entry["line"]})

        messages.append({"role": "user", "content": player_message})

        try:
            response = await self._client.chat.completions.create(
                messages=messages,
                model=self._model,
                max_tokens=max_tokens if max_tokens is not None else self._default_max_tokens,
                temperature=temperature,
            )
            generated_text = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None
            if generated_text:
                print(f"OpenAIService: Successfully generated NPC response for {npc_name}.")
            else:
                print(f"OpenAIService WARNING: Empty response from API for {npc_name}.")
            return generated_text
        except Exception as e:
            print(f"OpenAIService ERROR: Error calling OpenAI API for NPC response ({npc_name}): {e}")
            traceback.print_exc()
            return None

    async def generate_structured_multilingual_content(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None, # Consider a larger default for complex JSON
        temperature: float = 0.5  # May need adjustment for structured output
    ) -> Optional[Dict[str, Any]]:
        """
        Generates structured multilingual content as JSON from the AI.
        :param system_prompt: Instructions for the AI, including JSON format.
        :param user_prompt: The specific request and comprehensive context.
        :param max_tokens: Max length of the response.
        :param temperature: Controls creativity.
        Returns a dictionary parsed from the AI's JSON response, or None on error.
        """
        if not self.is_available() or not self._client:
            print(f"OpenAIService PLACEHOLDER: generate_structured_multilingual_content called (Model: {self._model}). AI not available.")
            # Placeholder for structured content might be more complex.
            # For now, returning None or a simple error structure.
            return {"error": "AI service not available.", "ru": "Сервис ИИ недоступен.", "en": "AI service not available."}

        effective_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        # For JSON, we might need more tokens than simple text. Consider increasing default for this method.
        # For example: effective_max_tokens = max_tokens if max_tokens is not None else 1500

        print(f"OpenAIService: generate_structured_multilingual_content called (Model: {self._model}, Max Tokens: {effective_max_tokens}, Temp: {temperature})")

        try:
            # Some models perform better with JSON if explicitly told to use JSON mode,
            # if the API supports it (e.g., response_format={"type": "json_object"} for newer OpenAI models)
            # This example uses the standard chat completion.
            completion_params = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "model": self._model,
                "max_tokens": effective_max_tokens,
                "temperature": temperature,
            }
            # Example for enabling JSON mode if using compatible OpenAI models/API versions:
            # if self._model in ["gpt-4-1106-preview", "gpt-3.5-turbo-1106"]: # Check your model version
            #     completion_params["response_format"] = {"type": "json_object"}


            response = await self._client.chat.completions.create(**completion_params)

            raw_response_text = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None

            if not raw_response_text:
                print("OpenAIService ERROR: Empty response from API.")
                return {"error": "Empty response from API.", "ru": "Пустой ответ от API.", "en": "Empty response from API."}

            print("OpenAIService: Received raw response. Attempting to parse JSON...")
            # The response might contain leading/trailing text around the JSON block,
            # or the JSON might be malformed. Robust parsing is needed.
            # Try to find JSON block if it's embedded:
            try:
                # Attempt to parse the whole string first
                parsed_json = json.loads(raw_response_text)
                print("OpenAIService: Successfully parsed JSON response.")
                return parsed_json
            except json.JSONDecodeError as e_direct:
                # If direct parsing fails, try to extract JSON from Markdown code blocks
                print(f"OpenAIService: Direct JSON parsing failed ({e_direct}). Trying to extract from Markdown code block.")
                if raw_response_text.startswith("```json") and raw_response_text.endswith("```"):
                    json_block = raw_response_text[len("```json"):-len("```")].strip()
                    try:
                        parsed_json = json.loads(json_block)
                        print("OpenAIService: Successfully parsed JSON from Markdown code block.")
                        return parsed_json
                    except json.JSONDecodeError as e_markdown:
                        print(f"OpenAIService ERROR: Failed to parse JSON even from Markdown block: {e_markdown}")
                        print(f"Raw response was: {raw_response_text}")
                        return {"error": "Failed to parse JSON response from AI.", "details": str(e_markdown), "raw_text": raw_response_text}
                else:
                    print(f"OpenAIService ERROR: Response is not valid JSON and not in a Markdown code block.")
                    print(f"Raw response was: {raw_response_text}")
                    return {"error": "Response is not valid JSON.", "raw_text": raw_response_text}

        except Exception as e:
            print(f"OpenAIService ERROR: Error calling OpenAI API for structured content: {e}")
            traceback.print_exc()
            return {"error": f"Internal error with AI service: {e}", "ru": f"Внутренняя ошибка с сервисом ИИ: {e}", "en": f"Internal error with AI service: {e}"}