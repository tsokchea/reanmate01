"""In-process background job queue (server/src/jobs/queue.js).

Runs ingest and generation work off the request thread on a pool of
JOB_WORKERS daemon threads, taken in arrival order. The Node queue ran one job
at a time; with AI calls taking tens of seconds that left one student's upload
waiting behind another's, so jobs now run side by side. Every handler already
claims its row in the database before working, so two jobs for the same row
never both generate.

The queue is per process: jobs queued in memory are lost on restart, which the
services already tolerate (a persisted 'generating' cache row is re-claimed by
the next request that asks for it).
"""

import logging
import queue
import threading
import time

from ..config import config

log = logging.getLogger("reanmate")

_handlers = {}
_queue = queue.Queue()
_workers = []
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
    with _worker_lock:
        _workers[:] = [worker for worker in _workers if worker.is_alive()]
        while len(_workers) < config.JOB_WORKERS:
            worker = threading.Thread(target=_run, name=f"reanmate-jobs-{len(_workers) + 1}", daemon=True)
            worker.start()
            _workers.append(worker)


def register(job_type, handler):
    _handlers[job_type] = handler


def enqueue(job_type, payload):
    _queue.put({"type": job_type, "payload": payload, "queued_at": time.time()})
    _ensure_worker()


def size():
    return _queue.qsize()
