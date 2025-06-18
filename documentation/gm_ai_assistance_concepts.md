# AI-Assisted GM Logging and Summarization (Future Concept)

This document outlines a conceptual plan for a future feature: AI-assisted logging and summarization of game events to assist Game Masters (GMs).

## 1. Concept Definition

*   **Goal:** To provide GMs with concise, AI-generated summaries of significant game events, player achievements, emerging plot threads, and overall world changes within their guild. This helps GMs stay informed and identify areas needing attention or further development.
*   **Source Data:**
    *   **Primary:** The `StoryLog` (or `GameLog`) which records structured game events (e.g., quest completions, important NPC interactions, combat outcomes, significant discoveries, faction relation changes).
    *   **Secondary:** Changes in `WorldState` flags, aggregated player progression data (e.g., average party level, major crafting achievements), economic shifts, or outputs from other simulation processors.
*   **Trigger for Summarization:**
    *   **Periodic:** Automated summaries generated at set intervals (e.g., daily, weekly real-time).
    *   **On-Demand:** GMs could request a summary for a specific period or based on certain criteria.
*   **Output:**
    *   A natural language summary delivered to a GM-designated Discord channel, a direct message, or a future GM dashboard interface.
    *   Summaries could be tailored in length and focus (e.g., "brief daily player activity report," "detailed weekly world evolution summary").

## 2. High-Level System Interaction

The system would involve the following components:

1.  **`GameLogManager` (or `StoryLogManager`):**
    *   **Existing Functionality:** Stores structured logs of game events.
    *   **New Method (Conceptual):** `async def get_significant_log_entries(guild_id: str, start_time: datetime, end_time: datetime, significance_criteria: Optional[Dict] = None) -> List[GameLogEntry]`
        *   This method would filter and retrieve log entries based on the time period and criteria.
        *   "Significance" could be defined by event types (e.g., `major_quest_completed`, `boss_defeated`, `faction_rep_changed_critical`, `rare_item_looted`, `new_location_discovered`), specific entities involved, or magnitude of change.

2.  **New `GmSummaryService` (Conceptual Service):**
    *   **Orchestration:** This service would manage the summarization process.
    *   **Data Collection:**
        *   Fetch recent significant log entries from `GameLogManager`.
        *   Optionally, fetch relevant `WorldState` data from `WorldStateManager` or `GameManager`.
        *   Optionally, query other managers (e.g., `PlayerManager`, `EconomyManager`) for aggregated data if needed for specific summary types.
    *   **Context Preparation:**
        *   Utilize `PromptContextCollector` to gather any necessary context related to the events being summarized (e.g., details about NPCs, locations, or quests mentioned in the logs to provide context to the LLM).
    *   **Prompt Generation:**
        *   Use `MultilingualPromptGenerator` to construct a detailed prompt for the Language Model (LLM).
        *   The prompt would instruct the LLM to act as a "Game Chronicler" or "Assistant GM."
        *   It would provide the structured list of significant events and the collected context.
        *   It would specify the desired output format, length, tone (e.g., narrative, bullet points), and focus (e.g., "player achievements," "emerging plot hooks," "economic trends").
    *   **AI Interaction:**
        *   Call an `OpenAIService` (or equivalent LLM interaction service) with the generated prompt.
    *   **Delivery:**
        *   Receive the natural language summary from the AI service.
        *   Format the summary (e.g., Markdown for Discord).
        *   Use a `NotificationService` to send the summary to the GM's configured channel or interface.

3.  **`PromptContextCollector`:**
    *   Would need to be extended to fetch context relevant to a list of heterogeneous game events, not just for generating new game content.

4.  **`MultilingualPromptGenerator`:**
    *   A new prompt generation function (e.g., `generate_gm_summary_prompt`) would be created.

5.  **`OpenAIService` (or equivalent):**
    *   The existing service for interacting with the LLM would be used.

## 3. AI Prompt Considerations

*   **Role Definition:** Clearly instruct the AI on its role (e.g., "You are an assistant Game Master, tasked with summarizing recent events in a text-based RPG. Provide a concise and informative overview for the head GM.").
*   **Input Data:** The prompt would include the structured log data (e.g., as a JSON list of event objects, each with `event_type`, `timestamp`, `involved_entities`, `details_json`).
*   **Output Requirements:**
    *   Specify desired length (e.g., "a 3-5 paragraph summary" or "a bulleted list of no more than 10 key points").
    *   Define focus areas: "Highlight major player achievements, significant world changes, potential new plot hooks, and any unusual activities."
    *   Ask for interpretation and connection: "Connect related events if possible and point out emerging trends or consequences."
    *   Example instruction: "Given the following log of events: [event_log_json], and this world context: [world_context_json], generate a narrative summary for the GM focusing on player impact and unresolved plot threads."

## 4. `RuleConfig` / GM Settings

*   **Configuration:** GMs could potentially configure:
    *   Frequency of periodic summaries (e.g., daily at a specific time, weekly).
    *   Types of events to be considered "significant" for their summaries.
    *   Preferred length or format of summaries.
    *   The specific channel/DM for receiving summaries.
*   These settings could be stored in a guild-specific configuration managed by `GameManager` or `GuildSettingsManager`.

## 5. Benefits

*   Reduces GM workload by automating the review of extensive game logs.
*   Helps GMs stay informed about multiple player groups or complex game states.
*   Highlights important trends or events that might require GM intervention or new content creation.
*   Can assist in generating "story so far" narratives for players or GMs.

This feature is conceptual and would require significant design and implementation effort, particularly around defining "significance" for events and crafting effective prompts for high-quality summaries.
