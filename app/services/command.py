import re
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

SAP_COMMANDS: Dict[str, List[str]] = {
    "CONFIRM": ["confirm", "confirmed", "ok", "okay", "yes", "done"],
    "SKIP": ["skip", "next item", "pass"],
    "REPEAT": ["repeat", "say again", "what", "pardon"],
    "NEXT": ["next", "continue", "go"],
    "CANCEL": ["cancel", "abort", "stop", "quit"],
    "CAMERA": ["camera", "scan", "video", "open camera"],
    "TASK_OVERVIEW": ["task overview", "details", "show task"],
}

# Mapping for common number words
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
}

# Flat map: variant string → command key
_VARIANT_TO_COMMAND: Dict[str, str] = {
    variant: cmd
    for cmd, variants in SAP_COMMANDS.items()
    for variant in variants
}

_ALL_VARIANTS: List[str] = list(_VARIANT_TO_COMMAND.keys())

def _extract_number(text: str) -> Optional[int]:
    """Helper to extract a whole number from text (digits or words) ONLY if in context."""
    text = text.lower().strip()
    
    # SYSTEM RIGIDITY: Only accept numbers if:
    # 1. Spoken as an explicit command (Pick, Quantity, Count, Confirm)
    # 2. Spoken as a standalone number (exact match)
    
    valid_prefixes = ["pick", "quantity", "confirm", "count", "locate", "item", "total", "value"]
    
    # Check for standalone number first
    if re.fullmatch(r'\d+', text) or text in _NUMBER_WORDS:
        digit_match = re.search(r'\b(\d+)\b', text)
        if digit_match: return int(digit_match.group(1))
        return _NUMBER_WORDS.get(text)

    # Check for prefix context
    has_prefix = any(p in text for p in valid_prefixes)
    if not has_prefix:
        # If no valid action verb is found, we should be RIGID and ignore the number
        return None

    # 1. Simple digit check
    digit_match = re.search(r'\b(\d+)\b', text)
    if digit_match:
        return int(digit_match.group(1))
    
    # 2. Word-based number check (simplistic for 1-99)
    # e.g., 'twenty three'
    words = text.split()
    total = 0
    found = False
    for word in words:
        word = word.replace("-", " ")
        parts = word.split()
        for p in parts:
            if p in _NUMBER_WORDS:
                total += _NUMBER_WORDS[p]
                found = True
    
    return total if found else None

def fuzzy_match_command(transcribed: str, word_map: Optional[Dict[str, str]] = None) -> Tuple[str, float]:
    """Return (command_key, confidence 0.0-1.0) for the closest SAP command match."""
    text = transcribed.strip().lower()
    if not text:
        return ("UNKNOWN", 0.0)

    # Apply per-worker locale substitutions (e.g. "DEZ" → "10" for Portuguese workers)
    if word_map:
        for src, dst in word_map.items():
            text = re.sub(r'\b' + re.escape(src.lower()) + r'\b', dst.lower(), text)

    # PRIORITY 1: Explicit Number Check (Pick cases)
    # This avoids "Pick 23" being matched to "Pick 2"
    number = _extract_number(text)
    if number is not None:
        # If it looks like a picking command or just a raw number
        # SAP EWM often accepts raw numbers as picking confirmation
        return (f"QUANTITY_{number}", 1.0)

    # PRIORITY 2: Fuzzy Match for Generic Commands
    result = process.extractOne(text, _ALL_VARIANTS, scorer=fuzz.WRatio)
    if result is None:
        return ("UNKNOWN", 0.0)

    matched_variant, score, _ = result
    
    # Threshold for fuzzy match
    if score < 70:
        return ("UNKNOWN", score / 100.0)

    command_key = _VARIANT_TO_COMMAND[matched_variant]
    return (command_key, score / 100.0)

CALIBRATION_PASSAGE = (
    "Please read this passage at your normal pace.\n\n"
    "The morning shift begins at six. Walk to bay three and confirm the first order. "
    "Repeat: one, two, three, four, five, six, seven, eight, nine, ten, eleven, "
    "twelve, thirteen, fourteen, fifteen, sixteen, seventeen, eighteen, nineteen, twenty. "
    "Skip to the next aisle when the bin is empty. Cancel if the label does not match. "
    "The quick brown fox jumps over the lazy dog."
)
