import uuid

def is_uuid_format(s: str) -> bool:
    """Checks if a string looks like a UUID (simple format check)."""
    if not isinstance(s, str):
        return False
    # Basic check for length and dashes
    if len(s) == 36 and s[8] == '-' and s[13] == '-' and s[18] == '-' and s[23] == '-':
        try:
            uuid.UUID(s) # Attempt to parse as UUID to confirm format
            return True
        except ValueError:
            return False # Looks like UUID but parsing failed
    return False # Does not look like a standard UUID format
