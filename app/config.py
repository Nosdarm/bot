import logging
import sys
import os # Import os

# 1. Define Log Format
log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# 2. Configure Logger 'text_rpg_bot'
logger = logging.getLogger('text_rpg_bot')
logger.setLevel(logging.INFO)

# 3. Add Console Handler (StreamHandler)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
logger.addHandler(console_handler)

# Example usage (optional, for testing this file directly)
if __name__ == '__main__':
    logger.info("Logging configuration loaded successfully.")
    logger.warning("This is a warning message for testing.")
    logger.error("This is an error message for testing.")

# --- OpenAI API Key Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY environment variable not set. AI services requiring OpenAI will not function.")
else:
    # Optional: Log a partial key or a message indicating it's loaded, for verification.
    # Be careful not to log the entire key.
    logger.info(f"OPENAI_API_KEY loaded (ending with '...{OPENAI_API_KEY[-4:]}' if long enough).")
