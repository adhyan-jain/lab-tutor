"""Experiment 3 knowledge model: colorimetric estimation of Ni2+ (conventional
spectrophotometer method and the smartphone RGB method).

Authority: the IACHY102 manual's Experiment 3 summary (Ni2+ + DMG in alkaline
solution gives pink Ni(dmg)2, oxidised by K3[Fe(CN)6] to a brown-red complex
measured at 440 nm; standards of 2, 4, 6 and 8 ppm from a 100 ppm stock; Beer's
law A = epsilon c l; RGB ratio method) and knowledge/adjacent/
exp03_beer_lambert_and_color_science.md. The follow-up questions are the
course's own MCQs (MCQ_Colorimetric_Estimation_Ni2plus, questions 11-20), kept
as written with their answer key. No measured data from the practical appears
here, and every question is answerable by a student who has only a phone.

Pure authored data. Nothing here asks a model whether an answer is right:
answer keys are regex groups matched deterministically.
"""

from __future__ import annotations

from dataclasses import replace

from .types import Concept, ConceptQuestion, Stage, build

C = Concept

CONCEPTS = (
    C("nickel_background", "Nickel in everyday use",
      "Nickel is normally +2 in its compounds. A thin nickel plating protects metal from corrosion and wear, and skin contact with nickel can cause an allergy called nickel-eczema.",
      (), 1, "Why the nickel in a sample is worth measuring."),
    C("nickel_dmg", "The nickel colour reaction",
      "In alkaline solution nickel(II) reacts with dimethylglyoxime (DMG) to form a pink Ni(dmg)2 complex. Potassium ferricyanide then oxidises it to a soluble brown-red complex, and that is the colour that is measured.",
      (), 3, "The colour that is measured comes from this reaction."),
    C("wavelength", "Choosing the wavelength",
      "The reading is taken near the wavelength where the coloured complex absorbs most, 440 nm here. The signal is largest there, and small slips in setting the wavelength change it least.",
      ("nickel_dmg",), 2, "The manual names 440 nm for the brown-red complex."),
    C("beer_law", "The Beer-Lambert law",
      "Absorbance is proportional to concentration: A = epsilon x c x l. For one species, one wavelength and one cuvette width, a more concentrated solution absorbs proportionally more.",
      (), 3, "This is why colour intensity can measure how much nickel there is."),
    C("ppm_dilution", "Concentration in ppm and dilution",
      "In a dilute water solution, ppm is milligrams of solute per litre. Diluting keeps the amount of solute and spreads it over more volume, so c1 x V1 = c2 x V2.",
      ("beer_law",), 3, "The standards are made by diluting a 100 ppm nickel stock in 50 mL flasks."),
    C("blank", "The blank",
      "A reference solution without the nickel. Readings are taken against it, so the numbers for the standards and the unknown show only the nickel. In this experiment the blank is the sodium hydroxide solution.",
      ("beer_law",), 3, "Absorbance is measured against a blank."),
    C("calibration_curve", "The calibration curve",
      "A graph of absorbance against the known concentrations of the standards, with concentration along the bottom. If Beer's law holds it is a straight line through, or very near, the origin, and the unknown's concentration is read from it.",
      ("beer_law", "ppm_dilution", "blank"), 3, "The unknown's result comes from this line."),
    C("rgb_pixel", "How a phone stores colour",
      "Each pixel of a photo is stored as three numbers, for red, green and blue. In a standard 24-bit image each number goes from 0 to 255, so 0, 0, 0 is black and 255, 255, 255 is white.",
      (), 2, "The smartphone method reads these three numbers for each sample."),
    C("additive_colour", "Additive colour",
      "Digital colour is made by adding red, green and blue light in different amounts, which is why RGB is called an additive colour model.",
      ("rgb_pixel",), 2, "It explains why the three numbers can describe any colour on the screen."),
    C("phone_method", "The smartphone colour method",
      "The standards, the blank and the unknown are photographed, their RGB values are read with an app, and the channel or ratio that changes steadily with concentration is used. A plain white background and the same lighting for every sample keep the comparison fair.",
      ("rgb_pixel", "calibration_curve"), 3, "It replaces the spectrophotometer with a phone camera."),
)

ALIASES = {
    "nickel_background": (r"\boxidation state", r"\beczema", r"\bplating", r"\bnickel[- ](plat|allerg)", r"\bwhy (measure|estimate) nickel"),
    "nickel_dmg": (r"\bdmg\b", r"\bdimethylglyoxime", r"\bni\(dmg\)", r"\bferricyanide", r"\bk3\[?fe", r"\bpink\b", r"\bbrown[- ]red"),
    "wavelength": (r"\b440\b", r"\bwavelength", r"\blambda[- ]?max", r"\bλ ?max"),
    "beer_law": (r"\bbeer", r"\blambert", r"\babsorbance", r"\bmolar absorptivity", r"\bepsilon"),
    "ppm_dilution": (r"\bppm\b", r"\bdilut", r"\bstock", r"\bstandard solutions?", r"\bc1 ?v1"),
    "blank": (r"\bblank\b", r"\bzero (the )?(instrument|reading)"),
    "calibration_curve": (r"\bcalibration", r"\bstraight line", r"\bstandard curve", r"\bthrough the origin"),
    "rgb_pixel": (r"\brgb\b", r"\bpixel", r"\b24[- ]bit", r"\b256\b", r"\b255\b"),
    "additive_colour": (r"\badditive", r"\bsubtractive", r"\bcolou?r (space|model)"),
    "phone_method": (r"\bsmartphone", r"\bphone method", r"\bwhite (paper )?background", r"\brgb (tool|app)", r"\bdigital imaging"),
}

_CONCEPTS = tuple(replace(c, aliases=ALIASES.get(c.id, ())) for c in CONCEPTS)

Q = ConceptQuestion

QUESTIONS = (
    # --- MCQ follow-ups (MCQ_Colorimetric_Estimation_Ni2plus, questions 1-10)
    Q("q3_mcq1", "nickel_background", "OBSERVATION",
      "The most common oxidation state of nickel in its compounds is:\na) +1\nb) +2\nc) +3\nd) +4\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\+\s*2\b", r"\b2\s*\+", r"^\W*2\W*$", r"plus\s*(2|two)"),),
      need=1, source="THEORY",
      expected_reasoning="Nickel is normally +2 in its compounds.",
      scaffold="Think of the Ni²⁺ ion that this whole experiment measures. What charge does it have?"),
    Q("q3_mcq2", "nickel_background", "OBSERVATION",
      "Which skin disorder can be caused by nickel exposure?\na) Psoriasis\nb) Vitiligo\nc) Nickel-eczema\nd) Acne\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?c\)?\W*$", r"eczema"),),
      need=1, source="THEORY",
      expected_reasoning="Nickel contact can cause nickel-eczema, a skin allergy.",
      scaffold="The name of this skin disorder includes the metal. Which option is it?"),
    Q("q3_mcq3", "nickel_background", "OBSERVATION",
      "A thin layer of nickel plated on a metal object mainly provides:\na) Corrosion and wear resistance\nb) Electrical insulation\nc) Lower density\nd) Magnetic shielding only\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?a\)?\W*$", r"corrosion", r"wear\s+resist"),),
      need=1, source="THEORY",
      expected_reasoning="A thin nickel plating protects the metal underneath from corrosion and wear.",
      scaffold="Why would anyone coat steel with a thin layer of nickel? Think of what rust does."),
    Q("q3_mcq4", "nickel_dmg", "OBSERVATION",
      "In alkaline medium, Ni²⁺ reacts with dimethylglyoxime (DMG) to form:\na) A blue Ni(OH)₂ precipitate\nb) A pink-coloured Ni(dmg)₂ complex\nc) A green nickel carbonate\nd) A colourless Ni–DMG salt\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\bpink\b", r"ni\s*\(\s*dmg\s*\)"),),
      need=1, source="THEORY",
      expected_reasoning="In alkaline solution nickel and DMG form a pink Ni(dmg)2 complex.",
      scaffold="The first colour in the nickel-DMG reaction scheme is not blue, green or colourless. Which colour is it?"),
    Q("q3_mcq5", "nickel_dmg", "OBSERVATION",
      "The oxidizing agent used to convert Ni(dmg)₂ into its soluble coloured form is:\na) NaOH\nb) K₃[Fe(CN)₆]\nc) HCl\nd) NiSO₄\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"ferricyanide", r"k\s*[3₃]\s*\[?\s*fe"),),
      need=1, source="THEORY",
      expected_reasoning="Potassium ferricyanide oxidises the pink complex to the soluble brown-red one.",
      scaffold="The oxidising agent is a potassium salt of an iron-cyanide complex. Which option is that?"),
    Q("q3_mcq6", "nickel_dmg", "OBSERVATION",
      "The oxidized Ni–DMG complex is:\na) Colourless\nb) Blue\nc) Brown-red and water soluble\nd) Yellow-green and insoluble\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?c\)?\W*$", r"brown[- ]?red", r"water[- ]?soluble"),),
      need=1, source="THEORY",
      expected_reasoning="The oxidised complex is brown-red and dissolves in water, so it can be measured in solution.",
      scaffold="The oxidised complex has to be dissolved to be measured, and it is coloured. Which option fits both?"),
    Q("q3_mcq7", "wavelength", "OBSERVATION",
      "The absorption maximum (λmax) of the oxidized complex used for measurement is:\na) 250 nm\nb) 440 nm\nc) 600 nm\nd) 750 nm\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\b440\b"),),
      need=1, source="THEORY",
      expected_reasoning="The manual names 440 nm for the brown-red complex.",
      scaffold="The brown-red complex absorbs in the blue end of the spectrum. Which wavelength is that?"),
    Q("q3_mcq8", "beer_law", "OBSERVATION",
      "The Beer–Lambert law is written as:\na) A = c/εl\nb) A = εcl\nc) A = ε/cl\nd) A = l/εc\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"(ε|epsilon)\s*[*x×]?\s*c\s*[*x×]?\s*l\b"),),
      need=1, source="THEORY",
      expected_reasoning="Absorbance equals molar absorptivity times concentration times path length: A = epsilon c l.",
      scaffold="Absorbance is proportional to concentration. So c and l multiply epsilon, they do not divide it."),
    Q("q3_mcq9", "beer_law", "OBSERVATION",
      "Absorbance is defined as:\na) A = log(I/I₀)\nb) A = I₀ − I\nc) A = log(I₀/I)\nd) A = I₀ × I\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?c\)?\W*$", r"log\s*\(?\s*i\s*[0₀o]\s*/\s*i\s*\)?"),),
      need=1, source="THEORY",
      expected_reasoning="Absorbance is the logarithm of incident light over transmitted light: A = log(I0 / I).",
      scaffold="More absorbed light means less comes out. Should the ratio have the incoming light on top or the outgoing?"),
    Q("q3_mcq10", "beer_law", "OBSERVATION",
      "The units of molar absorptivity (ε) are:\na) mol L⁻¹\nb) L mol⁻¹ cm⁻¹\nc) cm mol⁻¹\nd) ppm cm⁻¹\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"l\s*mol\W{0,2}[-−⁻]\s*[1¹]\s*cm", r"l\s*/\s*\(?\s*mol\s*[*x×·]?\s*cm"),),
      need=1, source="THEORY",
      expected_reasoning="Since A has no units, epsilon has units of litres per mole per centimetre.",
      scaffold="A has no units, and c is in mol per litre and l in cm. What units must epsilon have to cancel them?"),
    # --- MCQ follow-ups (MCQ_Colorimetric_Estimation_Ni2plus, questions 11-20)
    Q("q3_mcq11", "ppm_dilution", "INTERPRETATION",
      "If 2 mL of a 100 ppm Ni²⁺ stock solution is made up to 50 mL, the concentration is:\na) 2 ppm\nb) 4 ppm\nc) 6 ppm\nd) 8 ppm\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\b4\s*ppm\b", r"^\W*4\W*$"),),
      need=1, source="THEORY",
      expected_reasoning="Dilution keeps the amount of nickel: 100 ppm x 2 mL = c x 50 mL, so the flask is 4 ppm.",
      scaffold="Use c1 x V1 = c2 x V2, with the stock as c1 and the full flask as c2."),
    Q("q3_mcq12", "blank", "WHY",
      "In this experiment, the absorbance of the coloured solutions is measured against:\na) Distilled water only\nb) A blank (NaOH solution)\nc) The unknown sample\nd) Air\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\bblank\b", r"\bnaoh\b"),),
      need=1, source="THEORY",
      expected_reasoning="Readings are taken against a blank, here the sodium hydroxide solution, which has no nickel, so the readings show only the nickel.",
      scaffold="The blank has everything except the nickel. Which of these could the instrument be set to zero on, so only the nickel shows?"),
    Q("q3_mcq13", "calibration_curve", "INTERPRETATION",
      "A calibration plot that is a straight line passing through the origin shows that:\na) The solution is saturated\nb) The data obey Beer's law\nc) The instrument is faulty\nd) The reaction is incomplete\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"(?<!not )(?<!n't )obey\w*\s+beer", r"(?<!not )(?<!n't )follow\w*\s+beer"),),
      need=1, source="THEORY",
      expected_reasoning="Absorbance proportional to concentration, with zero reading at zero nickel, gives a straight line through the origin: that is Beer's law holding.",
      scaffold="If no nickel gives no absorbance, and doubling nickel doubles absorbance, what shape and starting point does the line have?"),
    Q("q3_mcq14", "calibration_curve", "INTERPRETATION",
      "In the calibration graph for colorimetry, the axes are:\na) Absorbance on X, concentration on Y\nb) Concentration (ppm) on X, absorbance on Y\nc) Time on X, absorbance on Y\nd) Wavelength on X, concentration on Y\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"concentration\s*(\(ppm\))?\s*on\s*(the\s*)?x"),),
      need=1, source="THEORY",
      expected_reasoning="The concentrations of the standards, which you choose, go along the bottom axis and the measured absorbance goes up the side.",
      scaffold="The standards are what you choose, and absorbance is what the instrument gives back. Which goes along the bottom?"),
    Q("q3_mcq15", "rgb_pixel", "INTERPRETATION",
      "A 24-bit digital image stores each pixel as:\na) 24 bits of red only\nb) 8 bits each for R, G and B\nc) 12 bits for colour and 12 for brightness\nd) 3 bits each for R, G and B\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"8\s*bits?\s*each", r"8\s*bits?\s*(for|per)\s*(each|every)"),),
      need=1, source="THEORY",
      expected_reasoning="A 24-bit pixel is three channels, red, green and blue, each stored in 8 bits.",
      scaffold="A 24-bit pixel is split equally between three colour channels. How many bits does each get?"),
    Q("q3_mcq16", "rgb_pixel", "INTERPRETATION",
      "Each of the R, G and B intensities can take how many levels?\na) 100\nb) 128\nc) 256\nd) 1024\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?c\)?\W*$", r"\b256\b"),),
      need=1, source="THEORY",
      expected_reasoning="Eight bits give 2^8 = 256 levels, numbered 0 to 255.",
      scaffold="Each channel uses 8 bits. How many different numbers can 8 bits hold?"),
    Q("q3_mcq17", "rgb_pixel", "INTERPRETATION",
      "A pixel with R = 0, G = 0, B = 0 appears:\na) White\nb) Black\nc) Grey\nd) Red\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\bblack\b"),),
      need=1, source="THEORY",
      expected_reasoning="With all three channels at 0 no light is added, so the pixel is black.",
      scaffold="Think of all three colours switched off, so no light at all is added."),
    Q("q3_mcq18", "rgb_pixel", "INTERPRETATION",
      "A pixel with R = 255, G = 255, B = 255 appears:\na) White\nb) Black\nc) Yellow\nd) Transparent\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?a\)?\W*$", r"\bwhite\b"),),
      need=1, source="THEORY",
      expected_reasoning="With all three channels at 255 the maximum of every colour is added, giving white.",
      scaffold="Now picture all three colours at full strength at once."),
    Q("q3_mcq19", "additive_colour", "INTERPRETATION",
      "The RGB model is an example of:\na) A subtractive colour space\nb) An additive colour space\nc) A monochrome space\nd) A fluorescence scale\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"\badditive\b"),),
      need=1, source="THEORY",
      expected_reasoning="RGB builds colours by adding red, green and blue light, so it is an additive colour space.",
      scaffold="RGB makes colours by adding light together. Is that additive or subtractive?"),
    Q("q3_mcq20", "phone_method", "WHY",
      "In the smartphone method, the sample photographs are taken against a white paper background in order to:\na) Increase the concentration\nb) Give a uniform background and consistent lighting for comparing colours\nc) Convert the colour to black\nd) Avoid using the RGB app\nReply with a, b, c or d.",
      groups=((r"^\W*(?:option\s*|answer\s*|ans\s*)?\(?b\)?\W*$", r"uniform\s+background", r"consistent\s+lighting"),),
      need=1, source="THEORY",
      expected_reasoning="A plain white background gives every sample the same surroundings and lighting, so differences in colour come from the nickel and not from the setting.",
      scaffold="A plain white background makes every tube sit in the same surroundings. What does that give you when you compare colours?"),
)

STAGES = (
    Stage("e3_chemistry", "The nickel colour reaction",
          "In alkaline solution nickel(II) reacts with dimethylglyoxime (DMG) to form a pink Ni(dmg)2 complex. "
          "Potassium ferricyanide then oxidises it to a soluble brown-red complex, and that is the colour measured, "
          "at about 440 nm.",
          ("nickel_background", "nickel_dmg", "wavelength"),
          ("q3_mcq1", "q3_mcq2", "q3_mcq3", "q3_mcq4", "q3_mcq5", "q3_mcq6", "q3_mcq7"),
          max_questions=3),
    Stage("e3_standards", "Standards, dilution and the blank",
          "The standards are 1, 2, 3 and 4 mL of a 100 ppm nickel stock in 50 mL flasks (2, 4, 6 and 8 ppm), and "
          "the unknown comes in its own flask. Readings are taken against a blank, the sodium hydroxide solution.",
          ("ppm_dilution", "blank"),
          ("q3_mcq11", "q3_mcq12")),
    Stage("e3_calibration", "The calibration line",
          "The absorbance of each standard is plotted against its concentration. If Beer's law holds, the points "
          "fall on a straight line through, or very near, the origin, and the unknown's concentration is read from "
          "that line.",
          ("beer_law", "calibration_curve"),
          ("q3_mcq8", "q3_mcq9", "q3_mcq10", "q3_mcq13", "q3_mcq14"),
          max_questions=3),
    Stage("e3_rgb", "How a phone records colour",
          "A phone photo stores each pixel as three numbers, for red, green and blue light. Mixing the three in "
          "different amounts makes every colour in the photo.",
          ("rgb_pixel", "additive_colour"),
          ("q3_mcq15", "q3_mcq16", "q3_mcq17", "q3_mcq18", "q3_mcq19"),
          max_questions=3),
    Stage("e3_phone", "Getting a fair photograph",
          "In the phone method the standards, the unknown and the blank are lined up and photographed together "
          "against white paper from about 50 cm, so they share the same lighting. The RGB response is then plotted "
          "against concentration to make the calibration line.",
          ("phone_method",),
          ("q3_mcq20",),
          max_questions=1),
)

ASSESSMENT = ("q3_mcq11", "q3_mcq12", "q3_mcq13", "q3_mcq19", "q3_mcq20")

STARTER_QUESTIONS = (
    "What does DMG do in this experiment?",
    "What is Beer's law?",
    "Why do we measure against a blank?",
    "Why should the calibration line pass through the origin?",
    "How do you make the standard solutions?",
    "How does a phone camera record colour?",
    "Why is a white background used for the photographs?",
)

KNOWLEDGE = build(
    "exp03", _CONCEPTS, (), (), QUESTIONS, ASSESSMENT, STAGES, STARTER_QUESTIONS,
    closing_summary=(
        "how nickel gives a measurable colour, how standards are diluted and why a blank is used, what Beer's "
        "law says and what a calibration line looks like, and how a phone records colour for the smartphone method."
    ),
    topics_hint=(
        "the nickel colour reaction, Beer's law, standards and dilution, the blank, the calibration line, "
        "and the smartphone colour method"
    ),
)
