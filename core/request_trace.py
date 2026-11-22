"""Request-scoped observations shared with FastAPI's synchronous worker threads."""
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
import json
import logging
from time import monotonic
from uuid import uuid4

from starlette.datastructures import MutableHeaders

from core.errors import MESSAGES


HEADER = 'X-Request-ID'
logger = logging.getLogger('uvicorn.error')
current_trace = ContextVar('geo_request_trace', default=None)


@dataclass
class RequestTrace:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    origin: str = 'not_reached'
    failure_stage: str | None = None
    failure_code: str | None = None


def record_failure(code):
    trace = current_trace.get()
    if trace is None or not isinstance(code, str):
        return
    if code in MESSAGES or code in ('DEMO_DAILY_LIMIT', 'DEMO_IP_LIMIT'):
        trace.failure_code = code
        if trace.failure_stage is None:
            trace.failure_stage = {
                'INPUT_INVALID': 'validation', 'DEMO_UNAVAILABLE': 'admission',
                'DEMO_DAILY_LIMIT': 'admission', 'DEMO_IP_LIMIT': 'admission',
                'HYDROLOGY_UNAVAILABLE': 'hydrology', 'HYDROLOGY_LOOKUP_FAILED': 'hydrology',
                'HYDROLOGY_NO_WATERWAY': 'hydrology',
                'DATABASE_UNAVAILABLE': 'database', 'AI_UNAVAILABLE': 'ai',
                'DATA_UNAVAILABLE': 'data', 'CONFIG_UNAVAILABLE': 'configuration',
            }.get(code)


class RequestTraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or scope['method'] != 'POST'
                or scope['path'] not in ('/geo/risk', '/geo/hydrology')):
            return await self.app(scope, receive, send)

        trace = RequestTrace()
        token = current_trace.set(trace)
        started = monotonic()
        status = None
        finished = False

        async def send_traced(message):
            nonlocal status, finished
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message)[HEADER] = trace.request_id
                status = message['status']
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body'):
                finished = True

        try:
            await self.app(scope, receive, send_traced)
        finally:
            current_trace.reset(token)
            event = dict(asdict(trace), path=scope['path'], status=status if finished else None,
                         duration_ms=round((monotonic() - started) * 1000, 3))
            logger.info('Geo request %s', json.dumps(event))
