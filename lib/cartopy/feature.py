# (C) British Crown Copyright 2011 - 2012, Met Office
#
# This file is part of cartopy.
#
# cartopy is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cartopy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with cartopy.  If not, see <http://www.gnu.org/licenses/>.
"""
This module defines :class:`Feature` instances, for use with
ax.add_feature().

"""
from abc import ABCMeta, abstractmethod
import os.path

import numpy as np
import shapely.geometry

import cartopy.io.shapereader as shapereader
import cartopy.crs

_COLOURS = {'land': np.array((240, 240, 220)) / 256.,
            'water': np.array((152, 183, 226)) / 256.}


_NATURAL_EARTH_GEOM_CACHE = {}
"""
Caches a mapping between (name, category, scale) and a tuple of the
resulting geometries.

Provides a significant performance benefit (when combined with object id
caching in GeoAxes.add_geometries) when producing multiple maps of the
same projection.

"""


class Feature(object):
    """
    The abstract base class for features.

    """

    __metaclass__ = ABCMeta

    def __init__(self, crs, **kwargs):
        self._crs = crs
        self._kwargs = dict(kwargs)

    @property
    def crs(self):
        """The cartopy CRS for the geometries in this feature."""
        return self._crs

    @property
    def kwargs(self):
        """
        A dictionary of keyword arguments to be used when creating
        the matplotlib artists for this feature.

        """
        return dict(self._kwargs)

    @abstractmethod
    def geometries(self):
        """
        Must be overriden to return an iterator of shapely geometries
        for this feature.

        """
        pass

    def intersecting_geometries(self, extent):
        """
        Returns an iterator of shapely geometries that intersect with
        the given extent. The extent is assumed to be in the CRS of
        the feature. If extent is None, the method returns all
        geometries for this dataset.

        """
        if extent is not None:
            extent_geom = shapely.geometry.box(extent[0], extent[2],
                                               extent[1], extent[3])
            return (geom for geom in self.geometries() if
                    extent_geom.intersects(geom))
        else:
            return self.geometries()


class ShapelyFeature(Feature):
    """
    A class capable of drawing a collection of
    shapely geometries.

    """
    def __init__(self, geometries, crs, **kwargs):
        """
        Args:

        * geometries:
            A collection of shapely geometries.
        * crs:
            The cartopy CRS in which the provided geometries are defined.

        Kwargs:
            Keyword arguments to be used when drawing this feature.

        """
        super(ShapelyFeature, self).__init__(crs, **kwargs)
        self._geoms = tuple(geometries)

    def geometries(self):
        return iter(self._geoms)


class NaturalEarthFeature(Feature):
    """
    A simple interface to Natural Earth shapefiles.

    See http://www.naturalearthdata.com/

    """
    def __init__(self, category, name, scale, **kwargs):
        """
        Args:

        * category:
            The category of the dataset, i.e. either 'cultural' or 'physical'.
        * name:
            The name of the dataset, e.g. 'admin_0_boundary_lines_land'.
        * scale:
            The dataset scale, i.e. one of '10m', '50m', or '110m'.
            Corresponding to 1:10,000,000, 1:50,000,000, and 1:110,000,000
            respectively.

        Kwargs:
            Keyword arguments to be used when drawing this feature.

        """
        super(NaturalEarthFeature, self).__init__(cartopy.crs.PlateCarree(),
                                                  **kwargs)
        self.category = category
        self.name = name
        self.scale = scale

    def geometries(self):
        """
        Returns the shapely geometries defined by this Natural
        Earth dataset.

        """
        key = (self.name, self.category, self.scale)
        if key not in _NATURAL_EARTH_GEOM_CACHE:
            path = shapereader.natural_earth(resolution=self.scale,
                                             category=self.category,
                                             name=self.name)
            geometries = tuple(shapereader.Reader(path).geometries())
            _NATURAL_EARTH_GEOM_CACHE[key] = geometries
        else:
            geometries = _NATURAL_EARTH_GEOM_CACHE[key]

        return iter(geometries)


class GSHHSFeature(Feature):
    """
    An interface to the GSHHS dataset.

    See http://www.ngdc.noaa.gov/mgg/shorelines/gshhs.html

    """

    _geometries_cache = {}
    """
    A mapping from scale and level to GSHHS shapely geometry::

        {(scale, level): geom}

    This provides a perfomance boost when plotting in interactive mode or
    instantiating multiple GSHHS artists, by reducing repeated file IO.

    """
    def __init__(self, scale='auto', levels=None, **kwargs):
        """
        Args:

        * scale:
            The dataset scale. One of 'auto', 'coarse', 'low', 'intermediate',
            'high, or 'full' (default is 'auto').
        * levels:
            A list of integers 1-4 corresponding to the desired GSHHS feature
            levels to draw (default is [1] which corresponds to coastlines).

        Kwargs:
            Keyword arguments to be used when drawing the feature. Defaults
            are edgecolor='black' and facecolor='none'.

        """
        super(GSHHSFeature, self).__init__(cartopy.crs.PlateCarree(), **kwargs)

        if scale not in ('auto', 'a', 'coarse', 'c', 'low', 'l',
                         'intermediate', 'i', 'high', 'h', 'full', 'f'):
            raise ValueError("Unknown GSHHS scale '{}'.".format(scale))
        self._scale = scale

        if levels is None:
            levels = [1]
        self._levels = set(levels)
        unknown_levels = self._levels.difference([1, 2, 3, 4])
        if unknown_levels:
            raise ValueError("Unknown GSHHS levels "
                             "'{}'.".format(unknown_levels))

        # Default kwargs
        self._kwargs.setdefault('edgecolor', 'black')
        self._kwargs.setdefault('facecolor', 'none')

    def _scale_from_extent(self, extent):
        """
        Returns the appropriate scale (e.g. 'i') for the given extent
        expressed in PlateCarree CRS.

        """
        # Default to coarse scale
        scale = 'c'

        if extent is not None:
            # Upper limit on extent in degrees.
            scale_limits = (('c', 20.0),
                            ('l', 10.0),
                            ('i', 2.0),
                            ('h', 0.5),
                            ('f', 0.1))

            width = abs(extent[1] - extent[0])
            height = abs(extent[3] - extent[2])
            min_extent = min(width, height)
            if min_extent != 0:
                for scale, limit in scale_limits:
                    if min_extent > limit:
                        break

        return scale

    def geometries(self):
        """Returns an iterator of shapely geometries for the GSHHS dataset."""
        return self.intersecting_geometries(extent=None)

    def intersecting_geometries(self, extent):
        """
        Returns an iterator of shapely geometries for the GSHHS dataset
        that intersect with the given extent.

        """
        if self._scale == 'auto':
            scale = self._scale_from_extent(extent)
        else:
            scale = self._scale[0]

        if extent is not None:
            extent_geom = shapely.geometry.box(extent[0], extent[2],
                                               extent[1], extent[3])
        for level in self._levels:
            geoms = GSHHSFeature._geometries_cache.get((scale, level))
            if geoms is None:
                # Load GSHHS geometries from appropriate shape file.
                # TODO selective load based on bbox of each geom in file.
                path = shapereader.gshhs(scale, level)
                geoms = tuple(shapereader.Reader(path).geometries())
                GSHHSFeature._geometries_cache[(scale, level)] = geoms
            for geom in geoms:
                if extent is None or extent_geom.intersects(geom):
                    yield geom


BORDERS = NaturalEarthFeature('cultural', 'admin_0_boundary_lines_land',
                              '110m', edgecolor='black', facecolor='none')
"""Small scale (1:110m) country boundaries."""


COASTLINE = NaturalEarthFeature('physical', 'coastline', '110m',
                                edgecolor='black', facecolor='none')
"""Small scale (1:110m) coastline, including major islands."""


LAKES = NaturalEarthFeature('physical', 'lakes', '110m',
                            edgecolor='face',
                            facecolor=_COLOURS['water'])
"""Small scale (1:110m) natural and artificial lakes."""


LAND = NaturalEarthFeature('physical', 'land', '110m',
                           edgecolor='face',
                           facecolor=_COLOURS['land'])
"""Small scale (1:110m) land polygons, including major islands."""


OCEAN = NaturalEarthFeature('physical', 'ocean', '110m',
                            edgecolor='face',
                            facecolor=_COLOURS['water'])
"""Small scale (1:110m) ocean polygons."""


RIVERS = NaturalEarthFeature('physical', 'rivers_lake_centerlines', '110m',
                             edgecolor=_COLOURS['water'],
                             facecolor='none')
"""Small scale (1:110m) single-line drainages, including lake centerlines."""
