"""FastAPI-версия сервиса ДЗ 8+9+10."""
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend import StubBackend

MAX_NEW_TOKENS = 32
MAX_PROMPT_CHARS = 4096
WORKSPACE = Path('.lab-after')


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    max_new_tokens: int = Field(32, ge=1, le=MAX_NEW_TOKENS)


class State:
    def __init__(self):
        self.backend = None
        self.ready = False
        self.warmup_seconds = 5
        self.accepted_path = WORKSPACE / 'accepted.json'


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = State()
    manifest = json.loads(st.accepted_path.read_text())
    st.backend = StubBackend(manifest)
    st.backend.load()
    st.ready = True           # в этой версии прогрев — мгновенный для stub
    app.state.s = st
    yield


app = FastAPI(lifespan=lifespan)


@app.get('/health')
def health():
    return {'alive': True}


@app.get('/ready')
def ready():
    s: State = app.state.s
    if not s.ready:
        raise HTTPException(503, 'not ready')
    return {'ready': True}


@app.get('/debug')
def debug():
    s: State = app.state.s
    return {'loaded_id': s.backend.model_id,
            'calls': s.backend.calls,
            'warmup_finished': s.ready,
            'runtime_sha256': s.backend.runtime_sha256}


@app.post('/generate')
def generate(req: GenerateRequest):
    s: State = app.state.s
    if not s.ready:
        raise HTTPException(503, 'not ready')
    t0 = time.perf_counter()
    out = s.backend.generate(req.prompt, req.max_new_tokens)
    return {
        'text': out['text'],
        'request_id': str(uuid.uuid4()),
        'model_id': s.backend.model_id,
        'runtime_sha256': s.backend.runtime_sha256,
        'output_tokens': out['output_tokens'],
        'generation_seconds': time.perf_counter() - t0,
    }
