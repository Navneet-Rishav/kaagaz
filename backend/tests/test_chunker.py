from app.domain.chunker import Chunk, chunk_pages


def test_short_pages_become_one_chunk_each_with_page_numbers() -> None:
    chunks = chunk_pages([(1, "Rent is ₹12,000."), (2, "Deposit is ₹24,000.")])
    assert [(c.page, c.text) for c in chunks] == [(1, "Rent is ₹12,000."), (2, "Deposit is ₹24,000.")]
    assert [c.index for c in chunks] == [0, 1]


def test_blank_pages_are_skipped() -> None:
    chunks = chunk_pages([(1, "   \n\n "), (2, "Hello")])
    assert [c.page for c in chunks] == [2]


def test_paragraphs_are_packed_up_to_the_size_limit() -> None:
    paras = [f"Paragraph {i} " + "x" * 280 for i in range(5)]  # ~292 chars each
    chunks = chunk_pages([(3, "\n\n".join(paras))], size=800, overlap=0)
    assert all(c.page == 3 for c in chunks)
    assert all(len(c.text) <= 800 for c in chunks)
    assert len(chunks) == 3  # 2 + 2 + 1 paragraphs
    assert chunks[0].text.startswith("Paragraph 0") and "Paragraph 1" in chunks[0].text


def test_chunks_never_cross_pages() -> None:
    chunks = chunk_pages([(1, "a " * 500), (2, "b " * 500)], size=300, overlap=50)
    for c in chunks:
        assert ("a" in c.text) != ("b" in c.text)
        assert c.page == (1 if "a" in c.text else 2)


def test_long_paragraph_is_split_with_overlap_at_word_boundaries() -> None:
    words = [f"w{i}" for i in range(400)]
    chunks = chunk_pages([(1, " ".join(words))], size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        first_word = nxt.text.split()[0]
        assert first_word in prev.text.split()  # overlap repeats the end of the previous chunk
    # every word survives, nothing cut mid-word
    seen = {w for c in chunks for w in c.text.split()}
    assert seen == set(words)


def test_devanagari_text_keeps_page_and_content() -> None:
    text = "यह किराया अनुबंध है।\n\nमासिक किराया ₹१२,००० होगा।"
    chunks = chunk_pages([(2, text)])
    assert chunks == [Chunk(page=2, index=0, text="यह किराया अनुबंध है।\n\nमासिक किराया ₹१२,००० होगा।")]


def test_indices_are_global_and_sequential() -> None:
    chunks = chunk_pages([(1, "x " * 600), (2, "y " * 600)], size=400, overlap=50)
    assert [c.index for c in chunks] == list(range(len(chunks)))
