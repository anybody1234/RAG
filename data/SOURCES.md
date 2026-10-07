# Nguồn dữ liệu

Bộ dữ liệu phát triển gồm 3 cặp luật Việt Nam (bản gốc tiếng Việt + bản dịch tiếng Anh), 1 luật sửa đổi, Nghị định 356/2025/NĐ-CP hướng dẫn Luật Bảo vệ dữ liệu cá nhân (chỉ có tiếng Việt) và GDPR (chỉ có tiếng Anh). Chủ đề xoay quanh **lao động, doanh nghiệp và dữ liệu cá nhân**, đủ để đặt câu hỏi trong một văn bản, câu hỏi ghép nhiều văn bản, câu hỏi chéo ngôn ngữ, và câu hỏi so sánh (Luật Bảo vệ dữ liệu cá nhân Việt Nam với GDPR).

Hai văn bản chỉ có một ngôn ngữ cho phép đo câu khác ngôn ngữ theo cả hai chiều: câu tiếng Việt hỏi về GDPR, và câu tiếng Anh hỏi về Nghị định 356.

Thông tin máy đọc được (URL, sha256, ngày hiệu lực, cặp song ngữ) nằm trong [`manifest.json`](manifest.json). File PDF **không commit** vào repo. Tải về `data/raw/` bằng lệnh:

```
python scripts/download_data.py
```

## Danh sách văn bản (kiểm tra ngày 2026-10-06; Nghị định 356/2025 ngày 2026-10-07)

| Văn bản | Số hiệu | Hiệu lực | Tiếng Việt | Tiếng Anh |
|---|---|---|---|---|
| Bộ luật Lao động | 45/2019/QH14 | 01/01/2021 | Công báo số 993+994, 94 trang | Bản dịch không chính thức (asean.org), 87 trang |
| Luật Doanh nghiệp | 59/2020/QH14 (sửa đổi bởi 03/2022/QH15, 76/2025/QH15) | 01/01/2021 | Công báo số 713+714 và 715+716, 2 file, 94 + 74 trang | Bản dịch không chính thức (investdanang.gov.vn), 136 trang |
| Luật sửa đổi, bổ sung một số điều của Luật Doanh nghiệp | 76/2025/QH15 | 01/07/2025 | Công báo số 951+952, 7 trang | Bản dịch của Viet An Law Firm, 8 trang |
| Luật Bảo vệ dữ liệu cá nhân | 91/2025/QH15 | 01/01/2026 | Công báo số 971+972, 25 trang | Bản dịch không chính thức (dpo-india.com), 27 trang |
| General Data Protection Regulation | (EU) 2016/679 | 25/05/2018 | — | Bản sao toàn văn (gdpr.eu.org), 117 trang |
| Nghị định quy định chi tiết một số điều và biện pháp thi hành Luật Bảo vệ dữ liệu cá nhân (thêm ngày 07/10/2026) | 356/2025/NĐ-CP | 01/01/2026 | Công báo số 18 ngày 18/01/2026, 70 trang | — |

Mọi file đều là PDF có lớp text. Số Điều đếm được khớp với văn bản gốc: Bộ luật Lao động 220 Điều, Luật Doanh nghiệp 218 Điều, Luật Bảo vệ dữ liệu cá nhân 39 Điều, Nghị định 356/2025 42 Điều (trang 1–37) và một Phụ lục gồm 13 mẫu biểu (trang 38–70).

**Vì sao chọn Nghị định 356/2025, không chọn Nghị định 145/2020/NĐ-CP (hướng dẫn Bộ luật Lao động):** cần một văn bản chỉ có tiếng Việt để có câu hỏi tiếng Anh mà nguồn chỉ có tiếng Việt. Nghị định 145/2020 đã bị nhiều văn bản cắt sửa, nên lập danh sách Điều bị sửa rủi ro cao:
- Nghị định 129/2025 bãi bỏ Điều 71–79;
- Nghị định 35/2022 bãi bỏ khoản 1, 2 Điều 73;
- Nghị quyết 66.18/2026/NQ-CP (và 66.16/2026/NQ-CP mà nó dẫn chiếu) cắt và sửa thủ tục cho thuê lại lao động ở các Điều 21–27 cùng nhiều điểm khác, chưa lập đủ phạm vi.

Nghị định 356/2025 mới có hiệu lực từ 01/01/2026, chỉ bị một văn bản tác động (5 Điều, xem phần tình trạng hiệu lực), và bổ sung trực tiếp cho Luật Bảo vệ dữ liệu cá nhân, nên có câu hỏi ghép Luật với Nghị định.

## Lưu ý về nguồn

- **Không dùng PDF trên `datafiles.chinhphu.vn`.** Các file "signed" ở đó là bản scan (hơn 95% số trang không có text), cần OCR mới đọc được. Bản Công báo (`congbaocdn.chinhphu.vn`) là bản dàn trang điện tử, có text đầy đủ.
- **Đặc điểm của PDF Công báo khi parse:**
  - Mỗi trang có header lặp lại dạng `CÔNG BÁO/Số 713 + 714/Ngày 24-7-2020 3`, trong đó số cuối là số trang Công báo, không phải số trang PDF. Cần bỏ header này khi parse.
  - Trích dẫn dùng số trang PDF (bắt đầu từ 1).
  - Luật Doanh nghiệp 2020 bị chia làm 2 file. Cuối phần 1 có dòng `(Xem tiếp Công báo số 715 + 716)`, và phần 2 bắt đầu ở Chương V.
  - Công báo năm 2026 (Nghị định 356/2025) có header `CÔNG BÁO/Số 18/Ngày 18-01-2026`, số trang Công báo nằm ở dòng riêng. Khối chữ ký số ghi `Ngày ký:` thay cho `Thời gian ký:`.
  - Nghị định 356/2025 có Phụ lục mẫu biểu sau Điều 42. Một số mẫu (mẫu 05, 07) chứa "Điều 1.", "Điều 2." của quyết định mẫu. Parser tách Phụ lục thành mục riêng (`heading_path` "Phụ lục > Mẫu số 01a", `article` rỗng), không gộp vào Điều 42.
  - Link tải Nghị định 356/2025 trong manifest là link "Tải về" dạng `g7.cdnchinhphu.vn/api/download/stream?Url=...` trên trang Công báo. Link xem trực tuyến `congbaocdn.chinhphu.vn/.../356signed-...pdf` cho đúng cùng file (sha256 trùng), dùng thay được nếu link stream đổi token.
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
  - **Luật Bảo vệ dữ liệu cá nhân 2025:** chưa có văn bản sửa đổi. Văn bản hướng dẫn là Nghị định 356/2025/NĐ-CP, có trong bộ dữ liệu từ 07/10/2026.
  - **Nghị định 356/2025/NĐ-CP** (kiểm tra ngày 07/10/2026): bị tác động bởi [Nghị quyết 22/2026/NQ-CP](https://congbao.chinhphu.vn/van-ban/nghi-quyet-so-22-2026-nq-cp-469469.htm) ngày 29/04/2026 (Công báo số 275 ngày 15/05/2026) ở **Điều 18, 19, 20, 25, 26**.
    - Nghị quyết cắt giảm, phân cấp thủ tục hành chính của Bộ Công an. Nó có hiệu lực từ 29/04/2026 đến hết 01/03/2027. Khoản 2 Điều 6 quy định: trong thời gian đó, nếu quy định về thủ tục trong Nghị quyết khác văn bản liên quan thì thực hiện theo Nghị quyết.
    - Phụ lục I.7, mục A.III: gộp "cấp lại" và "cấp đổi" Giấy chứng nhận đủ điều kiện kinh doanh dịch vụ xử lý dữ liệu cá nhân thành một thủ tục; hồ sơ chỉ còn đơn đề nghị, thời hạn 05 ngày làm việc (Điều 26).
    - Mục A.IV: thành phần hồ sơ cấp Giấy chứng nhận (Điều 25).
    - Mục B.I, B.II, B.III: hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên giới (Điều 18), đánh giá tác động xử lý dữ liệu (Điều 19) và cập nhật hồ sơ (Điều 20). Bộ Công an tiếp nhận rồi chuyển Công an tỉnh xử lý; hồ sơ chưa đạt bổ sung trong 30 ngày, trả kết quả trong 15 ngày.
    - Phụ lục II, dòng 8: giao Bộ Công an trình sửa Điều 18, Điều 19 của Nghị định.
    - Phạm vi dò: mọi Nghị quyết của Chính phủ năm 2026 trên Công báo (số 01–42 và 66.11–66.26) được tải toàn văn và tìm chuỗi "356/2025". Với 352 Nghị định năm 2026 (đến số 369), tôi lọc theo tiêu đề rồi đọc toàn văn 14 Nghị định về dữ liệu, an ninh mạng và bãi bỏ văn bản. Chỉ Nghị quyết 22/2026 tác động tới Nghị định 356. Nghị định 330/2026 (xử phạt trong lĩnh vực an ninh mạng và bảo vệ dữ liệu cá nhân) chỉ dẫn chiếu Nghị định 356, không sửa văn bản này.
    - Chú ý trùng số: Nghị định **356/2026**/NĐ-CP ngày 14/09/2026 là văn bản khác, bãi bỏ 18 nghị định cũ và không liên quan.
  - **GDPR:** chưa có sửa đổi có hiệu lực. Gói Digital Omnibus về dữ liệu vẫn đang đàm phán.

  Bộ dữ liệu dùng bản gốc, nên các Điều đã bị sửa (danh sách ở `amended_articles` trong manifest) được loại khỏi golden set.
- **Bản quyền:** văn bản quy phạm pháp luật Việt Nam không thuộc đối tượng bảo hộ quyền tác giả, nhưng bản dịch của bên thứ ba thì có thể có. Vì vậy repo chỉ lưu link và script tải, không lưu file.
