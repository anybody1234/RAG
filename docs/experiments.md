# Thí nghiệm retrieval

Nhật ký thí nghiệm của chatbot RAG cho văn bản luật. Mỗi thí nghiệm ghi lại:
- mục tiêu và nhóm câu hỏi nhắm tới;
- thay đổi so với config trước;
- số trước/sau trên cùng golden set;
- latency và chi phí;
- kết luận giữ hay bỏ.

File kết quả đầy đủ (metric từng câu, hạng của từng nguồn gold, top-5 chunk) nằm trong `eval/results/`.

## Cách đọc số

- **Golden set:** `eval/datasets/golden_v1.jsonl`, 100 câu, trong đó 88 câu có nguồn được tính metric. 12 câu `unanswerable` chỉ dùng để đo latency.
- **Chunk trúng một nguồn gold** khi thoả cả ba điều kiện:
  - đúng `doc_id`;
  - khoảng trang của chunk chứa trang gold;
  - text chunk chứa đoạn trích (so sau khi chuẩn hoá NFKC và gộp khoảng trắng).

  Câu hỏi tiếng Việt mà lấy được bản dịch tiếng Anh của đúng Điều đó vẫn bị tính là trượt, vì bản tiếng Việt mới là căn cứ.
- **Các metric:**
  - Hit@k = 1 khi ít nhất một nguồn gold nằm trong top-k.
  - Recall@k là tỉ lệ nguồn gold nằm trong top-k. Chỉ khác Hit@k ở câu `multi_hop`.
  - MRR@k = 1 / hạng của chunk trúng đầu tiên.
  - nDCG@k dùng gain nhị phân theo nguồn gold.
- **Câu khác ngôn ngữ:** không nguồn nào cùng ngôn ngữ với câu hỏi. Hiện cả 19 câu loại này đều là câu hỏi tiếng Việt về GDPR.
- **Retrieval latency:** tổng các bước mà một chế độ cần (viết lại câu hỏi, embed, mã hoá sparse, truy vấn Qdrant, rerank). Đo tuần tự từng câu trên máy dev, chưa có tải đồng thời (load test để P8). SLO: p95 ≤ 800 ms.
- **Nhiễu nền:** chạy 2 lần trên cùng code thì MRR@5 của hybrid lệch 0.006, vì embedding của OpenAI không hoàn toàn tất định.
  - Mỗi câu chiếm 1/88 ≈ 0.011 của Hit@5. Chênh lệch dưới 0.02 (tức 2 câu) phải soi từng câu trước khi kết luận.
  - Nhóm nhỏ như `multi_turn` (9 câu) không đủ để tinh chỉnh tham số riêng cho nhóm.
- **Config:** mỗi lần chạy ghi `config_version`, toàn bộ config và commit git (`dirty` cho biết code có khác commit hay không).

---

## 0. Baseline `v0.1-baseline` (06/10/2026)

**Config:**
- Chunk tối đa 800 token, overlap 0.1, đơn vị chính là Điều.
- Embedding `text-embedding-3-small` (1536 chiều).
- Sparse BM25 tự viết: âm tiết + bigram, k1 1.2, b 0.75. IDF do Qdrant tính trên kho của user.
- Hybrid: prefetch 50 dense + 50 sparse, gộp RRF với k = 60.
- Không viết lại câu hỏi, không rerank.

**Kết quả:** `eval/results/2026-10-06_v0.1-baseline_retrieval.json` (commit `4ff0cb1`, `dirty = false`).

### Tổng quan

| Chế độ | Hit@5 | Hit@50 | Recall@5 | Recall@50 | MRR@5 | nDCG@5 | Retrieval p50 | Retrieval p95 |
|---|---|---|---|---|---|---|---|---|
| dense | 0.659 | 0.875 | 0.602 | 0.858 | 0.541 | 0.530 | 196 ms | 241 ms |
| sparse | 0.648 | 0.773 | 0.597 | 0.744 | 0.540 | 0.534 | 7 ms | 8 ms |
| hybrid | **0.670** | 0.852 | **0.625** | 0.830 | **0.586** | **0.574** | 199 ms | 244 ms |

Hybrid tốt nhất ở các metric top-5 nhưng chỉ hơn dense 0.011 Hit@5 (đúng 1 câu). Mục tiêu Hit@5 ≥ 0.85 còn cách 0.18.

### Hit@5 của hybrid theo loại câu và ngôn ngữ

| Loại | Cùng ngôn ngữ | Khác ngôn ngữ |
|---|---|---|
| `single_article` | 0.955 (22 câu) | 0.000 (11 câu) |
| `numeric` | 0.929 (14) | 0.000 (3) |
| `paraphrase` | 0.545 (11) | 0.000 (4) |
| `multi_turn` | 0.625 (8) | 0.000 (1) |
| `multi_hop` | 1.000 (14); Recall@5 0.714 | không có |
| **Tất cả** | **0.855 (69)** | **0.000 (19)** |

### Hạng của nguồn gold đầu tiên (hybrid, 88 câu)

| Hạng 1 | 2–5 | 6–10 | 11–20 | 21–50 | Ngoài top-50 |
|---|---|---|---|---|---|
| 46 | 13 | 4 | 5 | 7 | 13 |

### Chẩn đoán

Áp cách đọc trong `CLAUDE.md`: Recall@50 thấp là lỗi parse/chunk/embedding; Recall@50 cao nhưng @5 thấp là lỗi xếp hạng.

1. **Parse và chunk không phải chỗ nghẽn.**
   - 106/106 đoạn trích gold nằm trọn trong một chunk đúng trang.
   - Với câu cùng ngôn ngữ, Recall@50 đạt 0.928 (hybrid) và 0.935 (sparse).
   - `single_article` và `numeric` cùng ngôn ngữ đạt Hit@5 0.93–0.96.

2. **Khác ngôn ngữ là lỗ hổng lớn nhất: 0/19 câu.**
   - Dense có Recall@50 0.684. Nghĩa là chunk GDPR thường có trong top-50, nhưng xếp dưới các chunk Luật Bảo vệ dữ liệu cá nhân 2025 bản tiếng Việt: cùng chủ đề, cùng ngôn ngữ với câu hỏi.
   - Ví dụ g023 "GDPR định nghĩa dữ liệu cá nhân như thế nào?": top-3 của dense đều là chunk của luật Việt Nam, còn Điều 4 GDPR ở hạng 48.
   - Embedding `text-embedding-3-small` ưu tiên chunk cùng ngôn ngữ hơn chunk đúng văn bản.
   - Sparse gần như không có cơ hội (Recall@50 0.053): câu hỏi và chunk không chung từ nào. Ngay cả "GDPR" cũng chỉ xuất hiện ở dòng tiêu đề của 1/157 chunk, vì văn bản tự gọi mình là "this Regulation".
   - Cùng nguyên nhân làm 3 câu `multi_hop` so sánh luật Việt Nam với GDPR (g075, g076, g077) chỉ lấy được nguồn tiếng Việt.
   - Đây là lỗi ở bước truy vấn, không phải ở chunk.

3. **`paraphrase` cùng ngôn ngữ: 6/11 câu đạt, 5 câu trượt, chia làm hai kiểu.**
   - **Có trong top-50 nhưng xếp thấp** (hạng 8–14 ở hybrid), là bài toán xếp hạng nên rerank có thể cứu:
     - g058: hạng 8;
     - g053: hạng 13, dù sparse xếp hạng 1;
     - g051: hạng 14.
   - **Không có trong top-50:** người hỏi dùng từ đời thường, khác hẳn từ trong luật. Cần viết lại câu hỏi:
     - g052 "nộp bằng đại học bản gốc để công ty giữ" so với "giữ bản chính văn bằng";
     - g057 "bán thông tin khách hàng cho công ty quảng cáo".

4. **`multi_turn`: câu hỏi cuối thiếu ngữ cảnh.**
   - Các câu như "Trong thời gian đó tôi được trả lương thế nào?" (g093) hay "And what's the limit per year?" (g098) không nói chủ đề là gì.
   - Hit@5 0.556 là số "trước" cho bước viết lại câu hỏi theo lịch sử hội thoại.

5. **RRF làm yếu tín hiệu mạnh của một nhánh.**
   - Hit@50 của hybrid (0.852) thấp hơn dense (0.875): chunk chỉ có ở một nhánh bị các chunk có mặt ở cả hai nhánh đẩy xuống. Vì vậy chẩn đoán Recall@50 phải xem từng nhánh riêng.
   - g053: sparse xếp hạng 1, dense không có trong top-50, nên hybrid chỉ cho hạng 13. Với k = 60, hạng 1 của một nhánh được 1/61 điểm, kém một chunk đứng hạng 20 ở cả hai nhánh (2/80).

6. **Latency còn nhiều dư địa.**
   - Hybrid p95 244 ms. Gần như toàn bộ là lời gọi embed câu hỏi (p50 187 ms, p95 231 ms); Qdrant chỉ mất 7–16 ms.
   - Còn dư khoảng 556 ms so với SLO 800 ms cho các bước thêm như gọi Luna hay rerank.

### Thứ tự thí nghiệm P4

Xếp theo chỗ đang hụt:

1. **Dịch câu hỏi sang ngôn ngữ còn lại bằng `gpt-6-luna`**, truy xuất bằng cả hai câu rồi gộp RRF.
   - Nhắm vào 19 câu khác ngôn ngữ và nguồn GDPR của 3 câu `multi_hop`.
   - Thử gộp chung với bước viết lại câu hỏi multi-turn thành một lần gọi Luna.
   - Cái giá là phải gọi Luna ở mọi lượt, nên phải đo latency.
2. **Rerank bằng `gpt-6-luna` trên top-50**, nhắm vào các câu `paraphrase` đang ở hạng 7–14.
3. **So sánh `text-embedding-3-large` với `text-embedding-3-small`.**
4. **Thử lại `rrf_k` và trọng số từng nhánh.**
5. **Cấu hình chunk**, xếp cuối vì Recall@50 của câu cùng ngôn ngữ đã đạt 0.93.

**Không làm:** lọc theo tên văn bản (thấy "GDPR" trong câu hỏi thì lọc theo `doc_id`). Cách đó chỉ khớp với golden set, không dùng được cho tài liệu user upload.
