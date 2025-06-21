# bot/game/exceptions.py

class GameError(Exception):
    """Base class for game-specific errors."""
    pass

class CharacterAlreadyInPartyError(GameError):
    """Raised when trying to add a character that is already in a party."""
    pass

class NotPartyLeaderError(GameError):
    """Raised when an action requiring party leadership is attempted by a non-leader."""
    pass

class PartyNotFoundError(GameError):
    """Raised when a specified party cannot be found."""
    pass

class PartyFullError(GameError):
    """Raised when trying to join a party that is already full."""
    pass

class CharacterNotInPartyError(GameError):
    """Raised when an action requires a character to be in a party, but they are not."""
    pass

# Add other custom game exceptions here as needed.
