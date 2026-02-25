from services.shared.chunking import chunk_text


def test_chunk_text_is_deterministic() -> None:
    text = "A" * 3000
    left = chunk_text(text, chunk_size=500, overlap=100)
    right = chunk_text(text, chunk_size=500, overlap=100)
    assert left == right
    assert len(left) > 1
