"""
Tests for the _parse_seconds timestamp-extraction helper.

The `parse_seconds` fixture supplies the *real* function, extracted from main.py
by conftest.py — see the note there on why it cannot simply be imported.
"""


class TestParseSecondsHHMMSS:
    def test_plain_hhmmss(self, parse_seconds):
        assert parse_seconds("1:02:30") == 3750

    def test_hhmmss_embedded_in_sentence(self, parse_seconds):
        assert parse_seconds("The scene starts at 0:01:45 in the movie.") == 105

    def test_hhmmss_zero_hours(self, parse_seconds):
        assert parse_seconds("0:00:05") == 5


class TestParseSecondsMmss:
    def test_plain_mmss(self, parse_seconds):
        assert parse_seconds("2:30") == 150

    def test_mmss_embedded(self, parse_seconds):
        assert parse_seconds("Jump to 10:00.") == 600

    def test_mmss_single_minute(self, parse_seconds):
        assert parse_seconds("1:00") == 60


class TestParseSecondsNaturalLanguage:
    def test_minutes_and_seconds(self, parse_seconds):
        assert parse_seconds("2 minutes and 30 seconds") == 150

    def test_minutes_only(self, parse_seconds):
        assert parse_seconds("5 minutes") == 300

    def test_seconds_only(self, parse_seconds):
        assert parse_seconds("45 seconds") == 45

    def test_abbreviated_min_sec(self, parse_seconds):
        assert parse_seconds("1 min 30 sec") == 90

    def test_plural_minutes_seconds(self, parse_seconds):
        assert parse_seconds("3 minutes 15 seconds into the video") == 195


class TestParseSecondsPlainNumber:
    def test_integer_string(self, parse_seconds):
        assert parse_seconds("150") == 150.0

    def test_float_string(self, parse_seconds):
        assert parse_seconds("90.5") == 90.5

    def test_number_with_surrounding_text(self, parse_seconds):
        assert parse_seconds("seek to 300 seconds") == 300.0


class TestParseSecondsNone:
    def test_empty_string(self, parse_seconds):
        assert parse_seconds("") is None

    def test_no_numbers(self, parse_seconds):
        assert parse_seconds("I don't know.") is None

    def test_whitespace_only(self, parse_seconds):
        assert parse_seconds("   ") is None


class TestParseSecondsPriority:
    def test_hhmmss_wins_over_mmss(self, parse_seconds):
        # "1:02:30" should be parsed as HH:MM:SS = 3750, not MM:SS
        assert parse_seconds("1:02:30") == 3750

    def test_natural_language_wins_over_plain_number(self, parse_seconds):
        # "2 minutes and 30 seconds" → 150, not just "2" or "30"
        assert parse_seconds("2 minutes and 30 seconds") == 150
