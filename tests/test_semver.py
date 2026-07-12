import pytest

from app.semver import SemVer


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.9.9", "0.10.0"),
        ("0.11.9", "0.12.0"),
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-beta"),
        ("1.0.0-rc.1", "1.0.0"),
    ],
)
def test_semantic_version_ordering(older: str, newer: str) -> None:
    assert SemVer.parse(older) < SemVer.parse(newer)


def test_build_metadata_does_not_affect_precedence() -> None:
    assert SemVer.parse("1.2.3+build.1") == SemVer.parse("1.2.3+build.2")


@pytest.mark.parametrize("invalid", ["1.2", "01.2.3", "1.2.3-01", "v1.2.3", "../1.2.3"])
def test_invalid_semantic_versions(invalid: str) -> None:
    with pytest.raises(ValueError):
        SemVer.parse(invalid)
