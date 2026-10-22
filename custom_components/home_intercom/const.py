"""Constants for the Home Intercom custom component."""

DOMAIN = "home_intercom"

# ——— Audio constants ———
PCM_RATE = 16000  # target sample rate (Hz)
PCM_BPS = 2  # 16-bit audio = 2 bytes per sample
WAV_MAGIC = b"RIFF"
WAV_HEADER_SIZE = 44  # RIFF(12) + fmt(24) + data(8)

# ——— Config keys ———
CONF_ROOMS = "rooms"
CONF_AREA_ID = "area_id"
CONF_ANNOUNCE_VOLUME = "announce_volume"
CONF_PAUSE_BUFFER = "pause_buffer"

# ——— Service names ———
SERVICE_ANNOUNCE = "announce"

# ——— Defaults ———
AUDIO_SUBDIR = "home_intercom_audio"
WWW_DIR = "www"

# ——— Config entry ———
PLATFORMS: list[str] = ["number", "sensor", "binary_sensor"]
YAML_UNIQUE_ID = f"{DOMAIN}_yaml"
UI_UNIQUE_ID = DOMAIN
# ——— PWA shared token (issue #54) ———
PWA_TOKEN_STORAGE_KEY = f"{DOMAIN}.pwa_token"  # HA .storage key
PWA_TOKEN_STORAGE_VERSION = 1

# ——— Custom chime (issue #66) ———
CUSTOM_CHIME_FILENAME = "custom_chime.wav"
MAX_CHIME_BYTES = 2 * 1024 * 1024  # 2 MB upload cap

# ——— HA panel URLs ———
# Legacy underscore path still works; hyphen path satisfies HA sidebar/dashboard rules.
PANEL_PATH_LEGACY = "/home_intercom"
PANEL_PATH = "/home-intercom"
DEFAULT_CHIME_STATIC_URL = f"{PANEL_PATH}/static/pre_announce.wav"
