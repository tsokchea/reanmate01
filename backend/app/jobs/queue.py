"""In-process background job queue (server/src/jobs/queue.js).

Runs ingest and generation work off the request thread. Like the Node queue it
is strictly sequential — one job at a time, in arrival order — on a single
daemon worker thread, and it is per process: jobs queued in memory are lost on
restart, which the services already tolerate (a persisted 'generating' cache
row is re-claimed by the next request that asks for it).
"""

import logging
import queue
import threading
import time

log = logging.getLogger("reanmate")

_handlers = {}
_queue = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _run():
    while True:
        job = _queue.get()
        handler = _handlers.get(job["type"])
        if handler is None:
            log.error('[jobs] no handler registered for job type "%s"', job["type"])
            continue
        try:
            handler(job["payload"])
        except Exception:
            log.exception('[jobs] job "%s" failed', job["type"])


def _ensure_worker():
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="reanmate-jobs", daemon=True)
            _worker.start()


def register(job_type, handler):
    _handlers[job_type] = handler


def enqueue(job_type, payload):
    _queue.put({"type": job_type, "payload": payload, "queued_at": time.time()})
    _ensure_worker()


def size():
    return _queue.qsize()
