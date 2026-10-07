"""Hiệu chỉnh LLM-judge: xuất mẫu cho người chấm độc lập, rồi đo mức đồng thuận giữa người chấm và judge.

    python eval/calibrate_judge.py export eval/results/<...>_e2e.json [--n 50]
    python eval/calibrate_judge.py agreement [--labels eval/judges/calibration_labels.jsonl]

`export` ghi 2 file:
- eval/judges/calibration_samples.jsonl: mẫu cho người chấm. KHÔNG có điểm judge. Mỗi dòng gồm id, type, question,
  history, reference_answer, contexts (đã đánh số [n], đủ text), answer, citations (số [n] và nhãn văn bản/Điều/trang).
- eval/judges/calibration_judge_scores.jsonl: nhãn và điểm judge của đúng các mẫu đó (người chấm không được xem).

Chọn mẫu: chia theo `type` tỉ lệ với golden set; trong mỗi loại, lấy xen kẽ câu judge chấm đúng và câu judge chấm
chưa đúng (partially_correct, incorrect), để mẫu có cả câu trả lời đúng lẫn sai. Thứ tự trong mỗi nhóm cố định theo
seed. Vì chọn có chủ đích, tỉ lệ đúng/sai trong mẫu không phản ánh tỉ lệ thật của cả bộ.

Người chấm ghi eval/judges/calibration_labels.jsonl, mỗi dòng một mẫu:
    {"id": "g001", "faithful": true, "citations_ok": true, "correctness": "correct", "relevancy": "relevant",
     "notes": "..."}
- faithful: mọi ý trong câu trả lời đều có trong context (không xét đúng/sai so với đáp án chuẩn). Câu chỉ từ chối
  thì ghi null.
- citations_ok: mọi [n] gắn với một ý đều thật sự ủng hộ ý đó. Câu không có [n] nào thì ghi null.
- correctness: correct | partially_correct | incorrect, so với reference_answer.
- relevancy: relevant | partially_relevant | irrelevant.

`agreement` so từng metric (bỏ qua mẫu mà người chấm hoặc judge để null):
- faithful ↔ judge faithfulness = 1; citations_ok ↔ judge citation_precision = 1;
- correctness, relevancy: trùng nhãn 3 mức, và trùng khi gộp về 2 mức (đúng/chưa đúng).
Judge chỉ được tin khi đồng thuận ≥ 80% (CLAUDE.md).
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
JUDGES_DIR = ROOT / "eval" / "judges"
SAMPLES = JUDGES_DIR / "calibration_samples.jsonl"
JUDGE_SCORES = JUDGES_DIR / "calibration_judge_scores.jsonl"
LABELS = JUDGES_DIR / "calibration_labels.jsonl"
TARGET_AGREEMENT = 0.80
SEED = 7
SAMPLE_CONTEXT_FIELDS = ("n", "title", "so_hieu", "heading_path", "pages", "text")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def judge_label(record: dict[str, Any]) -> str | None:
    """Nhãn correctness của lần chấm đầu tiên không lỗi."""
    runs = [run for run in record.get("judge", {}).get("runs", []) if not run["error"]]
    return runs[0]["correctness"] if runs else None


def choose(records: list[dict[str, Any]], n: int, seed: int = SEED) -> list[dict[str, Any]]:
    """Chia theo type tỉ lệ với số câu; trong mỗi type lấy xen kẽ câu judge chấm đúng và chưa đúng."""
    judged = [r for r in records if judge_label(r) is not None]
    if len(judged) < n:
        raise ValueError(f"chỉ có {len(judged)} câu đã được judge chấm, cần {n}")
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in judged:
        by_type[record["type"]].append(record)
    # Quota theo tỉ lệ, làm tròn xuống, phần dư chia cho các type có phần thập phân lớn nhất.
    exact = {t: n * len(rows) / len(judged) for t, rows in by_type.items()}
    quota = {t: int(v) for t, v in exact.items()}
    for t in sorted(exact, key=lambda t: exact[t] - quota[t], reverse=True)[: n - sum(quota.values())]:
        quota[t] += 1
    rng = random.Random(seed)
    chosen = []
    for question_type, rows in sorted(by_type.items()):
        good = [r for r in rows if judge_label(r) == "correct"]
        bad = [r for r in rows if judge_label(r) != "correct"]
        rng.shuffle(good)
        rng.shuffle(bad)
        # Xen kẽ sai/đúng, bắt đầu từ câu sai vì câu sai hiếm hơn; hết một bên thì lấy bên kia.
        interleaved = [r for pair in zip(bad, good, strict=False) for r in pair]
        longer = bad if len(bad) > len(good) else good
        interleaved += longer[min(len(bad), len(good)):]
        chosen += interleaved[: quota[question_type]]
    return sorted(chosen, key=lambda r: r["id"])


def sample_row(record: dict[str, Any], golden: dict[str, dict[str, Any]], source: str) -> dict[str, Any]:
    item = golden[record["id"]]
    return {
        "id": record["id"],
        "type": record["type"],
        "language": record["language"],
        "question": record["question"],
        "history": item.get("history", []),
        "reference_answer": item["reference_answer"],
        "contexts": [{key: context.get(key) for key in SAMPLE_CONTEXT_FIELDS} for context in record["contexts"]],
        "answer": record["answer"]["text"],
        "citations": record["answer"]["citations"],
        "invalid_citations": record["answer"]["invalid_citations"],
        "source": source,
    }


def judge_row(record: dict[str, Any]) -> dict[str, Any]:
    runs = record["judge"]["runs"]
    return {
        "id": record["id"],
        "scores": record["judge"]["scores"],
        "runs": [{key: run[key] for key in ("correctness", "relevancy", "scores", "claims", "explanation", "error")}
                 for run in runs],
    }


def export(results_path: Path, n: int, golden_path: Path) -> None:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results.get("kind") != "e2e":
        raise ValueError(f"{results_path} không phải kết quả e2e")
    golden = {row["id"]: row for row in read_jsonl(golden_path)}
    chosen = choose(results["questions"], n)
    write_jsonl(SAMPLES, [sample_row(r, golden, results_path.name) for r in chosen])
    write_jsonl(JUDGE_SCORES, [judge_row(r) for r in chosen])
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in chosen:
        counts[record["type"]][judge_label(record) == "correct"] += 1
    print(f"Đã xuất {len(chosen)} mẫu vào {SAMPLES.relative_to(ROOT)} (không có điểm judge)")
    print(f"Điểm judge của các mẫu đó: {JUDGE_SCORES.relative_to(ROOT)}")
    for question_type, (bad, good) in sorted(counts.items()):
        print(f"  {question_type:<15} {bad + good:>3} mẫu: judge chấm đúng {good}, chưa đúng {bad}")


def _rate(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    agree = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "agreement": round(agree / len(pairs), 4) if pairs else None}


def agreement(labels_path: Path) -> dict[str, Any]:
    labels = {row["id"]: row for row in read_jsonl(labels_path)}
    judged = {row["id"]: row for row in read_jsonl(JUDGE_SCORES)}
    missing = sorted(set(judged) - set(labels))
    pairs: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for sample_id, human in labels.items():
        if sample_id not in judged:
            continue
        scores, runs = judged[sample_id]["scores"], judged[sample_id]["runs"]
        label = next((run["correctness"] for run in runs if not run["error"]), None)
        relevancy = next((run["relevancy"] for run in runs if not run["error"]), None)
        if human.get("faithful") is not None and scores["faithfulness"] is not None:
            pairs["faithful"].append((human["faithful"], scores["faithfulness"] == 1.0))
        if human.get("citations_ok") is not None and scores["citation_precision"] is not None:
            pairs["citations_ok"].append((human["citations_ok"], scores["citation_precision"] == 1.0))
        if human.get("correctness") and label:
            pairs["correctness"].append((human["correctness"], label))
            pairs["correctness_binary"].append((human["correctness"] == "correct", label == "correct"))
        if human.get("relevancy") and relevancy:
            pairs["relevancy"].append((human["relevancy"], relevancy))
            pairs["relevancy_binary"].append((human["relevancy"] == "relevant", relevancy == "relevant"))
    report = {metric: _rate(rows) for metric, rows in pairs.items()}
    return {"labels": len(labels), "missing_labels": missing, "target": TARGET_AGREEMENT, "metrics": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("results", type=Path)
    export_parser.add_argument("--n", type=int, default=50)
    export_parser.add_argument("--golden", type=Path, default=ROOT / "eval" / "datasets" / "golden_v1.jsonl")
    agreement_parser = sub.add_parser("agreement")
    agreement_parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()
    try:
        if args.command == "export":
            export(args.results, args.n, args.golden)
            return 0
        report = agreement(args.labels)
    except (OSError, ValueError, KeyError) as exc:
        print(exc)
        return 1
    print(f"{report['labels']} nhãn; thiếu nhãn: {report['missing_labels'] or 'không'}")
    for metric, row in report["metrics"].items():
        value = row["agreement"]
        verdict = "đạt" if value is not None and value >= TARGET_AGREEMENT else "CHƯA ĐẠT"
        print(f"  {metric:<20} n={row['n']:>3}  đồng thuận {value if value is not None else '-'}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
