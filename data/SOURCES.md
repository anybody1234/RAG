# Nguồn dữ liệu

Bộ dữ liệu phát triển gồm 3 cặp luật Việt Nam (bản gốc tiếng Việt + bản dịch tiếng Anh), 1 luật sửa đổi và GDPR. Chủ đề xoay quanh **lao động, doanh nghiệp và dữ liệu cá nhân**, đủ để đặt câu hỏi trong một văn bản, câu hỏi ghép nhiều văn bản, câu hỏi chéo ngôn ngữ, và câu hỏi so sánh (Luật Bảo vệ dữ liệu cá nhân Việt Nam với GDPR).

Thông tin máy đọc được (URL, sha256, ngày hiệu lực, cặp song ngữ) nằm trong [`manifest.json`](manifest.json). File PDF **không commit** vào repo. Tải về `data/raw/` bằng lệnh:

```
python scripts/download_data.py
```

## Danh sách văn bản (kiểm tra ngày 2026-10-06)

| Văn bản | Số hiệu | Hiệu lực | Tiếng Việt | Tiếng Anh |
|---|---|---|---|---|
| Bộ luật Lao động | 45/2019/QH14 | 01/01/2021 | Công báo số 993+994, 94 trang | Bản dịch không chính thức (asean.org), 87 trang |
| Luật Doanh nghiệp | 59/2020/QH14 (sửa đổi bởi 03/2022/QH15, 76/2025/QH15) | 01/01/2021 | Công báo số 713+714 và 715+716, 2 file, 94 + 74 trang | Bản dịch không chính thức (investdanang.gov.vn), 136 trang |
| Luật sửa đổi, bổ sung một số điều của Luật Doanh nghiệp | 76/2025/QH15 | 01/07/2025 | Công báo số 951+952, 7 trang | Bản dịch của Viet An Law Firm, 8 trang |
| Luật Bảo vệ dữ liệu cá nhân | 91/2025/QH15 | 01/01/2026 | Công báo số 971+972, 25 trang | Bản dịch không chính thức (dpo-india.com), 27 trang |
| General Data Protection Regulation | (EU) 2016/679 | 25/05/2018 | — | Bản sao toàn văn (gdpr.eu.org), 117 trang |

Mọi file đều là PDF có lớp text. Số Điều đếm được khớp với văn bản gốc: Bộ luật Lao động 220 Điều, Luật Doanh nghiệp 218 Điều, Luật Bảo vệ dữ liệu cá nhân 39 Điều.

## Lưu ý về nguồn

- **Không dùng PDF trên `datafiles.chinhphu.vn`.** Các file "signed" ở đó là bản scan (hơn 95% số trang không có text), cần OCR mới đọc được. Bản Công báo (`congbaocdn.chinhphu.vn`) là bản dàn trang điện tử, có text đầy đủ.
- **Đặc điểm của PDF Công báo khi parse:**
  - Mỗi trang có header lặp lại dạng `CÔNG BÁO/Số 713 + 714/Ngày 24-7-2020 3`, trong đó số cuối là số trang Công báo, không phải số trang PDF. Cần bỏ header này khi parse.
  - Trích dẫn dùng số trang PDF (bắt đầu từ 1).
  - Luật Doanh nghiệp 2020 bị chia làm 2 file. Cuối phần 1 có dòng `(Xem tiếp Công báo số 715 + 716)`, và phần 2 bắt đầu ở Chương V.
- **Bản tiếng Anh đều là bản dịch không chính thức.** Khi hai bản lệch nhau, bản tiếng Việt là căn cứ. Bản dịch Luật Bảo vệ dữ liệu cá nhân được ghi nhận có ký tự lỗi mã hoá (`�` thay cho dấu gạch ngang), nhưng text do PyMuPDF trích ra không có `�` nào (kiểm tra 06/10, dấu gạch ngang ra đúng `–`). Bước làm sạch vẫn có `fix_replacement_chars` cho file khác.
- **GDPR:** bản chính thức nằm ở [EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng), nhưng trang này chặn tải tự động. Nếu muốn dùng bản chính thức, tải tay bằng trình duyệt, lưu đè `data/raw/en-gdpr-2016.pdf`, rồi cập nhật sha256 trong manifest.
- **Tình trạng hiệu lực** (đối chiếu ngày 06/10/2026 qua văn bản hợp nhất trên Công báo):
  - **Bộ luật Lao động** đã bị sửa đổi, bổ sung bởi 3 luật:
    - Luật Công nghiệp công nghệ số 71/2025/QH15: bổ sung khoản 8a Điều 154, hiệu lực 01/01/2026.
    - Luật Giáo dục nghề nghiệp 124/2025/QH15: sửa khoản 2 Điều 60 và Điều 62, hiệu lực 01/01/2026.
    - Luật Dân số 113/2025/QH15: sửa khoản 1 Điều 139 về nghỉ thai sản, hiệu lực 01/07/2026.

    Văn bản hợp nhất mới nhất: [18/VBHN-VPQH](https://congbao.chinhphu.vn/van-ban/van-ban-hop-nhat-so-18-vbhn-vpqh-468971.htm) ngày 12/02/2026.
  - **Luật Doanh nghiệp** đã bị sửa đổi ở 33 Điều. Văn bản hợp nhất: [67/VBHN-VPQH](https://congbao.chinhphu.vn/van-ban/van-ban-hop-nhat-so-67-vbhn-vpqh-45865.htm) ngày 15/08/2025.
    - Luật 76/2025/QH15 sửa 27 Điều. Lập từ toàn văn luật, có trong bộ dữ liệu.
    - [Luật 03/2022/QH15](https://congbao.chinhphu.vn/van-ban/nghi-quyet-so-03-2022-qh15-36795.htm), Điều 7, sửa Điều 49, 50, 60, 109, 148, 158, 217.
  - **Luật Bảo vệ dữ liệu cá nhân 2025:** chưa có văn bản sửa đổi. Văn bản hướng dẫn là Nghị định 356/2025/NĐ-CP, không có trong bộ dữ liệu.
  - **GDPR:** chưa có sửa đổi có hiệu lực. Gói Digital Omnibus về dữ liệu vẫn đang đàm phán.

  Bộ dữ liệu dùng bản gốc, nên các Điều đã bị sửa (danh sách ở `amended_articles` trong manifest) được loại khỏi golden set.
- **Bản quyền:** văn bản quy phạm pháp luật Việt Nam không thuộc đối tượng bảo hộ quyền tác giả, nhưng bản dịch của bên thứ ba thì có thể có. Vì vậy repo chỉ lưu link và script tải, không lưu file.
