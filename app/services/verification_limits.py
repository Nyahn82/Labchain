"""Bounded per-process admission for the single-process public verifier."""
from collections import deque
from threading import BoundedSemaphore, Lock
from time import monotonic
from fastapi import HTTPException
from app.config import settings

lock = Lock()
requests = {}
global_requests = deque()
slots = BoundedSemaphore(2)


def admit(ip):
    now = monotonic()
    with lock:
        for key in list(requests):
            if not requests[key] or requests[key][-1] <= now - 60:
                del requests[key]
        while global_requests and global_requests[0] <= now - 60:
            global_requests.popleft()
        queue = requests.get(ip, deque())
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if len(queue) >= settings.verification_requests_per_minute or len(global_requests) >= 60 or (ip not in requests and len(requests) >= 4096):
            raise HTTPException(429, 'Verification rate limit reached. Try again later.', headers={'Retry-After': '60'})
        queue.append(now); requests[ip] = queue; global_requests.append(now)
    if not slots.acquire(blocking=False):
        raise HTTPException(503, 'Verification is busy. Try again later.', headers={'Retry-After': '5'})
