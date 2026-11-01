"""Общий интерфейс backend для lab, flow, API и тестов."""
import json
import time
from pathlib import Path


class Backend:
    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.model_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = 0

    def load(self):
        raise NotImplementedError

    def generate(self, prompt: str, max_new_tokens: int) -> dict:
        raise NotImplementedError


class StubBackend(Backend):
    def load(self):
        return {'loaded': self.model_id, 'stub': True}

    def generate(self, prompt, max_new_tokens):
        self.calls += 1
        time.sleep(0.01)
        return {'text': f'STUB ONLY: {self.model_id}', 'output_tokens': 1}


class RealBackend(Backend):
    """Реальная модель через transformers. Адаптер PEFT — опционально."""

    def __init__(self, manifest, model_dir: Path, tokenizer_dir: Path | None = None,
                 adapter_dir: Path | None = None):
        super().__init__(manifest)
        self.model_dir = Path(model_dir)
        self.tokenizer_dir = Path(tokenizer_dir) if tokenizer_dir else None
        self.adapter_dir = Path(adapter_dir) if adapter_dir else None
        self.tok = None
        self.model = None

    def load(self):
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch

        tok_src = self.tokenizer_dir or self.manifest['runtime'].get('base_model_id', 'sshleifer/tiny-gpt2')
        self.tok = AutoTokenizer.from_pretrained(str(tok_src), trust_remote_code=True)
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token

        dtype = getattr(torch, self.manifest['runtime'].get('dtype', 'float32'))
        self.model = AutoModelForCausalLM.from_pretrained(
            str(self.model_dir), torch_dtype=dtype, trust_remote_code=True,
        )
        if self.adapter_dir:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, str(self.adapter_dir))
        self.model.eval()
        return {'loaded': self.model_id, 'stub': False, 'adapter': bool(self.adapter_dir)}

    def generate(self, prompt, max_new_tokens):
        import torch
        self.calls += 1
        inputs = self.tok(prompt, return_tensors='pt')
        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens,
                do_sample=False, pad_token_id=self.tok.eos_token_id,
            )
        gen = out[0][inputs['input_ids'].shape[1]:]
        return {'text': self.tok.decode(gen, skip_special_tokens=True),
                'output_tokens': int(gen.shape[0])}
