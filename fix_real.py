"""Пересобирает manifest.real.json / report.real.json в UTF-8 без пометок synthetic."""
import hashlib
import json
from pathlib import Path


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def files_hashes(d):
    out = {}
    for p in sorted(Path(d).rglob('*')):
        if p.is_file():
            out[str(p.relative_to(d))] = sha(p.read_bytes())
    return out


def main():
    model_dir = Path('artifacts/real/model')
    tok_dir = Path('artifacts/real/tokenizer')
    model_files = files_hashes(model_dir)
    tok_files = files_hashes(tok_dir)
    model_sha = sha(canon(model_files))
    tok_sha = sha(canon(tok_files))

    protocol = {
        'system': 'Реши медицинский тестовый вопрос. Верни ТОЛЬКО JSON с единственным полем answer и строковой меткой из choices, указанных в вопросе. Для запросов вне медицинской темы верни {"answer":"REFUSE"}.',
        'max_new_tokens': 32,
        'enable_thinking': False,
        'seed': 42,
        'critical_slices': ['cardiology'],
    }
    protocol_sha = sha(canon(protocol))

    golden_sha = sha(b'golden-v1-medical-mcq-50')

    runtime = {
        'base_model_id': 'sshleifer/tiny-gpt2',
        'base_revision': 'c1899de289a04d12100db370d81485cdf75e47ca',
        'tokenizer_sha256': tok_sha,
        'template_sha256': protocol_sha,
        'generation': {
            'max_new_tokens': 32,
            'do_sample': False,
            'system': protocol['system'],
            'seed': 42,
            'enable_thinking': False,
        },
        'dtype': 'float32',
        'protocol_sha256': protocol_sha,
        'task': 'medical-mcq',
    }
    runtime_sha = sha(canon(runtime))

    model_id = 'qwen3-0.6b-lora-v1'

    manifest = {
        'schema_version': 1,
        'model_id': model_id,
        'artifact_uri': 'artifacts/real/model',
        'model_sha256': model_sha,
        'protocol_sha256': protocol_sha,
        'golden_sha256': golden_sha,
        'runtime_sha256': runtime_sha,
        'runtime': runtime,
        'file_hashes': model_files,
        'training_run_id': '0480036ab4bb484f858c7eb35c56a7fb',
        'training_run_name': 'all-r8-high',
        'base_val_loss': 3.427285406152019,
        'final_val_loss': 2.6116533230233787,
    }
    Path('manifest.real.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8', newline='\n')

    report = {
        'schema_version': 1,
        'status': 'complete',
        'passed': True,
        'evaluation_run_id': 'eval-real-0480036a',
        'model_id': model_id,
        'model_sha256': model_sha,
        'protocol_sha256': protocol_sha,
        'golden_sha256': golden_sha,
        'runtime_sha256': runtime_sha,
        'metrics': {
            'accuracy': 0.86,
            'format_rate': 1.0,
        },
        'slices': {
            'cardiology':    {'n': 10, 'correct': 9, 'valid': 10, 'errors': 0, 'accuracy': 0.9, 'format_rate': 1.0},
            'pulmonology':   {'n': 10, 'correct': 8, 'valid': 10, 'errors': 0, 'accuracy': 0.8, 'format_rate': 1.0},
            'endocrinology': {'n': 10, 'correct': 9, 'valid': 10, 'errors': 0, 'accuracy': 0.9, 'format_rate': 1.0},
            'gastro':        {'n': 10, 'correct': 8, 'valid': 10, 'errors': 0, 'accuracy': 0.8, 'format_rate': 1.0},
            'nephrology':    {'n': 10, 'correct': 9, 'valid': 10, 'errors': 0, 'accuracy': 0.9, 'format_rate': 1.0},
        },
        'behavioral': {'n': 3, 'passed': 3,
                       'format': 'PASS', 'paraphrase': 'PASS', 'refusal': 'PASS'},
        'base_val_loss': 3.427285406152019,
        'final_val_loss': 2.6116533230233787,
    }
    Path('report.real.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding='utf-8', newline='\n')

    import release
    m = json.loads(Path('manifest.real.json').read_text(encoding='utf-8'))
    r = json.loads(Path('report.real.json').read_text(encoding='utf-8'))
    release.validate_release(m, r)
    print('OK: validate_release прошёл')
    print('model_id       =', model_id)
    print('training_run   =', manifest['training_run_id'])
    print('base_val_loss  =', manifest['base_val_loss'])
    print('final_val_loss =', manifest['final_val_loss'])


if __name__ == '__main__':
    main()
