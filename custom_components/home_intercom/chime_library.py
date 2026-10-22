"""Built-in chimes selected through the existing persistent active WAV."""
from pathlib import Path
import hashlib
import os
from uuid import uuid4

CHIMES = {
    "classic": ("经典提示", "pre_announce.wav", "原版广播提示音"),
    "gentle": ("轻柔双音", "chime-gentle.wav", "柔和轻响，适合日常提醒"),
    "doorbell": ("清脆叮咚", "chime-doorbell.wav", "清晰醒目，适合呼叫与取件"),
    "melody": ("温暖旋律", "chime-melody.wav", "短小旋律，适合家庭广播"),
}


def library_status(integration_dir, audio_dir):
    audio = Path(audio_dir)
    active = audio / "custom_chime.wav"
    current = active.read_bytes() if active.is_file() else (integration_dir / "static/pre_announce.wav").read_bytes()
    digest = hashlib.sha256(current).digest()
    selected = "custom"
    items = []
    for key, (name, filename, description) in CHIMES.items():
        content = (integration_dir / "static" / filename).read_bytes()
        if hashlib.sha256(content).digest() == digest:
            selected = key
        items.append({"id": key, "name": name, "description": description,
                      "url": f"/home-intercom/static/{filename}"})
    if selected == "custom" or (audio / "user_chime.wav").is_file():
        items.append({"id": "custom", "name": "自定义提示音", "description": "管理员上传的提示音",
                      "url": "/local/home_intercom_audio/" + ("custom_chime.wav" if selected == "custom" else "user_chime.wav")})
    return {"selected": selected, "items": items}


def select_chime(integration_dir, audio_dir, key):
    if not isinstance(key, str) or key not in {*CHIMES, "custom"}:
        raise ValueError("请选择有效的提示音")
    audio = Path(audio_dir)
    status = library_status(integration_dir, audio_dir)
    active = audio / "custom_chime.wav"
    saved = audio / "user_chime.wav"
    if key == "custom":
        source = active if status["selected"] == "custom" else saved
        if not source.is_file():
            raise ValueError("尚未上传自定义提示音")
    else:
        source = integration_dir / "static" / CHIMES[key][1]
    content = source.read_bytes()
    if status["selected"] == "custom" and active.is_file():
        saved.write_bytes(active.read_bytes())
    audio.mkdir(parents=True, exist_ok=True)
    temporary = audio / f".chime-{uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.replace(temporary, active)
    finally:
        temporary.unlink(missing_ok=True)
    return library_status(integration_dir, audio_dir)
