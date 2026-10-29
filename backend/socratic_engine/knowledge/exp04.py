"""Experiment 4 knowledge model: iron in carbon steel by potentiometric
titration with potassium permanganate.

Authority: the IACHY102 manual's Experiment 4 section (5Fe2+ + MnO4- + 8H+ ->
5Fe3+ + Mn2+ + 4H2O; E = E0 + (RT/nF) ln([Fe3+]/[Fe2+]); endpoint from the
EMF-vs-volume S-curve or the peak of DeltaE/DeltaV against average volume;
N(steel) = 0.05 N x V / 20 mL; Fe in g/100 mL = N x 55.85 x 100 / 1000) and
knowledge/adjacent/exp04_potentiometric_titration.md. No measured data from
the practical appears here, and every question is answerable by a student who
has only a phone: the information to reason about is chemistry knowledge or is
stated in the question itself (source metadata + wording scan:
knowledge/phone_safe.py).

Pure authored data. Answer keys are regex groups matched deterministically;
nothing asks a model whether an answer is right.
"""

from __future__ import annotations

from dataclasses import replace

from .types import Concept, ConceptQuestion, Misconception, Stage, build

C = Concept

CONCEPTS = (
    C("redox_titration", "Redox titration",
      "A titration in which the analyte is oxidised or reduced by the titrant. Here iron(II) is oxidised by permanganate.",
      (), 3, "The experiment is a redox titration of iron with potassium permanganate."),
    C("redox_reaction", "The permanganate-iron reaction",
      "In acid, permanganate oxidises iron(II) to iron(III) and is itself reduced to manganese(II): five iron ions react with each permanganate ion.",
      ("redox_titration",), 3, "5 Fe2+ + MnO4- + 8 H+ gives 5 Fe3+ + Mn2+ + 4 H2O."),
    C("potentiometry", "Potentiometry",
      "Measuring the potential of a cell at essentially zero current while titrant is added, instead of watching an indicator change colour.",
      (), 3, "The endpoint is found from potential readings, not from a colour change."),
    C("electrodes", "Indicator and reference electrodes",
      "The indicator electrode responds to the ratio of the oxidised and reduced forms in solution; the reference electrode holds a fixed potential. The measured EMF is the difference between them.",
      ("potentiometry",), 2, "An inert indicator electrode and a reference electrode are used."),
    C("emf", "EMF",
      "The potential difference between the two electrodes, in millivolts. Because the reference stays fixed, changes in the EMF come from the indicator electrode.",
      ("electrodes",), 2, "The EMF is read after each addition of titrant."),
    C("nernst", "The Nernst equation",
      "E = E0 + (RT/nF) ln([oxidised]/[reduced]). The potential depends on the ratio of the two forms, not on how much of either is present.",
      ("emf",), 3, "It explains why the EMF changes slowly and then jumps."),
    C("s_curve", "The S-shaped titration curve",
      "EMF plotted against titrant volume rises slowly, then jumps steeply around the equivalence point, then levels off again.",
      ("nernst", "redox_reaction"), 3, "The steep part of the curve marks the endpoint."),
    C("endpoint", "Endpoint and equivalence point",
      "The equivalence point is where exactly the stoichiometric amount of titrant has been added; the endpoint is the point located from the data, ideally the same place.",
      ("s_curve",), 3, "The result of the plot is the endpoint volume."),
    C("derivative_method", "The derivative method",
      "Dividing the change in EMF by the change in volume for each pair of readings and plotting it against the average volume turns the steepest part of the S-curve into a sharp peak whose top is the endpoint.",
      ("endpoint",), 3, "Delta E / Delta V against average volume."),
    C("self_indicator", "Permanganate as its own indicator",
      "Permanganate is intensely purple and its product, manganese(II), is almost colourless, so in an ordinary titration the first lasting pink colour signals the endpoint.",
      ("redox_reaction",), 1, "The potentiometric method does not depend on seeing that colour."),
    C("normality", "Normality and equivalents",
      "Equivalents per litre. At the equivalence point the equivalents of titrant equal the equivalents of analyte, so N1 x V1 = N2 x V2.",
      ("endpoint",), 3, "N(steel) = 0.05 x V(endpoint) / 20."),
    C("equivalent_weight", "Equivalent weight of iron",
      "The mass of iron that supplies one mole of electrons. Iron(II) to iron(III) is a one-electron change, so the equivalent weight is the atomic weight, 55.85 g.",
      ("normality",), 2, "Converts normality into grams of iron."),
    C("iron_content", "Iron content of the steel",
      "The normality of the steel solution multiplied by the equivalent weight of iron gives grams of iron per litre; scaling gives the amount in the stated volume.",
      ("normality", "equivalent_weight"), 3, "The reported quantity is grams of iron per 100 mL."),
    C("sample_preparation", "Preparing the steel solution",
      "The steel is dissolved in acid so the iron is in solution as iron(II). Only iron that is in solution as iron(II) is measured.",
      ("redox_titration",), 2, "The titration measures what the dissolving step has put into solution."),
    C("error_sources", "Sources of error",
      "Large titrant additions near the jump, iron(II) oxidised by air before titration, incomplete dissolution of the steel, fouled electrodes and unit slips all affect the result.",
      ("derivative_method", "iron_content"), 3, "Used to judge a result and to explain a bad one."),
)

ALIASES = {
    "redox_titration": (r"\bredox", r"\boxidation\b", r"\breduction\b", r"\boxidis", r"\boxidiz"),
    "redox_reaction": (r"\bpermanganate", r"\bkmno4", r"\bmno4", r"\b5 ?fe", r"\bwhy (is )?acid"),
    "potentiometry": (r"\bpotentiomet", r"\bwhy (do we|are we) (use|measure) (emf|potential)", r"\bpotential measure"),
    "electrodes": (r"\belectrode", r"\bcalomel", r"\bplatinum", r"\breference"),
    "emf": (r"\bemf\b", r"\bmillivolt", r"\bpotential difference"),
    "nernst": (r"\bnernst", r"\be0\b", r"\bstandard potential", r"\blog ?ratio"),
    "s_curve": (r"\bs[- ]?curve", r"\bs[- ]shaped", r"\btitration curve", r"\bwhy .{0,25}(jump|steep)"),
    "endpoint": (r"\bendpoint", r"\bequivalence point", r"\bend point"),
    "derivative_method": (r"\bderivative", r"\bdelta ?e", r"\bde ?/ ?dv", r"\bpeak\b", r"\baverage volume"),
    "self_indicator": (r"\bself[- ]indicator", r"\bits own indicator", r"\bpink colou?r", r"\bpurple"),
    "normality": (r"\bnormality", r"\bequivalent\b", r"\bn1 ?v1", r"\bwhat is n\b"),
    "equivalent_weight": (r"\bequivalent weight", r"\b55\.85", r"\batomic weight"),
    "iron_content": (r"\biron content", r"\bpercentage of iron", r"\bg/100", r"\bhow much iron", r"\bamount of iron"),
    "sample_preparation": (r"\bdissol", r"\bdigest", r"\bsteel sample", r"\bprepar.{0,20}(solution|steel)"),
    "error_sources": (r"\bsources? of error", r"\bwhat can go wrong", r"\berrors?\b", r"\bwhy .{0,30}(wrong|off)"),
}

_CONCEPTS = tuple(replace(c, aliases=ALIASES.get(c.id, ())) for c in CONCEPTS)

MISCONCEPTIONS = (
    Misconception(
        "endpoint_at_max_emf", "derivative_method",
        "The endpoint is where the EMF itself is highest.",
        (r"endpoint.{0,30}(highest|maximum|max|largest|top)\s+(emf|potential|reading)",
         r"(highest|maximum|max|largest)\s+(emf|potential).{0,20}(is |gives |marks )?(the )?(end ?point|equivalence)"),
        "After the jump the EMF keeps rising or levels off. What is it that is largest at the equivalence point: the EMF, or how quickly the EMF changes with volume?",
        "The endpoint is where the EMF changes fastest with volume, which shows as the maximum of the change in EMF divided by the change in volume."),
    Misconception(
        "normality_is_molarity", "normality",
        "Normality and molarity are the same thing.",
        (r"normality (is|=|equals|means) (the )?(same as )?molarity",
         r"(normality|molarity) (and|or) (normality|molarity) (are|is) (the )?same"),
        "Permanganate in acid takes five electrons per ion. Is a litre of solution that is 0.01 molar in permanganate worth 0.01 equivalents, or more?",
        "Normality counts equivalents per litre. It equals molarity multiplied by the number of electrons transferred per formula unit, so the two differ for permanganate."),
    Misconception(
        "emf_depends_on_amount", "nernst",
        "The EMF depends on how much iron is present, so it changes at a steady rate throughout the titration.",
        (r"emf (depends|is based) on (the )?(amount|quantity|how much)",
         r"emf (changes|goes up|rises) (steadily|evenly|linearly|constantly)"),
        "The Nernst equation contains a logarithm of the ratio of the two forms. How does a logarithm behave when the bottom of the ratio gets close to zero?",
        "The potential depends on the ratio of iron(III) to iron(II), so it changes slowly at first and then jumps when almost all the iron(II) is used up."),
    Misconception(
        "pink_colour_needed", "self_indicator",
        "You must see the pink colour to know the endpoint, so potentiometry is just a different way to see colour.",
        (r"(need|must|have to) (see|watch) (the )?(pink|colou?r)",
         r"potentiometr.{0,40}(colou?r|pink|visible)"),
        "In a coloured or cloudy solution a colour change can be hard to judge. What measurement could replace judging colour by eye?",
        "Potentiometry uses a measured potential instead of a colour change, so it works even where the colour is hard to judge."),
    Misconception(
        "aliquot_ignored", "iron_content",
        "The normality of the steel solution is the same as the permanganate normality.",
        (r"(steel|iron) (solution )?normality (is|=|equals) (the )?(same as )?(permanganate|titrant|0\.05)",
         r"normality (of the )?(steel|iron).{0,20}(is|=) 0\.05"),
        "N1 x V1 = N2 x V2. If the volume of iron solution is 20 mL but the permanganate volume is a different number, can the two normalities be equal?",
        "The normality of the steel solution comes from N1 x V1 = N2 x V2, so it depends on both volumes and is not the permanganate normality."),
)

Q = ConceptQuestion

QUESTIONS = (
    # --- the redox titration
    Q("q4_what_is_redox", "redox_titration", "OBSERVATION",
      "In a redox titration the analyte is oxidised or reduced by the titrant. In this experiment, is permanganate acting as an oxidising agent or a reducing agent?",
      groups=((r"oxidi[sz]ing", r"oxidant", r"oxidi[sz]es", r"takes electrons", r"gains electrons", r"oxidising agent"),),
      need=1, source="THEORY",
      expected_reasoning="Permanganate oxidises iron(II) to iron(III), so it is the oxidising agent.",
      scaffold="Permanganate turns iron(II) into iron(III). Is it taking electrons from the iron or giving them?"),
    Q("q4_stoichiometry", "redox_reaction", "OBSERVATION",
      "In the equation 5 Fe2+ + MnO4- + 8 H+ gives 5 Fe3+ + Mn2+ + 4 H2O, how many iron(II) ions react with each permanganate ion?",
      groups=((r"\b5\b", r"\bfive\b"),),
      need=1, source="GIVEN_DATA_INTERPRETATION",
      expected_reasoning="The coefficients show five iron(II) ions per permanganate ion.",
      scaffold="Take the number written in front of Fe2+ in the equation: that is how many react per permanganate."),
    Q("q4_acid_why", "redox_reaction", "WHY",
      "The equation includes 8 H+ on the left. What does that tell you about the medium in which permanganate must work as written?",
      groups=((r"acid", r"h\+", r"hydrogen ion", r"acidic"),),
      need=1, source="CONCEPTUAL_REASONING",
      expected_reasoning="Hydrogen ions are consumed in the reaction, so it has to be carried out in acid.",
      scaffold="H+ is a reactant. What kind of solution supplies a lot of H+?"),
    # --- measuring potential
    Q("q4_why_potentiometry", "potentiometry", "WHY",
      "Why might measuring a potential be better than watching for a colour change when finding the endpoint of a titration?",
      groups=((r"colou?r", r"visual", r"by eye", r"subjective", r"judge", r"hard to see", r"cloudy", r"turbid"),
              (r"objective", r"reading", r"number", r"measure", r"precise", r"accurate", r"graph", r"plot", r"coloured", r"cloudy", r"turbid", r"works")),
      need=1, source="CONCEPTUAL_REASONING",
      expected_reasoning="A measured potential gives numbers that can be plotted, so the endpoint does not depend on judging a colour by eye, and it works in coloured or cloudy solutions.",
      scaffold="What is hard about judging a colour change in a coloured solution, and what could you do instead?"),
    Q("q4_two_electrodes", "electrodes", "WHY",
      "A potential can only be measured between two points. Why does the cell need a reference electrode as well as the indicator electrode?",
      groups=((r"fixed", r"constant", r"steady", r"known", r"stable", r"reference", r"compar"),
              (r"potential", r"emf", r"change", r"differ", r"measure")),
      need=2, source="THEORY",
      expected_reasoning="The reference electrode has a fixed potential, so any change in the measured EMF comes from the indicator electrode responding to the solution.",
      scaffold="One electrode must stay the same so that changes in the reading can be blamed on the other. Which one stays the same?"),
    # --- Nernst and the S-curve
    Q("q4_nernst_ratio", "nernst", "WHY",
      "According to the Nernst equation E = E0 + (RT/nF) ln([Fe3+]/[Fe2+]), does the potential depend on the amounts of iron(III) and iron(II) or on their ratio?",
      groups=((r"ratio", r"divided", r"relative", r"quotient", r"proportion"),),
      need=1, source="THEORY",
      expected_reasoning="The potential depends on the ratio [Fe3+]/[Fe2+] through a logarithm, not on the absolute amounts.",
      scaffold="Consider what sits inside the logarithm: it is one concentration divided by the other."),
    Q("q4_why_jump", "s_curve", "WHY",
      "Near the equivalence point a tiny extra amount of permanganate makes the EMF jump by a large amount. Why?",
      groups=((r"almost all", r"nearly all", r"used up", r"run(s)? out", r"almost no", r"very little", r"almost gone", r"little left", r"hardly any", r"all the iron"),
              (r"ratio", r"fe2\+", r"iron\(ii\)", r"log", r"fe3\+", r"change", r"big", r"large", r"sharp")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="Almost all the iron(II) has been used, so a very small addition changes the ratio of iron(III) to iron(II) enormously, and the logarithm of the ratio, and so the EMF, jumps.",
      scaffold="By the equivalence point there is hardly any iron(II) left. What does a tiny change in a very small number do to a ratio?"),
    Q("q4_before_after", "s_curve", "PREDICTION",
      "Describe how you expect the EMF to behave well before the equivalence point and well after it, compared with the jump itself.",
      groups=((r"slow", r"gradual", r"small", r"gentle", r"little", r"flat", r"level", r"steady", r"plateau"),
              (r"jump", r"steep", r"sharp", r"sudden", r"rapid", r"big", r"large", r"fast")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="Far from the equivalence point the EMF changes slowly; around it, it jumps steeply; after it, it levels off at a high value.",
      scaffold="Compare how fast the EMF changes far from the equivalence point with how fast it changes right at it."),
    # --- finding the endpoint
    Q("q4_endpoint_derivative", "derivative_method", "WHY",
      "Why is the endpoint taken at the maximum of the change in EMF divided by the change in volume (delta E / delta V), instead of at the highest EMF reading?",
      groups=((r"steep", r"fastest", r"most rapid", r"greatest change", r"largest change", r"jump", r"rate of change", r"slope"),
              (r"equivalence", r"endpoint", r"peak", r"maximum", r"sharp", r"highest", r"after", r"keeps rising", r"levels")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="The equivalence point is where the EMF changes fastest with volume; the EMF itself keeps rising or levels off afterwards, so its highest value does not mark the endpoint.",
      scaffold="Which is largest at the equivalence point: the EMF, or how quickly the EMF is changing?"),
    Q("q4_derivative_table", "derivative_method", "INTERPRETATION",
      "Between 8.0 and 8.2 mL the EMF rises from 400 to 520 mV. Between 8.2 and 8.4 mL it rises from 520 to 540 mV. Which interval has the larger delta E / delta V, and what does that say about where the endpoint lies?",
      groups=((r"8\.0", r"first", r"600", r"\b120\b", r"earlier", r"lower volume"),
              (r"endpoint", r"equivalence", r"near", r"close", r"around", r"between", r"before", r"steep")),
      need=2, source="GIVEN_DATA_INTERPRETATION",
      expected_reasoning="The first interval changes by 120 mV over 0.2 mL, which is 600 mV per mL, against 100 mV per mL for the second. The endpoint is around the first interval, close to 8.1 mL.",
      scaffold="Divide each EMF change by 0.2 mL and compare the two numbers."),
    Q("q4_small_portions", "error_sources", "CONSEQUENCE",
      "Why should the titrant be added in smaller portions near the jump than far from it?",
      groups=((r"close", r"closer", r"near", r"precise", r"locat", r"resolv", r"accurate", r"miss", r"find", r"detail", r"overshoot"),
              (r"endpoint", r"equivalence", r"jump", r"peak", r"reading", r"point", r"volume")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="The information that locates the endpoint is in the readings around the jump; with large portions there would be no reading close enough to find it accurately.",
      scaffold="Most of the change happens in a very small range of volume. What do you need there to pin the endpoint down?"),
    # --- normality and iron content
    Q("q4_normality_calc", "normality", "INTERPRETATION",
      "20 mL of an iron solution is titrated with 0.05 N permanganate and the endpoint is at 8.0 mL. Using N1 x V1 = N2 x V2, what is the normality of the iron solution?",
      groups=((r"0?\.02\b", r"0\.020", r"2\s*x\s*10\^?\s*-?\s*2", r"2e-2"),),
      need=1, source="GIVEN_DATA_INTERPRETATION",
      expected_reasoning="N = 0.05 x 8.0 / 20 = 0.02 N.",
      scaffold="Multiply the permanganate normality by its volume and divide by the volume of iron solution."),
    Q("q4_eq_weight", "equivalent_weight", "WHY",
      "The equivalent weight of iron in this titration equals its atomic weight. Why?",
      groups=((r"one electron", r"1 electron", r"single electron", r"one-electron", r"\b1\b.{0,15}electron"),
              (r"fe2\+", r"iron", r"iron\(ii\)", r"fe3\+", r"oxidis", r"changes", r"equivalent", r"atomic")),
      need=1, source="CONCEPTUAL_REASONING",
      expected_reasoning="Iron(II) becomes iron(III) by losing one electron, so one mole of iron is one equivalent and the equivalent weight equals the atomic weight.",
      scaffold="How many electrons does each iron(II) ion lose to become iron(III)?"),
    Q("q4_mass_calc", "iron_content", "INTERPRETATION",
      "A steel solution has a normality of 0.02 N and the equivalent weight of iron is 55.85. About how many grams of iron are in 1 litre of the solution?",
      groups=((r"1\.1[0-9]*", r"1\.12", r"1\.117"),),
      need=1, source="GIVEN_DATA_INTERPRETATION",
      expected_reasoning="0.02 equivalents per litre x 55.85 g per equivalent is about 1.12 g per litre.",
      scaffold="Multiply the normality by the equivalent weight."),
    Q("q4_units_slip", "iron_content", "CONSEQUENCE",
      "A student works out the grams of iron per litre correctly but then reports it as grams per 100 mL without scaling. By roughly what factor is the reported number wrong, and in which direction?",
      groups=((r"\b10\b", r"ten", r"factor of 10", r"10 ?x", r"10 times"),
              (r"too (big|large|high)", r"larger", r"bigger", r"overestimate", r"higher", r"10 times", r"ten times")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="100 mL is one tenth of a litre, so the correct per-100 mL figure is ten times smaller; the unscaled number is ten times too large.",
      scaffold="How many 100 mL portions make a litre, and which number should be smaller?"),
    # --- accuracy and errors
    Q("q4_air_oxidation", "error_sources", "CONSEQUENCE",
      "Some of the iron(II) in the steel solution is oxidised by air to iron(III) before the titration starts. How does that affect the iron content calculated from the titration, and why?",
      groups=((r"lower", r"less", r"under", r"smaller", r"too low", r"decreas", r"reduce"),
              (r"permanganate", r"titrant", r"fe2\+", r"iron\(ii\)", r"only", r"react", r"measure", r"oxidis")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="Permanganate only reacts with iron(II), so iron already oxidised is not counted and the calculated iron content comes out too low.",
      scaffold="Which form of iron does the permanganate react with? What happens to iron that is already in the other form?"),
    Q("q4_incomplete_dissolve", "sample_preparation", "PREDICTION",
      "Suppose some of the steel did not dissolve. Would the calculated iron content come out too high, too low or unaffected, and why?",
      groups=((r"too low", r"lower", r"less", r"under", r"smaller", r"decreas"),
              (r"not (all |in )?(dissolv|solution)", r"undissolv", r"missing", r"solution", r"only", r"dissolved", r"counted")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="Only dissolved iron is titrated, so undissolved iron is not counted and the result is too low.",
      scaffold="The titration only sees iron that is in solution. What happens to iron that stayed behind?"),
    Q("q4_transfer_other", "redox_titration", "TRANSFER",
      "The same potentiometric approach is used to find the amount of chloride with silver nitrate. Using what you know from this experiment, what kind of measurement would you plot against volume, and where would you find the endpoint?",
      groups=((r"potential", r"emf", r"electrode", r"millivolt"),
              (r"jump", r"steep", r"sharp", r"derivative", r"peak", r"maximum", r"change")),
      need=2, source="CONCEPTUAL_REASONING",
      expected_reasoning="Plot the electrode potential against titrant volume; the endpoint is where the potential changes fastest, found from the steep part or the peak of the derivative.",
      scaffold="What is measured after each addition, and where is the endpoint on that curve?"),
    Q("q4_transfer_plot", "derivative_method", "TRANSFER",
      "Another titration gives a very shallow rise in EMF with no clear jump. What does that suggest about using this method for it, and what might help?",
      groups=((r"difficult", r"hard", r"unclear", r"not clear", r"poor", r"unsuitable", r"no sharp", r"weak", r"can'?t", r"cannot"),
              (r"smaller", r"finer", r"different", r"more\s+(readings|points)", r"derivative", r"another method", r"stronger", r"change")),
      need=1, source="CONCEPTUAL_REASONING",
      expected_reasoning="A weak jump makes the endpoint hard to locate; finer additions near the change or a different method would help.",
      scaffold="Without a sharp jump the endpoint is hard to pin down. What could make the jump easier to resolve?"),
)

STAGES = (
    Stage("e4_reaction", "The redox titration of iron",
          "Experiment 4 finds how much iron a carbon steel contains. The steel is dissolved in acid so the iron is "
          "in solution as iron(II), and it is titrated with potassium permanganate. In acid, five iron(II) ions "
          "react with each permanganate ion: 5 Fe2+ + MnO4- + 8 H+ gives 5 Fe3+ + Mn2+ + 4 H2O.",
          ("redox_titration", "redox_reaction", "sample_preparation"),
          ("q4_what_is_redox", "q4_stoichiometry", "q4_acid_why")),
    Stage("e4_potential", "Measuring a potential instead of a colour",
          "Instead of watching for a colour change, the titration follows the potential of a cell: an indicator "
          "electrode responds to the solution and a reference electrode stays fixed, and the EMF between them is "
          "read in millivolts after each addition of titrant.",
          ("potentiometry", "electrodes", "emf"),
          ("q4_why_potentiometry", "q4_two_electrodes")),
    Stage("e4_nernst", "Why the EMF jumps",
          "The potential follows E = E0 + (RT/nF) ln([Fe3+]/[Fe2+]), so it depends on the ratio of the two forms "
          "of iron. As the iron(II) runs out the ratio changes very rapidly, giving an S-shaped curve.",
          ("nernst", "s_curve"),
          ("q4_nernst_ratio", "q4_why_jump", "q4_before_after")),
    Stage("e4_endpoint", "Finding the endpoint",
          "The endpoint can be read from the S-curve or, more objectively, from the change in EMF divided by the "
          "change in volume plotted against the average volume, which has a sharp peak at the endpoint.",
          ("endpoint", "derivative_method"),
          ("q4_endpoint_derivative", "q4_derivative_table", "q4_small_portions")),
    Stage("e4_iron", "From endpoint to iron content",
          "At the equivalence point the equivalents of permanganate equal the equivalents of iron(II), so "
          "N1 x V1 = N2 x V2 gives the normality of the steel solution. Multiplying by the equivalent weight of "
          "iron, 55.85, gives grams of iron.",
          ("normality", "equivalent_weight", "iron_content"),
          ("q4_normality_calc", "q4_eq_weight", "q4_mass_calc", "q4_units_slip")),
    Stage("e4_errors", "Accuracy and what can go wrong",
          "The result is only as good as the iron that was put into solution as iron(II) and the readings around "
          "the jump. Air oxidation, incomplete dissolving and unit slips are the common causes of a wrong answer.",
          ("error_sources", "sample_preparation"),
          ("q4_air_oxidation", "q4_incomplete_dissolve")),
)

ASSESSMENT = (
    "q4_why_potentiometry", "q4_why_jump", "q4_endpoint_derivative", "q4_small_portions",
    "q4_normality_calc", "q4_eq_weight", "q4_air_oxidation", "q4_transfer_other", "q4_transfer_plot",
)

STARTER_QUESTIONS = (
    "Why does the EMF jump at the endpoint?",
    "What is the Nernst equation?",
    "Why do we use the derivative plot (ΔE/ΔV) to find the endpoint?",
    "What is the difference between normality and molarity?",
    "Why must the titration be done in acid?",
    "What are the sources of error in this experiment?",
    "How do we get the iron content from the endpoint volume?",
)

KNOWLEDGE = build(
    "exp04", _CONCEPTS, (), MISCONCEPTIONS, QUESTIONS, ASSESSMENT, STAGES, STARTER_QUESTIONS,
    closing_summary=(
        "the permanganate-iron redox reaction, why a measured potential can replace a colour change, how the "
        "Nernst equation gives an S-shaped curve, finding the endpoint from the derivative plot, turning the "
        "endpoint volume into the iron content, and the main sources of error."
    ),
    topics_hint=(
        "the redox reaction, potentiometry and the Nernst equation, finding the endpoint, "
        "normality and the iron calculation, and sources of error"
    ),
)
