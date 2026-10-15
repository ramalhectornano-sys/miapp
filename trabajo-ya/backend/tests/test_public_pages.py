"""Permitted page-reader fixtures; no test reads the Internet or sends mail."""
import asyncio
import hashlib
import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.services.public_pages import (
    MAX_HTML_BYTES, PageReadError, _PinnedPublicTransport, _resolve_public_addresses,
    _robots_permission, investigate_pages, public_page_url,
)

ROOT = "https://empresa.example.com"
URL = ROOT + "/empleos/chofer"
SEARCH = {"roles": ["chofer"], "cities": ["Rincón de los Sauces"]}
ROBOTS = "User-agent: *\nAllow: /\n"
TEXT = "Buscamos chofer en Rincón de los Sauces. Requisitos: licencia profesional y experiencia de dos años."


def settings(**changes):
    return SimpleNamespace(public_page_reads_enabled=True, public_page_max_reads=6, **changes)


def discovery(url=URL, **changes):
    return {"url": url, "title": "Chofer", "content": "Extracto del buscador.",
        "web_search": {"provider": "tavily", "request_id": "test-request"}, **changes}


async def run_reader(routes=None, results=None, options=None, client_options=None):
    routes = routes or {ROOT + "/robots.txt": ROBOTS, URL: "<main><p>" + TEXT + "</p></main>"}
    captured, events = [], []

    def handler(request):
        captured.append(request)
        response = routes.get(str(request.url))
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        if response is None:
            return httpx.Response(404, text="Not found")
        return httpx.Response(200, text=response, headers={"content-type": "text/plain" if request.url.path.endswith("robots.txt") else "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **(client_options or {})) as client:
        output = await investigate_pages(options or settings(), client,
            results or [discovery()], SEARCH, audit=lambda event: events.append(event))
    return output, captured, events


class PublicPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_link_keeps_discovery_and_hashed_publisher_evidence(self):
        (results, errors), captured, events = await run_reader()
        self.assertFalse(errors)
        result = results[0]
        self.assertEqual(result["content"], "Extracto del buscador.")
        self.assertIn(TEXT, result["raw_content"])
        self.assertEqual(result["web_search"]["request_id"], "test-request")
        proof = result["page_verification"]
        self.assertEqual(proof["status"], "verified_link")
        self.assertEqual(proof["final_url"], URL)
        self.assertEqual(proof["http_status"], 200)
        self.assertEqual(proof["dates"], {})
        self.assertEqual(proof["content_sha256"], hashlib.sha256(("<main><p>" + TEXT + "</p></main>").encode()).hexdigest())
        self.assertFalse(proof["application_method"]["recipient_verified"])
        self.assertEqual([str(request.url) for request in captured], [ROOT + "/robots.txt", URL])
        self.assertEqual([event["status"] for event in events], ["started", "succeeded", "started", "succeeded"])
        self.assertEqual(events[0]["event_id"], events[1]["event_id"])
        self.assertNotEqual(events[1]["event_id"], events[2]["event_id"])
        self.assertNotIn(TEXT, str(events))

    async def test_jsonld_is_bound_to_one_literal_publisher_job_and_excludes_scripts(self):
        posting = {"@type": "JobPosting", "title": "Chofer profesional",
            "hiringOrganization": {"name": "Transportes Ejemplo"}, "description": "Buscamos chofer profesional con experiencia.",
            "jobLocation": {"address": {"addressLocality": "Rincón de los Sauces", "addressRegion": "Neuquén", "addressCountry": "Argentina"}},
            "datePosted": "2026-10-14", "validThrough": "2099-12-31", "qualifications": "Licencia E1"}
        html = f'<head><script type="application/ld+json">{json.dumps(posting)}</script></head><main><p>{TEXT}</p><script>PRIVATE SCRIPT</script><input value="PRIVATE INPUT"><div hidden>PRIVATE HIDDEN</div><footer>PRIVATE FOOTER</footer></main>'
        (results, _), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html})
        result = results[0]
        fact = result["page_verification"]["job_posting"]
        self.assertEqual(fact["hiringOrganization"]["name"], "Transportes Ejemplo")
        self.assertEqual(fact["jobLocation"][0]["address"]["addressRegion"], "Neuquén")
        self.assertEqual(fact["datePosted"], "2026-10-14")
        self.assertIn("Licencia E1", result["raw_content"])
        self.assertFalse(fact["recipient_verified"])
        self.assertNotIn("PRIVATE", result["raw_content"])

    async def test_generic_directory_is_only_a_link_not_an_invented_job(self):
        (results, _), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS,
            URL: "<main>Somos una empresa de transporte en Neuquén. Consultá nuestras novedades y servicios.</main>"})
        proof = results[0]["page_verification"]
        self.assertEqual(proof["status"], "verified_link")
        self.assertEqual(proof["job_postings"], [])
        self.assertNotIn("job_posting", proof)
        self.assertNotIn("recipient_verified_at", str(results))

    async def test_published_email_instruction_remains_unverified(self):
        html = f"<main><p>{TEXT}</p><p>Enviar CV a empleos@empresa.example.com para postularte.</p></main>"
        (results, _), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html})
        method = results[0]["page_verification"]["application_method"]
        self.assertEqual(method["kind"], "published_email_pending_review")
        self.assertFalse(method["recipient_verified"])
        self.assertIn("Enviar CV", method["evidence"])

    async def test_actual_apply_href_has_evidence_but_no_form_is_submitted(self):
        html = f'<main><p>{TEXT}</p><a href="/postular/123">Postularme</a><form action="/postular"><input value="secret"></form></main>'
        (results, _), captured, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html})
        proof = results[0]["page_verification"]
        self.assertEqual(proof["application_links"], [{"url": ROOT + "/postular/123", "evidence": "Postularme"}])
        self.assertTrue(all(request.method == "GET" for request in captured))
        self.assertEqual(len(captured), 2)
        self.assertNotIn("secret", results[0]["raw_content"])

    async def test_following_is_same_publisher_bounded_and_only_one_hop(self):
        career = ROOT + "/empleos"
        other = ROOT + "/careers"
        third = ROOT + "/jobs"
        html = f'<main>{TEXT}<a href="/empleos">Empleos</a><a href="/careers">Careers</a><a href="/jobs">Jobs</a><a href="https://other.example.com/jobs">Jobs</a><a href="/login">Ingresar</a></main>'
        second = f'<main>{TEXT}<a href="/never-recursive">Jobs</a></main>'
        (results, errors), captured, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html, career: second, other: second, third: second})
        self.assertFalse(errors)
        self.assertEqual(len(results), 3)
        self.assertEqual([result["url"] for result in results], [URL, career, other])
        self.assertEqual(results[1]["parent_url"], URL)
        self.assertEqual(results[1]["web_search"], results[0]["web_search"])
        self.assertEqual(results[0]["page_verification"]["allowed_links"], [
            {"url": career, "evidence": "Empleos"}, {"url": other, "evidence": "Careers"}])
        self.assertEqual([str(request.url) for request in captured], [ROOT + "/robots.txt", URL, career, other])

    async def test_followed_links_share_the_total_six_page_budget(self):
        originals = [discovery(ROOT + f"/oferta/{index}") for index in range(6)]
        html = f'<main>{TEXT}<a href="/empleos">Empleos</a></main>'
        routes = {ROOT + "/robots.txt": ROBOTS, ROOT + "/empleos": html,
            **{item["url"]: html for item in originals}}
        (results, _), captured, _ = await run_reader(routes, originals)
        self.assertEqual(len(results), 6)
        self.assertEqual(len(captured), 7)  # robots plus at most six pages
        self.assertNotIn(ROOT + "/empleos", [str(request.url) for request in captured])

    async def test_initial_pages_are_bounded_and_extra_discoveries_stay_pending(self):
        routes = {ROOT + "/robots.txt": ROBOTS}
        routes.update({ROOT + f"/vacantes/{index}": f"<main>{TEXT}</main>" for index in range(8)})
        (results, _), captured, _ = await run_reader(routes, [discovery(ROOT + f"/vacantes/{index}") for index in range(8)])
        self.assertEqual(len(results), 8)
        self.assertEqual(len(captured), 7)
        self.assertEqual(results[6]["page_verification"]["status"], "pending_review")

    async def test_missing_denied_and_unreachable_robots_never_fetch_page(self):
        responses = [httpx.Response(404), "User-agent: *\nDisallow: /empleos\n", httpx.Response(503),
            httpx.Response(200, text="<html>captcha</html>", headers={"content-type": "text/html"})]
        for response in responses:
            with self.subTest(response=response):
                (results, errors), captured, _ = await run_reader({ROOT + "/robots.txt": response, URL: f"<main>{TEXT}</main>"})
                self.assertEqual(results[0]["page_verification"]["status"], "pending_review")
                self.assertTrue(errors)
                self.assertEqual(len(captured), 1)

    async def test_linkedin_and_computrabajo_are_discovered_but_not_scraped(self):
        urls = ["https://www.linkedin.com/jobs/view/123", "https://ar.computrabajo.com/ofertas-de-trabajo/chofer"]
        (results, errors), captured, events = await run_reader(results=[discovery(url) for url in urls])
        self.assertEqual(len(results), 2)
        self.assertFalse(captured)
        self.assertTrue(errors)
        self.assertTrue(all(result["page_verification"]["status"] == "pending_review" for result in results))
        self.assertTrue(all(event["status"] == "blocked" for event in events))

    async def test_private_redirect_cannot_be_followed(self):
        (results, errors), captured, _ = await run_reader({ROOT + "/robots.txt": ROBOTS,
            URL: httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data"})})
        self.assertEqual(results[0]["page_verification"]["status"], "pending_review")
        self.assertTrue(errors)
        self.assertEqual(len(captured), 2)

    async def test_cross_host_redirect_requires_new_robots_before_reading(self):
        other = "https://other.example.com"
        (results, _), captured, _ = await run_reader({ROOT + "/robots.txt": ROBOTS,
            URL: httpx.Response(302, headers={"Location": other + "/jobs"}),
            other + "/robots.txt": "User-agent: *\nDisallow: /\n", other + "/jobs": f"<main>{TEXT}</main>"})
        self.assertEqual(results[0]["page_verification"]["status"], "pending_review")
        self.assertEqual([str(request.url) for request in captured], [ROOT + "/robots.txt", URL, other + "/robots.txt"])

    async def test_404_captcha_and_http_denial_remain_unavailable_or_pending(self):
        for response, expected in [(httpx.Response(404), "unavailable"), (httpx.Response(410), "unavailable"),
                (httpx.Response(403), "pending_review"), (httpx.Response(429), "pending_review"),
                (httpx.Response(200, text="Verify that you are not a robot. Enable JavaScript to continue.", headers={"content-type": "text/html"}), "pending_review")]:
            with self.subTest(expected=expected, status=response.status_code):
                (results, _), captured, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: response})
                self.assertEqual(results[0]["page_verification"]["status"], expected)
                self.assertNotIn("raw_content", results[0])
                self.assertEqual(len(captured), 2)

    async def test_explicit_closed_or_expired_posting_is_not_active(self):
        expired = {"@type": "JobPosting", "title": "Chofer", "validThrough": "2020-01-01"}
        for html in [f"<main>{TEXT} Vacante cerrada.</main>",
                f'<script type="application/ld+json">{json.dumps(expired)}</script><main>{TEXT}</main>']:
            (results, _), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html})
            self.assertEqual(results[0]["page_verification"]["status"], "closed")

    async def test_secrets_and_cookies_in_shared_provider_client_never_reach_publisher(self):
        (results, _), captured, _ = await run_reader({ROOT + "/robots.txt": httpx.Response(200, text=ROBOTS,
            headers={"Set-Cookie": "publisher_session=secret; Path=/", "content-type": "text/plain"}), URL: f"<main>{TEXT}</main>"},
            client_options={"headers": {"Authorization": "Bearer PRIVATE-PROVIDER-KEY", "X-Api-Key": "PRIVATE-KEY"},
                "cookies": {"private": "PRIVATE-COOKIE"}})
        self.assertEqual(results[0]["page_verification"]["status"], "verified_link")
        for request in captured:
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("x-api-key", request.headers)
            self.assertNotIn("cookie", request.headers)

    async def test_large_payloads_and_pdf_links_do_not_become_verified_html(self):
        for response in [httpx.Response(200, content=b"x" * (MAX_HTML_BYTES + 1), headers={"content-type": "text/html"}),
                httpx.Response(200, content=b"PDF", headers={"content-type": "application/pdf"})]:
            (results, _), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: response})
            self.assertEqual(results[0]["page_verification"]["status"], "pending_review")

    async def test_disabling_reader_does_not_discard_discoveries_or_make_requests(self):
        options = SimpleNamespace(public_page_reads_enabled=False, public_page_max_reads=6)
        (results, _), captured, _ = await run_reader(options=options)
        self.assertFalse(captured)
        self.assertEqual(results[0]["content"], discovery()["content"])
        self.assertEqual(results[0]["page_verification"]["status"], "pending_review")

    async def test_real_proxy_is_never_bypassed_and_preserves_pending_discoveries(self):
        # The provider client is not a publisher transport. With a configured
        # proxy that cannot pin DNS, do no direct HTTP or DNS lookup at all.
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport()) as client:
            with patch("app.services.public_pages._proxy_present", return_value=True), \
                    patch("app.services.public_pages._resolve_public_addresses", AsyncMock()) as resolver:
                results, errors = await investigate_pages(settings(), client, [discovery()], SEARCH)
        self.assertFalse(errors)
        resolver.assert_not_awaited()
        self.assertEqual(results[0]["page_verification"]["status"], "pending_review")
        self.assertIn("proxy", results[0]["page_verification"]["reason"])

    async def test_valueless_html_attributes_do_not_crash_the_search(self):
        html = f'<main style aria-hidden><p>{TEXT}</p><script type>ignored code</script></main>'
        (results, errors), _, _ = await run_reader({ROOT + "/robots.txt": ROBOTS, URL: html})
        self.assertFalse(errors)
        self.assertEqual(results[0]["page_verification"]["status"], "verified_link")

    async def test_trickling_body_has_a_total_deadline_and_failed_audit(self):
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"<main>"
                await asyncio.sleep(0.02)
                yield TEXT.encode()

        routes = {ROOT + "/robots.txt": ROBOTS,
            URL: httpx.Response(200, stream=SlowBody(), headers={"content-type": "text/html"})}
        with patch("app.services.public_pages.MAX_REQUEST_SECONDS", 0.005):
            (results, errors), _, events = await run_reader(routes)
        self.assertTrue(errors)
        self.assertEqual(results[0]["page_verification"]["status"], "pending_review")
        completed = [event for event in events if event.get("http_status") == 200 and event["status"] == "failed"]
        self.assertEqual(len(completed), 1)
        started = next(event for event in events if event["event_id"] == completed[0]["event_id"] and event["status"] == "started")
        self.assertEqual(started["url"], URL)
        self.assertNotIn("raw_content", results[0])

    async def test_real_transport_pins_ip_and_keeps_original_sni_host_without_rebinding(self):
        captured = []
        delegate = httpx.MockTransport(lambda request: captured.append(request) or httpx.Response(200, text="ok"))
        resolver = AsyncMock(return_value=["93.184.216.34"])
        with patch("app.services.public_pages._resolve_public_addresses", resolver):
            async with httpx.AsyncClient(transport=_PinnedPublicTransport(delegate)) as client:
                await client.get(URL, headers={"Authorization": "private", "Cookie": "private"})
        self.assertEqual(resolver.await_count, 1)
        self.assertEqual(captured[0].url.host, "93.184.216.34")
        self.assertEqual(captured[0].headers["Host"], "empresa.example.com")
        self.assertEqual(captured[0].extensions["sni_hostname"], "empresa.example.com")
        self.assertNotIn("Authorization", captured[0].headers)
        self.assertNotIn("Cookie", captured[0].headers)

    async def test_different_publishers_sharing_ip_never_share_a_tls_pool(self):
        delegates = []

        def delegate(**options):
            captured = []
            pool = httpx.MockTransport(lambda request: captured.append(request) or httpx.Response(200, text="ok"))
            delegates.append((pool, captured, options))
            return pool

        with patch("app.services.public_pages._resolve_public_addresses", AsyncMock(return_value=["93.184.216.34"])), \
                patch("app.services.public_pages.httpx.AsyncHTTPTransport", side_effect=delegate):
            async with httpx.AsyncClient(transport=_PinnedPublicTransport()) as client:
                await client.get(URL)
                await client.get("https://other.example.com/jobs")
                await client.get(URL)
        self.assertEqual(len(delegates), 2)
        self.assertEqual([len(item[1]) for item in delegates], [2, 1])
        self.assertEqual([item[1][0].extensions["sni_hostname"] for item in delegates],
            ["empresa.example.com", "other.example.com"])
        self.assertTrue(all(item[2]["verify"] for item in delegates))

    async def test_mixed_public_private_dns_answers_fail_before_connection(self):
        loop = __import__("asyncio").get_running_loop()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=records)):
            with self.assertRaises(PageReadError):
                await _resolve_public_addresses("empresa.example.com")
        for ip in ["127.0.0.1", "169.254.169.254", "::1", "fd00::1", "224.0.0.1", "ff02::1", "2002:0a00:0001::1"]:
            with self.subTest(ip=ip), self.assertRaises(PageReadError):
                await _resolve_public_addresses(ip)

    async def test_async_audit_is_awaited_and_never_records_page_body(self):
        audit = AsyncMock()
        transport = httpx.MockTransport(lambda request: httpx.Response(200,
            text=ROBOTS if request.url.path == "/robots.txt" else f"<main>{TEXT}</main>",
            headers={"content-type": "text/plain" if request.url.path == "/robots.txt" else "text/html"}))
        async with httpx.AsyncClient(transport=transport) as client:
            await investigate_pages(settings(), client, [discovery()], SEARCH, audit=audit)
        self.assertEqual(audit.await_count, 4)
        self.assertNotIn(TEXT, str(audit.call_args_list))


class URLAndRobotsTests(unittest.TestCase):
    def test_untrusted_url_variants_are_rejected(self):
        bad = ["http://empresa.example.com/jobs", "https://localhost/jobs", "https://127.0.0.1/jobs",
            "https://169.254.169.254/latest", "https://user:password@empresa.example.com/jobs",
            "https://empresa.example.com:8443/jobs", "https://empresa.example.com/jobs?token=private",
            "https://empresa.example.com/jobs?ACCESS_TOKEN=private", "https://empresa.example.com/jobs#token",
            "https://empresa.example.com\\@localhost/jobs", "https://empresa.local/jobs", "https://123456/jobs"]
        bad += ["https://224.0.0.1/jobs", "https://[ff02::1]/jobs", "https://[2002:a00:1::1]/jobs"]
        self.assertTrue(public_page_url(URL))
        for url in bad:
            with self.subTest(url=url):
                self.assertFalse(public_page_url(url))

    def test_robots_longest_rule_allow_tie_exact_groups_and_wildcards(self):
        text = "User-agent: *\nDisallow: /\nAllow: /empleos\nDisallow: /empleos/privado\nAllow: /empleos/privado/publico\n"
        self.assertTrue(_robots_permission(text, URL)[0])
        self.assertFalse(_robots_permission(text, ROOT + "/empleos/privado")[0])
        self.assertTrue(_robots_permission(text, ROOT + "/empleos/privado/publico")[0])
        self.assertTrue(_robots_permission("User-agent: *\nDisallow: /x\nAllow: /x\n", ROOT + "/x")[0])
        self.assertFalse(_robots_permission("User-agent: *\nDisallow: /*?token=*\n", ROOT + "/x?token=public")[0])
        self.assertTrue(_robots_permission("User-agent: *\nDisallow: /\nUser-agent: TrabajoYA-Research\nAllow: /\n", URL)[0])
        self.assertFalse(_robots_permission("User-agent: *\nDisallow: /empleos/%70rivado$\n", ROOT + "/empleos/privado")[0])


if __name__ == "__main__":
    unittest.main()
