# Experiment 7 ground truth — Build atoms/molecules; orbital visualization; orbital contributions

Reference for checking every gauntlet answer in this sprint against.
Sources: `manual/IACHY102_manual.md` (tier A, p.39-42) and
`sources/tier_b/exp07_exp08_supplementary.md` (tier B, the genuinely-new
detail confirmed present in the fuller course PDF/DOCX but absent from
the markdown transcription). Nothing here is invented.

## The 5-step workflow (tier A)

Workflow: **Gabedit → ORCA 5.0.4 → Avogadro**, for **CH4** and **O2**.

1. Build structure in Gabedit (Geometry → Draw).
2. Generate ORCA input, optimize geometry, run ORCA, confirm a "job
   completion" message in the output file, read the final energy.
3. Re-open the *optimized* geometry (not the originally-drawn one),
   generate a new ORCA input for a single-point/orbital calculation, run
   it.
4. Read orbital energies from the output; visualize HOMO/LUMO and the
   optimized structure in Avogadro.
5. Repeat steps 3-4 across method/basis-set combinations: **B3LYP** and
   **B3P**, each with **6-31G / 6-31G* / 6-31G**** (Tables 1-2, p.41-42)
   — 6 runs per molecule, recording HOMO/LUMO orbital energy (eV) and the
   s/p/d/f electron-count contribution per atom (C+4H for methane; O+O
   for O2).

## What's checkable without reference numbers (tier A)

No reference numeric HOMO/LUMO values exist anywhere — the result tables
are blank for the student to fill in from their own ORCA runs. This is a
computational-method-execution experiment, not a measured-vs-recomputed
quantity. What the system CAN check deterministically (see
`backend/tier1_compute/experiments/exp07.py`'s `ComputationSanityPlugin`):
job-completion/convergence markers, LUMO energy > HOMO energy for the
same run, and energy after optimization ≤ energy before.

## The genuinely-new detail (tier B, confirmed present in the fuller PDF/DOCX)

**Building O2 in Gabedit** is a *different* sequence than drawing
methane (which uses the Hydrocarbon menu): click the element marked in
red to open the periodic table, select the Oxygen atom (O), then click
and pull down in the drawing window to produce the O2 molecule.

**Gabedit version**: 2.5.1, named explicitly in the source material.

## Genuinely not available anywhere (say so honestly, do not invent)

Confirmed absent from the manual transcription, the fuller PDF, the
BTech DOCX, and the two supplied Jupyter notebooks/ML docx (which are an
unrelated course's material and contain nothing about Exp7 at all):

- **Exact ORCA input-generator dialog field names/labels.** The manual
  and fuller documents describe this only generically ("change into the
  job type, types of calculation method, DFT method, and basis sets"),
  with the actual dialog only shown as an unindexed screenshot image in
  every source seen. No machine-readable field name exists to cite.
- **Table 1/2 numeric HOMO/LUMO and s/p/d/f values.** Blank in the source
  PDF itself for every method/basis-set row — this is intentional
  (students fill them from their own runs), not a transcription gap.
- **A sample ORCA input string for Exp7 specifically** (Exp8's manual
  section cites one, `! BP RI SP def2-SVP def2/J`, p.45 — that citation
  could not be re-verified against the fuller PDF/DOCX text extraction
  either, since p.45 is a screenshot image in every source seen; it is
  not contradicted, just unconfirmable by this pass).
- Any further Avogadro menu granularity beyond "Open the Avogadro
  software → Open the output file → select HOMO or LUMO."

A correct exp07 answer to a question touching one of these points states
the workflow/concept it can support, then says plainly that the specific
detail asked for isn't in the available material — it does not invent a
menu path, a field name, or a number to fill the gap.
