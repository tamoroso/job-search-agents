from functools import lru_cache
from anthropic import Anthropic
from jobagent.agents.config import MODELS
from jobagent.db.session import session_scope
from jobagent.db.models.observability import LLMCall
import time

class LLMCallError(Exception) : 
    """Error while adding new LLMCall entry"""

def compute_cost(model_tier, input_tokens, output_tokens) :
    model_data = MODELS[model_tier]
    price_in = model_data.price_in
    price_out = model_data.price_out
    return (input_tokens * price_in / 10**6 ) + (output_tokens * price_out / 10**6 ) if input_tokens != None and output_tokens != None else None

@lru_cache
def get_client() -> Anthropic : 
    return Anthropic()

def call_llm(prompt, trace_id=None):
    model_tier = prompt.model_tier
    model = MODELS[model_tier].id
    input_tokens = output_tokens = None
    success = False
    start = time.perf_counter()
    try:
        response = get_client().messages.parse(
            model = model,
            max_tokens = 1024,
            messages = [
                {
                    "role" : "user",
                    "content" : prompt.body
                }
            ],
            output_format = prompt.output_schema,
        )
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        success = True
        return response.parsed_output
    finally:
        try : 
            with session_scope() as session : 
                session.add(
                    LLMCall(
                    trace_id = trace_id,
                    agent = prompt.agent,
                    prompt_version = prompt.version,
                    model = model,
                    input_tokens = input_tokens,
                    output_tokens = output_tokens,
                    cost_usd = compute_cost(model_tier, input_tokens, output_tokens),
                    latency_ms = time.perf_counter() - start,
                    success = success,
                ))
        except Exception as e : 
            raise LLMCallError(f"unable to create LLMCall entry : {str(e)}") from e
        