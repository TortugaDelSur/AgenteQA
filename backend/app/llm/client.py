import json
from functools import lru_cache

from openai import OpenAI
from pydantic import ValidationError

from app.config import settings
from app.llm.prompts import CHAT_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from app.models.schemas import ChatMessage, ContextProgress, TestPlan


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
    )
    raw = response.choices[0].message.content

    try:
        return TestPlan(**json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"Ese JSON es invalido: {e}. Corregilo y devolvé solo el JSON valido."},
        ]
        response = get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=retry_messages,
            response_format={"type": "json_object"},
        )
        return TestPlan(**json.loads(response.choices[0].message.content))


def generate_report(plan: TestPlan, results: list) -> str:
    raise NotImplementedError("Implementado por Persona B")
