<!--
tier: C (curated adjacent — NOT the IACHY102 manual)
experiments: exp03
topic: colorimetry background for the Ni(II) determination -- basic terms, Beer-Lambert law, the nickel-DMG chemistry, dilution arithmetic and the smartphone/RGB method
-->

# Exp 3 background: colorimetry, Beer-Lambert law and the smartphone/RGB method

General chemistry background written for LabTutor. It explains the terms
and the reasoning behind the experiment; the manual's own procedure,
wavelength, volumes and table are the authority for what to do and
report, and nothing here replaces them.

## Basic terms

**Absorbance (A)** is how much light a sample takes in, on a logarithmic
scale: A = log10(I0 / I), where I0 is the light power going in and I the
power coming out. **Transmittance (T)** is the fraction that gets through,
I / I0, so A = -log10(T). An absorbance of 0 means all the light passes;
an absorbance of 1 means 10 percent passes; 2 means 1 percent. Absorbance
has no units.

**Molar absorptivity (epsilon)** is a constant that says how strongly one
particular species absorbs at one particular wavelength. It has units of
litres per mole per centimetre. **Path length (b or l)** is the distance
the light travels through the solution, usually the width of the cuvette
(commonly 1 cm).

**ppm (parts per million)** for a dilute aqueous solution is milligrams of
solute per litre of solution. A 100 ppm stock contains 100 mg of the
substance in every litre.

**Stock, standard and unknown.** The stock solution is the concentrated
starting solution. Standards are solutions of known concentration made
from it by dilution. The unknown is the sample whose concentration you
want to find.

**Blank.** A solution containing everything except the analyte. The
instrument is set to read zero absorbance on the blank, so that the
readings for the standards and the unknown show only the analyte, not the
solvent, the reagents or the cuvette.

**Calibration curve.** A graph of the instrument response (absorbance, or
the RGB-based value) against the known concentrations of the standards.
The unknown is measured the same way and its concentration is read from
the curve.

**Colorimeter and spectrophotometer.** A colorimeter measures absorbance
through a fixed, fairly broad band of wavelengths chosen by a filter; a
spectrophotometer can select a narrow wavelength across a range and can
record a full spectrum. **Lambda-max** is the wavelength at which the
species absorbs most strongly.

**Complexing agent (ligand).** A molecule that binds to a metal ion to form
a complex. Dimethylglyoxime (DMG) binds nickel through two nitrogen atoms
and is a chelating ligand: one DMG grabs the metal at two points, and two
DMG molecules surround each nickel. The complex is written Ni(dmg)2.

**Oxidation state.** The formal charge an atom would have if its bonds
were ionic. Nickel is normally +2 in its compounds. An oxidising agent
such as potassium ferricyanide takes electrons and changes the complex,
here into a soluble, brown-red form that is easier to measure.

## The Beer-Lambert law

The law relates absorbance to concentration: A = epsilon x b x c, where c is
the concentration. For a fixed species, wavelength and path length,
absorbance is directly proportional to concentration, so a plot of
absorbance against the concentrations of the standards, the calibration
curve, should be a straight line. Because absorbance is corrected against
the blank, a solution with no analyte reads zero, so the line is expected
to pass through the origin (or very close to it). A line that clearly
misses the origin usually points to a blank or dilution problem.

The law holds over a limited range. At high concentration the line bends,
for reasons the simple law does not include: changes in the solution's
refractive index, interactions between solute particles, and stray light
in the instrument at high absorbance. This is why a calibration curve
should only be trusted within the concentration range it was measured
over, and why an unknown that reads above the highest standard should be
diluted and remeasured, not extrapolated.

## Dilution arithmetic

Diluting a solution keeps the amount of solute but spreads it over a
larger volume, so concentration times volume is unchanged:
c1 x V1 = c2 x V2. For example, putting 10 mL of a 50 ppm solution into a
100 mL volumetric flask and making up to the mark gives 50 x 10 / 100 =
5 ppm. The same relationship shows why adding different volumes of stock
to flasks of one fixed size gives an evenly spaced series of standards.
A volumetric flask is used, not a beaker, because it holds one exactly
known volume when filled to its mark.

## Why the solution is coloured, and why measure at that wavelength

A coloured complex absorbs some wavelengths of visible light more than
others. The colour you see is what is left: the light it does not absorb
is transmitted or reflected. A complex that looks red-brown is absorbing
mainly the blue end of the spectrum, which is why a measurement in the
blue region (around the wavelength the manual names) gives the strongest
signal. The wavelength is chosen at or near lambda-max because the
absorbance is largest there, which makes the method most sensitive, and
small errors in setting the wavelength change the reading least. A more
concentrated solution has more absorbing species in the light's path, so
it absorbs more strongly; that is the basis for using colour intensity as
a measure of concentration.

## The nickel-DMG chemistry

In the manual's scheme, nickel(II) reacts with DMG in alkaline solution to
form a pink Ni(dmg)2 complex, and potassium ferricyanide then oxidises
this to a brown-red, water-soluble complex that is the species actually
measured. Sodium hydroxide gives the alkaline medium, since the complex
forms properly only in a suitable pH range. The reagents are added in a
set order and the flasks are left to stand so the colour has time to
develop fully before measurement; measuring too early gives low readings.
The unknown is treated exactly like the standards, with the same reagents,
the same waiting times and the same final volume, so that the only
difference between them is the amount of nickel.

## How a smartphone camera captures colour

A camera's image sensor is covered by a filter mosaic (commonly a Bayer
filter) so that each pixel records mostly one of three colour channels,
red, green and blue. In a standard 24-bit image each channel has 256
levels from 0 to 255, so R = G = B = 0 is black and 255 for all three is
white. The per-pixel values are the camera's estimate of how much light in
roughly those three wavelength bands reached the pixel, after substantial
automatic processing (white balance, gamma correction and other
adjustments) that a spectrophotometer does not perform.

## Why an RGB channel ratio is often used

A single channel's raw value depends on far more than the sample:
ambient light brightness and colour, the phone's auto-exposure and
auto-white-balance decisions, and its internal colour processing. A ratio
between two channels (R/G, R/B or G/B) cancels some of these shared
influences, since a change in overall brightness tends to scale several
channels together while the ratio stays put. That is why the manual has
you try ratios until one gives a linear response against concentration.
Which ratio works best follows from the colour: a brown-red solution
absorbs blue, so the blue channel tends to fall as concentration rises,
and ratios involving it change the most. A ratio does not remove every
source of variation, so lighting and the phone's position should be the
same for the standards and the unknown.

## Comparing the two methods and their limitations

- The instrument method reads absorbance at a defined wavelength and is
  generally more precise and reproducible.
- The smartphone method is cheap and convenient but less precise: the
  camera's broad colour channels are not a narrow wavelength band.
- Automatic camera adjustments (auto-exposure, auto-white-balance, HDR)
  can shift results between photos taken under seemingly similar
  conditions, so keep the settings, the background, the distance and the
  lighting the same for every tube.
- One phone's calibration does not transfer to another phone, since
  sensors and image processing differ.
- Photograph the standards, the blank and the unknown together in one
  image where possible, so they share the same lighting.

These are general limitations of camera-based colorimetry. They are
background for interpreting your own results, not a diagnosis of any
particular number, and they should not be used to explain away an
unexpected result before checking your own standards, dilutions and
measurement conditions.

## Reading the calibration graph

The straight line through the standards is usually characterised by its
slope and by R-squared, which measures how closely the points follow the
line (1 is a perfect fit). A high R-squared shows the standards were
prepared and measured consistently; it does not by itself prove the
unknown is right. The unknown's concentration is read by locating its
absorbance (or ratio) on the vertical axis and finding the matching
concentration on the horizontal axis. The unknown must fall inside the
range of the standards.

## Common sources of error

- Standards diluted inaccurately, or flasks not filled exactly to the mark.
- Reagents added in the wrong order, or the colour not given time to
  develop.
- A cuvette that is dirty, scratched, or not wiped dry, or not always
  inserted the same way round.
- Air bubbles in the light path.
- Using a different blank from the one the instrument was zeroed on.
- For the phone method, changing distance, lighting or camera settings
  between tubes.
