import os
import time
import logging
from google import genai
from google.genai import types
from pydantic import ValidationError
from models import RequestClassification, ProcessingError

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
SLEEP_BETWEEN_REQUESTS = 4  # 15 RPM limit → 4s gap

SYSTEM_PROMPT = """Ти — класифікатор запитів до AI-юніту компанії Netpeak.
AI-юніт займається автоматизацією, інтеграціями, аналітикою та AI-рішеннями для внутрішніх команд.

Класифікуй запит за такими полями:
- category: одне з [автоматизація, інтеграція, звіт/аналітика, баг/підтримка, питання/консультація, поза скоупом]
  * автоматизація — автоматизація рутинних задач, скриптів, процесів
  * інтеграція — з'єднання двох і більше систем/сервісів
  * звіт/аналітика — генерація звітів, дашбордів, аналіз даних
  * баг/підтримка — щось зламалось, не працює, треба полагодити
  * питання/консультація — теоретичне питання, оцінка можливостей, фідбек
  * поза скоупом — не стосується AI-юніту (закупівлі, HR, побутові питання)
- target_department: відділ-замовник (маркетинг, продажі, HR, аналітика, SMM, бухгалтерія тощо) або null якщо незрозуміло
- priority: low/medium/high (виводь з тону, слів "ГОРИТЬ", "терміново", "сьогодні" → high; "не горить", "до кінця місяця" → low)
- short_summary: суть запиту одним реченням українською
- requested_actions: конкретні дії, які просять виконати (може бути порожній список)
- needs_clarification: true якщо запит надто розмитий щоб брати в роботу без уточнень
- confidence: 1-10 — наскільки ти впевнений у правильності класифікації
- is_likely_duplicate: true якщо запит дуже схожий на інший відомий запит у черзі

Запит для класифікації:
"""


def build_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def _call_api(client: genai.Client, prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RequestClassification,
        ),
    )
    return response.text


def classify_request(
    client: genai.Client, request_id: str, raw_text: str
) -> RequestClassification | ProcessingError:
    prompt = SYSTEM_PROMPT + f'ID: {request_id}\nТекст: "{raw_text}"'
    raw = ""

    for attempt in range(2):
        # Network / quota / auth errors — no retry, fail immediately
        try:
            raw = _call_api(client, prompt)
        except Exception as api_exc:
            logger.error("API call failed for %s: %s", request_id, api_exc)
            return ProcessingError(id=request_id, error=str(api_exc), raw_response="")

        # Parse / schema validation errors — model returned bad output, retry once
        try:
            data = RequestClassification.model_validate_json(raw)
            return data.model_copy(update={"id": request_id})
        except (ValidationError, ValueError) as parse_exc:
            if attempt == 0:
                logger.warning(
                    "Bad model output for %s (attempt 1), retrying: %s",
                    request_id,
                    parse_exc,
                )
                time.sleep(SLEEP_BETWEEN_REQUESTS)
            else:
                return ProcessingError(
                    id=request_id, error=str(parse_exc), raw_response=raw
                )

    return ProcessingError(id=request_id, error="unknown", raw_response=raw)
