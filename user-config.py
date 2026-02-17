# Pywikibot configuration for CatWatchBot
# OAuth credentials are loaded from .env file
import os

# Load .env if not already loaded (needed when running pywikibot login directly)
try:
    import dotenv as _dotenv
    _config_dir = os.environ.get('PYWIKIBOT_DIR', os.getcwd())
    _dotenv.load_dotenv(os.path.join(_config_dir, '.env'))
    del _dotenv
except ImportError:
    pass

family = 'wikipedia'
mylang = 'no'

# Bot username on Norwegian Wikipedia and Commons
# Set MW_BOT_USERNAME in .env, or change the default below
usernames['wikipedia']['no'] = os.getenv('MW_BOT_USERNAME', 'IngeniousBot')
usernames['commons']['commons'] = os.getenv('MW_BOT_USERNAME', 'IngeniousBot')

# OAuth 1.0a authentication
# These are loaded from environment variables (set in .env file)
_consumer_token = os.getenv('MW_CONSUMER_TOKEN', '')
_consumer_secret = os.getenv('MW_CONSUMER_SECRET', '')
_access_token = os.getenv('MW_ACCESS_TOKEN', '')
_access_secret = os.getenv('MW_ACCESS_SECRET', '')

if _consumer_token and _consumer_secret and _access_token and _access_secret:
    authenticate['no.wikipedia.org'] = (
        _consumer_token,
        _consumer_secret,
        _access_token,
        _access_secret,
    )
    authenticate['commons.wikimedia.org'] = (
        _consumer_token,
        _consumer_secret,
        _access_token,
        _access_secret,
    )

# Throttle settings
put_throttle = 10
maxlag = 5
max_retries = 3
retry_wait = 10
retry_max = 30

# User agent description
user_agent_description = 'CatWatchBot2.0 (IngeniousBot) - Norwegian Wikipedia maintenance bot'

# Don't ask for confirmation on edits
# (the bot handles dry-run mode via --simulate flag)
simulate = False
