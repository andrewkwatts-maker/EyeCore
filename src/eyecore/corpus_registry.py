"""
Shared corpus registry for the EyeCore suite.

Each entry is a dict understood by CorpusManager.add():
  id          — unique stable identifier
  name        — human-readable title
  source_type — "gutenberg" | "url" | "git"
  source      — Gutenberg book ID, URL, or git URL
  topics      — list of tag strings for filtering
  description — one-line summary

Grouped constants let each downstream library import only what it needs:

  from eyecore.corpus_registry import GREEK_CORPUSES, NORSE_CORPUSES
  from eyecore.corpus_registry import MYTHOLOGY_CORPUSES   # all mythology
  from eyecore.corpus_registry import ALL_CORPUSES         # everything
"""

# ── Greek & Roman ─────────────────────────────────────────────────────────────

GREEK_CORPUSES = [
    {"id": "gutenberg-iliad",
     "name": "The Iliad (Homer)",
     "source_type": "gutenberg", "source": "2199",
     "topics": ["greek", "hero", "war"],
     "description": "Homer's Iliad — the Trojan War epic"},
    {"id": "gutenberg-odyssey",
     "name": "The Odyssey (Homer)",
     "source_type": "gutenberg", "source": "1727",
     "topics": ["greek", "hero", "journey"],
     "description": "Homer's Odyssey — the wanderings of Odysseus"},
    {"id": "gutenberg-theogony",
     "name": "Theogony & Works and Days (Hesiod)",
     "source_type": "gutenberg", "source": "348",
     "topics": ["greek", "deity", "creation", "cosmology"],
     "description": "Hesiod — Greek divine genealogy and creation"},
    {"id": "gutenberg-homeric-hymns",
     "name": "Homeric Hymns",
     "source_type": "gutenberg", "source": "24327",
     "topics": ["greek", "deity", "ritual"],
     "description": "Ancient hymns to the Greek gods"},
]

ROMAN_CORPUSES = [
    {"id": "gutenberg-metamorphoses",
     "name": "Metamorphoses (Ovid)",
     "source_type": "gutenberg", "source": "26073",
     "topics": ["roman", "greek", "transformation", "deity"],
     "description": "Ovid — myths of transformation"},
    {"id": "gutenberg-aeneid",
     "name": "The Aeneid (Virgil)",
     "source_type": "gutenberg", "source": "227",
     "topics": ["roman", "hero", "troy"],
     "description": "Virgil — the founding of Rome"},
]

# ── Norse ─────────────────────────────────────────────────────────────────────

NORSE_CORPUSES = [
    {"id": "gutenberg-prose-edda",
     "name": "Prose Edda (Snorri Sturluson)",
     "source_type": "gutenberg", "source": "10782",
     "topics": ["norse", "deity", "creation", "cosmology"],
     "description": "Primary Norse mythology source"},
    {"id": "gutenberg-volsunga",
     "name": "Volsunga Saga",
     "source_type": "gutenberg", "source": "1152",
     "topics": ["norse", "hero", "dragon"],
     "description": "The Norse saga of the Volsung family"},
]

# ── Celtic ────────────────────────────────────────────────────────────────────

CELTIC_CORPUSES = [
    {"id": "gutenberg-mabinogion",
     "name": "The Mabinogion",
     "source_type": "gutenberg", "source": "5765",
     "topics": ["celtic", "welsh", "hero", "faerie"],
     "description": "Welsh mythology — the four branches"},
    {"id": "gutenberg-celtic-myth",
     "name": "Celtic Myth and Legend (Squire)",
     "source_type": "gutenberg", "source": "14672",
     "topics": ["celtic", "irish", "scottish"],
     "description": "Celtic mythology survey by Charles Squire"},
]

# ── Egyptian ──────────────────────────────────────────────────────────────────

EGYPTIAN_CORPUSES = [
    {"id": "gutenberg-egyptian-myth",
     "name": "Egyptian Myth and Legend (Mackenzie)",
     "source_type": "gutenberg", "source": "15403",
     "topics": ["egyptian", "deity", "creation", "afterlife"],
     "description": "Egyptian mythology survey"},
]

# ── Hindu & Sanskrit ─────────────────────────────────────────────────────────

HINDU_CORPUSES = [
    {"id": "gutenberg-ramayana",
     "name": "The Ramayana (Dutt translation)",
     "source_type": "gutenberg", "source": "24869",
     "topics": ["hindu", "hero", "deity"],
     "description": "Hindu epic — Rama's quest to rescue Sita"},
    {"id": "gutenberg-mahabharata",
     "name": "The Mahabharata (Ganguli translation)",
     "source_type": "gutenberg", "source": "15474",
     "topics": ["hindu", "hero", "deity", "war"],
     "description": "Hindu epic — the Kurukshetra war"},
]

# ── Middle Eastern ────────────────────────────────────────────────────────────

MIDDLE_EASTERN_CORPUSES = [
    {"id": "gutenberg-1001-nights",
     "name": "One Thousand and One Nights",
     "source_type": "gutenberg", "source": "34206",
     "topics": ["arabic", "persian", "tales", "djinn"],
     "description": "Arabian Nights — folk tales from the Islamic Golden Age"},
]

# ── Esoteric / Occult ─────────────────────────────────────────────────────────
# Available for Esoterica and Synomosia modules to import

ESOTERIC_CORPUSES = [
    {"id": "gutenberg-book-of-the-dead",
     "name": "The Egyptian Book of the Dead (Budge)",
     "source_type": "gutenberg", "source": "7999",
     "topics": ["egyptian", "magic", "afterlife", "ritual"],
     "description": "Ancient Egyptian funerary text — spells and rites"},
    {"id": "gutenberg-golden-bough",
     "name": "The Golden Bough (Frazer)",
     "source_type": "gutenberg", "source": "3623",
     "topics": ["magic", "ritual", "comparative-religion", "folk"],
     "description": "Frazer's comparative study of magic and religion"},
    {"id": "gutenberg-malleus",
     "name": "Malleus Maleficarum",
     "source_type": "gutenberg", "source": "8925",
     "topics": ["witchcraft", "inquisition", "demonology", "magic"],
     "description": "15th-century witch-hunting manual"},
    {"id": "gutenberg-kabbalah",
     "name": "The Kabbalah (Ginsburg)",
     "source_type": "gutenberg", "source": "2792",
     "topics": ["kabbalah", "jewish-mysticism", "esoteric"],
     "description": "Historical survey of Kabbalistic tradition"},
    {"id": "gutenberg-hermetic",
     "name": "The Kybalion",
     "source_type": "gutenberg", "source": "14209",
     "topics": ["hermeticism", "esoteric", "philosophy"],
     "description": "The Seven Hermetic Principles"},
]

# ── Philosophy & Wisdom ───────────────────────────────────────────────────────
# General-purpose reference for any module

PHILOSOPHY_CORPUSES = [
    {"id": "gutenberg-republic",
     "name": "The Republic (Plato)",
     "source_type": "gutenberg", "source": "1497",
     "topics": ["greek", "philosophy", "ethics", "politics"],
     "description": "Plato's dialogues on justice and the ideal state"},
    {"id": "gutenberg-nicomachean",
     "name": "Nicomachean Ethics (Aristotle)",
     "source_type": "gutenberg", "source": "8438",
     "topics": ["greek", "philosophy", "ethics"],
     "description": "Aristotle on virtue and the good life"},
    {"id": "gutenberg-meditations",
     "name": "Meditations (Marcus Aurelius)",
     "source_type": "gutenberg", "source": "2680",
     "topics": ["stoic", "philosophy", "roman"],
     "description": "Stoic reflections by the Roman emperor"},
]

# ── Aggregates ────────────────────────────────────────────────────────────────

MYTHOLOGY_CORPUSES = (
    GREEK_CORPUSES
    + ROMAN_CORPUSES
    + NORSE_CORPUSES
    + CELTIC_CORPUSES
    + EGYPTIAN_CORPUSES
    + HINDU_CORPUSES
    + MIDDLE_EASTERN_CORPUSES
)

ALL_CORPUSES = MYTHOLOGY_CORPUSES + ESOTERIC_CORPUSES + PHILOSOPHY_CORPUSES


def get_by_topic(*topics: str) -> list:
    """Return all corpus entries tagged with ANY of the given topics."""
    topic_set = set(topics)
    return [c for c in ALL_CORPUSES if topic_set.intersection(c.get("topics", []))]


def get_by_id(corpus_id: str) -> dict | None:
    """Return a single corpus entry by its stable ID, or None."""
    return next((c for c in ALL_CORPUSES if c["id"] == corpus_id), None)
