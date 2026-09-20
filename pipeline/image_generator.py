"""
image_generator.py — switchable AI image provider (the "flux" media source).

IMAGE_PROVIDER:
    pollinations    FLUX via Pollinations.ai — note: the anonymous free tier now
                    returns 402 (Payment Required); needs a token to work.
    cloudflare      Cloudflare Workers AI (FLUX.1 schnell) — free 10k neurons/day
    hf_inference    HuggingFace Inference (FLUX.1-schnell)
    local_diffusers Z-Image-Turbo / FLUX.1-schnell on a local GPU

The FLUX ambience is OPTIONAL: the reel's main content is the animated graphics
(free, local). Enable it by adding 'flux' to MEDIA_SOURCES with a working
provider. All providers share the same generate_image(prompt) -> bytes contract.
"""

import os
import urllib.parse

import requests


def _together_keys() -> list[str]:
    keys = []
    for var in ("TOGETHER_API_KEY", "TOGETHER_API_KEY_2", "TOGETHER_API_KEY_3"):
        v = os.getenv(var)
        if v:
            keys.append(v)
    return keys


# Together rejects a size it cannot tile: the FLUX-family endpoints demand a
# multiple of 64 (FLUX.2 relaxes it to 16) anywhere between 128 and 2048. The
# reel is 1080x1920 and 1080 is a multiple of NEITHER, so every crowd backdrop
# was asked for at a width the API refuses. Snapping to 64 satisfies both
# families at once, and the cost is nothing: the backdrop is resized to the
# frame in animated_graphics.set_background() and then darkened to 38%, so the
# 8px of extra width never survives to be seen.
_SIZE_STEP = 64


def _snap(px: int) -> int:
    """Nearest size Together will accept: a multiple of 64 within [128, 2048]."""
    return max(128, min(2048, round(px / _SIZE_STEP) * _SIZE_STEP))


def _gen_together(prompt: str, width: int, height: int) -> bytes:
    """Together.ai image generation. Rotates through TOGETHER_API_KEY[_2,_3].

    The model is NOT pinned in code beyond the default below, because Together
    retires serverless models without notice: FLUX.1-schnell (and its -Free
    twin) stopped being served and every request 400'd with "non-serverless
    model" long after the key itself was still fine. Keep TOGETHER_IMAGE_MODEL
    pointing at something the /v1/models listing currently reports as type
    "image".
    """
    import base64
    keys = _together_keys()
    if not keys:
        raise RuntimeError("No TOGETHER_API_KEY in environment / .env")
    model = os.getenv("TOGETHER_IMAGE_MODEL",
                      "Rundiffusion/Juggernaut-Lightning-Flux")
    width, height = _snap(width), _snap(height)
    last = None
    for key in keys:
        r = requests.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "prompt": prompt, "width": width,
                  "height": height, "steps": 4, "response_format": "b64_json"},
            timeout=120,
        )
        if r.status_code in (429, 401, 402):
            # Out of credit or throttled on THIS key — the next one may still
            # have balance. A 400 is not retried: a bad model or a bad size is
            # the same on every key, and swallowing it here is what hid a
            # retired model behind a generic "all providers failed".
            last = r
            continue
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])
    if last is not None:
        last.raise_for_status()
    raise RuntimeError("Together image generation failed")


def _gen_fal(prompt: str, width: int, height: int) -> bytes:
    """Fal.ai FLUX schnell — fallback. Uses FAL_API_KEY."""
    key = os.getenv("FAL_API_KEY")
    if not key:
        raise RuntimeError("No FAL_API_KEY in environment / .env")
    r = requests.post(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        json={"prompt": prompt, "image_size": {"width": width, "height": height},
              "num_inference_steps": 4},
        timeout=120,
    )
    r.raise_for_status()
    img_url = r.json()["images"][0]["url"]
    return requests.get(img_url, timeout=60).content


def _gen_pollinations(prompt: str, width: int, height: int) -> bytes:
    """FLUX via Pollinations.ai. Note: anonymous free tier now returns 402."""
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
    "together": _gen_together,
    "fal": _gen_fal,
    "pollinations": _gen_pollinations,
    "cloudflare": _gen_cloudflare,
    "hf_inference": _gen_hf,
    "local_diffusers": _gen_local,
}

# Automatic fallback chain per primary provider (try the next if one fails).
_FALLBACKS = {
    "together": ["fal"],
    "fal": ["together"],
}


def generate_image(prompt: str, *, provider: str | None = None,
                   width: int = 1024, height: int = 1024) -> bytes:
    """Generate a single image, with an automatic fallback chain."""
    provider = (provider or os.getenv("IMAGE_PROVIDER", "together")).lower()
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown IMAGE_PROVIDER '{provider}'. Choose {list(_PROVIDERS)}.")

    chain = [provider, *_FALLBACKS.get(provider, [])]
    last_err = None
    for name in chain:
        try:
            return _PROVIDERS[name](prompt, width, height)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"All image providers failed ({chain}): {last_err}")
