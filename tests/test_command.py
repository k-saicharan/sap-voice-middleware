import pytest
from app.services.command import fuzzy_match_command, CALIBRATION_PASSAGE, SAP_COMMANDS


def test_exact_match_confirm():
    cmd, conf = fuzzy_match_command("confirm")
    assert cmd == "CONFIRM"
    assert conf > 0.9


def test_exact_match_quantity():
    cmd, conf = fuzzy_match_command("ten")
    assert cmd == "QUANTITY_10"
    assert conf > 0.9


def test_fuzzy_match_typo():
    cmd, conf = fuzzy_match_command("cnfirm")
    assert cmd == "CONFIRM"
    assert conf > 0.5


def test_numeric_string():
    cmd, conf = fuzzy_match_command("10")
    assert cmd == "QUANTITY_10"
    assert conf > 0.8


def test_empty_returns_unknown():
    cmd, conf = fuzzy_match_command("")
    assert cmd == "UNKNOWN"
    assert conf == 0.0


def test_calibration_passage_is_nonempty():
    assert len(CALIBRATION_PASSAGE) > 100


def test_calibration_passage_contains_numbers():
    passage_lower = CALIBRATION_PASSAGE.lower()
    for word in ["one", "ten", "twenty"]:
        assert word in passage_lower, f"'{word}' not found in calibration passage"


def test_calibration_passage_contains_command_words():
    passage_lower = CALIBRATION_PASSAGE.lower()
    for word in ["confirm", "skip", "cancel", "next"]:
        assert word in passage_lower, f"'{word}' not found in calibration passage"


def test_all_commands_have_variants():
    for cmd, variants in SAP_COMMANDS.items():
        assert len(variants) >= 1, f"{cmd} has no variants"
