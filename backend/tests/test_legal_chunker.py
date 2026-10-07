from app.ingestion.chunking import reflow
from app.ingestion.legal_chunker import chunk_legal, looks_like_legal, parse_legal_structure
from app.ingestion.models import Block


def words(text: str) -> int:
    """Bộ đếm token giả: mỗi từ một token, cho dễ tính trong test."""
    return len(text.split())


def blocks(text: str, page: int = 1) -> list[Block]:
    return [Block(line, page) for line in text.strip().split("\n")]


VI_LAW = """
QUỐC HỘI
Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;
Chương I
NHỮNG QUY ĐỊNH CHUNG
Điều 1. Phạm vi điều chỉnh
Luật này quy định về việc thành lập, tổ chức quản lý và hoạt động của doanh nghiệp theo quy định tại
Điều 209 của Luật này.
Điều 2. Sửa đổi, bổ sung Điều 4
1. Sửa đổi, bổ sung khoản 1 Điều 4 như sau:
“Điều 4. Giải thích từ ngữ
1. Doanh nghiệp là tổ chức có tên riêng, có tài sản, có trụ sở giao dịch.”
Chương II
TỔ CHỨC QUẢN LÝ
Mục 1
QUY ĐỊNH CHUNG
Điều 3. Hiệu lực thi hành
Luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2021.
"""


def test_parses_vietnamese_structure():
    structure = parse_legal_structure(blocks(VI_LAW))
    assert [a.label for a in structure.articles] == ["Điều 1", "Điều 2", "Điều 3"]
    assert [a.path for a in structure.articles] == [["Chương I"], ["Chương I"], ["Chương II", "Mục 1"]]
    assert [b.text for b in structure.preamble] == ["QUỐC HỘI", "Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;"]
    # Dẫn chiếu bị ngắt dòng được nối lại vào đoạn, không thành tiêu đề.
    assert structure.articles[0].blocks[1].text.endswith("theo quy định tại Điều 209 của Luật này.")
    # Điều nằm trong ngoặc kép là nội dung được sửa đổi của Điều 2.
    assert structure.articles[1].quoted == [False, False, True, True]
    all_text = "\n".join(b.text for a in structure.articles for b in a.blocks)
    assert "NHỮNG QUY ĐỊNH CHUNG" not in all_text and "Mục 1" not in all_text


EN_REGULATION = """
Whereas:
(1) Delegated acts under
Article 290 TFEU should be adopted by the Commission.
CHAPTER I General provisions
Article 1 Subject-matter and objectives
1. This Regulation lays down rules.
Article 2 Material scope
1. Approved certification mechanisms as referred to in
Article 42 may be used as an element to demonstrate compliance.
Article 3 Territorial scope
This Regulation applies.
"""


def test_ignores_references_that_look_like_article_headings():
    structure = parse_legal_structure(blocks(EN_REGULATION))
    assert [a.label for a in structure.articles] == ["Article 1", "Article 2", "Article 3"]
    assert structure.articles[0].path == ["Chapter I"]
    assert any("Article 290 TFEU" in b.text for b in structure.preamble)
    assert "Article 42 may be used" in structure.articles[1].blocks[-1].text


def test_unbalanced_quote_does_not_hide_later_structure():
    text = """
Article 1. Definitions
1. “employer” means a person who employs workers.
2. “employee means a person who works for an employer.
Article 2. Scope
1. This Code applies to employees.
Article 3. Effect
This Code takes effect in 2021.
"""
    structure = parse_legal_structure(blocks(text))
    assert [a.label for a in structure.articles] == ["Article 1", "Article 2", "Article 3"]
    assert structure.articles[1].quoted == [False, False]


def test_reflow_joins_wrapped_lines_and_keeps_page_range():
    lines = [
        Block("Điều 40. Nghĩa vụ của người lao động khi đơn phương chấm dứt hợp đồng lao động trái", 1),
        Block("pháp luật", 1),
        Block("1. Không được trợ cấp thôi việc và phải bồi thường cho người sử dụng lao động nửa tháng", 1),
        Block("tiền lương theo hợp đồng lao động.", 2),
        Block("2. Phải hoàn trả chi phí đào tạo.", 2),
    ]
    paragraphs = reflow(lines)
    assert [p.text for p in paragraphs] == [
        "Điều 40. Nghĩa vụ của người lao động khi đơn phương chấm dứt hợp đồng lao động trái pháp luật",
        (
            "1. Không được trợ cấp thôi việc và phải bồi thường cho người sử dụng lao động nửa tháng "
            "tiền lương theo hợp đồng lao động."
        ),
        "2. Phải hoàn trả chi phí đào tạo.",
    ]
    assert (paragraphs[1].page, paragraphs[1].page_end) == (1, 2)


def test_short_article_is_one_chunk():
    pieces = chunk_legal(blocks(VI_LAW), "vi", max_tokens=100, overlap_ratio=0.1, count=words)
    assert [" > ".join(p.path) for p in pieces] == [
        "Phần mở đầu", "Chương I > Điều 1", "Chương I > Điều 2", "Chương II > Mục 1 > Điều 3",
    ]
    assert pieces[1].text().startswith("Điều 1. Phạm vi điều chỉnh\n")


LONG_ARTICLE = """
Điều 5. Nghỉ hằng năm
1. Người lao động làm việc đủ 12 tháng cho một người sử dụng lao động thì được nghỉ hằng năm.
2. Người lao động làm việc chưa đủ 12 tháng thì số ngày nghỉ hằng năm theo tỷ lệ tương ứng.
3. Người sử dụng lao động quy định lịch nghỉ hằng năm sau khi tham khảo ý kiến người lao động.
"""


def test_long_article_is_split_by_clause_with_title_repeated():
    pieces = chunk_legal(blocks(LONG_ARTICLE), "vi", max_tokens=50, overlap_ratio=0.1, count=words)
    assert [" > ".join(p.path) for p in pieces] == ["Điều 5 > Khoản 1–2", "Điều 5 > Khoản 3"]
    assert all(p.text().startswith("Điều 5. Nghỉ hằng năm\n") for p in pieces)
    assert all(words(p.text()) <= 50 for p in pieces)
    assert all(p.article == "Điều 5" for p in pieces)


def test_long_clause_is_split_by_point_with_lead_repeated():
    text = """
Điều 36. Quyền đơn phương chấm dứt hợp đồng
1. Người sử dụng lao động có quyền đơn phương chấm dứt hợp đồng trong trường hợp sau đây:
a) Người lao động thường xuyên không hoàn thành công việc theo hợp đồng lao động đã giao kết;
b) Người lao động bị ốm đau, tai nạn đã điều trị 12 tháng liên tục mà chưa hồi phục;
c) Do thiên tai, hỏa hoạn, dịch bệnh nguy hiểm mà người sử dụng lao động đã tìm mọi biện pháp;
2. Khi chấm dứt hợp đồng, người sử dụng lao động phải báo trước.
"""
    pieces = chunk_legal(blocks(text), "vi", max_tokens=50, overlap_ratio=0.1, count=words)
    paths = [" > ".join(p.path) for p in pieces]
    assert paths[0].startswith("Điều 36 > Khoản 1 > Điểm a")
    assert paths[-1] == "Điều 36 > Khoản 2"
    lead = "Điều 36. Quyền đơn phương chấm dứt hợp đồng\n1. Người sử dụng lao động có quyền"
    assert all(p.text().startswith(lead) for p in pieces[:-1])
    assert all(words(p.text()) <= 50 for p in pieces)


def test_unstructured_long_article_is_split_by_sentence():
    sentence = "Người lao động được hưởng nguyên lương trong những ngày nghỉ lễ."
    text = "Điều 7. Nghỉ lễ\n" + " ".join([sentence] * 12)
    pieces = chunk_legal(blocks(text), "vi", max_tokens=40, overlap_ratio=0.0, count=words)
    assert len(pieces) > 1
    assert all(p.text().startswith("Điều 7. Nghỉ lễ\n") and words(p.text()) <= 40 for p in pieces)
    assert sum(p.text().count(sentence) for p in pieces) == 12


def test_appendix_forms_are_separate_from_last_article():
    """Phụ lục mẫu biểu sau Điều cuối (Nghị định 356/2025) không bị gộp vào Điều cuối. Mẫu biểu mới bắt đầu ở
    đầu trang; dòng "Mẫu số 01b" trong bảng danh mục giữa trang không mở mẫu mới, "Điều 1." trong mẫu quyết
    định không phải Điều của nghị định."""
    lines = blocks(VI_LAW) + [
        Block("TM. CHÍNH PHỦ", 1),
        Block("Phụ lục", 2),
        Block("DANH MỤC HỒ SƠ VÀ BIỂU MẪU", 2),
        Block("Mẫu số 01a Thông báo gửi hồ sơ đánh giá tác động", 2),
        Block("Mẫu số 01b", 2),
        Block("Quyết định cấp Giấy chứng nhận", 2),
        Block("Mẫu số 01a", 3),
        Block("THÔNG BÁO GỬI HỒ SƠ", 3),
        Block("Mẫu số 01b", 4),
        Block("QUYẾT ĐỊNH", 4),
        Block("Điều 1. Cấp Giấy chứng nhận cho tổ chức.", 4),
    ]
    structure = parse_legal_structure(lines)
    assert [a.label for a in structure.articles] == ["Điều 1", "Điều 2", "Điều 3"]
    assert structure.articles[-1].blocks[-1].text == "TM. CHÍNH PHỦ"
    assert [a.path for a in structure.appendices] == [
        ["Phụ lục"], ["Phụ lục", "Mẫu số 01a"], ["Phụ lục", "Mẫu số 01b"],
    ]
    assert [b.text for b in structure.appendices[0].blocks][-2:] == ["Mẫu số 01b", "Quyết định cấp Giấy chứng nhận"]

    pieces = chunk_legal(lines, "vi", max_tokens=100, overlap_ratio=0.1, count=words)
    assert [(" > ".join(p.path), p.article) for p in pieces[-3:]] == [
        ("Phụ lục", None), ("Phụ lục > Mẫu số 01a", None), ("Phụ lục > Mẫu số 01b", None),
    ]
    assert pieces[-1].text() == "Mẫu số 01b\nQUYẾT ĐỊNH\nĐiều 1. Cấp Giấy chứng nhận cho tổ chức."


def test_long_appendix_form_is_split_with_title_repeated():
    row = "Họ và tên người đại diện theo pháp luật của tổ chức đề nghị cấp giấy chứng nhận"
    lines = blocks(VI_LAW) + [Block("Phụ lục", 2), Block("Mẫu số 09", 3)]
    lines += [Block(f"{n}. {row}", 3) for n in range(1, 9)]
    pieces = chunk_legal(lines, "vi", max_tokens=40, overlap_ratio=0.0, count=words)
    forms = [p for p in pieces if p.path == ["Phụ lục", "Mẫu số 09"]]
    assert len(forms) > 1
    assert all(p.text().startswith("Mẫu số 09\n") and words(p.text()) <= 40 for p in forms)


def test_needs_at_least_three_articles_to_be_legal():
    assert looks_like_legal(blocks(VI_LAW))
    assert not looks_like_legal(blocks("Điều 1. Tiêu đề\nNội dung.\nĐiều 2. Tiêu đề\nNội dung."))
