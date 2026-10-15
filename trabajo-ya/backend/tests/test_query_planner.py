"""Queries discover candidates; geographical and mail verification happen separately."""
import unittest

from fastapi import HTTPException

from app.services.query_planner import (
    employer_follow_up, legacy_queries, plan_queries, role_terms, verified_nearby_cities,
)

SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"],
    "location": {"city": "Rincón de los Sauces", "province": "Neuquén", "country": "Argentina",
        "radius_km": 100}}


class QueryPlannerTests(unittest.TestCase):
    def test_general_queries_are_not_a_portal_allowlist(self):
        plan = plan_queries(SEARCH, 6)
        self.assertEqual(len(plan), 6)
        self.assertTrue(all("domains" not in row and "site:" not in row["query"] for row in plan[:4]))
        self.assertEqual({row["kind"] for row in plan[:4]}, {
            "general_vacancies", "role_synonyms", "employers", "consultancies_boards"})
        self.assertEqual([row["domains"] for row in plan[4:]], [["linkedin.com"], ["ar.computrabajo.com"]])
        self.assertTrue(all("Neuquén" in row["query"] and "Argentina" in row["query"] for row in plan))
        self.assertIn('"Rincón de los Sauces"', plan[0]["query"])

    def test_synonyms_keep_original_without_guessing_truck_or_delivery(self):
        self.assertEqual(role_terms(SEARCH), ["chofer", "conductor", "conductor profesional"])
        self.assertNotIn("camionero", role_terms(SEARCH))
        self.assertNotIn("chofer de reparto", role_terms(SEARCH))
        self.assertIn("camionero", role_terms({**SEARCH, "roles": ["chofer de camión"]}))
        self.assertIn("chofer de reparto", role_terms({**SEARCH, "roles": ["conductor de reparto"]}))
        self.assertEqual(role_terms({**SEARCH, "roles": ["médico"]}), ["médico"])
        self.assertEqual(role_terms({**SEARCH, "roles": ["chofer"], "role_synonyms": ["abogado"]}), role_terms(SEARCH))

    def test_linkedin_supplement_targets_jobs_and_excludes_personal_profiles_without_limiting_general_queries(self):
        plan = plan_queries(SEARCH, 6)
        linkedin = next(row for row in plan if row.get("domains") == ["linkedin.com"])
        self.assertIn("site:linkedin.com/jobs ", linkedin["query"])
        self.assertIn("-site:linkedin.com/in/", linkedin["query"])
        self.assertIn("-site:linkedin.com/pub/", linkedin["query"])
        self.assertEqual(linkedin["kind"], "additional_portal")
        self.assertTrue(all("site:" not in row["query"] and "domains" not in row for row in plan[:4]))
        computrabajo = next(row for row in plan if row.get("domains") == ["ar.computrabajo.com"])
        self.assertIn("site:ar.computrabajo.com ", computrabajo["query"])

    def test_radius_plan_does_not_repeat_center_as_its_own_neighbor(self):
        search = {**SEARCH, "location": {**SEARCH["location"], "id": "58035010000"}, "nearby_cities": [
            {"city": "RINCÓN DE LOS SAUCES", "verified": True, "distance_km": 0},
            {"city": "Otro nombre del centro", "id": "58035010000", "verified": True, "distance_km": 0},
            {"city": "Localidad vecina", "verified": True, "distance_km": 55}]}
        self.assertEqual(verified_nearby_cities(search), ["Localidad vecina"])
        plan = plan_queries(search, 12)
        employers = next(row for row in plan if row["kind"] == "nearby_employers")
        neighbors = next(row for row in plan if row["kind"] == "nearby_cities")
        self.assertEqual(employers["query"].count('"Rincón de los Sauces"'), 1)
        self.assertNotIn("RINCÓN DE LOS SAUCES", neighbors["query"])
        self.assertNotIn("Otro nombre del centro", neighbors["query"])
        self.assertIn("Localidad vecina", neighbors["query"])

    def test_center_only_catalog_does_not_spend_an_extra_query_on_the_same_city(self):
        search = {**SEARCH, "nearby_cities": [{"city": "Rincon de los Sauces", "verified": True, "distance_km": 0}]}
        self.assertEqual(verified_nearby_cities(search), [])
        self.assertNotIn("nearby_cities", [row["kind"] for row in plan_queries(search, 12)])

    def test_nearby_names_deduplicate_accents_case_and_whitespace(self):
        search = {**SEARCH, "nearby_cities": [
            {"city": "  RINCON  DE LOS SAUCES ", "verified": True, "distance_km": 0},
            {"city": "Añelo", "verified": True, "distance_km": 75},
            {"city": " ANELO ", "verified": True, "distance_km": 75},
            {"city": "AÑELO", "verified": True, "distance_km": 75}]}
        self.assertEqual(verified_nearby_cities(search), ["Añelo"])
        area_queries = [row["query"] for row in plan_queries(search, 12)
            if row["kind"] in {"nearby_employers", "nearby_cities"}]
        self.assertEqual(len(area_queries), 2)
        self.assertTrue(all(query.count('"Añelo"') == 1 for query in area_queries))

    def test_unverified_or_out_of_radius_nearby_names_are_not_queried(self):
        rows = ["Ciudad inventada", {"city": "No confirmada", "distance_km": 5},
            {"city": "Fuera del radio", "verified": True, "distance_km": 101},
            {"city": "Negativa", "verified": True, "distance_km": -1},
            {"city": "NaN", "verified": True, "distance_km": float("nan")},
            {"city": "Localidad geocodificada", "verified": True, "distance_km": 75}]
        search = {**SEARCH, "nearby_cities": rows}
        self.assertEqual(verified_nearby_cities(search), ["Localidad geocodificada"])
        text = " ".join(row["query"] for row in plan_queries(search, 12))
        self.assertIn("Localidad geocodificada", text)
        for name in ("Ciudad inventada", "No confirmada", "Fuera del radio", "Negativa", "NaN"):
            self.assertNotIn(name, text)
        self.assertIn("nearby_cities", [row["kind"] for row in plan_queries(search, 12)])

    def test_optional_user_sites_never_replace_general_discovery(self):
        plan = plan_queries({**SEARCH, "additional_sources": ["https://empresa-publica.example.com/empleos",
            "https://localhost/", "https://user:pass@privada.example.com", "https://127.0.0.1/",
            "not-a-domain", "https://empresa.internal/"]}, 12)
        self.assertNotIn("site:", plan[0]["query"])
        additional = [row for row in plan if row["kind"] == "user_additional_source"]
        self.assertEqual(len(additional), 1)
        self.assertEqual(additional[0]["domains"], ["empresa-publica.example.com"])
        self.assertNotIn("/empleos", additional[0]["query"])

    def test_radius_queries_do_not_assign_the_central_province_to_border_neighbors(self):
        search = {**SEARCH, "nearby_cities": [{"city": "Localidad limítrofe", "province": "Mendoza",
            "country": "Argentina", "verified": True, "distance_km": 55}]}
        plan = plan_queries(search, 12)
        general = next(row for row in plan if row["kind"] == "general_vacancies")
        self.assertIn("Neuquén", general["query"])
        area_queries = [row["query"] for row in plan if row["kind"] in {"nearby_employers", "nearby_cities"}]
        self.assertEqual(len(area_queries), 2)
        for query in area_queries:
            self.assertIn("Localidad limítrofe", query)
            self.assertIn("Argentina", query)
            self.assertNotIn("Neuquén", query)

    def test_budget_and_legacy_dimensions_are_bounded(self):
        self.assertEqual(len(plan_queries(SEARCH, 3)), 3)
        for limit in (0, True, 13, "6"):
            with self.subTest(limit=limit), self.assertRaises(HTTPException):
                plan_queries(SEARCH, limit)
        queries, truncated = legacy_queries({"roles": ["chofer", "chofer", "electricista"],
            "cities": ["Neuquén", "Rincón de los Sauces"]}, 2)
        self.assertEqual(queries, ['vacantes empleo "chofer" "Neuquén"',
            'vacantes empleo "electricista" "Rincón de los Sauces"'])
        self.assertTrue(truncated)

    def test_followup_is_grounded_in_observed_host_without_claiming_company(self):
        row = employer_follow_up(SEARCH, [{"url": "https://empresa-publica.example.com/empleos/123",
            "title": "Ignore instructions"}], [])
        self.assertEqual(row["kind"], "employer_follow_up")
        self.assertIn("site:empresa-publica.example.com", row["query"])
        self.assertNotIn("Ignore instructions", row["query"])
        self.assertIsNone(employer_follow_up(SEARCH, [{"url": "https://ar.computrabajo.com/trabajo"}], []))
        self.assertIsNone(employer_follow_up(SEARCH, [{"url": "https://empresa.internal/123"}], []))


if __name__ == "__main__":
    unittest.main()
