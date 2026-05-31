"""
image_generator.py — switchable AI image provider (the "flux" media source).

IMAGE_PROVIDER (default "pollinations"):
    pollinations    FLUX via Pollinations.ai — FREE, no API key, always online
    cloudflare      Cloudflare Workers AI (FLUX.2 klein) — free 10k neurons/day
    hf_inference    HuggingFace Inference (FLUX.1-schnell)
    local_diffusers Z-Image-Turbo / FLUX.1-schnell on a local GPU

All providers expose the same `generate_image(prompt) -> bytes` contract, so
switching is a config change with no code change (mirrors Synapse Core).
"""

import os
import urllib.parse

import requests


def _gen_pollinations(prompt: str, width: int, height: int) -> bytes:
    """FREE, no API key. FLUX via Pollinations.ai — always deployed."""
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
    r = requests.get(url, params={"model": "flux", "width": width, "height": height,
                                  "nologo": "true"}, timeout=120)
    r.raise_for_status()
    return r.content


def _gen_cloudflare(prompt: str, width: int, height: int) -> bytes:
    acc = os.environ["CF_ACCOUNT_ID"]
    tok = os.environ["CF_API_TOKEN"]
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acc}"
           f"/ai/run/@cf/black-forest-labs/flux-1-schnell")
    r = requests.post(url, headers={"Authorization": f"Bearer {tok}"},
                      json={"prompt": prompt}, timeout=120)
    r.raise_for_status()
    data = r.json()
    import base64
    return base64.b64decode(data["result"]["image"])


def _gen_hf(prompt: str, width: int, height: int) -> bytes:
    from huggingface_hub import InferenceClient
    client = InferenceClient(token=os.environ["HF_TOKEN"])
    img = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-schnell")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gen_local(prompt: str, width: int, height: int) -> bytes:
    import io

    import torch
    from diffusers import DiffusionPipeline
    model = os.getenv("LOCAL_IMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
    pipe = DiffusionPipeline.from_pretrained(model, torch_dtype=torch.bfloat16)
    pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    img = pipe(prompt, num_inference_steps=8, width=width, height=height).images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_PROVIDERS = {
    "pollinations": _gen_pollinations,
    "cloudflare": _gen_cloudflare,
    "hf_inference": _gen_hf,
    "local_diffusers": _gen_local,
}


def generate_image(prompt: str, *, provider: str | None = None,
                   width: int = 1280, height: int = 720) -> bytes:
    """Generate a single image and return PNG/JPEG bytes."""
    provider = (provider or os.getenv("IMAGE_PROVIDER", "pollinations")).lower()
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise ValueError(f"Unknown IMAGE_PROVIDER '{provider}'. Choose from {list(_PROVIDERS)}.")
    return fn(prompt, width, height)
