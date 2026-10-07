# Kế hoạch và danh sách task

**Timeline:** 10 tuần, khoảng 10 giờ/tuần, từ 06/10/2026 đến 14/12/2026. Mục tiêu là có dự án hoàn chỉnh trước đợt tuyển thực tập T1–T3/2027.

**Ký hiệu:**
- **[L]**: việc Long phải tự làm (tài khoản, duyệt, chấm tay, quyết định).
- Các task còn lại do Claude làm và Long review.

**Tiêu chí hoàn thành:** mỗi giai đoạn có tiêu chí đo được. Chỉ số mục tiêu nằm trong `CLAUDE.md`.

| Tuần | Ngày | Giai đoạn |
|---|---|---|
| 1 | 06–12/10 | P0 Setup ban đầu · bắt đầu P1 Golden set |
| 2 | 13–19/10 | P1 Golden set · bắt đầu P2 Ingestion |
| 3 | 20–26/10 | P2 Ingestion · bắt đầu P3 Retrieval |
| 4 | 27/10–02/11 | P3 Index + retrieval baseline |
| 5 | 03–09/11 | P4 Thí nghiệm retrieval · bắt đầu P5 |
| 6 | 10–16/11 | P5 Sinh câu trả lời + eval end-to-end |
| 7 | 17–23/11 | P6 Backend API |
| 8 | 24–30/11 | P7 Frontend |
| 9 | 01–07/12 | P8 Đo hệ thống và tối ưu |
| 10 | 08–14/12 | P9 Hoàn thiện portfolio |

---

## P0. Setup ban đầu (tuần 1)
- [x] Repo GitHub, `.venv` Python 3.13, requirements đã ghim version, `docker-compose.yml`
- [x] Bộ dữ liệu: `data/manifest.json` + `scripts/download_data.py`, 9 văn bản đều có lớp text
- [x] Khung backend:
  - Settings đọc `.env` (`backend/app/core/config.py`)
  - Config RAG có `config_version` (`config/rag.toml`)
  - Health check `/api/health/live` và `/api/health/ready`
- [x] Khung frontend React + Vite + TS, proxy `/api` sang backend
- [x] CI GitHub Actions: ruff + pytest (backend), lint + build (frontend)
- [x] File `.env` local, `JWT_SECRET` đã sinh sẵn
- [x] `scripts/check_env.py` kiểm tra key OpenAI và Langfuse, các model trong config, các service
- [x] `%UserProfile%\.wslconfig` giới hạn WSL ở 3GB RAM
- [x] Bật Virtual Machine Platform và đặt `hypervisorlaunchtype auto` (06/10). Có hiệu lực sau khi khởi động lại máy.
- [x] **[L]** Tạo OpenAI API key, dán vào `.env`. Đã kiểm tra: dùng được `gpt-6.1-sol`, `gpt-6-luna`, `text-embedding-3-small`.
- [x] **[L]** Tạo tài khoản Langfuse Cloud (EU), dán key vào `.env`. Đã kiểm tra: `auth_check` OK.
- [x] **[L]** Khởi động lại máy để Virtual Machine Platform có hiệu lực
- [x] Bật Docker Desktop (engine 29.8.2, giới hạn RAM ~2.8 GiB), chạy `docker compose up -d`

**Hoàn thành khi:** CI xanh; `python scripts/check_env.py` báo tất cả đều ổn.

**Kết quả (06/10):** đã hoàn thành.
- CI xanh.
- `check_env.py` đạt 13/13 mục.
- `/api/health/ready` trả HTTP 200 cho postgres, qdrant và redis.

## P1. Golden set v1 (tuần 1–2)
- [x] Đối chiếu tình trạng hiệu lực và văn bản sửa đổi qua văn bản hợp nhất trên Công báo (18/VBHN-VPQH, 67/VBHN-VPQH), cập nhật `amended_by`, `amended_articles`, `consolidated` trong `data/manifest.json`
- [x] Schema (`backend/app/evaluation/golden.py`) và script `eval/validate_golden.py`. Script kiểm tra:
  - Đủ các trường bắt buộc và đúng quy tắc theo loại câu hỏi.
  - Đúng phân bố loại câu hỏi.
  - Có ≥ 20% câu khác ngôn ngữ với nguồn.
  - `quote` thật sự xuất hiện ở đúng trang PDF đã ghi (có `--fix-pages` để tự sửa số trang).
- [x] Claude soạn nháp 100 câu (06/10). Kết quả:
  - Đúng phân bố cả 6 loại, 19% câu khác ngôn ngữ với nguồn (22% tính trên câu có nguồn).
  - 100% đoạn trích được xác minh có thật trong PDF.
  - ~~Không câu nào hỏi vào Điều đã bị sửa đổi.~~ Sai: g014 hỏi vào Điều 207, đã sửa ngày 06/10. Validator nay tự kiểm tra lỗi này.
- [x] Công cụ duyệt `eval/review_golden.py`: `export` tạo `golden_v1_review.md`, `apply` áp kết quả duyệt vào JSONL
- [x] **[L]** Duyệt `eval/datasets/golden_v1_review.md` (khoảng 3–4 giờ): tick câu đúng, ghi chú câu cần sửa, rồi chạy `python eval/review_golden.py apply`
  - 06/10: Claude duyệt theo yêu cầu của Long, đối chiếu từng đáp án với toàn văn Điều trong PDF. Kết quả 97/100 đạt, 3 câu có ghi chú (g014, g054, g078).
  - g014 hỏi vào Điều 207 Luật Doanh nghiệp, Điều này đã bị luật 76/2025 sửa. Vì vậy dòng "Không câu nào hỏi vào Điều đã bị sửa đổi" ở trên là sai.
- [x] Sửa các câu có ghi chú (06/10):
  - g014 đổi sang `multi_hop`, thêm nguồn luật 76/2025 trang 6, đáp án theo điểm c khoản 1 Điều 207 đã sửa (thêm "cổ đông").
  - g054 thêm nguồn Điều 106 trang 44.
  - g078 đổi sang `single_article`.
  - Phân bố không đổi.
- [x] Duyệt lại 3 câu g014, g054, g078 (06/10, Claude duyệt theo yêu cầu của Long, đối chiếu với toàn văn Điều):
  - g014 và g054 đạt.
  - g078 bổ sung lộ trình tuổi nghỉ hưu từ năm 2021 (60 tuổi 3 tháng, mỗi năm tăng 3 tháng) vào đáp án và thêm đoạn trích trang 64, để trả lời đúng câu "What is the retirement age" và nhất quán với g007.
- [x] **[L]** Quyết định về người duyệt (06/10). Long đã đọc phần sửa và đồng ý, giao Claude duyệt. Ghi nhận: golden set v1 được Claude duyệt bằng cách đối chiếu toàn văn Điều trong PDF, Long chấp thuận. Đây là ngoại lệ có chủ đích so với quy tắc "người duyệt" trong `CLAUDE.md`. Nên được nhắc tới khi trình bày kết quả eval.
- [x] Bổ sung `amended_articles` trong `data/manifest.json` (06/10). Ghi nguồn xác minh vào trường mới `amended_articles_source`.
  - **Luật Doanh nghiệp:** lập lại từ toàn văn, được 33 Điều.
    - Luật 76/2025 (khoản 1–28 Điều 1) sửa 27 Điều, gồm đủ 11 Điều còn thiếu: 8, 11, 13, 20, 22, 33, 52, 112, 140, 207, 215.
    - Luật 03/2022 (Điều 7, tải từ Công báo) sửa Điều 49, 50, 60, 109, 148, 158, 217.
    - Danh sách cũ còn ghi sai thừa 14 Điều (3, 5, 9, 12, 14, 18, 24, 28, 35, 53, 113, 129, 208, 218) và ghi nhầm 51, 61 thay cho 50, 60. Nguyên nhân: danh sách cũ được dò theo trang chú thích của văn bản hợp nhất, cách này bị lệch.
  - **Bộ luật Lao động:** đối chiếu lại với chú thích của 18/VBHN-VPQH. Có đúng 4 chú thích sửa đổi: Điều 60 khoản 2, Điều 62, Điều 139 khoản 1, Điều 154 (khoản 8a). Không thể kiểm tra từ `data/raw/` vì các luật sửa đổi không có trong bộ dữ liệu.
- [x] `validate_golden.py` tự báo lỗi khi đoạn trích nằm trong Điều có ở `amended_articles` mà câu hỏi không có nguồn từ luật sửa đổi. Chạy thử trên bản trước khi sửa: bắt đúng g014 và không báo nhầm câu nào khác.

**Hoàn thành khi:** có `eval/datasets/golden_v1.jsonl` gồm 100 câu đã duyệt, script kiểm tra pass.

**Kết quả (06/10):** đã hoàn thành.
- 100/100 câu đã duyệt.
- `validate_golden.py` không có lỗi.
- Phân bố: single_article 33, numeric 17, multi_hop 14, paraphrase 15, unanswerable 12, multi_turn 9.
- 22% câu có nguồn là câu khác ngôn ngữ với nguồn.

## P2. Ingestion (tuần 2–3)
- [x] Parser PDF (`backend/app/ingestion/pdf.py`):
  - Giữ số trang, đánh liên tục qua các file của một văn bản.
  - Bỏ header `CÔNG BÁO/Số .../Ngày ...`, số trang, chữ ký số "Ký bởi: ...", dòng "(Xem tiếp/Tiếp theo Công báo số ...)", và header lặp phát hiện tự động (ví dụ "Translated Version by Viet An Law Firm").
  - Đánh dấu trang `needs_ocr` (dưới 50 ký tự và có ảnh); interface `OcrEngine` để gắn OCR sau.
  - **Thay đổi so với kế hoạch:** văn bản luật dùng text thô theo dòng của PyMuPDF, chỉ tài liệu khác mới dùng `pymupdf4llm`. Trên 9 văn bản luật, cùng một chunker: text thô nhận đúng 1059/1059 Điều, 106/106 đoạn trích gold nằm trọn trong một chunk đúng trang, mất 3 s. `pymupdf4llm` chỉ được 1054/1059 Điều, 102/106 đoạn trích, mất 160 s. Nguyên nhân: nó dính tiêu đề Điều vào đoạn trước (Điều 146 Bộ luật Lao động), tách một điểm thành nhiều list item, và chèn thẻ `<mark>`. Đã cập nhật bảng quyết định trong `CLAUDE.md`.
- [x] Parser DOCX, HTML, MD/TXT; từ chối `.doc` kèm thông báo đổi sang `.docx` (`parsers.py`). DOCX/HTML được đưa về markdown đơn giản (heading `#`, bảng `| |`). Văn bản luật được tự nhận ra (≥ 3 tiêu đề Điều/Article) ở mọi định dạng.
- [x] Làm sạch văn bản: `clean_vietnamese_text`, và `fix_replacement_chars` để sửa `�`. Ghi chú: PyMuPDF trích bản dịch Luật Bảo vệ dữ liệu cá nhân ra không có `�` nào, nên hàm này chưa có tác dụng trên bộ dữ liệu hiện tại (đã sửa `data/SOURCES.md`).
- [x] Tách chữ ghép (NFKC, chỉ áp cho ký tự chữ ghép) và nối từ bị gạch nối cuối dòng. Việc giữ hay bỏ gạch nối dựa vào chính văn bản: "particular" xuất hiện ở chỗ khác thì nối liền, "fixed-term" xuất hiện ở chỗ khác thì giữ gạch nối. GDPR có 206 chỗ ngắt từ, sau xử lý không còn chỗ nào.
- [x] Chunker cho văn bản luật (`legal_chunker.py`):
  - Tiếng Việt theo Phần/Chương/Mục/Điều/Khoản/Điểm; tiếng Anh theo Part/Chapter/Section/Article/Clause/Point.
  - Một dòng chỉ được nhận là tiêu đề Điều khi nằm trong dãy số Điều tăng dần dài nhất. Nhờ vậy loại được các dẫn chiếu như "Article 290 TFEU should be..." trong Recitals của GDPR và "Article 32." trong phần sửa luật khác ở Bộ luật Lao động bản tiếng Anh. Nội dung sửa đổi trong ngoặc kép (“Điều 12. ...) cũng không bị nhận là tiêu đề.
  - Điều dài thì gom các Khoản liền nhau. Khoản quá dài thì tách theo Điểm và lặp lại câu dẫn của Khoản. Cuối cùng mới tách theo câu. Mọi chunk đều lặp lại tiêu đề Điều ở dòng đầu.
  - Mỗi chunk có `heading_path` (ví dụ "Chương III > Mục 3 > Điều 35 > Khoản 2"), `article`, `page`/`page_end`, `token_count`, `content_hash`.
  - 2 file Luật Doanh nghiệp được gộp thành 1 `doc_id`.
- [x] Chunker chung (`generic_chunker.py`): chia theo heading markdown, gom đoạn theo độ dài, overlap theo đoạn (≤ `overlap_ratio` × `max_tokens`).
- [x] Lệnh `python scripts/ingest.py` xuất chunk ra `data/processed/<doc_id>.jsonl` và in bảng tổng kết (`--doc`, `--file`).
- [x] Test (`backend/tests/`): unit test cho làm sạch, parser và 2 chunker (chạy trên CI), cộng 15 test trên dữ liệu thật (`test_ingest_real_data.py`, tự bỏ qua khi chưa tải `data/raw/`):
  - Nhận đủ Điều/Article theo đúng thứ tự 1..N: 220 / 218 / 39 / 3 (vi), 220 / 218 / 39 / 3 (en), 99 (GDPR).
  - Không chunk nào vượt `max_tokens`.
  - Không còn header Công báo, chữ ký số, `�` hay chữ ghép trong chunk.
  - Mọi đoạn trích của golden set nằm trọn trong một chunk có khoảng trang chứa trang gold. Nếu không đạt điều này, retrieval eval ở P3 không thể tính trúng.

**Hoàn thành khi:** nhận đúng 100% số Điều/Article trên toàn bộ dữ liệu, test pass.

**Kết quả (06/10):** đã hoàn thành với `config_version = v0.1-baseline` (`max_tokens` 800, `overlap_ratio` 0.1, đếm token bằng cl100k_base của `text-embedding-3-small`).
- 9/9 văn bản OK, 669 trang, 0 trang `needs_ocr`, 0 file lỗi.
- 1282 chunk, tối đa 796 token. Parse + chunk mất dưới 1 s mỗi văn bản (chưa tính embedding).
- Nhận đúng 1059/1059 Điều/Article. 106/106 đoạn trích gold nằm trọn trong một chunk đúng trang.
- 64/64 test pass, `ruff` sạch.

## P3. Index + retrieval baseline (tuần 3–4)
- [x] Gọi embedding OpenAI (`backend/app/retrieval/embedding.py`):
  - Gửi theo batch, tối đa 256 input và 200k token mỗi request (API cho phép 2048 input, 300k token).
  - Retry bằng `max_retries=5` của SDK `openai`: backoff khi gặp 408/409/429/5xx, timeout hoặc lỗi kết nối, tôn trọng Retry-After.
  - Token lấy từ `usage` của API. Chi phí tính theo `[prices]` trong `config/rag.toml`.
  - Cache theo (model, số chiều, sha256 nội dung) trong `data/cache/embeddings.sqlite`. Câu hỏi không cache, để latency đo được là latency thật.
- [x] Tokenizer BM25 (`sparse.py`):
  - NFC, chữ thường, âm tiết/từ + bigram âm tiết. Bigram không nối qua dấu câu hoặc xuống dòng. Số có dấu phân cách được giữ nguyên ("20.000.000").
  - Vector văn bản mang phần TF của BM25 (k1 1.2, b 0.75, `avg_doc_len` 215 đo trên bộ dev); vector câu hỏi có trọng số 1; IDF do Qdrant tính.
- [x] Collection Qdrant `chunks_text-embedding-3-small_1536` (`index.py`):
  - Dense (cosine) + sparse với `modifier: idf`.
  - Payload gồm metadata chunk, `user_id`, `amended_by` (văn bản bị sửa bởi những luật nào) và `amended` (Điều chứa chunk có trong `amended_articles`; 97/1282 chunk). Có payload index cho `user_id` (`is_tenant`) và `doc_id`.
  - Point ID = uuid5(`user_id:doc_id:content_hash`). Index lại một văn bản thì upsert rồi xoá các point cũ không còn trong lần này. Chạy lại không đổi gì và không tốn tiền.
  - Bộ dev được index dưới `user_id = "system"` bằng `python scripts/index.py`.
- [x] Truy vấn 3 chế độ dense / sparse / hybrid (`search.py`), chọn bằng `retrieval.mode`:
  - Hybrid: prefetch 50 dense + 50 sparse, gộp bằng RRF với k = 60 (mặc định của Qdrant là 2).
  - Filter `user_id` nằm trong từng prefetch. IDF của nhánh sparse chỉ tính trên kho của user đó (`IdfCorpusParams`), nên tài liệu của user khác không làm lệch trọng số.
- [x] `eval/run_retrieval_eval.py`:
  - Chunk trúng khi đúng `doc_id`, khoảng trang chứa trang gold và text chứa đoạn trích.
  - Tính Hit, Recall, MRR, nDCG ở top-5 và top-50. Báo cáo chia theo `type`, theo ngôn ngữ câu hỏi và theo nhóm khác ngôn ngữ.
  - Câu `multi_turn` dùng câu hỏi cuối chưa viết lại. Câu `unanswerable` không tính metric, chỉ tính latency.
  - Đo latency từng bước: embed, sparse, search.
- [x] Test: 34 test mới (tokenizer, batch/cache embedding, metric, index + truy vấn trên Qdrant in-memory, cách ly giữa 2 user, IDF tính theo kho của từng user, index lại idempotent, cờ `amended`). Tổng 98/98 pass, `ruff` sạch.
- [x] Chạy baseline 3 chế độ trên commit sạch `4ff0cb1`, lưu vào `eval/results/2026-10-06_v0.1-baseline_retrieval.json` (ghi `git.dirty = false`)

**Hoàn thành khi:** có số baseline cho cấu hình `v0.1-baseline`.

**Kết quả (06/10):** đã hoàn thành. Chẩn đoán chi tiết nằm ở `docs/experiments.md`.
- Index: 1282 chunk, 455k token, $0.0091. Chạy lại thì 100% lấy từ cache, $0. 106/106 nguồn gold nằm trọn trong một chunk của index.
- 88 câu có nguồn. Latency đo tuần tự trên 100 câu, chưa có tải đồng thời:

  | Chế độ | Hit@5 | Hit@50 | Recall@50 | MRR@5 | nDCG@5 | Retrieval p95 |
  |---|---|---|---|---|---|---|
  | dense | 0.659 | 0.875 | 0.858 | 0.541 | 0.530 | 241 ms |
  | sparse | 0.648 | 0.773 | 0.744 | 0.540 | 0.534 | 8 ms |
  | hybrid | **0.670** | 0.852 | 0.830 | **0.586** | **0.574** | 244 ms |

- Hit@5 của hybrid theo nhóm:

  | Nhóm | n | Hit@5 |
  |---|---|---|
  | Cùng ngôn ngữ | 69 | 0.855 |
  | Khác ngôn ngữ | 19 | 0.000 (dense 0.053) |
  | `multi_hop` (Recall@5) | 14 | 0.714 |
  | `numeric` | 17 | 0.765 |
  | `single_article` | 33 | 0.636 |
  | `multi_turn` (số "trước" cho bước viết lại câu hỏi) | 9 | 0.556 |
  | `paraphrase` | 15 | 0.400 |

- Retrieval p95 đạt SLO (≤ 800 ms), còn dư khoảng 556 ms. Gần như toàn bộ thời gian là lời gọi embed câu hỏi (p50 187 ms); Qdrant chỉ mất 7–16 ms.
- Chạy 2 lần trên cùng code: MRR@5 của hybrid lệch 0.006 (0.592 và 0.586), vì embedding của OpenAI không hoàn toàn tất định. Đây là mức nhiễu nền khi so sánh thí nghiệm.


## P4. Thí nghiệm retrieval (tuần 5)
Thứ tự xếp theo chỗ đang hụt (Long chốt 06/10). Số trước/sau và nhận xét của từng thí nghiệm nằm trong `docs/experiments.md`.
- [x] So sánh dense / sparse / hybrid: số baseline có ở P3
- [x] Hạ tầng thí nghiệm (06/10):
  - `--set khoá=giá_trị` trong `scripts/index.py` và `eval/run_retrieval_eval.py`; thí nghiệm bắt buộc có `config_version` riêng.
  - Chữ ký index lưu trong metadata collection, nên index của thí nghiệm này không ghi đè được index của thí nghiệm khác.
  - Eval ghi latency từng bước (rewrite, embed, sparse, search, rerank) và chi phí mỗi câu. 119 test pass.
- [x] Dịch câu hỏi bằng `gpt-6-luna` và gộp với bước viết lại multi-turn (thí nghiệm 1):
  - Dịch: nhóm khác ngôn ngữ tăng từ 0 lên 0.68–0.74, nhưng nhóm cùng ngôn ngữ giảm 0.06–0.09 vì bản song ngữ chen vào.
  - Luna mất p50 2.2 s, p95 4–5 s, min 1.4 s; không lần gọi nào dưới 1 s. **Không dùng**, vì vượt SLO.
  - Gộp viết lại và dịch vào một lần gọi không tốn thêm latency, nhưng `multi_turn` kém hơn chỉ viết lại.
  - **Dùng viết lại ở lượt hỏi tiếp:** `multi_turn` tăng từ 0.556 lên 0.889. Cũng là việc P5 cần.
- [x] Rerank bằng `gpt-6-luna` trên top-50 (thí nghiệm 2):
  - Hit@5 tăng từ 0.670 lên 0.841. Ba câu `paraphrase` mục tiêu lên hạng 1.
  - Mất p50 1.5 s, p95 2.8 s. **Không dùng**, vì vượt SLO.
  - Viết lại + dịch + rerank đạt Hit@5 **0.966**, nhưng tổng p95 7.9 s: đây là trần chất lượng.
- [x] `text-embedding-3-large` so với small (thí nghiệm 3): dense Hit@5 tăng từ 0.659 lên 0.795, latency chỉ thêm ~50 ms. **Dùng large.**
- [x] `rrf_k` và trọng số từng nhánh (thí nghiệm 4): **chọn k = 2, dense × 2.**
  - Với large, hybrid ngang chỉ dense.
  - BM25 hiện tại yếu với câu hỏi nêu thẳng số Điều: đúng 6/12 câu trong top-5, trong khi dense large được 10/12.
- [x] Cấu hình chunk (thí nghiệm 5): chunk 400 token kém hơn, 1200 token ngang 800. **Dùng 800 token và thêm tên văn bản vào text đem embed** (dense Hit@5 tăng từ 0.795 lên 0.830).
- [x] Chốt config `v0.2` (thí nghiệm 6), ghi bảng so sánh vào `docs/experiments.md`
- **Không làm:** lọc theo tên văn bản (thấy "GDPR" thì lọc theo `doc_id`). Cách đó chỉ khớp với golden set, không dùng được cho tài liệu user upload.
- [ ] **[L]** Quyết định 3 việc ở cuối `docs/experiments.md`:
  - nhóm khác ngôn ngữ (giữ nguyên, dịch câu hỏi, hay dịch lúc index);
  - hybrid hay chỉ dense;
  - latency của lượt hỏi tiếp so với TTFT.
- [x] Chạy lại `v0.2` trên commit sạch `b4c1364` (`dirty = false`): Hit@5 hybrid vẫn 0.864, retrieval p95 300 ms

**Hoàn thành khi:** Hit@5 ≥ 0.85, hoặc ghi rõ khoảng cách còn thiếu và nguyên nhân.

**Kết quả (06/10):** đạt với `config_version = v0.2`:
- Hit@5 hybrid **0.864**, MRR@5 0.735, Recall@50 0.960.
- Retrieval p95 **300 ms**.
- Nhóm cùng ngôn ngữ đạt 0.986, `multi_turn` đạt 9/9. Nhóm khác ngôn ngữ còn 0.421, và 11/12 câu trượt thuộc nhóm này.
- Số này có phần lạc quan, vì khoảng 20 cấu hình được chọn trên chính 88 câu. Cần golden set v2 để xác nhận.
- Chi phí API của cả ngày thí nghiệm khoảng $0.46.

## P5. Sinh câu trả lời + eval end-to-end (tuần 5–6)
Thứ tự từ 07/10: Boss duyệt từng commit. Chỉ tinh chỉnh prompt/config trên golden v1, vì golden v2 là bộ test giữ riêng.
- [x] Prompt trả lời `answer-v1` (`backend/app/generation/prompts.py`):
  - Mỗi chunk nằm trong `<document index="n" ...>`; text chunk không đóng được tag.
  - Mỗi ý gắn trích dẫn `[n]`.
  - Thiếu thông tin thì trả "Không tìm thấy trong tài liệu." (câu hỏi tiếng Anh: "Not found in the documents.").
  - Hai bản lệch nhau thì bản tiếng Việt là căn cứ.
- [x] Gọi LLM qua Responses API có streaming và đo TTFT (`answer.py`). Kiểm tra mọi `[n]`, map sang số hiệu, Điều/Khoản và trang (`citations.py`).
- [x] Cảnh báo Điều bị sửa đổi, 2 lớp:
  - Chunk có `amended` mang thuộc tính `amended_by` trong prompt; model dùng luật sửa đổi nếu có trong context.
  - Backend sinh cảnh báo tất định cho mỗi Điều bị sửa được trích dẫn, nằm trong `AnswerResult`.
  - Golden v1 không hỏi vào Điều bị sửa, nên đường này chỉ được kiểm tra bằng unit test.
- [x] Giá có cache: `cached_input` và `cache_write` trong `[prices]`.
  - Từ GPT-5.6, mặc định OpenAI tự ghi cache (1.25 lần giá input) cho prompt ≥ 1024 token. Context RAG không bao giờ dùng lại, nên mọi lời gọi LLM dùng mode `explicit`.
- [x] Đo TTFT của Sol (`eval/measure_ttft.py`, 06/10, code chưa commit, 28 câu):
  - TTFT của LLM: p50 1.71 s, p95 2.47 s.
  - TTFT user lượt đầu: p95 3.00 s. Lượt hỏi tiếp: p95 4.87 s, vượt SLO, vì riêng bước viết lại câu hỏi đã mất p95 2.50 s.
  - Sol chỉ nhận effort từ `low` trở lên; ở `low` model dùng 0 token suy luận.
- [x] Viết lại câu hỏi multi-turn bằng `gpt-6-luna` (làm ở P4: `backend/app/retrieval/query.py`, `query.rewrite`).
- [x] Code cho hạn của bước viết lại câu hỏi (`query.rewrite` = none | concat | llm, `query.rewrite_timeout_ms`): `concat` ghép câu hỏi trước của user với câu hiện tại, không gọi LLM; `llm` quá hạn hoặc lỗi thì dùng cách ghép.
- [ ] Đo 3 cách (chỉ ghép, LLM, LLM có hạn 1.5 s) cả về chất lượng lẫn TTFT lượt hỏi tiếp, với Sol và Luna (`measure_ttft.py --follow-up-only`). Cần Docker.
- [x] Trần chi phí (`backend/app/core/costs.py`), chặn trước khi gọi API, dựa trên ước tính chi phí tối đa của lời gọi:
  - trần ngày `DAILY_COST_LIMIT_USD` = $0.50 và trần cả dự án `PROJECT_COST_LIMIT_USD` = $2.80 (07/10: tài khoản còn $3.26 cho cả dự án);
  - chi phí thật ghi vào ledger SQLite dùng chung cho mọi checkout (`COST_LEDGER_PATH`, mặc định `~/.rag-chatbot/costs.sqlite`), kèm provider và số token để đếm quota của provider miễn phí;
  - lời gọi bị huỷ, timeout, lỗi 5xx hoặc stream đứt thì ghi mức tối đa đã giữ chỗ; provider từ chối (4xx) thì ghi $0.
- [x] Eval từ chối lưu kết quả khi code chưa commit, trừ khi chạy với `--allow-dirty`. Kết quả ghi định danh kho: sha256 của manifest và số chunk của từng văn bản trong index.
- [x] LLM-judge (`backend/app/evaluation/judge.py`, prompt `eval/judges/judge-v1.md`):
  - Judge tách câu trả lời thành các ý. Faithfulness và citation precision/recall được tính trong code từ nhãn của từng ý; correctness và relevancy là nhãn 3 mức.
  - Từ chối đếm trực tiếp, không qua judge.
  - Judge theo hồ sơ `[judges.<tên>]`, chạy với mọi endpoint tương thích OpenAI (Responses API hoặc Chat Completions). Giới hạn rpm/tpm/rpd/tpd; retry 429 theo Retry-After hoặc `retryDelay`; hết quota ngày thì dừng gọn. Kết quả ghi provider và model id do API trả về.
  - Timeout/5xx/mất kết nối chỉ retry 1 lần; 2 lỗi liên tiếp thì coi provider đang hỏng và dừng chấm (08/10, sau khi Gemini 3.8 quá tải treo tới timeout). Timeout của hồ sơ miễn phí: 120 s.
  - `judge-v2` (08/10): câu "tài liệu không nói về Y" trong câu trả lời từ chối không phải claim. Với v1, Groq tính câu này là claim không được ủng hộ, nên faithfulness của câu từ chối có giải thích bị kéo xuống (g061: 0.667 → 1.0 với v2; g081 không đổi).
  - Ví dụ trong prompt judge dùng luật hư cấu. `judge-v1` lấy ví dụ từ g034 (rò rỉ golden set), nên số chấm bằng v1 chỉ dùng để thử quy trình. Test `test_judge_prompts.py` chặn prompt judge chứa câu hỏi, đoạn trích hay đáp án của mọi golden set (docs/experiments.md mục 8).
  - Kết quả judge ghi riêng thời gian gọi API (`latency_ms`) và thời gian chờ giới hạn rpm/tpm (`wait_ms`); giới hạn tpm ước tính token ra bằng `output_tokens_estimate` (1000), không bằng `max_output_tokens`.
- [x] Trích dẫn sai định dạng (`[1, khoản 2 Điều 9]`, Luna ở g021) vẫn được map sang [1] và ghi vào `malformed_citations`.
  - Judge chính: Gemini `gemini-3.8-flash` free tier (100 request/ngày); judge thứ hai: Groq `openai/gpt-oss-120b`. Sol bị cấm vì ngân sách (Boss chốt 07/10).
- [x] `eval/run_e2e_eval.py`:
  - Ghi latency từng bước cho mọi câu, TTFT tách lượt đầu và lượt hỏi tiếp.
  - Ghi context đã đánh số kèm đủ text, để chấm lại bằng judge khác mà không chạy lại retrieval hay sinh câu trả lời.
  - Từ chối sai được tách theo context có chứa nguồn gold hay không.
  - In chi phí dự kiến và quota còn lại trước khi chạy; dự kiến vượt $0.30 thì từ chối nếu không có `--max-cost`.
  - Hết quota judge thì vẫn sinh câu trả lời; `--rejudge-missing FILE` chấm nốt vào hôm sau.
- [ ] 2 lời gọi thử Gemini và Groq (kiểm tra base_url, json_schema; tính vào quota). Chờ Boss duyệt commit ngân sách.
- [ ] e2e 5 câu (trả lời bằng Luna, judge Gemini), rồi đủ 100 câu v1. Sol trả lời 100 câu để so với Luna: duyệt riêng sau.
- [x] `eval/calibrate_judge.py`: `export` xuất ≥ 50 mẫu (`eval/judges/calibration_samples.jsonl`, không có điểm judge; điểm judge ở `calibration_judge_scores_<hồ sơ>.jsonl`), `judge --judge <hồ sơ>` cho judge khác chấm cùng bộ mẫu (chấm tiếp được qua nhiều ngày), `agreement --judge <hồ sơ>` tính mức đồng thuận theo từng metric.
- [ ] Hiệu chỉnh judge với 50 mẫu, cần đồng thuận ≥ 80%. Long quyết định 07/10: một agent độc lập với P5 chấm, không xem điểm judge. Gemini và Groq cùng chấm 50 mẫu để so.

**Hoàn thành khi:** có số đo cho 5 chỉ số chất lượng mục tiêu và chi phí mỗi câu.

## P6. Backend API (tuần 7)
- [ ] Models Postgres + Alembic: users, documents, document_files, jobs, conversations, messages, feedback
- [ ] Auth JWT: đăng ký, đăng nhập
- [ ] Upload tài liệu:
  - Lưu file, tạo job arq (parse → chunk → index), theo dõi trạng thái.
  - Xoá tài liệu thì xoá cả vector.
- [ ] Chat qua SSE: viết lại câu hỏi → truy xuất → sinh câu trả lời, trả kèm trích dẫn
- [ ] Lịch sử hội thoại, feedback 👍/👎
- [ ] Trace Langfuse từng bước, kèm `config_version`
- [ ] Rate limit; test API; test cách ly dữ liệu giữa 2 user

**Hoàn thành khi:** luồng upload → hỏi đáp chạy được qua API, test pass.

## P7. Frontend (tuần 8)
- [ ] Đăng nhập, đăng ký
- [ ] Quản lý tài liệu: upload, trạng thái job, xoá
- [ ] Chat streaming, hiển thị trích dẫn
- [ ] Bấm trích dẫn thì mở PDF đúng trang bằng `react-pdf`, highlight đoạn trích
- [ ] Feedback 👍/👎, lịch sử hội thoại

**Hoàn thành khi:** demo được end-to-end trên trình duyệt với bộ luật.

## P8. Đo hệ thống và tối ưu (tuần 9)
- [ ] Load test bằng Locust với 20 user đồng thời
- [ ] Bảng latency p50/p95 cho từng bước, chi phí mỗi câu
- [ ] Sửa điểm nghẽn để đạt TTFT p95 ≤ 3 s và retrieval p95 ≤ 800 ms
- [ ] Đo ingestion: PDF 100 trang chuyển sang `ready` trong ≤ 60 s
- [ ] Chạy lại toàn bộ eval với config cuối

**Hoàn thành khi:** mọi chỉ số trong `CLAUDE.md` đều có số đo.

## P9. Hoàn thiện portfolio (tuần 10)
- [ ] README: sơ đồ kiến trúc, bảng kết quả eval và thí nghiệm, hướng dẫn chạy
- [ ] `docs/experiments.md`: cái gì giúp, cái gì không giúp, vì sao
- [ ] Video demo 2–3 phút
- [ ] Golden set v2 (200 câu) nếu còn thời gian
- [ ] **[L]** Quyết định có deploy demo công khai (VPS khoảng $5–10/tháng) hay chỉ dùng video

**Hoàn thành khi:** người ngoài đọc README là hiểu, chạy lại được, và thấy được số liệu.

## Sau dự án (tuỳ chọn)
OCR cho PDF scan, hỗ trợ `.doc`, reranker chạy trên máy, deploy công khai.

## Rủi ro
| Rủi ro | Cách xử lý |
|---|---|
| RAM máy thiếu khi chạy đồng thời Docker, backend, trình duyệt | `mem_limit` trong compose, giới hạn RAM WSL, chỉ bật service đang cần |
| Chi phí API vượt dự kiến | Trần chi phí theo ngày; mỗi lần chạy eval e2e ước tính $2–3; chạy eval retrieval trước vì không tốn LLM |
| Golden set kém chất lượng làm số liệu sai lệch | Long duyệt từng câu; script kiểm tra quote có thật trong PDF |
| OpenAI đổi tên model hoặc giá | Tên model nằm trong `config/rag.toml`; tra lại trang giá trước khi đổi |
| Trễ tiến độ | Cắt P4 xuống còn hybrid + 1 thí nghiệm embedding; P7 làm giao diện tối giản |
