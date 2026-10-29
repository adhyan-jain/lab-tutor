<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp04
topic: potentiometric redox titration notes for iron in carbon steel with KMnO4 -- basic terms, why the EMF curve jumps, how to find the endpoint, and how to sanity-check the data
-->

# Exp 4: potentiometry and the iron-in-steel titration

Notes written for Catalyst on the chemistry of this titration. They
explain the terms and the reasoning; the manual's own procedure,
quantities, formulas and tables are the authority for what to do and
report, and nothing here replaces them.

## Basic terms

**Potentiometry** measures the potential (EMF, in millivolts) of a cell
at essentially zero current while a titrant is added. Instead of watching
an indicator change colour, you watch how the potential changes with the
volume of titrant.

**Indicator electrode and reference electrode.** The indicator electrode
(here an inert metal such as platinum) responds to the ratio of the
oxidised and reduced forms of the species in solution. The reference
electrode (for example a calomel electrode) holds a fixed potential. The
measured EMF is the difference between them, so only the changes in it
matter for finding the endpoint.

**Redox titration.** A titration in which the analyte is oxidised or
reduced by the titrant. Here the analyte is iron(II) and the titrant is
potassium permanganate, an oxidising agent.

**Equivalence point and endpoint.** The equivalence point is where exactly
the stoichiometric amount of titrant has been added. The endpoint is what
you actually locate from the data; a good method puts the two as close as
possible.

**Normality.** Equivalents of reacting species per litre. For a redox
reaction one equivalent is the amount that transfers one mole of
electrons. Iron(II) to iron(III) is a one-electron change, so for iron the
equivalent weight equals the atomic weight. Permanganate in acid takes
five electrons, which is why its normality is five times its molarity.
Because the two sides are written in equivalents, the working relation is
N1 x V1 = N2 x V2 at the equivalence point.

## The reaction

In acid, permanganate oxidises iron(II) to iron(III) and is itself reduced
to the nearly colourless manganese(II):

5 Fe2+ + MnO4- + 8 H+ -> 5 Fe3+ + Mn2+ + 4 H2O

Steel is first dissolved in acid, which brings the iron into solution as
iron(II). The titration then measures how much permanganate that iron
consumes; the iron content of the steel follows from the stoichiometry.
Permanganate is intensely purple, so in an ordinary titration it acts as
its own indicator. The potentiometric method does not rely on seeing that
colour change, which is the advantage when the solution is already
coloured.

## Why the EMF jumps at the endpoint (the Nernst equation)

The potential of the indicator electrode follows

E = E0 + (RT/nF) ln([Fe3+]/[Fe2+])

(at room temperature RT/F is about 25.7 mV, or 59 mV per decade for a
one-electron couple).

- **Before the equivalence point** there is still iron(II) left, and the
  ratio [Fe3+]/[Fe2+] changes slowly as titrant is added, so the EMF
  creeps upwards.
- **Near the equivalence point** almost all the iron(II) is used up, so a
  tiny extra amount of titrant changes the ratio enormously. The EMF
  climbs very steeply, by hundreds of millivolts for a fraction of a
  millilitre.
- **After the equivalence point** the potential is set by the
  permanganate/manganese(II) couple instead, which sits at a much higher
  potential, so the curve flattens out again at a high value.

Plotting EMF against volume therefore gives an S-shaped curve whose steepest
point marks the equivalence point.

## Finding the endpoint

**Visual method.** Draw the S-curve and take the volume at the middle of
the steep rise. It is quick but depends on where you judge the middle to
be.

**Derivative method.** Compute, for each pair of consecutive readings, the
change in EMF divided by the change in volume (delta E / delta V), and
assign it to the average of the two volumes. Plot it against that average
volume. The steepest part of the S-curve becomes a sharp peak, and the
volume at the top of the peak is the endpoint. This is more objective
because the maximum is a number you can read off the table.

Practical consequences:

- Take smaller additions near the jump. With large steps there may be no
  reading close enough to the true maximum, and the peak is poorly defined.
- The peak is found in the delta E / delta V column, not in the EMF column
  itself (the EMF keeps rising or levels off; it has no maximum there).
- The reported volume sits between two burette readings (an average
  volume), not at one of them. That is expected.

## From endpoint to iron content (the logic)

1. The endpoint volume of permanganate, and its known normality, give the
   equivalents of permanganate used.
2. At the equivalence point that equals the equivalents of iron(II) in
   the portion titrated, which gives the normality of the iron solution.
3. Normality multiplied by the equivalent weight of iron gives grams of
   iron per litre; scaling to the volume the manual asks for gives the
   reported quantity.

Unit slips here are common: millilitres against litres is a factor of
1000, and forgetting that the portion titrated is only part of the whole
solution changes the answer by that ratio. Use the manual's own formula
and quantities for the actual numbers.

## Sanity checks a student can do

- The EMF should rise as titrant is added, with the biggest change per
  millilitre around one narrow region. If it does not, check the
  electrode connections and that the solution is being stirred.
- The delta E / delta V column should have one clear maximum. Two
  similar peaks, or none, point to a reading or arithmetic error.
- The endpoint should lie inside the range of volumes actually added. If
  the maximum is at the last reading, the titration was stopped too early.
- The iron content should be a plausible fraction for carbon steel (most
  of the steel is iron, but the dissolved portion and dilution matter).
  A result off by a power of ten usually means a mL/L slip.

## Common sources of error

- **Incomplete dissolution** of the steel, or iron present partly as
  iron(III), which the titration would not measure.
- **Air oxidation** of iron(II) to iron(III) while the sample waits, which
  lowers the apparent iron content.
- **Adding titrant too fast near the endpoint**, so the potential has not
  settled when it is read.
- **Electrode problems**: a fouled platinum surface or a drifting
  reference electrode gives sluggish or noisy readings.
- **Chloride interference.** Permanganate can oxidise chloride, so the
  choice of acid for the medium matters; follow the manual for which acid
  to use rather than substituting one.
- **Burette reading and transcription errors** in the volume column,
  which shift individual points of the derivative.

## Quick answers to common questions

- **Why use potentiometry instead of an indicator?** It gives a number
  you can read off a graph, works in coloured or turbid solutions, and
  makes the endpoint less dependent on the experimenter's eye.
- **Why does the curve look like an S?** The potential depends on the
  logarithm of the ratio of oxidised to reduced iron, which changes
  slowly, then abruptly, then slowly again as the iron(II) runs out.
- **Where exactly is the endpoint?** At the volume where delta E / delta V
  is largest, not where the EMF itself is largest.
- **What does the second derivative do?** It crosses zero at the peak of
  the first derivative, which some people use to locate the endpoint even
  more precisely. The manual's method is the first-derivative peak.
