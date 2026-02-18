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
