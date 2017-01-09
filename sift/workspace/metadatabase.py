#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
metadatabase.py
===============

PURPOSE
Manage SQLAlchemy database of information used by DataMatrix
Used by DataMatrix, which is in turn used by Workspace


REFERENCES


REQUIRES
SQLAlchemy with SQLite

:author: R.K.Garcia <rayg@ssec.wisc.edu>
:copyright: 2016 by University of Wisconsin Regents, see AUTHORS for more details
:license: GPLv3, see LICENSE for more details
"""
__author__ = 'rayg'
__docformat__ = 'reStructuredText'

import os, sys
import logging, unittest, argparse

from sqlalchemy import Column, Integer, String, UnicodeText, Unicode, ForeignKey, DateTime, Interval, PickleType
from sqlalchemy.orm import Session, relationship
from sqlalchemy.ext.declarative import declarative_base


LOG = logging.getLogger(__name__)


# =================
# Database Entities

Base = declarative_base()


class File(Base):
    __tablename__ = 'files'
    id = Column(Integer, primary_key=True)

    format = Column(PickleType)  # class or callable which can pull this data into workspace from storage

    file_name = Column(Unicode)  # basename
    dir_path = Column(Unicode)  # dirname
    mtime = Column(DateTime)  # last observed mtime of the file, for change checking
    atime = Column(DateTime)  # last time this file was accessed by application

    products = relationship("Product", backref="file")


class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey('files.id'))

    kind = Column(PickleType)  # class or callable which can perform transformations on this data in workspace

    # cached metadata, consult file importer for definitive
    spacecraft = Column(String)  # eg "GOES-16", "Himawari-8"
    identifier = Column(String)  # eg "B01", "B02"
    start = Column(DateTime)
    duration = Column(Interval)
    resolution = Column(Integer, default=0)  # meters max resolution, e.g. 500, 1000, 2000, 4000
    proj4 = Column(String, default='')  # projection of the data in its native format, if applicable
    units = Column(Unicode, default=u'1')  # udunits compliant units, e.g. 'K'
    label = Column(Unicode, default=u'')  # "AHI Refl B11"
    description = Column(UnicodeText, default=u'')

    info = relationship("KeyValue", backref="product")


class KeyValue(Base):
    """
    key-value unicode string pairs associated with a product
    """
    __tablename__ = 'kvps'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'))
    key = Column(String)
    value = Column(UnicodeText, default=u'')


# ============================
# support and testing routines

class tests(unittest.TestCase):
    data_file = os.environ.get('TEST_DATA', os.path.expanduser("~/Data/test_files/thing.dat"))

    def setUp(self):
        pass

    def test_something(self):
        pass


def _debug(type, value, tb):
    "enable with sys.excepthook = debug"
    if not sys.stdin.isatty():
        sys.__excepthook__(type, value, tb)
    else:
        import traceback, pdb
        traceback.print_exception(type, value, tb)
        # …then start the debugger in post-mortem mode.
        pdb.post_mortem(tb)  # more “modern”



def main():
    parser = argparse.ArgumentParser(
        description="PURPOSE",
        epilog="",
        fromfile_prefix_chars='@')
    parser.add_argument('-v', '--verbose', dest='verbosity', action="count", default=0,
                        help='each occurrence increases verbosity 1 level through ERROR-WARNING-INFO-DEBUG')
    parser.add_argument('-d', '--debug', dest='debug', action='store_true',
                        help="enable interactive PDB debugger on exception")
    # http://docs.python.org/2.7/library/argparse.html#nargs
    # parser.add_argument('--stuff', nargs='5', dest='my_stuff',
    #                    help="one or more random things")
    parser.add_argument('inputs', nargs='*',
                        help="input files to process")
    args = parser.parse_args()

    levels = [logging.ERROR, logging.WARN, logging.INFO, logging.DEBUG]
    logging.basicConfig(level=levels[min(3, args.verbosity)])

    if args.debug:
        sys.excepthook = _debug

    if not args.inputs:
        unittest.main()
        return 0

    for pn in args.inputs:
        pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
