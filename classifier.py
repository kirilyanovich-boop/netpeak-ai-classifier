import asyncio
import os
import time
import logging
from google import genai
from google.genai import types
from pydantic import ValidationError
from models import RequestClassification, ProcessingError

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
SLEEP_BETWEEN_REQUESTS = 4     # 15 RPM limit → 4s gap
CONCURRENCY = 1
MIN_SLOT_SECONDS = (60 / 5) * CONCURRENCY  # Little's Law; реальний ліміт free tier — 5 RPM (не 15 за документацією), виявлено при тестуванні
TRANSIENT_RETRY_SLEEP = 5      # seconds before retrying 503/429/timeout

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


def _is_transient_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 503):
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    msg = str(exc).lower()
    return any(tok in msg for tok in ("503", "429", "timeout", "unavailable"))


async def _hold_slot(slot_start: float) -> None:
    elapsed = asyncio.get_event_loop().time() - slot_start
    await asyncio.sleep(max(0.0, MIN_SLOT_SECONDS - elapsed))


async def _call_api_async(client: genai.Client, prompt: str) -> str:
    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RequestClassification,
        ),
    )
    return response.text


async def classify_request_async(
    client: genai.Client,
    request_id: str,
    raw_text: str,
    semaphore: asyncio.Semaphore,
) -> RequestClassification | ProcessingError:
    prompt = SYSTEM_PROMPT + f'ID: {request_id}\nТекст: "{raw_text}"'
    raw = ""

    async with semaphore:
        slot_start = asyncio.get_event_loop().time()

        for validation_attempt in range(2):
            for api_attempt in range(3):
                try:
                    raw = await _call_api_async(client, prompt)
                    break
                except Exception as api_exc:
                    if _is_transient_error(api_exc) and api_attempt < 2:
                        logger.warning(
                            "Transient error for %s (attempt %d): %s — retrying in %ds",
                            request_id, api_attempt + 1, api_exc, TRANSIENT_RETRY_SLEEP,
                        )
                        await asyncio.sleep(TRANSIENT_RETRY_SLEEP)
                    else:
                        logger.error("API call failed for %s: %s", request_id, api_exc)
                        await _hold_slot(slot_start)
                        return ProcessingError(id=request_id, error=str(api_exc), raw_response="")

            try:
                data = RequestClassification.model_validate_json(raw)
                await _hold_slot(slot_start)
                return data.model_copy(update={"id": request_id})
            except (ValidationError, ValueError) as parse_exc:
                if validation_attempt == 0:
                    logger.warning(
                        "Bad model output for %s (attempt 1), retrying: %s",
                        request_id, parse_exc,
                    )
                    await asyncio.sleep(SLEEP_BETWEEN_REQUESTS)
                else:
                    await _hold_slot(slot_start)
                    return ProcessingError(id=request_id, error=str(parse_exc), raw_response=raw)

        await _hold_slot(slot_start)
        return ProcessingError(id=request_id, error="unknown", raw_response=raw)
