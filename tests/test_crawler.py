"""The crawler is generic and robust: it extracts visible text (skipping noise),
finds links, and fails soft on bad input."""
import crawler

_SAMPLE = b"""<html><head><style>.x{color:red}</style></head>
<body>
  <nav>menu home about</nav>
  <h1>Split Level Homes</h1>
  <p>Sloping block designs and floor plans.</p>
  <script>var secret = 1;</script>
  <a href="/page2">More designs</a>
  <a href="https://other.example/x">External</a>
  <footer>copyright 2026</footer>
</body></html>"""


def test_parse_extracts_text_and_links_skipping_noise():
    text, links = crawler.parse_page(_SAMPLE)
    assert "Split Level Homes" in text
    assert "Sloping block designs" in text
    assert "color:red" not in text          # <style> skipped
    assert "secret" not in text             # <script> skipped
    assert "menu home about" not in text    # <nav> skipped
    assert "copyright" not in text          # <footer> skipped
    assert "/page2" in links


def test_parse_never_raises_on_garbage():
    text, links = crawler.parse_page(b"\xff\xfe not really html <<<")
    assert isinstance(text, str) and isinstance(links, list)


def test_crawl_fails_soft_with_no_host():
    assert crawler.crawl("") == []          # no host -> empty, no network attempted


def test_slug_text_turns_a_product_url_into_words():
    t = crawler._slug_text("https://shop.example/products/sony-wh-1000xm5-noise-cancelling-headphones")
    assert "noise" in t and "cancelling" in t and "headphones" in t
    assert crawler._slug_text("https://x.example/p/12345") == ""   # numeric-only dropped
