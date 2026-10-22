"""
llm_integration.py
AI Content Creator - The Messenger

Responsibility:
Send a system prompt + user prompt to the OpenAI API and return the
generated draft plus metadata (model, tokens, cost, latency, status).
This is the only file that talks to the API.

Settings come from .env (loaded by main.py, or by the self-check below):
    OPENAI_API_KEY   your key (never in code)
    LLM_MODEL        model name, e.g. gpt-4o-mini

provider="mock" gives a free, offline answer for testing the pipeline.
This module does NOT build prompts and does NOT retrieve context.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

FALLBACK_MODEL = "gpt-4o-mini"      # used when LLM_MODEL is not set in .env

# Price in USD per 1 million tokens: (input, output).
# Fill in from OpenAI's pricing page. Unknown models -> cost = None.
PRICES_PER_MILLION = {
    # "gpt-4o-mini": (0.15, 0.60),
}

DEFAULT_MAX_TOKENS = 1200
DEFAULT_TIMEOUT = 60        # seconds per request
DEFAULT_RETRIES = 2         # SDK retries on rate limits, timeouts, 5xx

USAGE_LOG = Path(__file__).resolve().parent.parent / "outputs" / "usage_log.jsonl"


def default_model():
    """Read LLM_MODEL at call time, so it works no matter when .env is loaded."""
    return os.getenv("LLM_MODEL") or FALLBACK_MODEL


# --------------------------------------------------
# 2. PROVIDER CALLS
# Each returns: (text, input_tokens, output_tokens)
# --------------------------------------------------

def _call_openai(prompt, system, model, max_tokens, temperature, timeout, retries):
    from openai import OpenAI
    client = OpenAI(timeout=timeout, max_retries=retries)   # key from OPENAI_API_KEY
    params = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
    if system:
        params["instructions"] = system      # the SYSTEM prompt
    if temperature is not None:              # some newer models reject temperature
        params["temperature"] = temperature
    response = client.responses.create(**params)
    usage = response.usage
    return response.output_text, usage.input_tokens, usage.output_tokens


def _call_mock(prompt, system, model, max_tokens, temperature, timeout, retries):
    """Fake response so the whole pipeline can be tested for free."""
    topic_line = next((l for l in prompt.splitlines() if l.startswith("Topic:")), "Topic: ?")
    text = (f"[MOCK DRAFT] {topic_line[7:]}\n\n"
            "This is a placeholder post generated without calling an API.\n"
            "Run without --mock for real content.")
    return text, (len(system or "") + len(prompt)) // 4, len(text) // 4   # rough estimate


PROVIDERS = {"openai": _call_openai, "mock": _call_mock}


# --------------------------------------------------
# 3. HELPERS: COST, ERRORS, LOGGING
# --------------------------------------------------

def estimate_cost(model, input_tokens, output_tokens):
    """Return cost in USD, or None if the model's price is unknown."""
    if model not in PRICES_PER_MILLION:
        return None
    price_in, price_out = PRICES_PER_MILLION[model]
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)


def _friendly_error(error, model):
    """Turn SDK exceptions into a short, readable message."""
    name = type(error).__name__
    messages = {
        "AuthenticationError": "OPENAI_API_KEY is wrong or revoked. Check your .env file.",
        "PermissionDeniedError": f"This API key has no access to model '{model}'.",
        "NotFoundError": f"Model '{model}' not found. Check LLM_MODEL in .env.",
        "RateLimitError": "Rate limit or quota reached, even after retries. Check your OpenAI billing.",
        "APITimeoutError": "The request timed out, even after retries.",
        "APIConnectionError": "Could not reach the OpenAI API. Check your internet connection.",
        "BadRequestError": f"The API rejected the request for '{model}' (prompt too long or bad parameter).",
        "InternalServerError": "OpenAI had a server error, even after retries. Try again later.",
        "ModuleNotFoundError": "OpenAI SDK not installed: pip install -r requirements.txt",
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

def generate_content(prompt, system=None, provider="openai", model=None,
                     max_tokens=DEFAULT_MAX_TOKENS, temperature=None,
                     timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES, log=True):
    """
    Send a USER prompt (and optional SYSTEM prompt) to the LLM.

    Returns
    -------
    dict with keys:
        text, status ("success" | "error"), error,
        provider, model, input_tokens, output_tokens,
        cost_usd, latency_s, timestamp
    It never raises on API errors: check result["status"].
    """
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(PROVIDERS)}")
    if not prompt or not prompt.strip():
        raise ValueError("Prompt is empty.")
    model = model or (default_model() if provider == "openai" else "mock-model")

    result = {"text": "", "status": "error", "error": None,
              "provider": provider, "model": model,
              "input_tokens": 0, "output_tokens": 0, "cost_usd": None,
              "latency_s": None, "timestamp": datetime.now().isoformat(timespec="seconds")}

    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        result["error"] = "OPENAI_API_KEY is not set. Add it to the .env file in the project root."
        return result

    start = time.perf_counter()
    try:
        text, tokens_in, tokens_out = PROVIDERS[provider](
            prompt, system, model, max_tokens, temperature, timeout, retries)
        result.update(text=(text or "").strip(), status="success",
                      input_tokens=tokens_in, output_tokens=tokens_out,
                      cost_usd=estimate_cost(model, tokens_in, tokens_out))
        if not result["text"]:
            result.update(status="error", error="The model returned an empty response.")
    except Exception as error:
        result["error"] = _friendly_error(error, model)
    result["latency_s"] = round(time.perf_counter() - start, 2)

    if log:
        log_usage(result)
    return result


# --------------------------------------------------
# 5. SELF-CHECK
#   python src/llm_integration.py          one real call (costs a fraction of a cent)
#   python src/llm_integration.py --mock   free, no API call
# --------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    test_provider = "mock" if "--mock" in sys.argv else "openai"
    test_system = "You are a concise LinkedIn writer. Never invent facts."
    test_prompt = "Topic: When should companies use RAG?\nWrite a 2-sentence LinkedIn post."

    result = generate_content(test_prompt, system=test_system, provider=test_provider, log=False)
    print(f"Status:   {result['status']}")
    if result["error"]:
        print(f"Error:    {result['error']}")
    print(f"Model:    {result['provider']} / {result['model']}")
    print(f"Tokens:   {result['input_tokens']} in, {result['output_tokens']} out")
    print(f"Cost:     {result['cost_usd'] if result['cost_usd'] is not None else 'unknown'}")
    print(f"Latency:  {result['latency_s']}s\n")
    print(result["text"])