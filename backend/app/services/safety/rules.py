"""Deterministic red-flag rules engine.

Pure function of (text, age_days) — no model, no I/O, <1ms. Runs on the raw
user message before any model call. Age-aware per the design doc's red-flag
table. Fail direction: over-escalate; unknown age is treated as youngest.

Negation/idiom lookalikes ("baby fever", "fever broke yesterday", "breathing
fine now") are blanked out before keyword matching so they neither fire rules
nor count as weak hits. Numeric temperatures are always evaluated on the
original text — a stated number beats a reassuring phrase.
"""

import re
from dataclasses import dataclass, field

from app.ai.triage import TriageLevel

POISON_CONTROL_NUMBER = "1-800-222-1222"

FEVER_THRESHOLD_F = 100.4
FEVER_HIGH_THRESHOLD_F = 104.0
FEVER_AGE_GATE_DAYS = 90  # chronological age, never corrected

DEHYDRATION_DIAPER_HOURS = 8


@dataclass(frozen=True)
class RuleResult:
    level: TriageLevel
    matched: tuple[str, ...] = ()
    reason: str | None = None
    weak_hit: bool = False
    weak_words: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def fired(self) -> bool:
        return self.level != TriageLevel.NONE


# --- negation / idiom lookalikes (must NOT fire) --------------------------------

_NEGATION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bbaby\s+fever\b",  # idiom: wanting a baby, not a febrile baby
        r"\bfever\s+(?:broke|is\s+gone|went\s+away|went\s+down|has\s+gone|is\s+down|resolved)\b",
        r"\bno\s+(?:more\s+)?fever\b",
        r"\bfever[-\s]free\b",
        r"\bbreathing\s+(?:is\s+)?(?:fine|normal|normally|better|ok|okay|easier)(?:\s+now)?\b",
        r"\bno\s+(?:trouble|difficulty|problems?)\s+breathing\b",
        r"\bnot\s+vomiting\b",
        r"\bno\s+vomiting\b",
        r"\bstopped\s+vomiting\b",
    )
]


def _blank_negations(text: str) -> str:
    for pattern in _NEGATION_PATTERNS:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


# --- temperature extraction -----------------------------------------------------

_TEMP_RE = re.compile(
    r"(\d{2,3}(?:\.\d+)?)\s*(?:°\s*|deg(?:rees)?\s*)?([fc])?(?=[^a-z]|$)",
    re.IGNORECASE,
)
_TEMP_CUE_RE = re.compile(r"\b(?:temp(?:erature)?|fever|febrile|thermometer|reading)\b", re.IGNORECASE)
_AGE_UNIT_AFTER_RE = re.compile(r"^\s*(?:days?|weeks?|months?|hours?|hrs?|minutes?|mins?)\b", re.IGNORECASE)


def _extract_temps_fahrenheit(text: str) -> list[float]:
    """All plausible body temperatures in the text, normalized to °F."""
    has_cue = bool(_TEMP_CUE_RE.search(text))
    temps: list[float] = []
    for match in _TEMP_RE.finditer(text):
        value = float(match.group(1))
        unit = (match.group(2) or "").lower()
        if _AGE_UNIT_AFTER_RE.match(text[match.end() :]):
            continue  # "104 days old", "38 weeks" — an age/duration, not a temp
        if unit == "f":
            temps.append(value)
        elif unit == "c":
            temps.append(value * 9 / 5 + 32)
        else:
            if not has_cue:
                continue  # bare number with no fever/temp context
            if 95.0 <= value <= 110.0:
                temps.append(value)
            elif 34.0 <= value <= 43.0:
                temps.append(value * 9 / 5 + 32)
    return temps


# --- keyword rule table ---------------------------------------------------------

def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# (slug, level, patterns) — slugs come from the CONTRACTS.md reason list.
_KEYWORD_RULES: tuple[tuple[str, TriageLevel, tuple[re.Pattern[str], ...]], ...] = (
    (
        "breathing",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bgrunting\b",
            r"\bnostrils?\s+(?:are\s+)?flar\w+|\bflaring\s+nostrils?\b|\bnose\s+flar\w+",
            r"\bretract(?:ing|ions?)\b",
            r"\bribs?\s+(?:are\s+)?(?:pulling|sucking|caving)\b",
            r"\bchest\s+(?:is\s+)?(?:sucking|caving|pulling)\s+in\b",
            r"\bskin\s+(?:pulling|sucking)\s+in\s+(?:between|under)\s+(?:the\s+)?ribs\b",
            r"\bpauses?\s+in\s+(?:his|her|their|the)?\s*breathing\b",
            r"\bstop(?:s|ped|ping)?\s+breathing\b",
            r"\bnot\s+breathing\b",
            r"\b(?:struggling|working\s+hard|laboring|labouring|fighting)\s+to\s+breathe\b",
            r"\blabored\s+breathing\b",
            r"\bgasping\b",
            r"\bcan'?t\s+(?:seem\s+to\s+)?breathe\b",
        )),
    ),
    (
        "blue_skin",
        TriageLevel.EMERGENCY,
        _compile((
            r"\blips?\s+(?:are\s+|look\s+|turn(?:ed|ing)?\s+)?blue\b",
            r"\bblue\s+(?:lips?|around\s+the\s+(?:lips|mouth)|in\s+the\s+face|tinge)\b",
            r"\bturn(?:ed|ing)?\s+blue\b",
            r"\b(?:skin|face|color|colour)\s+(?:is\s+|looks?\s+)?(?:gray|grey|ashen|dusky)\b",
            r"\blooks?\s+(?:gray|grey|ashen|dusky)\b",
            r"\b(?:gray|grey)\s+(?:skin|color|colour)\b",
        )),
    ),
    (
        "unresponsive",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bunresponsive\b",
            r"\bwon'?t\s+wake(?:\s+up)?\b",
            r"\bcan'?t\s+(?:seem\s+to\s+)?wake\b",
            r"\bhard\s+to\s+wake\b",
            r"\bnot\s+waking(?:\s+up)?\b",
            r"\bfloppy\b",
            r"\blimp\b",
            r"\bpassed\s+out\b",
            r"\bunconscious\b",
            r"\bnot\s+responding\b",
        )),
    ),
    (
        "seizure",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bseizure?s?\b|\bseizing\b",
            r"\bconvuls\w+\b",
            r"\beyes?\s+roll(?:ed|ing)?\s+back\b",
            r"\b(?:rhythmic|jerking)\s+(?:movements?|motions?)\b",
            r"\bwhole\s+body\s+(?:went\s+)?stiff\b",
            r"\btwitching\s+all\s+over\b",
        )),
    ),
    (
        "dehydration",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bsunken\s+(?:fontanelle?|soft\s+spot)\b",
            r"\b(?:fontanelle?|soft\s+spot)\s+(?:is\s+|looks?\s+)?sunken\b",
            r"\b(?:no|without)\s+tears\b",
            r"\bcrying\s+(?:but\s+)?(?:with\s+)?no\s+tears\b",
            r"\bno\s+wet\s+diapers?\s+(?:since\s+(?:yesterday|last\s+night)|all\s+day)\b",
        )),
    ),
    (
        "vomiting_bilious",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bgreen\s+vomit\w*\b",
            r"\bvomit\w*\s+(?:is|was|looks?)\s+green\b",
            r"\bbilious\b",
            r"\bbile\b",
            r"\byellow[-\s]green\s+vomit\w*\b",
            r"\bprojectile\s+vomit\w*\b",
        )),
    ),
    (
        "rash_nonblanching",
        TriageLevel.EMERGENCY,
        _compile((
            r"\bpetechiae?\b",
            r"\bpurpura\b",
            r"\bnon[-\s]?blanching\b",
            r"\bpurple\s+(?:spots?|rash|dots?|blotches)\b",
            (
                r"\b(?:rash|spots?|dots?)\b[^.!?]{0,60}\b(?:doesn'?t|didn'?t|won'?t|not|isn'?t)\s+"
                r"(?:fade|blanch|disappear|go(?:ing)?\s+away|turn\s+white)\b"
            ),
        )),
    ),
    (
        "ingestion",
        TriageLevel.EMERGENCY,
        _compile((
            (
                r"\b(?:swallow(?:ed|ing)?|ingest(?:ed|ing)?|ate|drank|chewed(?:\s+on)?|got\s+into|"
                r"got\s+ahold\s+of|mouthed)\b[^.!?]{0,60}\b(?:pills?|tablets?|medications?|"
                r"medicines?|vitamins?|gummies|batter(?:y|ies)|magnets?|coins?|detergent|bleach|"
                r"cleaner\w*|cleaning\s+(?:supplies|products?)|chemicals?|soap|nicotine|"
                r"cigarettes?|alcohol|perfume|essential\s+oils?|plants?|button\s+batter(?:y|ies))\b"
            ),
            r"\bbutton\s+battery\b",
            r"\bpoison(?:ed|ing)?\b",
        )),
    ),
    (
        "parent_crisis",
        TriageLevel.CRISIS,
        _compile((
            r"\bhurt\s+(?:myself|my\s*self|the\s+baby|him|her|them|my\s+(?:baby|son|daughter|kid|child))\b",
            r"\bkill\s+myself\b",
            r"\bend\s+(?:it\s+all|my\s+life)\b",
            r"\bsuicid\w+\b",
            r"\bdon'?t\s+want\s+to\s+(?:be\s+here|live|wake\s+up)\b",
            r"\bwant\s+to\s+die\b",
            r"\bsha(?:ke|king|ook)\s+(?:the\s+baby|him|her|my\s+baby)\b",
            (
                r"\bafraid\s+(?:I|i)(?:'m|\s+am)?\s+(?:going\s+to|gonna|about\s+to|might|will)\s+"
                r"(?:hurt|shake|drop|throw)\b"
            ),
        )),
    ),
    (
        "parent_overwhelm",
        TriageLevel.CRISIS,
        _compile((
            r"\bcan'?t\s+take\s+(?:it|this)(?:\s+any\s*more|\s+anymore)?\b",
            r"\bcan'?t\s+do\s+this\s+(?:any\s*more|anymore)\b",
            r"\b(?:about|going)\s+to\s+lose\s+it\b",
            r"\blosing\s+(?:it|my\s+mind)\b",
            r"\bat\s+my\s+(?:breaking\s+point|limit|wit'?s?\s+end)\b",
            r"\bfalling\s+apart\b",
            r"\bcompletely\s+done\b",
        )),
    ),
)

# Head injury needs a fall/impact AND a concerning sign.
_FALL_RE = re.compile(
    r"\bfell\s+(?:off|from|down|out)\b|\bdropped\s+(?:him|her|them|the\s+baby|my\s+baby)\b|"
    r"\bhit\s+(?:his|her|their)\s+head\b|\bbanged\s+(?:his|her|their)\s+head\b|\bhead\s+injury\b|"
    r"\bfall\b|\bfell\b",
    re.IGNORECASE,
)
_HEAD_INJURY_SIGN_RE = re.compile(
    r"\bvomit\w*\b|\bthrew\s+up\b|\bthrowing\s+up\b|\bwon'?t\s+wake\b|\bcan'?t\s+wake\b|"
    r"\bhard\s+to\s+wake\b|\b(?:unusually|very|so)\s+(?:sleepy|drowsy)\b|\bpassed\s+out\b|"
    r"\bunconscious\b|\bknocked\s+out\b|\bseizure\b|\bbulging\b|\bswelling\b|\bswollen\b|"
    r"\bsoft\s+spot\b|\bunequal\s+pupils?\b|\bacting\s+(?:strange|different|off|weird)\b|"
    r"\binconsolable\b|\bnot\s+(?:himself|herself|themselves)\b",
    re.IGNORECASE,
)

# Weak-hit families: high-risk words that alone don't complete a rule but must
# never be silently passed (chat applies a see_doctor floor).
_WEAK_HIT_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fever", re.compile(r"\bfever(?:ish)?\b|\bfebrile\b|\btemp(?:erature)?\b", re.IGNORECASE)),
    ("breathing", re.compile(r"\bbreath\w*\b", re.IGNORECASE)),
    ("fall", re.compile(r"\bfell\b|\bfall\b|\bdropped\b", re.IGNORECASE)),
    ("vomit", re.compile(r"\bvomit\w*\b|\bthrew\s+up\b|\bthrowing\s+up\b", re.IGNORECASE)),
    ("choking", re.compile(r"\bchok\w+\b", re.IGNORECASE)),
)

_AFFIRMATIVE_FEVER_RE = re.compile(
    r"\b(?:has|have|had|running|got|with)\s+a\s+fever\b|\bfeels?\s+feverish\b|\bfebrile\b|"
    r"\bfeels?\s+(?:really\s+|very\s+)?hot\b|\bburning\s+up\b",
    re.IGNORECASE,
)

_NO_WET_DIAPER_HOURS_RE = re.compile(
    r"\b(?:no|not\s+(?:a\s+single|one)|hasn'?t\s+had\s+a)\s+wet\s+diaper\w*\b[^.!?]{0,30}?"
    r"\b(?:in|for|since)\s+(?:the\s+last\s+|over\s+|more\s+than\s+|about\s+)?(\d+)\+?\s*"
    r"(?:hours?|hrs?|h)\b",
    re.IGNORECASE,
)


@dataclass
class _Matches:
    entries: list[tuple[str, TriageLevel]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, slug: str, level: TriageLevel) -> None:
        if slug not in [slug_ for slug_, _ in self.entries]:
            self.entries.append((slug, level))


def evaluate_rules(text: str, age_days: int | None) -> RuleResult:
    scrubbed = _blank_negations(text)
    matches = _Matches()

    _match_fever(text, scrubbed, age_days, matches)

    for slug, level, patterns in _KEYWORD_RULES:
        if any(p.search(scrubbed) for p in patterns):
            matches.add(slug, level)
            if slug == "ingestion":
                matches.notes.append(f"Poison Control {POISON_CONTROL_NUMBER}")

    diaper_match = _NO_WET_DIAPER_HOURS_RE.search(scrubbed)
    if diaper_match and int(diaper_match.group(1)) >= DEHYDRATION_DIAPER_HOURS:
        matches.add("dehydration", TriageLevel.EMERGENCY)

    if _FALL_RE.search(scrubbed) and _HEAD_INJURY_SIGN_RE.search(scrubbed):
        matches.add("head_injury", TriageLevel.EMERGENCY)

    weak_words = tuple(
        word for word, pattern in _WEAK_HIT_WORDS if pattern.search(scrubbed)
    )

    if not matches.entries:
        return RuleResult(
            level=TriageLevel.NONE,
            weak_hit=bool(weak_words),
            weak_words=weak_words,
        )

    level = max((l for _, l in matches.entries), key=lambda l: l.severity)
    reason = next(slug for slug, l in matches.entries if l is level)
    return RuleResult(
        level=level,
        matched=tuple(slug for slug, _ in matches.entries),
        reason=reason,
        weak_hit=bool(weak_words),
        weak_words=weak_words,
        notes=tuple(matches.notes),
    )


def _match_fever(
    original: str, scrubbed: str, age_days: int | None, matches: _Matches
) -> None:
    temps = _extract_temps_fahrenheit(original)
    max_temp = max(temps, default=None)
    # Unknown age is treated as youngest (fail direction: over-escalate).
    under_3mo = age_days is None or age_days < FEVER_AGE_GATE_DAYS

    if max_temp is not None and max_temp >= FEVER_HIGH_THRESHOLD_F:
        matches.add("fever_high", TriageLevel.EMERGENCY)
    if max_temp is not None and max_temp >= FEVER_THRESHOLD_F and under_3mo:
        matches.add("fever_under_3mo", TriageLevel.EMERGENCY)
    if max_temp is None and under_3mo and _AFFIRMATIVE_FEVER_RE.search(scrubbed):
        # Fever reported but unmeasured in a <3mo: take a rectal temp + call now.
        matches.add("fever_under_3mo", TriageLevel.URGENT)
