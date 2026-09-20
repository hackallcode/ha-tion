# Tion MagicAir Android API — результаты перехвата

Дата перехвата: 2026-09-20. Приложение: MagicAir Android 1.19.8 (`com.tion.magicair`).

## Главный результат

Мобильное приложение использует `https://api.magicair.tion.ru` (без `2`). Авторизация передаётся как
`Authorization: Bearer <access_token>`. Для команд приложение отправляет JSON и затем опрашивает
`GET /task/{task_id}` до терминального состояния.

### 1. Включить или выключить расписание

```http
POST /zone/{zoneGuid}/schedule?on=true HTTP/1.1
Host: api.magicair.tion.ru
Authorization: Bearer <redacted>
Content-Type: application/json; charset=UTF-8
User-Agent: okhttp/2.7.5

{}
```

Для выключения единственное отличие — `on=false`.

Ответ на включение (HTTP 200):

```json
{
  "task_id": "0ed61b40-0f4f-4e57-8278-0df91686b730",
  "status": "queued",
  "type": "toggleCalendar",
  "target_guid": "<zoneGuid>",
  "user_guid": "<redacted>",
  "email": "<redacted>"
}
```

Цепочка: `POST` → `GET /task/{task_id}` → `completed`, тип задачи всегда `toggleCalendar`.
На втором чистом прогоне непосредственно перед запросом `/location` показывал
`is_active=false, is_mode_sync=false`; после выполнения — `is_active=true, is_mode_sync=true`.
`is_schedule_sync` оставался `true`.

Сигнатура для клиента:

```python
async def set_schedule_active(zone_guid: str, enable: bool):
    return await post(f"/zone/{zone_guid}/schedule", params={"on": enable}, json={})
```

Ключевое отличие от известного веб-вызова — обязательный query-параметр `on=true|false`.

### 2. Восстановить применение текущего расписания

```http
POST /zone/{zoneGuid}/schedule/preset HTTP/1.1
Host: api.magicair.tion.ru
Authorization: Bearer <redacted>
Content-Type: application/json; charset=UTF-8
User-Agent: okhttp/2.7.5

{}
```

Query-параметров в реальном запросе нет. В декомпилированном Retrofit-интерфейсе присутствует
необязательный `presetId`, но приложение его не передало.

Ответ (HTTP 200):

```json
{
  "task_id": "8b82458d-823a-4010-9362-de3abce999cc",
  "status": "queued",
  "type": "activatePreset",
  "target_guid": "<zoneGuid>",
  "user_guid": "<redacted>",
  "email": "<redacted>"
}
```

Поллинг показал `delivered` → `completed`, тип задачи `activatePreset`. Непосредственно перед нажатием
`GET /location` показывал `is_active=true, is_mode_sync=false`; после —
`is_active=true, is_mode_sync=true`. В этом прогоне применился параметр активного пресета: целевой CO₂
изменился с 1200 до 1500.

Сигнатура для клиента:

```python
async def apply_schedule(zone_guid: str):
    return await post(f"/zone/{zone_guid}/schedule/preset", json={})
```

## Асинхронные задачи, подтверждённые трафиком

| UI/операция | Endpoint | `type` |
|---|---|---|
| расписание вкл/выкл | `POST /zone/{zoneGuid}/schedule?on=...` | `toggleCalendar` |
| восстановить расписание | `POST /zone/{zoneGuid}/schedule/preset` | `activatePreset` |
| режим/цели комнаты | `POST /zone/{zoneGuid}/mode` | `setZoneMode` |
| питание/скорость/нагрев бризера | `POST /device/{deviceGuid}/mode` | `setDeviceMode` |
| подсветка | `POST /device/{deviceGuid}/settings` | `setBrightness` |
| перемещение устройства | `POST /device/{deviceGuid}/zone/{zoneGuid}` | `moveDevice` |

## Остальные наблюдавшиеся ручки

Всего в очищенном логе 220 обменов с `api.magicair.tion.ru` и 22 уникальные сигнатуры:

- состояние: `GET /location`, `GET /location/{guid}`, `GET /device/{guid}`;
- обновления: `GET /device/{guid}/updates`;
- история: `GET /zone/{guid}/data/12hours`, `GET /zone/{guid}/data/3days`;
- режим комнаты: `POST /zone/{guid}/mode`;
- управление устройством: `POST /device/{guid}/mode`, `POST /device/{guid}/settings`;
- перемещение/порядок: `POST /device/{deviceGuid}/zone/{zoneGuid}`,
  `POST /location/{locationGuid}/deviceOrder`;
- пресеты: `GET|POST /preset/{zoneGuid}` и
  `PUT|DELETE /preset/{zoneGuid}?presetId={presetId}`;
- расписания: `GET|POST /schedule/{zoneGuid}` и
  `PUT|DELETE /schedule/{zoneGuid}?scheduleId={scheduleId}`;
- задачи: `GET /task/{taskId}`;
- профиль: `GET /account/info`.

Полная карта наблюдавшихся и найденных статическим анализом ручек, схемы тел и пометки
`x-evidence: observed|apk-static` находятся в [`magicair-openapi.yaml`](./magicair-openapi.yaml).

## Что было сделано

1. Специально для тестов MagicAir создан отдельный disposable rootable Android 11 AVD на образе
   Google APIs без Google Play; рабочие пользовательские данные в нём не использовались.
2. Установлен APK MagicAir 1.19.8; SHA-256 APK:
   `525b150518d33601b649b75744116c569a27c4a90949d594921ac2ff66c55ed2`.
3. В системное хранилище Android установлен CA mitmproxy, прокси эмулятора направлен на хост.
4. Трафик отфильтрован по MagicAir API и сохранён в mitmproxy flow-файл.
5. APK декомпилирован jadx; Retrofit-интерфейсы использованы для дополнения карты API.
6. Сформирован рекурсивно очищенный JSONL: заголовки авторизации, cookie, email, user GUID и поля
   OAuth/паролей заменены на `<redacted>`.
7. Сформирован и проверен OpenAPI 3.0.3. `openapi-spec-validator` завершился с `OK`.

Примечание по TLS: у этой старой версии приложения найден собственный trust-all `X509TrustManager` и
разрешающий `HostnameVerifier`. Отдельный Frida/Objection bypass фактически не понадобился.

## Артефакты и безопасность

В этом репозитории (папка `docs/`):

- [`magicair-openapi.yaml`](./magicair-openapi.yaml) — проверенная OpenAPI 3.0.3 спецификация.

Методика перехвата трафика (эмулятор + mitmproxy + декомпиляция APK) описана в отдельной приватной
памятке и в этот репозиторий не входит.

Остальное лежит в локальном capture-воркспейсе и в git **не коммитится** (содержит секреты, APK и
декомпилят):

- `flows-redacted.jsonl` — очищенный структурированный лог (220 записей);
- `magicair-final-20260920.flows` — исходный mitmproxy capture;
- `jadx/` — декомпилированные Java-исходники;
- `generate_openapi.py`, `export_addon.py`, `extract_flows.py` — воспроизводящие скрипты;
- `action-markers.tsv` — временные метки ручных действий;
- `MagicAir_1.19.8.apk` — установочный пакет приложения.

SHA-256 исходного capture:
`3126fd351be91a1ee8d37038705a1a1e7b946128a1690f62c80a323c73a4e511`.

**Не публиковать `magicair-final-20260920.flows`: в исходном capture есть действующий access token и
данные аккаунта.** Для анализа и передачи использовать `flows-redacted.jsonl`. Сырые `.flows` и APK
никогда не должны попадать в git.

## Ограничения

`observed` означает, что запрос был реально пойман в этом сеансе. `apk-static` означает только наличие
декларации в APK: такая ручка не вызывалась и может быть устаревшей. Деструктивные методы не следует
проверять вне тестовой зоны. Удаление расписаний/пресетов потенциально каскадное.
