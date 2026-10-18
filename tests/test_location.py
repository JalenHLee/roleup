"""Tests for location.is_us_or_unclear: drop only when every location is clearly non-US."""

import pytest

from src.location import is_us_or_unclear


@pytest.mark.parametrize("location", [
    "New York, NY; London, UK",  # mixed: any US location keeps it
    "Markham, ON, Canada; Bellevue, WA, United States",
    "San Francisco, CA",
    "Austin, Texas",
    "Remote in USA",
    "United States",
    "London, KY",  # US state code wins over "London"
    "Indianapolis, IN",
    "Remote",  # unclear: kept
    "SF",
    "",
])
def test_kept(location):
    assert is_us_or_unclear(location)


@pytest.mark.parametrize("location", [
    "London, UK",
    "Toronto, ON, Canada",
    "Vancouver, BC",
    "Calgary, AB, Canada",
    "Montréal, QC",
    "Remote in Canada",
    "Hyderabad, India",
    "Manchester, UK; Toronto, ON, Canada",  # all non-US
    "United Kingdom",
])
def test_dropped(location):
    assert not is_us_or_unclear(location)
