"""Synthetic records: ten families, ten seekers, three true pairs and some decoys.

    uv run 15-reunite/seed.py            # write all records, then suggest matches for every seeker
    uv run 15-reunite/seed.py --reset    # start over (deletes this demo's local memory)
    uv run 15-reunite/seed.py --records-only   # write the records; match each seeker on the page

Every person, family and town here is made up. In the three true pairs (F-01/S-01, F-02/S-02,
F-03/S-03) the seeker describes the same details in their own words, never the family's:
"a red tin toy fire truck" becomes "a little metal fire engine". Decoy families share one or two
generic details with a true seeker (the same seaside town, a toy fire engine of another kind,
a flood in another year), and decoy seekers share details with no family strongly.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TRUE_PAIRS = {"S-01": "F-01", "S-02": "F-02", "S-03": "F-03"}

FAMILIES = [
    {  # F-01, true pair with S-01
        "contact": "Ruth Marsh, his older sister",
        "child": "Daniel, called Dani",
        "born": "1985",
        "lost": "Spring 1989 in Port Allery. Our mother went into hospital, Dani was placed with a "
        "foster family, and we lost track of him when the agency moved its records.",
        "looks": "Dark curly hair. A small scar just above his left eyebrow from falling against "
        "the stove door.",
        "loved": "A red tin toy fire truck our grandfather gave him, with a ladder that wound up "
        "on a handle. Our brown spaniel Biscuit, who slept on his bed.",
        "people": "Me, his big sister, who used to plait his hair to make him laugh. Our "
        "grandmother Nell, who sang 'You Are My Sunshine' at bedtime.",
        "places": "Our flat above Hartley's bakery on the harbour road. The seafront.",
        "story": "He was four. He lined his toys up on the windowsill so they could see the boats.",
    },
    {  # F-02, true pair with S-02
        "contact": "Teresa Varga, her mother",
        "child": "Mira",
        "born": "1991",
        "lost": "The 1994 floods in Wenmouth. In the evacuation she was handed onto a rescue boat "
        "with neighbours and we never found out which shelter she was taken to.",
        "looks": "Light brown hair. A strawberry-shaped birthmark on the inside of her right wrist.",
        "loved": "A knitted blue rabbit with one ear missing, called Pip.",
        "people": "Her grandfather Lajos, who captained the river ferry and let her ring its bell. "
        "He called her his little sparrow.",
        "places": "Our house on stilts at the edge of the river. The ferry crossing.",
        "story": "She was three. She was frightened of thunder and hid under the kitchen table.",
    },
    {  # F-03, true pair with S-03
        "contact": "Joseph Adeyemi, his father",
        "child": "Teo",
        "born": "1981",
        "lost": "November 1986 at Carrow Junction railway station. We were moving to the city; in "
        "the crowd on the platform he let go of his mother's hand and we lost him.",
        "looks": "Small for his age, a gap between his front teeth. He stuttered when he was excited.",
        "loved": "A wooden whistle shaped like a bird that his uncle Femi carved for him. Trains: "
        "he knew every engine's number.",
        "people": "His uncle Femi, who had a big beard and carved toys with a pocket knife. His "
        "baby sister.",
        "places": "Our fruit stall at Eastgate market, where he helped stack the oranges.",
        "story": "He was five, wearing a green duffel coat with wooden toggles.",
    },
    {  # F-04, decoy: a toy fire engine, but plastic and blue, in the mountains
        "contact": "Aileen Brennan, his mother",
        "child": "Owen",
        "born": "1986",
        "lost": "1990, in the mountain village of Hollin. His father took him abroad and stopped "
        "writing.",
        "looks": "Red hair and lots of freckles.",
        "loved": "A blue plastic fire engine with a siren that ran on batteries. Our grey cat, Pepper.",
        "people": "His grandfather, who played the fiddle at every wedding in the valley.",
        "places": "A farmhouse in the hills, snowed in every winter.",
        "story": "He was four and loved sledging.",
    },
    {  # F-05, decoy: a flood, but another year and another child
        "contact": "Kwame Osei, her father",
        "child": "Ama",
        "born": "1992",
        "lost": "The river flood of 1997 near Wenmouth; she was taken to a hospital in the "
        "confusion and the hospital lost her papers.",
        "looks": "A dark birthmark on the left side of her neck.",
        "loved": "A rag doll in a yellow dress. Singing.",
        "people": "Her grandmother, who sold smoked fish at the quay.",
        "places": "A fishing village with a lighthouse.",
        "story": "She was five and could already count to a hundred.",
    },
    {  # F-06, decoy: lost at a station, but older and a bus station
        "contact": "Irena Novak, his mother",
        "child": "Pavel",
        "born": "1984",
        "lost": "1992 at Merriton bus station, when he was eight, after a family argument.",
        "looks": "Tall for his age, a scar on his chin.",
        "loved": "Football, and a harmonica he played badly.",
        "people": "His older brother Marek.",
        "places": "A block of flats next to the football stadium.",
        "story": "He supported the city team and wore their scarf everywhere.",
    },
    {  # F-07
        "contact": "Britt Lindqvist, their mother",
        "child": "Twin girls, Elin and Sara",
        "born": "1980",
        "lost": "At birth, in Eastgate General Hospital: I was told one twin had died, and I have "
        "since learned that may not be true.",
        "looks": "Both had a small mole on the right cheek.",
        "loved": "",
        "people": "Their older brother Nils.",
        "places": "Eastgate.",
        "story": "I am looking for the twin I was told had died.",
    },
    {  # F-08
        "contact": "Carmen Ruiz, her mother",
        "child": "Lucía",
        "born": "1996",
        "lost": "1999, when her father took her abroad during a custody dispute.",
        "looks": "Black hair, very long eyelashes.",
        "loved": "A toy piano with coloured keys. Pink balloons.",
        "people": "Her cousin Paco, who was the same age.",
        "places": "Our flat with a balcony and a lemon tree in a pot.",
        "story": "She was three and sang in the bath.",
    },
    {  # F-09
        "contact": "Min-jun Park, his brother",
        "child": "Jin",
        "born": "1982",
        "lost": "After our house fire in 1984 he was taken to an orphanage while our parents were in "
        "hospital, and later adopted overseas.",
        "looks": "A burn scar on the back of his left hand.",
        "loved": "A wooden spinning top our father painted red and yellow.",
        "people": "Me, his older brother.",
        "places": "A house with a courtyard and a persimmon tree.",
        "story": "He was two.",
    },
    {  # F-10, decoy: the same seaside town as F-01/S-01, a stuffed dog
        "contact": "Maeve Doyle, her mother",
        "child": "Siobhan",
        "born": "1988",
        "lost": "Summer 1991 at the fairground on Port Allery seafront; she wandered off near the "
        "carousel and was taken into care.",
        "looks": "Freckles and a gap-toothed smile.",
        "loved": "A stuffed toy dog with a tartan collar. Candyfloss.",
        "people": "Her aunt Brigid, who ran the hoopla stall.",
        "places": "The fairground; the caravan we lived in for the season.",
        "story": "She was three.",
    },
]

SEEKERS = [
    {  # S-01, the same child as F-01
        "contact": "Callum Price",
        "born": "Around 1984 or 1985",
        "placed": "Adopted in 1990 and grew up inland, in Merriton.",
        "earliest": "Waking up to the smell of warm bread coming up through the floor. Seagulls "
        "screaming outside. An old lady singing me to sleep with a song about sunshine.",
        "objects": "A little metal fire engine, red, with a ladder you could crank up. I kept it "
        "until I was about ten.",
        "people": "A bigger girl who braided my hair and made me giggle, maybe a sister. A big "
        "floppy-eared brown dog, called Bisky or Biscuit.",
        "places": "Somewhere by the sea with boats.",
        "marks": "A faint scar over my left eyebrow; my adoptive parents were told it was a burn.",
        "story": "I think I was five when I moved, but my papers are vague.",
    },
    {  # S-02, the same child as F-02
        "contact": "Anna Kessler",
        "born": "1990 or 1991",
        "placed": "A children's home in Saltby from about 1995, then foster care.",
        "earliest": "Water everywhere and being carried high on someone's shoulders. A huge storm. "
        "Hiding under a table when it thundered.",
        "objects": "A woolly bunny, blue-ish, with only one ear.",
        "people": "An old man in a cap who let me pull a rope to ring the bell on a big boat that "
        "went back and forth across the river. Someone called me a bird name, sparrow or wren.",
        "places": "I always thought our house was up in the air: I remember wooden steps going up "
        "from the mud.",
        "marks": "A small reddish mark on my right wrist.",
        "story": "I don't know my real name.",
    },
    {  # S-03, the same child as F-03
        "contact": "Martin Hale",
        "born": "About 1981",
        "placed": "Found alone at a station and taken into care in 1986; grew up in children's homes "
        "around Carrow.",
        "earliest": "A huge hall full of steam and loudspeakers, crying because I couldn't find my "
        "mum. A green coat with wooden pegs instead of buttons.",
        "objects": "A little carved bird that sang when I blew into it.",
        "people": "A man with a bushy beard who made things out of wood with a knife.",
        "places": "Crates piled with oranges and apples; a market with striped awnings.",
        "marks": "I stammered badly as a boy and have a gap between my front teeth.",
        "story": "I have always loved trains, but they also make me anxious.",
    },
    {  # S-04, decoy: snow, but nothing specific
        "contact": "Lena Holt",
        "born": "1987",
        "placed": "Adopted at six from a children's home in the north.",
        "earliest": "Snow up to the windows. Being pulled on a wooden sledge by a woman in a red scarf.",
        "objects": "One red mitten on a string.",
        "people": "An aunt who knitted all the time.",
        "places": "A church with a green onion dome.",
        "marks": "None that I know of.",
        "story": "",
    },
    {  # S-05, decoy: a rag doll and a lighthouse, but a blue dress and another decade
        "contact": "Sara Mills",
        "born": "1979",
        "placed": "Fostered from 1983.",
        "earliest": "A lighthouse beam sweeping across my bedroom ceiling.",
        "objects": "A rag doll in a blue dress that my grandmother made.",
        "people": "A grandmother who smoked a pipe.",
        "places": "A cottage on a cliff.",
        "marks": "A mole on my left shoulder.",
        "story": "",
    },
    {  # S-06
        "contact": "Tom Vale",
        "born": "1978",
        "placed": "Into care in 1982 after my mother died.",
        "earliest": "Riding a big orange tram with a blind man who held my hand.",
        "objects": "A tin with buttons in it that I played with for hours.",
        "people": "The blind man, and a parrot that said hello.",
        "places": "A tram depot.",
        "marks": "",
        "story": "",
    },
    {  # S-07, decoy: a carousel, but a later year and nothing else
        "contact": "Hannah Brook",
        "born": "1993",
        "placed": "Adopted in 1997.",
        "earliest": "Painted horses going up and down and music playing.",
        "objects": "",
        "people": "A man in a uniform who bought me an ice lolly.",
        "places": "A city park with a bandstand.",
        "marks": "",
        "story": "",
    },
    {  # S-08, decoy: a red toy and a dog, but a desert town
        "contact": "Luis Moreno",
        "born": "1995",
        "placed": "Adopted in 1999 from a children's home near the border.",
        "earliest": "A long hot dusty road and riding in the back of a truck.",
        "objects": "A red toy car with a door that opened.",
        "people": "A small white dog called Chispa.",
        "places": "Desert, cactus, a house with a flat roof.",
        "marks": "",
        "story": "",
    },
    {  # S-09
        "contact": "Grace Wu",
        "born": "1983",
        "placed": "Adopted from a convent orphanage.",
        "earliest": "Long corridors with shiny floors and nuns in white.",
        "objects": "A silver bracelet with a bell on it.",
        "people": "A nun called Sister Agnes.",
        "places": "A courtyard with a fountain.",
        "marks": "",
        "story": "",
    },
    {  # S-10, decoy: a fiddle in the hills, like F-04, but goats, a stone village, no fire engine
        "contact": "Ibrahim Saleh",
        "born": "1986",
        "placed": "Came to the city with an uncle in 1993.",
        "earliest": "Goats on a steep hillside and someone playing a fiddle at a wedding.",
        "objects": "A brass bell from a goat's collar.",
        "people": "My uncle, who was a shepherd.",
        "places": "A village of stone houses in the mountains.",
        "marks": "",
        "story": "",
    },
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reset", action="store_true", help="delete this demo's local memory first")
    p.add_argument(
        "--records-only", action="store_true", help="write the records, suggest no matches yet"
    )
    a = p.parse_args()
    if a.reset:
        sys.path.insert(0, str(HERE.parent))
        from demokit.config import DATA  # noqa: PLC0415

        shutil.rmtree(DATA / "15-reunite" / "operator", ignore_errors=True)
    import app as demo  # noqa: PLC0415 - after any reset

    if demo.store.read()["records"]:
        sys.exit(f"{demo.store.path} already has records: run with --reset to start over")

    started = time.monotonic()
    families = [demo.new_record("family", {k: v for k, v in f.items() if v}) for f in FAMILIES]
    seekers = [demo.new_record("seeker", {k: v for k, v in s.items() if v}) for s in SEEKERS]
    # The first record of each kind makes its container, one at a time: the local engine
    # writes a new container's metadata while every other write reads it. After that the two
    # containers are two engines, and families and seekers go in side by side.
    demo.save_record(families[0])
    demo.save_record(seekers[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(lambda recs: [demo.save_record(r) for r in recs], [families[1:], seekers[1:]])
        )
    print(
        f"{len(families)} families and {len(seekers)} seekers in memory "
        f"in {time.monotonic() - started:.0f}s"
    )

    if a.records_only:
        return
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda r: demo.match(r["id"]), seekers))
    print(f"matches suggested for {len(results)} seekers in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
