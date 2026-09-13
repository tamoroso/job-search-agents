from sentence_transformers import SentenceTransformer
from functools import cache

class EmbedException(Exception) :
    """ Error while embedding sentences """

@cache
def get_model():
    return SentenceTransformer("BAAI/bge-m3")


def embed(texts, encode_method) :
    print(get_model().max_seq_length)
    try : 
        embeddings = get_model().encode_query(texts, normalize_embeddings = True ) if encode_method == "query" else get_model().encode_document(texts)
        return embeddings
    except Exception as e :
        raise EmbedException() from e 