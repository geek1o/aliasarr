from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.models.db import IndexerType
from app.services.indexer_adapters import parse_xml_releases
from app.services.indexer_diagnostics import diagnose_indexer, parse_capabilities
from app.services.indexer_service import NewznabIndexerClient, get_indexer_client
from app.services.torznab import TorznabRelease


CAPABILITIES_XML = """<?xml version="1.0"?>
<caps>
  <searching>
    <search available="yes" supportedParams="q" />
    <tv-search available="yes" supportedParams="q,season,ep" />
  </searching>
  <categories>
    <category id="5000" name="TV">
      <subcat id="5030" name="TV/SD" />
    </category>
  </categories>
</caps>
"""

TORZNAB_XML = """<?xml version="1.0"?>
<rss xmlns:t="http://torznab.com/schemas/2015/feed"><channel><item>
  <title><b>Олдскул</b> S01E01 1080p WEB-DL</title>
  <guid>release-1</guid>
  <comments>https://tracker.test/details/1</comments>
  <enclosure url="https://tracker.test/download/1" length="1073741824" />
  <t:attr name="seed_count" value="17" />
  <t:attr name="leechers" value="4" />
  <t:attr name="category" value="5030" />
</item></channel></rss>
"""


class TestIndexerAdapters(unittest.TestCase):
    def test_torznab_normalizes_namespace_aliases_and_fallbacks(self):
        result = parse_xml_releases(
            TORZNAB_XML,
            protocol="torznab",
            release_factory=TorznabRelease,
        )

        self.assertEqual(result.item_count, 1)
        self.assertEqual(result.warnings, [])
        release = result.releases[0]
        self.assertEqual(release.title, "Олдскул S01E01 1080p WEB-DL")
        self.assertEqual(release.seeders, 17)
        self.assertEqual(release.peers, 4)
        self.assertEqual(release.size_bytes, 1073741824)
        self.assertEqual(release.categories, [5030])
        self.assertEqual(release.download_url, "https://tracker.test/download/1")

    def test_newznab_normalizes_attribute_aliases(self):
        xml = """<rss xmlns:n="http://newznab.com/schemas/2010/feed"><channel><item>
          <title>Example S02E03 HDTV</title><guid>n-1</guid>
          <link>https://usenet.test/get/n-1</link>
          <n:attr name="filesize" value="2048" />
          <n:attr name="cat" value="5030,5040" />
        </item></channel></rss>"""

        result = parse_xml_releases(
            xml,
            protocol="newznab",
            release_factory=TorznabRelease,
        )

        release = result.releases[0]
        self.assertEqual(release.size_bytes, 2048)
        self.assertEqual(release.seeders, 100)
        self.assertEqual(release.categories, [5030, 5040])

    def test_adapter_reports_bad_fields_without_dropping_item(self):
        xml = """<rss xmlns:t="http://torznab.com/schemas/2015/feed"><channel><item>
          <title></title><t:attr name="releaseTitle" value="Example S01E01" />
          <t:attr name="seeders" value="many" />
        </item></channel></rss>"""

        result = parse_xml_releases(
            xml,
            protocol="torznab",
            release_factory=TorznabRelease,
        )

        self.assertEqual(result.releases[0].title, "Example S01E01")
        self.assertEqual(result.releases[0].seeders, 0)
        self.assertEqual(result.warnings[0].code, "invalid_numeric_attribute")

    def test_factory_handles_sqlalchemy_string_enum_values(self):
        indexer = SimpleNamespace(
            type=IndexerType.NEWZNAB,
            base_url="https://usenet.test",
            api_key=None,
            timeout_seconds=30,
        )
        self.assertIsInstance(get_indexer_client(indexer), NewznabIndexerClient)


class TestIndexerDiagnostics(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.indexer = SimpleNamespace(
            id=7,
            name="Fixture Indexer",
            type=IndexerType.TORZNAB,
            base_url="https://indexer.test/path",
            api_key="secret",
            categories=[5030],
            timeout_seconds=5,
        )

    def test_parse_capabilities(self):
        capabilities = parse_capabilities(CAPABILITIES_XML)
        self.assertTrue(capabilities["search_types"]["tv-search"]["available"])
        self.assertEqual(
            capabilities["search_types"]["tv-search"]["supported_params"],
            ["q", "season", "ep"],
        )
        self.assertEqual(capabilities["categories"][0]["subcategories"][0]["id"], 5030)

    async def test_fixture_pipeline_is_healthy_without_network(self):
        report = await diagnose_indexer(
            self.indexer,
            capabilities_xml=CAPABILITIES_XML,
            sample_xml=TORZNAB_XML,
        )

        self.assertEqual(report["status"], "healthy")
        self.assertTrue(report["connectivity"]["ok"])
        self.assertTrue(report["capabilities"]["ok"])
        self.assertEqual(report["category_mapping"]["supported"], [5030])
        self.assertEqual(report["sample"]["parsed_count"], 1)
        self.assertEqual(report["warnings"], [])
        self.assertNotIn("secret", str(report))

    async def test_structured_warnings_cover_mapping_and_sample_issues(self):
        self.indexer.categories = [5030, 9999]
        sample_xml = """<rss xmlns:t="http://torznab.com/schemas/2015/feed"><channel>
          <item><title>Unstructured release name</title><guid>dup</guid></item>
          <item><title>Another release</title><guid>dup</guid></item>
        </channel></rss>"""

        report = await diagnose_indexer(
            self.indexer,
            capabilities_xml=CAPABILITIES_XML,
            sample_xml=sample_xml,
        )

        codes = {warning["code"] for warning in report["warnings"]}
        self.assertEqual(report["status"], "error")
        self.assertIn("unsupported_configured_categories", codes)
        self.assertIn("unparsed_release_titles", codes)
        self.assertIn("missing_download_urls", codes)
        self.assertIn("missing_release_categories", codes)
        self.assertIn("duplicate_release_guids", codes)

    async def test_client_and_fetcher_are_injectable_and_errors_are_redacted(self):
        class FailingClient:
            async def search(self, query, is_probe=False):
                raise RuntimeError(
                    "GET https://indexer.test/api?t=search&apikey=do-not-leak failed"
                )

        async def capabilities_fetcher(indexer):
            return CAPABILITIES_XML

        report = await diagnose_indexer(
            self.indexer,
            client=FailingClient(),
            fetcher=capabilities_fetcher,
        )

        self.assertEqual(report["status"], "error")
        self.assertFalse(report["connectivity"]["ok"])
        self.assertIn("apikey=<redacted>", report["connectivity"]["error"])
        self.assertNotIn("do-not-leak", str(report))

    async def test_report_endpoint_redacts_url_userinfo(self):
        self.indexer.base_url = "https://user:password@indexer.test/path"

        report = await diagnose_indexer(
            self.indexer,
            capabilities_xml=CAPABILITIES_XML,
            sample_xml=TORZNAB_XML,
        )

        self.assertEqual(report["indexer"]["endpoint"], "https://indexer.test/path/api")
        self.assertNotIn("password", str(report))
