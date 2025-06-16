from app.config import logger # Assuming your logger is in app.config

def get_localized_text(i18n_field: dict | None, language: str, default_lang: str = 'en') -> str:
    """
    Retrieves localized text from a dictionary field.

    Args:
        i18n_field: A dictionary containing language codes as keys and text as values.
        language: The desired language code.
        default_lang: The fallback language code if the desired language is not found.

    Returns:
        The localized text string, or an error message if no suitable text is found.
    """
    if not isinstance(i18n_field, dict):
        logger.warning(f"i18n_field is not a dict: {i18n_field}. Attempting to use as-is if string, else error.")
        if isinstance(i18n_field, str): # Handle cases where it might already be a simple string
            return i18n_field
        return "Localization error: Invalid format (field is not a dictionary)"

    text = i18n_field.get(language)
    if text is None:
        text = i18n_field.get(default_lang)

    if text is None:
        # Fallback to any available language if specific and default are missing
        if i18n_field.values():
            # Attempt to get the first value, ensuring it's a string
            first_value = next(iter(i18n_field.values()))
            if isinstance(first_value, str):
                text = first_value
                logger.debug(f"No localization for '{language}' or '{default_lang}'. Fell back to first available: '{text}'")
            else:
                logger.warning(f"No valid string localization found for key in i18n_field. Field: {i18n_field}, Lang: {language}")
                text = "Localization error: No valid text available"
        else:
            logger.warning(f"No localization found for key in i18n_field (empty dict). Field: {i18n_field}, Lang: {language}")
            text = "Localization error: No text available (empty)"

    if not isinstance(text, str):
        logger.warning(f"Localized text resolved to non-string type ({type(text)}): {text}. For i18n_field: {i18n_field}, Lang: {language}")
        return "Localization error: Text not string"

    return text
