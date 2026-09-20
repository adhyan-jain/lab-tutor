<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp07
topic: everything needed to understand Experiment 7 -- terms, concepts, why the calculations are done this way, how to read a run, and what generally goes wrong
-->

# Exp 7 background: orbitals, HOMO/LUMO, the methods, and reading a run

This is general chemistry and software background written for LabTutor,
not the manual's procedure. It explains what the words in Experiment 7
mean, why the calculations are done the way they are, how to make sense
of a finished run, and what commonly goes wrong. It contains no menu
paths, no input syntax and no numerical results; the values a student
reports come only from their own runs. If anything here ever seems to
disagree with the manual about what a step should look like, the manual
is the authority. The screen guides further down say what each control
or output section is; they are not a procedure, and each line says where
its information comes from.

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

A molecular orbital (MO) is a wavefunction describing where an electron
is likely to be found across an entire molecule. When atoms come
together their atomic orbitals mix to form MOs (the linear combination
of atomic orbitals, or LCAO, approach). Mixing always produces as many
MOs as there were atomic orbitals. In-phase combinations pile electron
density between the nuclei and lie lower in energy: these are bonding
orbitals. Out-of-phase combinations have a node between the nuclei and
lie higher: antibonding orbitals, usually written with a star (sigma*,
pi*). An orbital that has almost no bonding or antibonding effect is
non-bonding. Sigma orbitals are symmetric around the bond axis; pi
orbitals have a nodal plane containing the bond axis. A molecule is held
together when more electrons occupy bonding orbitals than antibonding
ones. Each MO has an energy, and filling the lowest-energy MOs first
with the molecule's electrons (two per orbital, opposite spin, the Pauli
principle) gives the ground state.

## Occupied and virtual orbitals

The filled orbitals are the occupied orbitals. The empty ones above them
are called virtual or unoccupied orbitals. A calculation prints all of
them, which is why the list of orbital energies in a program such as
Avogadro runs well above the occupied set. The occupied ones are
labelled HOMO, HOMO-1, HOMO-2 and so on downward; the empty ones LUMO,
LUMO+1, LUMO+2 and so on upward.

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
group of three orbitals with exactly the same energy (see degenerate
orbitals below). For oxygen the highest occupied orbitals are the two
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

Methane and oxygen differ here for a reason. Methane is a closed-shell
molecule whose highest occupied orbitals are strongly bonding, and its
lowest unoccupied orbital is far above them, so its gap is large. Oxygen
is open-shell, with singly occupied antibonding orbitals near the top of
the occupied set and empty orbitals close by, so its frontier gap is much
smaller. The actual values come from the student's own calculations.

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
is in eV. Orbital energies are measured relative to an electron that has
been removed completely and is at rest, which is defined as zero. An
electron in a bound orbital is more stable than that, so its orbital
energy is negative, and the more negative, the more tightly the electron
is bound. A negative energy is therefore normal, not a warning. The
occupied orbitals are almost always negative. A LUMO can be negative
(the molecule can hold an extra electron in that orbital in this
calculation) or slightly positive, particularly with a small basis set;
a small positive LUMO is not by itself a sign of a failed run.

## Charge, spin and multiplicity

Charge is the net charge of the molecule (0 for neutral methane or
oxygen). Spin multiplicity is 2S+1, where S is half the number of
unpaired electrons: no unpaired electrons gives multiplicity 1 (a
singlet), one unpaired electron 2 (a doublet), two unpaired parallel
electrons 3 (a triplet). Methane has all electrons paired, so it is a
singlet and a closed-shell molecule. The ground state of oxygen has two
unpaired electrons in a pair of degenerate antibonding pi orbitals with
parallel spins, so it is a triplet and an open-shell molecule.

The multiplicity tells the program which electronic state to calculate.
Describing oxygen as a singlet would target a different, higher-energy
state and give misleading energies and orbitals. Open-shell calculations
treat spin-up and spin-down electrons separately, so their orbitals are
slightly different, the frontier orbitals are reported for each spin, and
the HOMO and LUMO must be read with that in mind. The manual does not say
which multiplicity value to enter for oxygen, so this is a point to
confirm with the instructor.

## Orbital contribution and population

A molecular orbital is built from atomic orbitals. The orbital
contribution says how much each atom's s, p, d or f atomic orbitals take
part in a given molecular orbital. In the printed orbital table each
column is one MO and each row is one atomic orbital on one atom; the
number is that atomic orbital's coefficient in the MO. A larger absolute
value means a larger share, and the sign is the phase (the in-phase or
out-of-phase mixing described above). It shows which atoms and which
kinds of orbital an MO is really made of. For example, an occupied
orbital of methane that contains mostly carbon p character and hydrogen s
character shows the carbon-hydrogen bonding, while d and f contributions
are expected to be very small for these light atoms.

A population analysis goes one step further and shares out the electrons
among the atoms and orbital types, which is what a table of "electrons in
s, p, d and f" is asking for. Different population schemes (Mulliken and
Loewdin are common ones) divide the electrons a little differently, so
numbers from different schemes are not directly comparable.

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

A functional is the mathematical recipe used to approximate the
exchange-correlation energy, the part of the true electronic energy that
DFT cannot compute exactly. There is no single best functional for every
purpose; a functional and basis set are usually chosen together as a
combination that has been validated for the property being studied.

A hybrid functional mixes a fraction of the exact exchange that
Hartree-Fock calculates with exchange and correlation from a pure DFT
functional. B3LYP and B3P are both hybrids of Becke's three-parameter
type; they differ in the correlation part of the functional (LYP for
B3LYP, a Perdew-type correlation for B3P), so they give slightly
different energies for the same molecule and basis set. Comparing them
in the tables shows how much the functional choice matters.

## What the basis set is, and 6-31G versus 6-31G* versus 6-31G**

A basis set is the set of mathematical functions used to build the
molecular orbitals. A program cannot represent an orbital exactly, so it
approximates it as a combination of these simpler functions. More
flexible functions describe the orbitals better and generally give more
accurate energies and geometries, but cost more time. In the Pople
family, 6-31G is a split-valence basis: core orbitals use one function
and valence orbitals use two sizes, so valence electrons can spread or
contract. 6-31G* adds polarization functions (d-type) to the heavy,
non-hydrogen atoms, which lets orbitals distort away from a purely
spherical shape. 6-31G** adds polarization functions to hydrogen atoms as
well (p-type). Each step adds flexibility, and orbital energies typically
shift a little as the basis set improves. Different basis sets give
noticeably different absolute energies for the same molecule, so a
comparison between two calculations is only meaningful when both used the
same method and basis set.

## SCF and convergence

To find the orbitals, the program guesses them, works out the average
field every electron feels from all the others, solves for improved
orbitals in that field, and repeats. This loop is the self-consistent
field (SCF) procedure. It has converged when the energy and orbitals stop
changing between cycles. If the output says the SCF did not converge, the
orbitals and energies from that run cannot be trusted.

## Geometry optimization versus a single-point energy

A single-point calculation computes the energy and orbitals for one fixed
arrangement of the atoms. A geometry optimization moves the atoms step by
step, recomputing the energy and the forces (the energy gradient), until
the forces are essentially zero: the lowest-energy arrangement for that
method and basis set. The line printed at the end of the output as the
final single point energy is the total energy of the last geometry, in
Hartree.

Orbital energies depend strongly on the positions of the nuclei. A
structure drawn by hand has approximate bond lengths and angles, so it is
not the arrangement the molecule actually prefers. That is why the
optimization is done first and the orbital calculation is run on the
optimized geometry: the HOMO, LUMO and orbital contributions then
describe the relaxed molecule rather than an arbitrary sketch, and it is
also why the optimized file, not the drawn one, is used for the second
calculation.

## Ground state and excited states

The ground state has the electrons in the lowest possible orbitals. An
excited state has at least one electron promoted into a higher orbital.
An option such as "Excited states: Nothing" means the run only computes
the ground state, which is what this experiment needs. The HOMO-LUMO gap
is a rough guide to how easily the first excitation happens.

## Simple sanity checks on a finished run

Two quick physical checks help catch a bad run, and neither needs a
reference value. First, for one and the same run the LUMO energy must lie
above the HOMO energy, because the LUMO is by definition the next orbital
up. Second, an optimization is searching for a lower energy, so the final
energy should normally be equal to or lower than the energy of the
starting structure; a final energy that is clearly higher suggests
something went wrong. A run that fails either check, or that shows no job
completion message, should be repeated or reported rather than written
up.

## The files a run leaves behind

An ORCA run works on an input file (extension .inp) and writes a readable
output file (.out) that holds the energies, orbital table and the job
completion message. It also writes other files: a binary wavefunction
file (.gbw), density files, and a short properties text file. Only the
.out file is meant to be read by eye. Avogadro reads the .out file to show
the molecule and its orbitals.

## Gabedit's main window, control by control

A student new to Gabedit meets a screen full of unlabelled icons. Each
line below says what a control is and where that knowledge comes from:
the manual's own screenshots, a primary manual for the program, or
nothing (in which case the honest answer is to hover for the tooltip or
ask the demonstrator). The course uses Gabedit 2.5.1; the only Gabedit
manual available is for 2.1.0, so a label there can differ slightly.

- **Menu bar: File, Edit, Insert, View, Geometry, Tools, Run, Settings, Help.** These are the
  menus across the top of the main window. (Source: shown in the manual's screenshot.)
- **Geometry, then Draw.** Opens the "Draw Geometry" window, where molecules are sketched and
  examined in three dimensions. (Source: documented by the Gabedit 2.1.0 manual, section on
  building molecules, and shown in the manual's screenshot.)
- **Run menu.** Holds "Run a Computation Chemistry program" (which opens the Run dialog) and "View
  result of calculation". (Source: shown in the manual's screenshot.)
- **Settings menu.** Its Preferences page holds the default command for each program and the
  remote-connection protocol. The course's Run dialog already shows the command orca, so nothing
  there needs changing for a local run. (Source: documented by the Gabedit 2.1.0 manual.)
- **Tools menu.** A Batch, Remote item lists and can kill jobs on a remote server; irrelevant for
  a run on the lab PC. (Source: documented by the Gabedit 2.1.0 manual.)
- **Insert, View and Help menus.** What they contain is not documented in the manual or the
  screenshots; hover for the tooltip or ask the demonstrator.
- **The first group of small toolbar icons.** These repeat, in the same order, the program icons
  beside the names in the Recent Projects list (Demon, Firefly, Gamess, Gaussian, Molcas, Molpro,
  Mopac, MPQC, NWChem, Psicode, ORCA, Q-Chem). Each opens that program's input generator. The
  manual's screenshots put a red box round the one labelled ORCA. (Source: shown in the manual's
  screenshot.)
- **The remaining toolbar icons** (file open and save, print, cut, copy, paste, search and others).
  Their individual functions are not documented; hover for the tooltip.
- **Recent Projects panel on the left.** A list of program names and file-type folders (XYZ, MOL2,
  PDB, Tinker, Gauss Zmat, Mopac Zmat, Hyperchem, Others). ORCA and Gabedit have expander
  arrows. What clicking each entry does is not documented.
- **The file tab above the text area.** It shows the open file's name (for example a methane file
  ending in .gab) with the structure written as text under a "[Gabedit Format]" line, one row per
  atom. A second tab is labelled "Unknown"; what it is for is not documented. (Source: shown in
  the manual's screenshot.)
- **Location, Output and Error tabs, with the Local and Remote panels at the bottom.** The Local
  panel lists Host, Login and Directory; the Remote panel lists the same three for a remote
  server. How the Local Directory relates to the Run dialog's Folder field is not documented.
  (Source: shown in the manual's screenshot.)
- **Output-page buttons Update/end, Geom. Conv., Dens. Orb. and Get All files.** Update/end
  refreshes the output of a job submitted locally, Geom. Conv. shows how the geometry changed over
  an optimisation, Dens. Orb. opens Gabedit's own orbital and density viewer, and Get All files
  fetches results from a remote machine. The course reads the .out file and views orbitals in
  Avogadro instead. (Source: documented by the Gabedit 2.1.0 manual.)

## Gabedit's Draw Geometry window, control by control

- **The toolbar down the left side.** A button marked M at the top, then columns of small icons
  separated by thin lines. The Gabedit 2.1.0 manual says this toolbar offers: a free selection and a
  fragment selection (hold Shift to select separate pieces), move and rotate for the selected atoms,
  a measure tool for atom-atom distance, angle and torsion (pick four atoms for a torsion), delete
  (click one of the selected atoms), and add or replace an atom. (Source: documented by the Gabedit
  2.1.0 manual.) Which picture is which tool is not documented, because the manual's icons are
  unlabelled; hover for the tooltip or ask the demonstrator. The M button is not documented either.
- **The icon in the red box in the oxygen step.** It is the add-or-replace-atom control: it opens the
  "Select your atom" periodic table, you pick the element, then click in the drawing area; clicking
  on an existing atom replaces it. (Source: documented by the Gabedit 2.1.0 manual, and shown in the
  manual's screenshot, where the box and an arrow on the O tile mark the two clicks.)
- **The "Select your atom" window.** A coloured periodic table with a tile per element. A tile
  marked X at the bottom left is not documented. (Source: shown in the manual's screenshot.)
- **The fragment window (title truncated to "Gabedit : Fragment Sel...").** A list headed Fragments
  in groups such as Functionals, Rings, Heterocyclic and Hydrocarbon, with a black preview pane
  below it. Choose an entry, then click in the drawing area to drop it. About a hundred fragments
  ship with Gabedit and you can save your own. The coloured circles in the preview pane are not
  documented. (Source: shown in the manual's screenshot, and documented by the Gabedit 2.1.0 manual.)
- **The hint lines at the bottom of the drawing window.** They begin "Press the Middle mo..." and
  are cut off in the screenshot, so the full mouse hints are not documented. (Source: shown in the
  manual's screenshot.)
- **The right-click menu.** Entries: Read, Edit, Selection, Save as, Add, Build, Crystallography,
  Operations, Labels, Render, Symmetry, Set, Export, Screen Capture, Tools, Amber potential,
  (Semi-)empirical, View, Close. (Source: shown in the manual's screenshot.) Read loads a structure
  from an existing file, Build makes linear, ring and symmetric molecules, polypeptides, nucleic
  acids and nanotubes, and Add offers the fragment library. (Source: documented by the Gabedit
  2.1.0 manual.) What the other entries do is not documented.
- **Save as.** Offers Gabedit file, XYZ, Mol2, Mol, Tinker, pdb, POSCAR (Cartesian and Direct), CIF
  (with all atoms, or with symmetry operators), Hyperchem, CChemI, Mopac Zmatrix, Gaussian Zmatrix
  and Other format (using open babel). The course picks Gabedit file, which is the format Gabedit's
  main window opens next. (Source: shown in the manual's screenshot.)
- **Molecular Mechanics optimisation.** Gabedit's own force-field clean-up is a different tool from
  the ORCA optimisation the course runs; it is not part of the course workflow. (Source: documented
  by the Gabedit 2.1.0 manual; the course version's menu for it is not documented.)

## The ORCA input dialog, field by field

Every field here is a control the student sets before pressing OK. The dialog is titled "Orca input".

- **Charge.** The net charge of the whole molecule. (Source: shown in the manual's screenshot.)
- **Spin multiplicity.** 2S+1 for the electronic state to calculate. The manual does not say what
  to enter for oxygen, and its dialog screenshot in the oxygen section still shows the methane
  setting. (Source: shown in the manual's screenshot; the value for oxygen is not documented, so ask
  the demonstrator.)
- **Number of electrons.** A read-only line the dialog fills in from the atoms and the charge. It is
  the quickest way to check that the charge is sensible: an odd number of electrons cannot be a
  singlet. (Source: shown in the manual's screenshot.)
- **Job Type.** The manual's screenshots show "Equilibrium structure search" for the optimisation and
  "Single Point Energy" for the orbital run. The other entries in the list are not documented.
  (Source: shown in the manual's screenshot.)
- **SCF Type.** The screenshots show "restricted". Restricted and unrestricted are explained in the
  next section. (Source: shown in the manual's screenshot.)
- **SCF Convergence.** Set to "Default" in the screenshots. ORCA itself offers a ladder of stricter
  and looser convergence criteria; the entries in the dialog's list are not documented.
  (Source: documented by the ORCA manual for the ladder; the dialog's list is not documented.)
- **Type of method.** Chooses the family of method: Hartree-Fock, local and gradient corrected
  functionals, hybrid functionals, meta-GGA and hybrid meta-GGA, a perturbatively corrected double
  hybrid, second-order many-body perturbation theory, high-level single-reference methods and
  semiempirical methods. The course tables use the hybrid family. (Source: shown in the manual's
  screenshot.)
- **Method.** The specific functional inside that family, for example B3LYP or B3P. Changing the
  family changes the list. (Source: shown in the manual's screenshot.)
- **Excited states.** Set to "Nothing" in the screenshots, meaning only the ground state is
  calculated. ORCA can compute excited states with time-dependent methods, but the dialog's other
  entries are not documented. (Source: shown in the manual's screenshot; the time-dependent methods
  are documented by the ORCA manual.)
- **Type (basis family).** Set to "Pople Style basis sets". (Source: shown in the manual's
  screenshot.)
- **Basis.** The named basis set: the manual's tables use 6-31G, 6-31G* and 6-31G**. A star adds
  polarisation functions on heavy atoms and two stars add them on hydrogen as well. (Source: shown
  in the manual's screenshot; the star convention is documented by the ORCA manual.)
- **Auxiliary basis.** In the screenshots this field reads "AutoAux Automatic construction of a
  general purpose fitting basis" and is greyed out, so it cannot be edited for those settings. An
  auxiliary (fitting) basis is a second, helper basis that lets ORCA approximate the two-electron
  integrals faster; AutoAux means ORCA builds one automatically. The timing table in the manual's
  screenshots lists a "Split-RI-J" line, the Coulomb approximation that uses the auxiliary basis,
  and a "Chain of spheres X" line, a companion approximation for the exchange part. (Source: shown in the manual's screenshot; AutoAux and the approximations are
  documented by the ORCA manual. Why the field is greyed out is not documented.)
- **Initial Guess.** Set to "Default". The starting orbitals for the SCF iterations. ORCA's own list
  includes a superposition of atomic densities (its default), a model potential, an extended-Hueckel
  guess, the bare-nucleus (core Hamiltonian) guess and reading orbitals from an earlier run. The
  choice affects speed and whether the SCF converges, not what the converged answer is meant to be.
  (Source: shown in the manual's screenshot for the field; documented by the ORCA manual for the
  list. The dialog's own list is not documented.)
- **Cancel and OK.** Cancel closes the dialog; OK writes the input into Gabedit's editor tab and the
  run itself is started later from the Run menu. (Source: shown in the manual's screenshot.)

## Restricted versus unrestricted, and why oxygen needs care

A restricted calculation puts electrons in pairs into the same spatial orbital, one spin up and one
spin down. That is the natural description for a molecule where every electron is paired, like
methane. An unrestricted calculation gives spin-up and spin-down electrons their own orbitals, which
is needed when there are unpaired electrons, as in oxygen's ground state. Restricted-open-shell is a
third option that keeps paired electrons together and treats the unpaired ones separately. The ORCA
manual says that, if you do not say otherwise, a closed-shell singlet is treated as restricted and
anything else as unrestricted. (Source: documented by the ORCA manual.) The reasoning a student
should be able to give is this: count the electrons, decide how many are unpaired, and that fixes both
the multiplicity to enter and whether a restricted setting can describe the molecule at all. The
manual's own dialog screenshots show "restricted" and do not say what to use for oxygen, so the value
and setting for oxygen are not documented and are worth asking the demonstrator. When a run is
unrestricted the output lists spin-up and spin-down orbitals separately, so the HOMO and LUMO must be
read with that in mind.

## Reading an ORCA output file, in file order

The .out file is long. This is what its parts are, in the order they appear, and what each is for.
(Source for the general structure: documented by the ORCA manual's output tutorial; the parts the
manual's screenshots show are noted per line.)

- **The banner and the echo of the input.** The program name and version, then a copy of the input
  file with numbered lines. If the run did something unexpected, compare the echo to what you meant
  to send; a wrong method, basis, charge or multiplicity shows up here first. (Source: documented by
  the ORCA manual.)
- **The geometry.** The atom positions in Cartesian coordinates. ORCA numbers atoms from zero, so the
  first atom is 0, the second 1, and so on, and the same numbering appears in the orbital tables.
  (Source: shown in the manual's screenshot for the numbering; documented by the ORCA manual for the
  coordinate listing.)
- **The basis set information.** Printed because PrintBasis was requested; it lists which functions
  sit on which atom. (Source: documented by the ORCA manual.)
- **The SCF settings.** A summary of the method as ORCA understood it: charge, multiplicity, number of
  electrons, functional and convergence thresholds. Use it to confirm the dialog choices arrived
  intact. (Source: documented by the ORCA manual.)
- **The SCF iterations.** One line per cycle showing the total energy and how much it and the density
  changed. The changes should shrink until they fall under the thresholds; a run whose changes stall
  or grow has not converged. (Source: documented by the ORCA manual.)
- **The convergence message.** A line saying the SCF converged after a number of cycles. If it is
  missing or says the SCF did not converge, no number below it can be trusted. (Source: documented by
  the ORCA manual.)
- **The energy breakdown.** The total energy split into nuclear repulsion, electronic energy, one- and
  two-electron parts, and exchange-correlation and virial information. The total is the number a
  single-point run is asking for. (Source: documented by the ORCA manual.)
- **ORBITAL ENERGIES.** A table with columns NO (the orbital's number, starting at zero), OCC (its
  occupancy), E(Eh) (energy in Hartree) and E(eV) (energy in electron volts). In a restricted run
  occupied orbitals show an occupancy of two and virtual orbitals show zero, so the HOMO is the last
  row with occupancy two and the LUMO is the very next row. (Source: shown in the manual's screenshot.)
- **MOLECULAR ORBITALS.** Printed because the input's output block asks ORCA to print the molecular orbitals. It is printed in blocks of six
  orbitals across the page. Over each column are the orbital's number, its energy in Hartree and its
  occupancy; each row below is one basis function, labelled with the atom's number, its element and
  the function (for example a 1s, 2s, three p functions and, where the basis has them, five d
  functions). The entries are coefficients: how strongly that basis function is mixed into that
  orbital, with a sign that is the orbital's phase. A coefficient near zero means that function
  hardly contributes. The number of orbitals in the table equals the number of basis functions, which
  is why a bigger basis set gives more virtual orbitals. (Source: shown in the manual's screenshot;
  the print option is documented by the ORCA manual.)
- **Population analyses and other property blocks.** The ORCA manual describes Mulliken and Loewdin
  population analyses, which split the electrons among atoms and among s, p and d shells. The course
  manual does not point to them. (Source: documented by the ORCA manual; the course manual does not
  mention them, so which block the tables expect is not documented.)
- **The timing table.** Total time and a breakdown of where it went (Fock matrix formation,
  diagonalisation, grid generation and so on) and the maximum memory used. It says nothing about the
  chemistry; it is there to show where a slow run spent its time. (Source: shown in the manual's
  screenshot.)
- **FINAL SINGLE POINT ENERGY.** The line the manual asks students to read for the energy, printed
  between rules. For an optimisation it is followed by "*** OPTIMIZATION RUN DONE ***", which means
  the geometry search finished. (Source: shown in the manual's screenshot, where both lines are
  boxed in red.)
- **The termination line.** A healthy run ends with the message that ORCA terminated normally and a
  total run time. This is the "job completion message" the manual tells students to look for.
  Its absence means the run ended with an error. (Source: documented by the ORCA manual; the manual
  itself calls it the job completion message.)

## Where each Table 1 and Table 2 quantity comes from

The HOMO and LUMO energies for the tables are read from Avogadro's Orbitals panel, as the manual says.
The same two orbitals can be found in the ORBITAL ENERGIES table of the .out file: the panel and the
table list the same orbitals in the same units, so they should agree. Checking one against the other
is a good habit and catches opening the wrong file. The electron counts in the s, p, d and f
orbitals come from the orbital-contribution data in the output; the manual's screenshot of the
MOLECULAR ORBITALS table has one column highlighted, and the manual does not say more about which
block or column to total. That is worth confirming with the demonstrator. A basis set without d
functions (plain 6-31G) has no d rows at all, and none of these basis sets has f functions, so a
zero there is a legitimate answer for reasons of the basis, not a mistake. (Source: shown in the
manual's screenshot for the tables and the highlighted column; the rest is background.)

## Avogadro's screen, control by control

- **Menu bar: File, Edit, View, Build, Select, Extensions, Crystallography, Settings, Help.**
  (Source: shown in the manual's screenshot.)
- **Toolbar labels New, Open, Save, Close and Quit.** Open is the one the manual uses, to load the
  ORCA .out file. (Source: shown in the manual's screenshot.)
- **The row of small tool icons and the Tool Settings and Display Settings buttons.** The left panel
  in the screenshots is titled "Navigate Settings" and has a "Display visual cues" checkbox, so the
  navigate tool is the active one. What each unlabelled icon does is not documented; hover for the
  tooltip or ask the demonstrator.
- **The tab "View 1" and the Messages bar under the 3D view.** The 3D view is the black area; the
  Messages bar is where Avogadro reports problems, so it is worth a look if a file will not load.
  (Source: shown in the manual's screenshot; what Messages reports is not documented.)
- **The window title.** Shows the file name, for example the methane .out file with a trailing
  asterisk; what the asterisk signals is not documented. (Source: shown in the manual's screenshot.)
- **The Orbitals panel.** A table with the columns Orbital, Energy (eV) and Symmetry. Rows are named
  relative to the frontier: HOMO-4 up to HOMO, then LUMO up to LUMO+11 for methane in the screenshot.
  The Symmetry column is empty in the screenshots and a green bar sits at the end of each row; what
  the bar means is not documented. Clicking the HOMO or LUMO row shows that orbital in the 3D view as
  a blue lobe and a red lobe. (Source: shown in the manual's screenshot.)
- **Quality, Render and Configure below the table.** Quality is a dropdown (set to Low in the
  screenshots), Render draws the selected orbital and Configure opens further settings. The other
  Quality entries, and what Configure holds, are not documented. (Source: shown in the manual's
  screenshot.)
- **What the two colours mean.** The red and blue lobes are the two signs of the orbital wave
  function, the same sign that the coefficients carry in ORCA's MOLECULAR ORBITALS table. They do not
  mean positive and negative charge. (Source: shown in the manual's screenshot for the two lobes;
  the sign convention is general background and is not documented by the manual.)
- **Why the LUMO energy can be positive.** In the screenshots the lowest unoccupied orbital sits at a
  positive energy in electron volts. That is not an error. Virtual orbitals are not filled, so their
  energies are not the energy of a bound electron; with a small basis set that has no diffuse
  functions they are pushed upward and can be above zero. So a positive LUMO tells you about the
  basis set and method, not that the molecule cannot accept an electron. The sanity checks that
  matter are that the HOMO is usually negative and that the LUMO lies above the HOMO. (Source: shown in the manual's
  screenshot for the positive value; the explanation is general background.)
- **Avogadro and ORCA list the same orbitals.** In the manual's screenshots the Orbitals panel and the
  ORBITAL ENERGIES table give the same energies in electron volts, and the panel's lowest row is a deep
  core orbital. Avogadro lists every orbital in the file, not just a few near the frontier.
  (Source: shown in the manual's screenshot.)

## When the job did not converge

Convergence means the optimisation or the SCF calculation kept refining
its answer until the change between steps fell below a small threshold.
Common generic reasons it does not:

- A poor starting geometry. If atoms are placed unreasonably close
  together or the initial structure is far from any real molecular shape,
  the optimiser can struggle to find a sensible minimum.
- An inappropriate method and basis-set combination for the system; some
  combinations are simply not well suited to some molecules or states.
- A genuinely flat or complicated potential energy surface, where many
  geometries have very similar energy and the optimiser oscillates
  between them instead of settling.
- Too tight a convergence threshold relative to the precision the chosen
  method and basis set can actually achieve.

## When the output file looks empty or incomplete

This usually means the job did not finish. Check for an explicit normal
termination or completion message near the end of the file (the exact
wording depends on the version and program) rather than assuming a long
file means success. A job that stopped partway through because it ran out
of allotted time, memory, or disk space will often leave a truncated
output with no such message.

## When the energy is a large positive number, or "nan" or "inf" appears

Total energies of molecules are large negative numbers, so a large
positive value, or nan or inf, generally indicates the calculation
diverged rather than converging to a physically meaningful answer. It is
often traceable to an unreasonable starting geometry, a charge or
multiplicity specified inconsistently with the actual molecule, or a
numerical instability in a particular method for that system.

## When two calculations give very different absolute energies

Absolute total energies from quantum chemistry calculations are usually
only meaningful in comparison to another calculation done with the exact
same method, basis set, and (for optimisations) similar convergence
settings. Comparing energies computed with different settings is
comparing two different approximations, not two states of the same
system, and differences produced this way are not chemically meaningful.

## Checklist before concluding something is broken

1. Confirm the input file actually specifies the molecule, method and
   basis set you intended. A typo in a keyword is far more common than a
   program bug.
2. Confirm the job actually ran to completion rather than being
   interrupted.
3. Re-read the specific output section the exercise asks you to report
   from, rather than skimming the whole file. The number you need is
   often in a clearly labelled block near the end.
4. If none of the above resolves it, ask a demonstrator with the actual
   output file in hand, since a specific error message usually narrows the
   cause immediately in a way generic advice cannot.

## Common misunderstandings

A negative orbital energy does not mean an unstable molecule. A bigger
basis set does not change the molecule, only how well the calculation
describes it, so energies shift a little when the basis set changes. A
HOMO-LUMO gap from one functional cannot be compared with one from
another as if they were the same measurement. The HOMO energy is related
to, but is not identical to, the ionization energy. And a run that did
not finish (no job completion message, or an SCF that did not converge)
should be repeated before any numbers are written up.
