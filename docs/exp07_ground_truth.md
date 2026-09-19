# Experiment 7 ground truth — Build atoms/molecules; orbital visualization; orbital contributions

Reference for checking every gauntlet answer. Verified line-by-line
against the text extracted from the course PDF
(`IACHY102-2026-27-manual_2_260830_133124.pdf`, Exp 7 = pp.39-42).
The retrievable form of this material is `sources/tier_b/exp07_exp08_supplementary.md`
(tier B, cited as official supplementary material) plus the shorter
summary in `manual/IACHY102_manual.md` (tier A). General-chemistry
"why" answers come from `knowledge/adjacent/exp07_*.md` (tier C,
labelled background, never the manual).

A correction to an earlier version of this file: the manual's Exp7
section is NOT thin. The markdown transcription is a summary; the PDF
spells out every step below.

## The procedure (PDF pp.39-41)

Software: **Gabedit** (2.5.1 per the DOCX) builds molecules and input
files; **ORCA 5.0.4** optimizes and predicts energies; **Avogadro**
visualizes the optimized molecule and the orbitals from the output.
Molecules: methane (CH4) and oxygen (O2).

**Methane**
1. Open Gabedit; menus at the top include File, Edit, Tools, Geometry.
2. Model methane: **Geometry → Draw** (opens the structure modelling
   window); at the bottom click **Hydrocarbon**, select the **methane**
   molecule; click in the window to place it; **right-click → Save as**,
   save as a Gabedit file; close the modelling window.
3. Optimize first, then calculate the orbital contribution. Open Gabedit,
   open the saved file; click the **ORCA input generator** → change the
   job type, type of calculation method, DFT method, basis set → **OK**.
   **Run → "Run a computational chemistry program"** → click **orca** →
   change the file name used to save data → **OK** (starts the run).
   When done, open the output in the same folder; at the end look for the
   **job completion message** (absent = ended with an error). Read the
   **final energy**.
4. Single point / orbitals: open the **geometry-optimized file** — it is
   the initial geometry; do NOT use the drawn structure. Change the
   calculation type as desired; ORCA input generation → change settings →
   OK; Run → Run a computational chemistry program → orca → file name → OK.
5. Output: go to the input folder, open the output file; orbital energies
   are there.
6. Avogadro: open Avogadro → **open** → open the output file → the
   methane structure and orbital energies are visualized; selecting
   **HOMO** or **LUMO** shows that orbital.

**Oxygen (O2)** — same calculations/procedure; only the modelling
differs: click the **red-coloured item** → periodic table → select
**oxygen (O)**; click in the window and **pull down** to get O2;
visualize; right-click → Save As (Gabedit file). Steps 3-6 as methane.

**Repeat for Tables 1 and 2** (both molecules, steps 3-6): open the input
in Gabedit → ORCA input generator → **Types of method → hybrid
functional (orca)**; **Method** → per table; **Basis** → per table.
After each run read the orbital contributions from the output (fill
Table 1); **HOMO and LUMO values are taken from Avogadro**.

**Table 1 (CH4) / Table 2 (O2):** six rows each — B3LYP and B3P, each
with 6-31G, 6-31G*, 6-31G**. Columns: HOMO/LUMO orbital energy (eV) and
the number of electrons in the s, p, d, f orbitals (C and 4H for CH4;
O and O for O2). **Results** section: HOMO/LUMO for B3LYP/6-31G, both
molecules. **Marks:** building 2 + completion of calculation 3 +
report 5 = 10.

## Genuinely not available in any supplied material (say so, never invent)

- The exact **field names/labels inside the ORCA input dialog** (the
  text says only "job type, calculation method, DFT method, basis sets");
  the dialog is shown only as screenshots. The manual also refers to a
  link with screenshot instructions that is not part of the material.
- **Numeric HOMO/LUMO and s/p/d/f values** — the tables are blank in the
  source by design (students fill them from their own runs).
- Any **menu path inside Avogadro beyond "open → output file → select
  HOMO or LUMO"**, and any **troubleshooting procedure** (Gabedit won't
  open a file, Avogadro crashes, runtimes) — the manual has none.
- The **multiplicity value to enter for O2** and any ORCA keyword syntax
  for Exp7 (the only sample input string in the material is Exp8's,
  p.45, a screenshot).
- The command-line form `orca 1.inp >1.out` appears only in Exp8's
  steps, not Exp7's (Exp7 uses Gabedit's Run dialog).

A correct answer touching these states what the material does say, then
plainly says the specific detail isn't in it. Consistency checks such as
"LUMO above HOMO" or "energy shouldn't rise after optimization" are
general chemistry (background explainer), NOT statements of the manual.
