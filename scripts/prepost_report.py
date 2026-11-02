"""Pre-test / post-test statistical report for one experiment.

Usage:
    python scripts/prepost_report.py --csv data/prepost_raw/exp07_prepost.csv \
        --pre-col "Pre Test" --post-col "Post Test" --id-col "Register Number" \
        --experiment "Experiment 7" --topic "..." --max-score 10 \
        --out data/session_data/reports/Exp07_PrePost_Report.pdf \
        [--prompts N --students N --session-date YYYY-MM-DD]

Implements the agreed analysis plan:
  * primary: paired-samples t-test (two-sided, alpha = 0.05)
  * sensitivity: Wilcoxon signed-rank test
  * effect size: Cohen's d_z (mean diff / SD of diffs), with Hedges' correction
  * uncertainty: 95% CI of the mean improvement
  * assumptions: Shapiro-Wilk + Q-Q plot on the DIFFERENCE scores, IQR outlier
    flagging (flagged, never deleted), floor / ceiling check

Pure statistics -- no model is involved in any number or verdict here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from scipy import stats

ALPHA = 0.05


def load_pairs(csv: str, id_col: str, pre_col: str, post_col: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(csv)
    raw.columns = [c.strip() for c in raw.columns]
    id_col, pre_col, post_col = id_col.strip(), pre_col.strip(), post_col.strip()
    df = raw[[id_col, pre_col, post_col]].copy()
    df.columns = ["id", "pre", "post"]
    df["id"] = df["id"].astype(str).str.strip()
    df = df[df["id"].ne("") & df["id"].ne("nan")]
    df["pre"] = pd.to_numeric(df["pre"], errors="coerce")
    df["post"] = pd.to_numeric(df["post"], errors="coerce")
    dup = int(df["id"].duplicated().sum())
    df = df.drop_duplicates("id", keep="first")
    enrolled = len(df)
    only_pre = int((df["pre"].notna() & df["post"].isna()).sum())
    only_post = int((df["pre"].isna() & df["post"].notna()).sum())
    neither = int((df["pre"].isna() & df["post"].isna()).sum())
    paired = df.dropna(subset=["pre", "post"]).copy()
    paired["diff"] = paired["post"] - paired["pre"]
    return paired, {
        "rows_in_sheet": enrolled, "duplicates_dropped": dup, "only_pre": only_pre,
        "only_post": only_post, "neither": neither, "paired_n": len(paired),
    }


def analyse(p: pd.DataFrame, max_score: float) -> dict:
    n = len(p)
    d = p["diff"].to_numpy(float)
    pre, post = p["pre"].to_numpy(float), p["post"].to_numpy(float)
    md, sd = d.mean(), d.std(ddof=1)
    se = sd / np.sqrt(n)
    tcrit = stats.t.ppf(1 - ALPHA / 2, n - 1)
    t_res = stats.ttest_rel(post, pre)
    dz = md / sd if sd > 0 else float("nan")
    hedges = dz * (1 - 3 / (4 * (n - 1) - 1))
    try:
        w = stats.wilcoxon(d, zero_method="wilcox", alternative="two-sided", method="auto")
        w_stat, w_p = float(w.statistic), float(w.pvalue)
    except ValueError:
        w_stat, w_p = float("nan"), float("nan")
    sh = stats.shapiro(d)
    q1, q3 = np.percentile(d, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out_mask = (d < lo) | (d > hi)
    # rank-biserial correlation for the Wilcoxon (matched pairs)
    nz = d[d != 0]
    ranks = stats.rankdata(np.abs(nz))
    rb = (ranks[nz > 0].sum() - ranks[nz < 0].sum()) / ranks.sum() if len(nz) else float("nan")
    return {
        "n": n,
        "pre_mean": pre.mean(), "pre_sd": pre.std(ddof=1), "pre_median": float(np.median(pre)),
        "post_mean": post.mean(), "post_sd": post.std(ddof=1), "post_median": float(np.median(post)),
        "diff_mean": md, "diff_sd": sd, "diff_median": float(np.median(d)),
        "ci_low": md - tcrit * se, "ci_high": md + tcrit * se,
        "t": float(t_res.statistic), "df": n - 1, "p_t": float(t_res.pvalue),
        "dz": dz, "hedges_gz": hedges,
        "wilcoxon_W": w_stat, "p_w": w_p, "rank_biserial": float(rb), "wilcoxon_nonzero": int(len(nz)),
        "shapiro_W": float(sh.statistic), "p_shapiro": float(sh.pvalue),
        "skew_diff": float(stats.skew(d)), "kurt_diff": float(stats.kurtosis(d)),
        "improved": int((d > 0).sum()), "same": int((d == 0).sum()), "declined": int((d < 0).sum()),
        "outliers": [
            {"id": p["id"].iloc[i], "pre": float(pre[i]), "post": float(post[i]), "diff": float(d[i])}
            for i in np.where(out_mask)[0]
        ],
        "outlier_fence": [float(lo), float(hi)],
        "pre_at_floor": int((pre <= 0).sum()), "post_at_floor": int((post <= 0).sum()),
        "pre_at_ceiling": int((pre >= max_score).sum()), "post_at_ceiling": int((post >= max_score).sum()),
        "pre_post_r": float(np.corrcoef(pre, post)[0, 1]) if n > 2 else float("nan"),
        "gain_pct_of_pre": float(md / pre.mean() * 100) if pre.mean() else float("nan"),
    }


def fmt_p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def figures(p: pd.DataFrame, r: dict, title: str, max_score: float, tmp: Path) -> list[Path]:
    paths = []
    pre, post, d = p["pre"].to_numpy(), p["post"].to_numpy(), p["diff"].to_numpy()
    c_pre, c_post, c_diff = "#6b7280", "#2563eb", "#059669"

    fig, ax = plt.subplots(1, 3, figsize=(11, 3.6))
    bins = np.arange(-0.5, max_score + 1.5, 1)
    ax[0].hist(pre, bins=bins, color=c_pre, alpha=0.85, edgecolor="white"); ax[0].set_title("Pre-test scores")
    ax[1].hist(post, bins=bins, color=c_post, alpha=0.85, edgecolor="white"); ax[1].set_title("Post-test scores")
    db = np.arange(d.min() - 0.5, d.max() + 1.5, 1)
    ax[2].hist(d, bins=db, color=c_diff, alpha=0.85, edgecolor="white")
    ax[2].axvline(0, color="black", lw=1); ax[2].axvline(d.mean(), color="#dc2626", ls="--", lw=1.5, label=f"mean = {d.mean():.2f}")
    ax[2].set_title("Difference (post - pre)"); ax[2].legend(frameon=False)
    for a in ax:
        a.set_ylabel("Students"); a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); f = tmp / "dist.png"; fig.savefig(f, dpi=170); plt.close(fig); paths.append(f)

    fig, ax = plt.subplots(1, 3, figsize=(11, 3.8))
    stats.probplot(d, dist="norm", plot=ax[0]); ax[0].set_title("Q-Q plot of difference scores")
    ax[0].get_lines()[0].set_markerfacecolor(c_diff); ax[0].get_lines()[0].set_markeredgecolor(c_diff)
    bp = ax[1].boxplot([pre, post, d], tick_labels=["Pre", "Post", "Diff"], patch_artist=True, widths=0.5)
    for patch, col in zip(bp["boxes"], [c_pre, c_post, c_diff]):
        patch.set_facecolor(col); patch.set_alpha(0.6)
    ax[1].set_title("Box plots"); ax[1].axhline(0, color="black", lw=0.6)
    for y0, y1 in zip(pre, post):
        ax[2].plot([0, 1], [y0, y1], color=c_diff if y1 > y0 else ("#dc2626" if y1 < y0 else "#9ca3af"), alpha=0.45, lw=1)
    ax[2].set_xticks([0, 1]); ax[2].set_xticklabels(["Pre", "Post"]); ax[2].set_ylim(-0.3, max_score + 0.3)
    ax[2].set_title("Trajectories (green up, red down)")
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); f = tmp / "diag.png"; fig.savefig(f, dpi=170); plt.close(fig); paths.append(f)
    return paths


def build_pdf(args, p: pd.DataFrame, meta: dict, r: dict) -> None:
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / ".tmp_fig"; tmp.mkdir(exist_ok=True)
    figs = figures(p, r, args.experiment, args.max_score, tmp)

    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=19, spaceAfter=4, textColor=colors.HexColor("#111827"))
    SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=10, textColor=colors.HexColor("#4b5563"), spaceAfter=10)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#1f2937"))
    B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.6, leading=13.5)
    SM = ParagraphStyle("SM", parent=B, fontSize=8.4, leading=11, textColor=colors.HexColor("#4b5563"))
    SMB = ParagraphStyle("SMB", parent=SM, fontName="Helvetica-Bold", textColor=colors.HexColor("#111827"))

    def table(rows, widths):
        rows = [[Paragraph(str(c), SMB if i == 0 else SM) for c in row] for i, row in enumerate(rows)]
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
        return t

    P = lambda s, st=B: Paragraph(s, st)
    sig = r["p_t"] < ALPHA
    sig_w = r["p_w"] < ALPHA
    normal_ok = r["p_shapiro"] >= ALPHA
    mag = "negligible" if abs(r["dz"]) < 0.2 else "small" if abs(r["dz"]) < 0.5 else "medium" if abs(r["dz"]) < 0.8 else "large"

    S = [P(f"{args.experiment}: Pre-test vs Post-test Statistical Report", H1)]
    sub = "LabTutor (Catalyst) &middot; BACHY105 Applied Chemistry Lab &middot; class SJT-102"
    if args.topic:
        sub += f" &middot; {args.topic}"
    S += [P(sub, SUB), P("1. Summary", H2)]
    direction = "rose" if r["diff_mean"] > 0 else "fell"
    S += [P(
        f"Across <b>{r['n']}</b> students with both scores, the mean score {direction} from "
        f"<b>{r['pre_mean']:.2f}</b> (SD {r['pre_sd']:.2f}) to <b>{r['post_mean']:.2f}</b> (SD {r['post_sd']:.2f}) out of "
        f"{args.max_score:g}: a mean change of <b>{r['diff_mean']:+.2f}</b> points (95% CI {r['ci_low']:+.2f} to {r['ci_high']:+.2f}). "
        f"The paired t-test is {'statistically significant' if sig else 'not statistically significant'} "
        f"(t({r['df']}) = {r['t']:.2f}, p {fmt_p(r['p_t'])}), with a {mag} effect (Cohen's d<sub>z</sub> = {r['dz']:.2f}). "
        f"The Wilcoxon signed-rank sensitivity test {'agrees' if sig == sig_w else 'DISAGREES'} "
        f"(p {fmt_p(r['p_w'])}). {r['improved']} students improved, {r['same']} were unchanged and {r['declined']} declined.")]

    rows = [["Metric", "Value", "Notes"],
            ["Sheet rows (unique students)", str(meta["rows_in_sheet"]), f"{meta['duplicates_dropped']} duplicate ID row(s) dropped"],
            ["Valid paired sample (N)", str(r["n"]), f"excluded: {meta['only_pre']} pre only, {meta['only_post']} post only, {meta['neither']} neither"],
            ["Pre-test, mean (SD)", f"{r['pre_mean']:.2f} ({r['pre_sd']:.2f})", f"median {r['pre_median']:g}"],
            ["Post-test, mean (SD)", f"{r['post_mean']:.2f} ({r['post_sd']:.2f})", f"median {r['post_median']:g}"],
            ["Mean difference (post - pre)", f"{r['diff_mean']:+.2f}", f"SD of differences {r['diff_sd']:.2f}; median {r['diff_median']:+g}"],
            ["95% CI of mean difference", f"[{r['ci_low']:+.2f}, {r['ci_high']:+.2f}]", "t-based, df = n - 1"],
            ["Paired t-test (two-sided)", f"t({r['df']}) = {r['t']:.2f}, p {fmt_p(r['p_t'])}", "significant" if sig else "not significant at alpha = 0.05"],
            ["Wilcoxon signed-rank", f"W = {r['wilcoxon_W']:.1f}, p {fmt_p(r['p_w'])}", f"{r['wilcoxon_nonzero']} non-zero differences; rank-biserial r = {r['rank_biserial']:+.2f}"],
            ["Effect size, Cohen's d<sub>z</sub>", f"{r['dz']:.2f}", f"{mag}; Hedges' g<sub>z</sub> = {r['hedges_gz']:.2f}"],
            ["Pre-post correlation", f"r = {r['pre_post_r']:.2f}", "how consistently students keep their rank"]]
    S += [Spacer(1, 6), table(rows, [5.2 * cm, 4.6 * cm, 7.4 * cm])]

    S += [P("2. Assumption checks", H2)]
    n_out = len(r["outliers"])
    chk = [["Check", "Result", "Reading"],
           ["Paired by unique ID", "Register number", f"{meta['duplicates_dropped']} duplicates; students without both scores excluded"],
           ["Normality of differences (Shapiro-Wilk)", f"W = {r['shapiro_W']:.3f}, p {fmt_p(r['p_shapiro'])}",
            "no evidence against normality; confirm on the Q-Q plot" if normal_ok else "evidence against normality: weigh the Wilcoxon result alongside the t-test"],
           ["Shape of differences", f"skew {r['skew_diff']:+.2f}, excess kurtosis {r['kurt_diff']:+.2f}", "values near 0 indicate a roughly symmetric, normal-like shape"],
           ["Outliers (1.5 x IQR rule)", f"{n_out} flagged", f"fences [{r['outlier_fence'][0]:+.1f}, {r['outlier_fence'][1]:+.1f}]; flagged only, none removed"],
           ["Floor / ceiling", f"pre: {r['pre_at_floor']} at 0, {r['pre_at_ceiling']} at max; post: {r['post_at_floor']} at 0, {r['post_at_ceiling']} at max",
            "ceiling clustering would cap possible gains" if r["post_at_ceiling"] > 0.15 * r["n"] else "no strong floor/ceiling effect"],
           ["Equal variances", "not required", "paired design"]]
    S += [table(chk, [4.8 * cm, 5.4 * cm, 7.0 * cm])]
    S += [P("A Shapiro-Wilk p &lt; 0.05 is evidence against normality; p &ge; 0.05 does not prove normality. With roughly 30-60 pairs the Q-Q plot and the size of any deviation matter as much as the p-value.", SM)]
    if n_out:
        orows = [["Register no.", "Pre", "Post", "Difference"]] + [[o["id"], f"{o['pre']:g}", f"{o['post']:g}", f"{o['diff']:+g}"] for o in r["outliers"]]
        S += [Spacer(1, 4), P("<b>Flagged differences</b> (check for data-entry errors; genuine extreme changes stay in the analysis):", B),
              table(orows, [4 * cm, 2.2 * cm, 2.2 * cm, 3 * cm])]

    S += [PageBreak(), P("3. Figures", H2), Image(str(figs[0]), width=17.2 * cm, height=17.2 * cm * 3.6 / 11),
          Spacer(1, 6), Image(str(figs[1]), width=17.2 * cm, height=17.2 * cm * 3.8 / 11)]

    if args.prompts:
        S += [P("4. Tool usage in the same session", H2),
              P(f"Students sent <b>{args.prompts}</b> chat prompts to the tutor for this experiment"
                + (f" ({args.students} distinct students)" if args.students else "")
                + (f", about {args.prompts / args.students:.1f} prompts per student" if args.students else "")
                + (f" (session date {args.session_date})" if args.session_date else "") + ". "
                "These are descriptive engagement counts only; this report does not relate usage to score change.", B)]

    S += [P("5. Interpretation and limits", H2),
          P("This is a single-group pre/post design with no control group. A significant improvement shows that scores rose "
            "between the two tests; it cannot by itself attribute the rise to the tutor, because the lab session, the "
            "manual, teaching and test familiarity all sit between the two measurements. The analysis uses only the "
            "students who completed both tests; if non-completers differ systematically from completers the result may "
            "not generalise to the full class. Statistics were computed with SciPy; no language model produced any figure "
            "or verdict in this report.", B)]
    if args.note:
        S += [Spacer(1, 4), P(args.note, B)]

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=1.9 * cm, rightMargin=1.9 * cm, topMargin=1.7 * cm,
                            bottomMargin=1.6 * cm, title=f"{args.experiment} Pre/Post Report", author="LabTutor")
    doc.build(S)
    for f in figs:
        f.unlink()
    tmp.rmdir()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True); ap.add_argument("--id-col", required=True)
    ap.add_argument("--pre-col", required=True); ap.add_argument("--post-col", required=True)
    ap.add_argument("--experiment", required=True); ap.add_argument("--topic", default="")
    ap.add_argument("--max-score", type=float, default=10); ap.add_argument("--out", required=True)
    ap.add_argument("--prompts", type=int, default=0); ap.add_argument("--students", type=int, default=0)
    ap.add_argument("--session-date", default="")
    ap.add_argument("--note", default="", help="extra design caveat paragraph for section 5")
    args = ap.parse_args()
    paired, meta = load_pairs(args.csv, args.id_col, args.pre_col, args.post_col)
    r = analyse(paired, args.max_score)
    build_pdf(args, paired, meta, r)
    Path(args.out).with_suffix(".json").write_text(json.dumps({"meta": meta, "stats": r}, indent=2, default=float))
    print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "outliers"}, default=float))
    print("outliers:", r["outliers"])


if __name__ == "__main__":
    main()
