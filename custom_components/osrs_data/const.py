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
