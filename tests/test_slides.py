import unittest

from webviewer.slides import SlideCache


class _FakeSlide:
    dimensions = (4000, 3000)
    properties = {"openslide.vendor": "test"}


class _FakeDeepZoom:
    level_dimensions = ((1, 1), (4000, 3000))
    level_tiles = ((1, 1), (16, 12))
    level_count = 2


class SlideCacheTests(unittest.TestCase):
    def test_metadata_uses_configured_tile_values_not_private_generator_attributes(self):
        cache = SlideCache(max_items=1)
        cache._items["slide.svs"] = {
            "slide": _FakeSlide(),
            "deepzoom": _FakeDeepZoom(),
            "tile_size": 254,
            "overlap": 1,
            "lock": cache._lock,
        }

        metadata = cache.metadata("slide.svs")

        self.assertEqual(metadata["tileSize"], 254)
        self.assertEqual(metadata["overlap"], 1)
        self.assertEqual(metadata["levelCount"], 2)


if __name__ == "__main__":
    unittest.main()
