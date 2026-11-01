"""Корректная реализация трёх контрактов (см. CONTRACTS.txt)."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False,
    ).encode('utf-8')


def cache_key(data_path: Path, config: dict) -> str:
    data_sha256 = hashlib.sha256(Path(data_path).read_bytes()).hexdigest()
    payload = {'data_sha256': data_sha256, 'config': config}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _need_sha(obj: dict, name: str, where: str) -> None:
    value = obj.get(name)
    if not isinstance(value, str) or not _HEX64.match(value):
        raise ValueError(f'{where}.{name}: ожидается lowercase SHA-256 hex')


def _need_nonempty_str(obj: dict, name: str, where: str) -> None:
    value = obj.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f'{where}.{name}: ожидается непустая строка')


def validate_release(manifest: dict, report: dict) -> None:
    if not isinstance(manifest, dict):
        raise ValueError('manifest должен быть dict')
    if not isinstance(report, dict):
        raise ValueError('report должен быть dict')

    # --- manifest ---
    sv = manifest.get('schema_version')
    if not isinstance(sv, int) or isinstance(sv, bool) or sv != 1:
        raise ValueError('manifest.schema_version: ожидается int 1')
    _need_nonempty_str(manifest, 'model_id', 'manifest')
    _need_nonempty_str(manifest, 'artifact_uri', 'manifest')
    for name in ('model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        _need_sha(manifest, name, 'manifest')

    runtime = manifest.get('runtime')
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('manifest.runtime: ожидается непустой dict')
    recomputed = hashlib.sha256(_canonical(runtime)).hexdigest()
    if recomputed != manifest['runtime_sha256']:
        raise ValueError(
            f'runtime_sha256 не совпадает с пересчитанным из runtime: '
            f'{manifest["runtime_sha256"]} != {recomputed}'
        )

    # --- report ---
    if report.get('status') != 'complete':
        raise ValueError('report.status: ожидается "complete"')
    if report.get('passed') is not True:
        raise ValueError('report.passed: ожидается именно bool True')
    _need_nonempty_str(report, 'evaluation_run_id', 'report')

    if report.get('model_id') != manifest['model_id']:
        raise ValueError('report.model_id не совпадает с manifest.model_id')
    for name in ('model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        if report.get(name) != manifest[name]:
            raise ValueError(f'report.{name} не совпадает с manifest.{name}')

    metrics = report.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('report.metrics: ожидается dict')
    for name in ('accuracy', 'format_rate'):
        v = metrics.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f'report.metrics.{name}: ожидается number, не bool/str')
        if not math.isfinite(v):
            raise ValueError(f'report.metrics.{name}: NaN/Inf запрещены')
        if not (0.0 <= float(v) <= 1.0):
            raise ValueError(f'report.metrics.{name}: ожидается диапазон [0,1]')


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')

    # Идемпотентность: если байты совпадают — не трогаем файл вообще.
    if target.exists() and target.read_bytes() == payload:
        return

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent),
                                    prefix=target.name + '.', suffix='.tmp')
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise