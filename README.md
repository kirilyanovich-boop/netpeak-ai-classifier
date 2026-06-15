# Класифікатор запитів AI-юніту

Скрипт читає `input_requests.csv` (внутрішні запити до AI-юніту у вільній формі), класифікує кожен через Google Gemini і зберігає структурований результат у `output.json` та `report.md`.

## Як запустити

```bash
pip install -r requirements.txt
cp .env.example .env
# відкрий .env і встав свій GEMINI_API_KEY
python main.py
```

Ключ отримати: https://aistudio.google.com/apikey (безкоштовно, реєстрація через Google-акаунт).

## Що генерується

- **`output.json`** — повний структурований результат по всіх 18 запитах
- **`report.md`** — агрегати: розподіл по категоріях, пріоритетах, відділах; список запитів що потребують уточнення, можливі дублі, помилки обробки

## Схема класифікації

| Поле | Тип | Опис |
|------|-----|------|
| `id` | string | ID з вхідного CSV |
| `category` | enum | автоматизація / інтеграція / звіт/аналітика / баг/підтримка / питання/консультація / поза скоупом |
| `target_department` | string \| null | відділ-замовник |
| `priority` | low/medium/high | виведено з тону і терміновості |
| `short_summary` | string | суть одним реченням |
| `requested_actions` | list[string] | конкретні дії, що просять |
| `needs_clarification` | bool | запит надто розмитий для роботи |
| `confidence` | int 1–10 | впевненість моделі у класифікації |
| `is_likely_duplicate` | bool | схожий на інший запит у черзі |

Поля `confidence` і `is_likely_duplicate` додані понад мінімум: перше дозволяє фільтрувати сумнівні класифікації без `needs_clarification`, друге — одразу виявляти дублі (у тестових даних REQ-001 і REQ-013 — той самий Google Ads звіт).

## Де ламається / обмеження

**Невалідний вивід LLM.** Використовується нативний structured output Gemini (`response_mime_type=application/json` + `response_json_schema`), тому модель змушена повертати валідний JSON. Якщо Pydantic-валідація все ж падає — один retry. Після другого фейлу запит записується у `errors` і скрипт іде далі, не падаючи.

**Мережеві та API-помилки** (quota, auth, timeout) відловлюються окремо і не ретраяться — одразу `ProcessingError`. Quota-помилка на безкоштовному тірі означає, що треба почекати і запустити знову.

**Rate limit.** Free tier Gemini — ~15 RPM. Між запитами `sleep(4s)`. На 18 запитів — ~2 хвилини.

**Недетермінізм.** Однаковий запит може дати різну класифікацію при перезапуску. Поле `confidence` допомагає виявити невпевнені результати. Для стабільності можна виставити `temperature=0` в `GenerateContentConfig`.

**Великий обсяг.** Обробка послідовна (не async). При 100+ запитах буде повільно (~7+ хвилин) і вищий ризик quota-помилок.

## Технічний вибір

- **`google-genai`** (не `google-generativeai`) — актуальний SDK станом на 2025–2026, старий deprecated.
- **`gemini-3.5-flash`** — поточна безкоштовна модель (gemini-2.0-flash і 1.5-flash shutdown).
- **Нативний structured output** замість `"поверни тільки JSON"` у промпті: Gemini стабільно обгортає відповідь у ```json``` навіть при прямій забороні; `response_json_schema` вирішує це на рівні API.

## Що зробив би далі

- `temperature=0` в конфіг для відтворюваних результатів
- async-обробка (`asyncio` + `client.aio.models.generate_content`) для паралельних запитів
- запис результату в Google Sheets через `gspread`
- Telegram-дайджест через Bot API
- тести на edge-cases (REQ-002/REQ-011 → needs_clarification, REQ-012 → поза скоупом)
