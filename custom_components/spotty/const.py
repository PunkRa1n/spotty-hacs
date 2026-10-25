"""Konstanten."""

from datetime import timedelta

DOMAIN = "spotty"

CONF_SOURCE_TYPE = "source_type"
SOURCE_SPOTTY = "spotty"
SOURCE_CUSTOM = "custom"

CONF_TOKEN_HEADER = "token_header"
CONF_DATA_KEY = "data_key"
CONF_TIME_FIELD = "time_field"
CONF_PRICE_FIELD = "price_field"
CONF_PRICE_FACTOR = "price_factor"

CONF_DEVICES = "devices"
CONF_POWER_ENTITY = "power_entity"
CONF_STANDBY_W = "standby_w"
CONF_FINISH_BY = "finish_by"
CONF_TAIL_MIN = "tail_min"

DEFAULT_NAME = "Spotty"
DEFAULT_THRESHOLD_PCT = 25.0
DEFAULT_STANDBY_W = 3.0
DEFAULT_TAIL_MIN = 20
DEFAULT_TOKEN_HEADER = "Authorization"

# Einlernen: so lange auf den Start warten bzw. maximal aufzeichnen
LEARN_WAIT_MAX = timedelta(hours=3)
LEARN_MAX_DURATION = timedelta(hours=8)

STORAGE_VERSION = 1

SPOTTY_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
