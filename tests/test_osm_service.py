import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.osm_service import OSMService


class OSMServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = OSMService()
        self.service.api = MagicMock()

    def test_skips_fetch_when_area_is_already_mapped(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 6

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        self.service.api.query.assert_not_called()
        session.commit.assert_not_called()
        session.close.assert_called_once()

    def test_sanitizes_osm_text_fields_before_commit(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        self.service.api.query.return_value = SimpleNamespace(
            relations=[],
            ways=[
                SimpleNamespace(
                    id=123,
                    tags={"name": "Rio\x00Teste", "waterway": "river\x1f"},
                    nodes=[
                        SimpleNamespace(lon=-46.0, lat=-23.0),
                        SimpleNamespace(lon=-46.1, lat=-23.1),
                    ],
                )
            ],
        )

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        rivers = session.add_all.call_args[0][0]
        self.assertEqual(len(rivers), 1)
        self.assertEqual(rivers[0].name, "RioTeste")
        self.assertEqual(rivers[0].type, "river")
        session.commit.assert_called_once()
        session.close.assert_called_once()

    def test_rolls_back_when_commit_fails(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        session.commit.side_effect = ValueError(
            "A string literal cannot contain NUL (0x00) characters."
        )
        self.service.api.query.return_value = SimpleNamespace(
            relations=[],
            ways=[
                SimpleNamespace(
                    id=456,
                    tags={"name": "Rio Teste", "waterway": "river"},
                    nodes=[
                        SimpleNamespace(lon=-46.0, lat=-23.0),
                        SimpleNamespace(lon=-46.1, lat=-23.1),
                    ],
                )
            ],
        )

        with patch("services.osm_service.SessionLocal", return_value=session):
            self.service.fetch_and_save_rivers(-23.0, -46.0)

        session.rollback.assert_called_once()
        session.close.assert_called_once()
