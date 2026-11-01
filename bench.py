"""Мини-замер сервиса. Стучится в уже запущенный HTTP-сервис."""
import argparse
import concurrent.futures
import csv
import json
import time
import urllib.error
import urllib.request


def one_call(url, prompt, limit, req_id):
    started = time.perf_counter()
    req = urllib.request.Request(
        url, data=json.dumps({'prompt': prompt, 'max_new_tokens': limit}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    try:
        r = urllib.request.urlopen(req, timeout=120)
        body = json.loads(r.read())
        status = r.status
        error = ''
    except urllib.error.HTTPError as e:
        body = {}
        status = e.code
        error = e.read().decode(errors='replace')[:200]
    except Exception as e:
        body = {}
        status = 0
        error = f'{type(e).__name__}: {e}'[:200]
    wall = time.perf_counter() - started
    return {
        'id': req_id, 'status': status, 'error': error,
        'wall_s': round(wall, 4),
        'gen_s': round(body.get('generation_seconds', 0.0), 4) if body else 0.0,
        'model_id': body.get('model_id', ''),
        'output_tokens': body.get('output_tokens', 0),
    }


def run_batch(port, n, concurrency, limit):
    url = f'http://127.0.0.1:{port}/generate'
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(one_call, url, f'hello {i}', limit, i) for i in range(n)]
        rows = [f.result() for f in concurrent.futures.as_completed(futures)]
    return time.perf_counter() - t0, rows


def summarize(total, rows):
    ok = [r for r in rows if r['status'] == 200]
    bad = [r for r in rows if r['status'] != 200]
    ok_wall = [r['wall_s'] for r in ok]
    return {
        'n': len(rows), 'ok': len(ok), 'errors': len(bad),
        'total_s': round(total, 3),
        'ok_rps': round(len(ok) / total, 3) if total else 0.0,
        'mean_wall_ok_s': round(sum(ok_wall) / len(ok_wall), 3) if ok_wall else 0.0,
        'max_wall_ok_s': round(max(ok_wall), 3) if ok_wall else 0.0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8092)
    p.add_argument('--limit', type=int, default=16)
    p.add_argument('--n', type=int, default=8)
    p.add_argument('--out', default='results.csv')
    args = p.parse_args()
    all_rows = []
    for conc in (1, 2):
        total, rows = run_batch(args.port, args.n, conc, args.limit)
        for r in rows:
            r['mode'] = f'concurrency={conc}'
            r['limit'] = args.limit
        all_rows.extend(rows)
        print(f'concurrency={conc}:', summarize(total, rows))
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['mode', 'id', 'status', 'error',
                                          'wall_s', 'gen_s', 'model_id',
                                          'output_tokens', 'limit'])
        w.writeheader()
        w.writerows(all_rows)


if __name__ == '__main__':
    main()
