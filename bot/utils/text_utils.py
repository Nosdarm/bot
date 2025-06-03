import json
from typing import Dict, Any

def generate_summary(data_json: str, content_type: str) -> str:
    """
    Generates a brief summary for AI-generated content.
    """
    try:
        data: Dict[str, Any] = json.loads(data_json)
    except json.JSONDecodeError:
        return "Error: Could not parse content data."

    summary = f"Content Type: {content_type.capitalize()}\n"
    default_lang = 'en' # Or another preferred default

    if content_type == 'npc':
        name_i18n = data.get('name_i18n', {})
        name = name_i18n.get(default_lang, data.get('name', "Unknown NPC"))
        archetype = data.get('archetype', "N/A")
        summary += f"NPC Name: {name}\nArchetype: {archetype}"
    elif content_type == 'quest':
        name_i18n = data.get('name_i18n', {}) # Quests might use 'name_i18n' or 'title_i18n'
        title_i18n = data.get('title_i18n', name_i18n) # Fallback to name_i18n
        title = title_i18n.get(default_lang, data.get('name', data.get('title', "Unknown Quest")))
        summary += f"Quest Title: {title}"

        objectives = data.get('objectives', [])
        if objectives and isinstance(objectives, list):
            summary += f"\nObjectives ({len(objectives)}):"
            for i, obj in enumerate(objectives[:2]): # Show first 2 objectives
                obj_desc_i18n = obj.get('description_i18n', {})
                obj_desc = obj_desc_i18n.get(default_lang, obj.get('description', 'No description'))
                summary += f"\n  - {obj_desc}"
            if len(objectives) > 2:
                summary += "\n  ...and more."

    elif content_type == 'location':
        name_i18n = data.get('name_i18n', {})
        name = name_i18n.get(default_lang, data.get('name', "Unknown Location"))
        summary += f"Location Name: {name}"

        description_i18n = data.get('description_i18n',
                               data.get('description_template_i18n', {}))
        description = description_i18n.get(default_lang, data.get('description', "No description available."))

        # Take the first 100 chars of description for summary
        summary += f"\nDescription: {description[:100]}{'...' if len(description) > 100 else ''}"

    else:
        summary += "Unknown content type or no specific summary format defined."

    return summary.strip()

# Example Usage (can be removed or commented out)
if __name__ == '__main__':
    npc_data_example = {
        "name_i18n": {"en": "Sir Reginald", "ru": "Сэр Реджинальд"},
        "archetype": "Knight",
        "stats": {"strength": 10}
    }
    quest_data_example = {
        "name_i18n": {"en": "The Lost Artifact"},
        "objectives": [
            {"description_i18n": {"en": "Find the ancient amulet."}},
            {"description_i18n": {"en": "Return it to the wizard."}}
        ]
    }
    location_data_example = {
        "name_i18n": {"en": "The Whispering Woods"},
        "description_i18n": {"en": "A dense and ancient forest, rumored to hold many secrets. The trees here seem to whisper tales of old to those who listen closely enough."}
    }

    print("--- NPC Summary ---")
    print(generate_summary(json.dumps(npc_data_example), 'npc'))
    print("\n--- Quest Summary ---")
    print(generate_summary(json.dumps(quest_data_example), 'quest'))
    print("\n--- Location Summary ---")
    print(generate_summary(json.dumps(location_data_example), 'location'))

    # Test with missing name
    npc_data_no_name = { "archetype": "Peasant" }
    print("\n--- NPC Summary (No Name) ---")
    print(generate_summary(json.dumps(npc_data_no_name), 'npc'))

    # Test with missing name_i18n but has name
    npc_data_plain_name = { "name": "Bob", "archetype": "Peasant" }
    print("\n--- NPC Summary (Plain Name) ---")
    print(generate_summary(json.dumps(npc_data_plain_name), 'npc'))

    # Test quest with plain title
    quest_data_plain_title = {"title": "Simple Task"}
    print("\n--- Quest Summary (Plain Title) ---")
    print(generate_summary(json.dumps(quest_data_plain_title), 'quest'))

    # Test location with description_template_i18n
    location_data_template_desc = {
        "name_i18n": {"en": "The Old Mill"},
        "description_template_i18n": {"en": "A dilapidated mill by the river."}
    }
    print("\n--- Location Summary (Template Desc) ---")
    print(generate_summary(json.dumps(location_data_template_desc), 'location'))
