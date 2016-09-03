#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sift.model.document
--------------------

Core (low-level) document model for SIFT.
The core is sometimes accessed via Facets, which are like database views for a specific group of use cases

The document model is a metadata representation which permits the workspace to be constructed and managed.

Document is primarily a composition of layers.
Layers come in several flavors:

 - Image : a float32 field shown as tiles containing strides and/or alternate LODs, having a colormap
 - Outline : typically a geographic political map
 - Shape : a highlighted region selected by the user: point, line (great circle), polygon
 - Combination : calculated from two or more image layers, e.g. RGBA combination of images
                 combinations may be limited to areas specified by region layers.

Future Work:

 - Volume : a 3D dataset, potentially sparse
 - DenseVolume
 - SparseVolume : (x,y,z) point cloud

Layers are represented in 1 or more LayerSets, which are alternate configurations of the display.
Users may wish to display the same data in several different ways for illustration purposes.
Only one LayerSet is used on a given Map window at a time.

Layers have presentation settings that vary with LayerSet:

 - z_order: bottom to top in the map display
 - visible: whether or not it's being drawn on the map
 - a_order: animation order, when the animation button is hit
 - colormap: how the data is converted to pixels
 - mixing: mixing mode when drawing (normal, additive)

Document has zero or more Probes. Layers also come in multiple
flavors that may be be attached to plugins or helper applications.

 - Scatter: (layerA, layerB, region) -> xy plot
 - Slice: (volume, line) -> curtain plot
 - Profile: (volume, point) -> profile plot

Document has zero or more Colormaps, determining how they're presented

The document does not own data (content). It only owns metadata (info).
At most, document holds coarse overview data content for preview purposes.

All entities in the Document have a UUID that is their identity throughout their lifecycle, and is often used as shorthand
between subsystems. Document rarely deals directly with content.

:author: R.K.Garcia <rayg@ssec.wisc.edu>
:copyright: 2015 by University of Wisconsin Regents, see AUTHORS for more details
:license: GPLv3, see LICENSE for more details
"""
from sift.model.layer import mixing, DocLayer, DocBasicLayer, DocCompositeLayer, DocRGBLayer

__author__ = 'rayg'
__docformat__ = 'reStructuredText'

import sys
import logging
import unittest
import argparse
from collections import namedtuple, MutableSequence
from uuid import UUID
import numpy as np
from abc import ABCMeta, abstractmethod, abstractproperty
from weakref import ref

from sift.common import KIND, INFO, COMPOSITE_TYPE
from sift.model.guidebook import AHI_HSF_Guidebook, GUIDE

from PyQt4.QtCore import QObject, pyqtSignal


LOG = logging.getLogger(__name__)

DEFAULT_LAYER_SET_COUNT = 1  # this should match the ui configuration!

# presentation information for a layer; z_order comes from the layerset
prez = namedtuple('prez', [
    'uuid',     # UUID: dataset in the document/workspace
    'kind',     # what kind of layer it is
    'visible',  # bool: whether it's visible or not
    'a_order',  # int: None for non-animating, 0..n-1 what order to draw in during animation
    'colormap', # name or uuid: color map to use; name for default, uuid for user-specified
    'climits',     # tuple: valid min and valid max used for color mapping normalization
    'mixing'    # mixing mode constant
])


class DocLayerStack(MutableSequence):
    """
    list-like layer set which will slowly eat functionality from Document as warranted, and provide cleaner interfacing to GUI elements
    """
    _doc = None  # weakref to document we belong to
    _store = None
    _u2r = None  # uuid-to-row correspondence cache

    def __init__(self, doc, *args, **kwargs):
        if isinstance(doc, DocLayerStack):
            self._doc = ref(doc._doc())
            self._store = list(doc._store)
        elif isinstance(doc, Document):
            self._doc = ref(doc)
            self._store = list(*args)
        else:
            raise ValueError('cannot initialize DocLayerStack using %s' % type(doc))

    def __setitem__(self, index:int, value:prez):
        if index>=0 and index<len(self._store):
            self._store[index] = value
        elif index == len(self._store):
            self._store.append(value)
        else:
            raise IndexError('%d not a valid index' % index)
        self._u2r = None

    @property
    def uuid2row(self):
        if self._u2r is None:
            self._u2r = dict((p.uuid,i) for (i,p) in enumerate(self._store))
        return self._u2r

    def __getitem__(self, index:int):  # then return layer object
        if isinstance(index, int):
            return self._store[index]
        elif isinstance(index, UUID):  # then return 0..n-1 index in stack
            return self.uuid2row.get(index, None)
        elif isinstance(index, DocLayer):
            return self.uuid2row.get(index.uuid, None)
        elif isinstance(index, prez):
            return self.uuid2row.get(index.uuid, None)
        else:
            raise ValueError('unable to index LayerStack using %s' % repr(index))

    def __iter__(self):
        for each in self._store:
            yield each

    def __len__(self):
        return len(self._store)

    def __delitem__(self, index:int):
        del self._store[index]
        self._u2r = None

    def insert(self, index:int, value:prez):
        self._store.insert(index, value)
        self._u2r = None

    def clear_animation_order(self):
        for i,q in enumerate(self._store):
            self._store[i] = q._replace(a_order=None)

    def index(self, uuid):
        assert(isinstance(uuid, UUID))
        u2r = self.uuid2row
        return u2r.get(uuid, None)

    @property
    def animation_order(self):
        aouu = [(x.a_order, x.uuid) for x in self._store if (x.a_order is not None)]
        aouu.sort()
        ao = tuple(u for a,u in aouu)
        LOG.debug('animation order is {0!r:s}'.format(ao))
        return ao

    @animation_order.setter
    def animation_order(self, layer_or_uuid_seq):
        self.clear_animation_order()
        for nth,lu in enumerate(layer_or_uuid_seq):
            try:
                idx = self[lu]
            except ValueError:
                LOG.warning('unable to find layer in LayerStack')
                raise
            self._store[idx] = self._store[idx]._replace(a_order=nth)


#
#
# class DocAsLayerStack(metaclass=ABCMeta):
#     """
#     interface used by SceneGraphManager
#     """
#     @abstractmethod
#     def layers_in_z_order(self):
#         """
#         return current enabled list of (active layer, animation order)
#         animation order of 0 implies not part of current animation
#         :return:
#         """
#         pass
#
#
# class DocAsDataSpace(metaclass=ABCMeta):
#     """
#     interface used to coordinate left-right-up-down keys.
#     application behavior managing these keypresses uses this interface
#     Typically left-right is time, up-down is channel.
#     Consultation with the guidebook may be needed.
#     'l', 'r', 'u', 'd', 'i', 'o': left, right, up, down, in, out
#     """
#     @abstractmethod
#     def neighboring_layer(self, direction:str, amount:int=1):
#         """
#         return neighboring layer
#         :param direction: l, r, u, d string indicating direction
#         :param amount: number of steps to displace, typically +1
#         :return:
#         """
#         pass
#
#
# class DocAsLayerTree(metaclass=ABCMeta):
#     """
#     interface (facet) used to coordinate drag-and-drop layer tree
#     """
#     pass
#





class Document(QObject):  # base class is rightmost, mixins left of that
    """
    Document has one or more LayerSets choosable by the user (one at a time) as currentLayerSet
    LayerSets configure animation order, visibility, enhancements and linear combinations
    LayerSets can be cloned from the prior active LayerSet when unconfigured
    Document has Probes, which operate on the currentLayerSet
    Probes have spatial areas (point probes, shaped areas)
    Probe areas are translated into localized data masks against the workspace raw data content

    """
    current_set_index = 0
    _workspace = None
    _layer_sets = None  # list(DocLayerSet(prez, ...) or None)
    _layer_with_uuid = None  # dict(uuid:Doc____Layer)
    _guidebook = None  # FUTURE: this is currently an AHI_HSF_Guidebook, make it a general guidebook

    # signals
    didAddBasicLayer = pyqtSignal(tuple, UUID, prez)  # new order list with None for new layer; info-dictionary, overview-content-ndarray
    didAddCompositeLayer = pyqtSignal(tuple, UUID, prez)  # comp layer is derived from multiple basic layers and has its own UUID
    didRemoveLayers = pyqtSignal(tuple, list, int, int)  # new order, UUIDs that were removed from current layer set, first row removed, num rows removed
    willPurgeLayer = pyqtSignal(UUID)  # UUID of the layer being removed
    didReorderLayers = pyqtSignal(tuple)  # list of original indices in their new order, None for new layers
    didChangeLayerVisibility = pyqtSignal(dict)  # {UUID: new-visibility, ...} for changed layers
    didReorderAnimation = pyqtSignal(tuple)  # list of UUIDs representing new animation order
    didChangeLayerName = pyqtSignal(UUID, str)  # layer uuid, new name
    didSwitchLayerSet = pyqtSignal(int, tuple, tuple)  # new layerset number typically 0..3, list of prez tuples representing new display order, new animation order
    didChangeColormap = pyqtSignal(dict)  # dict of {uuid: colormap-name-or-UUID, ...} for all changed layers
    didChangeColorLimits = pyqtSignal(dict)  # dict of {uuid: colormap-name-or-UUID, ...} for all changed layers
    didChangeComposition = pyqtSignal(tuple, UUID, prez, dict)  # new-layer-order, changed-layer, change-info: composite channels were reassigned or polynomial altered
    didCalculateLayerEqualizerValues = pyqtSignal(dict)  # dict of {uuid: (value, normalized_value_within_clim)} for equalizer display
    # didChangeShapeLayer = pyqtSignal(dict)

    def __init__(self, workspace, layer_set_count=DEFAULT_LAYER_SET_COUNT, **kwargs):
        super(Document, self).__init__(**kwargs)
        self._guidebook = AHI_HSF_Guidebook()
        self._workspace = workspace
        self._layer_sets = [DocLayerStack(self)] + [None] * (layer_set_count - 1)
        self._layer_with_uuid = {}
        # TODO: connect signals from workspace to slots including update_dataset_info

    def _default_colormap(self, datasetinfo):
        """
        consult guidebook and user preferences for which enhancement should be used for a given datasetinfo
        :param datasetinfo: dictionary of metadata about dataset
        :return: enhancement info and siblings participating in the enhancement
        """
        return self._guidebook.default_colormap(datasetinfo)

    @property
    def current_layer_set(self):
        return self._layer_sets[self.current_set_index]

    # def _additional_guidebook_information(self, info):
    #     """
    #     when adding a file, return any additional information we want from the guidebook
    #     :param info: existing datasetinfo
    #     :return: dictionary of information not immediately available from the file itself
    #     """
    #     md =
    #     return {
    #         INFO.DISPLAY_TIME: self._guidebook.display_time(info)
    #     }

    def _insert_layer_with_info(self, info: DocLayer, cmap=None, insert_before=0):
        """
        insert a layer into the presentations but do not signal
        :return: new prez tuple, new reordered indices tuple
        """
        p = prez(uuid=info[INFO.UUID],
                 kind=info[INFO.KIND],
                 visible=True,
                 a_order=None,
                 colormap=cmap,
                 climits=info[INFO.CLIM],
                 mixing=mixing.NORMAL)

        q = p._replace(visible=False)  # make it available but not visible in other layer sets
        old_layer_count = len(self._layer_sets[self.current_set_index])
        for dex, lset in enumerate(self._layer_sets):
            if lset is not None:  # uninitialized layer sets will be None
                lset.insert(insert_before, p if dex == self.current_set_index else q)

        reordered_indices = tuple([None] + list(range(old_layer_count)))  # FIXME: this should obey insert_before, currently assumes always insert at top
        return p, reordered_indices

    def open_file(self, path, insert_before=0):
        """
        open an arbitrary file and make it the new top layer.
        emits docDidChangeLayer followed by docDidChangeLayerOrder
        :param path: file to open and add
        :return: overview (uuid:UUID, datasetinfo:dict, overviewdata:numpy.ndarray)
        """
        uuid, info, content = self._workspace.import_image(source_path=path)
        if uuid in self._layer_with_uuid:
            LOG.warning("layer with UUID {0:s} already in document?".format(uuid))
            return uuid, info, content
        # info.update(self._additional_guidebook_information(info))
        self._layer_with_uuid[uuid] = dataset = DocBasicLayer(self, info)
        # also get info for this layer from the guidebook
        gbinfo = self._guidebook.collect_info(dataset)
        dataset.update(gbinfo)  # FUTURE: should guidebook be integrated into DocBasicLayer?

        # add as visible to the front of the current set, and invisible to the rest of the available sets
        cmap = self._default_colormap(dataset)
        dataset[INFO.CLIM] = self._guidebook.climits(dataset)
        dataset[INFO.NAME] = self._guidebook.display_name(dataset) or dataset[INFO.NAME]
        presentation, reordered_indices = self._insert_layer_with_info(dataset, cmap=cmap, insert_before=insert_before)
        # signal updates from the document
        self.didAddBasicLayer.emit(reordered_indices, dataset.uuid, presentation)
        return uuid, dataset, content

    def open_files(self, paths, insert_before = 0):
        """
        sort paths into preferred load order (see guidebook.py)
        open files in order, yielding uuid, info, overview_content
        :param paths: paths to open
        :param insert_before: where to insert them in layer list
        :return:
        """
        paths = list(self._guidebook.sort_pathnames_into_load_order(paths))
        for path in paths:
            yield self.open_file(path, insert_before)

    def sort_paths(self, paths):
        """
        :param paths: list of paths
        :return: list of paths
        """
        paths = list(reversed(self._guidebook.sort_pathnames_into_load_order(paths)))  # go from load order to display order by reversing
        return paths

    def time_label_for_uuid(self, uuid):
        """used to update animation display when a new frame is shown
        """
        if not uuid:
            return "YYYY-MM-DD HH:MM"
        info = self._layer_with_uuid[uuid]
        return self._guidebook.display_time(info)

    def prez_for_uuids(self, uuids, lset=None):
        if lset is None:
            lset = self.current_layer_set
        for p in lset:
            if p.uuid in uuids:
                yield p

    def colormap_for_uuids(self, uuids, lset=None):
        for p in self.prez_for_uuids(uuids, lset=lset):
            yield p.colormap

    def valid_range_for_uuid(self, uuid):
        # Limit ourselves to what information
        layer = self._layer_with_uuid[uuid]
        return self._guidebook.climits({
            INFO.UUID: uuid,
            INFO.KIND: layer[INFO.KIND],
            INFO.PATHNAME: layer[INFO.PATHNAME],
        })

    def convert_units(self, uuid, data, inverse=False):
        """
        :param uuid: layer id
        :param data: values to convert
        :param inverse: when true, convert from display units to data units
        :return:
        """
        formatstr, unitstr, lam = self._guidebook.units_conversion(self._layer_with_uuid[uuid])
        return formatstr, unitstr, lam(data, inverse)

    def flipped_for_uuids(self, uuids, lset=None):
        for p in self.prez_for_uuids(uuids, lset=lset):
            default_clim = self._layer_with_uuid[p.uuid][INFO.CLIM]
            yield ((p.climits[1] - p.climits[0]) > 0) != ((default_clim[1] - default_clim[0]) > 0)

    def update_equalizer_values(self, probe_name, state, xy_pos, uuids=None):
        """user has clicked on a point probe; determine relative and absolute values for all document image layers
        """
        # if the point probe was turned off then we don't want to have the equalizer
        if not state:
            self.didCalculateLayerEqualizerValues.emit({})
            return

        if uuids is None:
            uuids = [(pinf.uuid, pinf) for pinf in self.current_layer_set]
        else:
            uuids = [(uuid, self._layer_with_uuid[uuid]) for uuid in uuids]
        zult = {}
        for uuid, pinf in uuids:
            lyr = self._layer_with_uuid[pinf.uuid]
            if lyr[INFO.KIND] == KIND.IMAGE:
                value = self._workspace.get_content_point(pinf.uuid, xy_pos)
                fmt, unit_str, unit_conv = self._guidebook.units_conversion(self._layer_with_uuid[pinf.uuid])
                # calculate normalized bar width relative to its current clim
                nc, xc = unit_conv(np.array(pinf.climits))
                if nc > xc:  # sometimes clim is swapped to reverse color scale
                    nc, xc = xc, nc
                value = unit_conv(value)
                if np.isnan(value):
                    zult[pinf.uuid] = None
                else:
                    bar_width = (np.clip(value, nc, xc) - nc) / (xc - nc)
                    zult[pinf.uuid] = (value, bar_width, fmt, unit_str)
            elif lyr[INFO.KIND] == KIND.RGB:
                # We can show a valid RGB
                # Get 3 values for each channel
                # XXX: Better place for this?
                def _sci_to_rgb(v, cmin, cmax):
                    if cmin == cmax:
                        return 0
                    elif cmin > cmax:
                        if v > cmin:
                            v = cmin
                        elif v < cmax:
                            v = cmax
                    else:
                        if v < cmin:
                            v = cmin
                        elif v > cmax:
                            v = cmax

                    return int(round(abs(v - cmin) / abs(cmax - cmin) * 255.))
                values = []
                for dep_lyr, clims in zip(lyr.l[:3], lyr[INFO.CLIM]):
                    if dep_lyr is None:
                        values.append(None)
                    elif clims is None:
                        values.append(None)
                    else:
                        value = self._workspace.get_content_point(dep_lyr[INFO.UUID], xy_pos)
                        values.append(_sci_to_rgb(value, clims[0], clims[1]))

                # fmt = "{:3d}"
                fmt = "{}"
                unit_str = ""
                nc = 0
                xc = 255
                bar_widths = [(np.clip(value, nc, xc) - nc) / (xc - nc) for value in values if value is not None]
                bar_width = np.mean(bar_widths) if len(bar_widths) > 0 else 0
                values = ",".join(["{:3d}".format(v if v is not None else 0) for v in values])
                zult[pinf.uuid] = (values, bar_width, fmt, unit_str)

        self.didCalculateLayerEqualizerValues.emit(zult)  # is picked up by layer list model to update display

    # TODO, find out if this is needed/used and whether or not it's correct
    def update_dataset_info(self, new_info):
        """
        slot which updates document on new information workspace has provided us about a dataset
        typically signaled by importer operating in the workspace
        :param new_info: information dictionary including projection, levels of detail, etc
        :return: None
        """
        uuid = new_info[INFO.UUID]
        if uuid not in self._layer_with_uuid:
            LOG.warning('new information on uuid {0!r:s} is not for a known dataset'.format(new_info))
        self._layer_with_uuid[new_info[INFO.UUID]].update(new_info)
        # TODO, also get information about this layer from the guidebook?

        # TODO: see if this affects any presentation information; view will handle redrawing on its own

    def _clone_layer_set(self, existing_layer_set):
        return DocLayerStack(existing_layer_set)

    @property
    def current_animation_order(self):
        """
        return tuple of UUIDs representing the animation order in the currently selected layer set
        :return: tuple of UUIDs
        """
        return self.current_layer_set.animation_order

    @property
    def current_layer_uuid_order(self):
        """
        list of UUIDs (top to bottom) currently being displayed, independent of visibility/validity
        :return:
        """
        return tuple(x.uuid for x in self.current_layer_set)

    @property
    def current_visible_layer_uuid(self):
        """
        :return: the topmost visible layer's UUID
        """
        for x in self.current_layer_set:
            if x.visible:
                return x.uuid
        return None

    # def current_visible_layer_uuids(self, max_layers=None):
    #     """
    #     :param max_layers:
    #     :yield: the visible layers in the current layer set
    #     """
    #     count = 0
    #     for x in self.current_layer_set:
    #         if x.visible:
    #             count += 1
    #             yield x.uuid
    #         if max_layers is not None and count >= max_layers:
    #             break

    # TODO: add a document style guide which says how different bands from different instruments are displayed

    @property
    def active_layer_order(self):
        """
        return list of valid (can-be-displayed) layers which are either visible or in the animation order
        typically this is used by the scenegraphmanager to synchronize the scenegraph elements
        :return: sequence of (layer_prez, layer) pairs, with order=0 for non-animating layers
        """
        for layer_prez in self.current_layer_set:
            if layer_prez.visible or layer_prez.a_order is not None:
                layer = self._layer_with_uuid[layer_prez.uuid]
                if not layer.is_valid:
                    # we don't have enough information to display this layer yet, it's still loading or being configured
                    continue
                yield layer_prez, layer

    def layers_where(self, is_valid=None, is_active=None, in_type_set=None):
        """
        query current layer set for layers matching criteria
        :param is_valid: None, or True/False whether layer is valid (could be displayed)
        :param is_active: None, or True/False whether layer is active (valid & (visible | animatable))
        :param in_type_set: None, or set of Python types that the layer falls into
        :return: sequence of layers in no particular order
        """
        for layer_prez in self.current_layer_set:
            layer = self._layer_with_uuid[layer_prez.uuid]
            valid = layer.is_valid
            if is_valid is not None:
                if valid != is_valid:
                    continue
            if is_active is not None:
                active = valid and (layer_prez.visible or layer_prez.a_order is not None)
                if active != is_active:
                    continue
            if in_type_set is not None:
                if type(layer) not in in_type_set:
                    continue
            yield layer


    def select_layer_set(self, layer_set_index:int):
        """Change the selected layer set, 0..N (typically 0..3), cloning the old set if needed
        emits docDidChangeLayerOrder with an empty list implying complete reassessment,
        if cloning of layer set didn't occur

        :param layer_set_index: which layer set to switch to

        """

        # the number of layer sets is no longer fixed, but you can't select more than 1 beyond the end of the list!
        assert(layer_set_index <= len(self._layer_sets) and layer_set_index >= 0)

        # if we are adding a layer set, do that now
        if layer_set_index == len(self._layer_sets) :
            self._layer_sets.append(None)

        # if the selected layer set doesn't exist yet, clone another set to make it
        did_clone = False
        if self._layer_sets[layer_set_index] is None:
            self._layer_sets[layer_set_index] = self._clone_layer_set(self._layer_sets[self.current_set_index])
            did_clone = True

        # switch to the new layer set and set off events to let others know about the change
        self.current_set_index = layer_set_index
        self.didSwitchLayerSet.emit(layer_set_index, self.current_layer_set, self.current_animation_order)

    # def change_layer_order(self, old_index, new_index):
    #     L = self.current_layer_set
    #     order = list(range(len(L)))
    #     p = L[old_index]
    #     d = order[old_index]
    #     del L[old_index]
    #     del order[old_index]
    #     L.insert(new_index, p)
    #     L.insert(new_index, d)
    #     self.didReorderLayers.emit(order)

    # def swap_layer_order(self, row1, row2):
    #     L = self.current_layer_set
    #     order = list(range(len(L)))
    #     L[row1], L[row2] = L[row2], L[row1]
    #     order[row1], order[row2] = order[row2], order[row1]
    #     self.didReorderLayers.emit(order)

    def row_for_uuid(self, *uuids):
        d = dict((q.uuid,i) for i,q in enumerate(self.current_layer_set))
        if len(uuids)==1:
            return d[uuids[0]]
        else:
            return [d[x] for x in uuids]

    def toggle_layer_visibility(self, rows_or_uuids, visible=None):
        """
        change the visibility of a layer or layers
        :param rows_or_uuids: layer index or index list, 0..n-1, alternately UUIDs of layers
        :param visible: True, False, or None (toggle)
        """
        L = self.current_layer_set
        zult = {}
        if isinstance(rows_or_uuids, int) or isinstance(rows_or_uuids, UUID):
            rows_or_uuids = [rows_or_uuids]
        for dex in rows_or_uuids:
            if isinstance(dex, UUID):
                dex = L.index(dex)  # returns row index
            old = L[dex]
            vis = (not old.visible) if visible is None else visible
            # print(vis)
            nu = old._replace(visible=vis)
            L[dex] = nu
            zult[nu.uuid] = nu.visible
        self.didChangeLayerVisibility.emit(zult)

    def animation_changed_visibility(self, changes):
        """
        this is triggered by animation being stopped,
        via signal scenegraphmanager.didChangeLayerVisibility
        in turn we generate our own didChangeLayerVisibility to ensure document views are up to date
        :param changes: dictionary of {uuid:bool} with new visibility state
        :return:
        """
        u2r = dict((q.uuid,i) for i,q in enumerate(self.current_layer_set))
        L = self.current_layer_set
        for uuid,visible in changes.items():
            dex = L[uuid]
            old = L[dex]
            L[dex] = old._replace(visible=visible)
        self.didChangeLayerVisibility.emit(changes)

    def next_last_step(self, uuid, delta=0, bandwise=False):
        """
        given a selected layer uuid,
        use the data guidebook to
        find the next or last time/bandstep (default: the layer itself) in the document
        make all layers in the sibling group invisible save that timestep
        :param uuid: layer we're focusing on as reference
        :param delta: -1 => last step, 0 for focus step, +1 for next step
        :param bandwise: True if we want to change by band instead of time
        :return: UUID of new focus layer
        """
        # get list of UUIDs in time order, plus index where the focus uuid is
        layer = self._layer_with_uuid[uuid]
        if isinstance(layer, DocRGBLayer):
            sibs = self._rgb_layer_siblings_uuids(layer)
            dex = sibs.index(uuid)
        else:
            if bandwise:  # next or last band
                consult_guide = self._guidebook.channel_siblings
            else:
                consult_guide = self._guidebook.time_siblings
            sibs, dex = consult_guide(uuid, self._layer_with_uuid.values())
        # LOG.debug('layer {0} family is +{1} of {2!r:s}'.format(uuid, dex, sibs))
        if not sibs:
            LOG.info('nothing to do in next_last_timestep')
            self.toggle_layer_visibility(uuid, True)
            return uuid
        dex += delta + len(sibs)
        dex %= len(sibs)
        new_focus = sibs[dex]
        del sibs[dex]
        if sibs:
            self.toggle_layer_visibility(sibs, False)
        self.toggle_layer_visibility(new_focus, True) # FUTURE: do these two commands in one step
        return new_focus

    def is_layer_visible(self, row):
        return self.current_layer_set[row].visible

    def layer_animation_order(self, layer_number):
        return self.current_layer_set[layer_number].a_order

    def change_layer_name(self, row, new_name):
        uuid = self.current_layer_set[row].uuid if not isinstance(row, UUID) else row
        info = self._layer_with_uuid[uuid]
        assert(uuid==info[INFO.UUID])
        info[INFO.NAME] = new_name
        self.didChangeLayerName.emit(uuid, new_name)

    def change_colormap_for_layers(self, name, uuids=None):
        L = self.current_layer_set
        if uuids is not None:
            uuids = self._guidebook.time_siblings_uuids(uuids, self._layer_with_uuid.values())
        else:  # all data layers
            uuids = [pinfo.uuid for pinfo in L]

        nfo = {}
        for uuid in uuids:
            for dex,pinfo in enumerate(L):
                if pinfo.uuid==uuid:
                    L[dex] = pinfo._replace(colormap=name)
                    nfo[uuid] = name
        self.didChangeColormap.emit(nfo)

    def current_layers_where(self, kinds=None, bands=None, uuids=None):
        """
        check current layer list for criteria and yield
        :param kinds: None, or set(KIND.xxx)
        :param bands: None, or set(band or band-trio)
        :param uuids: None, or set(UUID)
        :return: yield (index, prez, layer) from current layer set
        """
        L = self.current_layer_set
        for idx,p in enumerate(L):
            if (uuids is not None) and (p.uuid not in uuids):
                continue
            layer = self._layer_with_uuid[p.uuid]
            if (kinds is not None) and (layer.kind not in kinds):
                continue
            if (bands is not None) and (layer.band not in bands):
                continue
            yield (idx, p, layer)

    def change_clims_for_layers_where(self, clims, **query):
        """
        query using .current_layers_where() and change clims en masse
        :param clims: new color limits consistent with layer's presentation
        :param query: see current_layers_where()
        :return:
        """
        nfo = {}
        L = self.current_layer_set
        for idx, pz, layer in self.current_layers_where(**query):
            new_pz = pz._replace(climits=clims)
            nfo[layer.uuid] = new_pz
            L[idx] = new_pz
        self.didChangeColorLimits.emit(nfo)

    def flip_climits_for_layers(self, uuids=None):
        L = self.current_layer_set
        if uuids is not None:
            uuids = self._guidebook.time_siblings_uuids(uuids, self._layer_with_uuid.values())
        else:  # all data layers
            uuids = [pinfo.uuid for pinfo in L]

        nfo = {}
        for uuid in uuids:
            for dex,pinfo in enumerate(L):
                if pinfo.uuid==uuid:
                    nfo[uuid] = pinfo.climits[::-1]
                    L[dex] = pinfo._replace(climits=nfo[uuid])
        self.didChangeColorLimits.emit(nfo)

    def create_rgb_composite(self, r=None, g=None, b=None, clim=None, all_timesteps=True):
        """
        user has specified that a band trio should be shown as RGB
        disable display of the three layers
        add a composite layer at the z level of the topmost of the three
        """
        from uuid import uuid1 as uuidgen
        uuid = uuidgen()
        ds_info = {
            INFO.UUID: uuid,
            INFO.NAME: '-RGB-',
            INFO.KIND: KIND.RGB,
            GUIDE.BAND: [],
            GUIDE.DISPLAY_TIME: None,
            INFO.ORIGIN_X: None,
            INFO.ORIGIN_Y: None,
            INFO.CELL_WIDTH: None,
            INFO.CELL_HEIGHT: None,
            INFO.CLIM: (None, None, None)
        }

        self._layer_with_uuid[uuid] = ds_info = DocRGBLayer(self, ds_info)
        presentation, reordered_indices = self._insert_layer_with_info(ds_info)

        LOG.info('generating incomplete (invalid) composite for user to configure')
        self.didAddCompositeLayer.emit(reordered_indices, ds_info.uuid, presentation)

        color_assignments = {}
        def _(color, lyr):
            if lyr:
                color_assignments[color] = self._layer_with_uuid[lyr] if isinstance(lyr, UUID) else lyr
        _('r', r)
        _('g', g)
        _('b', b)
        LOG.debug("New Composite UUIDs: %s" % repr(color_assignments))
        if color_assignments:
            self.change_rgb_component_layer(ds_info, **color_assignments)

        if color_assignments and clim:
            self.change_rgbs_clims(clim, [ds_info])

        # disable visibility of the existing layers FUTURE: remove them entirely? probably not; also consider consistent behavior
        if color_assignments:
            self.toggle_layer_visibility((x for x in (r,g,b) if x is not None), False)

        # FUTURE: add rule to document on RGB affinity
        # FUTURE: register with workspace so that it can persist info to disk if needed
        return ds_info

    def change_rgb_component_layer(self, layer:DocRGBLayer, propagate_to_siblings=True, **rgba):
        """
        change the layer composition for an RGB layer, and signal
        by default, propagate the changes to sibling layers matching this layer's configuration
        :param layer:
        :param rgba:
        :return:
        """
        LOG.debug('revising RGB layer config for %s: %s' % (layer.uuid, repr(list(rgba.keys()))))
        if layer is None or not rgba:
            return
        # identify siblings before we make any changes!
        siblings = self._rgb_layer_siblings_uuids(layer) if propagate_to_siblings else None
        changed = False
        clims = list(layer[INFO.CLIM])
        for k,v in rgba.items():
            # assert(k in 'rgba')
            idx = 'rgba'.index(k)
            if getattr(layer,k,None) is v:
                continue
            changed = True
            setattr(layer, k, v)
            clims[idx] = None  # causes update_metadata to pull in upstream clim values
        if not changed:
            return
        # force an update of clims for components that changed
        layer[INFO.CLIM] = tuple(clims)
        updated = layer.update_metadata_from_dependencies()
        LOG.info('updated metadata for layer %s: %s' % (layer.uuid, repr(list(updated.keys()))))
        prez, = self.prez_for_uuids([layer.uuid])
        # this signals the scenegraph manager et al to see if the layer is now both visible and valid
        self.didChangeComposition.emit((), layer.uuid, prez, rgba)
        all_changed_layer_uuids = [layer.uuid]
        if propagate_to_siblings:
            all_changed_layer_uuids += list(self._propagate_matched_rgb_components(layer, siblings))
        # now propagate CLIMs and signal
        self.change_rgbs_clims(layer[INFO.CLIM], all_changed_layer_uuids)

    def change_and_propagate_rgb_clims(self, layer:DocRGBLayer, new_clims:tuple, include_siblings=True):
        # FIXME: migrate RGB clim into prez and not layer; only set INFO.CLIM if it hasn't already been set
        # self.change_clims_for_layers_where(new_clims, uuids={layer.uuid})
        # old_clim = layer[INFO.CLIM]
        # if isinstance(old_clim, tuple) and old_clim==new_clims:
        #     return
        layer[INFO.CLIM] = new_clims
        changed = {layer.uuid: new_clims}
        if include_siblings:
            for similar in self._rgb_layer_siblings_uuids(layer):
                if similar in changed:
                    continue
                simlyr = self._layer_with_uuid[similar]
                changed[similar] = new_clims
                simlyr[INFO.CLIM] = new_clims
        self.didChangeColorLimits.emit(changed)

    def set_rgb_range(self, layer:DocRGBLayer, rgba:str, min:float, max:float):
        new_clims = tuple(x if c != rgba else (min, max) for c, x in zip("rgba", layer[INFO.CLIM]))
        self.change_and_propagate_rgb_clims(layer, new_clims)

    def change_rgbs_clims(self, clims, layers):
        """
        change color limits for one or more RGB layers in one swipe
        :param clims: tuple of ((minred, maxred), (mingreen, maxgreen), (minblue,maxblue))
        :param layers: sequence of layer objects or UUIDs
        :return:
        """
        changed = {}
        # FIXME: deprecate this routine since display limits should be part of presentation tuple; data limits are part of layer
        for layer in layers:
            if isinstance(layer, UUID):
                layer = self._layer_with_uuid[layer]
            if not isinstance(layer, DocRGBLayer):
                continue
            if layer[INFO.CLIM] == clims:
                continue
            changed[layer.uuid] = clims
            layer[INFO.CLIM] = clims
        self.didChangeColorLimits.emit(changed)

    def _directory_of_layers(self, kind=KIND.IMAGE):
        for x in [q for q in self._layer_with_uuid.values() if q.kind==kind]:
            yield x.uuid, (x.platform, x.instrument, x.sched_time, x.band)

    def _rgb_layer_siblings_uuids(self, master_layer:DocRGBLayer):
        """
        given an RGB layer, find all the other layers with similar instrument-band selection
        :param master_layer:
        :return: list of uuids, including master layer itself
        """
        siblings = []
        master_subkey = master_layer.platform, master_layer.instrument, master_layer.band
        for (uuid,key) in self._directory_of_layers(kind=KIND.RGB):
            subkey = (key[0], key[1], key[3])
            if subkey==master_subkey:
                siblings.append((key[2], uuid))
        siblings.sort()
        LOG.debug('found RGB siblings %s' % repr(siblings))
        return [uu for time,uu in siblings]

    # def _propagate_clims_to_rgb_similars(self, master_layer:DocRGBLayer, clims:tuple, inclusive=True):
    #     to_update = [x for x in self._rgb_layer_siblings(master_layer) if x != master_layer.uuid]
    #     LOG.debug('updating %d RGB layer clims' % len(to_update))
    #     self.change_rgb_clims(clims, to_update)

    def _propagate_matched_rgb_components(self, master_layer, sibling_layers):
        """
        user has changed RGB selection on a layer which has siblings (e.g. animation loop)
        hunt down corresponding loaded channels for the sibling layer timesteps
        update those layers to match
        :param master_layer: layer which is steering this change and has changed band selection
        :param sibling_layers: layers which are supposed to follow master
        :return:
        """
        # FUTURE: consolidate/promote commonalities with loop_rgb_layers_following
        # build a directory of image layers to draw from
        building_blocks = dict((key,uuid) for (uuid,key) in self._directory_of_layers(kind=KIND.IMAGE))
        plat, inst, band = master_layer.platform, master_layer.instrument, master_layer.band
        did_change = []
        for sibling in sibling_layers:
            if isinstance(sibling, UUID):
                sibling = self._layer_with_uuid[sibling]
            if sibling.uuid == master_layer.uuid:
                continue
            change_these = {}
            for mb,sb,b in zip(band, sibling.band, 'rgb'):
                if mb==sb:
                    continue
                key_we_want = (plat, inst, sibling.sched_time, mb)
                new_uuid = building_blocks.get(key_we_want, None)
                change_these[b] = self._layer_with_uuid[new_uuid]
            if not change_these:
                continue
            did_change.append(sibling.uuid)
            self.change_rgb_component_layer(sibling, propagate_to_siblings=False, **change_these)
        return did_change

    def loop_rgb_layers_following(self, rgb_uuid:UUID,
                                  create_additional_layers=True,
                                  force_color_limits=True,
                                  make_contributing_layers_invisible=True):
        """
        LOOP BUTTON
        create RGB layers matching the configuration of the indicated layer (if create_all==True)
        Take all time steps with RGB layers for this channel set and make an animation loop
        Mark all layers which are not contributing to the loop as invisible.
        :param rgb_uuid:
        :param create_additional_layers:
        :param make_contributing_layers_invisible: whether or not to make layers not part of hte loop invisible
        :return:
        """
        master = self._layer_with_uuid[rgb_uuid]
        if not isinstance(master, DocRGBLayer):
            LOG.warning('loop_rgb_layers_following can only operate on RGB layers')
            return
        if None is master.sched_time:
            LOG.warning("cannot identify schedule time of master")
            return

        # build a directory of image layers to draw from
        building_blocks = dict((key,uuid) for (uuid,key) in self._directory_of_layers(kind=KIND.IMAGE))

        # find the list of loaded timesteps
        loaded_timesteps = set(x.sched_time for x in self._layer_with_uuid.values())
        loaded_timesteps = list(sorted(loaded_timesteps, reverse=True))  # build in last-to-first order to get proper layer list order
        LOG.debug('time steps available: %s' % repr(loaded_timesteps))

        # animation sequence we're going to use
        sequence = [(master.sched_time, master.uuid)]

        # build a directory of RGB layers we already have
        already_have = dict((key,uuid) for (uuid,key) in self._directory_of_layers(kind=KIND.RGB))
        to_build, to_make_invisible = [], []
        # figure out what layers we can build matching pattern, using building blocks
        rband, gband, bband = master.band[:3]
        plat, inst, sched_time = master.platform, master.instrument, master.sched_time
        for step in loaded_timesteps:
            if step==sched_time:
                continue
            preexisting_layer_uuid = already_have.get((plat, inst, step, master.band), None)
            if preexisting_layer_uuid:
                sequence.append((step, preexisting_layer_uuid))
                continue
            LOG.debug('assessing %s' % step)
            # look for the bands
            r = building_blocks.get((plat, inst, step, rband), None)
            g = building_blocks.get((plat, inst, step, gband), None)
            b = building_blocks.get((plat, inst, step, bband), None)
            if r and g and b:
                to_build.append((step,r,g,b))
                to_make_invisible.extend([r,g,b])
                LOG.info('will build RGB from r=%s g=%s b=%s' % (r,g,b))
            else:
                LOG.info("no complete RGB could be made for %s" % step)

        # build new RGB layers
        if create_additional_layers:
            LOG.info('creating %d additional RGB layers from loaded image layers' % len(to_build))
            for (when,r,g,b) in to_build:
                # rl,gl,bl = self._layer_with_uuid[r], self._layer_with_uuid[g], self._layer_with_uuid[b]
                new_layer = self.create_rgb_composite(r, g, b)
                sequence.append((when, new_layer.uuid))

        if force_color_limits:
            self.change_rgbs_clims(master[INFO.CLIM], (uu for _, uu in sequence))

        if make_contributing_layers_invisible:
            buhbye = set(to_make_invisible)
            LOG.debug('making %d layers invisible after using them to make RGBs' % len(buhbye))
            self.toggle_layer_visibility(buhbye, False)

        # set animation order
        sequence.sort()
        new_anim_order = tuple(uu for (t,uu) in sequence)
        self.current_layer_set.animation_order = new_anim_order
        self.didReorderAnimation.emit(new_anim_order)

    def __len__(self):
        # FIXME: this should be consistent with __getitem__, not self.current_layer_set
        return len(self.current_layer_set)

    def uuid_for_current_layer(self, row):
        uuid = self.current_layer_set[row].uuid
        return uuid

    def remove_layers_from_all_sets(self, uuids):
        for uuid in list(uuids):
            # FUTURE: make this removal of presentation tuples from inactive layer sets less sucky
            LOG.debug('removing {}'.format(uuid))
            for dex,layer_set in enumerate(self._layer_sets):
                if dex==self.current_set_index or layer_set is None:
                    continue
                for pdex, presentation in enumerate(layer_set):
                    if presentation.uuid==uuid:
                        del layer_set[pdex]
                        break
            # now remove from the active layer set
            self.remove_layer_prez(uuid)  # this will send signal and start purge

    def animate_siblings_of_layer(self, row_or_uuid):
        uuid = self.current_layer_set[row_or_uuid].uuid if not isinstance(row_or_uuid, UUID) else row_or_uuid
        layer = self._layer_with_uuid[uuid]
        if isinstance(layer, DocRGBLayer):
            return self.loop_rgb_layers_following(layer.uuid)
        new_anim_uuids, _ = self._guidebook.time_siblings(uuid, self._layer_with_uuid.values())
        if new_anim_uuids is None or len(new_anim_uuids)<2:
            LOG.info('no time siblings to chosen band, will try channel siblings to chosen time')
            new_anim_uuids, _ = self._guidebook.channel_siblings(uuid, self._layer_with_uuid.values())
        if new_anim_uuids is None or len(new_anim_uuids)<2:
            LOG.warning('No animation found')
            return []
        LOG.debug('new animation order will be {0!r:s}'.format(new_anim_uuids))
        L = self.current_layer_set
        L.animation_order = new_anim_uuids
        # L.clear_animation_order()
        # for dex,u in enumerate(new_anim_uuids):
        #     LOG.debug(u)
        #     row = L.uuid2row.get(u, None)
        #     if row is None:
        #         LOG.error('unable to find row for uuid {} in current layer set'.format(u))
        #         continue
        #     old = L[row]
        #     new = old._replace(a_order=dex)
        #     L[row] = new
        self.didReorderAnimation.emit(tuple(new_anim_uuids))
        return new_anim_uuids

    def get_info(self, row=None, uuid=None):
        if row is not None:
            uuid_temp = self.current_layer_set[row].uuid
            nfo = self._layer_with_uuid[uuid_temp]
            return nfo
        elif uuid is not None:
            nfo = self._layer_with_uuid[uuid]
            return nfo
        return None

    def __getitem__(self, layer_uuid):
        """
        return layer with the given UUID
        """
        if isinstance(layer_uuid, UUID):
            return self._layer_with_uuid[layer_uuid]
        else:
            raise ValueError('document[UUID] required, %r was used' % type(layer_uuid))
            # LOG.error('DEPRECATED usage document[index:int] -> DocLayerStack[index]; arg type is %r' % type(row_or_uuid))
            # return self.current_layer_set[row_or_uuid]

    def reorder_by_indices(self, new_order, uuids=None, layer_set_index=None):
        """given a new layer order, replace the current layer set
        emits signal to other subsystems
        """
        if layer_set_index is None:
            layer_set_index = self.current_set_index
        assert(len(new_order)==len(self._layer_sets[layer_set_index]))
        new_layer_set = [self._layer_sets[layer_set_index][n] for n in new_order]
        self._layer_sets[layer_set_index] = new_layer_set
        self.didReorderLayers.emit(tuple(new_order))

    def insert_layer_prez(self, row:int, layer_prez_seq):
        cls = self.current_layer_set
        clo = list(range(len(cls)))
        lps = list(layer_prez_seq)
        lps.reverse()
        if not lps:
            LOG.warning('attempt to drop empty content')
            return
        for p in lps:
            if not isinstance(p, prez):
                LOG.error('attempt to drop a new layer with the wrong type: {0!r:s}'.format(p))
                continue
            cls.insert(row, p)
            clo.insert(row, None)

    def is_using(self, uuid:UUID, layer_set:int=None):
        "return true if this dataset is still in use in one of the layer sets"
        # FIXME: this needs to check not just which layers are being displayed, but which layers which may be in use but as part of a composite instead of a direct scenegraph entry
        LOG.error('composite layers currently not checked for dependencies')
        if layer_set is not None:
            lss = [self._layer_sets[layer_set]]
        else:
            lss = [q for q in self._layer_sets if q is not None]
        for ls in lss:
            for p in ls:
                if p.uuid==uuid:
                    return True
        return False

    def remove_layer_prez(self, row_or_uuid, count:int=1):
        """
        remove the presentation of a given layer/s in the current set
        :param row: which current layer set row to remove
        :param count: how many rows to remove
        :return:
        """
        if isinstance(row_or_uuid, UUID) and count==1:
            row = self.row_for_uuid(row_or_uuid)
            uuids = [row_or_uuid]
        else:
            row = row_or_uuid
            uuids = [x.uuid for x in self.current_layer_set[row:row+count]]
        self.toggle_layer_visibility(list(range(row, row+count)), False)
        clo = list(range(len(self.current_layer_set)))
        del clo[row:row+count]
        del self.current_layer_set[row:row+count]
        self.didRemoveLayers.emit(tuple(clo), uuids, row, count)
        for uuid in uuids:
            if not self.is_using(uuid):
                LOG.info('purging layer {}, no longer in use'.format(uuid))
                self.willPurgeLayer.emit(uuid)
                # remove from our bookkeeping
                del self._layer_with_uuid[uuid]
                # remove from workspace
                self._workspace.remove(uuid)


#
# class DocumentTreeBranch(QObject):
#     pass
#
# class DocumentTreeLeaf(QObject):
#     pass
#
#
# class DocumentAsLayerTree(QObject):
#     """
#      DocumentAsLayerTree is a facet or wrapper (if it were a database, it would be a view; but view is already taken)
#      It allows the layer controls - specifically a LayerStackTreeViewModel - to easily access and modify
#      the document on behalf of the user.
#      It includes both queries for display and changes which then turn into document updates
#      The base model is just a list of basic layers.
#      Composite and Algebraic layers, however, are more like folders.
#      Other additional layer types may also have different responses to being dragged or having items dropped on them
#     """
#
#     def __init__(self, doc, *args, **kwargs):
#         self._doc = doc
#         super(DocumentAsLayerTree, self).__init__()
#
#     def
#


def main():
    parser = argparse.ArgumentParser(
        description="PURPOSE",
        epilog="",
        fromfile_prefix_chars='@')
    parser.add_argument('-v', '--verbose', dest='verbosity', action="count", default=0,
                        help='each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG')
    # http://docs.python.org/2.7/library/argparse.html#nargs
    # parser.add_argument('--stuff', nargs='5', dest='my_stuff',
    #                    help="one or more random things")
    parser.add_argument('pos_args', nargs='*',
                        help="positional arguments don't have the '-' prefix")
    args = parser.parse_args()

    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    logging.basicConfig(level=levels[min(3, args.verbosity)])

    if not args.pos_args:
        unittest.main()
        return 0

    for pn in args.pos_args:
        pass

    return 0


if __name__ == '__main__':
    sys.exit(main())

