import asyncio
import logging

from dotenv import load_dotenv

from models import RequestClassification, ProcessingError
from telegram_notify import send_digest

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

FAKE_RESULTS = [
    RequestClassification(
        id="REQ-001", category="автоматизація", target_department="маркетинг",
        priority="high", short_summary="Тест high priority",
        requested_actions=["зробити автоматизацію"], needs_clarification=False,
        confidence=9, is_likely_duplicate=False,
    ),
    RequestClassification(
        id="REQ-002", category="звіт/аналітика", target_department="аналітика",
        priority="medium", short_summary="Тест medium",
        requested_actions=["побудувати звіт"], needs_clarification=True,
        confidence=6, is_likely_duplicate=False,
    ),
    RequestClassification(
        id="REQ-003", category="інтеграція", target_department=None,
        priority="low", short_summary="Тест needs_clarification",
        requested_actions=[], needs_clarification=True,
        confidence=4, is_likely_duplicate=True,
    ),
]

FAKE_ERRORS = [
    ProcessingError(id="REQ-004", error="test error", raw_response=""),
]

if __name__ == "__main__":
    asyncio.run(send_digest(FAKE_RESULTS, FAKE_ERRORS))
