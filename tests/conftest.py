"""Shared test fixtures."""

import pytest


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return (
        b"id,product,country,Event Description,Summary\n"
        b"1,Widget A,US,The device failed to deploy correctly during testing.,Found crack in housing.\n"
        b"2,Widget B,UK,Normal operation observed with no issues.,No defects found.\n"
        b"3,Widget A,US,Battery overheated during charging cycle.,Replaced battery module.\n"
    )


@pytest.fixture
def sample_txt_bytes() -> bytes:
    return (
        b"This is the first paragraph of a test document. It contains some text "
        b"that should be chunked by the semantic chunker.\n\n"
        b"This is the second paragraph. It discusses a completely different topic "
        b"about machine learning and natural language processing.\n\n"
        b"The third paragraph covers database design patterns and best practices "
        b"for handling concurrent connections in production systems.\n"
    )


@pytest.fixture
def mock_embed_fn():
    """Return a fake embedding function that produces deterministic vectors."""
    def _embed(texts: list[str]) -> list[list[float]]:
        return [[float(i) / 10.0] * 384 for i, _ in enumerate(texts)]
    return _embed
