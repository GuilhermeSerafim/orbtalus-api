import socket
import unittest

from offline_guard import offline_boundaries


class OfflineGuardTests(unittest.TestCase):
    def test_external_and_arbitrary_loopback_connections_are_blocked(self):
        with offline_boundaries() as attempts:
            for address in (("192.0.2.1", 443), ("127.0.0.1", 5432)):
                with socket.socket() as sock, self.assertRaises(AssertionError):
                    sock.connect(address)
            with self.assertRaises(AssertionError):
                socket.getaddrinfo("example.invalid", 443)
            with self.assertRaises(AssertionError):
                socket.create_connection(("127.0.0.1", 8080))
            self.assertEqual(len(attempts), 4)

    def test_only_stdlib_socketpair_can_create_internal_wakeup_channel(self):
        with offline_boundaries() as attempts:
            left, right = socket.socketpair()
            try:
                left.send(b"x")
                self.assertEqual(right.recv(1), b"x")
            finally:
                left.close()
                right.close()
            self.assertEqual(attempts, [])
