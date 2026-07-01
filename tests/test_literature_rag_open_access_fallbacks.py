"""Tests for direct open-access literature download fallbacks."""

from pathlib import Path

import pytest

from src.agents.deep_interpreter.tools import literature_rag


def test_get_unpaywall_email_prefers_unpaywall_env(monkeypatch):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "unpaywall@example.com")
    monkeypatch.setenv("PUBMED_EMAIL", "pubmed@example.com")

    assert literature_rag._get_unpaywall_email() == "unpaywall@example.com"


def test_get_unpaywall_email_falls_back_to_pubmed_email(monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    monkeypatch.setenv("PUBMED_EMAIL", "pubmed@example.com")

    assert literature_rag._get_unpaywall_email() == "pubmed@example.com"


def test_paper_text_quality_rejects_paywall_preview():
    text = """
    Abstract
    This paper has a useful abstract.
    This is a preview of subscription content, log in via an institution to check access.
    Buy article PDF USD 39.95.
    """

    status, reason = literature_rag._paper_text_quality(text)

    assert status == "not_fulltext"
    assert "paywall" in reason


def test_paper_text_quality_accepts_long_sectioned_text():
    text = "\n".join(
        [
            "Abstract",
            "Idiopathic pulmonary fibrosis text.",
            "Introduction",
            "A" * 6000,
            "Methods",
            "B" * 6000,
            "Results",
            "C" * 6000,
            "Discussion",
            "D" * 6000,
            "References",
        ]
    )

    status, reason = literature_rag._paper_text_quality(text)

    assert status == "likely_fulltext"
    assert "section signals" in reason


def test_extract_text_from_html_strips_markup():
    content = (
        b"<html><body><h1>Title</h1><p>Abstract text</p>"
        b"<script>bad()</script></body></html>"
    )

    text = literature_rag._extract_text_from_response(content, "text/html")

    assert "Title" in text
    assert "Abstract text" in text
    assert "bad()" not in text


def test_fetch_pubmed_dois_parses_batch_xml(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = """<?xml version="1.0"?>
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation><PMID>123</PMID><Article /></MedlineCitation>
            <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/test</ArticleId></ArticleIdList></PubmedData>
          </PubmedArticle>
          <PubmedArticle>
            <MedlineCitation><PMID>456</PMID><Article><ELocationID EIdType="doi">10.1000/fallback</ELocationID></Article></MedlineCitation>
          </PubmedArticle>
        </PubmedArticleSet>"""

        def raise_for_status(self):
            return None

    def fake_get(url, params=None, timeout=None, headers=None):
        assert "efetch.fcgi" in url
        assert params["id"] == "123,456"
        return FakeResponse()

    monkeypatch.setattr(literature_rag.requests, "get", fake_get)

    assert literature_rag._fetch_pubmed_dois(["123", "456"]) == {
        "123": "10.1000/test",
        "456": "10.1000/fallback",
    }


def test_try_crossref_fulltext_downloads_likely_text(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        def __init__(self, status_code=200, payload=None, content=b"", content_type="text/html"):
            self.status_code = status_code
            self._payload = payload
            self.content = content
            self.headers = {"content-type": content_type}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append(url)
        if "api.crossref.org" in url:
            return FakeResponse(
                payload={
                    "message": {
                        "link": [
                            {
                                "URL": "https://example.org/fulltext.html",
                                "content-type": "text/html",
                                "intended-application": "text-mining",
                            }
                        ]
                    }
                }
            )
        return FakeResponse(
            content=(
                b"Abstract\nIntroduction\n"
                + b"A" * 7000
                + b"\nMethods\n"
                + b"B" * 7000
                + b"\nResults\n"
                + b"C" * 7000
                + b"\nDiscussion\nReferences"
            ),
            content_type="text/html",
        )

    monkeypatch.setattr(literature_rag.requests, "get", fake_get)
    output = tmp_path / "pmid_123.txt"

    result = literature_rag._try_crossref_fulltext("123", "10.1000/test", str(output))

    assert result["success"] is True
    assert result["source"] == "Crossref"
    assert output.exists()
    assert "Source: Crossref" in output.read_text()
    assert calls[0].startswith("https://api.crossref.org/works/")


def test_try_unpaywall_fulltext_requires_email(monkeypatch, tmp_path):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    monkeypatch.delenv("PUBMED_EMAIL", raising=False)

    result = literature_rag._try_unpaywall_fulltext(
        "123", "10.1000/test", str(tmp_path / "x.txt")
    )

    assert result["success"] is False
    assert result["source"] == "Unpaywall"
    assert "UNPAYWALL_EMAIL" in result["message"]


def test_try_unpaywall_fulltext_downloads_best_oa_pdf(monkeypatch, tmp_path):
    class FakeResponse:
        def __init__(self, payload=None, content=b"", content_type="text/html"):
            self.status_code = 200
            self._payload = payload
            self.content = content
            self.headers = {"content-type": content_type}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        if "api.unpaywall.org" in url:
            return FakeResponse(
                payload={
                    "is_oa": True,
                    "oa_status": "green",
                    "best_oa_location": {
                        "url_for_pdf": "https://repo.example/full.pdf",
                        "host_type": "repository",
                    },
                    "oa_locations": [],
                }
            )
        return FakeResponse(
            content=(
                b"Abstract\nIntroduction\n"
                + b"A" * 7000
                + b"\nMethods\n"
                + b"B" * 7000
                + b"\nResults\n"
                + b"C" * 7000
                + b"\nDiscussion\nReferences"
            ),
            content_type="text/html",
        )

    monkeypatch.setenv("UNPAYWALL_EMAIL", "unpaywall@example.com")
    monkeypatch.setattr(literature_rag.requests, "get", fake_get)
    output = tmp_path / "pmid_123.txt"

    result = literature_rag._try_unpaywall_fulltext("123", "10.1000/test", str(output))

    assert result["success"] is True
    assert result["source"] == "Unpaywall"
    assert "OA Status: green" in output.read_text()


class FakeDownloadTool:
    name = "download_paper"

    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        Path(payload["output_path"]).write_text("Abstract\nfallback text", encoding="utf-8")
        return {"success": True, "source": "PubMed_Abstract"}


@pytest.mark.asyncio
async def test_download_papers_uses_crossref_after_mcp_abstract_fallback(
    monkeypatch,
    tmp_path,
):
    tool = FakeDownloadTool()
    monkeypatch.setenv("PUBMED_MCP_PYTHON", "/python")
    monkeypatch.setenv("PUBMED_MCP_SERVER", "/server.py")

    async def fake_tools():
        return [tool]

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(literature_rag, "_get_pubmed_download_tools", fake_tools)
    monkeypatch.setattr(literature_rag, "_fetch_pubmed_dois", lambda pmids: {"123": "10.1000/test"})
    monkeypatch.setattr(literature_rag.asyncio, "sleep", fake_sleep)

    def fake_crossref(pmid, doi, output_path):
        Path(output_path).write_text(
            "Source: Crossref\nFull Text\n" + "A" * 25000,
            encoding="utf-8",
        )
        return {"success": True, "file_path": output_path, "source": "Crossref"}

    monkeypatch.setattr(literature_rag, "_try_crossref_fulltext", fake_crossref)
    monkeypatch.setattr(
        literature_rag,
        "_try_unpaywall_fulltext",
        lambda *args: {"success": False, "source": "Unpaywall"},
    )

    result = await literature_rag.download_papers_for_rag(["123"], output_dir=str(tmp_path))

    assert result["123"]["source"] == "Crossref"
    assert tool.calls == [
        {
            "pmid": "123",
            "doi": "10.1000/test",
            "output_path": str(tmp_path / "pmid_123.txt"),
            "prefer_pmc": True,
        }
    ]


@pytest.mark.asyncio
async def test_download_papers_uses_unpaywall_after_mcp_and_crossref(
    monkeypatch,
    tmp_path,
):
    tool = FakeDownloadTool()
    monkeypatch.setenv("PUBMED_MCP_PYTHON", "/python")
    monkeypatch.setenv("PUBMED_MCP_SERVER", "/server.py")

    async def fake_tools():
        return [tool]

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(literature_rag, "_get_pubmed_download_tools", fake_tools)
    monkeypatch.setattr(literature_rag, "_fetch_pubmed_dois", lambda pmids: {"123": "10.1000/test"})
    monkeypatch.setattr(literature_rag.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        literature_rag,
        "_try_crossref_fulltext",
        lambda *args: {"success": False, "source": "Crossref"},
    )

    def fake_unpaywall(pmid, doi, output_path):
        Path(output_path).write_text(
            "Source: Unpaywall\nFull Text\n" + "B" * 25000,
            encoding="utf-8",
        )
        return {"success": True, "file_path": output_path, "source": "Unpaywall"}

    monkeypatch.setattr(literature_rag, "_try_unpaywall_fulltext", fake_unpaywall)

    result = await literature_rag.download_papers_for_rag(["123"], output_dir=str(tmp_path))

    assert result["123"]["source"] == "Unpaywall"
    assert tool.calls == [
        {
            "pmid": "123",
            "doi": "10.1000/test",
            "output_path": str(tmp_path / "pmid_123.txt"),
            "prefer_pmc": True,
        }
    ]


@pytest.mark.asyncio
async def test_download_papers_passes_doi_to_mcp_after_direct_fallbacks_fail(
    monkeypatch,
    tmp_path,
):
    tool = FakeDownloadTool()
    monkeypatch.setenv("PUBMED_MCP_PYTHON", "/python")
    monkeypatch.setenv("PUBMED_MCP_SERVER", "/server.py")

    async def fake_tools():
        return [tool]

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(literature_rag, "_get_pubmed_download_tools", fake_tools)
    monkeypatch.setattr(literature_rag, "_fetch_pubmed_dois", lambda pmids: {"123": "10.1000/test"})
    monkeypatch.setattr(
        literature_rag,
        "_try_crossref_fulltext",
        lambda *args: {"success": False, "source": "Crossref"},
    )
    monkeypatch.setattr(
        literature_rag,
        "_try_unpaywall_fulltext",
        lambda *args: {"success": False, "source": "Unpaywall"},
    )
    monkeypatch.setattr(literature_rag.asyncio, "sleep", fake_sleep)

    result = await literature_rag.download_papers_for_rag(["123"], output_dir=str(tmp_path))

    assert result["123"]["source"] == "PubMed_Abstract"
    assert tool.calls == [
        {
            "pmid": "123",
            "doi": "10.1000/test",
            "output_path": str(tmp_path / "pmid_123.txt"),
            "prefer_pmc": True,
        }
    ]
