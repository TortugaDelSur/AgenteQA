import httpx

from app.models.schemas import TestCase, TestResult

TIMEOUT_SECONDS = 15.0
BODY_SNIPPET_LEN = 500


async def run_endpoint(tc: TestCase, client: httpx.AsyncClient | None = None) -> TestResult:
    """Ejecuta un TestCase tipo "endpoint": hace la request y compara status/body.

    `client` es inyectable para tests (httpx.MockTransport); si no viene, se crea y cierra uno propio.
    Una excepcion de red devuelve status "error" (no propaga, para no tumbar el resto del plan).
    """
    req = tc.request
    if req is None:
        return TestResult(
            test_case_id=tc.id, status="error", detail="el test case 'endpoint' no define 'request'"
        )

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = await client.request(
            req.method, req.url, headers=req.headers or None, json=req.body
        )
    except httpx.HTTPError as exc:
        return TestResult(
            test_case_id=tc.id, status="error", detail=f"la request fallo: {exc!r}"
        )
    finally:
        if own_client:
            await client.aclose()

    problems: list[str] = []
    if tc.expected_status is not None and response.status_code != tc.expected_status:
        problems.append(f"esperaba status {tc.expected_status}, recibio {response.status_code}")
    if tc.expected_body_contains and tc.expected_body_contains not in response.text:
        problems.append(
            f"el body de la respuesta no contiene el texto esperado ({tc.expected_body_contains!r})"
        )

    evidence = f"HTTP {response.status_code} {req.method} {req.url}\n{response.text[:BODY_SNIPPET_LEN]}"
    if problems:
        return TestResult(
            test_case_id=tc.id, status="fail", detail="; ".join(problems), evidence=evidence
        )
    return TestResult(
        test_case_id=tc.id,
        status="pass",
        detail=f"HTTP {response.status_code}, todas las verificaciones pasaron",
        evidence=evidence,
    )
