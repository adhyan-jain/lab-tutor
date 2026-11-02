"""Split the combined Exp2 + Exp3 Google-Form pre/post quizzes into per-experiment scores.

Each form has 20 MCQs: questions 1-10 are Experiment 2, 11-20 are Experiment 3. The
exported sheet has every student's answers and only a TOTAL ("12 / 20"), not per-question
marks and not the answer key. So the key is *derived*: we solve for the one answer-per-
question assignment that reproduces every student's total exactly (integer programme).
The script refuses to continue unless (a) a solution exists and (b) it is unique, and the
derived key is written out so it can be eyeballed against the real quiz.

Usage:
    python scripts/prepost_exp02_03_prepare.py [raw_dir]   # default data/prepost_raw

Writes exp02_prepost.csv, exp03_prepost.csv (reg no, name, pre, post; scores out of 10)
and exp02_03_derived_answer_key.json + exp02_03_data_quality.json into raw_dir.

Data-quality rules (all counted in the data_quality file):
  * register number is taken from whichever of the Name / Registration Number fields
    matches ^\\d{2}[A-Z]{3}\\d{4}$ after upper-casing, trimming and O->0 in the digits;
  * rows with no recoverable register number are excluded;
  * a student who submitted more than once keeps their FIRST submission.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

REG = re.compile(r"^\d{2}[A-Z]{3}\d{4}$")


def clean_reg(value: object) -> str | None:
    s = re.sub(r"\s+", "", str(value)).upper()
    if len(s) == 9:  # letter O typed for zero in the 4 trailing digits
        s = s[:5] + s[5:].replace("O", "0")
    return s if REG.match(s) else None


def derive_key(d: pd.DataFrame, qcols: list[str]) -> dict[int, str]:
    opts = [sorted(d[c].dropna().astype(str).str.strip().unique()) for c in qcols]
    idx: dict[tuple[int, str], int] = {}
    for q, o in enumerate(opts):
        for a in o:
            idx[(q, a)] = len(idx)
    nv = len(idx)
    one = np.zeros((len(qcols), nv))
    for (q, _a), j in idx.items():
        one[q, j] = 1
    stu = np.zeros((len(d), nv))
    for i, (_, r) in enumerate(d.iterrows()):
        for q, c in enumerate(qcols):
            if pd.notna(r[c]):
                stu[i, idx[(q, str(r[c]).strip())]] = 1
    tot = d["tot"].to_numpy()
    base = [LinearConstraint(one, 1, 1), LinearConstraint(stu, tot, tot)]
    first = milp(np.zeros(nv), constraints=base, integrality=np.ones(nv), bounds=Bounds(0, 1))
    if first.status != 0:
        raise SystemExit("No answer key reproduces every student's total: cannot derive scores safely.")
    x = np.round(first.x)
    chosen = np.where(x == 1)[0]
    cut = LinearConstraint(np.eye(nv)[chosen].sum(0, keepdims=True), 0, len(qcols) - 1)
    second = milp(np.zeros(nv), constraints=base + [cut], integrality=np.ones(nv), bounds=Bounds(0, 1))
    if second.status == 0:
        raise SystemExit("Answer key is NOT unique: need the real key from the quiz author.")
    inv = {j: k for k, j in idx.items()}
    return {inv[j][0]: inv[j][1] for j in chosen}


def load(path: Path) -> tuple[pd.DataFrame, dict, dict]:
    raw = pd.read_csv(path)
    qcols = list(raw.columns[4:24])
    raw["tot"] = raw["Score"].str.extract(r"(\d+)\s*/\s*20")[0].astype(float)
    key = derive_key(raw, qcols)
    ok = np.array([[str(r[c]).strip() == key[i] for i, c in enumerate(qcols)] for _, r in raw.iterrows()])
    assert (ok.sum(1) == raw["tot"].to_numpy()).all()
    raw["s02"], raw["s03"] = ok[:, :10].sum(1), ok[:, 10:].sum(1)
    regs, names, swapped = [], [], 0
    for _, r in raw.iterrows():
        a, b = clean_reg(r["Registration Number"]), clean_reg(r["Name"])
        reg = a or b
        swapped += int(a is None and b is not None)
        regs.append(reg)
        names.append(str(r["Registration Number"] if a is None and b else r["Name"]).strip())
    raw["reg"], raw["student_name"] = regs, names
    raw["ts"] = pd.to_datetime(raw["Timestamp"], errors="coerce")
    n_all = len(raw)
    bad = raw[raw["reg"].isna()]
    raw = raw[raw["reg"].notna()].sort_values("ts")
    dups = int(raw["reg"].duplicated().sum())
    raw = raw.drop_duplicates("reg", keep="first")
    qc = {"rows": n_all, "no_valid_register_number_excluded": len(bad), "id_fields_swapped_and_repaired": swapped,
          "repeat_submissions_dropped_kept_first": dups, "unique_students": len(raw)}
    return raw[["reg", "student_name", "s02", "s03", "ts"]], qc, {int(k) + 1: v for k, v in key.items()}


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/prepost_raw")
    pre, qc_pre, key_pre = load(root / "exp02_03_pretest.csv")
    post, qc_post, key_post = load(root / "exp02_03_posttest.csv")
    m = pre.merge(post, on="reg", how="outer", suffixes=("_pre", "_post"))
    m["name"] = m["student_name_pre"].fillna(m["student_name_post"])
    for exp, col in (("02", "s02"), ("03", "s03")):
        out = pd.DataFrame({"reg no": m["reg"], "name": m["name"], "pre": m[f"{col}_pre"], "post": m[f"{col}_post"]})
        out.sort_values("reg no").to_csv(root / f"exp{exp}_prepost.csv", index=False)
    both = int(m["s02_pre"].notna().mul(m["s02_post"].notna()).sum())
    (root / "exp02_03_derived_answer_key.json").write_text(json.dumps({"pretest": key_pre, "posttest": key_post}, indent=2, ensure_ascii=False))
    (root / "exp02_03_data_quality.json").write_text(json.dumps(
        {"pretest": qc_pre, "posttest": qc_post, "students_in_either_test": len(m), "students_with_both": both,
         "first_pre_submission": str(pre["ts"].min()), "last_pre_submission": str(pre["ts"].max()),
         "first_post_submission": str(post["ts"].min()), "last_post_submission": str(post["ts"].max())}, indent=2))
    print(json.dumps({"pretest": qc_pre, "posttest": qc_post, "either": len(m), "both": both}, indent=2))


if __name__ == "__main__":
    main()
