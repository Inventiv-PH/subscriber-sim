"""
Modal GPU compute — Jasmin inference.

Deploy once:
    modal deploy scripts/modal_server.py

The Streamlit app calls this directly via Modal client (no HTTP server needed).
"""

from pathlib import Path
from threading import Thread

import modal

app  = modal.App("jasmin-inference")

ADAPTER_DIR = Path(__file__).parent.parent / "models" / "adapter"

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04",
        add_python="3.11",
    )
    .pip_install(
        "torch>=2.4.0",
        "transformers>=4.40.0",
        "peft>=0.10.0",
        "accelerate>=0.27.0",
        "bitsandbytes>=0.43.0",
        "safetensors>=0.4.0",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    .add_local_dir(ADAPTER_DIR, remote_path="/adapter")
)

volume = modal.Volume.from_name("jasmin-model-cache", create_if_missing=True)
MODEL_CACHE = "/cache"
BASE_MODEL  = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"


@app.cls(
    image=image,
    gpu="T4",
    volumes={MODEL_CACHE: volume},
    scaledown_window=300,
    timeout=120,
)
class JasminModel:

    @modal.enter()
    def load(self):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print("Loading tokenizer…")
        self.tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL, cache_dir=MODEL_CACHE
        )
        self.tokenizer.pad_token = self.tokenizer.eos_token

        print("Loading base model…")
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.float16,
            device_map="auto",
            cache_dir=MODEL_CACHE,
        )

        print("Merging LoRA adapter…")
        base = PeftModel.from_pretrained(base, "/adapter")
        self.model = base.merge_and_unload()
        self.model.eval()
        volume.commit()
        print("✅ Ready")

    @modal.method()
    def generate(self, messages: list[dict], stop: list[str], max_tokens: int,
                 temperature: float, top_p: float, rep_pen: float):
        """Yields response tokens — call with .remote_gen() from the client."""
        from transformers import TextIteratorStreamer

        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)

        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True
        )

        Thread(
            target=self.model.generate,
            kwargs=dict(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repetition_penalty=rep_pen,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
                streamer=streamer,
            ),
            daemon=True,
        ).start()

        buf = ""
        for token in streamer:
            buf += token
            for s in stop:
                if s in buf:
                    yield buf[:buf.index(s)]
                    return
            yield buf
            buf = ""
