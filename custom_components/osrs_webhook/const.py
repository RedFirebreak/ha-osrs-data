DOMAIN = "osrs_webhook"

EVENT_TYPE = "osrs_webhook_event"

CONF_WEBHOOK_ID = "webhook_id"
CONF_TITLE = "title"

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_store"

# Data key for the per-entry AccountStore kept in hass.data
DATA_ACCOUNT_STORE = "account_store"

# Dispatcher signal for account updates
SIGNAL_ACCOUNT_UPDATED = f"{DOMAIN}_account_updated"
