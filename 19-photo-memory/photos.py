"""The sample photos: a personal library in three albums, from Wikimedia Commons (CC0, CC BY,
CC BY-SA), fetched once at 1280 px and kept in data/19-photo-memory/photos/. Each lists its
author and licence; `source` is the photo's Commons page."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from demokit.config import ROOT

PHOTOS_DIR = ROOT / "data" / "19-photo-memory" / "photos"

ALBUMS = {"lisbon": "Lisbon", "home": "Home", "kyoto": "Kyoto"}

PHOTOS = {
    "lisbon-tram": {
        "album": "lisbon",
        "title": "Tram in Alfama",
        "file": "lisbon-tram.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8c/Tram_28_in_Alfama_%28Lissabon_2016%29_%2826029557541%29.jpg/1280px-Tram_28_in_Alfama_%28Lissabon_2016%29_%2826029557541%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Tram_28_in_Alfama_(Lissabon_2016)_(26029557541).jpg",
        "credit": "Paul Arps from The Netherlands, CC BY 2.0",
    },
    "lisbon-pastries": {
        "album": "lisbon",
        "title": "Pastéis de nata",
        "file": "lisbon-pastries.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5a/Pasteis_de_nata_%28Lissabon_2016%29_%2826069956686%29.jpg/1280px-Pasteis_de_nata_%28Lissabon_2016%29_%2826069956686%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Pasteis_de_nata_(Lissabon_2016)_(26069956686).jpg",
        "credit": "Paul Arps from The Netherlands, CC BY 2.0",
    },
    "lisbon-bridge": {
        "album": "lisbon",
        "title": "Bridge at sunset",
        "file": "lisbon-bridge.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a1/Ponte_25_de_Abril_at_sunset_01.jpg/1280px-Ponte_25_de_Abril_at_sunset_01.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Ponte_25_de_Abril_at_sunset_01.jpg",
        "credit": "Pedro Simões from Lisboa, Portugal, CC BY 2.0",
    },
    "lisbon-tiles": {
        "album": "lisbon",
        "title": "Tiled house fronts",
        "file": "lisbon-tiles.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/da/House_fronts_with_azulejos%2C_Lisbon_-_49721178411.jpg/1280px-House_fronts_with_azulejos%2C_Lisbon_-_49721178411.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:House_fronts_with_azulejos,_Lisbon_-_49721178411.jpg",
        "credit": "Sonse, CC BY 2.0",
    },
    "lisbon-cat": {
        "album": "lisbon",
        "title": "Cat on a bench",
        "file": "lisbon-cat.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/c0/Cat_sleeping_on_a_bench%2C_Prazeres_Cemetery%2C_Lisbon%2C_Portugal_julesvernex2.jpg/1280px-Cat_sleeping_on_a_bench%2C_Prazeres_Cemetery%2C_Lisbon%2C_Portugal_julesvernex2.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Cat_sleeping_on_a_bench,_Prazeres_Cemetery,_Lisbon,_Portugal_julesvernex2.jpg",
        "credit": "Jules Verne Times Two, CC BY-SA 4.0",
    },
    "lisbon-tower": {
        "album": "lisbon",
        "title": "Belém Tower",
        "file": "lisbon-tower.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/65/Torre_Bel%C3%A9m_April_2009-4a.jpg/1280px-Torre_Bel%C3%A9m_April_2009-4a.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Torre_Bel%C3%A9m_April_2009-4a.jpg",
        "credit": "Alvesgaspar, CC BY-SA 3.0",
    },
    "home-cake": {
        "album": "home",
        "title": "Birthday cake",
        "file": "home-cake.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2e/Italy_-_birthday_cake_with_candles_5.jpg/1280px-Italy_-_birthday_cake_with_candles_5.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Italy_-_birthday_cake_with_candles_5.jpg",
        "credit": "Francesca Cesa Bianchi, Milano, CC BY-SA 3.0 it",
    },
    "home-dog": {
        "album": "home",
        "title": "Dog on the beach",
        "file": "home-dog.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e3/A_dog_running_on_the_beach.jpg/1280px-A_dog_running_on_the_beach.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:A_dog_running_on_the_beach.jpg",
        "credit": "Bruce Emmerling, CC BY-SA 4.0",
    },
    "home-bike": {
        "album": "home",
        "title": "Green bicycle",
        "file": "home-bike.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a3/Green_bicycle_leaning_on_the_wall.jpg/1280px-Green_bicycle_leaning_on_the_wall.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Green_bicycle_leaning_on_the_wall.jpg",
        "credit": "www.Pixel.la Free Stock Photos, CC0",
    },
    "home-rain": {
        "album": "home",
        "title": "Rain on the window",
        "file": "home-rain.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2a/Rain_on_a_window_pane.jpg/1280px-Rain_on_a_window_pane.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Rain_on_a_window_pane.jpg",
        "credit": "Theactivistuk, CC BY-SA 4.0",
    },
    "kyoto-gates": {
        "album": "kyoto",
        "title": "Fushimi Inari",
        "file": "kyoto-gates.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8a/20181110_Fushimi_Inari_Torii_12.jpg/1280px-20181110_Fushimi_Inari_Torii_12.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:20181110_Fushimi_Inari_Torii_12.jpg",
        "credit": "Balon Greyjoy, CC0",
    },
    "kyoto-bamboo": {
        "album": "kyoto",
        "title": "Bamboo grove",
        "file": "kyoto-bamboo.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/ef/Arashiyama_Bamboo_Grove_%28Unsplash%29.jpg/1280px-Arashiyama_Bamboo_Grove_%28Unsplash%29.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Arashiyama_Bamboo_Grove_(Unsplash).jpg",
        "credit": "Erol Ahmed erol, CC0",
    },
    "kyoto-ramen": {
        "album": "kyoto",
        "title": "Ramen",
        "file": "kyoto-ramen.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/69/Ramen_Bowl_2.jpg/1280px-Ramen_Bowl_2.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Ramen_Bowl_2.jpg",
        "credit": "Shisma, CC BY 4.0",
    },
    "kyoto-temple": {
        "album": "kyoto",
        "title": "Kinkaku-ji pond",
        "file": "kyoto-temple.jpg",
        "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a9/Rokuon-ji_%28Kita-ku_Kyoto%29_Kinkaku-ji_Pond_hdsr_S5_02.jpg/1280px-Rokuon-ji_%28Kita-ku_Kyoto%29_Kinkaku-ji_Pond_hdsr_S5_02.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
        "source": "https://commons.wikimedia.org/wiki/File:Rokuon-ji_(Kita-ku_Kyoto)_Kinkaku-ji_Pond_hdsr_S5_02.jpg",
        "credit": "Hyppolyte de Saint-Rambert, CC BY 4.0",
    },
}


def fetch(key: str) -> Path:
    """The photo, downloaded the first time."""
    r = PHOTOS[key]
    dest = PHOTOS_DIR / r["file"]
    if dest.is_file():
        return dest
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {r['title']}")
    req = urllib.request.Request(
        r["url"],
        headers={"User-Agent": "membase-use-cases/0.1 (github.com/unibaseio/membase-use-cases)"},
    )
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)
    return dest
