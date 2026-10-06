"""The Experiment 7 practical procedure, as an opt-in overview.

Shown only when a student explicitly asks how the experiment is performed
(conversation.is_procedure_request) or taps "Practical / Experiment". Authored
text, no model call, no step-by-step stepper, and nothing the student is asked
to go and do: the practical is normally performed on a lab computer, and
tomorrow's students have only a phone. It describes the workflow and what each
stage is for, then offers to explain the ideas instead.
"""

from __future__ import annotations

OVERVIEW = (
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
    "to understand the ideas behind each one. Which would you like to start with?"
)

#: Chip action ids (conversation.ACTIONS) offered under the overview.
CHIPS = ["explain_theory", "guide_concepts"]


def overview() -> str:
    return OVERVIEW
