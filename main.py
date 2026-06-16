import asyncio
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from classifier import build_client, classify_request_async, CONCURRENCY, MIN_SLOT_SECONDS
from models import RequestClassification, ProcessingError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INPUT_CSV = Path("input_requests.csv")
OUTPUT_JSON = Path("output.json")
OUTPUT_REPORT = Path("report.md")


def read_requests(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_output(
    results: list[RequestClassification],
    errors: list[ProcessingError],
) -> dict:
    return {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results) + len(errors),
        "successful": len(results),
        "failed": len(errors),
        "results": [r.model_dump() for r in results],
        "errors": [e.model_dump() for e in errors],
    }


def build_report(
    results: list[RequestClassification],
    errors: list[ProcessingError],
) -> str:
    lines: list[str] = ["# Звіт класифікації запитів\n"]

    # by category
    from collections import Counter
    cat_counts = Counter(r.category for r in results)
    lines.append("## По категоріях\n")
    lines.append("| Категорія | Кількість |")
    lines.append("|-----------|-----------|")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {count} |")
    lines.append("")

    # by priority
    pri_counts = Counter(r.priority for r in results)
    lines.append("## По пріоритетах\n")
    lines.append("| Пріоритет | Кількість |")
    lines.append("|-----------|-----------|")
    for pri in ("high", "medium", "low"):
        lines.append(f"| {pri} | {pri_counts.get(pri, 0)} |")
    lines.append("")

    # by department
    dept_counts = Counter(
        r.target_department for r in results if r.target_department
    )
    lines.append("## По відділах\n")
    lines.append("| Відділ | Кількість |")
    lines.append("|--------|-----------|")
    for dept, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {dept} | {count} |")
    lines.append("")

    # needs clarification
    clarify = [r for r in results if r.needs_clarification]
    lines.append("## Потребують уточнення\n")
    if clarify:
        for r in clarify:
            lines.append(f"- **{r.id}**: {r.short_summary}")
    else:
        lines.append("_Немає_")
    lines.append("")

    # duplicates
    duplicates = [r for r in results if r.is_likely_duplicate]
    lines.append("## Можливі дублі\n")
    if duplicates:
        for r in duplicates:
            lines.append(f"- **{r.id}**: {r.short_summary}")
    else:
        lines.append("_Немає_")
    lines.append("")

    # errors
    lines.append("## Помилки обробки\n")
    if errors:
        for e in errors:
            lines.append(f"- **{e.id}**: {e.error}")
    else:
        lines.append("_Немає_")

    return "\n".join(lines)


async def main() -> None:
    rows = read_requests(INPUT_CSV)
    logger.info("Завантажено %d запитів", len(rows))

    client = build_client()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        classify_request_async(client, row["id"], row["raw_text"], semaphore)
        for row in rows
    ]
    logger.info(
        "Запускаю %d задач асинхронно (паралельність: %d, очікуваний час: ~%ds)",
        len(tasks), CONCURRENCY, int(len(tasks) / CONCURRENCY * MIN_SLOT_SECONDS),
    )
    outcomes = await asyncio.gather(*tasks)

    results = [o for o in outcomes if isinstance(o, RequestClassification)]
    errors  = [o for o in outcomes if isinstance(o, ProcessingError)]

    output = build_output(results, errors)
    OUTPUT_JSON.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Збережено %s", OUTPUT_JSON)

    report = build_report(results, errors)
    OUTPUT_REPORT.write_text(report, encoding="utf-8")
    logger.info("Збережено %s", OUTPUT_REPORT)

    logger.info(
        "Готово: %d успішно, %d помилок", len(results), len(errors)
    )


if __name__ == "__main__":
    asyncio.run(main())
