"""A job shared by searches never shares authorization for their different areas."""
import copy
import unittest

from app.services.research import automatic_geography_allowed


class GeographicSendBoundary(unittest.TestCase):
    def fixture(self):
        search = {"id": "search-a", "research_mode": "general", "radius_km": 100,
            "cities": ["Rincón de los Sauces"], "province": "Neuquén", "country": "Argentina"}
        job = {"payload": {"geography": {"search_id": "search-a", "radius_km": 100,
            "within_radius": True, "location_verified": True,
            "search_center": {"city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina"}}}}
        return job, search

    def test_same_search_and_verified_area_qualifies(self):
        job, search = self.fixture()
        self.assertTrue(automatic_geography_allowed(job, search))

    def test_another_search_changed_radius_or_unknown_area_cannot_borrow_proof(self):
        for change in ({"search_id": "search-b"}, {"radius_km": 200}, {"within_radius": None},
                {"within_radius": False}, {"location_verified": False},
                {"search_center": {"city": "Otra ciudad", "province": "Neuquén", "country": "Argentina"}},
                {"search_center": {"city": "Rincón de los Sauces", "province": "Mendoza", "country": "Argentina"}}):
            job, search = self.fixture()
            job["payload"]["geography"].update(change)
            self.assertFalse(automatic_geography_allowed(job, search), change)

    def test_missing_proof_cannot_authorize_new_general_search(self):
        _, search = self.fixture()
        self.assertFalse(automatic_geography_allowed({}, search))

    def test_legacy_search_keeps_its_existing_separate_delivery_checks(self):
        self.assertTrue(automatic_geography_allowed({}, {"research_mode": "legacy"}))
