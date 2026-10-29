import gzip
import hashlib
import json
from importlib import import_module
from pathlib import Path

import pytest


@pytest.fixture
def bench(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "benchmarks"))
    return import_module("wheel_abi")


def test_rejects_page_ids_that_escape_the_sample_directory(bench, tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "test/html").mkdir(parents=True)
    dest = tmp_path / "sample/pages"
    dest.mkdir(parents=True)
    canary = tmp_path / "canary"
    canary.write_text("keep")
    (corpus / "canary.html.gz").write_bytes(gzip.compress(b"overwritten"))
    (corpus / "metadata.json").write_text(
        json.dumps(
            {
                "files": {
                    "../../canary": {
                        "split": "test",
                        "domain": "d",
                        "page_type": "article",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="page IDs"):
        bench.prepare_pages(corpus, dest)
    assert canary.read_text() == "keep"


def test_pins_selected_html_even_when_extraction_would_be_unchanged(
    bench, tmp_path, monkeypatch
):
    corpus = tmp_path / "corpus"
    bodies = corpus / "test/html"
    bodies.mkdir(parents=True)
    dest = tmp_path / "pages"
    dest.mkdir()
    meta = {}
    digest = hashlib.sha256()
    for i in range(20):
        key = f"{i:04}"
        html = f"<!--{i}--><a href='/'>link</a>".encode()
        meta[key] = {"split": "test", "domain": "d", "page_type": "article"}
        (bodies / f"{key}.html.gz").write_bytes(gzip.compress(html))
        digest.update(key.encode("ascii"))
        digest.update(hashlib.sha256(html).digest())
    (corpus / "metadata.json").write_text(json.dumps({"files": meta}))
    monkeypatch.setattr(bench, "SAMPLE_SHA256", digest.hexdigest())
    assert bench.prepare_pages(corpus, dest)["pages"] == 20
    (bodies / "0000.html.gz").write_bytes(
        gzip.compress(b"<!--X--><a href='/'>link</a>")
    )
    with pytest.raises(ValueError, match="pinned WCXB sample"):
        bench.prepare_pages(corpus, dest)
