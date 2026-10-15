"""Five months of synthetic tastings (coffee, tea and wine) for one taster, into memory and the map.

    uv run 09-taste-journal/seed.py

Each tasting is one memory in the `Tastings` container, dated by the day it was tasted (written
side by side, about 15 s on the local engine), plus its flavor scores in the journal file the star
map reads. Re-running skips tastings already in memory. The taster leans bright, floral and
fruity, and keeps rating smoky, roasty and tannic things low; the palate and recommendation
answers should find that.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as demo  # noqa: E402

# (date, kind, name, origin, rating, notes, flavor), the flavor in DIMS order:
# acidity, sweetness, bitterness, body, fruit, floral, earthy, roast
TASTINGS = [
    (
        "2026-05-04",
        "coffee",
        "Ethiopia Guji Hambela",
        "Guji, Ethiopia, washed",
        5,
        (
            "Jasmine on the nose, then bergamot and white peach. Tea-like body, sparkling lemon "
            "acidity. Best cup of the spring."
        ),
        (8, 6, 1, 3, 8, 9, 1, 2),
    ),
    (
        "2026-05-11",
        "wine",
        "Mosel Riesling Kabinett",
        "Mosel, Germany, 2023",
        5,
        (
            "Green apple, lime zest and a little honey. Racy acidity, low alcohol, slate finish. "
            "Could drink this all afternoon."
        ),
        (9, 6, 1, 3, 8, 6, 2, 0),
    ),
    (
        "2026-05-18",
        "tea",
        "Lapsang Souchong",
        "Wuyi, Fujian, China",
        2,
        (
            "Pine smoke and campfire, almost like bacon. Interesting for two sips, then it was all "
            "smoke. Did not finish the pot."
        ),
        (2, 2, 5, 6, 1, 0, 6, 10),
    ),
    (
        "2026-05-25",
        "coffee",
        "Sumatra Mandheling dark roast",
        "North Sumatra, Indonesia, wet-hulled",
        2,
        (
            "Cedar, tobacco and dark chocolate, heavy and syrupy. Bitter finish that lingers. "
            "Needed "
            "milk to get through it."
        ),
        (1, 3, 8, 9, 1, 0, 8, 9),
    ),
    (
        "2026-06-01",
        "tea",
        "Darjeeling First Flush",
        "Castleton estate, Darjeeling, India",
        4,
        (
            "Muscatel grape, fresh-cut flowers, light and brisk. A little astringent if steeped "
            "past "
            "three minutes."
        ),
        (6, 4, 3, 3, 6, 8, 2, 1),
    ),
    (
        "2026-06-08",
        "wine",
        "Napa Cabernet Sauvignon",
        "Napa Valley, California, 2020",
        2,
        (
            "Blackcurrant jam, vanilla and toasty oak. Huge tannins dried my mouth out. "
            "Impressive, "
            "but tiring by the second glass."
        ),
        (3, 4, 4, 10, 6, 0, 6, 6),
    ),
    (
        "2026-06-14",
        "coffee",
        "Kenya Nyeri AA",
        "Nyeri, Kenya, washed SL28",
        5,
        (
            "Blackcurrant and red grapefruit, juicy and bright like a fruit cordial. Sweet "
            "tomato-leaf finish. Stunning as a V60."
        ),
        (9, 7, 2, 5, 10, 4, 2, 2),
    ),
    (
        "2026-06-22",
        "tea",
        "Gyokuro",
        "Yame, Fukuoka, Japan",
        4,
        (
            "Deep umami, sweet seaweed broth, very smooth. Low-temperature brew was key. Savory "
            "more "
            "than floral."
        ),
        (2, 6, 2, 6, 2, 3, 6, 0),
    ),
    (
        "2026-06-29",
        "wine",
        "Beaujolais Fleurie",
        "Fleurie, Beaujolais, 2023",
        5,
        "Violets and crunchy raspberry, light and chilled. Almost no tannin. Perfect summer red.",
        (7, 5, 1, 3, 9, 8, 2, 0),
    ),
    (
        "2026-07-06",
        "coffee",
        "Brazil Cerrado natural",
        "Cerrado Mineiro, Brazil",
        3,
        (
            "Peanut, milk chocolate and caramel. Round and easy, low acidity. Pleasant but "
            "forgettable."
        ),
        (2, 7, 3, 6, 2, 1, 4, 5),
    ),
    (
        "2026-07-13",
        "tea",
        "Alishan High Mountain Oolong",
        "Alishan, Chiayi, Taiwan",
        5,
        (
            "Orchid and lilac, creamy body, sweet cooling finish. Lasted six infusions. My "
            "favorite "
            "tea so far."
        ),
        (4, 7, 1, 5, 4, 10, 1, 1),
    ),
    (
        "2026-07-20",
        "wine",
        "Barossa Shiraz",
        "Barossa Valley, Australia, 2021",
        2,
        "Black pepper, smoked meat, plum jam and a lot of alcohol. Heavy and hot. Not for me.",
        (2, 5, 4, 10, 6, 0, 7, 6),
    ),
    (
        "2026-08-02",
        "coffee",
        "Panama Gesha",
        "Boquete, Panama, washed",
        5,
        (
            "Jasmine and honeysuckle, mango, black tea body. Delicate and incredibly clean. Worth "
            "the "
            "price once a year."
        ),
        (7, 8, 1, 3, 8, 10, 0, 1),
    ),
    (
        "2026-08-10",
        "tea",
        "English Breakfast with milk",
        "Assam and Ceylon blend",
        3,
        "Malty and strong, fine with milk on a rainy morning. A bit flat and bitter without it.",
        (3, 3, 6, 7, 2, 1, 5, 4),
    ),
    (
        "2026-08-17",
        "wine",
        "Sancerre",
        "Sancerre, Loire Valley, 2023",
        4,
        "Grapefruit, cut grass and flint. Very dry and lively. Great with goat cheese.",
        (9, 3, 2, 3, 7, 5, 3, 0),
    ),
    (
        "2026-08-30",
        "coffee",
        "Colombia Huila pink bourbon",
        "Huila, Colombia, washed",
        5,
        "Red apple, hibiscus and panela sweetness. Bright but balanced, silky body.",
        (7, 8, 1, 5, 8, 7, 1, 2),
    ),
    (
        "2026-09-07",
        "tea",
        "Pu-erh, aged shou",
        "Menghai, Yunnan, China, 2012",
        1,
        (
            "Wet forest floor, compost and old leather. Thick and dark. Could not get past the "
            "earthiness."
        ),
        (1, 3, 5, 8, 0, 0, 10, 4),
    ),
    (
        "2026-09-14",
        "wine",
        "Alsace Gewurztraminer",
        "Alsace, France, 2022",
        4,
        (
            "Lychee, rose petals and ginger. Off-dry and perfumed. A little low in acidity but "
            "gorgeous on the nose."
        ),
        (4, 8, 1, 5, 8, 10, 2, 0),
    ),
    (
        "2026-09-28",
        "coffee",
        "Rwanda Nyamasheke",
        "Nyamasheke, Rwanda, washed",
        4,
        (
            "Red currant, black tea and orange blossom. Clean and juicy, slightly lighter than the "
            "Kenya."
        ),
        (8, 6, 2, 4, 8, 7, 1, 2),
    ),
    (
        "2026-10-05",
        "wine",
        "Rioja Reserva",
        "Rioja, Spain, 2018",
        3,
        (
            "Cherry, dill and vanilla from American oak, soft tannins. Fine with dinner, oak was a "
            "bit much."
        ),
        (5, 4, 3, 7, 6, 1, 5, 5),
    ),
]

PROFILE = [
    "Sam brews coffee at home on a V60 and drinks it black.",
    "Sam avoids caffeine after 3 pm, so afternoon tea has to be low-caffeine or herbal.",
]


def main() -> None:
    have = {t["id"]: t for t in demo.journal.all()}
    todo = []
    for i, (day, kind, name, origin, rating, notes, vector) in enumerate(TASTINGS):
        tid = f"seed-{i:02d}"
        if have.get(tid, {}).get("memory_ids"):
            continue
        todo.append(
            {
                "id": tid,
                "date": day,
                "kind": kind,
                "name": name,
                "origin": origin,
                "notes": notes,
                "rating": rating,
                "in_memory": False,
                "flavor": dict(zip(demo.DIMS, map(float, vector), strict=True)),
            }
        )
    print(
        f"{len(TASTINGS)} tastings into {demo.CONTAINER!r} for {demo.USER!r} on the "
        f"{demo.mem.mode} base; {len(TASTINGS) - len(todo)} already in memory"
    )
    started = time.monotonic()
    for t in demo.remember(todo) if todo else []:
        print(f"  {t['date']}  {t['name']:<36} {t['rating']}/5  {len(t['memory_ids'])} memory")
    known = set(demo.mem.profile().get("static") or [])
    for fact in PROFILE:
        if fact not in known:
            demo.mem.remember_fact(fact)
    print(f"written in {time.monotonic() - started:.0f}s; profile: {PROFILE}")


if __name__ == "__main__":
    main()
