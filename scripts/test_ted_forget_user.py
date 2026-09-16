"""The containment rule in ted-forget-user.py, which is the part that unlinks.

Everything else in that script reads or refuses. This is the one place it
removes a file, and the filename comes out of message text the gateway wrote,
so it is input rather than a constant. A path that escapes the cache would be
deleting something nobody asked it to.
"""

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent / "ted-forget-user.py"
spec = importlib.util.spec_from_file_location("ted_forget_user", MODULE)
forget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forget)


def deletable(path: str) -> bool:
    """The exact test the script applies before unlinking."""
    p = Path(path)
    return any(p.is_relative_to(root) for root in forget.DELETABLE_ROOTS)


@pytest.mark.parametrize(
    "path",
    [
        "~/.hermes/cache/images/img_2ae20ec5d829.jpg",
        "~/.hermes/cache/audio/voice_abc123.ogg",
    ],
)
def test_cached_media_is_deletable(path):
    assert deletable(str(Path(path).expanduser()))


@pytest.mark.parametrize(
    "path",
    [
        "~/.hermes/state.db",
        "~/.hermes/SOUL.md",
        "~/.hermes/logs/agent.log",
        "~/.ssh/id_rsa",
        "/etc/passwd",
        "~/Documents/build-week-health accountability partner/hermes/SOUL.md",
        # The traversal shape: a path that starts inside the cache and climbs
        # out of it. `is_relative_to` compares the literal parts, so this has
        # to be checked rather than assumed.
        "~/.hermes/cache/images/../../SOUL.md",
    ],
)
def test_everything_else_is_not(path):
    assert not deletable(str(Path(path).expanduser().resolve()))


def test_the_media_pattern_only_matches_media():
    """A path in message text is only a candidate if it looks like an upload."""
    found = forget.MEDIA_PATH.findall(
        "logged it /Users/x/.hermes/cache/images/a.jpg and "
        "/Users/x/.hermes/state.db and /Users/x/.hermes/cache/audio/b.ogg"
    )
    assert found == [
        "/Users/x/.hermes/cache/images/a.jpg",
        "/Users/x/.hermes/cache/audio/b.ogg",
    ]


def test_the_roots_are_the_two_cache_directories():
    """If a third root is ever added it should be a deliberate edit, not a
    surprise found while reading a deletion that went too far."""
    assert [p.name for p in forget.DELETABLE_ROOTS] == ["images", "audio"]
    assert all(p.parent.name == "cache" for p in forget.DELETABLE_ROOTS)
