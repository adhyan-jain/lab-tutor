Supplementary procedural detail for Experiments 7 and 8, drawn from the
fuller course PDF/DOCX supplied alongside the markdown manual
transcription (`IACHY102-2026-27-manual_2_260830_133124.pdf` and
`BTech_Lab_V5_09072025.docx`). This is official course material, but it
is not the manual transcription itself -- every citation drawn from this
file is labelled as such (see `backend/sources/tiers.py`). Table 1/2's
numeric HOMO/LUMO and s/p/d/f values are blank in every source seen --
students fill them from their own ORCA runs. The exact fields of the ORCA
input dialog are shown only in screenshots, so they are not listed here.

## Experiment 7 — Build atoms/molecules; orbital visualization; orbital contributions (p.39–42)

Software used: Gabedit (version 2.5.1) builds the molecules and input files; ORCA 5.0.4 optimizes the molecules and predicts the energy of the optimized molecules; Avogadro visualizes the optimized molecule and the molecular orbitals from the output. The molecules modelled are methane (CH4) and oxygen (O2). The manual says full instructions with screenshots are available at a link it provides, which is not part of this material.

Step 1 (methane): Open Gabedit. Many options are available at the top of the window, for example File, Edit, Tools and Geometry.

Step 2 (methane): Model the methane molecule. Go to the Geometry option and click on Draw; this opens the structure modelling window. Go to the bottom of that window and click Hydrocarbon, then select the methane molecule. Click in the drawing window to place the methane molecule. Then right-click, go to Save as, and save the input as a Gabedit file on your computer. After saving the input, close the modelling window.

Step 3 (input file creation and structure optimization): First the structure is optimized, and only then is the orbital contribution calculated. Open Gabedit again and open the saved Gabedit file, which opens the saved structure. Click the ORCA input generator; it opens the ORCA input, where you change the job type, the type of calculation method, the DFT method and the basis set, then click OK. Go to Run and click "Run a computational chemistry program". In the dialog that appears, click ORCA, change the file name used to save the data, and click OK; the simulation starts. After it completes, open the output file in the same folder and look at the end of the file for the job completion message. If the job completion message is not there, the run ended with an error. Once the simulation has completed, open the output file to get the final energy of the methane molecule.

Step 4 (single-point calculation and molecular orbital generation): After the optimization, run a calculation for the orbital contribution. Open the geometry-optimized file; it now serves as the initial geometry for the calculation, and the drawn structure should not be used. Change the calculation type as required, click the ORCA input generation option, make the changes in the window that opens, and click OK. Go to Run, click "Run a computational chemistry program", choose ORCA, change the file name, and click OK to start the simulation.

Step 5 (output file and orbital energy): Go to the folder that contains the input and find the output file. After the simulation is completed, open the output; the orbital energies can be seen there.

Step 6 (visualization in Avogadro): Open the Avogadro software and go to the open option. Open the output file. The methane structure and the orbital energies can now be visualized. Selecting HOMO or LUMO displays that orbital's structure.

Oxygen molecule (O2): The calculations are the same as for CH4, so follow the same procedure; only the structure modelling differs. Step 1, building the O atom: click the red-coloured item to open the periodic table and select the oxygen atom (O). Step 2, building the O2 molecule: click in the window and pull down to get the O2 molecule, then visualize it. Right-click, go to Save As, and save the Gabedit input file on your computer. Steps 3, 4, 5 and 6 are the same as for methane.

Repeating for other methods and basis sets: for both molecules, repeat steps 3 to 6 with the different methods and basis sets given in Tables 1 and 2 (B3LYP and B3P, each with 6-31G, 6-31G* and 6-31G**, so six runs per molecule). Open the input file in Gabedit and go to the ORCA input generator. Click "Types of method" and change it to the hybrid functional ORCA option. Click "Method" and change it to the method given in the table. Click "Basis" and change it to the basis set given in the table. After finishing every calculation, open the output file, where the orbital contribution can be seen; the final contribution values are taken and filled into Table 1. The HOMO and LUMO values are taken from Avogadro.

Tables and marks: Table 1 (methane) records, for each of the six method/basis-set combinations, the HOMO and LUMO orbital energies in eV and the number of electrons present in the s, p, d and f orbitals of C and of the four H atoms. Table 2 (O2) records the same for the two O atoms. The Results section asks for HOMO and LUMO for B3LYP/6-31G for both CH4 and O2. The marks are 2 for building the molecule, 3 for completion of the calculation and 5 for the report, out of 10.

## Experiment 8 — Conformational analysis: ethane AND cyclohexane (p.43–47)

**Running the ORCA calculation from the command line.** After generating
the ORCA input file (named e.g. `1.inp`), the job is run with:

```
orca 1.inp >1.out
```

This is repeated once per conformer (staggered, eclipsed; chair, boat,
half-chair, twist-boat), each producing its own output file to read the
final energy and, for the orbital-energy runs, HOMO/LUMO from.
