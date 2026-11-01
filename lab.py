"""Исполняемый прототип для расследования. Только синтетические данные, без модели."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import release


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def initialize(root):
    if root.exists():
        raise FileExistsError('Рабочий каталог уже существует. Выберите новый --workspace.')
    root.mkdir(parents=True)
    runtime = {'base_revision': 'fixture-only', 'tokenizer_sha256': 'a' * 64,
               'template_sha256': 'b' * 64,
               'generation': {'max_new_tokens': 32, 'do_sample': False},
               'dtype': 'float32'}
    for version in ['A', 'B']:
        artifact = root / f'model-{version}.txt'
        artifact.write_text(f'STUB ONLY — version {version}\n')
        files = {artifact.name: digest(artifact.read_bytes())}
        m = {'schema_version': 1, 'model_id': f'fixture-{version}',
             'artifact_uri': artifact.name, 'model_sha256': digest(canonical(files)),
             'protocol_sha256': 'd' * 64, 'golden_sha256': 'e' * 64,
             'runtime_sha256': digest(canonical(runtime)), 'runtime': runtime,
             'file_hashes': files}
        report = {k: m[k] for k in ['model_id', 'model_sha256', 'protocol_sha256',
                                    'golden_sha256', 'runtime_sha256']}
        report.update(status='complete', passed=True,
                      evaluation_run_id=f'fixture-eval-{version}',
                      metrics={'accuracy': .8, 'format_rate': 1.0}, synthetic=True)
        write(root / f'manifest-{version}.json', m)
        write(root / f'report-{version}.json', report)
    write(root / 'accepted.json', read(root / 'manifest-A.json'))
    report = read(root / 'report-B.json')
    report['status'] = 'running'
    report['passed'] = 'false'
    write(root / 'report-incomplete.json', report)
    report = read(root / 'report-B.json')
    report['passed'] = False
    write(root / 'report-reject.json', report)
    write(root / 'config.json', {'tokenizer_revision': 'r1',
                                 'template_sha256': 'b' * 64,
                                 'max_length': 128,
                                 'code_revision': 'prepare-v1'})
    (root / 'input.txt').write_text('Первый пример\nВторой пример\n')
    print('Создан синтетический стенд:', root)


def prepare(root):
    config = read(root / 'config.json')
    key = release.cache_key(root / 'input.txt', config)
    cache = root / 'cache'
    cache.mkdir(exist_ok=True)
    entry = cache / (key + '.json')
    if entry.exists():
        result = read(entry)
        print('CACHE_HIT', result['input_sha256'])
        return result
    payload = (root / 'input.txt').read_bytes()
    result = {'input_sha256': digest(payload),
              'rows': len(payload.splitlines()), 'config': config}
    write(entry, result)
    print('PREPARED', result['input_sha256'])
    return result


def release_id(manifest, report):
    payload = {
        'model_id': manifest['model_id'],
        'model_sha256': manifest['model_sha256'],
        'runtime_sha256': manifest['runtime_sha256'],
        'evaluation_run_id': report['evaluation_run_id'],
    }
    return digest(canonical(payload))


def _append_jsonl(path, entry):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _release_already_logged(log_path, rid):
    if not log_path.exists():
        return False
    for line in log_path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get('release_id') == rid:
                return True
        except json.JSONDecodeError:
            continue
    return False


def run(root, report_name, fail_after_prepare=False, fail_after_publish=False):
    attempts = root / 'attempts.jsonl'

    def log_attempt(status, **kw):
        _append_jsonl(attempts, {'ts': time.time(), 'status': status, **kw})

    prepared = prepare(root)
    if fail_after_prepare:
        log_attempt('failed_after_prepare')
        raise RuntimeError('Инъекция сбоя после подготовки')

    manifest = read(root / 'manifest-B.json')
    report = read(root / report_name)
    try:
        release.publish(manifest, report, root / 'accepted.json')
    except Exception as e:
        log_attempt('publish_rejected', error=type(e).__name__, message=str(e))
        raise
    if fail_after_publish:
        log_attempt('failed_after_publish_before_log')
        raise RuntimeError('Инъекция сбоя между указателем и журналом')

    rid = release_id(manifest, report)
    log = root / 'publications.jsonl'
    already = _release_already_logged(log, rid)
    if not already:
        _append_jsonl(log, {'release_id': rid, 'model_id': manifest['model_id'],
                            'prepared_sha256': prepared['input_sha256']})
    log_attempt('published', release_id=rid, duplicate=already)
    print('PUBLISHED', manifest['model_id'], 'release_id=' + rid,
          'duplicate=' + str(already))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, default=Path('.lab'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    rp = sub.add_parser('run')
    rp.add_argument('--report', default='report-B.json')
    rp.add_argument('--fail-after-prepare', action='store_true')
    rp.add_argument('--fail-after-publish', action='store_true')
    args = parser.parse_args()
    if args.command == 'init':
        initialize(args.workspace)
    else:
        run(args.workspace, args.report, args.fail_after_prepare, args.fail_after_publish)


if __name__ == '__main__':
    main()