"""Figures for the JSET manuscript.

Run from the repo root:  .venv/bin/python data/paper/make_figures.py
Reads data/session_data/reports/Exp0N_PrePost_Report.json (written by
scripts/prepost_report.py) and writes data/paper/figures/fig1_architecture.png and
fig2_effects.png.  No model is involved in any number shown.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path("data")
OUT = ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


def box(ax, x, y, w, h, text, fc="#f3f4f6", ec="#6b7280", bold=False, size=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, fontweight="bold" if bold else "normal")


def arrow(ax, x0, y0, x1, y1, color="#374151"):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.3))


def fig1() -> None:
    fig, ax = plt.subplots(figsize=(7.6, 4.9))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6.6); ax.axis("off")
    box(ax, 0.2, 5.4, 2.2, 0.9, "Student message\n(phone / browser)", fc="#e0f2fe", ec="#0284c7")
    box(ax, 3.2, 5.4, 3.2, 0.9, "Deterministic triage\nsafety - distress - off-scope\n(regex, no model call)", fc="#fef3c7", ec="#d97706")
    box(ax, 7.2, 5.4, 2.6, 0.9, "Fixed, authored reply\n(0 model calls)", fc="#fef3c7", ec="#d97706")
    arrow(ax, 2.4, 5.85, 3.2, 5.85); arrow(ax, 6.4, 5.85, 7.2, 5.85)

    box(ax, 0.2, 3.5, 2.9, 1.2, "Deterministic mode selection\ntheory Q&A / authored Socratic\nfollow-up / numeric check", fc="#dcfce7", ec="#16a34a")
    box(ax, 3.6, 3.5, 2.8, 1.2, "Tier 1: compute + verdict\nTier 2: known-mistake library\nTier 3: escalate to staff", fc="#dcfce7", ec="#16a34a", bold=True)
    box(ax, 6.9, 3.5, 2.9, 1.2, "Retrieval from the course\nmanual and authored notes\n(BM25 + TF-IDF hybrid)", fc="#ede9fe", ec="#7c3aed")
    arrow(ax, 1.6, 5.4, 1.6, 4.7); arrow(ax, 3.1, 4.1, 3.6, 4.1); arrow(ax, 6.4, 4.1, 6.9, 4.1)

    box(ax, 1.5, 1.7, 7.0, 1.0, "ONE language-model generation per message\nphrases an already-made decision, grounded in the retrieved passage", fc="#fee2e2", ec="#dc2626", bold=True)
    arrow(ax, 5.0, 3.5, 5.0, 2.7)
    box(ax, 2.2, 0.35, 5.6, 0.85, "Answer gate (single outbound door)\nstrips any number the student has not already seen", fc="#e0f2fe", ec="#0284c7", bold=True)
    arrow(ax, 5.0, 1.7, 5.0, 1.2)
    ax.text(9.9, 0.8, "Student", ha="right", fontsize=8, color="#374151"); arrow(ax, 7.8, 0.78, 9.1, 0.78)
    ax.text(0.2, 2.4, "Models never see\nthe final answer", fontsize=7.8, color="#991b1b", style="italic", va="center")
    fig.tight_layout(); fig.savefig(OUT / "fig1_architecture.png", dpi=220); plt.close(fig)


def fig2() -> None:
    rows = []
    for n, label in (("02", "Exp 2  Ester hydrolysis kinetics"), ("03", "Exp 3  Nickel by colorimetry"),
                     ("07", "Exp 7  Orbital energies (ORCA)"), ("08", "Exp 8  Conformer analysis")):
        s = json.loads((ROOT / "session_data" / "reports" / f"Exp{n}_PrePost_Report.json").read_text())["stats"]
        rows.append((label, s["n"], s["diff_mean"], s["ci_low"], s["ci_high"], s["dz"], s["p_t"], s["p_w"]))
    fig, ax = plt.subplots(figsize=(7.6, 3.3))
    ys = list(range(len(rows)))[::-1]
    for y, (lab, n, m, lo, hi, dz, pt, pw) in zip(ys, rows):
        col = "#059669" if lo > 0 else "#6b7280"
        ax.plot([lo, hi], [y, y], color=col, lw=2.2); ax.plot(m, y, "o", color=col, ms=7)
        ptxt = f"p={pt:.3f}" if pt >= 0.001 else "p<0.001"
        ax.text(3.45, y, f"N={n}   d_z={dz:.2f}   {ptxt}", va="center", fontsize=8)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(ys); ax.set_yticklabels([r[0] for r in rows]); ax.set_xlim(-1.5, 5.6)
    ax.set_xlabel("Mean change in score, post - pre (points out of 10), with 95% CI")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "fig2_effects.png", dpi=220); plt.close(fig)


if __name__ == "__main__":
    fig1(); fig2(); print("figures written to", OUT)
