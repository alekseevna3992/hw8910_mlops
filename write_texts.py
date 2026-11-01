import csv, io
from pathlib import Path

defects = [
    ["id","symptom","reproduce","expected","observed","root_cause","fix_commit","regression_test","before_log","after_log"],
    ["1",
     "Кеш подготовки не инвалидируется при изменении данных и не учитывает config",
     "run дважды; изменить input.txt; run ещё раз",
     "PREPARED -> CACHE_HIT -> PREPARED",
     "всегда CACHE_HIT",
     "cache_key = sha256(str(data_path)); игнорирует байты файла и поля config",
     "release.py:cache_key",
     "test_cache_invalidated_on_data_change; test_changed_bytes_at_same_path_invalidate_cache",
     "logs/before_run_after_change.log",
     "logs/green_integration.log"],
    ["2",
     "Неполный/чужой/отказной отчёт получает зелёный выпуск",
     "run --report report-incomplete.json / report-foreign.json / report-reject.json",
     "отказ; accepted.json побайтно неизменён",
     "PUBLISHED fixture-B во всех трёх",
     "validate_release проверяет только truthy(report.get('passed')); 'false' - непустая строка, truthy; нет status, хешей, runtime_sha256, metrics, model_id",
     "release.py:validate_release",
     "test_reject_and_incomplete_and_foreign_report; test_incomplete_false_and_truthy_string_rejected; test_report_binding_mismatch_rejected; test_runtime_change_with_stale_hash_rejected",
     "logs/before_incomplete.log; logs/before_foreign.log; logs/before_accepted_after_incomplete.log",
     "logs/green_integration.log"],
    ["3",
     "При ошибке записи target частично перезаписан",
     "mock os.replace/write_text -> raise внутри publish",
     "target побайтно неизменён; tmp удалён; исключение наружу",
     "частичная перезапись target",
     "publish использует target.write_text без временного файла, flush/fsync и os.replace",
     "release.py:publish",
     "test_failed_atomic_replace_preserves_previous_bytes; test_rejection_preserves_previous_bytes; test_publish_and_repeat",
     "logs/intentional_break.log",
     "logs/green_all_fixed.log"],
    ["4",
     "Повтор успешного выпуска создаёт дубликаты публикаций",
     "run дважды подряд",
     "одна запись в publications.jsonl",
     "6 записей в .lab-before/publications.jsonl",
     "run() безусловно дописывает publications.jsonl; нет release_id и проверки; журнал попыток и журнал событий не разделены",
     "lab.py:run; lab.py:release_id",
     "test_no_duplicate_publications; test_crash_between_pointer_and_log_recovered",
     "logs/before_pub_count.log (6); .lab-before/publications.jsonl",
     "logs/after_pub_count.log (1); .lab-after/publications.jsonl"],
    ["5",
     "ready=200 до завершения прогрева",
     "service --warmup-seconds 5; сразу GET /ready",
     "503 до окончания прогрева",
     "200 сразу",
     "self.ready=True в __init__; не связан с warmup_finished",
     "service.py:ServiceState.__init__",
     "test_ready_false_before_warmup",
     "logs/before_ready_status.txt (200)",
     "logs/after_ready_early.txt (503); logs/after_ready_late.txt (200)"],
    ["6",
     "Сервис отдаёт model_id из accepted.json вместо загруженной модели",
     "сервис на A; опубликовать B; снова /generate без перезапуска",
     "model_id == A до перезапуска; B после",
     "сразу B",
     "generate() читает advertised=accepted.json на каждый запрос вместо self.backend.loaded_id",
     "service.py:generate; app.py",
     "test_version_reflects_loaded_not_advertised",
     "logs/before_debug_version.log",
     "logs/green_integration.log"],
    ["7",
     "Невалидный запрос запускает backend",
     "POST /generate max_new_tokens=100000 / 0 / 'many' / пустой prompt",
     "4xx; /debug.calls не растёт",
     "200; calls++",
     "нет валидации полей до вызова backend",
     "service.py:handler_for; app.py:GenerateRequest",
     "test_invalid_request_does_not_call_backend",
     "logs/before_debug_after_bad.json (calls++)",
     "logs/fastapi_calls_after_bad.json (calls==0)"],
]

buf = io.StringIO()
w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
for row in defects:
    w.writerow(row)
Path("defects.csv").write_text(buf.getvalue(), encoding="utf-8")
print("defects.csv written:", Path("defects.csv").stat().st_size, "bytes")

report = """Отчёт ДЗ 8+9+10
================

1. Репозиторий и устройство
   - Проект hw8910. Исходная (сломанная) версия прототипа — .broken/release.py, .broken/lab.py, .broken/service.py.
   - Исправленная версия — те же три файла в корне + backend.py, app.py, app_real.py, flow.py, bench.py, build_real.py.
   - Тесты: tests/test_release.py (13 приложенных) + tests/test_integration.py (8 собственных).
   - Зависимости: Python 3.12, torch 2.15.0+cpu, transformers 5.22.1, peft 0.21.2, prefect 3.9.1, fastapi 0.150.0, pydantic, uvicorn[standard], httpx.
   - Красный прогон: logs/red_integration.log — 7 из 8 новых тестов падают (FAIL). Зелёный: logs/green_all_fixed.log — 21/21 OK.
   - defects.csv — 7 причин, воспроизведение, исправление, тест, до/после.

2. Что переиспользовано из ДЗ 6+7
   - Веса, adapter_config, manifest, отчёты ДЗ 6+7 в этой сдаче недоступны (find по ~/Documents/BMSTU/MLOps не нашёл ни adapter_config.json, ни *.safetensors, ни manifest*.json, ни report*.json).
   - Вместо них выполнен реальный smoke на настоящей transformers-модели sshleifer/tiny-gpt2 (артефакт сохранён в artifacts/real/model и artifacts/real/tokenizer, manifest.real.json + report.real.json, отчёт помечен synthetic_metrics=true, note="SMOKE ONLY").
   - Как только адаптер/отчёты ДЗ 6+7 появятся — build_real.py и RealBackend(adapter_dir=...) подхватят их без изменения кода.

3. Граф задач (flow.py, Prefect 3.9)
   - prepare_task: cache_key_fn=task_input_hash, persist_result=True. Входы: data_path, config_path, result_dir. Выход: input_sha256, rows, config, cache_key. Кеш: .lab-after/cache-prefect/<cache_key>.json.
   - check_artifact_task: читает manifest, сверяет file_hashes с реальными файлами на диске.
   - gate_task: release.validate_release(manifest, report).
   - publish_task: release.publish(manifest, report, accepted.json).
   - Повтор prepare при неизменных входах → CACHE_HIT (logs/flow_run1.log PREPARED, logs/flow_run2.log CACHE_HIT). Проверено на реальном прогоне.
   - Повтор публикации не создаёт дубликат: lab.py:release_id + _release_already_logged, разделены attempts.jsonl и publications.jsonl.
   - Сбой после подготовки → повтор с CACHE_HIT. Сбой между обновлением accepted.json и записью журнала (--fail-after-publish) → повтор восстанавливает согласованность без дубля.

4. Прогоны процесса
   - Успешный: lab.py run → PUBLISHED fixture-B.
   - Сбой после подготовки: lab.py run --fail-after-prepare → exit 1, accepted.json побайтно неизменён, повтор → CACHE_HIT.
   - Изменение input.txt по тому же пути → новый cache_key → PREPARED.
   - Сбой между publish и log: accepted.json = B, журнал пуст; повтор → одна запись в publications.jsonl.

5. Gate и публикация
   - Полный отчёт: status=complete, passed is True (строго bool), evaluation_run_id непустой, все четыре хеша и model_id совпадают с manifest, metrics.accuracy и metrics.format_rate — числа в [0,1] (не bool, не str), runtime_sha256 пересчитан из runtime.
   - Отрицательные: report-incomplete.json (status=running, passed='false'), report-foreign.json (A-отчёт для B), report-reject.json (passed=False), NaN/Inf, runtime_sha256 != recomputed, model_sha256 mismatch. Все → ValueError, accepted.json неизменён.
   - Хеш accepted.json до/после отказов совпадает (logs/before_accepted_after_incomplete.log).
   - PASS из фикстуры не считается оценкой модели: report.real.json помечен synthetic_metrics=true и note="SMOKE ONLY".

6. Быстрые тесты и триггеры
   - Зелёный: 21/21 OK. Красный: 7/8 FAIL в test_integration.
   - CI: локальный прогон. GitHub Actions не настраивался (не требуется для сдачи).
   - Триггеры:
     * новый код → unittest discover tests;
     * изменение данных → инвалидация кеша подготовки (cache_key) и повтор оценки;
     * новый адаптер → полный eval (quality_gate ДЗ 6+7) + release.validate_release перед сменой accepted.json.

7. API (FastAPI, app.py для stub и app_real.py для tiny-gpt2)
   - /health — жизнь процесса; /ready — готовность; /debug — loaded_id, calls, runtime_sha256.
   - Прогрев в app.py — stub грузится в lifespan, ready=True.
   - Успешный ответ /generate: text, request_id, model_id, runtime_sha256, output_tokens, generation_seconds.
   - Неправильный запрос (max_new_tokens=100000 / 0 / 'many' / пустой prompt) → 422 pydantic, /debug.calls не увеличивается: logs/fastapi_calls_before.json calls=0, logs/fastapi_calls_after_bad.json calls=0, logs/fastapi_calls_after_valid.json calls=1.
   - Реальный /generate на app_real: tiny-gpt2, настоящий transformers.generate, ответ в logs/real_valid.json (text=" stairs ...", output_tokens=8, generation_seconds=0.012).

8. Замер
   - logs/bench_real_summary.log: concurrency=1 и concurrency=2, по 4 запроса на медленном CPU (tiny-gpt2, ~0.4 МБ весов). n=4 допустимо по ДЗ (4+4 на медленном CPU).
   - results_real.csv содержит все попытки: mode, id, status, error, wall_s, gen_s, model_id, output_tokens, limit. Ошибки и таймауты не удаляются.
   - ВАЖНО: в conc=1 первый запрос = 1.10 s (холодный старт, инициализация torch), остальные три = 0.106/0.029/0.018 s. В conc=2 все 4 запроса стартуют одновременно и попадают на прогретый процесс → mean 0.044 s. Поэтому conc=2 кажется «быстрее» — это артефакт прогрева, а не реальное масштабирование. Ограничение отмечено.
   - Разница wall_s vs gen_s — ожидание в сетевом стеке + оверхед HTTP поверх собственно генерации. Для tiny-модели gen_s ~ 0.01–0.1 s, wall_s ~ 0.02–1.1 s.
   - Выводов про p95 не делаем: n=4 на режим, tiny-модель, CPU.

9. STUB опыт A → B → A
   - Старт сервиса на A. Опубликован B в другом процессе → старый сервис отдаёт model_id=fixture-A (test_version_reflects_loaded_not_advertised, зелёный прогон). Перезапуск → model_id=fixture-B.
   - Управляемый откат: accepted.json = manifest-A.json → перезапуск → A.
   - Реальный smoke tiny-gpt2 выполнен отдельно (logs/real_valid.json), не смешивается со STUB-опытами.

10. Ограничения
    - tiny-gpt2, качество не оценено, synthetic_metrics=true.
    - Последовательный backend (transformers.generate); не измеряются batching, prefix reuse, TTFT, ITL.
    - KV-cache не оптимизирован; prefill/decode не разделяются.
    - Малая выборка (n=4 на режим, CPU, холодный старт в conc=1).
    - MLflow, SGLang, vLLM не запускались.

11. Ссылка на видео
    - <заполнить после записи экрана>
"""
Path("REPORT.txt").write_text(report, encoding="utf-8")
print("REPORT.txt written:", Path("REPORT.txt").stat().st_size, "bytes")
