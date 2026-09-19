<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp02
topic: reaction kinetics background for the acid-catalysed hydrolysis of ethyl acetate -- basic terms, why the titration works, and how to read the data
-->

# Exp 2 background: reaction kinetics and the ester hydrolysis titration

General chemistry background written for LabTutor. It explains the terms
and the reasoning behind the experiment; the manual's own procedure,
formula, volumes and table are the authority for what to do and report,
and nothing here replaces them.

## Basic terms

**Reaction rate** is how fast a reactant is used up or a product forms:
the change in concentration per unit time (for example mol per litre per
minute).

**Rate law and rate constant.** The rate law says how the rate depends on
concentrations. The rate constant, k, is the proportionality factor in
that law. It does not depend on how much reactant is present, but it does
depend on temperature and on the catalyst. Its units depend on the order:
for a first-order reaction k has units of 1/time (the manual's table uses
per minute).

**Order and molecularity.** Order is an experimentally observed quantity:
the power to which a concentration is raised in the empirical rate law.
Molecularity is a mechanistic concept: the number of molecules that
collide in a single elementary step (unimolecular, bimolecular, and so
on). For a single elementary step order and molecularity coincide; for a
multi-step mechanism they generally do not, and order must be found from
data rather than read off the balanced equation.

**Half-life** is the time for the concentration of a reactant to fall to
half. For a first-order reaction it is 0.693 divided by k (0.693 is the
natural logarithm of 2) and does not depend on the starting
concentration, which is a quick test for first-order behaviour.

**Catalyst.** A substance that speeds a reaction by giving it a path with
a lower activation energy and is not used up overall. Here the acid (the
H+ from hydrochloric acid) is the catalyst.

**Hydrolysis** is a reaction with water that splits a bond. An ester
(R-COO-R') hydrolyses to a carboxylic acid and an alcohol; for ethyl
acetate the products are acetic acid and ethanol.

**Titration terms.** A standard solution is one whose concentration is
accurately known. The titre is the volume of it used. The end-point is
where the indicator changes colour; the equivalence point is where the
chemical amounts match exactly. A good indicator makes the two coincide
closely. Phenolphthalein is colourless in acid and turns pink in weakly
basic solution, so "the first pale permanent pink" marks the point where
a tiny excess of sodium hydroxide has been added.

**Normality (N)** is equivalents per litre. For hydrochloric acid and
sodium hydroxide, which each supply one H+ or OH- per formula unit, 1 N
equals 1 mol per litre.

## Integrated rate laws

A rate law written as a differential equation can be integrated to give
concentration as an explicit function of time, the form used to analyse
data:

- **Zero order**: the concentration decreases linearly with time.
- **First order**: the natural logarithm of the concentration decreases
  linearly with time. The rate constant is the size of the slope of that
  line, and the half-life is constant.
- **Second order**: the reciprocal of the concentration increases
  linearly with time.

Plotting data in the form for a candidate order and seeing which plot is
actually a straight line is a standard way to find the order from
experiment.

## Pseudo-order kinetics

When a reaction depends on more than one species but one of them is in
such large excess that its concentration barely changes, the reaction
behaves as if it depended only on the other. That is pseudo-order
kinetics. Ester hydrolysis involves an ester molecule and a water
molecule coming together, so it is bimolecular, but water is present in
huge excess (it is the solvent) so its concentration is effectively
constant, and the observed rate depends only on the ester: the reaction
looks first order. The true rate constant can be recovered from the
pseudo-constant by dividing by the roughly constant concentration of the
species in excess, when that is known.

## Acid catalysis

An acid catalyst commonly protonates a reactive site on the substrate
(here the oxygen of the ester's carbonyl group), which makes it more open
to attack by a weak nucleophile such as water, lowering the activation
energy. The catalyst is regenerated, so its concentration does not change
during the run. The rate constant therefore rises with the acid
concentration, but within a run the acid behaves as a constant. Because
the acid is present throughout, it is also what the titration mostly
measures at the start.

## What the titration actually measures

The sodium hydroxide neutralises acid in the withdrawn sample. That acid
is the hydrochloric acid catalyst, which stays constant, plus the acetic
acid produced by the reaction, which grows with time. Ethanol does not
react with sodium hydroxide, and the ester is not titrated. So the titre
rises as the reaction proceeds:

- the titre at zero time is essentially the catalyst alone (the manual
  calls it V0);
- the titre at time t is the catalyst plus the acetic acid formed so far;
- the titre at completion (V-infinity) is the catalyst plus all the acetic
  acid the ester can give.

The increase from zero time to completion is proportional to the amount
of ester present at the start, and the amount still to come at time t
(V-infinity minus Vt) is proportional to the ester remaining. The
constant hydrochloric acid part cancels in these differences, which is why
the manual works with differences and not with raw titres.

## Why the log plot is a straight line

For a first-order reaction the natural logarithm of the remaining ester
falls linearly with time. The manual uses base-10 logarithms of V-infinity
minus Vt (a quantity proportional to the remaining ester), so the plot of
that against time is a straight line sloping downward, and the rate
constant is the size of the slope multiplied by 2.303, which is the
natural logarithm of 10 and converts between the two kinds of logarithm.
Calculating k at several time intervals and finding nearly the same value
each time is the same check: a constant k means first order. A curved plot
means the order is not one, or that a reading (especially V-infinity) is
wrong.

## Why ice, and why heating at the end

Each 10 mL sample is run into a flask with ice because cooling slows the
reaction to a near stop, so the titre reflects the composition at the
moment of withdrawal instead of continuing to change while the titration
is done. The reaction mixture is heated on a hot water bath for a long
time at the end because heating speeds the reaction to completion, which
gives the final reading, V-infinity. Without that final reading there is
no reference for how much ester there was.

## Temperature and the Arrhenius equation

The Arrhenius equation, k = A exp(-Ea / RT), relates the rate constant to
temperature: A is the pre-exponential (frequency) factor, Ea the
activation energy and R the gas constant.

Why it works physically: a reaction happens when molecules collide, but
only collisions with enough energy to get over the activation barrier
lead to products. At temperature T the molecules have a spread of
energies, and the exponential term exp(-Ea / RT) is the fraction of them
that have at least the activation energy Ea. Raising the temperature
shifts the spread to higher energies, so that fraction, and with it k,
grows quickly. A bigger Ea makes the fraction smaller and more sensitive
to temperature. The factor A collects how often molecules collide and how
likely they are to meet in the right orientation. A catalyst does not
change T; it lowers Ea, which has the same kind of effect on k. Plotting the natural logarithm
of k against 1/T for several temperatures gives a straight line with slope
-Ea/R, which is how an activation energy is found. It needs rate constants
at more than one temperature, so it is not part of every kinetics
experiment. As a rule of thumb, reaction rates roughly double for a
10 degree rise near room temperature.

## Common sources of error

- Not pipetting the ester and the samples exactly, or not noting the time
  of each withdrawal accurately.
- Letting the withdrawn sample stand instead of cooling and titrating it at
  once, so it keeps reacting.
- Overshooting the end-point (a strong, not pale, pink).
- Not heating long enough for the reaction to finish, so V-infinity is too
  low and every value of k comes out wrong.
- Losing ethyl acetate to evaporation, since it is volatile.
- Using minutes in one place and seconds in another, so k has the wrong
  units.
