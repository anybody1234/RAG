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
- [ ] Gọi embedding OpenAI theo batch, có retry, đếm token và chi phí
- [ ] Tokenizer BM25 cho tiếng Việt và tiếng Anh, tạo sparse vector
- [ ] Collection Qdrant:
  - Dense + sparse với `modifier: idf`.
  - Payload index cho `user_id` và `doc_id`.
  - Upsert idempotent theo hash nội dung chunk.
- [ ] Hybrid query: prefetch dense + sparse, gộp RRF, filter theo `user_id`
- [ ] `eval/run_retrieval_eval.py`:
  - Tính Hit@k, Recall@k, MRR, nDCG ở top-50 và top-5.
  - Báo cáo theo `type` và theo ngôn ngữ.
  - So khớp với gold bằng trang + quote.
- [ ] Lưu baseline đầu tiên vào `eval/results/`, ghi retrieval p95

**Hoàn thành khi:** có số baseline cho cấu hình `v0.1-baseline`.

## P4. Thí nghiệm retrieval (tuần 5)
- [ ] So sánh dense / sparse / hybrid
- [ ] So sánh `text-embedding-3-small` với `text-embedding-3-large`
- [ ] Thử 2–3 cấu hình chunk
- [ ] Rerank bằng `gpt-6-luna`: chỉ giữ nếu cải thiện và vẫn đạt retrieval p95 ≤ 800 ms
- [ ] Chốt config, ghi bảng so sánh và nhận xét vào `docs/experiments.md`

**Hoàn thành khi:** Hit@5 ≥ 0.85, hoặc ghi rõ khoảng cách còn thiếu và nguyên nhân.

## P5. Sinh câu trả lời + eval end-to-end (tuần 5–6)
- [ ] Prompt trả lời (version hoá):
  - Bọc tài liệu trong tag `<document>`.
  - Trích dẫn `[n]`.
  - Trả "Không tìm thấy trong tài liệu" khi thiếu thông tin.
- [ ] Gọi `gpt-6.1-sol` qua Responses API (streaming); kiểm tra mọi `[n]` hợp lệ; map `[n]` sang văn bản, Điều và trang
- [ ] Viết lại câu hỏi multi-turn bằng `gpt-6-luna`
- [ ] Trần chi phí theo ngày (`DAILY_COST_LIMIT_USD`)
- [ ] LLM-judge chấm faithfulness, correctness, relevancy, citation precision/recall; abstention đếm trực tiếp
- [ ] **[L]** Chấm tay 50 mẫu để hiệu chỉnh judge (cần đồng thuận ≥ 80%)
- [ ] `eval/run_e2e_eval.py`; so sánh Sol và Luna cho bước trả lời

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
