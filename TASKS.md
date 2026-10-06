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
  - Không câu nào hỏi vào Điều đã bị sửa đổi.
- [x] Công cụ duyệt `eval/review_golden.py`: `export` tạo `golden_v1_review.md`, `apply` áp kết quả duyệt vào JSONL
- [x] **[L]** Duyệt `eval/datasets/golden_v1_review.md` (khoảng 3–4 giờ): tick câu đúng, ghi chú câu cần sửa, rồi chạy `python eval/review_golden.py apply`
  - 06/10: Claude duyệt theo yêu cầu của Long, đối chiếu từng đáp án với toàn văn Điều trong PDF. Kết quả 97/100 đạt, 3 câu có ghi chú (g014, g054, g078).
  - g014 hỏi vào Điều 207 Luật Doanh nghiệp, Điều này đã bị luật 76/2025 sửa. Vì vậy dòng "Không câu nào hỏi vào Điều đã bị sửa đổi" ở trên là sai.
- [ ] Sửa các câu có ghi chú, lặp lại cho tới khi 100/100 câu được duyệt
- [ ] Bổ sung `amended_articles` của Luật Doanh nghiệp trong `data/manifest.json`. Luật 76/2025 còn sửa thêm Điều 8, 11, 13, 20, 22, 33, 52, 112, 140, 207, 215 nhưng manifest chưa ghi. Kiểm tra lại danh sách của Bộ luật Lao động với 18/VBHN-VPQH.

**Hoàn thành khi:** có `eval/datasets/golden_v1.jsonl` gồm 100 câu đã duyệt, script kiểm tra pass.

## P2. Ingestion (tuần 2–3)
- [ ] Parser PDF bằng `pymupdf4llm`:
  - Giữ số trang.
  - Bỏ header `CÔNG BÁO/Số .../Ngày ...`.
  - Đánh dấu trang `needs_ocr`.
- [ ] Parser DOCX, HTML, MD/TXT; từ chối `.doc` kèm thông báo đổi sang `.docx`
- [ ] Làm sạch văn bản: dùng `clean_vietnamese_text` (`backend/app/ingestion/text_cleaning.py`), sửa ký tự lỗi `�` trong bản dịch
- [ ] Tách chữ ghép bằng NFKC (`ﬁ` thành `fi`) và nối từ bị gạch nối cuối dòng (`par-` + `ticular`) trong PDF GDPR. Nếu thiếu bước này, BM25 sẽ trượt các từ như "specific" và "official".
- [ ] Chunker cho văn bản luật:
  - Tiếng Việt theo Phần/Chương/Mục/Điều/Khoản/Điểm; tiếng Anh theo Chapter/Section/Article/Clause.
  - Điều dài thì tách theo Khoản.
  - Mỗi chunk có `heading_path`.
  - Gộp 2 file Luật Doanh nghiệp thành 1 `doc_id`.
- [ ] Chunker chung (theo heading và độ dài) cho tài liệu người dùng upload không phải văn bản luật
- [ ] Lệnh `scripts/ingest.py` xuất chunk ra `data/processed/*.jsonl` để soi tay
- [ ] Test trên dữ liệu thật:
  - Số Điều nhận được là 220 / 218 / 39 / 3 cho 4 luật tiếng Việt, 99 Article cho GDPR.
  - Không chunk nào vượt `max_tokens`.

**Hoàn thành khi:** nhận đúng 100% số Điều/Article trên toàn bộ dữ liệu, test pass.

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
