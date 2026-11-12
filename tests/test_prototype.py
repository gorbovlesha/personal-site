"""Keep the visitor's navigation aligned with the agreed card scope."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


class PrototypeMap(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_nav = False
        self.navigation = []
        self.sections = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav' and attrs.get('aria-label') == 'Основная навигация':
            self.in_nav = True
        if self.in_nav and tag == 'a':
            self.navigation.append(attrs.get('href'))
        if tag == 'section' and attrs.get('id'):
            self.sections.append(attrs['id'])

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_nav = False


class PrototypeTests(unittest.TestCase):
    def test_every_required_section_is_reachable_in_reading_order(self):
        page = PrototypeMap()
        page.feed((Path(__file__).resolve().parents[1] / 'src' / 'index.html').read_text())
        required = ['about', 'skills', 'projects', 'experience', 'contact']
        self.assertEqual(page.sections, required)
        self.assertEqual(page.navigation, ['#' + name for name in required])


if __name__ == '__main__':
    unittest.main()
