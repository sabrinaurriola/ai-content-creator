"""
llm_integration.py
AI Content Creator - The Messenger

Responsibility:
Send a finished prompt (from prompt_templates.py) to an LLM and return
the generated draft plus metadata (model, tokens, cost, latency, status).

Supported providers: "openai", "anthropic", and "mock" (free, offline,
for testing the pipeline without an API key).

This module does NOT build prompts and does NOT retrieve context.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv      # optional: reads API keys from .env
    load_dotenv()
except ImportError:
    pass


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# Change these in .env (OPENAI_MODEL=..., ANTHROPIC_MODEL=...).
# Check each provider's model list for the current names.
DEFAULT_MODELS = {
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
    "mock": "mock-model",
}

# Price in USD per 1 million tokens: (input, output).
# Fill in from the providers' pricing pages. Unknown models -> cost = None.
PRICES_PER_MILLION = {
    # "gpt-4o-mini": (0.15, 0.60),
}

DEFAULT_MAX_TOKENS = 1200
DEFAULT_TIMEOUT = 60        # seconds per request
DEFAULT_RETRIES = 2         # SDK retries on rate limits, timeouts, 5xx

USAGE_LOG = Path(__file__).resolve().parent.parent / "outputs" / "usage_log.jsonl"


# --------------------------------------------------
# 2. PROVIDER CALLS
# Each returns: (text, input_tokens, output_tokens)
# --------------------------------------------------

def _call_openai(prompt, model, max_tokens, temperature, timeout, retries):
    from openai import OpenAI
    client = OpenAI(timeout=timeout, max_retries=retries)   # key from OPENAI_API_KEY
    params = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
    if temperature is not None:          # some newer models reject temperature
        params["temperature"] = temperature
    response = client.responses.create(**params)
    usage = response.usage
    return response.output_text, usage.input_tokens, usage.output_tokens


def _call_anthropic(prompt, model, max_tokens, temperature, timeout, retries):
    from anthropic import Anthropic
    client = Anthropic(timeout=timeout, max_retries=retries)  # key from ANTHROPIC_API_KEY
    params = {"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if temperature is not None:
        params["temperature"] = temperature
    response = client.messages.create(**params)
    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response.usage.input_tokens, response.usage.output_tokens


def _call_mock(prompt, model, max_tokens, temperature, timeout, retries):
    """Fake response so the whole pipeline can be tested for free."""
    topic_line = next((l for l in prompt.splitlines() if l.startswith("Topic:")), "Topic: ?")
    text = (f"[MOCK DRAFT] {topic_line[7:]}\n\n"
            "This is a placeholder post generated without calling an API.\n"
            "Switch LLM_PROVIDER to 'openai' or 'anthropic' for real content.")
    return text, len(prompt) // 4, len(text) // 4      # rough token estimate


PROVIDERS = {"openai": _call_openai, "anthropic": _call_anthropic, "mock": _call_mock}


# --------------------------------------------------
# 3. HELPERS: COST, ERRORS, LOGGING
# --------------------------------------------------

def estimate_cost(model, input_tokens, output_tokens):
    """Return cost in USD, or None if the model's price is unknown."""
    if model not in PRICES_PER_MILLION:
        return None
    price_in, price_out = PRICES_PER_MILLION[model]
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


def _friendly_error(error):
    """Turn SDK exceptions into a short, readable message."""
    name = type(error).__name__
    messages = {
        "AuthenticationError": "Invalid or missing API key. Check your .env file.",
        "PermissionDeniedError": "This API key has no access to that model.",
        "NotFoundError": "Model not found. Check the model name.",
        "RateLimitError": "Rate limit or quota reached, even after retries.",
        "APITimeoutError": "The request timed out, even after retries.",
        "APIConnectionError": "Could not reach the API. Check your internet connection.",
        "BadRequestError": "The API rejected the request (prompt too long or bad parameter).",
        "InternalServerError": "The provider had a server error, even after retries.",
        "ModuleNotFoundError": "SDK not installed: pip install openai anthropic",
    }
    return f"{name}: {messages.get(name, str(error))}"


def log_usage(result, log_path=USAGE_LOG):
    """Append one line of metadata (no content) to outputs/usage_log.jsonl."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {k: v for k, v in result.items() if k != "text"}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# --------------------------------------------------
# 4. MAIN FUNCTION
# --------------------------------------------------

def generate_content(prompt, provider=None, model=None,
                     max_tokens=DEFAULT_MAX_TOKENS, temperature=None,
                     timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, log=True):
    """
    Send a prompt to the LLM and return a result dict.

    Returns
    -------
    dict with keys:
        text, status ("success" | "error"), error,
        provider, model, input_tokens, output_tokens,
        cost_usd, latency_s, timestamp
    It never raises on API errors: check result["status"].
    """
    provider = (provider or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(PROVIDERS)}")
    if not prompt or not prompt.strip():
        raise ValueError("Prompt is empty.")
    model = model or DEFAULT_MODELS[provider]

    result = {"text": "", "status": "error", "error": None,
              "provider": provider, "model": model,
              "input_tokens": 0, "output_tokens": 0, "cost_usd": None,
              "latency_s": None, "timestamp": datetime.now().isoformat(timespec="seconds")}

    start = time.perf_counter()
    try:
        text, tokens_in, tokens_out = PROVIDERS[provider](
            prompt, model, max_tokens, temperature, timeout, retries)
        result.update(text=(text or "").strip(), status="success",
                      input_tokens=tokens_in, output_tokens=tokens_out,
                      cost_usd=estimate_cost(model, tokens_in, tokens_out))
        if not result["text"]:
            result.update(status="error", error="The model returned an empty response.")
    except Exception as error:
        result["error"] = _friendly_error(error)
    result["latency_s"] = round(time.perf_counter() - start, 2)

    if log:
        log_usage(result)
    return result


# --------------------------------------------------
# 5. LOCAL TEST: python src/llm_integration.py [provider]
# --------------------------------------------------

if __name__ == "__main__":
    import sys
    test_provider = sys.argv[1] if len(sys.argv) > 1 else "mock"
    test_prompt = "Topic: When should companies use RAG?\nWrite a 3-sentence LinkedIn post."

    result = generate_content(test_prompt, provider=test_provider, log=False)
    print(f"Status:   {result['status']}")
    if result["error"]:
        print(f"Error:    {result['error']}")
    print(f"Model:    {result['provider']} / {result['model']}")
    print(f"Tokens:   {result['input_tokens']} in, {result['output_tokens']} out")
    print(f"Cost:     {result['cost_usd'] if result['cost_usd'] is not None else 'unknown'}")
    print(f"Latency:  {result['latency_s']}s\n")
    print(result["text"])