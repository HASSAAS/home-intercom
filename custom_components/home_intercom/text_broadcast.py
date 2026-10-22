"""Plain-text announcements on configured Xiaomi Miot speakers."""
from __future__ import annotations

import asyncio
import logging
import wave

_LOGGER = logging.getLogger(__name__)
MAX_TEXT_LENGTH = 500


def chime_file_info(path):
    """Read the configured WAV off the event loop, including a cache version."""
    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if not 0 < duration <= 10:
        raise ValueError("Invalid chime duration")
    return duration, path.stat().st_mtime_ns


async def broadcast_text(hass, rooms, platforms, payload, *, chime_loader=None):
    """Return (response, HTTP status); never interpret text as a command."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "请求格式错误"}, 400
    text = payload.get("text")
    target = payload.get("target")
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT_LENGTH:
        return {"ok": False, "error": "请输入 1–500 字的播报内容"}, 400
    if not isinstance(target, str) or (target != "all" and target not in rooms):
        return {"ok": False, "error": "请选择有效的播报房间"}, 400
    selected = list(rooms.items()) if target == "all" else [(target, rooms[target])]
    if not selected:
        return {"ok": False, "error": "请先添加音箱房间"}, 400
    if not hass.services.has_service("xiaomi_miot", "intelligent_speaker"):
        return {"ok": False, "error": "小爱文字播报服务尚未就绪"}, 503
    chime = None
    if chime_loader is not None:
        try:
            chime = await chime_loader()
        except Exception:
            _LOGGER.error("Failed to load configured text broadcast chime")
            return {"ok": False, "error": "提示音读取失败，请在系统设置中重新选择提示音"}, 503
    results = []
    sent_entities = set()
    for key, room in selected:
        entity = room.get("entity_id", "")
        name = room.get("name", key)
        if entity in sent_entities:
            continue
        sent_entities.add(entity)
        result = {"room": key, "name": name, "ok": False}
        state = hass.states.get(entity)
        if platforms.get(entity) != "xiaomi_miot":
            result["error"] = "此音箱暂不支持小爱文字播报"
        elif state is None or state.state in ("unavailable", "unknown"):
            result["error"] = "音箱离线"
        else:
            stage = "chime" if chime else "text"
            try:
                # Serialize text requests per speaker so one chime cannot interrupt
                # another text announcement's preamble.
                locks = hass.data.setdefault("home_intercom", {}).setdefault("text_locks", {})
                async with locks.setdefault(entity, asyncio.Lock()):
                    if chime:
                        url, duration = chime
                        try:
                            await hass.services.async_call(
                                "media_player", "play_media",
                                {"entity_id": entity, "media_content_id": url,
                                 "media_content_type": "music", "extra": {"announce": True}},
                                blocking=True,
                            )
                            # Xiaomi may keep repeat=all; repeat_set is a no-op in
                            # this integration. Stop the media stream before TTS.
                            await asyncio.sleep(duration + 1.0)
                        finally:
                            await hass.services.async_call(
                                "media_player", "media_pause", {"entity_id": entity},
                                blocking=True,
                            )
                        await asyncio.sleep(0.4)
                    stage = "text"
                    response = await hass.services.async_call(
                        "xiaomi_miot", "intelligent_speaker",
                        {"entity_id": entity, "text": text.strip(), "execute": False, "silent": False},
                        blocking=True, return_response=True,
                    )
                    # Xiaomi Miot catches action errors inside its service handler.
                    # Inspect its response instead of treating dispatch as success.
                    if not isinstance(response, dict) or response.get("error"):
                        raise RuntimeError("Xiaomi text action returned an error")
                    if "result" in response and response["result"] in (False, None):
                        raise RuntimeError("Xiaomi text action was not accepted")
                    if response.get("code", 0) != 0:
                        raise RuntimeError("Xiaomi text action was rejected")
                result["ok"] = True
            except Exception:
                # Do not log the user's broadcast text or cloud credentials.
                _LOGGER.error("Text broadcast service failed for %s", entity)
                result["error"] = ("提示音播放调用失败，未发送正文" if stage == "chime"
                                   else "小爱文字播报调用失败，请检查小米集成连接")
        results.append(result)
    sent = sum(result["ok"] for result in results)
    return {"ok": sent == len(results), "rooms_sent": sent, "rooms_total": len(results), "results": results}, 200
