"""FastAPI на реальной модели из manifest.real.json."""
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend import RealBackend

MAX_NEW_TOKENS = 32
MAX_PROMPT_CHARS = 4096
MANIFEST = Path('manifest.real.json')


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    max_new_tokens: int = Field(16, ge=1, le=MAX_NEW_TOKENS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    manifest = json.loads(MANIFEST.read_text())
    model_dir = Path(manifest['artifact_uri'])
    adapter = Path('artifacts/real/adapter')
    adapter = adapter if adapter.exists() else None
    backend = RealBackend(manifest, model_dir=model_dir,
                          tokenizer_dir=Path('artifacts/real/tokenizer'),
                          adapter_dir=adapter)
    backend.load()
    app.state.backend = backend
    yield


app = FastAPI(lifespan=lifespan)


@app.get('/health')
def health():
    return {'alive': True}


@app.get('/ready')
def ready():
    return {'ready': app.state.backend is not None}


@app.get('/debug')
def debug():
    b = app.state.backend
    return {'loaded_id': b.model_id, 'calls': b.calls,
            'runtime_sha256': b.runtime_sha256}


@app.post('/generate')
def generate(req: GenerateRequest):
    b = app.state.backend
    t0 = time.perf_counter()
    out = b.generate(req.prompt, req.max_new_tokens)
    return {
        'text': out['text'],
        'request_id': str(uuid.uuid4()),
        'model_id': b.model_id,
        'runtime_sha256': b.runtime_sha256,
        'output_tokens': out['output_tokens'],
        'generation_seconds': time.perf_counter() - t0,
    }
