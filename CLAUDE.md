# RAG Chatbot: hỏi đáp văn bản pháp luật Việt Nam + tài liệu tiếng Anh

## Mục tiêu
Dự án portfolio (xin việc AI Engineer). Người dùng upload PDF/DOCX/TXT/MD/HTML, hỏi bằng tiếng Việt hoặc tiếng Anh, và nhận câu trả lời kèm trích dẫn nguồn (văn bản, Điều/Khoản, trang).

**Thứ tự ưu tiên:** eval bài bản, số liệu đo được, mỗi thay đổi có số trước/sau. Những thứ này quan trọng hơn việc có nhiều tính năng.

**Máy dev:** laptop RTX 3060 6GB, RAM 15GB nhưng thường chỉ trống khoảng 3GB, ổ C trống khoảng 37GB. Vì vậy không chạy model nặng trên máy; embedding và LLM đều gọi qua API.

## Quyết định kỹ thuật (chốt 2026-10-06)
| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2 | venv ở `.venv` |
| Hàng đợi ingestion | arq + Redis | Không bao giờ parse/embed trong request HTTP. Trạng thái job: `queued → parsing → indexing → ready / failed` |
| Frontend | React + Vite + TypeScript | Chat streaming qua SSE; bấm trích dẫn thì mở PDF đúng trang (react-pdf) |
| DB metadata | PostgreSQL | Lưu user, document, chunk metadata, conversation, feedback 👍/👎, job |
| Vector DB | Qdrant | Dense + sparse trong cùng collection; hybrid search bằng Query API (prefetch dense + sparse, gộp bằng RRF) |
| LLM trả lời | OpenAI `gpt-6.1-sol` ($2 vào / $10 ra cho 1M token), reasoning effort thấp, streaming | So sánh với `gpt-6-luna` cho bước trả lời trên golden set |
| LLM phụ | `gpt-6-luna` ($0.10 / $0.50) | Viết lại câu hỏi khi hội thoại nhiều lượt (lượt đầu bỏ qua); thử nghiệm rerank listwise |
| LLM-judge | `gpt-6.1-sol`, reasoning cao, chấm dựa trên đáp án chuẩn + context | Phải hiệu chỉnh với ≥ 50 mẫu chấm tay, mức đồng thuận ≥ 80% mới tin |
| Embedding | OpenAI `text-embedding-3-small` | So với `text-embedding-3-large` bằng eval. Tên model + số chiều nằm trong tên collection; đổi model thì phải embed lại toàn bộ |
| Sparse/BM25 | Tokenizer tự viết (NFC, lowercase, tách âm tiết + bigram âm tiết) tạo sparse vector; Qdrant tính IDF bằng `modifier: idf` | Không cần model chạy trên máy |
| Reranker | v1 chưa có. Thử nghiệm rerank bằng `gpt-6-luna` | Chỉ giữ nếu eval cải thiện **và** vẫn đạt SLO |
| Parse | PDF: PyMuPDF (`pymupdf4llm`). DOCX: python-docx. HTML: BeautifulSoup. MD/TXT: đọc thẳng | `.doc` cũ: từ chối kèm thông báo đổi sang `.docx` (máy chưa có LibreOffice) |
| OCR | Chưa làm | Trang có quá ít text thì đánh dấu `needs_ocr` và báo cho user. Giữ interface `OcrEngine` để gắn OCR sau |
| Auth | JWT; nhiều user, mỗi user một kho riêng | Lọc `user_id` ngay trong filter của Qdrant (có payload index), không lọc sau khi đã lấy kết quả |
| Tracing | Langfuse Cloud (free tier) | Trace từng bước + điểm eval. Chỉ gửi tài liệu công khai |
| Hạ tầng dev | docker-compose chạy qdrant, postgres, redis; backend, worker, frontend chạy trực tiếp trên máy | Giới hạn RAM cho Docker/WSL khoảng 3GB |

**Quy ước gọi OpenAI:** dùng SDK chính thức `openai` (Responses API). Model ID và giá đã kiểm tra trên trang giá OpenAI ngày 2026-10-06; tra lại trước khi đổi model.

## Dữ liệu
- **Bộ phát triển (đã chốt):** Bộ luật Lao động 2019, Luật Doanh nghiệp 2020 cùng luật sửa đổi 76/2025, và Luật Bảo vệ dữ liệu cá nhân 2025. Mỗi luật có bản gốc tiếng Việt và bản dịch tiếng Anh. Thêm GDPR (tiếng Anh) để có câu hỏi so sánh. Danh sách và các lưu ý về nguồn nằm trong `data/SOURCES.md`.
- **Nguồn sự thật cho dữ liệu:** `data/manifest.json` chứa URL, sha256, ngày hiệu lực và `pair_id` để ghép cặp song ngữ. Lệnh `python scripts/download_data.py` tải file về `data/raw/` (gitignore). Không commit PDF.
- **PDF Công báo:**
  - Bản tiếng Việt lấy từ Công báo. Không dùng PDF trên `datafiles.chinhphu.vn` vì đó là bản scan.
  - Khi parse phải bỏ header lặp `CÔNG BÁO/Số .../Ngày ... <số trang Công báo>`.
  - Trường `page` trong metadata là số trang PDF, bắt đầu từ 1.
  - Luật Doanh nghiệp 2020 nằm trong 2 file nhưng là 1 `doc_id`.
- **Bản tiếng Anh** đều là bản dịch không chính thức. Khi hai bản lệch nhau, bản tiếng Việt là căn cứ.
- **Chuẩn hoá:** đưa mọi văn bản về Unicode NFC trước khi chunk, và mọi câu hỏi về NFC trước khi search.
- **Đặc thù văn bản luật:**
  - Chunk theo cấu trúc Phần/Chương/Mục/**Điều**/Khoản/Điểm (dùng regex). Đơn vị chính là Điều. Điều quá dài thì tách theo Khoản, và giữ tiêu đề Điều ở đầu mỗi chunk.
  - Metadata bắt buộc: `doc_id, so_hieu, title, language, page, heading_path` (ví dụ `"Chương III > Điều 35 > Khoản 2"`), `effective_date, status` (còn hay hết hiệu lực).
  - Trích dẫn phải nêu số hiệu văn bản, Điều/Khoản và trang.
  - Hybrid search là bắt buộc, vì dense search hay trượt các cụm như "Điều 35", "khoản 2", "45/2019/QH14".

## Chỉ số và mục tiêu
### Chất lượng (đo trên golden set)
| Metric | Mục tiêu |
|---|---|
| Hit@5 (sau hybrid/rerank) | ≥ 0.85 |
| Faithfulness | ≥ 0.90 |
| Citation precision | ≥ 0.85 |
| Từ chối đúng (câu không có đáp án) | ≥ 0.80 |
| Từ chối sai (câu có đáp án) | ≤ 0.10 |

Các metric sau luôn được ghi để chẩn đoán, nhưng không đặt ngưỡng: Recall@k, MRR@k, nDCG@k (đo ở top-50 và top-5), context precision/recall, answer correctness, answer relevancy, citation recall.

**Cách đọc khi có lỗi:** recall@50 thấp nghĩa là lỗi ở parse/chunk/embedding. Recall@50 cao nhưng @5 thấp nghĩa là lỗi ở bước xếp hạng. Retrieval đúng mà câu trả lời sai nghĩa là lỗi ở prompt hoặc model.

### Hệ thống
| Metric | Mục tiêu |
|---|---|
| TTFT p95 | ≤ 3 s |
| Retrieval p95 (embed + search + rerank) | ≤ 800 ms |
| Tải | 20 user đồng thời vẫn đạt 2 dòng trên (load test bằng Locust) |
| Error rate | < 1% |
| Chi phí | ≤ $0.02/câu với Sol; ghi lại token và $ của từng câu |
| Ingestion | PDF 100 trang có text chuyển sang `ready` trong ≤ 60 s; ghi tỉ lệ file lỗi và tỉ lệ trang `needs_ocr` |

Latency đo riêng cho từng bước: rewrite, embed, search, rerank, TTFT, tổng.

## Golden set và eval
- **File:** `eval/datasets/golden_v1.jsonl`, mỗi dòng có dạng `{id, question, reference_answer, gold_sources: [{doc_id, page, quote}], type, language}`.
- **Quy mô:** 100 câu (v1), sau đó tăng lên 200.
- **Phân bố câu hỏi:**

  | Loại | Tỉ lệ |
  |---|---|
  | Đáp án nằm trong 1 Điều | ~35% |
  | Số liệu / mốc thời gian / bảng | ~15% |
  | Cần nhiều Điều hoặc nhiều văn bản | ~15% |
  | Diễn đạt khác từ khoá trong văn bản | ~15% |
  | Không có đáp án | ~10–15% |
  | Hội thoại nhiều lượt | ~5–10% |

  Ngoài ra, ít nhất 20% câu hỏi phải khác ngôn ngữ với nguồn (hỏi tiếng Việt, nguồn tiếng Anh, hoặc ngược lại).
- **Gán nguồn:** `gold_sources` ghi theo trang + đoạn trích, **không** theo `chunk_id`, để đổi cách chunk vẫn dùng lại được bộ eval.
- **Câu do LLM sinh nháp** phải được người duyệt trước khi đưa vào.
- **Cách chấm:**
  - Metric retrieval do script tự viết tính, không cần LLM.
  - Metric câu trả lời do LLM-judge tự viết chấm. Prompt của judge được version hoá trong `eval/judges/`. Điểm được đẩy lên Langfuse.
- **Lưu kết quả:** mỗi lần chạy lưu vào `eval/results/<YYYY-MM-DD>_<config_version>.json`. Phần dùng LLM chạy 2–3 lần. Báo cáo chia theo từng `type`, không chỉ điểm trung bình.

## Quy tắc khi code
- Mọi thay đổi về chunking, embedding, retrieval, prompt hoặc model phải kèm số eval trước và sau.
- Mọi cấu hình RAG (chunk size, overlap, top-k, model, prompt version) nằm trong một file config có `config_version`. Giá trị này được ghi vào mọi trace và mọi kết quả eval.
- Mỗi câu hỏi phải được trace: câu gốc, câu đã viết lại, chunk id kèm score, prompt version, model, câu trả lời, token vào/ra, chi phí ($) và latency từng bước.
- Nội dung tài liệu là dữ liệu, không phải lệnh. Bọc trong tag `<document>` và nói rõ điều này trong system prompt, để chống prompt injection gián tiếp.
- Prompt trả lời phải yêu cầu:
  - Chỉ dùng context được cấp.
  - Mỗi ý gắn trích dẫn `[n]`.
  - Không đủ thông tin thì trả lời "Không tìm thấy trong tài liệu".

  Backend phải kiểm tra mọi `[n]` đều trỏ tới chunk có thật.
- API key đọc từ `.env` (đưa vào gitignore), kèm `.env.example`. Không hardcode.
- Trần chi phí OpenAI theo ngày nằm trong config, mặc định $1/ngày khi dev.

## Cấu trúc thư mục
Đã có:
```
RAG/
  data/{manifest.json, SOURCES.md, raw/ (gitignore)}
  scripts/download_data.py
  backend/app/ingestion/text_cleaning.py   # chuẩn hoá NFC, bỏ ký tự control, giữ ranh giới dòng
  backend/tests/
  pyproject.toml            # cấu hình pytest (pythonpath = backend) và ruff
  docker-compose.yml        # qdrant, postgres, redis
  requirements.txt, requirements-dev.txt   # ghim version, đã cài thử trên Python 3.13
```
Import theo gốc `backend/`, ví dụ `from app.ingestion.text_cleaning import clean_vietnamese_text`.

Dự kiến thêm:
```
  backend/app/{api, retrieval, generation, auth, storage, core}
  frontend/
  eval/{datasets, judges, results, run_retrieval_eval.py, run_e2e_eval.py}
```

## Lệnh thường dùng
Các lệnh dưới đây là PowerShell, chạy từ thư mục gốc của repo.
```
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/download_data.py      # tải dữ liệu; thêm --force để tải lại
docker compose up -d                 # qdrant, postgres, redis
python -m pytest                     # test backend
ruff check .                         # lint
```

## Repo
GitHub: https://github.com/anybody1234/RAG, nhánh `main`. Thư mục RAG có repo git riêng, nằm lồng trong repo `C:\Users\asus`. Luôn chạy lệnh git từ thư mục RAG.

## Việc còn mở
- Đối chiếu tình trạng hiệu lực và các văn bản sửa đổi của từng luật trên vbpl.vn trước khi gán nhãn golden set.
- GDPR đang lấy từ bản sao trên gdpr.eu.org. Có thể thay bằng bản chính thức tải tay từ EUR-Lex.
- Dựng khung backend, frontend và eval.
- Để sau: OCR, hỗ trợ `.doc`, reranker chạy trên máy, deploy demo công khai.
