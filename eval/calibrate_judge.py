"""Hiệu chỉnh LLM-judge: xuất mẫu cho người chấm độc lập, cho các judge chấm cùng bộ mẫu, rồi đo mức đồng thuận.

    python eval/calibrate_judge.py export eval/results/<...>_e2e.json [--n 50]
    python eval/calibrate_judge.py judge --judge groq          # judge khác chấm cùng bộ mẫu, chấm tiếp được
    python eval/calibrate_judge.py agreement --judge gemini [--labels eval/judges/calibration_labels.jsonl]

`export` ghi 2 file:
- eval/judges/calibration_samples.jsonl: mẫu cho người chấm. KHÔNG có điểm judge. Mỗi dòng gồm id, type, question,
  history, reference_answer, contexts (đã đánh số [n], đủ text và metadata như judge đã thấy), answer, citations.
- eval/judges/calibration_judge_scores_<hồ sơ judge>.jsonl: nhãn và điểm của judge đã chấm lần chạy e2e đó, cho
  đúng các mẫu đã xuất (người chấm không được xem).

`judge` cho một hồ sơ judge khác chấm các mẫu chưa có điểm trong file điểm của hồ sơ đó. Ghi file sau mỗi mẫu; hết
quota ngày thì dừng gọn, chạy lại hôm sau sẽ chấm tiếp phần còn thiếu.

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
import asyncio
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from run_e2e_eval import CONTEXT_FIELDS, JudgeRunner, check_estimate, estimate_cost, print_quota
from run_retrieval_eval import DirtyTreeError, check_git_clean, git_state

from app.core.costs import BudgetExceededError
from app.core.rag_config import load_rag_config
from app.evaluation.judge import JudgeCase, build_judge, judge_identity

JUDGES_DIR = ROOT / "eval" / "judges"
SAMPLES = JUDGES_DIR / "calibration_samples.jsonl"
LABELS = JUDGES_DIR / "calibration_labels.jsonl"
TARGET_AGREEMENT = 0.80
SEED = 7
SAMPLE_CONTEXT_FIELDS = ("n", *CONTEXT_FIELDS, "pages")


def scores_path(profile: str) -> Path:
    return JUDGES_DIR / f"calibration_judge_scores_{profile}.jsonl"


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


def judge_row(sample_id: str, identity: dict[str, Any], judged: dict[str, Any]) -> dict[str, Any]:
    return {"id": sample_id, "judge": identity, "scores": judged["scores"], "runs": judged["runs"]}


def judge_done(row: dict[str, Any]) -> bool:
    return any(run["error"] is None for run in row["runs"])


def export(results_path: Path, n: int, golden_path: Path) -> None:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results.get("kind") != "e2e":
        raise ValueError(f"{results_path} không phải kết quả e2e")
    identity = {key: value for key, value in results["judge"].items()
                if key not in ("repeats", "judged", "missing", "stopped_reason")}
    profile = identity.get("profile")
    if not profile:
        raise ValueError(f"{results_path} không ghi hồ sơ judge (chạy trước khi có judge theo hồ sơ)")
    golden = {row["id"]: row for row in read_jsonl(golden_path)}
    chosen = choose(results["questions"], n)
    write_jsonl(SAMPLES, [sample_row(r, golden, results_path.name) for r in chosen])
    write_jsonl(scores_path(profile), [judge_row(r["id"], identity, r["judge"]) for r in chosen])
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in chosen:
        counts[record["type"]][judge_label(record) == "correct"] += 1
    print(f"Đã xuất {len(chosen)} mẫu vào {SAMPLES.relative_to(ROOT)} (không có điểm judge)")
    print(f"Điểm judge {profile} của các mẫu đó: {scores_path(profile).relative_to(ROOT)}")
    for question_type, (bad, good) in sorted(counts.items()):
        print(f"  {question_type:<15} {bad + good:>3} mẫu: judge chấm đúng {good}, chưa đúng {bad}")


async def judge_samples(judge_name: str | None, max_cost: float | None) -> None:
    config = load_rag_config()
    name = judge_name or config.eval.judge
    profile = config.judge_profile(name)
    identity = judge_identity(name, profile, config.eval.judge_prompt_version)
    samples = read_jsonl(SAMPLES)
    path = scores_path(name)
    rows = {row["id"]: row for row in read_jsonl(path)} if path.exists() else {}
    keys = ("provider", "model", "prompt_version")
    if any(any(row["judge"].get(key) != identity[key] for key in keys) for row in rows.values()):
        raise ValueError(f"{path} có điểm của judge khác {[identity[k] for k in keys]}; đổi tên hoặc xoá file trước")
    todo = [sample for sample in samples if sample["id"] not in rows or not judge_done(rows[sample["id"]])]
    check_estimate(estimate_cost(config, [], len(todo), profile, answers=False), max_cost)
    print_quota(name, profile, len(todo))
    runner = JudgeRunner(build_judge(profile, config.eval.judge_prompt_version, config.prices), repeats=1)
    commit = git_state()["commit"]
    for index, sample in enumerate(todo, start=1):
        history = [(turn["role"], turn["content"]) for turn in sample["history"]]
        case = JudgeCase(sample["question"], sample["reference_answer"], sample["contexts"], sample["answer"], history)
        judged, _ = await runner.run(case)
        if judged is None:
            break
        rows[sample["id"]] = judge_row(sample["id"], identity, judged) | {
            "judged_at": datetime.now().astimezone().isoformat(timespec="seconds"), "commit": commit,
        }
        write_jsonl(path, [rows[s["id"]] for s in samples if s["id"] in rows])
        print(f"\r{index}/{len(todo)} mẫu", end="", flush=True)
    print()
    done = sum(judge_done(row) for row in rows.values())
    print(f"{path.relative_to(ROOT)}: {done}/{len(samples)} mẫu đã có điểm"
          + (f"; dừng sớm: {runner.stopped}" if runner.stopped else ""))


def _rate(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    agree = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "agreement": round(agree / len(pairs), 4) if pairs else None}


def agreement(labels_path: Path, judge_scores: Path) -> dict[str, Any]:
    labels = {row["id"]: row for row in read_jsonl(labels_path)}
    judged = {row["id"]: row for row in read_jsonl(judge_scores)}
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
    judge_parser = sub.add_parser("judge")
    judge_parser.add_argument("--judge", metavar="TÊN", help="hồ sơ judge trong [judges.<tên>]; mặc định [eval] judge")
    judge_parser.add_argument("--max-cost", type=float, metavar="USD")
    judge_parser.add_argument("--allow-dirty", action="store_true", help="vẫn chạy khi code chưa commit")
    agreement_parser = sub.add_parser("agreement")
    agreement_parser.add_argument("--judge", metavar="TÊN", help="hồ sơ judge có file điểm cần so; mặc định [eval] judge")
    agreement_parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()
    try:
        if args.command == "export":
            export(args.results, args.n, args.golden)
            return 0
        if args.command == "judge":
            check_git_clean(args.allow_dirty)
            asyncio.run(judge_samples(args.judge, args.max_cost))
            return 0
        report = agreement(args.labels, scores_path(args.judge or load_rag_config().eval.judge))
    except (BudgetExceededError, DirtyTreeError, OSError, ValueError, KeyError) as exc:
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
