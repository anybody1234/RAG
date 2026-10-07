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
   - g053: sparse xếp hạng 1, dense không có trong top-50, nên hybrid chỉ cho hạng 13. Qdrant tính RRF là Σ 1/(k + hạng − 1). Với k = 60, hạng 1 của một nhánh được 1/60 điểm, kém một chunk đứng hạng 20 ở cả hai nhánh (2/79).

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

---

## 1. Dịch câu hỏi và viết lại multi-turn bằng `gpt-6-luna` (06/10/2026)

**Mục tiêu:** 19 câu khác ngôn ngữ (Hit@5 = 0) và 9 câu `multi_turn` (Hit@5 0.556).

**Cách làm** (`backend/app/retrieval/query.py`, prompt `query-v1`):
- Một lần gọi `gpt-6-luna` qua Responses API, `reasoning: none`, đầu ra JSON schema strict. Lần gọi này làm hai việc, bật riêng được:
  - `query.rewrite`: viết câu hỏi thành câu độc lập theo lịch sử hội thoại. Chỉ gọi khi có lịch sử.
  - `query.translate`: dịch sang ngôn ngữ còn lại (vi ↔ en). Bật thì phải gọi ở mọi lượt.
- Truy xuất bằng cả câu gốc và câu dịch:
  - Mỗi câu có một nhánh dense và một nhánh sparse; các nhánh gộp bằng RRF (k = 60). Nhánh của câu dịch có trọng số `query.translation_weight`.
  - Hai câu được embed trong cùng một request.
- Gọi Luna lỗi thì dùng nguyên câu hỏi gốc. Trong 309 lần gọi ở các lần chạy dưới đây, không lần nào lỗi.

**Kết quả** (hybrid, 88 câu có nguồn; file `eval/results/2026-10-06_v0.2-exp-*_retrieval.json`):

| Config | Hit@5 | Cùng ngôn ngữ (69) | Khác ngôn ngữ (19) | `multi_turn` (9) | MRR@5 | Hit@50 |
|---|---|---|---|---|---|---|
| baseline | 0.670 | 0.855 | 0.000 | 0.556 | 0.586 | 0.852 |
| E1: dịch | 0.750 | 0.768 | 0.684 | 0.444 | 0.505 | 0.966 |
| E1b: dịch, trọng số câu dịch 0.5 | 0.773 | 0.783 | 0.737 | 0.556 | 0.538 | 0.966 |
| E2: chỉ viết lại multi-turn | 0.705 | **0.899** | 0.000 | **0.889** | **0.637** | 0.875 |
| E3: viết lại + dịch trong một lần gọi | **0.784** | 0.797 | 0.737 | 0.778 | 0.558 | **0.977** |

**Latency** (ms, p50 / p95 trên 100 câu, chạy tuần tự):

| Config | Gọi Luna | Retrieval (embed + search) | Tổng |
|---|---|---|---|
| baseline | không gọi | 199 / 244 | 199 / 244 |
| E1 | 2205 / 4529 | 265 / 460 | 2470 / 4823 |
| E1b | 2098 / 3941 | 254 / 296 | 2401 / 4193 |
| E2 | chỉ ở 9 lượt hỏi tiếp: 1220–2080 | 197 / 218 | 198 / 1726 |
| E3 | 2191 / 4911 | 256 / 389 | 2503 / 5182 |

Chi phí Luna rất nhỏ: khoảng 140 token vào và 30 token ra mỗi lần gọi, tức $0.00003/câu.

**Nhận xét:**
1. **Dịch câu hỏi sửa được phần lớn nhóm khác ngôn ngữ.** Hit@5 của nhóm này lên 0.68–0.74 với hybrid, 0.84–0.95 nếu chỉ dùng dense. Hit@50 của hybrid lên 0.97.
2. **Nhưng nhóm cùng ngôn ngữ giảm 0.06–0.09.**
   - Ba luật Việt Nam có cả bản gốc lẫn bản dịch, nên câu dịch kéo bản song ngữ của đúng Điều đó vào top-5.
   - Ví dụ g010, g041, g064, g078 là câu tiếng Anh về Bộ luật Lao động và Luật Doanh nghiệp. Câu dịch tiếng Việt đẩy bản gốc tiếng Việt lên trên bản tiếng Anh, trong khi gold là bản tiếng Anh.
   - E3 mất đúng 6 câu loại này và được 16 câu, chủ yếu là câu khác ngôn ngữ.
   - Giảm trọng số câu dịch xuống 0.5 chỉ bớt được một phần.
3. **Gộp viết lại và dịch vào một lần gọi không tốn thêm latency** so với chỉ dịch (p50 2191 so với 2205 ms). Tuy vậy `multi_turn` kém hơn khi chỉ viết lại (0.778 so với 0.889), vì câu dịch vẫn kéo bản song ngữ vào.
4. **Chỉ viết lại ở lượt hỏi tiếp (E2) không có mặt trái.**
   - `multi_turn` tăng từ 0.556 lên 0.889, nhóm cùng ngôn ngữ từ 0.855 lên 0.899.
   - Luna chỉ được gọi ở lượt hỏi tiếp, nên lượt đầu giữ nguyên latency.
   - Câu còn trượt là g100: câu tiếng Việt về GDPR, tức vẫn là vấn đề khác ngôn ngữ.
5. **Latency là chỗ chặn.**
   - Một lần gọi Luna mất ít nhất 1.4 s, trung vị 2.2 s, p95 4–5 s, lâu nhất 12 s. Không lần nào dưới 1 s, dù đầu vào chỉ ~140 token. Đầu ra dạng text thường cũng không nhanh hơn JSON schema (đo A/B 10 lần mỗi loại: trung vị 1.51 s so với 1.57 s).
   - Probe 6 lần với priority tier được trung vị ~0.9 s, vẫn vượt dư địa.
   - Embed hai câu trong một request chậm hơn một câu khoảng 50 ms.
   - Dư địa chỉ ~556 ms, nên dịch ở mọi lượt không thể đạt retrieval p95 ≤ 800 ms.
   - Nếu tính bước viết lại riêng như định nghĩa trong `CLAUDE.md` (retrieval chỉ gồm embed + search + rerank), thì riêng p95 của bước Luna (4–5 s) đã vượt TTFT p95 ≤ 3 s.

**Kết luận:**
- **Không dùng dịch câu hỏi ở mọi lượt** với SLO hiện tại. Code vẫn giữ (`query.translate`, mặc định tắt), dùng lại được nếu SLO đổi hoặc có model nhanh hơn.
- **Giữ viết lại câu hỏi ở lượt hỏi tiếp** (E2), đúng thiết kế ban đầu ("lượt đầu bỏ qua"). Lượt hỏi tiếp sẽ chậm thêm 1.2–2.1 s; phần này phải đo cùng TTFT ở P5 và P8.
- **Nhóm khác ngôn ngữ vẫn cần một cách không tốn latency lúc hỏi.** Các bước sau sẽ thử embedding large và chunk mang tên văn bản. Mọi cách truy xuất được tài liệu khác ngôn ngữ đều sẽ gặp vấn đề bản song ngữ ở nhận xét 2.

---

## 2. Rerank bằng `gpt-6-luna` trên top-50 (06/10/2026)

**Mục tiêu:** các câu `paraphrase` có chunk đúng trong top-50 nhưng xếp hạng 7–14 (g051, g053, g058).

**Cách làm** (`backend/app/retrieval/rerank.py`, prompt `rerank-v1`):
- Rerank listwise trong một lần gọi `gpt-6-luna` (`reasoning: none`, JSON schema strict).
  - Đầu vào: câu hỏi và 50 chunk đầu của hybrid. Mỗi chunk gồm tên văn bản, `heading_path` và tối đa 200 token đầu (~7.3k token mỗi lần gọi).
  - Đầu ra: số thứ tự của tối đa 10 chunk hữu ích nhất. Các chunk còn lại giữ thứ tự cũ.
- Prompt nói rõ: chunk có thể khác ngôn ngữ với câu hỏi (xét theo nghĩa). Khi bản gốc và bản dịch nêu cùng một quy định, xếp bản cùng ngôn ngữ với câu hỏi lên trước.
  - Quy tắc này khớp với cách gán gold: câu hỏi tiếng Anh về luật Việt Nam lấy nguồn là bản dịch tiếng Anh.
  - Nó cũng khớp quy tắc sản phẩm: trả lời bằng nguồn cùng ngôn ngữ với người hỏi, và bản tiếng Việt là căn cứ khi hai bản lệch nhau.

**Kết quả** (hybrid, 88 câu có nguồn):

| Config | Hit@5 | Cùng ngôn ngữ | Khác ngôn ngữ | `paraphrase` | `multi_turn` | MRR@5 | Retrieval p95 | Tổng p95 |
|---|---|---|---|---|---|---|---|---|
| baseline | 0.670 | 0.855 | 0.000 | 0.400 | 0.556 | 0.586 | 244 ms | 244 ms |
| R1: rerank | 0.841 | 0.927 | 0.526 | 0.733 | 0.667 | 0.809 | 3.0 s | 3.0 s |
| R2: viết lại multi-turn + rerank | 0.864 | 0.957 | 0.526 | 0.733 | 0.889 | 0.837 | 3.8 s | 3.8 s |
| R3: viết lại + dịch + rerank | **0.966** | 0.957 | **1.000** | **0.867** | **1.000** | **0.932** | 3.8 s | **7.9 s** |

**Nhận xét:**
1. **Rerank là đòn bẩy lớn nhất về chất lượng.**
   - Riêng rerank tăng Hit@5 thêm 0.17 và MRR@5 thêm 0.22: được 16 câu, mất 1 câu (g018).
   - Cả ba câu `paraphrase` mục tiêu đều lên hạng 1: g051 từ 14, g053 từ 13, g058 từ 8.
   - `numeric` tăng từ 0.765 lên 0.941, `single_article` từ 0.636 lên 0.818.
2. **Rerank cứu được cả câu khác ngôn ngữ** (từ 0 lên 0.526): chunk GDPR vốn có trong top-50 nhưng xếp dưới, và LLM đọc được cả hai ngôn ngữ.
3. **Kết hợp với dịch câu hỏi (R3) thì bù được mặt trái của dịch.**
   - Nhờ quy tắc ưu tiên bản cùng ngôn ngữ, nhóm cùng ngôn ngữ không còn bị bản song ngữ chen vào (0.957 so với 0.797 ở E3 khi không có rerank).
   - Nhóm khác ngôn ngữ đạt 19/19.
   - Còn trượt 3 câu:
     - g052 và g057 không có trong top-50, vì người hỏi dùng từ đời thường;
     - g018 là câu tiếng Anh về "beneficial owner" theo luật sửa đổi 2025.
4. **Rerank không thể đạt SLO.**
   - Mỗi lần gọi mất ít nhất 1.03 s, p50 1.49 s, p95 2.8 s, lâu nhất 8.2 s. Không lần nào dưới 556 ms.
   - Theo `CLAUDE.md`, rerank nằm trong retrieval p95 ≤ 800 ms, nên riêng rerank đã vượt gần 4 lần ở p95.
   - Chi phí $0.00074/câu, chủ yếu là ~7.3k token đầu vào.
5. **Lỗi định dạng:** 3/298 lần gọi rerank lỗi; khi lỗi, hệ thống giữ nguyên thứ tự cũ.
   - 1 lần `BadRequestError`, gọi lại thì không tái hiện được.
   - 2 lần Luna trả JSON đúng rồi dính thêm rác phía sau (`{"ranking":[1,2]} ngood{...}`), dù đã bật strict schema. Đã sửa sau lần chạy: chỉ đọc object JSON đầu tiên (`parse_json_object`).

**Kết luận:**
- Với SLO hiện tại, không dùng rerank bằng Luna. Code vẫn giữ (`retrieval.reranker = "llm"`).
- R3 cho thấy **trần chất lượng** của pipeline: Hit@5 0.966, cao hơn mục tiêu 0.85. Nhưng tổng p95 là 7.9 s, gấp 10 lần retrieval SLO và vượt cả TTFT p95 ≤ 3 s trước khi kịp sinh câu trả lời.

---

## 3. `text-embedding-3-large` so với `text-embedding-3-small` (06/10/2026)

**Thay đổi:** embedding `text-embedding-3-large`, 3072 chiều, collection `chunks_text-embedding-3-large_3072`. Index toàn bộ 455k token mất $0.059, gấp 6.5 lần small. Chunk, sparse và RRF giữ như baseline.

**Kết quả** (88 câu có nguồn):

| Chế độ | Embedding | Hit@5 | Hit@50 | Recall@50 | MRR@5 | nDCG@5 | Khác ngôn ngữ Hit@5 | Cùng ngôn ngữ Hit@5 |
|---|---|---|---|---|---|---|---|---|
| dense | small | 0.659 | 0.875 | 0.858 | 0.541 | 0.530 | 0.053 | 0.826 |
| dense | large | **0.795** | **0.955** | **0.943** | **0.705** | **0.702** | **0.368** | 0.913 |
| hybrid | small | 0.670 | 0.852 | 0.830 | 0.586 | 0.574 | 0.000 | 0.855 |
| hybrid | large | 0.727 | 0.955 | 0.932 | 0.632 | 0.628 | 0.053 | 0.913 |

Sparse không đổi (0.648), vì text đem index giống hệt.

**Latency:** embed câu hỏi p50 tăng từ 188 lên 238 ms; retrieval p95 hybrid tăng từ 244 lên 296 ms, vẫn đạt SLO.

**Nhận xét:**
1. **Large tốt hơn rõ ở dense.**
   - Hit@5 tăng 0.14, Recall@50 tăng 0.09. `paraphrase` (dense) tăng từ 0.400 lên 0.733.
   - Câu khác ngôn ngữ tăng từ 0.053 lên 0.368: embedding large ít thiên về ngôn ngữ hơn.
   - Recall@50 của câu cùng ngôn ngữ đạt 0.971.
2. **Với large, hybrid lại kém dense** (0.727 so với 0.795).
   - Nhánh sparse không giúp gì cho câu khác ngôn ngữ, mà RRF còn đẩy kết quả đúng của dense xuống: Hit@5 nhóm khác ngôn ngữ của hybrid chỉ 0.053, trong khi dense đạt 0.368.
   - Cách gộp hai nhánh phải chỉnh lại; xem thí nghiệm 4.
3. **Chi phí và bộ nhớ:**
   - Mỗi user upload tốn gấp 6.5 lần khi index; PDF 100 trang khoảng 70k token, tức ~$0.009.
   - Vector chiếm 12 KB thay vì 6 KB (1282 chunk: 15.8 MB so với 7.9 MB).
   - Nếu bộ nhớ thành vấn đề, có thể thử large rút còn 1536 chiều (tham số `dimensions`).

**Kết luận:** dùng `text-embedding-3-large`. Đây là cải thiện lớn nhất không tốn latency gọi LLM.

---

## 4. `rrf_k` và trọng số từng nhánh (06/10/2026)

**Thiết lập:** embedding large (thí nghiệm 3), chế độ hybrid, mỗi nhánh prefetch 50.

Qdrant gộp RRF theo công thức score = Σ 1/(k + hạng/w − 1), với w là trọng số của nhánh. Với w = 1 đây là RRF thường: hạng 1 được 1/k điểm. Tăng w của một nhánh tương đương nén hạng của nhánh đó lại (w = 2 thì hạng 2 tính như hạng 1).

**Kết quả** (88 câu có nguồn):

| `rrf_k` | Trọng số dense / sparse | Hit@5 | Cùng ngôn ngữ | Khác ngôn ngữ | `paraphrase` | `multi_turn` | MRR@5 |
|---|---|---|---|---|---|---|---|
| 60 | 1 / 1 | 0.727 | 0.913 | 0.053 | 0.533 | 0.667 | 0.632 |
| 60 | 1 / 0.5 | 0.716 | 0.899 | 0.053 | 0.533 | 0.667 | 0.623 |
| 60 | 1 / 0.25 | 0.727 | 0.899 | 0.105 | 0.533 | 0.667 | 0.613 |
| 20 | 1 / 1 | 0.750 | 0.913 | 0.158 | 0.533 | 0.667 | 0.638 |
| 10 | 1 / 1 | 0.761 | 0.927 | 0.158 | 0.533 | 0.667 | 0.640 |
| 10 | 2 / 1 | 0.750 | 0.913 | 0.158 | 0.533 | 0.667 | 0.633 |
| 10 | 3 / 1 | 0.739 | 0.899 | 0.158 | 0.533 | 0.667 | 0.632 |
| 2 | 1 / 1 | 0.761 | 0.899 | 0.263 | 0.533 | 0.444 | 0.653 |
| 2 | 2 / 1 | **0.784** | 0.913 | 0.316 | 0.667 | 0.444 | **0.684** |
| chỉ dense | | 0.795 | 0.913 | 0.368 | 0.733 | 0.444 | 0.705 |

Retrieval p95 của mọi dòng nằm trong khoảng 277–372 ms.

**Kiểm tra thêm: câu hỏi nêu thẳng số Điều hoặc số hiệu.** Golden set hầu như không có loại câu này, trong khi đó chính là lý do `CLAUDE.md` bắt buộc hybrid ("dense hay trượt Điều 35, khoản 2, 45/2019/QH14"). Tôi thử 12 câu, ví dụ "Điều 35 Bộ luật Lao động quy định gì?", "Điều 169 Bộ luật số 45/2019/QH14", "Article 33 GDPR". Đích là chunk đầu tiên thuộc đúng văn bản và đúng Điều. Đây là phép thử nhanh, không phải golden set đã duyệt.

| Embedding | Chế độ | Đúng ở hạng 1 | Trong top-5 |
|---|---|---|---|
| small | dense | 2/12 | 4/12 |
| small, large | sparse | 1/12 | 6/12 |
| small | hybrid k = 60 | 2/12 | 6/12 |
| large | dense | **5/12** | **10/12** |
| large | hybrid k = 60 | 3/12 | 9/12 |
| large | hybrid k = 2, dense × 2 | 3/12 | 9/12 |

**Nhận xét:**
1. **Với embedding large, k nhỏ tốt hơn k = 60.** Hạng đầu của dense đã đáng tin, và k nhỏ cho hạng đầu mỗi nhánh nhiều điểm hơn.
2. **Hạ trọng số sparse khi k = 60 gần như vô tác dụng.** Với k lớn, việc nhân hạng lên 2–4 lần chỉ làm điểm đổi rất ít. Ngược lại, tăng trọng số dense khi k = 10 cũng không giúp.
3. **Hybrid tốt nhất (k = 2, dense × 2) kém chỉ dense 1 câu** (0.784 so với 0.795). Mức chênh này nằm trong nhiễu. Các cấu hình từ 0.761 đến 0.795 chỉ cách nhau 3 câu, nên tôi không tinh chỉnh thêm trên 88 câu để tránh khớp quá mức với golden set.
4. **BM25 hiện tại không làm tốt việc hybrid được kỳ vọng.**
   - Với câu hỏi nêu số Điều, sparse chỉ đưa đúng Điều vào top-5 ở 6/12 câu, trong khi dense large được 10/12.
   - Nguyên nhân: bigram "điều 35" xuất hiện ở mọi chunk có dẫn chiếu tới Điều 35, nhiều khi nhiều lần hơn ở chính chunk Điều 35. Tiêu đề "Điều 35." chỉ xuất hiện một lần, nên BM25 xếp các chunk dẫn chiếu lên trước.
   - Vì vậy tiền đề "dense trượt Điều 35 nên bắt buộc hybrid" không còn đúng với embedding large. Nhánh sparse chỉ có giá trị nếu nó nhận ra được chunk là chính Điều đó, chứ không phải chunk nhắc tới Điều đó. Một hướng sửa là thêm term riêng cho Điều của chính chunk (từ metadata `article`), và tách cụm "Điều N" trong câu hỏi thành term đó. Cách này chung cho mọi văn bản luật, kể cả tài liệu user upload.

**Kết luận:**
- Giữ hybrid theo `CLAUDE.md`, đổi cách gộp sang **`rrf_k` = 2 (mặc định của Qdrant), `dense_weight` = 2**.
- Chỉ dense cho kết quả ngang bằng. Việc bỏ hẳn nhánh sparse, hoặc sửa BM25 cho câu hỏi nêu số Điều, cần Long quyết vì đụng tới một quyết định đã chốt trong `CLAUDE.md`.

---

## 5. Cấu hình chunk (06/10/2026)

**Thiết lập:** embedding large, hybrid với `rrf_k` = 2 và dense × 2 (thí nghiệm 4). Mỗi cấu hình được index vào một collection riêng.
- `avg_doc_len` của BM25 đo lại cho từng kích thước chunk: 146 với 400 token, 239 với 1200 token.
- Riêng tuỳ chọn `index.embed_title` thêm dòng "<tên văn bản> (<số hiệu>) | <heading_path>" lên đầu text đem embed và mã hoá sparse. Payload vẫn giữ text gốc.

| Chunk | Số chunk | Hit@5 hybrid | MRR@5 hybrid | Hit@5 chỉ dense | Khác ngôn ngữ (dense) | Chi phí index |
|---|---|---|---|---|---|---|
| 800 token, overlap 0.1 (đang dùng) | 1282 | 0.784 | 0.684 | 0.795 | 0.368 | |
| 800 + tên văn bản | 1282 | **0.795** | 0.693 | **0.830** | **0.526** | $0.064 |
| 400 token | 1959 | 0.761 | 0.676 | 0.761 | 0.263 | $0.044 |
| 1200 token | 1148 | 0.784 | **0.698** | 0.818 | 0.421 | $0.021 |

Cả bốn cấu hình đều giữ 106/106 đoạn trích gold nằm trọn trong một chunk. Chi phí index nhỏ vì chunk trùng nội dung lấy embedding từ cache.

**Nhận xét:**
1. **Thêm tên văn bản giúp rõ nhất**, chủ yếu ở nhóm khác ngôn ngữ (dense từ 0.368 lên 0.526).
   - Phần lớn câu khác ngôn ngữ có nêu "GDPR", và giờ mỗi chunk GDPR đều mang dòng "General Data Protection Regulation (GDPR)".
   - Cách này khác với lọc theo tên văn bản (đã loại): nó chỉ là tín hiệu mềm trong embedding, và áp dụng được cho mọi văn bản có tên, kể cả file user upload (tên lấy từ tên file hoặc do user đặt).
   - Mặt hạn chế: phần cải thiện này bị phóng đại với những câu không nêu tên văn bản.
2. **Chunk 400 token kém hơn:** Điều bị cắt thành nhiều mảnh, mỗi mảnh ít ngữ cảnh hơn.
3. **Chunk 1200 token ngang 800 ở hybrid** và hơn 2 câu ở dense. Đổi lại, mỗi chunk dài hơn, nên mỗi câu trả lời ở P5 tốn nhiều token hơn.

**Kết luận:** giữ chunk 800 token, bật `embed_title`.

---

## 6. Chốt config `v0.2` (06/10/2026)

**Thay đổi so với `v0.1-baseline`** (đều không gọi LLM ở lượt hỏi đầu):
- `text-embedding-3-large` (3072 chiều);
- `index.embed_title = true`;
- `rrf_k` = 2, `dense_weight` = 2;
- `query.rewrite = true`: viết lại câu hỏi bằng Luna, chỉ ở lượt hỏi tiếp.

Không bật dịch câu hỏi và rerank, vì cả hai vượt SLO (thí nghiệm 1 và 2).

**Kết quả:** `eval/results/2026-10-06_v0.2_retrieval.json` (commit `b4c1364`, `dirty = false`). Lần chạy trước đó trên code chưa commit cho cùng Hit@5; MRR và nDCG lệch dưới 0.003.

| | v0.1 hybrid | **v0.2 hybrid** | v0.2 chỉ dense |
|---|---|---|---|
| Hit@5 | 0.670 | **0.864** | 0.875 |
| Hit@50 | 0.852 | 0.977 | 0.989 |
| Recall@50 | 0.830 | 0.960 | 0.972 |
| MRR@5 | 0.586 | 0.735 | 0.761 |
| nDCG@5 | 0.574 | 0.740 | 0.762 |
| Cùng ngôn ngữ, Hit@5 (69) | 0.855 | **0.986** | 0.957 |
| Khác ngôn ngữ, Hit@5 (19) | 0.000 | 0.421 | 0.579 |
| `single_article` (33) | 0.636 | 0.818 | 0.849 |
| `numeric` (17) | 0.765 | 0.882 | 0.941 |
| `multi_hop` Recall@5 (14) | 0.714 | 0.786 | 0.786 |
| `paraphrase` (15) | 0.400 | 0.733 | 0.733 |
| `multi_turn` (9) | 0.556 | **1.000** | 0.889 |
| Retrieval p95 | 244 ms | **300 ms** | 294 ms |
| Lượt hỏi tiếp (viết lại + retrieval) | | 1.6–2.9 s (lần chạy trước tới 3.3 s) | |
| Chi phí mỗi câu | $0.000001 | $0.000008 | |

**Đạt tiêu chí P4:** Hit@5 0.864 ≥ 0.85, retrieval p95 300 ms ≤ 800 ms.

**Còn hụt:**
- 11/12 câu trượt top-5 là câu tiếng Việt hỏi về GDPR.
  - 9 câu có chunk đúng ở hạng 6–43.
  - g046 và g063 không có trong top-50.
- Câu cùng ngôn ngữ duy nhất còn trượt là g057 (`paraphrase`, hạng 8).

**Lưu ý khi đọc số:**
- Khoảng 20 cấu hình được chọn trên chính 88 câu này, nên con số 0.864 có phần lạc quan.
- Cần golden set v2 (P9) để xác nhận. Golden set v2 nên có thêm câu hỏi nêu thẳng số Điều hoặc số hiệu (thí nghiệm 4).

**Việc cần Long quyết:**
1. **Nhóm khác ngôn ngữ (0.421).** Các lựa chọn:
   - **Giữ nguyên.** Không tốn gì thêm.
   - **Dịch câu hỏi ở mọi lượt.** Đo trên v0.1: thêm p50 ~2.2 s ở mọi lượt, nhóm khác ngôn ngữ lên ~0.74, nhưng nhóm cùng ngôn ngữ giảm 0.06–0.09.
   - **Dịch câu hỏi + rerank.** Hit@5 0.966, nhưng tổng p95 7.9 s.
   - **Dịch chunk lúc index** (lưu thêm vector của bản dịch). Chưa thử. Không tốn latency lúc hỏi nhưng tốn chi phí index, và sẽ gặp lại vấn đề bản song ngữ chen vào.
2. **Hybrid hay chỉ dense.** Hai cách ngang nhau trên golden set (0.864 so với 0.875). Hybrid tốt hơn ở nhóm cùng ngôn ngữ, dense tốt hơn ở nhóm khác ngôn ngữ. BM25 hiện tại yếu với câu hỏi nêu số Điều. Đề xuất: sửa BM25 bằng term "Điều N" riêng cho chunk của chính Điều đó, rồi đo lại trước khi quyết.
3. **Latency của lượt hỏi tiếp.** Viết lại câu hỏi cộng retrieval mất 1.6–3.3 s, chưa tính TTFT của Sol, nên lượt hỏi tiếp có nguy cơ vượt TTFT p95 ≤ 3 s. Phải đo ở P5.

---

## 7. Kho 10 văn bản (thêm Nghị định 356/2025) và sửa lỗi chữ ký số (07/10/2026)

**Không phải thí nghiệm chọn config.** Config giữ nguyên `v0.2`; chỉ kho dữ liệu đổi. Đây là baseline mới cho mọi so sánh sau này.

**Thiết lập:** golden set v1 (88 câu có nguồn), 3 lần chạy, mỗi lần trên một commit sạch.
- **9 văn bản:** `v0.2` ở `b4c1364` (lần chạy lại của thí nghiệm 6), 1282 chunk.
- **kho10:** `v0.2-kho10` ở `cefbb3a`. Thêm Nghị định 356/2025 (chỉ có tiếng Việt, 100 chunk), 1382 chunk.
- **kho10-chuky:** `v0.2-kho10-chuky` ở `dd9590d`. Như kho10, cộng bản sửa chữ ký số: chữ ký số trang 1 không còn lọt vào chunk ở 3 văn bản, mỗi văn bản đổi 1 chunk. 1381 chunk.

Từ lần chạy này, kết quả ghi `corpus` (sha256 của manifest và số chunk của từng văn bản trong index).

| | 9 văn bản | kho10 | kho10-chuky |
|---|---|---|---|
| Hit@5 hybrid | 0.864 | 0.841 | **0.830** |
| MRR@5 hybrid | 0.735 | 0.728 | 0.717 |
| Recall@50 hybrid | 0.960 | 0.938 | 0.938 |
| Hit@5 chỉ dense | 0.875 | 0.830 | 0.818 |
| Hit@5 cùng ngôn ngữ (69) | 0.986 | 0.986 | 0.971 |
| Hit@5 khác ngôn ngữ (19) | 0.421 | 0.316 | 0.316 |
| Retrieval p95 hybrid | 300 ms | 318 ms | 370 ms |

Theo văn bản chứa nguồn gold (hybrid, Hit@5 / MRR@5):

| Nhóm | n | 9 văn bản | kho10 | kho10-chuky |
|---|---|---|---|---|
| GDPR | 23 | 0.522 / 0.323 | 0.435 / 0.273 | 0.435 / 0.295 |
| Luật BVDLCN 2025 (vi + en) | 11 | 0.909 / 0.864 | 0.909 / 0.864 | 0.909 / 0.818 |
| Văn bản còn lại | 54 | 1.000 / 0.885 | 1.000 / 0.894 | 0.981 / 0.876 |

**Nhận xét:**
1. **Nghị định 356 cạnh tranh trực tiếp với GDPR.**
   - Chunk của Nghị định có mặt trong top-5 hybrid ở 17/23 câu GDPR và 9/11 câu BVDLCN. Không câu nào thuộc nhóm văn bản còn lại bị ảnh hưởng.
   - GDPR mất 2 câu ở top-5: g025 (hạng 3 → 8) và g060 (5 → 10). g031 và g061 rơi khỏi top-50.
   - Câu GDPR hầu hết hỏi bằng tiếng Việt, nên thêm một văn bản tiếng Việt cùng chủ đề càng đẩy GDPR xuống. Đây là cùng một lỗ hổng khác ngôn ngữ đã ghi ở thí nghiệm 6, nay nặng hơn (0.421 → 0.316). P4b (chia nhánh dense theo ngôn ngữ, dịch chunk lúc index) cần đo lại trên kho này.
   - Nhóm BVDLCN giữ nguyên Hit@5: câu hỏi tiếng Việt và văn bản tiếng Việt, Nghị định chỉ chen vào các vị trí sau.
2. **Sửa lỗi chữ ký số làm mất 1 câu (g017, hạng 1 → 6), do ranh giới chunk đổi.**
   - Trước khi sửa, 4 dòng chữ ký số (~40 token) ở trang 1 luật 76/2025 làm Khoản 1 Điều 1 vượt 800 token, nên bị tách theo điểm. Định nghĩa "chủ sở hữu hưởng lợi" nhờ vậy nằm trong một chunk nhỏ, tập trung, và đứng hạng 1.
   - Sau khi sửa, Khoản 1 vừa một chunk (771 token, gồm cả loạt định nghĩa sửa đổi của Điều 4), nên định nghĩa đó bị loãng.
   - Bản sửa là đúng (bỏ rác). Kết quả hạng 1 trước đây là may mắn của ranh giới chunk, và chỉ chênh 1/88 câu, ở mức nhiễu. Nó cho thấy chunk dài nhiều định nghĩa là điểm yếu của chunker: Khoản liệt kê nhiều định nghĩa nên được tách theo điểm sớm hơn. Ghi lại để xem xét, chưa sửa.
3. **Retrieval p95 vẫn đạt SLO** (370 ms ≤ 800 ms). Phần tăng nằm ở bước embed câu hỏi (p95 276 → 357 ms, là latency API của OpenAI); search của Qdrant vẫn khoảng 14 ms dù kho lớn hơn 8%.
4. **Hit@5 hybrid 0.830 < 0.85** trên kho mới. Mức hụt nằm hết ở nhóm khác ngôn ngữ, đúng chỗ P4b nhắm tới.

**Chi phí:** index Nghị định 356 $0.0083; index lại sau khi sửa chữ ký $0.0005 (1376/1381 chunk lấy từ cache); hai lần eval $0.0016. Ledger ghi tổng $0.0103 cho ngày 07/10.

**Kết quả:** `eval/results/2026-10-07_v0.2-kho10_retrieval.json`, `eval/results/2026-10-07_v0.2-kho10-chuky_retrieval.json`.

---

## 8. Prompt judge: rò rỉ ví dụ từ golden set, và `judge-v2` (08/10/2026)

**Không phải thí nghiệm chọn config.** Ghi lại để biết số chấm bằng judge nào thì tin được tới đâu.

**Lỗi rò rỉ ở `judge-v1`.**
- Ví dụ few-shot trong `eval/judges/judge-v1.md` gần như là câu g034 của golden v1 (thời gian thử việc tối đa với trình độ cao đẳng), kể cả nguyên văn đoạn trích khoản 2 Điều 25.
- Khi chấm g034, judge đã thấy sẵn "expected output". Nếu g034 lọt vào bộ mẫu hiệu chỉnh, mức đồng thuận bị đẩy lên giả tạo.
- `judge-v1` được giữ nguyên, vì đã dùng để chấm `2026-10-08_v0.2-luna_e2e-n5.json`. **Mọi số chấm bằng `judge-v1` chỉ dùng để thử quy trình**, không dùng làm số liệu.

**`judge-v2`** (config dùng từ 08/10):
- Ví dụ thay bằng luật hư cấu ("Luật Cây xanh đô thị", "Ruritania Tree Protection Act"), không trùng câu hỏi hay Điều nguồn nào của golden v1, v2 và bản nháp v2.
- Test `backend/tests/test_judge_prompts.py` so mọi chuỗi 7 từ liên tiếp (sau `normalize_for_match`) của prompt judge với câu hỏi, lịch sử, đoạn trích và đáp án chuẩn của mọi file `golden_*.jsonl`. Test bắt được lỗi của v1 (25 chuỗi trùng g034). `judge-v1` được bỏ qua có chủ đích.
- Thêm quy tắc cho câu trả lời từ chối: câu "tài liệu không nói về Y" là nói về tài liệu, không phải claim.
  - Groq (`openai/gpt-oss-120b`) chấm bằng v1 đã tính câu này là claim không được ủng hộ, kéo faithfulness của câu từ chối có giải thích xuống (g061: 0.667).
  - Lỗi này lặp lại ở mọi câu từ chối có kèm giải thích, nên làm lệch faithfulness một cách hệ thống.
- Kiểm chứng bằng Groq trên g061 và g081: xem phần kết quả trong TASKS.md P5.
