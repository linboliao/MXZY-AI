import io
import threading
from collections import OrderedDict


class SlideUnavailable(RuntimeError):
    pass


class SlideCache:
    TILE_SIZE = 254
    OVERLAP = 1

    def __init__(self, max_items=4):
        self.max_items = max_items
        self._items = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _open(path):
        try:
            import openslide
            from openslide.deepzoom import DeepZoomGenerator
        except ImportError as error:
            raise SlideUnavailable(
                "The OpenSlide Python dependency is not installed; WSI viewing is unavailable"
            ) from error
        try:
            slide = openslide.OpenSlide(str(path))
            deepzoom = DeepZoomGenerator(
                slide,
                tile_size=SlideCache.TILE_SIZE,
                overlap=SlideCache.OVERLAP,
                limit_bounds=False,
            )
            return {
                "slide": slide,
                "deepzoom": deepzoom,
                "tile_size": SlideCache.TILE_SIZE,
                "overlap": SlideCache.OVERLAP,
                "lock": threading.RLock(),
            }
        except Exception as error:
            raise SlideUnavailable(f"Unable to open the pathology slide: {error}") from error

    def get(self, path):
        key = str(path)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            item = self._open(path)
            self._items[key] = item
            while len(self._items) > self.max_items:
                _, stale = self._items.popitem(last=False)
                stale["slide"].close()
            return item

    def metadata(self, path):
        item = self.get(path)
        with item["lock"]:
            deepzoom = item["deepzoom"]
            slide = item["slide"]
            levels = []
            for level, (width, height) in enumerate(deepzoom.level_dimensions):
                tiles_x, tiles_y = deepzoom.level_tiles[level]
                levels.append(
                    {
                        "level": level,
                        "width": width,
                        "height": height,
                        "tilesX": tiles_x,
                        "tilesY": tiles_y,
                    }
                )
            return {
                "width": slide.dimensions[0],
                "height": slide.dimensions[1],
                "tileSize": item["tile_size"],
                "overlap": item["overlap"],
                "levelCount": deepzoom.level_count,
                "maxLevel": deepzoom.level_count - 1,
                "levels": levels,
                "properties": {
                    "objectivePower": slide.properties.get("openslide.objective-power"),
                    "mppX": slide.properties.get("openslide.mpp-x"),
                    "mppY": slide.properties.get("openslide.mpp-y"),
                    "vendor": slide.properties.get("openslide.vendor"),
                },
            }

    def tile(self, path, level, col, row, quality=88):
        item = self.get(path)
        with item["lock"]:
            deepzoom = item["deepzoom"]
            if level < 0 or level >= deepzoom.level_count:
                raise ValueError("Invalid zoom level")
            tiles_x, tiles_y = deepzoom.level_tiles[level]
            if col < 0 or row < 0 or col >= tiles_x or row >= tiles_y:
                raise ValueError("Invalid slide coordinates")
            image = deepzoom.get_tile(level, (col, row)).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True)
            return buffer.getvalue()
