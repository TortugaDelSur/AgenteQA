from app.models.schemas import TestPlan

SAMPLE_TEST_PLAN = TestPlan(
    test_cases=[
        {
            "id": "TC-01",
            "type": "ui",
            "title": "Login exitoso",
            "steps": [
                {"action": "goto", "url": "https://example.com/login"},
                {"action": "fill", "selector": "#email", "value": "test@example.com"},
                {"action": "fill", "selector": "#password", "value": "secret123"},
                {"action": "click", "selector": "#login-button"},
                {"action": "assert_text", "selector": "h1", "expected": "Bienvenido"},
            ],
        },
        {
            "id": "TC-02",
            "type": "endpoint",
            "title": "GET /api/health responde 200",
            "request": {"method": "GET", "url": "https://example.com/api/health", "headers": {}, "body": None},
            "expected_status": 200,
            "expected_body_contains": "ok",
        },
    ]
)
