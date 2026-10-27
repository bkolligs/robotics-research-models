"""Paper-presence matcher for robotics model variants.

A paper counts at most once per variant. A more specific alias consumes its
span before a shorter sibling, so "pi0.5" is not also "pi0", and "gr00t n1.5"
is not also "gr00t n1". Bare "gr00t" is its own unspecified row, not N1.
"""

from __future__ import annotations

import re
import unicodedata

from mentions.taxonomy import VARIANTS

_SUB = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "₊": "+", "₋": "-", "⋆": "*", "∗": "*", "·": "",
})

# arXiv HTML emits both the rendered form and the TeX, e.g. "π 0.5 \pi_{0.5}".
# The version must be a braced subscript or a dotted minor ("0.5"). A bare
# "\pi 0" is a control-paper juxtaposition ("2\pi rad/s, 0 < a"), not π0.
_TEX = re.compile(
    r"\\pi\s*(?:\^\s*\{?\s*\*?\s*\}?\s*)?_?\s*\{(\*?\s*[0-9]+(?:\.[0-9]+)?)\s*\}"
    r"(?:\s*-?\s*fast)?"
    r"|\\pi\s*([0-9]+\.[0-9]+)(?:\s*-?\s*fast)?",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_SUB)
    # Keep the greek letter for the π-series aliases. "pi0" is policy
    # notation; the model is written "π0" or "π₀". The TeX fold below
    # still turns \pi_{0.5} into pi0.5, which is how arXiv HTML writes
    # the dotted releases.
    text = text.replace("Π", "π")
    text = text.lower()
    text = text.replace("–", "-").replace("—", "-")

    def _pi(m: re.Match[str]) -> str:
        ver = (m.group(1) or m.group(2) or "").replace(" ", "")
        fast = "-fast" if re.search(r"fast", m.group(0)) else ""
        return f" pi{ver}{fast} "

    # TeX first, while backslashes are still intact.
    text = _TEX.sub(_pi, text)
    # arXiv HTML renders the model as "π 0.5" and the TeX fold emits
    # "pi0.5". Collapse the spaced greek form onto the alias token.
    text = re.sub(
        r"(?<![a-z0-9])π\s+(\*?\s*[0-9]+(?:\.[0-9]+)?)",
        lambda m: "π" + re.sub(r"\s+", "", m.group(1)),
        text,
    )
    text = re.sub(r"\s+", " ", text)
    return f" {text} "


def _alias_pattern(alias: str) -> re.Pattern[str]:
    alias = normalize(alias).strip()
    # Keep dots and hyphens inside the token; require a boundary on each side
    # so "rt-1" does not match inside "rt-10" and "n1.5" does not match "n1.50".
    body = re.escape(alias)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


# Longest alias first, globally, so a specific variant claims the span
# before a shorter alias of another variant in the same family.
_RULES: list[tuple[str, str, re.Pattern[str]]] = []
for _vid, _label, _fid, _flabel, _country, _company, _access, _year, aliases in VARIANTS:
    for alias in aliases:
        _RULES.append((_vid, alias, _alias_pattern(alias)))
_RULES.sort(key=lambda row: len(normalize(row[1]).strip()), reverse=True)

VARIANT_IDS = [row[0] for row in VARIANTS]
FAMILY_OF = {row[0]: row[2] for row in VARIANTS}
LABEL_OF = {row[0]: row[1] for row in VARIANTS}


# pi0 / $\pi_{0}$ is policy notation unless the paper is talking about the
# Physical Intelligence model. A model cue within this window is required
# before those spellings count. The dotted releases (pi0.5, pi05) do not
# need it: they are not policy notation.
_PI0_CUE = re.compile(
    r"physical intelligence|openpi|vision-language-action|\bvla\b|"
    r"pi0\.5|pi0-fast|π0\.5|π0-fast|flow-matching|flow matching"
)
# ASCII "pi0", and the TeX / greek forms that normalize to the same token.
_PI0_AMBIGUOUS = re.compile(
    r"(?<![a-z0-9])pi0(?![a-z0-9.])"
    r"|\\pi_\{\s*0\s*\}"
    r"|\\pi_0(?![0-9.])"
    r"|(?<![a-z0-9])π\s*0(?![0-9.])"
)


def _pi0_is_model(text: str) -> bool:
    folded = text.lower()
    for match in _PI0_AMBIGUOUS.finditer(folded):
        window = folded[max(0, match.start() - 180):match.end() + 180]
        if _PI0_CUE.search(window):
            return True
    return False


def find_variants(text: str) -> set[str]:
    """Return variant ids present in text. Each variant at most once.

    Every alias hit is a candidate. At each character span the longest
    candidate wins, so a second "pi0.5" later in the paper cannot be
    re-read as "pi0".
    """
    norm = normalize(text)
    candidates: list[tuple[int, int, str]] = []
    for vid, _alias, pattern in _RULES:
        for match in pattern.finditer(norm):
            candidates.append((match.start(), match.end(), vid))
    # Leftmost, then longest. A shorter alias nested in a longer one loses.
    candidates.sort(key=lambda row: (row[0], -(row[1] - row[0])))
    occupied: list[tuple[int, int]] = []
    found: set[str] = set()

    def overlaps(start: int, end: int) -> bool:
        return any(not (end <= a or start >= b) for a, b in occupied)

    for start, end, vid in candidates:
        if overlaps(start, end):
            continue
        occupied.append((start, end))
        found.add(vid)
    if "pi0" not in found and _pi0_is_model(text):
        found.add("pi0")
    return found


def find_families(text: str) -> set[str]:
    return {FAMILY_OF[vid] for vid in find_variants(text)}
