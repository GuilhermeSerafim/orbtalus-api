"""Offline test boundaries, with only Python's internal socketpair permitted.

On Windows asyncio creates a socketpair for its wakeup pipe. Its stdlib fallback
uses one loopback connect to the socket it just created. This exception is scoped
to that exact stdlib function on the current thread; arbitrary loopback, DNS and
HTTP remain forbidden. No server or application port is opened by these tests.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import socket
from unittest.mock import patch


@contextmanager
def offline_boundaries():
    attempts = []
    internal_pair = ContextVar('stdlib_socketpair', default=False)
    original_pair = socket.socketpair
    original_connect = socket.socket.connect

    def forbidden(*args, **kwargs):
        attempts.append('external_io')
        raise AssertionError('External IO forbidden by offline tests')

    def socketpair(*args, **kwargs):
        token = internal_pair.set(True)
        try:
            return original_pair(*args, **kwargs)
        finally:
            internal_pair.reset(token)

    def connect(sock, address):
        if internal_pair.get() and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)
        return forbidden()

    with ExitStack() as stack:
        for target, replacement in (
            ('socket.socketpair', socketpair),
            ('socket.socket.connect', connect),
            ('socket.socket.connect_ex', forbidden),
            ('socket.socket.sendto', forbidden),
            ('socket.create_connection', forbidden),
            ('socket.getaddrinfo', forbidden),
            ('requests.sessions.Session.request', forbidden),
            ('psycopg2.connect', forbidden),
            ('dotenv.load_dotenv', forbidden),
            ('httpx.HTTPTransport.handle_request', forbidden),
            ('httpx.AsyncHTTPTransport.handle_async_request', forbidden),
            ('httpx2.HTTPTransport.handle_request', forbidden),
            ('httpx2.AsyncHTTPTransport.handle_async_request', forbidden),
        ):
            stack.enter_context(patch(target, replacement))
        yield attempts
