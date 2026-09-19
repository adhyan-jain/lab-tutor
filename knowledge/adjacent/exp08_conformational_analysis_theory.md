<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp08
topic: conformational analysis background for ethane and cyclohexane -- basic terms, why conformers differ in energy, the chair/half-chair/twist-boat/boat forms, and how to read the computed energies
-->

# Exp 8 background: conformers of ethane and cyclohexane

General organic chemistry background written for LabTutor. It explains the
terms and the "why"; the manual's own steps and the values a student
reports come from the manual and from the student's own runs. Nothing here
is the manual's procedure.

## Basic terms

**Conformation and conformer.** A conformation is one particular
three-dimensional arrangement of a molecule that can change into another
just by rotating around single bonds, with no bond broken. Each such
arrangement is a conformer. Conformers of one molecule are not different
compounds: they are different shapes of the same molecule, each with its
own energy. This is different from a configuration (for example cis versus
trans, or a mirror-image form), which can only change by breaking bonds.

**Dihedral (torsion) angle.** Look along a bond between atoms B and C.
The dihedral angle for A-B-C-D is the angle you would turn the A end
relative to the D end. It is the number that changes as a bond rotates.

**Newman projection.** A way of drawing a molecule looking straight down
one bond: a circle for the back atom, the front atom at its centre, and
the attached groups radiating from each. It shows the dihedral angles
between groups on the two atoms directly.

**Strain.** Extra energy a conformer has compared with an ideal, relaxed
arrangement. Torsional strain comes from groups on neighbouring atoms
being eclipsed instead of staggered. Steric strain comes from atoms being
pushed too close together. Angle strain comes from bond angles forced away
from the ideal tetrahedral value of about 109.5 degrees.

**Potential energy profile (or surface).** A graph of energy against a
geometric coordinate. For ethane it is energy against the dihedral angle as
one CH3 group turns relative to the other. Low points are stable
conformers (minima); high points are the tops of barriers between them.

**Minimum, saddle point and barrier.** A minimum is a geometry where any
small change raises the energy, so a relaxed molecule settles there. A
saddle point is the top of a barrier along the path between two minima:
it is a maximum along that path but a minimum in the other directions. An
energy barrier is the height of a saddle point above the minimum.

## Ethane: staggered versus eclipsed

Looking down the C-C bond of ethane, the staggered conformation has the
hydrogens on the front carbon between the hydrogens on the back carbon
(60 degrees apart), while the eclipsed conformation has them directly
behind each other (0 degrees). As the bond turns through a full circle the
energy goes through three minima (staggered) and three maxima (eclipsed),
repeating every 120 degrees, because ethane has three-fold symmetry.

The staggered conformer is lower in energy. The eclipsed one is a saddle
point on the rotation path, not a stable shape. The height of the barrier
is small, about 12 kJ/mol (roughly 3 kcal/mol), which is only a few times
the thermal energy at room temperature, so ethane rotates freely and the
two forms are not separate species, only more and less populated points
along a continuous rotation.

Why the staggered form is lower is described in more than one way, and the
explanations are not fully settled. One view attributes the barrier to
hyperconjugation: in the staggered form a filled C-H bonding orbital on
one carbon can donate a little electron density into an empty C-H
antibonding orbital on the other, a stabilising interaction that is
weaker when eclipsed. Another view attributes it mainly to repulsion
between the electron clouds of the C-H bonds, which is larger when they
are eclipsed. Textbooks commonly lump the result under the name torsional
strain. For the experiment, what matters is that staggered is lower.

## Cyclohexane: the forms and their order

A six-membered ring is not flat. A flat ring would force bond angles of 120
degrees and eclipse every C-H bond, so the ring puckers. The main shapes are:

- **Chair.** Every carbon is staggered relative to its neighbours and all
  bond angles are close to tetrahedral. It has almost no strain and is the
  lowest-energy form; at room temperature nearly all cyclohexane
  molecules are chairs at any moment.
- **Twist-boat.** A boat that has twisted slightly, which relieves some of
  the eclipsing and the flagpole crowding. It is a genuine energy minimum,
  but higher than the chair.
- **Boat.** Two carbons on opposite ends of the ring are raised on the
  same side. It has eclipsing along its sides and a steric clash between
  the two flagpole hydrogens that point at each other across the top. The
  boat is higher than the twist-boat and is not a minimum: it is a saddle
  point between two twist-boats.
- **Half-chair.** A strained, nearly flat arrangement in which four
  adjacent carbons lie roughly in one plane. It is the highest-energy of
  the four and is the saddle point on the path from a chair towards a
  twist-boat, so it is the top of the main barrier to ring flipping. It is
  a transition-state-like geometry, not a stable conformer.

The general order of energy, lowest to highest, is: chair, then
twist-boat, then boat, then half-chair. Textbook figures put the
twist-boat about 5 to 6 kcal/mol (roughly 23 kJ/mol), the boat about 7
kcal/mol (roughly 29 kJ/mol) and the half-chair about 10 to 11 kcal/mol
(roughly 45 kJ/mol) above the chair. A quantum chemistry calculation with
a particular method and basis set will give somewhat different numbers, so
use the ordering, and the rough scale, as a sanity check, not as values to
reproduce. The values a student reports are the ones from their own runs.

**Ring flip.** One chair converts into the other chair by passing over the
half-chair and twist-boat region. In a ring flip, every axial position
becomes equatorial and vice versa. Axial bonds point straight up or down
parallel to the ring's axis; equatorial bonds point outward around the
ring's equator. This matters for substituted rings, where a bulky group
prefers the equatorial position to avoid crowding by the two axial
hydrogens on the same side (1,3-diaxial interactions), but for plain
cyclohexane the two chairs are identical.

## Reading the computed energies

A quantum chemistry program reports a total energy for each geometry, in
Hartree (Eh), as a large negative number, for example the value printed on
the "final single point energy" line of the output. The total energy of one
geometry on its own means little. What is meaningful is the difference
between two geometries computed with the same method and basis set. To
compare conformers subtract their energies. One Hartree is about 2626
kJ/mol, or about 627.5 kcal/mol, so a difference of 0.005 Hartree is
about 13 kJ/mol. Energies from different methods or basis sets must not be
mixed in one comparison.

Because only relative energies matter, potential energy profiles are
usually plotted relative to the lowest conformer, with that one set to
zero.

## Practical points about optimizing these shapes

A geometry optimization moves the atoms downhill in energy until it reaches
a minimum. That has consequences here:

- The eclipsed form of ethane is a saddle point. If it is optimized
  without any restriction, the structure may relax towards the staggered
  form.
- The boat and half-chair forms of cyclohexane are not minima either, so a
  free optimization can relax a boat into a twist-boat or a half-chair into
  a chair or twist-boat. Holding these shapes usually needs a constraint
  on one or more torsion angles, or a fixed-geometry (single-point)
  calculation on the built structure.
- The manual does not say how these shapes are meant to be held during
  the run, so how to keep the eclipsed, boat and half-chair geometries is
  a point to confirm with the demonstrator.

Also check that each optimization finished: the output should carry a job
completion message, and a run that did not converge should be repeated
before its energy is used.

## The run command in general

The command the manual gives runs ORCA on an input file (extension .inp)
and uses the greater-than sign to send everything the program prints into
an output file (.out); the name in the command is the file name. The output
file is the one to open to find the energy. It is a plain text file, and
the job completion message and the final energy are near its end.

## Common misunderstandings

A lower total energy (more negative) means a more stable arrangement of
the same atoms, provided both were computed the same way. A conformer with
a higher energy is not "wrong": it is simply less stable and less
populated. A saddle point is not a stable molecule, so an optimization that
moves away from it is behaving correctly. And a small energy difference
between two conformers does not mean the calculation failed; ethane's
barrier is small on purpose.
