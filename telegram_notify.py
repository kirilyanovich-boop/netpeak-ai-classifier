import logging
import os
from collections import Counter

import httpx

from models import RequestClassification, ProcessingError

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _build_message(
    results: list[RequestClassification],
    errors: list[ProcessingError],
) -> str:
    total = len(results) + len(errors)
    cat_counts = Counter(r.category for r in results)
    high_count = sum(1 for r in results if r.priority == "high")
    clarify_count = sum(1 for r in results if r.needs_clarification)

    lines = [f"Класифікація: {total} запитів ({len(errors)} помилок)\n"]
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat}: {count}")
    lines.append(f"\nHigh priority: {high_count}")
    lines.append(f"Потребують уточнення: {clarify_count}")
    if errors:
        lines.append(f"Помилки обробки: {len(errors)}")
    return "\n".join(lines)


async def send_digest(
    results: list[RequestClassification],
    errors: list[ProcessingError],
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info("TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані — пропускаємо дайджест")
        return

    text = _build_message(results, errors)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _API_URL.format(token=token),
                json={"chat_id": chat_id, "text": text},
            )
            resp.raise_for_status()
        logger.info("Telegram-дайджест надіслано")
    except Exception as exc:
        logger.warning("Не вдалось надіслати Telegram-дайджест: %s", exc)
