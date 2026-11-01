"""Prefect flow ДЗ 8+9+10. Стадии: подготовка -> проверка артефакта -> gate -> публикация."""
import hashlib
import json
from pathlib import Path

from prefect import flow, task, get_run_logger

import release


def _canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(b):
    return hashlib.sha256(b).hexdigest()


def content_hash(ctx, parameters):
    """Хеш, который инвалидируется при изменении содержимого файлов и аргументов."""
    h = hashlib.sha256()
    for name in ('data_path', 'config_path'):
        p = Path(parameters.get(name, ''))
        if p.exists():
            h.update(name.encode('utf-8'))
            h.update(p.read_bytes())
    for k, v in sorted(parameters.items()):
        if k in ('data_path', 'config_path'):
            continue
        h.update(k.encode('utf-8'))
        h.update(json.dumps(v, sort_keys=True, default=str).encode('utf-8'))
    return h.hexdigest()


@task
def prepare_task(data_path: str, config_path: str, result_dir: str) -> dict:
    logger = get_run_logger()
    cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
    key = release.cache_key(Path(data_path), cfg)
    cache_dir = Path(result_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    entry = cache_dir / (key + '.json')
    if entry.exists():
        logger.info('CACHE_HIT %s', key)
        result = json.loads(entry.read_text(encoding='utf-8'))
        result['from_cache'] = True
        return result
    payload = Path(data_path).read_bytes()
    result = {
        'input_sha256': _digest(payload),
        'rows': len(payload.splitlines()),
        'config': cfg,
        'cache_key': key,
        'from_cache': False,
    }
    entry.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info('PREPARED %s', key)
    return result


@task(persist_result=True)
def check_artifact_task(manifest_path: str) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    base = Path(manifest_path).parent
    for name, expected in manifest.get('file_hashes', {}).items():
        p = base / name
        if not p.exists():
            raise FileNotFoundError(f'artifact file missing: {p}')
        actual = _digest(p.read_bytes())
        if actual != expected:
            raise ValueError(f'file_hashes mismatch for {name}: {actual} != {expected}')
    return {
        'model_id': manifest['model_id'],
        'artifact_uri': manifest['artifact_uri'],
        'model_sha256': manifest['model_sha256'],
        'training_run_id': manifest.get('training_run_id'),
        'training_run_name': manifest.get('training_run_name'),
        'base_val_loss': manifest.get('base_val_loss'),
        'final_val_loss': manifest.get('final_val_loss'),
    }


@task
def gate_task(manifest_path: str, report_path: str) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    release.validate_release(manifest, report)
    return {
        'decision': 'PASS',
        'evaluation_run_id': report['evaluation_run_id'],
        'model_id': manifest['model_id'],
        'metrics': report.get('metrics', {}),
    }


@task
def publish_task(manifest_path: str, report_path: str, target: str) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    release.publish(manifest, report, Path(target))
    return {'target': str(target), 'model_id': manifest['model_id']}


@flow(name='release-flow')
def release_flow(data_path: str, config_path: str, manifest_path: str,
                 report_path: str, accepted_path: str, result_dir: str) -> dict:
    prepared = prepare_task(data_path, config_path, result_dir)
    artifact = check_artifact_task(manifest_path)
    gate = gate_task(manifest_path, report_path)
    published = publish_task(manifest_path, report_path, accepted_path)
    return {
        'prepared': prepared,
        'prepared_source': 'CACHE_HIT' if prepared['from_cache'] else 'PREPARED',
        'artifact': artifact,
        'gate': gate,
        'published': published,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', type=Path, default=Path('.lab-after'))
    ap.add_argument('--report', default='report-B.json')
    ap.add_argument('--manifest', default='manifest-B.json')
    args = ap.parse_args()
    ws = args.workspace
    result = release_flow(
        data_path=str(ws / 'input.txt'),
        config_path=str(ws / 'config.json'),
        manifest_path=str(ws / args.manifest),
        report_path=str(ws / args.report),
        accepted_path=str(ws / 'accepted.json'),
        result_dir=str(ws / 'cache-prefect'),
    )
    print('FLOW_RESULT', json.dumps(result, ensure_ascii=False, indent=2))
