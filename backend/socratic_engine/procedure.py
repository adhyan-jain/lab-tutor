"""The practical procedure (Exp 7, 2, 4), as an opt-in overview and stepper.

Shown only when a student explicitly asks how the experiment is performed
(conversation.is_procedure_request) or taps "Practical / Experiment". Authored
text, no model call, and nothing the student is asked to go and do: the
practical is normally performed on a lab computer, and students may have only
a phone. It describes the workflow and what each stage is for.

After the overview, "next", "back", "repeat" and "step N" walk its six stages
one at a time (`navigate`, per experiment), from a position kept on the thread
(ConversationState.procedure_item). The position survives a question asked in
between, so "next" after a side question carries on from the same stage
instead of starting again or being answered by the model.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.socratic_engine.walkthrough.navigation import Nav, NavCommand

OVERVIEW_EXP07 = (
    "**How Experiment 7 is normally performed**\n\n"
    "On the lab computer, the practical goes through these stages. You do not need to do any of them here: "
    "this is only an overview, so you know what the workflow is and why each stage exists.\n\n"
    "1. **Build the molecule** (methane, then oxygen) in Gabedit and save the structure.\n"
    "2. **Set up the calculation** in ORCA: the job type, the charge and spin, the method (DFT with a chosen "
    "functional) and the basis set.\n"
    "3. **Optimise the geometry** and check that the job finished normally, noting the first and last energies.\n"
    "4. **Run a single-point calculation** on the optimised structure to get the orbital energies, including the "
    "HOMO and LUMO.\n"
    "5. **Visualise the HOMO and LUMO** in Avogadro.\n"
    "6. **Repeat** for oxygen and for the other methods and basis sets, recording the orbital energies and the "
    "s, p, d and f contributions, then compare the results.\n\n"
    "With only your phone and this page we cannot run any of these stages, so the most useful thing to do here is "
    'to understand the ideas behind each one. Say "next" to go through the stages one at a time, name one '
    '(for example "stage 3"), or pick one of these.'
)


@dataclass(frozen=True)
class Stage:
    title: str
    what: str
    why: str


#: One entry per numbered line of OVERVIEW_EXP07, in the same order.
STAGES_EXP07: tuple[Stage, ...] = (
    Stage(
        "Build the molecule",
        "In the lab, the molecule is drawn atom by atom in Gabedit (methane first: one carbon and four hydrogens), "
        "given a sensible starting shape, and saved as a structure file the calculation can read.",
        "A calculation needs a starting arrangement of atoms. It does not have to be perfect, because the "
        "optimisation stage will improve it, but it must be the right molecule with the right connections.",
    ),
    Stage(
        "Set up the calculation",
        "The structure is opened in ORCA's input set-up, where the job type is chosen, the charge and spin "
        "multiplicity are set, and a method (a DFT functional such as B3LYP) and a basis set are picked.",
        "These choices decide what is being calculated and how approximately. Charge and spin describe the "
        "molecule's electrons; the method and basis set trade accuracy against computing time.",
    ),
    Stage(
        "Optimise the geometry",
        "The calculation moves the atoms step by step towards the arrangement with the lowest energy, and the "
        "output is checked to confirm the job finished normally. The first and last energies are noted.",
        "Orbital energies only mean something for a sensible, stable structure. The energy should go down during "
        "an optimisation; if it went up, something in the set-up was wrong.",
    ),
    Stage(
        "Run a single-point calculation",
        "With the optimised structure fixed, one more calculation is run without moving the atoms, and its "
        "output lists every molecular orbital with its energy and whether it is occupied.",
        "This is where the HOMO (highest occupied) and LUMO (lowest unoccupied) orbitals and their energies come "
        "from. The LUMO must lie above the HOMO.",
    ),
    Stage(
        "Visualise the HOMO and LUMO",
        "The results are opened in Avogadro, which draws the HOMO and LUMO as surfaces around the molecule.",
        "Seeing where the electron density of these two orbitals sits helps explain where a molecule is likely to "
        "give or accept electrons, which is what the HOMO-LUMO gap is about.",
    ),
    Stage(
        "Repeat and compare",
        "The same stages are repeated for oxygen and for each combination of method and basis set, recording the "
        "orbital energies and the s, p, d and f contributions in tables, then comparing them.",
        "Comparing results shows how much the answer depends on the choices made at set-up, and how methane "
        "(all electrons paired) differs from oxygen (two unpaired electrons).",
    ),
)


_OVERVIEW_INTRO = (
    "**How {label} is normally performed**\n\n"
    "In the lab, the practical goes through these stages. You do not need to do any of them here: "
    "this is only an overview, so you know what the workflow is and why each stage exists.\n\n"
)
_OVERVIEW_OUTRO = (
    "\n\nWith only your phone and this page we cannot do any of these stages, so the most useful thing to do "
    'here is to understand the ideas behind each one. Say "next" to go through the stages one at a time, name '
    'one (for example "stage 3"), or pick one of these.'
)


def _build_overview(label: str, lines: tuple[str, ...]) -> str:
    body = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    return _OVERVIEW_INTRO.format(label=label) + body + _OVERVIEW_OUTRO


STAGES_EXP02: tuple[Stage, ...] = (
    Stage(
        "Start the reaction",
        "Ethyl acetate is mixed with a dilute acid, which acts as the catalyst, and a timer is started at the "
        "moment of mixing. The mixture is kept at a steady temperature.",
        "The rate of the hydrolysis depends on temperature and on the acid concentration, so both are held "
        "fixed. Time zero must be marked, because every later reading is a time measured from it.",
    ),
    Stage(
        "Take samples at fixed times",
        "At chosen intervals a fixed volume of the reaction mixture is withdrawn with a pipette and run into "
        "ice-cold water.",
        "The cold water slows the reaction almost to a stop, so the sample still holds the composition it had "
        "at the instant it was taken, even though it is titrated a little later.",
    ),
    Stage(
        "Titrate each sample with alkali",
        "Each quenched sample is titrated against standard sodium hydroxide. The volume needed is recorded "
        "against the time the sample was taken.",
        "The acid catalyst is present from the start, but the reaction also makes acetic acid. The extra alkali "
        "needed as time passes tells you how much acetic acid, and so how much ester has reacted.",
    ),
    Stage(
        "Find the reading at completion",
        "A portion of the mixture is allowed to react to completion and titrated in the same way, giving the "
        "final volume, V-infinity. The reading at time zero is V-zero.",
        "V-infinity corresponds to all the ester having reacted, so the difference between it and any later "
        "reading measures how much ester is still left.",
    ),
    Stage(
        "Tabulate and plot",
        "From the readings the quantity V-infinity minus Vt is worked out for each time, and its logarithm is "
        "plotted against time.",
        "Because water is in large excess, the reaction behaves as first order in the ester (pseudo-first-order), "
        "so this plot should be a straight line.",
    ),
    Stage(
        "Get the rate constant",
        "The slope of the straight line is read off and multiplied by 2.303 (the sign is taken so the rate "
        "constant comes out positive), giving k in reciprocal minutes.",
        "The rate constant is the single number that sums up how fast the reaction goes under these conditions; "
        "a poor straight-line fit is a sign of a timing or reading error.",
    ),
)
OVERVIEW_EXP02 = _build_overview(
    "Experiment 2",
    (
        "**Start the reaction**: mix ethyl acetate with dilute acid and start the timer.",
        "**Take samples at fixed times** and quench each in ice-cold water.",
        "**Titrate each sample** with standard sodium hydroxide and record the volume.",
        "**Find the reading at completion** (V-infinity) and the reading at time zero.",
        "**Tabulate and plot** the logarithm of (V-infinity minus Vt) against time.",
        "**Get the rate constant** from the slope.",
    ),
)

STAGES_EXP03: tuple[Stage, ...] = (
    Stage(
        "Make the standards",
        "Five 50 mL flasks are set out. 1, 2, 3 and 4 mL of the 100 ppm nickel stock, run from a burette, go into "
        "four of them to give standards of 2, 4, 6 and 8 ppm. The fifth flask is the unknown, which is handed out "
        "ready-made.",
        "Different volumes of one stock in flasks of the same size give an evenly spaced series of known "
        "concentrations, which the calibration line is built from.",
    ),
    Stage(
        "Develop the colour",
        "0.5 mL of DMG solution and then 0.5 mL of potassium ferricyanide are added to all five flasks, which are "
        "shaken once and left for 5 minutes. Each flask is then made up to the 50 mL mark with 1 N sodium "
        "hydroxide and left for at least 10 minutes.",
        "DMG makes the pink Ni(dmg)2 complex, and the ferricyanide oxidises it to the soluble brown-red complex "
        "that is measured. The sodium hydroxide gives the alkaline medium, and the waiting gives the complex time "
        "to form completely.",
    ),
    Stage(
        "Measure the absorbance",
        "The absorbance of each brown-red solution is read at 440 nm against the sodium hydroxide solution, which "
        "is the blank, and noted in a table.",
        "440 nm is where the oxidised complex absorbs most, and measuring against the blank leaves only the "
        "nickel's contribution in each reading.",
    ),
    Stage(
        "Plot the calibration line",
        "Absorbance is plotted against concentration for the standards.",
        "If Beer's law holds, the points fall on a straight line through, or very near, the origin.",
    ),
    Stage(
        "Read the unknown",
        "The unknown's absorbance is located on the line, and its concentration is read from it.",
        "The unknown was treated like the standards, so the line turns its reading into ppm. It has to fall "
        "inside the range of the standards.",
    ),
    Stage(
        "Repeat with a phone camera",
        "The standards, the unknown and the blank are lined up and photographed together against white paper, "
        "holding the camera about 50 cm away. Their RGB values are read with the RGB Tool app, and the RGB "
        "response is plotted against concentration for a second calibration line.",
        "A phone is a cheap stand-in for the instrument but less precise, so the lighting, background and "
        "distance are kept the same for every tube.",
    ),
)
OVERVIEW_EXP03 = _build_overview(
    "Experiment 3",
    (
        "**Make the standards**: put 1, 2, 3 and 4 mL of the 100 ppm nickel stock into 50 mL flasks; the unknown is handed out ready-made.",
        "**Develop the colour**: add DMG, then ferricyanide, wait, make up to the mark with sodium hydroxide and wait again.",
        "**Measure the absorbance** of each solution at 440 nm against the sodium hydroxide blank.",
        "**Plot the calibration line** of absorbance against concentration.",
        "**Read the unknown** from the line.",
        "**Repeat with a phone camera**, photographing the samples together against white paper.",
    ),
)

STAGES_EXP04: tuple[Stage, ...] = (
    Stage(
        "Prepare the iron solution",
        "A weighed piece of carbon steel is dissolved in acid, which brings the iron into solution as iron(II), "
        "and the solution is made up to a known volume. A fixed portion of it is used for each titration.",
        "The titration can only measure iron that is in solution and in the iron(II) state, so the dissolving "
        "step decides what is being measured.",
    ),
    Stage(
        "Set up the electrodes",
        "An inert indicator electrode and a reference electrode are placed in the solution and connected to a "
        "potential-measuring meter. The solution is stirred, and potassium permanganate of known normality "
        "fills the burette.",
        "The meter reports the EMF between the two electrodes. The reference electrode stays fixed, so any "
        "change in the reading comes from the iron(III) to iron(II) ratio at the indicator electrode.",
    ),
    Stage(
        "Add titrant and record the EMF",
        "Permanganate is added in portions and the EMF is read after each. Portions are made smaller near the "
        "point where the reading starts to jump.",
        "Most of the information is in the few readings around the jump; large portions there would leave "
        "no reading close enough to the equivalence point to locate it.",
    ),
    Stage(
        "Locate the endpoint",
        "The EMF is plotted against the volume to give an S-shaped curve. For each pair of readings the change "
        "in EMF divided by the change in volume is plotted against the average volume, and the sharp maximum "
        "gives the endpoint volume.",
        "The steepest part of the S-curve is where one drop of titrant changes the iron(III) to iron(II) ratio "
        "the most, which is the equivalence point.",
    ),
    Stage(
        "Calculate the iron content",
        "The normality of the steel solution comes from the endpoint volume, the permanganate normality and the "
        "volume of solution titrated. It is then converted to grams of iron per 100 mL using the equivalent "
        "weight of iron.",
        "This turns a volume read off a graph into the quantity the experiment is really after: how much iron "
        "the steel contains.",
    ),
    Stage(
        "Repeat and check",
        "A second titration is recorded in the same way, and the two results are compared.",
        "Agreement between repeats shows the result is reproducible and not the effect of a single misread "
        "volume or a drifting electrode.",
    ),
)
OVERVIEW_EXP04 = _build_overview(
    "Experiment 4",
    (
        "**Prepare the iron solution** by dissolving a piece of carbon steel in acid.",
        "**Set up the electrodes** and fill the burette with potassium permanganate.",
        "**Add titrant in portions** and record the EMF after each one.",
        "**Locate the endpoint** from the S-curve and its derivative plot.",
        "**Calculate the iron content** from the endpoint volume.",
        "**Repeat and check** that the results agree.",
    ),
)

# Public Exp7 names kept as aliases for existing callers and tests.
OVERVIEW = OVERVIEW_EXP07
STAGES = STAGES_EXP07

#: experiment id -> (overview text, stages)
_CONTENT: dict[str, tuple[str, tuple[Stage, ...]]] = {
    "exp07": (OVERVIEW_EXP07, STAGES_EXP07),
    "exp02": (OVERVIEW_EXP02, STAGES_EXP02),
    "exp03": (OVERVIEW_EXP03, STAGES_EXP03),
    "exp04": (OVERVIEW_EXP04, STAGES_EXP04),
}


def stages_for(experiment_id: str = "exp07") -> tuple[Stage, ...]:
    return _CONTENT.get(experiment_id, _CONTENT["exp07"])[1]

#: Chip action ids (conversation.ACTIONS) offered under the overview.
CHIPS = ["next_step", "explain_theory", "guide_concepts"]


def overview(experiment_id: str = "exp07") -> str:
    return _CONTENT.get(experiment_id, _CONTENT["exp07"])[0]


def _stage_text(n: int, lead: str = "", experiment_id: str = "exp07") -> str:
    stages = stages_for(experiment_id)
    stage = stages[n - 1]
    body = (
        f"**Stage {n} of {len(stages)}: {stage.title}**\n\n{stage.what}\n\n"
        f"**Why it matters:** {stage.why}"
    )
    return f"{lead}\n\n{body}" if lead else body


def _stage_chips(n: int, experiment_id: str = "exp07") -> list[str]:
    chips = ["next_step"] if n < len(stages_for(experiment_id)) else []
    if n > 1:
        chips.append("prev_step")
    return chips + ["explain_theory", "guide_concepts"]


def navigate(current: int | None, cmd: NavCommand, experiment_id: str = "exp07") -> tuple[int, str, list[str]]:
    """Move through the overview's stages. `current` is 0 for the overview
    itself, 1-6 for a stage. Returns (new position, reply text, chip ids)."""
    total = len(stages_for(experiment_id))
    text = overview(experiment_id)
    pos = max(0, min(current or 0, total))
    if cmd.kind is Nav.REPEAT:
        if pos == 0:
            return 0, text, CHIPS
        return pos, _stage_text(pos, "Here it is again.", experiment_id), _stage_chips(pos, experiment_id)
    if cmd.kind is Nav.BACK:
        if pos <= 1:
            return 0, f"Here is the overview again.\n\n{text}", CHIPS
        return pos - 1, _stage_text(pos - 1, experiment_id=experiment_id), _stage_chips(pos - 1, experiment_id)
    if cmd.kind is Nav.NEXT:
        if pos >= total:
            return pos, (
                "That was the last stage. Would you like to understand the ideas behind any of them? "
                'Ask about one, say "stage 2" to look at a stage again, or let me guide you through the key ideas.'
            ), ["explain_theory", "guide_concepts"]
        return pos + 1, _stage_text(pos + 1, experiment_id=experiment_id), _stage_chips(pos + 1, experiment_id)
    n = cmd.target or 0
    if not 1 <= n <= total:
        chips = _stage_chips(pos, experiment_id) if pos else CHIPS
        return pos, f'The practical has {total} stages. Say a number from 1 to {total}, for example "stage 3".', chips
    return n, _stage_text(n, experiment_id=experiment_id), _stage_chips(n, experiment_id)
