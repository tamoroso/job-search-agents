from pydantic import BaseModel
import os

class ModelTier(BaseModel):
    id : str
    price_in : float
    price_out : float

MODELS : dict[str, ModelTier] = {
    "small": ModelTier(id = "claude-haiku-4-5-20251001", price_in = 1, price_out = 5), # per Million tokens
    "large" : ModelTier(id = "claude-sonnet-5", price_in = 2, price_out = 10) # per Million tokens
}