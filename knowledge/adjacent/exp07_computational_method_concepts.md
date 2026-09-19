<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp07
topic: concepts behind the Gabedit/ORCA/Avogadro calculations
-->

# Why the Experiment 7 calculations are done the way they are

This is general computational-chemistry background, not the manual's
procedure. It answers "why" and "what does this mean" questions the
manual does not. It gives no menu paths, no input-file syntax and no
numerical results; those come only from the student's own runs and the
manual.

## What Gabedit, ORCA and Avogadro are

The three programs do different jobs. Gabedit is a graphical interface
for computational chemistry: it is used to draw molecules, save them,
and prepare and launch input files for calculation programs such as
ORCA. ORCA is a quantum chemistry program package. It reads an input
file describing the molecule, the method and the basis set, then
performs the calculation (for example a geometry optimization or a
single-point energy) using methods that include density functional
theory, and writes the results to an output file. It does the heavy
numerical work but has no drawing interface of its own, which is why
Gabedit prepares its input. Avogadro is a molecular editor and
visualizer: it reads the finished output and displays the molecule and
its molecular orbitals, so the HOMO and LUMO can be looked at as well
as listed as numbers. In short, Gabedit builds and sets up, ORCA
calculates, and Avogadro shows the result.

## Why the geometry is optimized before the orbital calculation

Orbital energies depend strongly on the positions of the nuclei. A
structure drawn by hand has approximate bond lengths and angles, so it
is not the arrangement the molecule actually prefers. A geometry
optimization moves the atoms until the total energy stops decreasing,
which finds the relaxed (lowest-energy) structure for the chosen method
and basis set. Running the orbital (single-point) calculation on that
optimized geometry means the HOMO, LUMO and orbital contributions
describe the relaxed molecule rather than an arbitrary sketch. This is
also why the optimized file, not the drawn one, is used for the second
calculation. Optimization normally lowers the energy compared with the
starting structure; if it does not, something is wrong with the run.

## Simple sanity checks on a finished run

Two quick physical checks help catch a bad run, and neither needs a
reference value. First, for one and the same run the LUMO energy must
lie above the HOMO energy, because the LUMO is by definition the next
orbital up. Second, after a geometry optimization the final energy
should be equal to or lower than the energy of the starting structure,
since the optimizer only accepts steps that do not raise the energy. A
run that fails either check, or that shows no job completion message,
should be repeated or reported rather than written up.

## What "orbital contribution" tells you

A molecular orbital is built from atomic orbitals. The orbital
contribution says how much each atom's s, p, d or f atomic orbitals
take part in a given molecular orbital, in terms of electron population
per atom. It shows which atoms and which kinds of orbital an MO is
really made of. For example, an occupied orbital of methane that
contains mostly carbon p character and hydrogen s character shows the
carbon-hydrogen bonding, while d and f contributions are expected to be
very small for these light atoms.

## Density functional theory versus Hartree-Fock

Hartree-Fock treats each electron as moving in the average field of the
others and leaves out electron correlation, the way electrons avoid one
another instantaneously. Density functional theory (DFT) describes the
electrons through their density and includes correlation approximately,
through the chosen functional. For molecules like methane and oxygen,
DFT usually gives more reliable energies and geometries than plain
Hartree-Fock at a similar computational cost, which is why it is the
usual choice for this kind of exercise. The price is that the result
depends on the functional, which is an approximation.

## What a hybrid functional is

A hybrid functional mixes a fraction of the exact exchange that
Hartree-Fock calculates with exchange and correlation from a pure DFT
functional. B3LYP and B3P are both hybrids of Becke's three-parameter
type; they differ in the correlation part of the functional (LYP for
B3LYP, a Perdew-type correlation for B3P), so they give slightly
different energies for the same molecule and basis set. Comparing them
in the tables shows how much the functional choice matters.

## What the basis set is, and 6-31G versus 6-31G* versus 6-31G**

A basis set is the set of mathematical functions used to build the
molecular orbitals. More flexible functions describe the orbitals
better but cost more time. In the Pople family, 6-31G is a split-valence
basis: core orbitals use one function and valence orbitals use two
sizes, so valence electrons can spread or contract. 6-31G* adds
polarization functions (d-type) to the heavy, non-hydrogen atoms, which
lets orbitals distort away from a purely spherical shape. 6-31G** adds
polarization functions to hydrogen atoms as well (p-type). Each step
adds flexibility, and orbital energies typically shift a little as the
basis set improves.

## Why oxygen is a triplet and why it matters for the calculation

The ground state of the oxygen molecule has two unpaired electrons in a
pair of degenerate antibonding pi orbitals, with parallel spins. Spin
multiplicity is 2S+1, where S is the total spin, so two parallel
unpaired electrons give multiplicity 3, a triplet. Methane, by
contrast, has all electrons paired and is a singlet. The multiplicity
tells the program which electronic state to calculate: describing
oxygen as a singlet would target a different, higher-energy state and
give misleading energies and orbitals. A molecule with unpaired
electrons is an open-shell system, and its spin-up and spin-down
electrons occupy slightly different orbitals, so the frontier orbitals
are reported separately for each spin and the HOMO and LUMO must be
read with that in mind. The manual does not say which multiplicity
value to enter, so this is a point to confirm with the instructor.

## Why the HOMO-LUMO gap is different for methane and oxygen

Methane is a closed-shell molecule whose highest occupied orbitals are
strongly bonding, and its lowest unoccupied orbital is far above them,
so its gap is large. Oxygen is open-shell, with singly occupied
antibonding orbitals near the top of the occupied set and empty
orbitals close by, so its frontier gap is much smaller. A large gap
generally goes with lower reactivity and absorption at shorter
wavelengths; a small gap goes with higher reactivity and easier
excitation. This is qualitative: the actual values come from the
student's own calculations.

## What a negative orbital energy means

Orbital energies are measured relative to an electron that has been
removed completely and is at rest, which is defined as zero. An
electron in a bound orbital is more stable than that, so its orbital
energy is negative. The more negative the energy, the more tightly the
electron is bound. The HOMO energy is roughly related to the energy
needed to remove an electron, which is why the HOMO of a molecule that
holds its electrons tightly is very negative. A LUMO energy that is also
negative means the molecule can hold an extra electron in that orbital
in this calculation.
