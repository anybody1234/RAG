# Nhật ký duyệt golden set v2

Người duyệt: phiên Claude `golden-v2-review`, độc lập với người soạn (phiên `golden-v2`), duyệt ngày 07–08/10/2026.
Bản nháp: `golden_v2_draft.jsonl` (128 câu, HEAD nháp `3d96b3f`). Kết quả: `golden_v2.jsonl` (100 câu, `reviewed: true`, giữ id nháp).

Cách duyệt: đọc toàn văn Điều chứa mỗi nguồn qua `read_pdf_pages()` (mọi khoản, kể cả phần sang trang). Đã đọc trọn Nghị định 356 (Điều 1–42, Mẫu số 08) và Luật 91/2025 bản tiếng Anh. Câu unanswerable được dò từ khoá vi/en trên cả 10 văn bản. Câu khác ngôn ngữ được đối chiếu với Luật 91 bản tiếng Anh (câu tiếng Anh về NĐ 356) và với luật Việt Nam (câu tiếng Việt về GDPR). Mọi câu được so với `golden_v1.jsonl` theo nội dung hỏi và theo Điều nguồn. Không gọi LLM, không chạy retrieval.

## Thống kê
| Nhóm | Nháp | Giữ | Sửa | Loại | Còn lại |
|---|---|---|---|---|---|
| dec (NĐ 356) | 33 | 20 | 4 | 9 | 24 |
| lab (Bộ luật Lao động) | 32 | 24 | 2 | 6 | 26 |
| ent (Luật Doanh nghiệp + 76/2025) | 28 | 18 | 4 | 6 | 22 |
| dp (Luật 91 + GDPR) | 35 | 25 | 3 | 7 | 28 |
| **Cộng** | 128 | 87 | 13 | 28 | 100 |

13 câu sửa gồm 7 câu sửa nội dung (dec-19, dec-24, dec-25, ent-16, dp-22, dp-24, dp-25; trong đó ent-16 và dp-24 sửa cả tag) và 6 câu chỉ sửa tag (dec-20, lab-20, lab-21, ent-14, ent-15, ent-28).

Phân bố cuối (`python eval/validate_golden.py eval/datasets/golden_v2.jsonl`: không lỗi):

| Loại | lab | ent | dp | dec | Cộng |
|---|---|---|---|---|---|
| single_article | 8 | 7 | 9 | 9 | 33 |
| numeric | 4 | 3 | 4 | 4 | 15 |
| multi_hop | 4 | 3 | 4 | 4 | 15 |
| paraphrase | 4 | 3 | 4 | 4 | 15 |
| unanswerable | 3 | 3 | 3 | 3 | 12 |
| multi_turn | 3 | 3 | 4 | 0 | 10 |

Chỉ tiêu:
- Câu khác ngôn ngữ: 25/88 câu có nguồn (28%). Tiếng Việt chỉ có nguồn GDPR: 14 câu (7 câu `no_doc_name`). Tiếng Anh chỉ có nguồn NĐ 356: 11 câu (8 câu `no_doc_name`).
- Tags: `explicit_ref` 17 (dec 4, lab 4, ent 4, dp 5), `colloquial` 21, `no_doc_name` 63, `comparison` 3 (dec-22 so sánh NĐ 356 với GDPR, dp-22, dp-25).
- Ngôn ngữ câu hỏi: en 40, vi 60 (40% tiếng Anh).
- Multi_hop Luật 91 + NĐ 356: dec-19, dec-20, dec-21. Multi_hop có nguồn luật 76/2025 cho Điều đã bị sửa: ent-14.

## Lỗi hệ thống của bản nháp
1. **Multi_hop có nguồn thừa.** Một nguồn đã chứa trọn nội dung nguồn kia: NĐ Điều 41.1 nhắc lại Luật Điều 38.2 (dec-19); luật 76/2025 thay trọn điểm a khoản 5 Điều 112 (ent-13).
2. **Chỉ kiểm tra nguồn duy nhất cho câu khác ngôn ngữ.** Câu cùng ngôn ngữ về NĐ 356 bỏ sót điều tương ứng của Luật 91: Điều 9.4.d (dec-24), Điều 17.1.b (dec-25).
3. **Câu khẳng định "luật không quy định…" chưa dò hết văn bản.** dp-22 nói Luật 91 không quy định bên chịu trách nhiệm bồi thường, nhưng Điều 37.1.g và 37.2.d có quy định. Đáp án lab-17 là suy luận.
4. **Câu hỏi chép câu dẫn của điều luật, paraphrase dùng lại nguyên từ khoá:** dp-07, dp-08, dec-28.
5. **Cụm câu dồn vào cùng một Điều.** NĐ Điều 5 có 3 câu; NĐ Điều 13.2.b có 2 câu. Đặt tên doanh nghiệp có 3 câu, Điều 53 có 2 câu, DPIA có 4 câu. Đáp án của câu numeric trùng nội dung lịch sử của câu multi_turn (ent-09/ent-22, ent-10/ent-21).
6. **Thiếu tag `no_doc_name`** ở 8 câu không nêu tên văn bản: dec-20, lab-20, lab-21, ent-14, ent-15, ent-16, ent-28, dp-24.
7. **Multi_turn có câu cuối tự đủ nghĩa:** lab-31, ent-21, dp-29.
8. **Unanswerable theo khuôn của v1:** lab-28 giống g082, ent-26 giống g081/g089, dp-34 giống g088/g091. Ngược lại, các câu bẫy "kho có nhắc chủ đề nhưng không có con số" (dec-30, lab-29, lab-30, ent-24…) đều đúng.
9. **Trùng nguồn với v1:** lab-24 trùng g010; nửa GDPR của dp-26 trùng g029.

Điểm tốt: mọi đoạn trích đều đúng nguyên văn và đúng trang, không câu nào hỏi vào Điều bị sửa (trừ ngoại lệ hợp lệ), các câu khác ngôn ngữ đều đã giới hạn phạm vi ("in Vietnam", "ở EU") để văn bản kia không trả lời được.

## Các câu người soạn còn phân vân
| Câu | Kết luận |
|---|---|
| dec-06 (mã hoá trên đám mây) | Giữ một nguồn. Luật 91 Điều 12.3 chỉ nói tổ chức tự quyết định việc mã hoá, không trả lời được câu "có bắt buộc mã hoá không". |
| dec-25 (chia sẻ nội bộ) | Sửa: thêm nguồn Luật 91 Điều 17.1.b (điều kiện "phù hợp với mục đích xử lý đã xác lập"). |
| dec-21 / dec-02 | Giữ dec-21 (multi_hop Luật + NĐ), loại dec-02. |
| dec-22 / dec-23 | Giữ dec-22 (câu duy nhất so sánh NĐ 356 với GDPR), loại dec-23. |
| lab-17 (thưởng Tết) | Loại: đáp án là suy luận, câu dễ gây nhiễu khi chấm. |
| lab-03 ("at last 18") | Giữ: đoạn trích phải khớp nguyên văn PDF nên giữ lỗi bản dịch; đáp án viết đúng "at least". |
| dp-06 (DPO bị sa thải) | Giữ: câu nói rõ "ở châu Âu", Bộ luật Lao động không áp dụng và không nói về DPO. |
| dec-29 (Mẫu số 08) | Giữ: đo được việc truy xuất Phụ lục, câu nêu rõ "Mẫu số 08" nên không lẫn với Điều 28.1. |

## Ghi chú chung
- Hit@k tính "ít nhất một nguồn gold trong top-k", Recall tính "tỉ lệ nguồn gold trúng". Thêm nguồn thay thế (khi văn bản khác cũng trả lời được) chỉ làm giảm Recall, không làm hỏng Hit.
- Một số câu dùng chung Điều nguồn với v1 nhưng hỏi nội dung khác: dec-21 (Luật Điều 2.2; g019 hỏi Điều 2.1), dec-22 (GDPR Article 37(5); g029 hỏi 37(1)), dec-24 (Luật Điều 9.4.d, cùng g059; nguồn chính là NĐ Điều 6.3), dp-22 (Luật Điều 4.1.đ; g020 hỏi cả danh sách quyền). Câu nào hỏi lại đúng nội dung của v1 thì đã loại (lab-24, dp-26).
- Không chạy `python eval/review_golden.py export eval/datasets/golden_v2.jsonl`: lệnh này ghi đè file nhật ký này.

## Nhóm dec (Nghị định 356)
| id | kết luận | lý do |
|---|---|---|
| v2-dec-01 | loại | Đúng Điều 42, nhưng thừa single; câu dễ về ngày hiệu lực, v1 đã có kiểu câu này (g048, g074). |
| v2-dec-02 | loại | Gần trùng dec-21 (cùng Điều 3). Giữ dec-21 vì là multi_hop Luật 91 + NĐ 356. |
| v2-dec-03 | loại | Đúng Điều 4.1.l, nhưng thừa single; câu có/không gần như đọc lại điểm l. |
| v2-dec-04 | giữ | Đúng Điều 9.3.b; Luật 91 Điều 30.3 và GDPR không nêu xác thực đa yếu tố. |
| v2-dec-05 | giữ | Đúng Điều 10.4; Luật 91 chỉ nhắc "virtual universe", không định nghĩa. |
| v2-dec-06 | giữ | Đúng Điều 12.4. Luật 91 Điều 12.3 chỉ nói tổ chức "tự quyết định" mã hoá, không trả lời được câu hỏi; câu nêu tên Nghị định nên một nguồn là đúng. |
| v2-dec-07 | giữ | Đúng Điều 22.1–2. |
| v2-dec-08 | giữ | Đúng Điều 7.1 (a–g), 2 đoạn trích cùng Điều. |
| v2-dec-09 | giữ | Đúng Điều 14.1. |
| v2-dec-10 | loại | "Dùng để làm gì" mơ hồ: Cổng còn có chức năng ở Luật 91 Điều 22.3, NĐ Điều 27.4, 28.2. Đáp án viết gọn thiếu "đường lối … của Đảng". |
| v2-dec-11 | giữ | Đúng Điều 17.3. |
| v2-dec-12 | giữ | Đúng Điều 10.3; "in Vietnam" loại GDPR Article 22. |
| v2-dec-13 | giữ | Đúng Điều 5.4. |
| v2-dec-14 | loại | Câu thứ ba hỏi vào Điều 5 (cùng dec-13, dec-20); thừa numeric. |
| v2-dec-15 | giữ | Đúng Điều 31.4. |
| v2-dec-16 | giữ | Đúng Điều 29.1. |
| v2-dec-17 | giữ | Đúng Điều 27.1.b và 27.3 (Điều 27 không bị NQ 22/2026 sửa). |
| v2-dec-18 | loại | Thừa numeric. Con số "tối thiểu 03 nhân sự" trùng với điều kiện Điều 22.2.c (dịch vụ xử lý), nên câu không phân biệt được hai loại dịch vụ. |
| v2-dec-19 | sửa | NĐ Điều 41.1 nhắc lại trọn quy định của Luật Điều 38.2, nên nguồn Luật không cần → không phải multi_hop thật. Trước: hỏi có phải làm ngay không + ngưỡng "số lượng lớn". Sau: hỏi thêm "từ khi nào, trong bao lâu", cần ngày Luật có hiệu lực (Điều 38.1, 01/01/2026); quote Luật đổi sang đoạn Điều 38.1–38.2 (trang 26). |
| v2-dec-20 | sửa | Đúng (Luật Điều 10.2 + NĐ Điều 5.2, cả hai cần). Tag trước `[colloquial]`, sau `[no_doc_name]`: câu dùng thuật ngữ "rút lại sự đồng ý", "xử lý dữ liệu cá nhân" và không nêu tên văn bản. |
| v2-dec-21 | giữ | Multi_hop thật: Luật Điều 2.2 (định nghĩa) + NĐ Điều 3 (danh mục). |
| v2-dec-22 | giữ | Đúng NĐ Điều 13.2 + GDPR Article 37(5); câu duy nhất so sánh NĐ 356 với GDPR. |
| v2-dec-23 | loại | Gần trùng dec-22 (cùng đoạn trích Điều 13.2.b). |
| v2-dec-24 | sửa | Luật 91 Điều 9.4.d ("im lặng hoặc không phản hồi không được coi là sự đồng ý") cũng trả lời được. Thêm nguồn Luật 91 vi trang 7 và nêu trong đáp án. |
| v2-dec-25 | sửa | Luật 91 Điều 17.1.b cũng nêu chia sẻ nội bộ, kèm điều kiện "phù hợp với mục đích xử lý đã xác lập". Thêm nguồn Luật 91 vi trang 10; đáp án nêu điều kiện mục đích (marketing chưa xác lập thì không thuộc trường hợp này) rồi mới đến nghĩa vụ ở NĐ Điều 7.4. |
| v2-dec-26 | giữ | Đúng Điều 11.2.a–b; Luật 91 Điều 30 không cấm lưu trực tiếp trên chuỗi khối. |
| v2-dec-27 | giữ | Đúng Điều 10.6. Diễn đạt khá sát điều luật nhưng là câu tiếng Anh hỏi nguồn tiếng Việt. |
| v2-dec-28 | loại | Paraphrase yếu: "điểm danh", "nhận diện cảm xúc" trùng nguyên từ khoá Điều 21.5. |
| v2-dec-29 | giữ | Đúng Mẫu số 08 (trang 54–55). Hỏi vào biểu mẫu là hợp lệ: đo được việc truy xuất Phụ lục, câu nêu rõ "Mẫu số 08" nên không lẫn với nội dung thông báo ở Điều 28.1. |
| v2-dec-30 | giữ | Dò "phí", "lệ phí", "fee" toàn kho: chỉ có phí chuyển giao dữ liệu và lệ phí đăng ký doanh nghiệp, không có lệ phí cấp Giấy chứng nhận. |
| v2-dec-31 | giữ | Dò "giờ/hours" gần "đào tạo/bồi dưỡng/training": không có số giờ đào tạo. |
| v2-dec-32 | giữ | Dò "bảo hiểm/insurance": chỉ có dữ liệu bảo hiểm (NĐ Điều 4.1.k, Luật Điều 26), không có bảo hiểm trách nhiệm nghề nghiệp. |
| v2-dec-33 | loại | Thừa unanswerable; câu hỏi danh sách doanh nghiệp là bẫy yếu (không có thông tin một phần). |

## Nhóm lab (Bộ luật Lao động)
| id | kết luận | lý do |
|---|---|---|
| v2-lab-01 | giữ | Đúng Điều 14. |
| v2-lab-02 | giữ | Đúng Điều 37. |
| v2-lab-03 | giữ | Đúng Điều 151. Đoạn trích giữ lỗi bản dịch "at last 18" vì phải khớp nguyên văn PDF; đáp án viết đúng "at least 18". |
| v2-lab-04 | giữ | Đúng Điều 156. |
| v2-lab-05 | giữ | Đúng Điều 199, nêu rõ quyền thuộc tổ chức đại diện người lao động. |
| v2-lab-06 | giữ | Đúng Điều 209. Câu dễ nhưng giữ để nhóm lab có đủ `explicit_ref`. |
| v2-lab-07 | giữ | Đúng, đủ 7 điểm khoản 1 Điều 36. |
| v2-lab-08 | loại | Thừa single; câu tra cứu đơn giản. |
| v2-lab-09 | giữ | Đúng Điều 137.4. |
| v2-lab-10 | giữ | Đúng, đủ các khoản Điều 29. |
| v2-lab-11 | giữ | Đúng Điều 190. |
| v2-lab-12 | giữ | Đúng Điều 115.1. |
| v2-lab-13 | giữ | Đúng Điều 155. |
| v2-lab-14 | loại | Trùng ý lab-01: đáp án lab-01 đã nêu ngoại lệ người giúp việc gia đình phải ký văn bản (khoản 1 Điều 162). |
| v2-lab-15 | giữ | Đúng Điều 110. |
| v2-lab-16 | giữ | Đúng Điều 97.4. |
| v2-lab-17 | loại | Đáp án "luật không bắt buộc thưởng Tết" là suy luận, không có câu chữ trong Điều 104; hệ thống trả lời "không tìm thấy" cũng có lý, nên câu dễ gây nhiễu khi chấm. |
| v2-lab-18 | giữ | Đúng Điều 19. |
| v2-lab-19 | giữ | Đúng Điều 101. |
| v2-lab-20 | sửa | Multi_hop thật: mức bồi thường ở Điều 129.1, trần khấu trừ 30% chỉ có ở Điều 102.3. Thêm tag `no_doc_name`. |
| v2-lab-21 | sửa | Đúng Điều 36.2.a + Điều 48.1, cả hai cần. Thêm tag `no_doc_name`. |
| v2-lab-22 | giữ | Đúng Điều 137.1 + Điều 138, cả hai cần. |
| v2-lab-23 | giữ | Đúng Điều 105 + Điều 111.1, cả hai cần. |
| v2-lab-24 | loại | Trùng một phần v1 g010 (người 14 tuổi làm được việc gì). |
| v2-lab-25 | giữ | Lịch sử Điều 30, câu cuối Điều 31; câu cuối dựa vào ngữ cảnh "tạm hoãn". |
| v2-lab-26 | giữ | Lịch sử Điều 148, câu cuối Điều 149.3–4; "they" phụ thuộc lịch sử. |
| v2-lab-27 | giữ | Đúng Điều 128.2–4. |
| v2-lab-28 | loại | Đúng là không có trong kho (dò "kinh phí công đoàn": 0 kết quả), nhưng cùng khuôn với v1 g082 (tỷ lệ đóng trên quỹ lương). |
| v2-lab-29 | giữ | Dò "income tax/thu nhập cá nhân": chỉ có ở Điều 102.3 (khấu trừ lương), không có thuế suất cho tiền làm thêm giờ. |
| v2-lab-30 | giữ | Dò "phạt": chỉ có Điều 127 (cấm phạt tiền thay kỷ luật), không có mức phạt khi không ký hợp đồng văn bản. |
| v2-lab-31 | loại | Câu cuối tự đủ nghĩa, không phụ thuộc lịch sử (cùng Điều 27 với lịch sử). |
| v2-lab-32 | giữ | Điều 157 giao Chính phủ quy định thủ tục; kho không có nơi nộp hay thời hạn. |

## Nhóm ent (Luật Doanh nghiệp + 76/2025)
| id | kết luận | lý do |
|---|---|---|
| v2-ent-01 | giữ | Đúng Điều 34. |
| v2-ent-02 | loại | Cụm câu về đặt tên (ent-07, ent-27); thừa single. |
| v2-ent-03 | giữ | Đúng Điều 43. |
| v2-ent-04 | giữ | Đúng Điều 44. |
| v2-ent-05 | giữ | Đúng Điều 195.2–3. |
| v2-ent-06 | giữ | Đúng Điều 211. |
| v2-ent-07 | giữ | Đúng Điều 41.2–3. |
| v2-ent-08 | giữ | Đúng Điều 180. |
| v2-ent-09 | loại | Thừa numeric; nội dung trùng lịch sử của ent-22 (Điều 139.2). |
| v2-ent-10 | giữ | Đúng Điều 154.1–2. |
| v2-ent-11 | giữ | Đúng Điều 132. |
| v2-ent-12 | giữ | Đúng Điều 135.4. |
| v2-ent-13 | loại | Khoản 17 Điều 1 luật 76/2025 thay trọn điểm a khoản 5 Điều 112, nên nguồn bản gốc 2020 không cần cho câu "điều kiện hiện hành" → không phải multi_hop thật. ent-14 đã đáp ứng yêu cầu multi_hop có nguồn 76/2025. |
| v2-ent-14 | sửa | Multi_hop thật: điểm a–d khoản 3 Điều 128 bản gốc + điểm c1 do luật 76/2025 bổ sung. Thêm tag `no_doc_name` (câu nêu "Article 128" nhưng không nêu tên luật). |
| v2-ent-15 | sửa | Đúng Điều 69 + Điều 135.2, cả hai cần. Thêm tag `no_doc_name`. |
| v2-ent-16 | sửa | Điều 53.4 dẫn chiếu "mua lại hoặc chuyển nhượng theo Điều 51 và Điều 52"; thời hạn 15 ngày áp dụng qua dẫn chiếu tới Điều 51.3. Đáp án viết lại cho rõ việc mua lại "thực hiện theo Điều 51", bỏ cách viết như thể Điều 51.3 nói thẳng về người thừa kế. Thêm tag `no_doc_name`. |
| v2-ent-17 | giữ | Đúng Điều 189.3. |
| v2-ent-18 | giữ | Đúng Điều 113.1, 113.3. |
| v2-ent-19 | giữ | Đúng Điều 191. |
| v2-ent-20 | loại | Trùng chủ đề ent-16 (phần vốn góp của thành viên đã chết, Điều 53); thừa paraphrase. |
| v2-ent-21 | loại | Câu cuối tự đủ nghĩa; lịch sử trùng nội dung ent-10 (Điều 154.2). |
| v2-ent-22 | giữ | Đúng Điều 139.3. |
| v2-ent-23 | giữ | Đúng Điều 206.3 (Điều 206 không bị sửa; 207 mới bị sửa). |
| v2-ent-24 | giữ | Luật chỉ nói "nộp đủ lệ phí … theo pháp luật về phí và lệ phí" (Điều 27.1.d), không có mức tiền. |
| v2-ent-25 | giữ | Dò "ngân hàng thương mại/commercial bank/foreign ownership": 0 kết quả. |
| v2-ent-26 | loại | Gần v1 g081/g089 (thuế thu nhập doanh nghiệp). |
| v2-ent-27 | giữ | Lịch sử Điều 37, câu cuối Điều 39. |
| v2-ent-28 | sửa | Dò "niêm yết/Sở Giao dịch Chứng khoán": chỉ có nghĩa vụ thông báo, không có điều kiện vốn niêm yết. Thêm tag `no_doc_name` (câu không nêu tên văn bản). |

## Nhóm dp (Luật 91/2025 + GDPR)
| id | kết luận | lý do |
|---|---|---|
| v2-dp-01 | giữ | Đúng GDPR Article 5(1)–(2). |
| v2-dp-02 | giữ | Đúng Article 18(1)–(2); v1 chỉ có quyền xoá (Article 17), chưa có quyền hạn chế xử lý. |
| v2-dp-03 | giữ | Đúng Article 27. Khác v1 g028: g028 hỏi GDPR có áp dụng không (Article 3), câu này hỏi nghĩa vụ chỉ định đại diện và các trường hợp miễn. |
| v2-dp-04 | giữ | Đúng Article 26, 2 đoạn trích cùng Article. |
| v2-dp-05 | giữ | Đúng Article 32(1). |
| v2-dp-06 | giữ | Đúng Article 38(3). Câu nói rõ "ở châu Âu" nên Bộ luật Lao động không phải nguồn thay thế. |
| v2-dp-07 | loại | Câu hỏi chép gần nguyên câu dẫn khoản 1 Điều 19; câu không nêu nước nên GDPR Article 6 cũng có thể dùng để trả lời. |
| v2-dp-08 | loại | Câu hỏi chép gần nguyên câu dẫn khoản 2 Điều 16 ("chỉ được công khai trong các trường hợp"). |
| v2-dp-09 | giữ | Đúng Điều 28.6–28.7 (bản tiếng Anh). |
| v2-dp-10 | giữ | Đúng Điều 39.1–39.2. |
| v2-dp-11 | giữ | Đúng Điều 17.2. Khác v1 g057 (Điều 7, cấm mua bán dữ liệu). |
| v2-dp-12 | giữ | Đúng Article 30(5). |
| v2-dp-13 | giữ | Đúng Article 36(2). |
| v2-dp-14 | giữ | Đúng Điều 20.2–20.3. Câu nêu "Điều 20 Luật 91" nên NĐ Điều 18.4 (đã bị NQ 22/2026 sửa) không phải nguồn. |
| v2-dp-15 | loại | Thừa numeric; cùng Điều 20 với dp-14. |
| v2-dp-16 | giữ | Đúng Article 45(3). |
| v2-dp-17 | giữ | Đúng Article 16. |
| v2-dp-18 | loại | Nội dung (Article 35(3)(c)) đã nằm trong lịch sử của dp-27; cụm câu DPIA dày (dp-13, dp-25, dp-27). |
| v2-dp-19 | giữ | Đúng Điều 26.2. |
| v2-dp-20 | giữ | Đúng Điều 32.1.b, 32.2, 32.3. |
| v2-dp-21 | giữ | Đúng Article 25(2). |
| v2-dp-22 | sửa | Đáp án nháp sai: nói Luật 91 "không quy định riêng … bên chịu trách nhiệm", trong khi điểm g khoản 1 Điều 37 (bên kiểm soát chịu trách nhiệm trước chủ thể dữ liệu về thiệt hại) và điểm d khoản 2 Điều 37 (bên xử lý chịu trách nhiệm trước bên kiểm soát) có quy định. Sau: đáp án nêu Điều 4.1.đ + Điều 37.1.g + 37.2.d, phần GDPR thêm miễn trách ở Article 82(3); thêm nguồn Luật 91 vi trang 23. Lẽ ra loại vì lỗi lớn, nhưng giữ lại sau khi sửa vì cần đủ 3 câu `comparison` sau khi loại dp-26. |
| v2-dp-23 | giữ | Article 45(1) + 46(1)–(2), cả hai cần. Luật 91 Điều 20 chỉ nói chuyển dữ liệu ra khỏi Việt Nam, không áp dụng chiều EU → Việt Nam. |
| v2-dp-24 | sửa | Đúng Điều 20.6.b + Điều 21.1, cả hai cần. Đáp án thêm ngoại lệ Điều 38 (doanh nghiệp nhỏ, khởi nghiệp, siêu nhỏ, hộ kinh doanh) vì câu nói "it must still". Thêm tag `no_doc_name`. |
| v2-dp-25 | sửa | Đúng Luật Điều 21.1 + GDPR Article 35(1), 36(1). Trước: "mọi bên kiểm soát đều phải lập … (trừ cơ quan nhà nước có thẩm quyền)". Sau: thêm ngoại lệ Điều 38 cho doanh nghiệp nhỏ, khởi nghiệp, siêu nhỏ, hộ kinh doanh. |
| v2-dp-26 | loại | Nửa GDPR (Article 37(1): khi nào bắt buộc DPO) hỏi lại đúng nội dung v1 g029. v2 là bộ test giữ riêng nên tránh trùng. |
| v2-dp-27 | giữ | Đúng Article 35(7); câu cuối phụ thuộc lịch sử ("bản đánh giá đó"). |
| v2-dp-28 | giữ | Lịch sử Điều 28.3, câu cuối Điều 28.5. |
| v2-dp-29 | loại | Câu cuối gần như tự đủ nghĩa; thừa multi_turn (bản cuối đúng 10 câu). |
| v2-dp-30 | giữ | Lịch sử Article 28(2), câu cuối Article 28(4). |
| v2-dp-31 | giữ | Article 45(8) chỉ nói Uỷ ban công bố danh sách; dò tên các nước có quyết định công nhận (Japan, Switzerland, Canada…): 0 kết quả. |
| v2-dp-32 | giữ | Dò "phí/lệ phí" trong Luật 91 và NĐ 356: chỉ có phí chuyển giao dữ liệu, không có phí nộp hồ sơ đánh giá tác động. |
| v2-dp-33 | giữ | Dò "fee": GDPR chỉ có phí bên kiểm soát thu của chủ thể dữ liệu (Article 12(5), 15(3)) và phí cơ quan giám sát thu khi yêu cầu vô căn cứ; không có phí thường niên. |
| v2-dp-34 | loại | Cùng khuôn v1 g088/g091 (hỏi một luật khác không có trong kho). |
| v2-dp-35 | giữ | Đúng Article 82(4)–(5); câu cuối phụ thuộc lịch sử ("dữ liệu đó"). |
