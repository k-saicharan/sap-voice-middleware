from typing import Dict, List, Tuple

from rapidfuzz import fuzz, process

SAP_COMMANDS: Dict[str, List[str]] = {
    "CONFIRM": ["confirm", "confirmed", "ok", "okay", "yes", "done"],
    "SKIP": ["skip", "next item", "pass"],
    "REPEAT": ["repeat", "say again", "what", "pardon"],
    "NEXT": ["next", "continue", "go"],
    "CANCEL": ["cancel", "abort", "stop", "quit"],
    "QUANTITY_1": ["one", "1"],
    "QUANTITY_2": ["two", "2"],
    "QUANTITY_3": ["three", "3"],
    "QUANTITY_4": ["four", "4"],
    "QUANTITY_5": ["five", "5"],
    "QUANTITY_6": ["six", "6"],
    "QUANTITY_7": ["seven", "7"],
    "QUANTITY_8": ["eight", "8"],
    "QUANTITY_9": ["nine", "9"],
    "QUANTITY_10": ["ten", "10"],
    "QUANTITY_11": ["eleven", "11"],
    "QUANTITY_12": ["twelve", "12"],
    "QUANTITY_13": ["thirteen", "13"],
    "QUANTITY_14": ["fourteen", "14"],
    "QUANTITY_15": ["fifteen", "15"],
    "QUANTITY_16": ["sixteen", "16"],
    "QUANTITY_17": ["seventeen", "17"],
    "QUANTITY_18": ["eighteen", "18"],
    "QUANTITY_19": ["nineteen", "19"],
    "QUANTITY_20": ["twenty", "20"],
}

# Flat map: variant string → command key
_VARIANT_TO_COMMAND: Dict[str, str] = {
    variant: cmd
    for cmd, variants in SAP_COMMANDS.items()
    for variant in variants
}

_ALL_VARIANTS: List[str] = list(_VARIANT_TO_COMMAND.keys())

# Calibration passage — phonetically rich, ~30s at a natural reading pace.
# Covers all core English phonemes, numbers 1-20, and warehouse command vocabulary.
# Workers read this naturally; the system extracts their voice profile from it,
# not the content. The same passage is used for every worker.
CALIBRATION_PASSAGE = (
    "Please read this passage at your normal pace.\n\n"
    "The morning shift begins at six. Walk to bay three and confirm the first order. "
    "Repeat: one, two, three, four, five, six, seven, eight, nine, ten, eleven, "
    "twelve, thirteen, fourteen, fifteen, sixteen, seventeen, eighteen, nineteen, twenty. "
    "Skip to the next aisle when the bin is empty. Cancel if the label does not match. "
    "The quick brown fox jumps over the lazy dog."
)


def fuzzy_match_command(transcribed: str) -> Tuple[str, float]:
    """Return (command_key, confidence 0.0-1.0) for the closest SAP command match."""
    text = transcribed.strip().lower()
    if not text:
        return ("UNKNOWN", 0.0)

    result = process.extractOne(text, _ALL_VARIANTS, scorer=fuzz.WRatio)
    if result is None:
        return ("UNKNOWN", 0.0)

    matched_variant, score, _ = result
    command_key = _VARIANT_TO_COMMAND[matched_variant]
    return (command_key, score / 100.0)
