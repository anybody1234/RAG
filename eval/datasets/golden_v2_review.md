# Nhật ký duyệt golden set v2 (WIP, dừng giữa chừng do hết quota)

Người duyệt: phiên Claude `golden-v2-review`, độc lập với người soạn. Nguồn: toàn văn PDF qua `read_pdf_pages()`.
Bản nháp: `golden_v2_draft.jsonl` (128 câu, HEAD nháp `3d96b3f`). Chưa tạo `golden_v2.jsonl`.

## Trạng thái
- Đã đọc toàn văn Nghị định 356 (Điều 1–42, Mẫu số 08) và Luật 91/2025 bản tiếng Anh.
- Đã duyệt sơ bộ v2-dec-01 → v2-dec-24 (kết luận dưới đây là **tạm**, chưa áp vào JSONL).
- Chưa duyệt: v2-dec-25 → v2-dec-33, toàn bộ nhóm lab, ent, dp.
- Đã có danh sách v1 (100 câu, kèm Điều nguồn) để dò trùng; chưa đối chiếu từng câu v2.

## Ghi chú chung
- Hit@k tính "ít nhất một nguồn gold trong top-k"; Recall tính "tỉ lệ nguồn gold trúng". Nên thêm nguồn thay thế (khi văn bản khác cũng trả lời được) chỉ làm giảm Recall, không làm hỏng Hit.
- Quota cắt theo nhóm (brief người soạn): dec 33→24, lab 32→26, ent 28→22, dp 35→28.
- Câu khác ngôn ngữ dự kiến dư: en-Nghị định 356 có 16 ứng viên, vi-GDPR có 15 ứng viên (cần ≥10 mỗi chiều).

## Kết luận tạm nhóm dec
| id | kết luận | lý do |
|---|---|---|
| v2-dec-01 | giữ (ứng viên cắt) | Đúng Điều 42. Câu dễ, nêu thẳng số hiệu. |
| v2-dec-02 | loại | Gần trùng v2-dec-21 (cùng Điều 3). Giữ dec-21 vì là multi_hop Luật 91 + NĐ 356, loại câu single dư. |
| v2-dec-03 | giữ (ứng viên cắt) | Đúng Điều 4.1.l. Câu tra cứu dễ. |
| v2-dec-04 | giữ | Đúng Điều 9.3.b; Luật 91 Điều 30.3 và GDPR không nêu xác thực đa yếu tố. |
| v2-dec-05 | giữ (ứng viên cắt) | Đúng Điều 10.4; Luật 91 chỉ nhắc "virtual universe", không định nghĩa. |
| v2-dec-06 | giữ | Đúng Điều 12.4. Luật 91 Điều 12.3 chỉ nói tổ chức "tự quyết định" mã hoá, không trả lời được câu hỏi; câu nêu tên Nghị định nên một nguồn là đúng. |
| v2-dec-07 | giữ | Đúng Điều 22.1–2. |
| v2-dec-08 | giữ | Đúng Điều 7.1 (a–g), 2 đoạn trích cùng Điều. |
| v2-dec-09 | giữ (ứng viên cắt) | Đúng Điều 14.1. |
| v2-dec-10 | ứng viên loại | Điều 39.2 đúng, nhưng "dùng để làm gì" mơ hồ: Cổng còn có chức năng ở Luật 91 Điều 22.3, NĐ Điều 27.4, 28.2. Đáp án viết gọn "chủ trương, chính sách" thiếu "đường lối … của Đảng". |
| v2-dec-11 | giữ | Đúng Điều 17.3. |
| v2-dec-12 | giữ | Đúng Điều 10.3; "in Vietnam" loại GDPR Điều 22. |
| v2-dec-13 | giữ | Đúng Điều 5.4. |
| v2-dec-14 | loại | Thứ ba hỏi vào Điều 5 (cùng dec-13, dec-20); thừa numeric. |
| v2-dec-15 | giữ | Đúng Điều 31.4. |
| v2-dec-16 | giữ | Đúng Điều 29.1. |
| v2-dec-17 | giữ | Đúng Điều 27.1.b và 27.3 (Điều 27 không bị NQ 22/2026 sửa). |
| v2-dec-18 | giữ (ứng viên cắt) | Đúng Điều 16.1. |
| v2-dec-19 | sửa | NĐ Điều 41.1 nhắc lại trọn quy định của Luật Điều 38.2, nên nguồn Luật không cần → không phải multi_hop thật. Sửa: hỏi thêm "miễn đến khi nào", cần ngày hiệu lực của Luật (Điều 38.1, 01/01/2026); đổi quote Luật thành "This Law comes into force from January 1, 2026" (trang 26). |
| v2-dec-20 | sửa nhỏ | Đúng (Luật Điều 10.2 + NĐ Điều 5.2, cả hai cần). Bỏ tag `colloquial` (câu dùng thuật ngữ "rút lại sự đồng ý"). |
| v2-dec-21 | giữ | Multi_hop thật: Luật Điều 2.2 (định nghĩa) + NĐ Điều 3 (danh mục). |
| v2-dec-22 | giữ | Đúng NĐ Điều 13.2 + GDPR Article 37(5); là câu duy nhất so sánh NĐ 356 với GDPR. Chưa đọc lại GDPR trang 75. |
| v2-dec-23 | loại | Gần trùng dec-22 (cùng đoạn trích Điều 13.2.b). |
| v2-dec-24 | sửa | Luật 91 Điều 9.4.d ("im lặng hoặc không phản hồi không được coi là sự đồng ý") cũng trả lời được. Thêm nguồn Luật 91 bản vi Điều 9 và nêu trong đáp án. |
