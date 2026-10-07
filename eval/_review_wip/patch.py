"""Apply review decisions to golden_v2_draft.jsonl -> golden_v2.jsonl and print stats.

python patch.py [--write]
"""
import copy
import json
import sys
from collections import Counter

from h import *  # noqa

DRAFT = ROOT / "eval/datasets/golden_v2_draft.jsonl"
OUT = ROOT / "eval/datasets/golden_v2.jsonl"

L91VI = "vi-luat-bao-ve-du-lieu-ca-nhan-2025"
L91EN = "en-personal-data-protection-law-2025"
ND = "vi-nghi-dinh-bao-ve-du-lieu-ca-nhan-2025"
GDPR = "en-gdpr-2016"

DROPS: dict[str, str] = {}
EDITS: dict[str, dict] = {}

# ---------------- dec ----------------
DROPS.update({
    "v2-dec-02": "gần trùng dec-21",
    "v2-dec-10": "mơ hồ",
    "v2-dec-14": "câu thứ ba vào Điều 5",
    "v2-dec-18": "thừa numeric, số 3 trùng điều kiện Điều 22",
    "v2-dec-23": "gần trùng dec-22",
    "v2-dec-28": "paraphrase yếu (trùng từ khoá)",
    "v2-dec-33": "thừa unanswerable, bẫy yếu",
})
EDITS["v2-dec-19"] = {
    "question": "Do small businesses and start-ups in Vietnam have to carry out personal data processing impact "
                "assessments and appoint data protection staff right away? If they can opt out, from when and for "
                "how long, and how many data subjects counts as a 'large number'?",
    "reference_answer": "Not necessarily. Small enterprises and start-ups may choose whether or not to apply Articles "
                        "21, 22 and Article 33(2) of the Personal Data Protection Law (processing impact assessment "
                        "and its updates, and designating data protection departments/personnel or hiring a "
                        "service) for 5 years from the Law's entry into force on 1 January 2026 (Law 91/2025/QH15, "
                        "Article 38(1)-(2)). The option does not apply to those that provide personal data processing "
                        "services, directly process sensitive personal data, or process personal data of a large "
                        "number of data subjects; Decree 356/2025/ND-CP, Article 41(1), sets that threshold as from "
                        "the time the accumulated total of processed personal data reaches 100,000 data subjects "
                        "or more.",
    "gold_sources": [
        {"doc_id": L91EN, "page": 26,
         "quote": "1. This Law comes into force from January 1, 2026. 2. Small enterprises and start-ups have the "
                  "right to choose whether or not to implement the provisions in Article 21, Article 22 and Clause "
                  "2, Article 33 of this Law within 05 years"},
        {"doc_id": ND, "page": 36,
         "quote": "100 nghìn chủ thể dữ liệu cá nhân trở lên dựa trên kết quả tích lũy tổng lượng dữ liệu cá nhân "
                  "đã xử lý"},
    ],
}
EDITS["v2-dec-20"] = {"tags": []}
EDITS["v2-dec-24"] = {
    "reference_answer": "Không. Theo khoản 3 Điều 6 Nghị định 356/2025/NĐ-CP, bên kiểm soát dữ liệu không được thiết "
                        "lập phương thức mặc định đồng ý hoặc tạo chỉ dẫn không rõ ràng, gây hiểu lầm giữa đồng ý và "
                        "không đồng ý; các thiết lập mặc định phải bảo đảm nguyên tắc bảo vệ dữ liệu cá nhân và tôn "
                        "trọng quyền của chủ thể dữ liệu. Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 cũng quy định sự im "
                        "lặng hoặc không phản hồi không được coi là sự đồng ý (điểm d khoản 4 Điều 9).",
    "add_sources": [{"doc_id": L91VI, "page": 7,
                     "quote": "Sự im lặng hoặc không phản hồi không được coi là sự đồng ý"}],
}
EDITS["v2-dec-25"] = {
    "reference_answer": "Có. Chia sẻ dữ liệu cá nhân giữa các bộ phận trong cùng một tổ chức chỉ là trường hợp chuyển "
                        "giao hợp lệ khi để xử lý phù hợp với mục đích xử lý đã xác lập (điểm b khoản 1 Điều 17 Luật "
                        "Bảo vệ dữ liệu cá nhân 91/2025/QH15); dùng cho marketing mà mục đích này chưa được xác lập "
                        "thì không thuộc trường hợp đó. Khi chia sẻ nội bộ, theo khoản 4 Điều 7 Nghị định "
                        "356/2025/NĐ-CP, tổ chức phải xây dựng quy trình kiểm soát việc chia sẻ, sử dụng dữ liệu "
                        "đúng quy định và có biện pháp phòng, chống nhân sự nội bộ chia sẻ trái phép dữ liệu cá nhân "
                        "cho bên thứ ba.",
    "add_sources": [{"doc_id": L91VI, "page": 10,
                     "quote": "Chia sẻ dữ liệu cá nhân giữa các bộ phận trong cùng một cơ quan, tổ chức để xử lý dữ "
                              "liệu cá nhân phù hợp với mục đích xử lý đã xác lập"}],
}

# ---------------- lab ----------------
DROPS.update({
    "v2-lab-08": "thừa single; câu tra cứu đơn giản",
    "v2-lab-14": "trùng ý với lab-01 (đáp án lab-01 đã nêu ngoại lệ người giúp việc gia đình phải ký văn bản)",
    "v2-lab-17": "đáp án là suy luận từ Điều 104, dễ bị chấm là từ chối",
    "v2-lab-24": "trùng một phần v1 g010 (người 14 tuổi làm việc)",
    "v2-lab-28": "cùng khuôn với v1 g082 (tỷ lệ đóng trên quỹ lương)",
    "v2-lab-31": "câu cuối không phụ thuộc lịch sử",
})

# ---------------- ent ----------------
DROPS.update({
    "v2-ent-02": "cụm câu đặt tên (ent-07, ent-27), thừa single",
    "v2-ent-09": "thừa numeric; trùng lịch sử của ent-22",
    "v2-ent-13": "nguồn bản gốc 2020 không cần (luật 76/2025 thay trọn điểm a), không phải multi_hop thật",
    "v2-ent-20": "trùng chủ đề ent-16 (người thừa kế phần vốn góp)",
    "v2-ent-21": "câu cuối không phụ thuộc lịch sử; lịch sử trùng ent-10",
    "v2-ent-26": "gần v1 g081/g089 (thuế thu nhập doanh nghiệp)",
})
EDITS["v2-ent-16"] = {
    "reference_answer": "Khi người thừa kế không muốn trở thành thành viên, phần vốn góp được công ty mua lại hoặc "
                        "chuyển nhượng theo Điều 51 và Điều 52 (điểm a khoản 4 Điều 53 Luật Doanh nghiệp 2020). Việc "
                        "mua lại thực hiện theo Điều 51: công ty phải mua lại trong 15 ngày kể từ ngày nhận được yêu "
                        "cầu, theo giá thị trường hoặc giá xác định theo nguyên tắc tại Điều lệ, trừ khi hai bên thỏa "
                        "thuận được giá; chỉ được thanh toán nếu sau đó công ty vẫn trả đủ nợ và nghĩa vụ tài sản "
                        "khác (khoản 3 Điều 51). Nếu công ty không thanh toán được thì có quyền tự do chuyển nhượng "
                        "phần vốn góp cho thành viên khác hoặc người không phải là thành viên (khoản 4 Điều 51).",
}
EDITS["v2-ent-28"] = {"tags": ["no_doc_name"]}


def apply():
    items = load(DRAFT)
    ids = {i["id"] for i in items}
    for k in list(DROPS) + list(EDITS):
        assert k in ids, k
    out = []
    for it in items:
        if it["id"] in DROPS:
            continue
        it = copy.deepcopy(it)
        e = EDITS.get(it["id"], {})
        for k, v in e.items():
            if k == "add_sources":
                it["gold_sources"] = it["gold_sources"] + v
            else:
                it[k] = v
        it["reviewed"] = True
        out.append(it)
    return out


def stats(items):
    man = M
    c = Counter(i["type"] for i in items)
    print(len(items), "items;", dict(c))
    grp = Counter((i["id"].split("-")[1], i["type"]) for i in items)
    for g in ["lab", "ent", "dp", "dec"]:
        print(f"  {g}: total {sum(v for (gg, t), v in grp.items() if gg == g)} ",
              {t: grp[(g, t)] for t in ["single_article", "numeric", "multi_hop", "paraphrase", "unanswerable",
                                        "multi_turn"]})
    tags = Counter(t for i in items for t in i.get("tags", []))
    print("tags", dict(tags))
    lang = Counter(i["language"] for i in items)
    print("lang", dict(lang), f"en share {lang['en'] / len(items):.0%}")
    ans = [i for i in items if i.get("gold_sources")]
    xl = []
    for i in ans:
        langs = {man.get(s["doc_id"]).language for s in i["gold_sources"]}
        if i["language"] not in langs:
            xl.append(i)
    vi_gdpr = [i for i in xl if i["language"] == "vi" and {s["doc_id"] for s in i["gold_sources"]} == {GDPR}]
    en_nd = [i for i in xl if i["language"] == "en" and {s["doc_id"] for s in i["gold_sources"]} == {ND}]
    print(f"cross-lingual {len(xl)}/{len(ans)} = {len(xl) / len(ans):.0%}; vi-GDPR {len(vi_gdpr)} "
          f"(no_doc_name {sum('no_doc_name' in i.get('tags', []) for i in vi_gdpr)}); en-ND {len(en_nd)} "
          f"(no_doc_name {sum('no_doc_name' in i.get('tags', []) for i in en_nd)})")
    expl = Counter(i["id"].split("-")[1] for i in items if "explicit_ref" in i.get("tags", []))
    print("explicit_ref by group", dict(expl))
    cmp_ = [i["id"] for i in items if "comparison" in i.get("tags", [])]
    print("comparison", cmp_)


if __name__ == "__main__":
    items = apply()
    stats(items)
    if "--write" in sys.argv:
        OUT.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
        print("written", OUT)
