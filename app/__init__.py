"""Job search operating agent."""
from pathlib import Path

# Load API keys (ANTHROPIC_API_KEY, ADZUNA_APP_ID, ADZUNA_APP_KEY) from the
# project's .env file so every entry point sees them: the Streamlit app, the
# scout CLI and the agents. Variables already set in the environment (for
# example GitHub Actions secrets) are left untouched.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is a declared dependency; tolerate its absence
    pass
