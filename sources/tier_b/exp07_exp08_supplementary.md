Supplementary procedural detail for Experiments 7 and 8, drawn from the
fuller course PDF/DOCX supplied alongside the markdown manual
transcription (`IACHY102-2026-27-manual_2_260830_133124.pdf` and
`BTech_Lab_V5_09072025.docx`). This is official course material, but it
is not the manual transcription itself -- every citation drawn from this
file is labelled as such (see `backend/sources/tiers.py`). Only the
procedural detail confirmed genuinely absent from
`manual/IACHY102_manual.md` is included here; nothing in this file
duplicates or overrides that document, and Table 1/2's numeric HOMO/LUMO
and s/p/d/f values remain blank in every source seen -- students fill
them from their own ORCA runs.

## Experiment 7 — Build atoms/molecules; orbital visualization; orbital contributions (p.39–42)

**Building O2 in Gabedit.** After building methane, building the O2
molecule uses a different sequence than drawing a hydrocarbon: click the
element marked in red to open the periodic table, select the Oxygen atom
(O), then click and pull down in the drawing window to produce the O2
molecule (two bonded oxygen atoms), rather than the Hydrocarbon-menu
path used for methane.

**Software version.** The source material names Gabedit **2.5.1**
specifically.

## Experiment 8 — Conformational analysis: ethane AND cyclohexane (p.43–47)

**Running the ORCA calculation from the command line.** After generating
the ORCA input file (named e.g. `1.inp`), the job is run with:

```
orca 1.inp >1.out
```

This is repeated once per conformer (staggered, eclipsed; chair, boat,
half-chair, twist-boat), each producing its own output file to read the
final energy and, for the orbital-energy runs, HOMO/LUMO from.
