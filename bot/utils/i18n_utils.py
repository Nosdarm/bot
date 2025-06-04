from typing import Dict, Any

def get_i18n_text(data_dict: Dict[str, Any], field_prefix: str, lang: str, default_lang: str = "en") -> str:
    """
    Retrieves internationalized text from a dictionary.

    Args:
        data_dict: The dictionary containing the data (e.g., a model instance as a dict).
        field_prefix: The base name of the field (e.g., "name", "description").
                      The function will look for a field named f"{field_prefix}_i18n".
        lang: The desired language code (e.g., "en", "es").
        default_lang: The fallback language code if the desired language is not found.

    Returns:
        The internationalized text string, or a fallback/default string if not found.
    """
    if not data_dict:
        return f"{field_prefix} not found (empty data)"

    i18n_field_name = f"{field_prefix}_i18n"
    i18n_data = data_dict.get(i18n_field_name)

    if isinstance(i18n_data, dict) and i18n_data:
        if lang in i18n_data:
            return str(i18n_data[lang])
        if default_lang in i18n_data:
            return str(i18n_data[default_lang])
        # Fallback to the first value in the i18n dict if specific langs not found
        try:
            return str(next(iter(i18n_data.values())))
        except StopIteration: # Should not happen if i18n_data is not empty
            pass # Fall through to plain field access

    # If i18n field doesn't exist, is not a dict, or is empty, try plain field
    plain_field_value = data_dict.get(field_prefix)
    if plain_field_value is not None:
        return str(plain_field_value)

    return f"{field_prefix} not found"
