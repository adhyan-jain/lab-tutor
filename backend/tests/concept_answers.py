"""Model answers for the Exp7 concept questions, shared by the tests.

Each is what a student who understands the idea might plausibly write; the
tests assert every one classifies CORRECT, which keeps the authored answer
keys in knowledge/exp07.py honest.
"""

GOOD = {
    "q_ch4_atoms": "5 atoms, one carbon and four hydrogens",
    "q_ch4_geometry": "tetrahedral because the bonds repel and stay far apart",
    "q_ch4_why_tetra": "the bonds repel each other so they spread as far apart as possible",
    "q_hybrid_why": "hybridisation, the orbitals mix to form four equivalent sp3 orbitals",
    "q_dft_idea": "it is much faster and cheaper than the exact treatment so larger molecules are practical",
    "q_pattern_predict": "the values would shift slightly with the method but stay broadly similar",
    "q_opt_predict": "No, probably not, it is only a rough guess so the energy is not the lowest",
    "q_opt_why": "It lowers the energy so the geometry is at its minimum before the orbital calculation",
    "q_opt_observe": "It moved the atoms to a lower energy, more stable structure",
    "q_energy_lower": "A lower more negative energy means a more stable arrangement",
    "q_opt_consequence": "The orbital energies would be wrong because the geometry is not relaxed",
    "q_geom_use_opt": "It is the optimised lowest energy structure, so the geometry is more accurate",
    "q_orbital_predict": "It shows the probability of finding an electron, the electron density in space",
    "q_homo_meaning": "HOMO is the highest occupied molecular orbital and LUMO is the lowest unoccupied one",
    "q_homo_picture": "They show the region of electron density, and the two colours are the phase",
    "q_electronic_o2": "The electron count has to match the spin and charge you set",
    "q_method_why": "To compare how the results differ with the method and basis set approximation",
    "q_basis_same": "No, it is the same molecule, the basis set changes how we describe it mathematically",
    "q_pattern_interpret": "The HOMO values are similar with small differences between methods",
    "q_contrib_meaning": "It shows the contribution of s and p atomic orbital types to the electrons",
    "q_compare_ch4_o2": "O2 has unpaired electrons and a different spin compared to CH4",
    "q_transfer_opt": "Any molecule needs it, because a drawn structure is not the lowest energy geometry",
    "q_transfer_orbitals": "No, the atoms, electrons and bonding differ so the orbitals would differ",
}
