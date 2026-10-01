"""Chemistry drawn as chemists draw it: skeletal structures and arrow-pushing mechanisms.

A molecule is written as SMILES (``flexo.chemistry.molecule``), laid out in two
dimensions the way a chemist would draw it -- rings as regular polygons, chains
zigzagging at 120 degrees, every bond on ChemDraw's 30-degree grid
(``flexo.chemistry.layout``) -- and drawn to the ACS proportions: bonds 1.44 label
heights long, double bonds offset into their rings, labels clipping the bonds that
meet them (``flexo.chemistry.draw``).

A mechanism is a run of steps, each a set of curly arrows that move electrons
(``flexo.chemistry.electrons``). The arrows are not decoration: each moves a pair
of electrons (or one, for a fishhook) from a lone pair or a bond to an atom or a
bond, so the structure after them follows -- and is drawn -- from the structure
before. A step whose arrows would give carbon ten electrons, or leave a bond with
one, is said in words; a step drawn by hand is checked against what its arrows make.
"""
