"""Home Intercom — PWA-based family broadcast system for Home Assistant.

Rooms live on the writable UI config entry (PWA / Options Flow). A leftover
YAML SOURCE_IMPORT entry is imported once into that UI entry and then removed
(issue #75).
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .announce import handle_announce_service
from .api import register_api_views
from .const import AUDIO_SUBDIR, CONF_ANNOUNCE_VOLUME, CONF_PAUSE_BUFFER, CONF_ROOMS, DOMAIN, PLATFORMS, PWA_TOKEN_STORAGE_KEY, PWA_TOKEN_STORAGE_VERSION, SERVICE_ANNOUNCE, WWW_DIR
from .rooms import combined_entry_rooms

_LOGGER = logging.getLogger(__name__)

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ENTITY_ID): cv.string,
        vol.Optional(CONF_ANNOUNCE_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional(CONF_PAUSE_BUFFER): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ROOMS): vol.Schema({cv.string: ROOM_SCHEMA}),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

YAML_UNIQUE_ID = f"{DOMAIN}_yaml"
UI_UNIQUE_ID = DOMAIN


# ═══════════════════════════════════════════════════════════════════════
# YAML → one-time import into the writable UI entry (issue #75)
# ═══════════════════════════════════════════════════════════════════════


def _entry_room_map(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Combined data + options rooms for one config entry (options key order wins)."""
    return combined_entry_rooms(entry)


def merge_incoming_rooms(
    current: dict[str, dict[str, Any]], incoming: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Add YAML keys that are not already on the UI entry. Existing keys win."""
    merged = {key: dict(room) for key, room in current.items()}
    added: list[str] = []
    for key, room in incoming.items():
        if key in merged or not isinstance(room, dict):
            continue
        merged[key] = dict(room)
        added.append(key)
    return merged, added


def _find_ui_entry(entries: list[ConfigEntry]) -> ConfigEntry | None:
    """Find the writable UI config entry."""
    for entry in entries:
        if entry.unique_id == UI_UNIQUE_ID:
            return entry
    return None


def _move_room_devices(hass: HomeAssistant, from_entry_id: str, to_entry_id: str) -> None:
    """Re-home YAML room devices onto the UI entry so HA does not drop them."""
    from homeassistant.helpers import device_registry as dr

    if from_entry_id == to_entry_id:
        return
    registry = dr.async_get(hass)
    for device in list(registry.devices.get_devices_for_config_entry_id(from_entry_id)):
        room_ids = [
            ident
            for domain, ident in device.identifiers
            if domain == DOMAIN
        ]
        if not room_ids:
            continue
        registry.async_update_device(device.id, add_config_entry_id=to_entry_id)
        registry.async_update_device(device.id, remove_config_entry_id=from_entry_id)


async def _import_yaml_rooms(hass: HomeAssistant, config_rooms: dict[str, Any]) -> None:
    """Copy leftover YAML rooms onto the UI entry, then drop the YAML entry."""
    entries = list(hass.config_entries.async_entries(DOMAIN))
    yaml_entry = _find_yaml_entry(entries)
    ui_entry = _find_ui_entry(entries)
    incoming: dict[str, Any] = {}
    if yaml_entry is not None:
        incoming.update(_entry_room_map(yaml_entry))
    incoming.update(config_rooms)
    if not incoming and yaml_entry is None:
        return

    if ui_entry is None:
        # Do not await the flow here: async_setup still holds the setup lock,
        # so creating the entry would deadlock and never call async_setup_entry.
        yaml_entry_id = yaml_entry.entry_id if yaml_entry is not None else None

        async def _finish_import() -> None:
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={CONF_ROOMS: incoming},
            )
            ui = _find_ui_entry(list(hass.config_entries.async_entries(DOMAIN)))
            if yaml_entry_id is None or ui is None:
                return
            _move_room_devices(hass, yaml_entry_id, ui.entry_id)
            await hass.config_entries.async_remove(yaml_entry_id)
            _LOGGER.info("Removed YAML config entry after importing rooms into the PWA catalog")

        hass.async_create_task(_finish_import())
        return

    merged, added = merge_incoming_rooms(_entry_room_map(ui_entry), incoming)
    if added:
        options = dict(ui_entry.options)
        options[CONF_ROOMS] = merged
        hass.config_entries.async_update_entry(ui_entry, options=options)
        _LOGGER.info("Imported YAML rooms into the UI entry: %s", ", ".join(added))

    if yaml_entry is not None:
        _move_room_devices(hass, yaml_entry.entry_id, ui_entry.entry_id)
        await hass.config_entries.async_remove(yaml_entry.entry_id)
        _LOGGER.info("Removed YAML config entry after importing rooms into the PWA catalog")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import deprecated YAML rooms into the writable UI entry."""
    yaml_rooms: dict[str, Any] = {}
    if DOMAIN in config:
        yaml_rooms = dict(config[DOMAIN][CONF_ROOMS])
        _LOGGER.warning(
            "home_intercom YAML is deprecated; rooms are imported into the UI entry. "
            "Add and remove speakers in the PWA, then remove the home_intercom: block "
            "from configuration.yaml"
        )
    await _import_yaml_rooms(hass, yaml_rooms)
    return True


# ═══════════════════════════════════════════════════════════════════════
# Config entry setup — per-entry, merged globally
# ═══════════════════════════════════════════════════════════════════════


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up or update a config entry. Merges all entries' rooms for services."""
    # Rename existing default titles while preserving user-defined names.
    default_titles = {"Home Intercom": "家庭广播", "Home Intercom (YAML)": "家庭广播"}
    if entry.title in default_titles:
        hass.config_entries.async_update_entry(entry, title=default_titles[entry.title])

    # Older installations may still contain an empty legacy entry.
    if entry.unique_id == "home_intercom_buttons":
        return True

    room_map = combined_entry_rooms(entry)

    # Store per-entry rooms
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entry_rooms", {})
    hass.data[DOMAIN]["entry_rooms"][entry.entry_id] = room_map

    # Drop HA devices for rooms no longer on this entry (YAML #63, UI PWA delete).
    _reconcile_room_devices(hass, entry.entry_id, set(room_map.keys()))

    # Full setup with merged rooms from all entries
    await _full_setup(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.unique_id == "home_intercom_buttons":
        return True

    # Room entry (UI): unload platforms so reload can re-forward (#64)
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    if DOMAIN in hass.data:
        hass.data[DOMAIN].setdefault("entry_rooms", {}).pop(entry.entry_id, None)
        remaining = hass.data[DOMAIN].get("entry_rooms", {})
        if not remaining:
            hass.services.async_remove(DOMAIN, SERVICE_ANNOUNCE)
            hass.data.pop(DOMAIN, None)
        else:
            # Other entries still loaded — refresh merged room list only
            all_rooms: dict[str, dict[str, Any]] = {}
            for rooms in remaining.values():
                all_rooms.update(rooms)
            hass.data[DOMAIN]["rooms"] = all_rooms
            _register_services(hass, all_rooms)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Config entry removed — YAML leftovers are already imported into the UI entry."""
    return None


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when Options flow saves changes."""
    await hass.config_entries.async_reload(entry.entry_id)




# ═══════════════════════════════════════════════════════════════════════
# Core setup — merges all entries' rooms
# ═══════════════════════════════════════════════════════════════════════


async def _async_load_pwa_token(hass: HomeAssistant) -> str:
    """Load the PWA shared token from .storage; generate + persist on first run.

    Issue #54: the token previously lived only in hass.data, so every HA
    restart or config-entry reload rotated it — already-open PWA pages then
    got 401 from RecordView until manually refreshed. Persisting it keeps
    existing pages working across restarts.
    """
    store = Store(hass, PWA_TOKEN_STORAGE_VERSION, PWA_TOKEN_STORAGE_KEY)
    data = await store.async_load()
    if isinstance(data, dict) and data.get("token"):
        return data["token"]
    token = secrets.token_urlsafe(32)
    await store.async_save({"token": token})
    _LOGGER.info("Generated new PWA token (first run or storage reset)")
    return token


async def _full_setup(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Full setup: merge all entries, register services + devices."""
    entry_rooms = hass.data.get(DOMAIN, {}).get("entry_rooms", {})
    all_rooms: dict[str, dict[str, Any]] = {}
    for rooms in entry_rooms.values():
        for rid in rooms:
            if rid in all_rooms:
                _LOGGER.warning(
                    "Room key collision: '%s' defined in multiple config entries — "
                    "last entry wins (non-deterministic ordering).",
                    rid,
                )
        all_rooms.update(rooms)

    audio_dir = hass.config.path(WWW_DIR, AUDIO_SUBDIR)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].update(
        {
            "rooms": all_rooms,
            "audio_dir": audio_dir,
        }
    )

    await hass.async_add_executor_job(lambda: os.makedirs(audio_dir, exist_ok=True))
    hass.data[DOMAIN]["pwa_token"] = await _async_load_pwa_token(hass)

    # Initialize error/state tracking
    hass.data[DOMAIN].setdefault("errors", {})
    hass.data[DOMAIN].setdefault("states", {})

    register_api_views(hass)
    _register_services(hass, all_rooms)
    _register_devices(hass, entry.entry_id, entry_rooms.get(entry.entry_id, {}))
    # Forward room diagnostic and volume platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Home Intercom — %d rooms (%d entries), audio: %s",
        len(all_rooms),
        len(entry_rooms),
        audio_dir,
    )


def _register_services(hass: HomeAssistant, room_map: dict[str, Any]) -> None:
    """Register home_intercom.announce with dynamic room list."""

    async def _handle_announce(call: ServiceCall):
        await handle_announce_service(hass, call)

    room_keys = ["all"] + sorted(room_map.keys())
    target_selector = vol.In(room_keys) if room_keys else str
    schema = vol.Schema(
        {
            vol.Required("target", default="all"): target_selector,
            vol.Required("url"): str,
            vol.Optional("volume", default=50): int,
        }
    )

    # Remove old service before re-registering (rooms may have changed)
    if hass.services.has_service(DOMAIN, SERVICE_ANNOUNCE):
        hass.services.async_remove(DOMAIN, SERVICE_ANNOUNCE)
    hass.services.async_register(DOMAIN, SERVICE_ANNOUNCE, _handle_announce, schema=schema)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: Any
) -> bool:
    """Remove a room device from the room configuration."""

    # Find which room this device belongs to
    room_id = None
    for domain, rid in device_entry.identifiers:
        if domain == DOMAIN:
            room_id = rid
            break
    if room_id is None:
        return False

    # Remove room from UI entry's options
    new_options = {**entry.options}
    if room_id in new_options.get(CONF_ROOMS, {}):
        rooms = dict(new_options[CONF_ROOMS])
        rooms.pop(room_id, None)
        new_options[CONF_ROOMS] = rooms
    hass.config_entries.async_update_entry(entry, options=new_options)
    return True


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Get friendly name from entity registry, fall back to entity_id."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is not None:
        return entry.original_name or entity_id
    return entity_id


def _media_player_manufacturer(
    hass: HomeAssistant,
    entity_id: str,
    entity_registry: Any,
    device_registry: Any,
) -> str:
    """Get the manufacturer of the underlying media_player device.

    Follows entity_id → entity entry → device entry → manufacturer.
    Falls back to "Home Intercom" if the chain is broken.
    """
    entry = entity_registry.async_get(entity_id)
    if entry is not None and entry.device_id:
        device = device_registry.async_get(entry.device_id)
        if device is not None and device.manufacturer:
            return device.manufacturer
    return "Home Intercom"








def _register_devices(hass: HomeAssistant, entry_id: str, room_map: dict[str, Any]) -> None:
    """Register devices for ONE config entry. Import is lazy."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)
    entity_registry = er.async_get(hass)

    for room_id, room in room_map.items():
        entity_id = room.get(CONF_ENTITY_ID, "")
        name = room.get(CONF_NAME, room_id)
        if not entity_id:
            continue

        # Copy manufacturer from the underlying media_player device
        manufacturer = _media_player_manufacturer(hass, entity_id, entity_registry, registry)

        device = registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers={(DOMAIN, room_id)},
            name=name,
            manufacturer=manufacturer,
            model=_friendly_name(hass, entity_id),
        )
        if area_registry.async_get_area(room_id) and device.area_id != room_id:
            registry.async_update_device(device.id, area_id=room_id)


def _reconcile_room_devices(
    hass: HomeAssistant,
    entry_id: str,
    current_rooms: set[str],
) -> None:
    """Remove HA devices owned by this entry whose room is gone.

    ``_register_devices`` only calls ``async_get_or_create``. Without this,
    deleting a room (YAML edit or PWA) leaves an empty card in
    Settings → Devices. Called on every setup/reload so cold restarts
    also drop stale entries.
    """
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    for device in list(registry.devices.get_devices_for_config_entry_id(entry_id)):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier not in current_rooms:
                _LOGGER.info(
                    "Removing orphaned device '%s' (room '%s')",
                    device.name or device.id,
                    identifier,
                )
                registry.async_remove_device(device.id)
                break


_reconcile_yaml_devices = _reconcile_room_devices


def _find_yaml_entry(entries: list[ConfigEntry]) -> ConfigEntry | None:
    """Find the YAML (SOURCE_IMPORT) entry among existing entries."""
    for entry in entries:
        if entry.unique_id == YAML_UNIQUE_ID:
            return entry
    return None
