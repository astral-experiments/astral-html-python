import gzip
import hashlib
import tarfile
from importlib import import_module
from io import BytesIO
from pathlib import Path

import pytest


def test_corpus_deduplication_and_output_groups(tmp_path, monkeypatch, capsys):
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

    with pytest.raises(ValueError, match="pinned WCXB corpus"):
        bench.check_wcxb(archive)
    keys = {
        body: hashlib.sha256(body).digest()
        for body in (same, different, also_different, too_deep)
    }
    monkeypatch.setattr(
        bench,
        "WCXB_DIGEST",
        hashlib.sha256(b"".join(sorted(keys.values()))).hexdigest(),
    )
    matching, differing = bench.check_wcxb(archive)
    assert matching == [keys[same]]
    assert set(differing) == {keys[different], keys[also_different]}
    assert "astral-html rejected test/html/3.html.gz" in capsys.readouterr().out

    # One microsecond for the matching page and five for the two differing pages.
    ticks = iter((0, 1_000, 1_000, 6_000) * len(bench.PARSERS))
    monkeypatch.setattr(bench, "perf_counter_ns", lambda: next(ticks))
    times = bench.wcxb_sample(archive, (matching, differing), seed=0)
    assert list(times.values()) == [(2.0, 1.0)] * len(bench.PARSERS)
