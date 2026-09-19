<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp07
topic: definitions of the terms used in Experiment 7 and how to read a finished run
-->

# Experiment 7 terms explained: orbitals, HOMO/LUMO, spin and the output

This is general chemistry background written for LabTutor, not the
manual's procedure. It explains what the words in Experiment 7 mean and
how to make sense of a finished run. It contains no menu paths, no input
syntax and no numerical results; the values a student reports come only
from their own runs.

## Atomic orbitals: what s, p, d and f mean

An atomic orbital is the region around one nucleus where an electron is
likely to be found, and each has a shape. An s orbital is spherical. A p
orbital is dumbbell shaped and comes in three orientations (px, py, pz).
A d orbital has a cloverleaf shape and comes in five kinds, and an f
orbital has seven. Carbon in methane has electrons in 1s, 2s and 2p
orbitals; hydrogen only has a 1s. Tables 1 and 2 ask how many electrons
sit in each type (s, p, d, f) on each atom. Carbon and oxygen do not have
occupied d or f orbitals in their ground state, so any d or f population
that appears is a small side effect of the mathematics: the basis set
lets the orbitals bend into shapes that need d-type (or p-type on
hydrogen) functions. That is why a plain 6-31G basis, which has no such
polarization functions, cannot show any d population at all, while 6-31G*
(d functions on the heavy atoms) and 6-31G** (also p functions on
hydrogen) can, in small amounts.

## Molecular orbitals: bonding, antibonding and non-bonding

When atoms come together their atomic orbitals mix to form molecular
orbitals (MOs) that belong to the whole molecule. Mixing always produces
as many MOs as there were atomic orbitals. In-phase combinations pile
electron density between the nuclei and lie lower in energy: these are
bonding orbitals. Out-of-phase combinations have a node between the
nuclei and lie higher: antibonding orbitals, usually written with a star
(sigma*, pi*). An orbital that has almost no bonding or antibonding
effect is non-bonding. Sigma orbitals are symmetric around the bond axis;
pi orbitals have a nodal plane containing the bond axis. A molecule is
held together when more electrons occupy bonding orbitals than
antibonding ones.

## Occupied and virtual orbitals

Electrons fill MOs from the lowest energy upward, two per orbital with
opposite spins (the Pauli principle). The filled orbitals are the
occupied orbitals. The empty ones above them are called virtual or
unoccupied orbitals. A calculation prints all of them, which is why the
list of orbital energies in a program such as Avogadro runs well above
the occupied set. The occupied ones are labelled HOMO, HOMO-1, HOMO-2 and
so on downward; the empty ones LUMO, LUMO+1, LUMO+2 and so on upward.

## HOMO in detail

The HOMO is the Highest Occupied Molecular Orbital: the highest-energy
orbital that still contains electrons. Because it holds the most loosely
bound electrons, it is where a molecule is most willing to give electrons
away. That makes the HOMO the orbital that matters when the molecule acts
as an electron donor (a base or nucleophile), and its energy is roughly
related to how much energy it takes to remove an electron (the ionization
energy): a lower, more negative HOMO means the electrons are held more
tightly. The shape of the HOMO shows where on the molecule the donating
electron density sits. For methane the HOMO belongs to the C-H bonding
set, and because methane is tetrahedral, that highest bonding level is a
group of three orbitals with exactly the same energy (see degeneracy
below). For oxygen the highest occupied orbitals are the two
antibonding pi orbitals that hold its two unpaired electrons.

## LUMO in detail

The LUMO is the Lowest Unoccupied Molecular Orbital: the lowest-energy
orbital with no electrons in it. It is where an extra electron would go
first, so it matters when the molecule acts as an electron acceptor (an
acid or electrophile), and its energy is roughly related to the
molecule's electron affinity: a lower LUMO means electrons are added more
easily. Its shape shows where an incoming electron density would be
accepted. By definition the LUMO always lies above the HOMO of the same
run.

## The HOMO-LUMO gap

The gap is the LUMO energy minus the HOMO energy. It is a quick guide to
how easily a molecule can be excited or made to react. A large gap means
electrons must be lifted a long way, so the molecule is generally
unreactive and absorbs only high-energy (short-wavelength) light. A small
gap means easy excitation, more reactivity and absorption at longer
wavelengths. It is a qualitative indicator: the gap from a DFT
calculation is not the same thing as the measured optical gap, and it
depends on the functional and basis set, so compare gaps only between
runs made the same way.

## Degenerate orbitals

Orbitals with exactly the same energy are called degenerate. Symmetry
forces this: the three p orbitals of a free atom are degenerate, and in a
tetrahedral molecule like methane one set of three MOs is degenerate. When
the program lists such orbitals they show the same energy (to the printed
precision). This is normal and is not a sign of an error. If the HOMO is
degenerate, then "the HOMO" is one member of the set and all members
have the same energy.

## Energy units and sign

ORCA prints orbital energies in Hartree (Eh, also written Ha) and in
electronvolts (eV). One Hartree is about 27.2 eV. Avogadro's orbital list
is in eV. Bound electrons have negative orbital energies because zero is
defined as an electron completely removed and at rest; the more negative,
the more tightly bound. A negative energy is therefore normal, not a
warning.

## Orbital contribution and population

An orbital contribution says how much each atom's atomic orbitals (1s, 2s,
2p and so on) take part in a given molecular orbital. In the printed
orbital table each column is one MO and each row is one atomic orbital
on one atom; the number is that atomic orbital's coefficient in the MO. A
larger absolute value means a larger share, and the sign is the phase (the
in-phase or out-of-phase mixing described above). A population analysis
goes one step further and shares out the electrons among the atoms and
orbital types, which is what a table of "electrons in s, p, d and f" is
asking for. Different population schemes (Mulliken and Loewdin are common
ones) divide the electrons a little differently, so numbers from different
schemes are not directly comparable.

## Charge, spin and multiplicity

Charge is the net charge of the molecule (0 for neutral methane or
oxygen). Spin multiplicity is 2S+1, where S is half the number of
unpaired electrons: no unpaired electrons gives multiplicity 1 (a
singlet), one unpaired electron 2 (a doublet), two unpaired parallel
electrons 3 (a triplet). Methane has all electrons paired, so it is a
singlet. Ground-state oxygen has two unpaired electrons, so it is a
triplet. The multiplicity tells the program which electronic state to
calculate, and a molecule with unpaired electrons is called open shell,
while one with all electrons paired is closed shell. Open-shell
calculations treat spin-up and spin-down electrons separately, so the
frontier orbitals are reported for each spin.

## SCF and convergence

To find the orbitals, the program guesses them, works out the average
field every electron feels from all the others, solves for improved
orbitals in that field, and repeats. This loop is the self-consistent
field (SCF) procedure. It has converged when the energy and orbitals stop
changing between cycles. If the output says the SCF did not converge, the
orbitals and energies from that run cannot be trusted.

## Geometry optimization versus a single-point energy

A single-point calculation computes the energy and orbitals for one fixed
arrangement of the atoms. A geometry optimization moves the atoms
step by step, recomputing the energy and the forces (the energy
gradient), until the forces are essentially zero: the lowest-energy
arrangement for that method and basis set. The line printed at the end of
the output as the final single point energy is the total energy of the
last geometry, in Hartree; it is the number that should be equal to or
lower than the energy at the start of an optimization. An optimization is
done first so that the later orbital calculation describes the relaxed
molecule rather than a hand-drawn approximation.

## Ground state and excited states

The ground state has the electrons in the lowest possible orbitals. An
excited state has at least one electron promoted into a higher orbital.
An option such as "Excited states: Nothing" means the run only computes
the ground state, which is what Experiment 7 needs. The HOMO-LUMO gap is
a rough guide to how easily the first excitation happens.

## Hybrid orbitals and the molecular-orbital picture of methane

A carbon atom has one 2s and three 2p orbitals. To explain methane's four
identical C-H bonds at about 109.5 degrees, chemists mix them into four
equivalent sp3 hybrid orbitals, each pointing to a corner of a
tetrahedron and overlapping with one hydrogen 1s orbital. This is a
bonding model that gives a localised picture. The molecular orbitals a
calculation prints are spread over the whole molecule (one low-lying
carbon-2s-based orbital and a triply degenerate set built from carbon 2p
and the hydrogens), which is a different but equivalent description of the
same electrons. Both describe the same molecule; the printed orbitals
are the ones that carry the orbital energies.

## The files a run leaves behind

An ORCA run works on an input file (extension .inp) and writes a readable
output file (.out) that holds the energies, orbital table and the job
completion message. It also writes other files: a binary wavefunction
file (.gbw), density files, and a short properties text file. Only the
.out file is meant to be read by eye. Avogadro reads the .out file to show
the molecule and its orbitals.

## Common misunderstandings

A negative orbital energy does not mean an unstable molecule. A bigger
basis set does not change the molecule, only how well the calculation
describes it, so energies shift a little when the basis set changes. A
HOMO-LUMO gap from one functional cannot be compared with one from
another as if they were the same measurement. The HOMO energy is related
to, but is not identical to, the ionization energy. And a run that did
not finish (no job completion message, or an SCF that did not converge)
should be repeated before any numbers are written up.
