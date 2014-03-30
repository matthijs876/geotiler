#
# GeoTiler - library to create maps using tiles from a map provider
#
# NOTE: The code contains BSD licensed code from Modest Maps project.
#
# Copyright (C) 2013-2014 by Artur Wroblewski <wrobell@pld-linux.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import math
import logging

from shapely.geometry import Point
import PIL.Image as Image

from .provider.conf import DEFAULT_PROVIDER
from . import Core
from .tilenet import TileRequest, render_tiles

logger = logging.getLogger(__name__)

class Map(object):
    """
    Map created from tiles and to be drawn as an image.

    The initial map instance is created using geographical extent and zoom.
    This calculates center of the map and size of the image.

    The extent, zoom, center and image size can be changed at any time with
    appropriate properties.

    *NOTE:* Changing image size recalculates map extent.

    :var provider: Map tiles provider (default OpenStreetMap).
    :var _extent: Map geographical extent.
    :var _center: Map geographical center.
    :var _zoom: Map zoom.
    :var _size: Image size.
    :var _offset: Position of base tile relative to map center.
    """
    def __init__(self, extent, zoom, provider=DEFAULT_PROVIDER):
        """
        Create map.

        :param extent: Map geographical extent.
        :param zoom: Map zoom.
        :param provider: Map tiles provider.
        """
        super().__init__()
        self.provider = provider
        self.coordinate = None
        self.offset = None

        self._extent = extent
        self._center = None
        self._zoom = zoom
        self._size = None

        self._on_change_extent_zoom()
        #assert self._center is not None
        assert self.coordinate is not None
        assert self._size is not None
        assert self.offset is not None


    @property
    def extent(self):
        """
        Map geographical extent.
        """
        return self._extent


    @extent.setter
    def extent(self, extent):
        self._extent = extent
        self._on_change_extent()


    @property
    def zoom(self):
        """
        Map zoom value.

        Setting zoom value changes map offset.
        """
        return self._zoom


    @zoom.setter
    def zoom(self, zoom):
        self._zoom = zoom
        self._on_change_zoom()


    @property
    def size(self):
        """
        Size of the image containing map.

        It is a tuple (width, height).

        Setting size of the image changes map extent.
        """
        return self._size


    @size.setter
    def size(self, size):
        self._size = size
        self._on_change_size()


    def _on_change_zoom(self):
        """
        Update map center after map zoom change.
        """
        center_coord = self.provider.locationCoordinate(self._center).zoomTo(self._zoom)
        map_coord, map_offset = calculateMapCenter(self.provider, center_coord)
        self.coordinate = map_coord
        self.offset = map_offset


    def _on_change_extent(self):
        """
        Update map center after map extent change.
        """
        width, height = self._size
        p1 = Point(*self._extent[:2])
        p2 = Point(*self._extent[2:])
        map_coord, map_offset = calculateMapExtent(self.provider, width, height, p1, p2)
        self.coordinate = map_coord
        self.offset = map_offset


    def _on_change_size(self):
        """
        Update map extent after map image size change.
        """
        w, h = self._size
        p1 = self.pointLocation(Point(0, h))
        p2 = self.pointLocation(Point(w, 0))
        self._extent = p1.x, p1.y, p2.x, p2.y


    def _on_change_extent_zoom(self):
        """ Return map instance given a provider, two corner locations, and zoom value.
        """
        # a coordinate per corner
        x1, y1, x2, y2 = self._extent
        p1 = Point(x1, y1)
        p2 = Point(x2, y2)
        coord_a = self.provider.locationCoordinate(p1).zoomTo(self._zoom)
        coord_b = self.provider.locationCoordinate(p2).zoomTo(self._zoom)

        # precise width and height in pixels
        width = abs(coord_a.column - coord_b.column) * self.provider.tile_width
        height = abs(coord_a.row - coord_b.row) * self.provider.tile_height

        # projected center of the map
        center_coord = Core.Coordinate(
            (coord_a.row + coord_b.row) / 2,
            (coord_a.column + coord_b.column) / 2,
            self._zoom
        )

        map_coord, map_offset = calculateMapCenter(self.provider, center_coord)

        self.coordinate = map_coord
        self.offset = map_offset
        self._size = int(width), int(height)


    def __str__(self):
        return 'Map(%(provider)s, %(_size)s, %(coordinate)s, %(offset)s)' % self.__dict__


    def locationPoint(self, location):
        """ Return an x, y point on the map image for a given geographical location.
        """
        point = Point(self.offset.x, self.offset.y)
        coord = self.provider.locationCoordinate(location).zoomTo(self.coordinate.zoom)

        # distance from the known coordinate offset
        point = Point(
            point.x + self.provider.tile_width * (coord.column - self.coordinate.column),
            point.y + self.provider.tile_height * (coord.row - self.coordinate.row)
        )

        # because of the center/corner business
        w, h = self._size
        point = Point(point.x + w / 2, point.y + h / 2)

        return point

    def pointLocation(self, point):
        """ Return a geographical location on the map image for a given x, y point.
        """
        hizoomCoord = self.coordinate.zoomTo(Core.Coordinate.MAX_ZOOM)

        w, h = self._size

        # because of the center/corner business
        point = Point(point.x - w / 2, point.y - h / 2)

        # distance in tile widths from reference tile to point
        xTiles = (point.x - self.offset.x) / self.provider.tile_width
        yTiles = (point.y - self.offset.y) / self.provider.tile_height

        # distance in rows & columns at maximum zoom
        xDistance = xTiles * math.pow(2, (Core.Coordinate.MAX_ZOOM - self.coordinate.zoom))
        yDistance = yTiles * math.pow(2, (Core.Coordinate.MAX_ZOOM - self.coordinate.zoom))

        # new point coordinate reflecting that distance
        coord = Core.Coordinate(round(hizoomCoord.row + yDistance),
                                round(hizoomCoord.column + xDistance),
                                hizoomCoord.zoom)

        coord = coord.zoomTo(self.coordinate.zoom)

        location = self.provider.coordinateLocation(coord)

        return location



def render_map(map, downloader=None):
    """
    Render map image.

    If `downloader` is null, then default map tiles downloader is used.

    The function returns an image (instance of PIL.Image class).

    :param map: Map instance.
    :param downloader: Map tiles downloader.
    """
    coord = map.coordinate.copy()
    w, h = map._size
    corner = Point(int(map.offset.x + w / 2), int(map.offset.y + h / 2))

    while corner.x > 0:
        corner = Point(corner.x - map.provider.tile_width, corner.y)
        coord = coord.left()

    while corner.y > 0:
        corner = Point(corner.x, corner.y - map.provider.tile_height)
        coord = coord.up()

    tiles = []

    rowCoord = coord.copy()
    for y in range(int(corner.y), h, map.provider.tile_height):
        tileCoord = rowCoord.copy()
        for x in range(int(corner.x), w, map.provider.tile_width):
            tiles.append(TileRequest(map.provider, tileCoord, Point(x, y)))
            tileCoord = tileCoord.right()
        rowCoord = rowCoord.down()

    return render_tiles(tiles, map._size, downloader=downloader)


def calculateMapCenter(provider, centerCoord):
    """ Based on a provider and center coordinate, returns the coordinate
        of an initial tile and its point placement, relative to the map center.
    """
    # initial tile coordinate
    initTileCoord = centerCoord.container()

    # initial tile position, assuming centered tile well in grid
    initX = (initTileCoord.column - centerCoord.column) * provider.tile_width
    initY = (initTileCoord.row - centerCoord.row) * provider.tile_height
    initPoint = Point(round(initX), round(initY))

    return initTileCoord, initPoint

def calculateMapExtent(provider, width, height, *args):
    """ Based on a provider, width & height values, and a list of locations,
        returns the coordinate of an initial tile and its point placement,
        relative to the map center.
    """
    coordinates = list(map(provider.locationCoordinate, args))

    TL = Core.Coordinate(min([c.row for c in coordinates]),
                         min([c.column for c in coordinates]),
                         min([c.zoom for c in coordinates]))

    BR = Core.Coordinate(max([c.row for c in coordinates]),
                         max([c.column for c in coordinates]),
                         max([c.zoom for c in coordinates]))

    # multiplication factor between horizontal span and map width
    hFactor = (BR.column - TL.column) / (float(width) / provider.tile_width)

    # multiplication factor expressed as base-2 logarithm, for zoom difference
    hZoomDiff = math.log(hFactor) / math.log(2)

    # possible horizontal zoom to fit geographical extent in map width
    hPossibleZoom = TL.zoom - math.ceil(hZoomDiff)

    # multiplication factor between vertical span and map height
    vFactor = (BR.row - TL.row) / (float(height) / provider.tile_height)

    # multiplication factor expressed as base-2 logarithm, for zoom difference
    vZoomDiff = math.log(vFactor) / math.log(2)

    # possible vertical zoom to fit geographical extent in map height
    vPossibleZoom = TL.zoom - math.ceil(vZoomDiff)

    # initial zoom to fit extent vertically and horizontally
    initZoom = min(hPossibleZoom, vPossibleZoom)

    ## additionally, make sure it's not outside the boundaries set by provider limits
    #initZoom = min(initZoom, provider.outerLimits()[1].zoom)
    #initZoom = max(initZoom, provider.outerLimits()[0].zoom)

    # coordinate of extent center
    centerRow = (TL.row + BR.row) / 2
    centerColumn = (TL.column + BR.column) / 2
    centerZoom = (TL.zoom + BR.zoom) / 2
    centerCoord = Core.Coordinate(centerRow, centerColumn, centerZoom).zoomTo(initZoom)

    return calculateMapCenter(provider, centerCoord)


# vim: sw=4:et:ai
