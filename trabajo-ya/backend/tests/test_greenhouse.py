"""Official-API recipient evidence tests; fixtures never send mail or call providers."""
import copy
import unittest

import httpx
from fastapi import HTTPException

from app.services.greenhouse import (
    API_BASE, MAX_RESPONSE_BYTES, SOURCE_ID, revalidate_job, verify_discoveries,
)

URL = "https://job-boards.greenhouse.io/transporte/jobs/123"
ENDPOINT = f"{API_BASE}/transporte/jobs/123"
SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"]}
QUOTE = "Para el puesto de Chofer en Rincón de los Sauces, enviá tu CV a empleos@empresa.example.com."


def publication(**changes):
    return {"id": 123, "internal_job_id": 567, "title": "Chofer profesional",
        "company_name": "Transportes Ejemplo", "location": {"name": "Rincón de los Sauces"},
        "content": f"<p>Buscamos chofer profesional.</p><p>{QUOTE}</p>", **changes}


async def verify(raw=None, url=URL, search=None):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=publication() if raw is None else raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, failures = await verify_discoveries(client, [{"url": url, "content": "UNTRUSTED PRIVATE DISCOVERY"}], search or SEARCH)
    return jobs, failures, requests


class GreenhouseTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_api_instruction_is_attested_with_exact_evidence(self):
        jobs, failures, requests = await verify()
        self.assertEqual(failures, [])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertTrue(job["recipient_verified"])
        self.assertEqual(job["id"], "transporte:123")
        self.assertEqual(job["recipient_email"], "empleos@empresa.example.com")
        self.assertEqual(job["company"], "Transportes Ejemplo")
        self.assertEqual(job["url"], URL)
        proof = job["payload"]["greenhouse"]
        self.assertEqual(job["payload"]["integration_id"], SOURCE_ID)
        self.assertEqual(proof["email_quote"], QUOTE)
        self.assertEqual(proof["job_id"], 123)
        self.assertEqual(proof["board"], "transporte")
        self.assertEqual(proof["endpoint"], ENDPOINT)
        self.assertRegex(proof["fetched_at"], r"T.*\+00:00$")
        self.assertNotIn("PRIVATE", str(job))
        self.assertEqual(str(requests[0].url), ENDPOINT)
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].headers["Accept"], "application/json")

    async def test_board_name_is_fetched_instead_of_inferred_from_slug(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, json={"name": "Nombre oficial distinto"} if request.url.path.endswith("/transporte")
                else publication(company_name=None))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            jobs, failures = await verify_discoveries(client, [{"url": URL}], SEARCH)
        self.assertEqual(jobs[0]["company"], "Nombre oficial distinto")
        self.assertEqual(requests, [ENDPOINT, f"{API_BASE}/transporte"])

    async def test_missing_company_name_and_board_name_are_manual(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={} if request.url.path.endswith("/transporte") else publication(company_name=None)))) as client:
            jobs, failures = await verify_discoveries(client, [{"url": URL}], SEARCH)
        self.assertEqual(jobs, [])

    async def test_legacy_host_tracking_is_removed_and_duplicates_are_bounded(self):
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json=publication()))) as client:
            jobs, failures = await verify_discoveries(client, [{"url": "https://boards.greenhouse.io/transporte/jobs/123/?gh_src=example"}] * 20, SEARCH)
        self.assertEqual(len(requests), 1)
        self.assertEqual(jobs[0]["url"], "https://boards.greenhouse.io/transporte/jobs/123")

    async def test_arbitrary_evil_private_and_encoded_urls_never_make_requests(self):
        urls = ["http://boards.greenhouse.io/transporte/jobs/123", "https://boards.greenhouse.io.evil.test/transporte/jobs/123",
            "https://user:pass@boards.greenhouse.io/transporte/jobs/123", "https://127.0.0.1/transporte/jobs/123",
            "https://boards.greenhouse.io:443/transporte/jobs/123", "https://boards.greenhouse.io/transporte/../jobs/123",
            "https://boards.greenhouse.io/%2e%2e/jobs/123", "https://boards.greenhouse.io/trans%2Fporte/jobs/123",
            "https://boards.greenhouse.io/transporte/jobs/0", "https://boards.greenhouse.io/transporte/jobs/123#token",
            "https://boards.greenhouse.io/transporte/jobs/123?url=https://127.0.0.1", "https://boards.greenhouse.io/embed/job_app?for=transporte&token=123"]
        for url in urls:
            with self.subTest(url=url):
                jobs, failures, requests = await verify(url=url)
                self.assertEqual((jobs, failures, requests), ([], [], []))

    async def test_discovery_email_and_flags_never_authorize_api_without_instruction(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=publication(content="<p>Vacante de chofer. Aplicá en línea.</p>")))) as client:
            jobs, failures = await verify_discoveries(client, [{"url": URL, "recipient_email": "inventado@example.com",
                "recipient_verified": True, "content": QUOTE}], SEARCH)
        self.assertEqual(jobs, [])

    async def test_noemail_vague_contact_policy_footer_and_ambiguous_addresses_stay_manual(self):
        content = ["Buscamos chofer.", "Contacto: empleos@empresa.example.com.",
            "Application contact information: email empleos@empresa.example.com.",
            "Send your resume for accessibility support to access@empresa.example.com.",
            "Please send your CV to support@empresa.example.com.",
            "For questions about your application, email employ@empresa.example.com.",
            "No envíes tu CV a empleos@empresa.example.com.",
            "Send your CV to empleos@empresa.example.com or alternate@empresa.example.com.",
            "Apply online using the application portal. Send your CV to empleos@empresa.example.com.",
            "<p>Send your CV to empleos@empresa.example.com.</p><p>Send your resume to other@empresa.example.com.</p>",
            "<script>Send your CV to empleos@empresa.example.com.</script>",
            "<footer>Send your CV to empleos@empresa.example.com.</footer>",
            "Send your resume through LinkedIn. Company directory: jobs@empresa.example.com.",
            "Send your resume through LinkedIn; jobs@empresa.example.com.",
            "You do not need to send your resume. jobs@empresa.example.com.",
            "You do not need to send your resume to jobs@empresa.example.com.",
            "No hace falta enviar tu CV a empleos@empresa.example.com.",
            "No se permite enviar tu CV a empleos@empresa.example.com.",
            "Do not submit your application to jobs@empresa.example.com.",
            "Never email your resume to jobs@empresa.example.com.",
            "No manden su CV a empleos@empresa.example.com.",
            "You shouldn’t send your resume to jobs@empresa.example.com.",
            "Evitar enviar CV a empleos@empresa.example.com.",
            "No aplicar por correo a jobs@empresa.example.com.",
            "No postular por correo a jobs@empresa.example.com.",
            "Enviar CV a jobs@empresa.example.com está prohibido.",
            "Send your CV to jobs@empresa.example.com is not permitted.",
            "Send no CV to jobs@empresa.example.com.",
            "Enviar ningún CV a jobs@empresa.example.com.",
            f"<p>{QUOTE}</p><p>We do not accept applications by email.</p>",
            f"<p>{QUOTE}</p><p>No se aceptan postulaciones por correo.</p>",
            f"<p>{QUOTE}</p><p>Please do not follow up.</p>",
            f"<p>{QUOTE}</p><p>No enviar recordatorios.</p>",
            "Send your resume through LinkedIn to jobs@empresa.example.com."]
        for value in content:
            with self.subTest(content=value):
                jobs, failures, requests = await verify(publication(content=value))
                self.assertEqual(jobs, [])
                self.assertEqual(failures, [])

    async def test_english_resume_and_apply_by_email_instructions_are_supported(self):
        for value in ["Please send your resume to jobs@empresa.example.com.",
                "Apply by email to jobs@empresa.example.com.", "Email your CV to jobs@empresa.example.com."]:
            with self.subTest(content=value):
                jobs, failures, _ = await verify(publication(content=f"<p>{value}</p>"))
                self.assertEqual(len(jobs), 1)

    async def test_html_entities_are_decoded_and_quote_is_plain_text(self):
        jobs, _, _ = await verify(publication(content=html_content()))
        self.assertEqual(jobs[0]["payload"]["greenhouse"]["email_quote"], QUOTE)
        self.assertNotIn("<p>", jobs[0]["description"])

    async def test_id_mismatch_prospect_missing_fields_closed_expired_or_invalid_deadline_stay_manual(self):
        cases = [publication(id=999), publication(id="123"), publication(id=True),
            publication(internal_job_id=None), publication(internal_job_id=False), publication(internal_job_id=0),
            publication(title=""), publication(location={}), publication(content=None),
            publication(application_deadline="2000-01-01T00:00:00Z"),
            publication(application_deadline="2099-01-01T00:00:00"), publication(application_deadline="tomorrow"),
            publication(content=f"<p>Applications closed.</p><p>{QUOTE}</p>")]
        for raw in cases:
            with self.subTest(raw=raw):
                jobs, failures, _ = await verify(raw)
                self.assertEqual((jobs, failures), ([], []))

    async def test_timezone_aware_future_deadline_is_preserved(self):
        jobs, _, _ = await verify(publication(application_deadline="2099-01-01T00:00:00Z"))
        self.assertEqual(jobs[0]["valid_until"], "2099-01-01T00:00:00+00:00")
        self.assertEqual(jobs[0]["payload"]["greenhouse"]["valid_until"], jobs[0]["valid_until"])

    async def test_roles_use_substring_and_cities_require_normalized_exact_identity(self):
        jobs, _, _ = await verify(search={"roles": ["CHOFER"], "cities": ["RINCON DE LOS SAUCES"]})
        self.assertEqual(len(jobs), 1)
        for changes in [{"title": "Operario"}, {"location": {"name": "Neuquén"}},
                {"location": {"name": "Rincón de los Sauces, Neuquén"}}]:
            jobs, _, _ = await verify(publication(**changes))
            self.assertEqual(jobs, [])

    async def test_404_and_410_are_real_completed_queries_with_no_verified_job(self):
        for status in (404, 410):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
                self.assertEqual(await verify_discoveries(client, [{"url": URL}], SEARCH), ([], []))

    async def test_redirects_error_codes_malformed_and_oversized_payloads_fail_closed(self):
        responses = [httpx.Response(302, headers={"Location": "https://127.0.0.1/private"}),
            httpx.Response(429), httpx.Response(500), httpx.Response(200, content=b"not JSON"),
            httpx.Response(200, json=[]), httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1))]
        for response in responses:
            requests = []
            with self.subTest(status=response.status_code, size=len(response.content)):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or response)) as client:
                    with self.assertRaises(HTTPException) as raised:
                        await verify_discoveries(client, [{"url": URL}], SEARCH)
                self.assertEqual(raised.exception.status_code, 502)
                self.assertEqual(len(requests), 1)

    async def test_network_failure_returns_safe_error_without_request_details(self):
        def handler(request):
            raise httpx.ConnectError("private-token-and-network-details", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(HTTPException) as raised:
                await verify_discoveries(client, [{"url": URL}], SEARCH)
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private-token", raised.exception.detail)

    async def test_partial_api_failure_preserves_verified_other_job_and_warning(self):
        def handler(request):
            return httpx.Response(500) if request.url.path.endswith("/999") else httpx.Response(200, json=publication())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            jobs, failures = await verify_discoveries(client, [{"url": URL}, {"url": URL.replace("123", "999")}], SEARCH)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(failures), 1)

    async def test_revalidation_succeeds_only_with_fresh_official_identical_evidence(self):
        jobs, _, _ = await verify()
        job = {**jobs[0], "source": SOURCE_ID}
        requests = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json=publication()))) as client:
            await revalidate_job(client, job)
        self.assertEqual([str(request.url) for request in requests], [ENDPOINT])

    async def test_revalidation_blocks_changed_withdrawn_or_closed_publication(self):
        jobs, _, _ = await verify()
        changes = [publication(content="Apply online."), publication(content=QUOTE.replace("empleos@", "otro@")),
            publication(title="Chofer diferente"), publication(company_name="Otra empresa"),
            publication(location={"name": "Neuquén"}), publication(application_deadline="2000-01-01T00:00:00Z"),
            publication(content=QUOTE.replace("enviá tu CV", "enviá tu CV actualizado")), publication(internal_job_id=None)]
        for raw in changes:
            with self.subTest(raw=raw):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=raw))) as client:
                    with self.assertRaises(HTTPException) as raised:
                        await revalidate_job(client, jobs[0])
                self.assertEqual(raised.exception.status_code, 409)

    async def test_revalidation_rejects_forged_provenance_before_network(self):
        jobs, _, _ = await verify()
        changed = []
        for field, value in [("board", "../../private"), ("job_id", 999), ("job_id", "123"),
                ("endpoint", "https://127.0.0.1/private"), ("email_quote", "No email here")]:
            job = copy.deepcopy(jobs[0])
            job["payload"]["greenhouse"][field] = value
            changed.append(job)
        job = copy.deepcopy(jobs[0])
        job["source"] = "web:tavily"
        changed.append(job)
        for job in changed:
            requests = []
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=publication()))) as client:
                with self.assertRaises(HTTPException) as raised:
                    await revalidate_job(client, job)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(requests, [])


def html_content():
    import html
    return html.escape(f"<p>{QUOTE}</p>")


if __name__ == "__main__":
    unittest.main()
