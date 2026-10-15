"""The saved search cannot accept invented coordinates or implicit send rights."""
import unittest

from pydantic import ValidationError

from app.models import SearchProposal
from app.services.schedule import proposal_row


class ResearchProposalTests(unittest.TestCase):
    def test_city_only_clients_get_general_research_without_coordinates(self):
        proposal = SearchProposal(title="Chofer", role="Chofer", city="Rincón de los Sauces")
        row = proposal_row(proposal, "owner")
        self.assertEqual(row["country"], "Argentina")
        self.assertEqual(row["radius_km"], 0)
        self.assertEqual(row["research_mode"], "general")
        self.assertIsNone(row["location"])
        self.assertFalse(row["auto_apply"])

    def test_identity_requires_server_resolution_before_saving_coordinates(self):
        proposal = SearchProposal(title="Chofer", role="Chofer", city="Rincón de los Sauces",
            province=" Neuquén ", country=" Argentina ", radius_km=100, location_id=" geo-provider-id ")
        row = proposal_row(proposal, "owner")
        self.assertEqual(proposal.location_id, "geo-provider-id")
        self.assertEqual(row["province"], "Neuquén")
        self.assertEqual(row["radius_km"], 100)
        self.assertNotIn("location_id", row)
        self.assertIsNone(row["location"])

    def test_radius_must_be_an_integer_in_bounds(self):
        for radius in (-1, 1001, True, "100", 100.0):
            with self.subTest(radius=radius), self.assertRaises(ValidationError):
                SearchProposal(title="Chofer", role="Chofer", city="Neuquén", radius_km=radius)

    def test_client_cannot_supply_coordinates_or_change_research_pipeline(self):
        for extra in ({"latitude": -37}, {"location": {"latitude": -37, "longitude": -68}},
                {"research_mode": "legacy"}, {"auto_apply": True}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                SearchProposal(title="Chofer", role="Chofer", city="Neuquén", **extra)

    def test_required_search_text_cannot_be_blank(self):
        for key in ("title", "role", "city", "country"):
            data = {"title": "Chofer", "role": "Chofer", "city": "Neuquén", key: " "}
            with self.subTest(key=key), self.assertRaises(ValidationError):
                SearchProposal(**data)


if __name__ == "__main__":
    unittest.main()
