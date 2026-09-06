from functools import lru_cache
from anthropic import Anthropic
from jobagent.agents.config import MODELS

@lru_cache
def get_client() -> Anthropic : 
    return Anthropic()


def call_llm(prompt): 
    try : 
        client = get_client()
        rendered_prompt = prompt.render()
        response = client.message.parse(
            model = MODELS[prompt.model_tier].id,
            max_tokens=1024,
            messages = [
                {"role" : "user",
                "message" : rendered_prompt}
            ]
        )
        #TODO: Add entry to database on llm_call
        return response
    except : 
        raise Exception("llm_call_error")


#TODO: Add test call_llm with trivial schema 