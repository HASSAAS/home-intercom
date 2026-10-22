"""Persistent shared announcement presets, separate from room configuration."""
import asyncio
from uuid import uuid4


class PresetConflict(ValueError):
    """Another client has saved a newer revision."""


def apply_change(data, payload):
    if not isinstance(payload, dict):
        raise ValueError("请求格式错误")
    if type(payload.get("revision")) is not int or payload["revision"] != data["revision"]:
        raise PresetConflict("预设已在其他设备更新，请重新选择后再保存")
    items = [dict(item) for item in data["items"]]
    action = payload.get("action")
    preset_id = payload.get("id")
    existing = next((item for item in items if item["id"] == preset_id), None)
    if action == "delete":
        if existing is None:
            raise ValueError("预设不存在，请刷新后重试")
        items.remove(existing)
    elif action == "save":
        name, text = payload.get("name"), payload.get("text")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 30:
            raise ValueError("预设名称需要 1–30 字")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            raise ValueError("预设内容需要 1–500 字")
        if preset_id is not None and existing is None:
            raise ValueError("预设不存在，请刷新后重试")
        if existing:
            existing.update(name=name.strip(), text=text.strip())
        else:
            if len(items) >= 30:
                raise ValueError("最多保存 30 条预设")
            items.append({"id": uuid4().hex, "name": name.strip(), "text": text.strip()})
    else:
        raise ValueError("不支持的操作")
    return {"revision": data["revision"] + 1, "items": items}


async def preset_request(hass, payload=None):
    from homeassistant.helpers.storage import Store

    state = hass.data.setdefault("home_intercom", {})
    lock = state.setdefault("preset_lock", asyncio.Lock())
    async with lock:
        store = state.setdefault("preset_store", Store(hass, 1, "home_intercom.text_presets"))
        if "text_presets" not in state:
            loaded = await store.async_load()
            initial = loaded or {"revision": 0, "items": [
                {"id": "meal", "name": "吃饭提醒", "text": "饭做好了，请大家来吃饭。"},
                {"id": "rest", "name": "休息提醒", "text": "时间不早了，请早点休息。"},
                {"id": "delivery", "name": "取件提醒", "text": "有快递到了，请记得取件。"},
            ]}
            if loaded is None:
                await store.async_save(initial)
            state["text_presets"] = initial
        if payload is not None:
            updated = apply_change(state["text_presets"], payload)
            await store.async_save(updated)
            state["text_presets"] = updated
        return state["text_presets"]
