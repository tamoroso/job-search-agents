from unittest.mock import MagicMock

import pytest

import jobagent.embeddings as embeddings_module
from jobagent.embeddings import EmbedException, embed


@pytest.fixture
def fake_model(monkeypatch):
    model = MagicMock()
    model.max_seq_length = 8192
    monkeypatch.setattr(embeddings_module, "get_model", lambda: model)
    return model


def test_embed_query_calls_encode_query_with_normalization(fake_model):
    fake_model.encode_query.return_value = [0.1, 0.2, 0.3]

    result = embed(["hello"], "query")

    fake_model.encode_query.assert_called_once_with(
        ["hello"], normalize_embeddings=True)
    fake_model.encode_document.assert_not_called()
    assert result == [0.1, 0.2, 0.3]


def test_embed_document_calls_encode_document(fake_model):
    fake_model.encode_document.return_value = [0.4, 0.5, 0.6]

    result = embed(["hello"], "document")

    fake_model.encode_document.assert_called_once_with(["hello"])
    fake_model.encode_query.assert_not_called()
    assert result == [0.4, 0.5, 0.6]


@pytest.mark.parametrize("encode_method", ["passage", "", "unknown"])
def test_embed_non_query_method_falls_back_to_encode_document(fake_model, encode_method):
    fake_model.encode_document.return_value = ["embedding"]

    embed(["hello"], encode_method)

    fake_model.encode_document.assert_called_once_with(["hello"])


def test_embed_wraps_encode_query_errors_in_embed_exception(fake_model):
    fake_model.encode_query.side_effect = RuntimeError("boom")

    with pytest.raises(EmbedException):
        embed(["hello"], "query")


def test_embed_wraps_encode_document_errors_in_embed_exception(fake_model):
    fake_model.encode_document.side_effect = RuntimeError("boom")

    with pytest.raises(EmbedException):
        embed(["hello"], "document")


def test_embed_preserves_original_exception_as_cause(fake_model):
    original_error = ValueError("original")
    fake_model.encode_document.side_effect = original_error

    with pytest.raises(EmbedException) as exc_info:
        embed(["hello"], "document")

    assert exc_info.value.__cause__ is original_error


def test_embed_query_returns_vector_with_real_model():
    result = embed(["quel est le salaire pour ce poste ?"], "query")

    assert len(result) == 1
    vec = result[0]
    assert len(vec) == 1024


def test_embed_document_returns_vector_with_real_model():
    result = embed(["Nous recherchons un développeur Python."], "document")

    assert len(result) == 1
    vec = result[0]
    assert len(vec) == 1024


def test_embed_document_compare_similarities():
    embeddings = embed(["I optimized the latency of a scoring pipeline by migrating to ONNX Runtime with dynamic batching.", "Migrating from scikit-learn to ONNX reduced the response time of the scoring service from 340ms to 80ms through batching.",
                        "The tomato garden is growing well this year with plenty of sunshine.", "I like watching science fiction movies on Sunday evenings."], "document")

    similarities = embeddings_module.get_model().similarity(embeddings, embeddings)

    assert similarities[0][1] > similarities[2][3]
