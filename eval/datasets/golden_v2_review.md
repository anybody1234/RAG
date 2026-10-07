# Nhật ký duyệt golden set v2 (WIP)

Người duyệt: phiên Claude `golden-v2-review`, độc lập với người soạn. Nguồn: toàn văn PDF qua `read_pdf_pages()`.
Bản nháp: `golden_v2_draft.jsonl` (128 câu, HEAD nháp `3d96b3f`).

## Trạng thái
- Đã duyệt: nhóm dec (33 câu), lab (32), ent (28).
- Chưa duyệt: nhóm dp (35).
- Chưa tạo `golden_v2.jsonl`. Một số câu "giữ" ở nhóm dec còn là ứng viên cắt, chốt khi đếm phân bố cuối.

## Ghi chú chung
- Hit@k tính "ít nhất một nguồn gold trong top-k"; Recall tính "tỉ lệ nguồn gold trúng". Thêm nguồn thay thế (khi văn bản khác cũng trả lời được) chỉ làm giảm Recall, không làm hỏng Hit.
- Quota cắt theo nhóm (brief người soạn): dec 33→24, lab 32→26, ent 28→22, dp 35→28.

## Nhóm dec (Nghị định 356)
| id | kết luận | lý do |
|---|---|---|
| v2-dec-01 | giữ (ứng viên cắt) | Đúng Điều 42. Câu dễ, nêu thẳng số hiệu. |
| v2-dec-02 | loại | Gần trùng dec-21 (cùng Điều 3). Giữ dec-21 vì là multi_hop Luật 91 + NĐ 356. |
| v2-dec-03 | giữ (ứng viên cắt) | Đúng Điều 4.1.l. Câu có/không, gần như đọc lại điểm l. |
| v2-dec-04 | giữ | Đúng Điều 9.3.b; Luật 91 Điều 30.3 và GDPR không nêu xác thực đa yếu tố. |
| v2-dec-05 | giữ (ứng viên cắt) | Đúng Điều 10.4; Luật 91 chỉ nhắc "virtual universe", không định nghĩa. |
| v2-dec-06 | giữ | Đúng Điều 12.4. Luật 91 Điều 12.3 chỉ nói tổ chức "tự quyết định" mã hoá, không trả lời được câu hỏi; câu nêu tên Nghị định nên một nguồn là đúng. |
| v2-dec-07 | giữ | Đúng Điều 22.1–2. |
| v2-dec-08 | giữ | Đúng Điều 7.1 (a–g), 2 đoạn trích cùng Điều. |
| v2-dec-09 | giữ (ứng viên cắt) | Đúng Điều 14.1. |
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
| v2-dec-20 | sửa | Đúng (Luật Điều 10.2 + NĐ Điều 5.2, cả hai cần). Bỏ tag `colloquial`: câu dùng thuật ngữ "rút lại sự đồng ý", "xử lý dữ liệu cá nhân". |
| v2-dec-21 | giữ | Multi_hop thật: Luật Điều 2.2 (định nghĩa) + NĐ Điều 3 (danh mục). |
| v2-dec-22 | giữ | Đúng NĐ Điều 13.2 + GDPR Article 37(5); câu duy nhất so sánh NĐ 356 với GDPR. |
| v2-dec-23 | loại | Gần trùng dec-22 (cùng đoạn trích Điều 13.2.b). |
| v2-dec-24 | sửa | Luật 91 Điều 9.4.d ("im lặng hoặc không phản hồi không được coi là sự đồng ý") cũng trả lời được. Thêm nguồn Luật 91 vi trang 7 và nêu trong đáp án. |
| v2-dec-25 | sửa | Luật 91 Điều 17.1.b cũng nêu chia sẻ nội bộ, kèm điều kiện "phù hợp với mục đích xử lý đã xác lập". Thêm nguồn Luật 91 vi trang 10; đáp án nêu điều kiện mục đích (marketing chưa xác lập thì không thuộc trường hợp này) rồi mới đến nghĩa vụ ở NĐ Điều 7.4. |
| v2-dec-26 | giữ | Đúng Điều 11.2.a–b; Luật 91 Điều 30 không cấm lưu trực tiếp trên chuỗi khối. |
| v2-dec-27 | giữ | Đúng Điều 10.6. Diễn đạt khá sát điều luật nhưng là câu tiếng Anh hỏi nguồn tiếng Việt. |
| v2-dec-28 | loại | Paraphrase yếu: "điểm danh", "nhận diện cảm xúc" trùng nguyên từ khoá Điều 21.5. |
| v2-dec-29 | giữ (ứng viên cắt) | Đúng Mẫu số 08 (trang 54–55). Hỏi vào biểu mẫu là hợp lệ: đo được việc truy xuất Phụ lục, câu nêu rõ "Mẫu số 08" nên không lẫn với nội dung thông báo ở Điều 28.1. |
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
| v2-lab-20 | giữ | Multi_hop thật: mức bồi thường ở Điều 129.1, trần khấu trừ 30% chỉ có ở Điều 102.3. |
| v2-lab-21 | giữ | Đúng Điều 36.2.a + Điều 48.1, cả hai cần. |
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
| v2-ent-14 | giữ | Multi_hop thật: điểm a–d khoản 3 Điều 128 bản gốc + điểm c1 do luật 76/2025 bổ sung. |
| v2-ent-15 | giữ | Đúng Điều 69 + Điều 135.2, cả hai cần. |
| v2-ent-16 | sửa | Điều 53.4 dẫn chiếu "mua lại hoặc chuyển nhượng theo Điều 51 và Điều 52"; thời hạn 15 ngày áp dụng qua dẫn chiếu tới Điều 51.3. Đáp án viết lại cho rõ việc mua lại "thực hiện theo Điều 51", bỏ cách viết như thể Điều 51.3 nói thẳng về người thừa kế. |
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
