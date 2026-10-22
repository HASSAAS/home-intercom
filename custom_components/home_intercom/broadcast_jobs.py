"""Run broadcasts independently of reverse-proxy HTTP request timeouts."""
import asyncio
import logging
import time
from uuid import uuid4

_LOGGER = logging.getLogger(__name__)


def start_broadcast_job(hass, work):
    jobs = hass.data.setdefault("home_intercom", {}).setdefault("text_jobs", {})
    now = time.monotonic()
    for key, job in list(jobs.items()):
        if job["status"] == "done" and now - job["created"] > 600:
            jobs.pop(key)
    if sum(job["status"] == "running" for job in jobs.values()) >= 5:
        return {"ok": False, "error": "已有播报正在处理中，请稍候再试"}, 429
    completed = sorted((key for key in jobs if jobs[key]["status"] == "done"), key=lambda key: jobs[key]["created"])
    for key in completed[:max(0, len(jobs) - 19)]:
        jobs.pop(key)
    job_id = uuid4().hex
    job = jobs[job_id] = {"status": "running", "created": now}

    async def run():
        try:
            async with asyncio.timeout(120):
                response, _status = await work()
            job["result"] = response
        except TimeoutError:
            job["result"] = {"ok": False, "error": "音箱响应超时，请先确认是否已播报，避免重复发送"}
        except asyncio.CancelledError:
            job["result"] = {"ok": False, "error": "播报任务已中断"}
            raise
        except Exception:
            _LOGGER.error("Background text broadcast failed")
            job["result"] = {"ok": False, "error": "播报执行失败，请检查音箱连接"}
        finally:
            job["status"] = "done"

    hass.async_create_background_task(run(), f"home_intercom_text_{job_id}")
    return {"ok": True, "job_id": job_id, "status": "running"}, 202


def broadcast_job_status(hass, job_id):
    job = hass.data.get("home_intercom", {}).get("text_jobs", {}).get(job_id)
    if job is None:
        return {"error": "播报任务记录已失效，请先确认音箱是否已播报，避免重复发送"}, 404
    return {"job_id": job_id, "status": job["status"], "result": job.get("result")}, 200
