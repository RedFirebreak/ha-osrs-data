DOMAIN = "osrs_data"

EVENT_TYPE = "osrs_data_event"

CONF_TITLE = "title"

# Storage
STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}_store"

# Data key for the per-entry AccountStore kept in hass.data
DATA_ACCOUNT_STORE = "account_store"
DATA_HISTORY_STORE = "history_store"
DATA_DEDUPE_CACHE = "dedupe_cache"
DATA_STORE = "store"
DATA_PAIRING_STORE = "pairing_store"
DATA_EVENT_DEDUPE_CACHE = "event_dedupe_cache"

# Dispatcher signal for account updates
SIGNAL_ACCOUNT_UPDATED = f"{DOMAIN}_account_updated"

# Pairing
PAIRING_CODE_LENGTH = 5
PAIRING_CODE_TTL = 300  # seconds (5 minutes)
DEVICE_TOKEN_LENGTH = 64  # hex characters

# Presence / online detection
PRESENCE_TIMEOUT = 1500  # seconds (25 minutes) — fallback when no tickDelay known
PRESENCE_CHECK_INTERVAL = 5  # seconds between periodic checks

# OSRS game tick duration in seconds
TICK_DURATION = 0.6
# Multiplier applied to tickDelay to compute the per-account timeout
# timeout = floor(tickDelay * TICK_TIMEOUT_MULTIPLIER * TICK_DURATION)
# 3.1x allows ~2 missed messages of grace before marking offline.
TICK_TIMEOUT_MULTIPLIER = 3.1

# ── Configurable options (stored in ConfigEntry.options) ────────────
# Keys and their defaults.  Defaults preserve prior hardcoded behavior,
# so an entry with no options behaves exactly as before.
CONF_DEATH_LIMIT = "death_limit"
CONF_LOOT_LIMIT = "loot_limit"
CONF_DEFAULT_LIMIT = "default_limit"
CONF_DEDUPE_TTL = "dedupe_ttl"
CONF_PRESENCE_TIMEOUT = "presence_timeout"

DEFAULT_DEATH_LIMIT = 50
DEFAULT_LOOT_LIMIT = 100
DEFAULT_HISTORY_LIMIT = 50
DEFAULT_DEDUPE_TTL = 30
