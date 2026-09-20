"""Authored Experiment 7 walkthrough: Gabedit -> ORCA -> Avogadro.

Every control name below comes from the manual's own screenshots or the
Gabedit / ORCA / Avogadro manuals, as tagged in
knowledge/adjacent/exp07_background.md. Nothing here states a numerical
result of the student's calculation: the only numbers used as answer keys
are counts that follow from chemistry (electrons: 10 for CH4, 16 for O2)
or what a dialog visibly shows. The reference HOMO/LUMO ranges the course
withholds are deliberately not present.

Text fields use str.format with: {molecule}, {method}, {basis}, {n_elec},
{run_no}, {run_total}. Keep literal braces out of authored text.

A chapter's `preview` items are about the NEXT chapter's not-yet-taught
ideas and are asked at the end of the chapter that holds them.
"""

from __future__ import annotations

from backend.socratic_engine.walkthrough.types import (
    Chapter,
    Choice,
    Question,
    QuizItem,
    Script,
    WalkStep,
)

# ---------------------------------------------------------------- helpers


def _c(key: str, text: str, why: str = "") -> Choice:
    return Choice(key=key, text=text, why=why)


def _mcq(qid: str, ask: str, correct: str, *choices: Choice, hint: str = "", reveal: str = "", ok: str = "") -> Question:
    return Question(id=qid, ask=ask, kind="mcq", choices=choices, correct=correct, hint=hint, reveal=reveal, ok=ok)


def _short(qid: str, ask: str, *groups: tuple[str, ...], need: int = 1, hint: str = "", reveal: str = "", ok: str = "") -> Question:
    return Question(id=qid, ask=ask, kind="short", groups=groups, need=need, hint=hint, reveal=reveal, ok=ok)


def _num(qid: str, ask: str, *numbers: float, hint: str = "", reveal: str = "", ok: str = "") -> Question:
    return Question(id=qid, ask=ask, kind="number", numbers=numbers, tol=0.0, hint=hint, reveal=reveal, ok=ok)


def _report(qid: str, ask: str, capture: str, hint: str = "") -> Question:
    return Question(id=qid, ask=ask, kind="report", capture=capture, hint=hint)


def _seen(qid: str, ask: str, hint: str = "") -> Question:
    """An observation only someone at the screen can give: any real answer
    (not a bare 'ok') counts; there is no key to compare against."""
    return Question(id=qid, ask=ask, kind="short", groups=((r"[a-z0-9]{2,}",),), need=1, hint=hint)


def _q(qid: str, stem: str, correct: str, *choices: Choice, teaser_step: str = "", teaser: str = "") -> QuizItem:
    return QuizItem(id=qid, stem=stem, choices=choices, correct=correct, teaser_step=teaser_step, teaser=teaser)


# ------------------------------------------------------------------ steps

_BUILD = (
    WalkStep(
        id="b1_open", chapter="build", title="Open Gabedit",
        do="Open **Gabedit**. Look along the top of the main window: that row is the menu bar.",
        why="Gabedit is only the front end. It draws the molecule and writes the input file; ORCA does the calculation and Avogadro shows the result.",
        evidence=_seen("b1_e", "Tell me once Gabedit's window is actually open in front of you.",
                       hint="Just say a word or two once it's open -- I only need to know we're both looking at the same thing."),
        stuck="If Gabedit will not open, tell me exactly what happens (nothing, an error box, a blank window) and we will work from that.",
        ack="Good, that is the menu you will use next.",
    ),
    WalkStep(
        id="b2_draw", chapter="build", title="Open the drawing window",
        do="Choose **Geometry**, then **Draw**. A window called **Draw Geometry** opens; this is where you sketch the molecule.",
        why="Draw Geometry is a separate window with its own toolbar. Keeping it separate from the main window is why you save from here and reopen in the main window later.",
        evidence=_seen("b2_e", "Tell me once you can see the Draw Geometry window with its toolbar down the left side.",
                       hint="It opens as a separate window from the main one."),
        stuck="If nothing opens, check the menu path once more: **Geometry** first, then **Draw**. Tell me what you see.",
        ack="That is the drawing window.",
    ),
    WalkStep(
        id="b3_methane", chapter="build", title="Place methane",
        do="At the bottom of the window click **Hydrocarbon**, pick **methane** from the fragment list, then click once in the drawing area to drop it there.",
        why="The fragment library holds ready-made molecules with sensible starting geometry, so you do not have to build methane atom by atom.",
        evidence=_num("b3_e", "Count the atoms now in the drawing area, carbon and hydrogens together. How many?", 5.0,
                      hint="Methane is CH4: one carbon plus the hydrogens on it.",
                      reveal="Methane is one carbon and four hydrogens, so five atoms."),
        check=_mcq("b3_c", "Before you rotate it: what shape do the five atoms make?", "a",
                   _c("a", "A tetrahedron, with carbon at the centre", "Four bonds spread as far apart as they can get, about 109.5 degrees apart."),
                   _c("b", "A flat square with carbon in the middle", "A flat square would put the bonds only 90 degrees apart, closer than necessary."),
                   _c("c", "A straight line", "A line cannot hold four bonds around one atom."),
                   hint="Four hydrogens want to be as far from each other as possible in three dimensions.",
                   reveal="It is a tetrahedron: four bonds spread apart in 3D. Rotate the view and you will see it is not flat."),
        stuck="Fragment window not showing? It opens after you click **Hydrocarbon**. Tell me what is on screen.",
        ack="Five atoms, as expected.",
    ),
    WalkStep(
        id="b4_save", chapter="build", title="Save the structure",
        do="Right-click in the drawing area, choose **Save as**, pick **Gabedit file**, and save it. Then close the Draw Geometry window.",
        why="Gabedit file is the format the main window opens next. The other formats in that list (XYZ, Mol2, and so on) are for other programs.",
        evidence=_short("b4_e", "What three-letter extension does the file you saved end with?", (r"\.?gab\b",),
                        hint="It is named after the program you are using."),
        stuck="If Save as does not appear, right-click on empty space inside the drawing area rather than on an atom.",
        ack="Saved. Keep track of where; you will reopen it in a moment.",
    ),
)

_SETUP = (
    WalkStep(
        id="o1_open_file", chapter="setup", title="Open the saved file",
        do="Back in the main Gabedit window, open the file you just saved (the **File** menu, or the open icon on the toolbar).",
        why="Gabedit builds the ORCA input from whatever geometry is loaded in the main window, so the file has to be open there first.",
        prereq="This needs the Gabedit file you saved in the last chapter.",
        evidence=_seen("o1_e", "Tell me once you can see your saved structure loaded as text in the main window.",
                       hint="Open it from the File menu or the open icon on the toolbar."),
        stuck="If you cannot find your file, look in the folder you saved it to, and check it ends in .gab.",
        ack="The geometry is loaded as text, one row per atom.",
    ),
    WalkStep(
        id="o2_orca_dialog", chapter="setup", title="Open the Orca input dialog",
        do="On the main toolbar, click the **ORCA** icon (the manual boxes it in red). A dialog titled **Orca input** opens.",
        why="Each program icon on that toolbar opens that program's input generator. The dialog is where you choose what ORCA should calculate and how.",
        prereq="This needs the methane file open from the previous step.",
        evidence=_num("o2_e", "Find the line **Number of electrons** in the dialog. What number does it show?", 10.0,
                      hint="Count them yourself: carbon has 6 electrons and each hydrogen has 1.",
                      reveal="6 from carbon plus 4 x 1 from the hydrogens gives 10."),
        check=_mcq("o2_c", "Why is it worth reading that line before you change anything?", "b",
                   _c("a", "ORCA needs you to type it in", "The dialog fills it in from the atoms and the charge; you do not type it."),
                   _c("b", "It tells you whether the charge and multiplicity you have chosen can be right", "An odd electron count can never be a singlet, so a surprising number is a warning."),
                   _c("c", "It sets the basis set", "The basis set is a separate field further down."),
                   hint="Think about what would change the count: the atoms, or the charge.",
                   reveal="It is a quick check on charge and spin: the dialog computes it from your atoms and charge, so a surprising number means one of them is wrong."),
        stuck="If the dialog does not open, make sure a file is loaded in the main window, then click the ORCA icon again. Which icon are you clicking?",
        ack="Ten electrons for methane.",
    ),
    WalkStep(
        id="o3_job_scf", chapter="setup", title="Job type, charge and spin",
        do="Set **Job Type** to **Equilibrium structure search** (that is the geometry optimisation). Leave **Charge** at 0 and **Spin multiplicity** at 1, and **SCF Type** on restricted.",
        why="Optimisation first, because orbital energies are only meaningful at a relaxed geometry. Methane is neutral with every electron paired, so charge 0 and multiplicity 1.",
        evidence=_short("o3_e", "Tell me the **Charge** and **Spin multiplicity** the dialog shows now.", (r"\b0\b|zero|neutral",), (r"\b1\b|singlet|one",), need=2,
                        hint="Two numbers: first the charge, then the spin multiplicity."),
        check=_mcq("o3_c", "Why is a restricted SCF appropriate for methane?", "c",
                   _c("a", "Restricted is always faster and always correct", "Not always correct: it fails when electrons are unpaired."),
                   _c("b", "Because methane has a positive charge", "Methane here is neutral."),
                   _c("c", "Because every electron is paired, so each orbital holds one spin-up and one spin-down electron", "Exactly the closed-shell situation restricted is built for."),
                   hint="Count the electrons and ask whether any is left unpaired.",
                   reveal="All ten electrons are paired, so each occupied orbital holds one spin-up and one spin-down electron, which is what restricted means."),
        stuck="Job Type looks different from what I described? Read me the entries in its list and we will match it.",
        ack="Optimisation set up.",
    ),
    WalkStep(
        id="o4_method_basis", chapter="setup", title="Method and basis set",
        do="Set **Type of method** to the **hybrid functional** family, **Method** to **B3LYP**, and under **Type: Pople Style basis sets** set **Basis** to **6-31G**. Leave **Auxiliary basis** as it is.",
        why="The Results section of the manual asks for B3LYP with 6-31G, so start there. Auxiliary basis is a helper set ORCA builds itself to speed up integrals; the dialog greys it out.",
        evidence=_short("o4_e", "Read me the **Method** and **Basis** now shown in the dialog.", (r"b3lyp",), (r"6-31g(?![*\w])",), need=2,
                        hint="Two fields: Method, then Basis. Tell me both."),
        check=_mcq("o4_c", "What does choosing a bigger basis set change?", "a",
                   _c("a", "How much freedom the orbitals have to take their shape", "More basis functions let each orbital bend and polarise more accurately."),
                   _c("b", "How many electrons the molecule has", "The electron count comes from the atoms and charge."),
                   _c("c", "Which atoms are in the molecule", "That comes from the geometry."),
                   hint="A basis set is a set of building-block functions for the orbitals.",
                   reveal="A basis set is the toolbox of functions used to build each orbital; a bigger one gives the orbitals more freedom to take their shape."),
        stuck="Cannot find B3LYP? Change **Type of method** first; the Method list depends on it.",
        ack="B3LYP with 6-31G.",
    ),
    WalkStep(
        id="o5_check_input", chapter="setup", title="Press OK and read the input",
        do="Press **OK**. Gabedit writes the ORCA input into its text area. Read it and find the line that mentions your method and basis.",
        why="Checking the generated input before running is the habit that saves the most time: a wrong method, basis, charge or multiplicity shows up here first.",
        evidence=_short("o5_e", "Copy that line here, or tell me which method and basis words it contains.", (r"b3lyp",), (r"6-31g",), need=2,
                        hint="Look for the line containing B3LYP."),
        stuck="Text area unchanged? Make sure you pressed OK, not Cancel.",
        ack="The input matches what you chose.",
    ),
)

_RUN = (
    WalkStep(
        id="r1_run", chapter="run", title="Start the optimisation",
        do="Open the **Run** menu, choose **Run a Computation Chemistry program**, click **orca**, type a new file name for the results (say one that contains \"opt\"), and press **OK**.",
        why="Gabedit hands the input to ORCA and ORCA writes the results to the file name you give here. A distinct name keeps this run apart from the later one.",
        prereq="This needs the ORCA input from the last step.",
        evidence=_seen("r1_e", "Which file name did you type in the dialog?", hint="Just tell me the name you gave it."),
        stuck="Nothing seems to happen after OK? Give it a few seconds, then look at the **Output** tab at the bottom. Tell me what it shows.",
        ack="Running. Small molecules finish quickly.",
    ),
    WalkStep(
        id="r2_completion", chapter="run", title="Did it finish properly?",
        do="Open the output file (in the folder you saved to, or through the Run menu's view-result item) and jump to the end. Look for the **job completion message**.",
        why="A run that stopped with an error can still leave numbers in the file. The completion message is the only thing that tells you the numbers are trustworthy.",
        evidence=_short("r2_e", "Paste the completion line you find near the end, or tell me it is not there.", (r"terminated normally",), (r"not there|no such|missing|cannot find|can.?t find|didn.?t|absent",), need=1,
                        hint="Near the end there is a line with stars saying whether ORCA terminated normally."),
        check=_mcq("r2_c", "If that line is missing, what does it mean?", "b",
                   _c("a", "Nothing; the energies are still fine", "Numbers from a failed run cannot be trusted."),
                   _c("b", "The run ended with an error, so do not read energies from it", "Exactly: check the input and re-run."),
                   _c("c", "You are using the wrong basis set", "It could be many things, but the message itself only says the run did not finish cleanly."),
                   hint="What would a normal-termination message be telling you if it were there?",
                   reveal="A missing completion message means the run ended with an error. Do not read energies from it; check the input and run it again."),
        stuck="If ORCA did not terminate normally, look at the input echo near the top: a wrong charge, multiplicity, method or basis shows up there first. Paste what you see.",
        ack="Clean finish.",
    ),
    WalkStep(
        id="r3_energies", chapter="run", title="First and last energy",
        do="Search the output for **FINAL SINGLE POINT ENERGY**. The optimiser prints one for every geometry cycle. Note the **first** one and the **last** one (the last sits next to **OPTIMIZATION RUN DONE**). Give me both numbers, first then last.",
        why="Optimisation moves the atoms downhill, cycle by cycle, so the last energy cannot be higher than the first. That single fact is a check you can run on your own data.",
        evidence=_report("r3_e", "Tell me the first energy, then the last one (in Eh).", "e_first,e_final",
                         hint="Two numbers, both large and negative, in Hartree (Eh). First cycle first."),
        stuck="Only see one FINAL SINGLE POINT ENERGY? The optimisation may have converged in one cycle; tell me and we will check the line after it.",
        ack="Both energies recorded.",
        closes_hook=True,
    ),
)

_READ = (
    WalkStep(
        id="p1_open_opt", chapter="read", title="Start from the optimised geometry",
        do="In Gabedit open the **geometry-optimised** file from the run you just finished. Do not use the structure you drew.",
        why="The drawn structure is a rough guess. The optimised one is where the energy is lowest, and that is the geometry at which orbital energies mean something.",
        evidence=_seen("p1_e", "Which file did you open?", hint="Give me the file name."),
        check=_mcq("p1_c", "Why start the orbital calculation from the optimised geometry?", "b",
                   _c("a", "It makes the calculation run faster", "Speed is not the reason."),
                   _c("b", "Orbital energies describe the molecule at its lowest-energy shape, not at a guess", "Orbital energies depend on where the atoms sit."),
                   _c("c", "ORCA refuses to run on a drawn structure", "It would run; the numbers would just mean less."),
                   hint="Think about what the optimisation was for.",
                   reveal="Orbital energies depend on the geometry. The optimised shape is the molecule at rest, so that is the one worth reporting."),
        stuck="Not sure which file is the optimised one? Tell me the file names in your folder.",
        ack="Good habit: geometry first, then orbitals.",
    ),
    WalkStep(
        id="p2_single_point", chapter="read", title="Switch to a single point",
        do="Click the **ORCA** icon again. Change **Job Type** to **Single Point Energy**. Leave method and basis as they are, and press **OK**.",
        why="A single point does not move the atoms. It computes the energy and the orbitals for exactly the geometry you give it.",
        evidence=_short("p2_e", "Which **Job Type** does the dialog show now?", (r"single point",),
                        hint="It is the entry for a calculation at fixed geometry."),
        stuck="Do not see Single Point Energy? Open the Job Type list and read me its entries.",
        ack="Fixed-geometry calculation set up.",
    ),
    WalkStep(
        id="p3_run_sp", chapter="read", title="Run it under a new file name",
        do="Run it the same way as before (**Run**, **Run a Computation Chemistry program**, **orca**), but type a **new** results file name, say one containing \"sp\".",
        why="ORCA writes results to the name you give. The same name would overwrite the optimisation output you may still need.",
        evidence=_seen("p3_e", "Which file name did you use this time?", hint="Tell me the new name."),
        check=_mcq("p3_c", "Why must the name differ from the optimisation run's?", "a",
                   _c("a", "The same name would overwrite the earlier output", "Right: you would lose the optimisation results."),
                   _c("b", "ORCA cannot run twice on one molecule", "It can."),
                   _c("c", "Gabedit would delete the geometry", "The geometry is a separate file."),
                   hint="What happens to a file when another one is saved under its name?",
                   reveal="Saving under the same name overwrites the earlier output, so use a new name and both runs stay available."),
        stuck="Job still running? Check the **Output** tab. Tell me what you see.",
        ack="Single point running.",
    ),
    WalkStep(
        id="p4_orbital_table", chapter="read", title="Find the orbital energies table",
        do="Open the new output and search for **ORBITAL ENERGIES**. The columns are **NO**, **OCC**, **E(Eh)** and **E(eV)**.",
        why="OCC is how many electrons sit in that orbital. In a restricted run occupied orbitals show 2 and empty ones 0, so the HOMO is the last row with OCC 2 and the LUMO is the row right after it.",
        evidence=_num("p4_e", "How many rows have an **OCC** of 2?", 5.0,
                      hint="Ten electrons, two per orbital.",
                      reveal="Ten electrons in pairs fill five orbitals, so five rows have OCC 2."),
        check=_mcq("p4_c", "Which row is the HOMO?", "b",
                   _c("a", "The first row of the table", "The first row is the lowest-energy orbital, a deep core one."),
                   _c("b", "The last row that still has OCC 2", "That is the highest occupied orbital."),
                   _c("c", "The row with the largest NO", "The last row of the table is the highest empty orbital."),
                   hint="HOMO means highest occupied.",
                   reveal="HOMO is the last row that still holds electrons (OCC 2). The LUMO is the very next row."),
        stuck="Cannot find ORBITAL ENERGIES? Make sure you opened the single-point output and not the optimisation one.",
        ack="Five filled orbitals for ten electrons.",
    ),
    WalkStep(
        id="p5_homo_lumo", chapter="read", title="Read the HOMO and LUMO",
        do="From that table read the **E(eV)** value of the HOMO row and of the LUMO row. Give me both, HOMO first.",
        why="These are the two frontier orbitals. You will read the same two values in Avogadro as a cross-check.",
        evidence=_report("p5_e", "Tell me the HOMO energy, then the LUMO energy, in eV.", "homo_out,lumo_out",
                         hint="Two numbers from the E(eV) column: the last OCC 2 row, then the next row."),
        stuck="Not sure which row? The HOMO is the last row with OCC 2.",
        ack="HOMO and LUMO from ORCA recorded.",
    ),
)

_ORBITALS = (
    WalkStep(
        id="v1_avogadro", chapter="orbitals", title="Open the output in Avogadro",
        do="Open **Avogadro**, click **Open** on its toolbar, and load the single-point output file.",
        why="Avogadro reads the ORCA output and can draw the orbitals, which the text file cannot.",
        prereq="This needs the single-point output from the last chapter, not the optimisation one.",
        evidence=_seen("v1_e", "Tell me once your molecule is loaded and showing in Avogadro's 3D view.",
                       hint="Use Open on the toolbar and pick the single-point output file."),
        stuck="Avogadro will not open the file? Check its Messages bar under the 3D view and tell me what it says.",
        ack="The molecule is loaded.",
    ),
    WalkStep(
        id="v2_panel", chapter="orbitals", title="Read the Orbitals panel",
        do="Open the **Orbitals** panel. Its columns are **Orbital**, **Energy (eV)** and **Symmetry**. Find the **HOMO** row and the **LUMO** row and give me both energies.",
        why="Avogadro and ORCA list the same orbitals in the same units, so these two numbers should match the ones you read from the ORCA table.",
        evidence=_report("v2_e", "Tell me the HOMO energy, then the LUMO energy from the panel.", "homo_avo,lumo_avo",
                         hint="Two numbers, HOMO row first."),
        check=_mcq("v2_c", "Your LUMO may be positive in eV. What does that mean?", "c",
                   _c("a", "The calculation failed", "A completed run can have a positive LUMO."),
                   _c("b", "The molecule cannot accept electrons", "Positive does not mean that."),
                   _c("c", "Virtual orbitals are not filled, and a small basis set pushes them upward; the sanity checks that matter are HOMO usually negative and LUMO above HOMO", "It tells you about the method and basis, not a failure."),
                   hint="A virtual orbital has no electron in it, so its energy is not the energy of a bound electron.",
                   reveal="A positive LUMO is normal: virtual orbitals are empty, and small basis sets push them up. What matters is HOMO usually negative and LUMO above HOMO."),
        stuck="Panel empty? Make sure a molecule is loaded and try the Extensions menu for the orbital tool.",
        ack="Panel values recorded.",
    ),
    WalkStep(
        id="v3_render_homo", chapter="orbitals", title="Draw the HOMO",
        do="Click the **HOMO** row, then **Render**. You should see lobes in two colours around the molecule.",
        why="The energy tells you how high the orbital sits; the picture tells you where the electron density is, which is what matters for reactivity.",
        evidence=_num("v3_e", "How many different colours do the lobes have?", 2.0,
                      hint="Look at the 3D view after Render.",
                      reveal="There are two colours, red and blue."),
        check=_mcq("v3_c", "What do the two colours mean?", "b",
                   _c("a", "Red is positive charge and blue is negative charge", "The lobes are not charges."),
                   _c("b", "They are the two signs of the orbital's wave function", "The same sign as the coefficients in ORCA's MOLECULAR ORBITALS table."),
                   _c("c", "Red is the HOMO and blue is the LUMO", "Both lobes belong to the one orbital you selected."),
                   hint="It is a property of one orbital, not a comparison of two.",
                   reveal="The two colours are the two signs (phases) of the same orbital's wave function. They do not mean electric charge."),
        stuck="Nothing drawn? Select the HOMO row first, then press Render. Quality set to Low is fine.",
        ack="That is the HOMO.",
    ),
    WalkStep(
        id="v4_lumo", chapter="orbitals", title="Draw the LUMO",
        do="Now click the **LUMO** row and **Render** it.",
        why="The LUMO is where an incoming electron would go first. Comparing its shape with the HOMO's shows how the molecule would behave as an acceptor rather than a donor.",
        check=_mcq("v4_c", "Which orbital shows where an incoming electron would be accepted first?", "b",
                   _c("a", "The HOMO", "The HOMO is where electrons are given away from."),
                   _c("b", "The LUMO", "It is the lowest empty orbital."),
                   _c("c", "The lowest orbital in the table", "That is a deep core orbital."),
                   hint="One is for donating electrons, the other for receiving them.",
                   reveal="The LUMO is where an extra electron would go first; the HOMO is where electrons are most easily given away."),
        stuck="Tell me what you see when you click the LUMO row.",
        ack="Both frontier orbitals drawn.",
    ),
)

_OXYGEN = (
    WalkStep(
        id="x1_build", chapter="oxygen", title="Build O2",
        do="Open **Geometry**, then **Draw**. Click the icon boxed in red in the manual (the **add or replace atom** control). In the **Select your atom** periodic table pick **O**, click in the drawing area, and pull down to get a second oxygen.",
        why="Only the modelling differs from methane: you place two atoms yourself instead of taking a fragment.",
        evidence=_num("x1_e", "How many atoms are in the drawing area now?", 2.0,
                      hint="Oxygen gas is O2.",
                      reveal="O2 has two oxygen atoms."),
        check=_num("x1_c", "How many electrons does O2 have in total?", 16.0,
                   hint="Each oxygen atom has 8.",
                   reveal="8 electrons per oxygen atom, so 16 in total."),
        stuck="Cannot find the icon? Hover over the left toolbar icons for tooltips: it is the one that opens a periodic table.",
        ack="O2 built.",
    ),
    WalkStep(
        id="x2_save", chapter="oxygen", title="Save O2",
        do="Right-click, **Save as**, **Gabedit file**, under a name that is clearly different from methane's.",
        why="A different name keeps the two molecules' files apart and stops you feeding the methane geometry to the oxygen calculation by mistake.",
        evidence=_seen("x2_e", "Which name did you save it under?", hint="Just the file name."),
        stuck="Save as missing? Right-click on empty space in the drawing area.",
        ack="O2 saved.",
    ),
    WalkStep(
        id="x3_electrons", chapter="oxygen", title="Open O2 in the Orca dialog",
        do="Close the drawing window, open the O2 file in the main window, and click the **ORCA** icon. Read the **Number of electrons** line.",
        why="If the dialog still shows methane's electron count, you have the wrong file loaded. The dialog fills the count in from the atoms in the loaded geometry.",
        prereq="This needs the O2 file you just saved, not the methane one.",
        evidence=_num("x3_e", "What does **Number of electrons** show?", 16.0,
                      hint="If it says 10, you are looking at methane.",
                      reveal="It should read 16. If it says 10 the methane file is still loaded."),
        stuck="Showing 10? The methane file is still loaded. Open the O2 file and click ORCA again.",
        ack="Sixteen electrons for O2.",
    ),
    WalkStep(
        id="x4_spin", chapter="oxygen", title="Charge, spin and SCF type for O2",
        do="Keep **Charge** at 0. Now decide the **Spin multiplicity** yourself. If the dialog offers an unrestricted **SCF Type**, choose it. The manual does not say what to enter for oxygen, so confirm your choice with your demonstrator.",
        why="Ground-state O2 has two unpaired electrons with parallel spins, which is a triplet (multiplicity 3). A restricted setting pairs every electron, so it cannot describe those two.",
        evidence=_num("x4_e", "How many unpaired electrons does ground-state O2 have?", 2.0,
                      hint="Its two highest electrons occupy two different antibonding pi orbitals, one each.",
                      reveal="Two: they sit alone in two degenerate antibonding pi orbitals with parallel spins."),
        check=_mcq("x4_c", "So which multiplicity does that give (2S+1)?", "c",
                   _c("a", "1", "That would mean no unpaired electrons."),
                   _c("b", "2", "That is one unpaired electron."),
                   _c("c", "3", "S = 1 (two parallel spins of one half each), so 2S+1 = 3."),
                   hint="S is half the number of unpaired electrons.",
                   reveal="Two unpaired electrons give S = 1, so multiplicity 2S+1 = 3, a triplet."),
        stuck="Confirm the multiplicity and SCF type with your demonstrator if the manual and the dialog disagree; tell me what the dialog offers.",
        ack="Triplet, and unrestricted where the dialog offers it.",
    ),
    WalkStep(
        id="x5_opt", chapter="oxygen", title="Optimise O2",
        do="Set the **Job Type**, method and basis exactly as for methane (**Equilibrium structure search**, hybrid functional, B3LYP, 6-31G), run it under a new name, and confirm **ORCA terminated normally**. Then give me the first and last **FINAL SINGLE POINT ENERGY**.",
        why="Same procedure as methane, with the same checks: a clean termination and a last energy no higher than the first.",
        evidence=_report("x5_e", "Tell me the first energy, then the last one (in Eh).", "o2_e_first,o2_e_final",
                         hint="First cycle first, last cycle last."),
        stuck="Did not terminate normally? Compare the input echo with charge, multiplicity and method; paste what you see.",
        ack="O2 optimised.",
    ),
    WalkStep(
        id="x6_orbitals", chapter="oxygen", title="O2 orbitals",
        do="Run the **Single Point Energy** on the optimised O2 geometry under a new name, then read the **HOMO** and **LUMO** energies in Avogadro's **Orbitals** panel. Give me both.",
        why="An unrestricted run lists spin-up and spin-down orbitals separately, so read the HOMO and LUMO knowing which spin you are looking at; ask your demonstrator which to report.",
        evidence=_report("x6_e", "Tell me the HOMO energy, then the LUMO energy in eV.", "o2_homo,o2_lumo",
                         hint="Two numbers, HOMO first."),
        check=_mcq("x6_c", "Why do open-shell frontier orbitals need extra care?", "a",
                   _c("a", "Spin-up and spin-down electrons get separate orbitals, so there are two sets of energies", "Which set you report is worth confirming."),
                   _c("b", "Open-shell molecules have no HOMO", "They do have one."),
                   _c("c", "The basis set cannot be used", "The basis set works the same way."),
                   hint="Recall what unrestricted means.",
                   reveal="In an unrestricted calculation spin-up and spin-down electrons have their own orbitals, so the frontier energies exist for each spin."),
        stuck="Tell me what the Orbitals panel lists for O2.",
        ack="O2 orbital energies recorded.",
    ),
)

_TABLES = (
    WalkStep(
        id="t1_set", chapter="tables", title="Set method and basis",
        do="Table run {run_no} of {run_total}, {molecule}. Open its optimised geometry, click **ORCA**, set **Type of method** to **hybrid functional**, **Method** to **{method}** and **Basis** to **{basis}**, then **OK**.",
        why="Each table row is one method and basis pairing on the same molecule. Changing one thing at a time is what lets you see its effect.",
        evidence=_short("t1_e", "Read me the **Method** and **Basis** in the dialog.", (r"\bb3lyp\b|\bb3p\b",), (r"6-31g",), need=2,
                        hint="Two fields: Method and Basis."),
        stuck="Method not in the list? Change Type of method to hybrid functional first.",
        ack="Set.",
    ),
    WalkStep(
        id="t2_run", chapter="tables", title="Run and confirm",
        do="Run it under a **new** name, then check the end of the output for **ORCA terminated normally**.",
        why="Every run needs its own name and its own clean-finish check, because a table row built from a failed run is worthless.",
        evidence=_short("t2_e", "Paste the completion line, or tell me it is missing.", (r"terminated normally",), (r"missing|not there|no such|absent|cannot|can.?t",), need=1,
                        hint="It is near the end of the output, with stars."),
        stuck="Did not finish cleanly? Check the input echo for method, basis, charge and multiplicity, and paste it.",
        ack="Clean run.",
    ),
    WalkStep(
        id="t3_orbitals", chapter="tables", title="HOMO and LUMO",
        do="Open the output in Avogadro and read the **HOMO** and **LUMO** energies from the **Orbitals** panel. Give me both, HOMO first.",
        why="These are the values that go into the HOMO/LUMO columns of Table 1 (CH4) and Table 2 (O2).",
        evidence=_report("t3_e", "Tell me the HOMO energy, then the LUMO energy in eV.", "homo,lumo", hint="Two numbers, HOMO first."),
        stuck="Panel shows nothing? Reopen the output in Avogadro and try again.",
        ack="Recorded.",
    ),
    WalkStep(
        id="t4_shells", chapter="tables", title="s, p, d and f electrons",
        do="From the orbital-contribution data in the output, note the electrons in the **s**, **p**, **d** and **f** orbitals for every atom in this row. Add them all up and give me the total.",
        why="Electrons cannot appear or disappear: added up over all atoms and shells, they must equal the molecule's electron count ({n_elec}). Plain 6-31G has no d functions, so a d of zero there is correct.",
        evidence=_report("t4_e", "What do all the s, p, d and f figures add up to?", "shells_total",
                         hint="Add every atom's s, p, d and f entries together."),
        stuck="Not sure which block to read? The manual does not say which column; ask your demonstrator, and tell me what you are looking at.",
        ack="Row complete.",
    ),
)

_ALL_STEPS = _BUILD + _SETUP + _RUN + _READ + _ORBITALS + _OXYGEN + _TABLES

# ---------------------------------------------------------------- chapters

_CHAPTERS = (
    Chapter(
        id="build", title="Build methane in Gabedit",
        hook="Before we open anything: methane is CH4, five atoms. If you had to arrange them in 3D so the four hydrogens stay as far from each other as possible, what shape would you expect? Just take a guess.",
        hook_ack="Good, hold on to that guess: Gabedit will show us the real shape in a minute.",
        step_ids=("b1_open", "b2_draw", "b3_methane", "b4_save"),
        recall=(
            _q("qb_r1", "Which program actually performs the calculation?", "b",
               _c("a", "Gabedit", "Gabedit draws and prepares the input."),
               _c("b", "ORCA", "ORCA reads the input and does the numerical work."),
               _c("c", "Avogadro", "Avogadro displays the finished result.")),
            _q("qb_r2", "Why do we save methane as a Gabedit file?", "a",
               _c("a", "It is the format the main window opens next", "The other formats are for other programs."),
               _c("b", "ORCA can only read that format", "ORCA reads its own input, which Gabedit writes for you."),
               _c("c", "It compresses the molecule", "Format choice is not about size.")),
        ),
        preview=(
            _q("qb_p1", "ORCA's dialog shows a line called Number of electrons. Where do you think that number comes from?", "c",
               _c("a", "You must type it in", "Nobody types it."),
               _c("b", "It is always 10", "It changes with the molecule."),
               _c("c", "It is worked out from the atoms in the loaded geometry and the charge", "Which is why it is a good check."),
               teaser_step="o2_orca_dialog", teaser="You will read that line in the next chapter."),
        ),
    ),
    Chapter(
        id="setup", title="Set up the ORCA input",
        hook="ORCA is going to ask about the number of electrons and about spin. Do you think you have to type the electron count in yourself, or can the program work it out from the atoms? Have a guess.",
        hook_ack="Thanks. The dialog will settle it in the very next step.",
        step_ids=("o1_open_file", "o2_orca_dialog", "o3_job_scf", "o4_method_basis", "o5_check_input"),
        recall=(
            _q("qs_r1", "Why is a restricted SCF fine for methane?", "a",
               _c("a", "All its electrons are paired", "Closed-shell, so restricted describes it well."),
               _c("b", "It is neutral", "Charge alone does not decide it."),
               _c("c", "It has few atoms", "Size is not the reason.")),
            _q("qs_r2", "A bigger basis set gives the orbitals...", "b",
               _c("a", "More electrons", "The electron count does not change."),
               _c("b", "More freedom to take their shape", "More building-block functions."),
               _c("c", "A different molecule", "The molecule is the same.")),
        ),
        preview=(
            _q("qs_p1", "An optimisation moves the atoms cycle by cycle. By the end, the energy compared with the start is...", "b",
               _c("a", "Higher", "It would not stop at a worse geometry."),
               _c("b", "Lower or equal", "The optimiser only walks downhill."),
               _c("c", "Unrelated to the start", "It is directly related: each cycle improves on the last."),
               teaser_step="r3_energies", teaser="You will check this against your own two energies."),
        ),
    ),
    Chapter(
        id="run", title="Run the optimisation",
        hook="The optimiser moves the atoms a little, recomputes the energy, and repeats. By the time it stops, do you expect the last energy to be lower than, equal to, or higher than the first? Guess first; we will read the real numbers.",
        hook_ack="Good, you have committed to a prediction. Keep it in mind, we will compare it with your actual output.",
        step_ids=("r1_run", "r2_completion", "r3_energies"),
        recall=(
            _q("qr_r1", "What tells you a run finished properly?", "a",
               _c("a", "A message near the end that ORCA terminated normally", "The job completion message."),
               _c("b", "The output file is not empty", "A failed run also leaves text."),
               _c("c", "It finished quickly", "Speed says nothing about success.")),
            _q("qr_r2", "What does a single-point calculation do to the atoms?", "b",
               _c("a", "Moves them to lower the energy", "That is an optimisation."),
               _c("b", "Nothing: it computes energy and orbitals at the geometry you give it", "Fixed geometry."),
               _c("c", "Deletes them", "No.")),
        ),
        preview=(
            _q("qr_p1", "The optimisation is done. Why run a second job, a single point, on the optimised geometry?", "c",
               _c("a", "To move the atoms further", "A single point moves nothing."),
               _c("b", "Because the first run had no energy", "It did have one."),
               _c("c", "To get energies and orbitals at exactly that relaxed geometry", "That is the point of it."),
               teaser_step="p2_single_point", teaser="You set that up in the next chapter."),
        ),
    ),
    Chapter(
        id="read", title="Single point and orbital energies",
        hook="The next run is a single point: no atoms move. So why run ORCA a second time on the optimised geometry, instead of just reading the orbitals from the first run? Guess.",
        hook_ack="Nice, let us see whether the steps back that up.",
        step_ids=("p1_open_opt", "p2_single_point", "p3_run_sp", "p4_orbital_table", "p5_homo_lumo"),
        recall=(
            _q("qp_r1", "In a restricted run, which row is the HOMO?", "b",
               _c("a", "The first row", "That is a deep core orbital."),
               _c("b", "The last row with OCC 2", "The highest occupied orbital."),
               _c("c", "The row with the biggest number", "That is high in the empty orbitals.")),
            _q("qp_r2", "How many orbitals are occupied in methane (10 electrons, restricted)?", "a",
               _c("a", "5", "Two electrons per orbital."),
               _c("b", "10", "That counts electrons, not orbitals."),
               _c("c", "2", "Too few.")),
            _q("qp_r3", "Why run the single point under a different file name?", "b",
               _c("a", "ORCA forbids repeats", "It allows them."),
               _c("b", "The same name would overwrite the earlier output", "So you would lose it."),
               _c("c", "It makes it faster", "No effect on speed.")),
        ),
        preview=(
            _q("qp_p1", "Avogadro will draw the HOMO in two colours. What do you think they show?", "b",
               _c("a", "Positive and negative charge", "Not charges."),
               _c("b", "The two signs of the orbital's wave function", "They are phases."),
               _c("c", "Two different orbitals", "It is one orbital."),
               teaser_step="v3_render_homo", teaser="You will see the two colours yourself in the next chapter."),
        ),
    ),
    Chapter(
        id="orbitals", title="See the orbitals in Avogadro",
        hook="ORCA gave you orbital energies as a table of numbers. What can a picture of the HOMO tell you that the number cannot?",
        hook_ack="Good thinking, we will see the picture in a moment.",
        step_ids=("v1_avogadro", "v2_panel", "v3_render_homo", "v4_lumo"),
        recall=(
            _q("qv_r1", "The red and blue lobes of an orbital are...", "c",
               _c("a", "Positive and negative charge", "Not charges."),
               _c("b", "The HOMO and the LUMO", "One orbital at a time."),
               _c("c", "The two signs of the wave function", "Their phase.")),
            _q("qv_r2", "A positive LUMO in eV usually means...", "b",
               _c("a", "The run failed", "Not necessarily."),
               _c("b", "The empty orbital is pushed up by a small basis set", "Common with small basis sets."),
               _c("c", "The molecule is unstable", "It says nothing about that.")),
        ),
        preview=(
            _q("qv_p1", "Ground-state oxygen has how many unpaired electrons?", "c",
               _c("a", "0", "That is methane's case."),
               _c("b", "1", "That is a doublet."),
               _c("c", "2", "In two degenerate antibonding pi orbitals."),
               teaser_step="x4_spin", teaser="You will use this to choose the multiplicity."),
        ),
    ),
    Chapter(
        id="oxygen", title="Oxygen",
        hook="Oxygen is O2. Are its electrons all paired up like methane's? And if they are not, what do you think that does to how you set up the calculation?",
        hook_ack="Keep that in mind; the setup step will make it concrete.",
        step_ids=("x1_build", "x2_save", "x3_electrons", "x4_spin", "x5_opt", "x6_orbitals"),
        recall=(
            _q("qx_r1", "How many electrons does O2 have?", "b",
               _c("a", "8", "That is one atom."),
               _c("b", "16", "Two atoms of 8."),
               _c("c", "32", "Too many.")),
            _q("qx_r2", "What multiplicity describes ground-state O2?", "c",
               _c("a", "1", "That needs no unpaired electrons."),
               _c("b", "2", "One unpaired electron."),
               _c("c", "3", "Two parallel unpaired electrons.")),
        ),
        preview=(
            _q("qx_p1", "You will run 12 combinations in all. Which do you think changes a molecule's HOMO more?", "c",
               _c("a", "Changing B3LYP to B3P, always", "You cannot know without the data."),
               _c("b", "Changing 6-31G to 6-31G**, always", "You cannot know without the data."),
               _c("c", "It depends; your own table will tell you", "The data decides."),
               teaser_step="t3_orbitals", teaser="Your table will show it."),
        ),
    ),
    Chapter(
        id="tables", title="Fill Tables 1 and 2",
        hook="You are about to change the method and the basis set twelve times in all. Which do you think moves the HOMO more: switching B3LYP to B3P, or switching the basis from 6-31G to 6-31G**? Pick one, and we will see if your own data agrees.",
        hook_ack="Good, keep it in mind. Your table will decide.",
        step_ids=("t1_set", "t2_run", "t3_orbitals", "t4_shells"),
        recall=(
            _q("qt_r1", "Why can a d electron count of zero be correct with plain 6-31G?", "a",
               _c("a", "That basis has no d functions", "Polarisation functions come with the star."),
               _c("b", "Carbon has no electrons", "It does."),
               _c("c", "The run failed", "Not necessarily.")),
            _q("qt_r2", "The s, p, d, f electrons added over all atoms should equal...", "b",
               _c("a", "The number of atoms", "Not that."),
               _c("b", "The molecule's electron count", "Electrons are conserved."),
               _c("c", "Zero", "No.")),
            _q("qt_r3", "A star on a basis set (6-31G*) adds...", "c",
               _c("a", "Electrons", "It changes functions, not electrons."),
               _c("b", "Another atom", "No."),
               _c("c", "Polarisation functions on heavy atoms", "d functions on C or O.")),
        ),
        preview=(
            _q("qt_p1", "Two stars (6-31G**) add polarisation functions to...", "b",
               _c("a", "Only the carbon", "Not just heavy atoms."),
               _c("b", "The heavy atoms and the hydrogens", "p functions on hydrogen as well."),
               _c("c", "Nothing", "They add functions."),
               teaser_step="t4_shells", teaser="Watch how the d and p columns change as the basis grows."),
            _q("qt_p2", "Which matters more for a table row: a clean termination or a fast run?", "a",
               _c("a", "A clean termination", "A failed run's numbers are not trustworthy."),
               _c("b", "A fast run", "Speed is irrelevant to correctness."),
               _c("c", "Neither", "The completion message matters a lot."),
               teaser_step="t2_run", teaser="You check that on every row."),
        ),
    ),
)

# One row per combination, methane first then oxygen: (molecule, method, basis).
COMBOS: tuple[tuple[str, str, str], ...] = tuple(
    (mol, method, basis)
    for mol in ("ch4", "o2")
    for method in ("B3LYP", "B3P")
    for basis in ("6-31G", "6-31G*", "6-31G**")
)
ELECTRONS = {"ch4": 10, "o2": 16}
MOLECULE_NAMES = {"ch4": "methane", "o2": "oxygen"}


def _build() -> Script:
    steps = _ALL_STEPS
    return Script(
        experiment_id="exp07",
        title="Gabedit, ORCA and Avogadro",
        chapters=_CHAPTERS,
        steps=steps,
        by_id={s.id: s for s in steps},
    )


SCRIPT: Script = _build()
LINEAR_STEP_IDS: tuple[str, ...] = tuple(s.id for s in SCRIPT.steps if s.chapter != "tables")
LOOP_STEP_IDS: tuple[str, ...] = tuple(s.id for s in SCRIPT.steps if s.chapter == "tables")
