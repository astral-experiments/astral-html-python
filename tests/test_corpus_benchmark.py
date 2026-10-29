import gzip
import hashlib
import tarfile
from importlib import import_module
from io import BytesIO
from pathlib import Path

import pytest


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    for package in ("bs4", "lxml", "cssselect", "selectolax"):
        pytest.importorskip(package)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    bench = import_module("run")

    same = b'<a href="/">one <b>two</b></a>'
    different = b'<a href="/one">one<a href="/two">two</a>'
    also_different = different.replace(b"two", b"three")
    too_deep = b"<div>" * 257
    archive = tmp_path / "wcxb.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, body in (
            ("dev/html/1", same),
            ("test/html/1", same),
            ("test/html/2", different),
            ("test/html/3", too_deep),
            ("test/html/4", also_different),
        ):
            data = gzip.compress(body)
            member = tarfile.TarInfo(f"wcxb/{name}.html.gz")
            member.size = len(data)
            tar.addfile(member, BytesIO(data))

    keys = {
        body: hashlib.sha256(body).digest()
        for body in (same, different, also_different, too_deep)
    }
    monkeypatch.setattr(
        bench,
        "WCXB_DIGEST",
        hashlib.sha256(b"".join(sorted(keys.values()))).hexdigest(),
    )
    # The reference parsers agree on all four fixture pages. Astral preserves
    # the nested anchors and rejects the page that exceeds its nesting limit.
    reference = "6b430deb57b453ec5d96e9fe18fec59432e32be2bb25a1cc17dae1aa6188429f"
    monkeypatch.setattr(
        bench,
        "WCXB_OUTPUT_DIGESTS",
        {
            "astral-html": "85d0b04d17853fc075f65fad6a601128488c51777ef9081ceae52e8b08e8ab7e",
            "selectolax (Lexbor)": reference,
            "lxml": reference,
            "Beautiful Soup": reference,
        },
    )
    return bench, archive, [keys[same]], {keys[different], keys[also_different]}


def test_corpus_deduplication_and_output_groups(corpus, monkeypatch, capsys):
    bench, archive, expected_matching, expected_differing = corpus
    matching, differing = bench.check_wcxb(archive)
    assert matching == expected_matching
    assert set(differing) == expected_differing
    assert "astral-html rejected test/html/3.html.gz" in capsys.readouterr().out

    # One microsecond for the matching page and five for the two differing pages.
    ticks = iter((0, 1_000, 1_000, 6_000) * len(bench.PARSERS))
    monkeypatch.setattr(bench, "perf_counter_ns", lambda: next(ticks))
    times = bench.wcxb_sample(archive, (matching, differing), seed=0)
    assert list(times.values()) == [(2.0, 1.0)] * len(bench.PARSERS)

    monkeypatch.setattr(bench, "WCXB_DIGEST", "")
    with pytest.raises(ValueError, match="pinned WCXB corpus"):
        bench.check_wcxb(archive)


@pytest.mark.parametrize(
    ("drop_links", "message"),
    [(True, "No pages produced identical output"), (False, "pinned results")],
)
def test_corpus_check_rejects_shared_astral_regression(
    corpus, monkeypatch, drop_links, message
):
    bench, archive, _, _ = corpus

    def broken_links(doc, css):
        if drop_links:
            return []
        # Only alter an already-differing page. Agreement and link counts stay put.
        return [
            (href, text.replace("three", "3"))
            for href, text in bench.astral_links(doc, css)
        ]

    monkeypatch.setattr(
        bench,
        "PARSERS",
        [
            (name, parse, broken_links if links is bench.astral_links else links)
            for name, parse, links in bench.PARSERS
        ],
    )
    with pytest.raises(ValueError, match=message):
        bench.run_wcxb(archive, samples=2, check_only=True)
