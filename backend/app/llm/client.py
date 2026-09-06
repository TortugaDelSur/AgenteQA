import json
from functools import lru_cache

from openai import OpenAI
from pydantic import ValidationError

from app.config import settings
from app.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    PAGE_DOUBT_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
)
from app.models.schemas import ChatMessage, ContextProgress, TestPlan, TestResult

# temperature baja para que el checklist de contexto y el plan sean lo mas reproducibles posible
# entre corridas (no elimina el no-determinismo del LLM, pero lo reduce bastante).
TEMPERATURE = 0.1


@lru_cache
def get_client() -> OpenAI:
    return OpenAI(base_url=settings.deepseek_base_url, api_key=settings.deepseek_api_key)


def _to_openai_messages(system_prompt: str, history: list[ChatMessage]) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    return messages


def chat(history: list[ChatMessage], page_snapshot: str | None = None) -> tuple[str, ContextProgress]:
    messages = _to_openai_messages(CHAT_SYSTEM_PROMPT, history)
    if page_snapshot:
        messages.append({
            "role": "user",
            "content": f"Elementos reales encontrados en la pagina (para contrastar contra lo que decis):\n{page_snapshot}",
        })

    response = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=TEMPERATURE,
    )
    data = json.loads(response.choices[0].message.content)
    return data["reply"], ContextProgress(**data["context"])


def generate_plan(history: list[ChatMessage], page_snapshot: str | None = None) -> TestPlan:
    messages = _to_openai_messages(PLAN_SYSTEM_PROMPT, history)
    if page_snapshot:
        messages.append({
            "role": "user",
            "content": f"Elementos reales encontrados en la pagina:\n{page_snapshot}",
        })

    response = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=TEMPERATURE,
    )
    raw = response.choices[0].message.content

    try:
        return _parse_test_plan(raw)
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f"Ese JSON es invalido: {e}. Corregilo, respetando el schema exacto "
                           f'(un objeto con la clave "test_cases"), y devolvé solo el JSON valido.',
            },
        ]
        response = get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=retry_messages,
            response_format={"type": "json_object"},
            temperature=TEMPERATURE,
        )
        return _parse_test_plan(response.choices[0].message.content)


def _parse_test_plan(raw: str) -> TestPlan:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError(f"esperaba un objeto JSON, recibio {type(data).__name__}")
    return TestPlan(**data)


def check_page_doubt(history: list[ChatMessage], url: str, elements: str) -> str | None:
    messages = _to_openai_messages(PAGE_DOUBT_SYSTEM_PROMPT, history)
    messages.append({"role": "user", "content": f"Pantalla: {url}\nElementos encontrados:\n{elements}"})

    response = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=TEMPERATURE,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("question") or None


def generate_report(plan: TestPlan, results: list[TestResult]) -> str:
    payload = {
        "test_cases": [tc.model_dump() for tc in plan.test_cases],
        "results": [r.model_dump() for r in results],
    }
    response = get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        temperature=TEMPERATURE,
    )
    return response.choices[0].message.content
