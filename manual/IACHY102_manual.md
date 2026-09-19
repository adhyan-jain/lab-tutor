# IACHY102 — Engineering Chemistry Laboratory Manual (VIT)

Transcribed text of the IACHY102 course manual. Page numbers below are
the manual's own printed page numbers, so citations against this file
line up with citations against the original PDF.

Course: IACHY102, Engineering Chemistry Laboratory, VIT. 10 experiments
assessed this semester, 10 marks each, 100 total, no FAT — continuous
assessment only (p.4). Rubric per experiment: Doing the experiment 2M +
Observations/calculations 2M + Results-vs-skill-value 6M (error 0–3%→6,
>3–4%→5, >4–5%→4, >5%→1) (p.7–8), except Experiments 7 and 8 which use a
separate computational rubric: Building the molecule 2M + Completion of
calculation 3M + Report 5M (p.42, p.47).

## Assessed experiment set (p.7, "Assessment procedure" — authoritative
numbering; the longer 15-item "Indicative Experiments" list on p.5–6 is
the wider syllabus pool, not the assessed set)

| # | Title | Manual pages |
|---|-------|-------|
| 1 | Thermodynamic functions from EMF measurements: Zn–Cu system | 10–15 |
| 2 | Determination of reaction rate, order and molecularity — ester hydrolysis | 16–19 |
| 3 | Colorimetric estimation of Ni2+ (conventional + smartphone RGB) | 20–23 |
| 4 | Analysis of iron in carbon steel by potentiometry | 28–32 |
| 5 | Preparation of ZnO semiconductor and its characterization | 33–35 |
| 6 | Estimation of sulfate ion in drinking water by conductivity | 24–27 |
| 7 | Build atoms and molecules; visualize atomic/hybrid orbitals; calculate orbital contributions (Gabedit/ORCA/Avogadro) | 39–42 |
| 8 | Conformational analysis of cyclohexane AND ethane; potential energy profile | 43–47 |
| 9 | Colorimetric estimation of Fe2+ (conventional + smartphone RGB) | 48–51 |
| 10 | Size-dependent colour variation of Cu2O nanoparticles (nephelometry) | 36–38 |

Experiment 8 covers both ethane (staggered/eclipsed) and cyclohexane
(chair/boat/twist-boat) conformer energies. Experiment 7 is a separate
DFT/orbital-contribution workflow (CH4 and O2, HOMO/LUMO).

---

## Experiment 1 — Thermodynamic functions from EMF measurements: Zn–Cu system (p.10–15)

**Aim:** construct/measure EMF of a Daniell cell at different metal-ion
concentrations and temperatures; determine ΔG, ΔH, ΔS.

**Half-reactions:** Zn(s) → Zn²⁺(aq) + 2e⁻ (E° = −0.760 V); Cu²⁺(aq) + 2e⁻
→ Cu(s) (E° = +0.340 V). Overall Ecell° = 0.340 − (−0.760) = **1.10 V**.

**Part A — single electrode potential:**
E°(M/Mⁿ⁺) = E(M/Mⁿ⁺) − (0.0595/n)·log(γc·C), where γc is the activity
coefficient (Table 2, p.12) and C the electrolyte concentration.
E(M/Mⁿ⁺) = Ecell + Ecalomel; Ecalomel (SCE) = 0.244 ± 0.0007 V (25°C).

**Part B — Nernst equation for the cell:**
Ecell = Ecell° − (RT/nF)·ln([Zn²⁺]/[Cu²⁺]), R = 8.314 J·K⁻¹·mol⁻¹, F =
96500, n = 2.

*Worked example (p.13), verbatim:* [Zn²⁺] = 0.05 M, [Cu²⁺] = 0.01 M, T =
303 K (30 °C):
Ecell = 1.1 − (8.314×303)/(2×96500) · ln(0.05/0.01)
      = 1.1 − 0.01305 × 1.6094 = 1.1 − 0.021 = **1.079 V**.

**Part C — Gibbs free energy:** ΔG = −nFEcell.
*Worked example (p.13):* n=2, E=0.99 V, F=96500 → ΔG₁ = −2×96500×0.99 =
**−191 kJ/mol** at T₁ = 30 °C. n=2, E=1.020 V → ΔG₁ₐ = −2×96500×1.020 =
**−197 kJ/mol** at T₁ₐ = 50 °C.

**Part C — ΔH and ΔS (Gibbs–Helmholtz), worked example (p.14–15):**
ΔG₁ at 30 °C = −191 kJ/mol, ΔG₁ₐ at 50 °C = −197 kJ/mol →
ΔG* at 40 °C (313 K) = (−191 + −197)/2 = **−194 kJ/mol** (simple average
of the two bracketing ΔG values, as printed).
∂(ΔG)/∂T = (ΔG₁ₐ − ΔG₁)/(T₁ₐ − T₁) = (−197 − (−191))/(323 − 303)
        = −6/20 = **−0.3 kJ/K**.
ΔH = ΔG − T·[∂(ΔG)/∂T] = −194 − 313×(−0.3) = −194 + 93.9 = **−100.1 kJ**.
ΔS = (ΔH − ΔG)/T = (−100.1 − (−194))/313 = 93.9/313 = **0.3 kJ·K⁻¹·mol⁻¹**.

No stated numeric tolerance band for this experiment specifically; the
course-wide rubric (p.8) uses the same 0–3/3–4/4–5/>5% error bands as
every other wet-lab experiment, applied to the final ΔG/ΔH/ΔS results.

---

## Experiment 2 — Ester hydrolysis kinetics (p.16–19)

Acid-catalysed hydrolysis of ethyl acetate, pseudo-first-order in ester
(water in large excess). Reaction: CH3COOC2H5 + H2O →(H+) CH3COOH +
C2H5OH.

k₁' = (2.303/t)·log[(V∞ − V₀)/(V∞ − Vt)], equivalently k₁' = slope ×
2.303 from a plot of log(V∞ − Vt) vs t, where V₀/Vt/V∞ are NaOH titre
volumes at t=0, at time t, and at completion. No fully-worked numeric
example is printed (Table-1 on p.19 is blank for the student to fill);
the sample graph (p.18) shows illustrative points only, not tabulated
values to reproduce exactly.

---

## Experiment 3 — Colorimetric estimation of Ni²⁺ (p.20–23)

Ni²⁺ + DMG (alkaline) → pink Ni(dmg)₂, oxidised by K3[Fe(CN)6] → brown-red
complex, λmax = **440 nm**. Standards: 2, 4, 6, 8 ppm (1/2/3/4 mL of 100
ppm Ni stock into 50 mL flasks) + 1 unknown. Beer's law: A = εcl.
Digital/RGB method: same standards photographed, RGB (or R/G, G/B, R/B
ratio — whichever is linear) vs concentration, "RGB Tool" app. No
numeric worked example printed (Table 1, p.23, is blank).

---

## Experiment 4 — Iron in carbon steel by potentiometry (p.28–32)

5Fe²⁺ + MnO4⁻ + 8H⁺ → 5Fe³⁺ + Mn²⁺ + 4H2O. E = E₀ + (RT/nF)·ln([Fe³⁺]/[Fe²⁺]).
Endpoint from EMF-vs-volume plot (S-curve) or its derivative ΔE/ΔV vs
average volume (sharp peak at equivalence). N(steel) = 0.05 N ×
V(KMnO4 at endpoint) / 20 mL. Fe (g/100 mL) = N(steel) × 55.85 × 100/1000.
No numeric worked example printed (both titration tables are blank).

---

## Experiment 5 — ZnO semiconductor preparation and characterization (p.33–35)

Zn(NO3)2 + 2KOH → Zn(OH)2 + 2KNO3; Zn(OH)2 →(120°C, 1h) ZnO + H2O.
Characterization: XRD (hexagonal ZnO, reference pattern p.34), UV-Vis
(reported band gap **3.2 eV** for the reference sample), SEM (spherical
morphology, reference image p.34). Crystallite size via Scherrer
equation: Grain size = k·λ / (cos θ · FWHM), k = 0.9, λ = 1.0506 Å,
θ and FWHM read off the student's own XRD trace. This is a wet-lab +
instrumental-characterization experiment with no student-computed
numeric formula beyond Scherrer's equation (θ/FWHM are read from an
instrument trace the manual does not supply numbers for) — no worked
example to reproduce.

---

## Experiment 6 — Sulfate estimation by conductometry (p.24–27)

BaCl2 + Na2SO4 → BaSO4↓ + 2NaCl, followed conductometrically (minimum
conductance at equivalence, from intersecting line-segments on a
conductance-vs-volume plot). Standardisation: N(BaCl2) = 0.02 N × 20 mL
/ V₁ (mL, from Plot-1 intersection). Unknown: N(sample) = N(BaCl2) ×
V₂ / 20 mL. Sulfate (g/100 mL) = N(sample) × 48.03 × 100/1000. Given
constant for the unknown: 0.96 mg/mL sulfate, eq. wt. of SO4²⁻ = 48.03.
No V₁/V₂ numeric example printed (student reads these off their own
titration plot) — no worked example to reproduce end-to-end, though the
formula chain itself is unambiguous.

---

## Experiment 7 — Build atoms/molecules; orbital visualization; orbital contributions (p.39–42)

Workflow (Gabedit → ORCA 5.0.4 → Avogadro), for **CH4** and **O2**:
1. Build structure in Gabedit (Geometry → Draw).
2. Generate ORCA input, optimize geometry, run ORCA, confirm "job
   completion" message in the output file, read the final energy.
3. Re-open the optimized geometry (not the drawn one), generate a new
   ORCA input for a single-point/orbital calculation, run it.
4. Read orbital energies from the output; visualize HOMO/LUMO and the
   optimized structure in Avogadro.
5. Repeat steps 3–4 across method/basis-set combinations: B3LYP and B3P,
   each with 6-31G / 6-31G* / 6-31G** (Tables 1–2, p.41–42) — 6 runs per
   molecule, recording HOMO/LUMO orbital energy (eV) and the s/p/d/f
   electron-count contribution per atom (C+4H for methane; O+O for O2).

No reference numeric HOMO/LUMO values are printed (the result tables are
blank for the student to fill from their own ORCA runs). The manual asks
the student to look for the job completion message at the end of the
output file after each ORCA run.

---

## Experiment 8 — Conformational analysis: ethane AND cyclohexane (p.43–47)

**Ethane:** staggered vs eclipsed, via Avogadro (build) → ORCA (DFT
single-point, `! BP RI SP def2-SVP def2/J`, sample input shown p.45) →
plot energy vs conformer. Reference plot (p.45) shows staggered lower
than eclipsed at both dihedral repeats (illustrative curve, not a
numeric table to reproduce — the printed y-axis values are for the
manual's own example run, not a general worked answer).

**Cyclohexane:** chair, half-chair, twist-boat, boat — same procedure.
Reference plot (p.46) orders chair (lowest) < twist-boat < half-chair ≈
boat (highest), i.e. chair is the global minimum and boat/half-chair the
highest-energy forms, consistent with standard ring-strain chemistry.

Deterministic check available: the *ordering* the chemistry requires —
staggered < eclipsed (ethane); chair < twist-boat < half-chair, chair <
boat, twist-boat < boat (cyclohexane) — can be verified from the
student's own reported energies without needing the manual's specific
numbers.

---

## Experiment 9 — Colorimetric estimation of Fe²⁺ (p.48–51)

4Fe³⁺ + 2NH2OH·HCl → 4Fe²⁺ + N2O + 4H⁺ + H2O (reduces stray Fe³⁺ first).
Fe²⁺ + 1,10-phenanthroline → red [Fe(phen)3]²⁺, λmax = **510 nm**.
Standards: 1, 2, 3, 4 ppm (5/10/15/20 mL of 10 ppm Fe stock into 50 mL
flasks) + 1 unknown. Same Beer's-law and RGB-ratio methodology as
Experiment 3. No numeric worked example printed (Table 1, p.51, blank).

---

## Experiment 10 — Size-dependent colour variation of Cu2O nanoparticles (p.36–38)

Benedict's reagent (Cu²⁺-citrate complex) + glucose, alkaline, heated →
Cu2O nanoparticles; particle size (hence colour: yellow → red) increases
with NaOH concentration/volume used. Measured by turbidity/Nephelometry
(NTU) rather than absorbance. Table 1 (p.37): 5 NaOH concentrations (0,
0.0001, 0.001, 0.01, 0.1 M) → colour goes yellow (low) to red (high),
illustrative colours only, not numeric. Table 2 (p.37) + Observations
(p.38): 4 standards (A–D, NaOH volumes 45/40/35/30 mL) + 1 unknown,
turbidity (NTU) vs NaOH volume calibration, unknown read off the graph.
No numeric turbidity values are printed (both the standard curve figure
on p.38 and the observations table are for the student's own run) — no
worked example to reproduce.
