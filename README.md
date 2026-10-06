# RAG Chatbot: hỏi đáp văn bản pháp luật (Việt + Anh)

Chatbot RAG cho phép tải lên tài liệu (PDF, DOCX, TXT, Markdown, HTML), đặt câu hỏi bằng tiếng Việt hoặc tiếng Anh, và nhận câu trả lời **có trích dẫn nguồn**: văn bản, Điều/Khoản, số trang. Dữ liệu phát triển là luật Việt Nam về lao động, doanh nghiệp, dữ liệu cá nhân (bản gốc + bản dịch tiếng Anh) và GDPR.

Trọng tâm của dự án là **đo lường được**. Mọi thay đổi về cách chunk, truy xuất, prompt hay model đều phải có số liệu eval trước và sau trên một bộ câu hỏi chuẩn.

> **Trạng thái:** đang khởi tạo. Đã chốt thiết kế, môi trường và bộ dữ liệu. Code mới có bước làm sạch văn bản; chưa có API và giao diện.

## Kiến trúc

```
Upload ─► hàng đợi (arq + Redis) ─► parse ─► chuẩn hoá NFC ─► chunk theo Điều/Khoản
       ─► embedding (OpenAI) + BM25 sparse ─► Qdrant
Hỏi    ─► viết lại câu hỏi (multi-turn) ─► hybrid search (dense + sparse, RRF)
       ─► LLM (OpenAI, streaming) ─► câu trả lời + trích dẫn [n]
```

| Thành phần | Công nghệ |
|---|---|
| Backend | Python 3.13, FastAPI |
| Frontend | React + Vite + TypeScript |
| Vector DB | Qdrant (dense + sparse) |
| Metadata | PostgreSQL |
| LLM | `gpt-6.1-sol` (trả lời), `gpt-6-luna` (viết lại câu hỏi, so sánh) |
| Embedding | `text-embedding-3-small`, so sánh với `-large` bằng eval |
| Tracing | Langfuse Cloud |

## Chỉ số mục tiêu

| Chất lượng (trên golden set) | Mục tiêu | Hệ thống | Mục tiêu |
|---|---|---|---|
| Hit@5 | ≥ 0.85 | TTFT p95 | ≤ 3 s |
| Faithfulness | ≥ 0.90 | Retrieval p95 | ≤ 800 ms |
| Citation precision | ≥ 0.85 | Tải đồng thời | 20 user |
| Từ chối đúng khi không có đáp án | ≥ 0.80 | Chi phí | ≤ $0.02/câu |

## Cài đặt

Yêu cầu: Python 3.13, Docker, Node.js (cho frontend).

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

copy .env.example .env               # rồi điền OPENAI_API_KEY, LANGFUSE_*, JWT_SECRET
python scripts/download_data.py      # tải bộ văn bản luật về data/raw/
docker compose up -d                 # qdrant, postgres, redis
python -m pytest                     # chạy test
```

## Dữ liệu

Danh sách văn bản, nguồn tải và các lưu ý khi parse nằm trong [`data/SOURCES.md`](data/SOURCES.md). File PDF không được commit vào repo; script tải và kiểm tra sha256 theo [`data/manifest.json`](data/manifest.json).

## Lộ trình

1. Bộ câu hỏi chuẩn (golden set) v1: 100 câu
2. Ingestion: parse, chuẩn hoá, chunk theo cấu trúc văn bản luật, index
3. Retrieval và eval retrieval (dense, hybrid, rerank)
4. Sinh câu trả lời có trích dẫn, eval end-to-end
5. API, giao diện web (upload, chat streaming, xem nguồn)
6. Tracing, load test, tối ưu theo số liệu eval
