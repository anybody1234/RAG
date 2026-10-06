import unicodedata

from app.retrieval.sparse import SparseEncoder, term_index, tokenize


def test_tokenize_lowercases_and_adds_syllable_bigrams():
    assert tokenize("Thời gian thử việc") == [
        "thời", "gian", "thử", "việc", "thời gian", "gian thử", "thử việc",
    ]


def test_tokenize_normalizes_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Điều 35 người lao động")
    assert tokenize(decomposed) == tokenize("Điều 35 người lao động")


def test_bigrams_do_not_cross_punctuation_or_line_breaks():
    terms = tokenize("Điều 35. Quyền đơn phương\nkhoản 2, điểm a")
    assert "điều 35" in terms and "35 quyền" not in terms and "phương khoản" not in terms
    assert "khoản 2" in terms and "2 điểm" not in terms


def test_document_numbers_and_amounts():
    terms = tokenize("Bộ luật số 45/2019/QH14, phạt 20.000.000 đồng")
    assert {"45", "2019", "qh14", "45 2019", "2019 qh14"} <= set(terms)
    assert {"20.000.000", "20.000.000 đồng"} <= set(terms)


def test_term_index_is_stable_uint32():
    assert term_index("thử việc") == term_index("thử việc")
    assert term_index("thử việc") != term_index("thử")
    assert 0 <= term_index("điều 35") < 2**32


def test_document_vector_uses_bm25_term_frequency():
    encoder = SparseEncoder(k1=1.2, b=0.75, avg_doc_len=4)
    vector = encoder.encode_document("lương lương thưởng phạt")
    weights = dict(zip(vector.indices, vector.values, strict=True))
    assert vector.indices == sorted(vector.indices)
    # Văn bản dài đúng bằng avg_doc_len: tf = 1 cho trọng số 1, tf = 2 cho 2·2.2/3.2.
    assert weights[term_index("thưởng")] == 1.0
    assert abs(weights[term_index("lương")] - 2 * 2.2 / 3.2) < 1e-9


def test_longer_documents_get_lower_weights():
    encoder = SparseEncoder(k1=1.2, b=0.75, avg_doc_len=4)
    short = encoder.encode_document("lương thưởng")
    long = encoder.encode_document("lương thưởng " + "khác " * 20)
    index = term_index("lương")
    assert dict(zip(short.indices, short.values, strict=True))[index] > dict(
        zip(long.indices, long.values, strict=True)
    )[index]


def test_query_vector_has_unit_weight_per_unique_term():
    vector = SparseEncoder(1.2, 0.75, 200).encode_query("lương lương")
    assert sorted(vector.indices) == sorted({term_index("lương"), term_index("lương lương")})
    assert vector.values == [1.0, 1.0]


def test_empty_text_gives_empty_vector():
    assert SparseEncoder(1.2, 0.75, 200).encode_query("!!!").indices == []
