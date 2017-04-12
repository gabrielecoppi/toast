# Copyright (c) 2015-2017 by the parties listed in the AUTHORS file.
# All rights reserved.  Use of this source code is governed by 
# a BSD-style license that can be found in the LICENSE file.

from ..mpi import MPI

import os
import unittest
import warnings

from .._version import __version__

from .mpi import MPITestRunner

from .ctoast import test_ctoast

from . import cbuffer as testcbuffer
from . import cache as testcache
from . import rng as testrng
from . import fft as testfft
from . import dist as testdist
from . import qarray as testqarray
from . import tod as testtod
from . import psd_math as testpsdmath
from . import intervals as testintervals
from . import cov as testcov
from . import ops_pmat as testopspmat
from . import ops_dipole as testopsdipole
from . import ops_simnoise as testopssimnoise
from . import ops_madam as testopsmadam
from . import map_satellite as testmapsatellite
from . import map_ground as testmapground
from . import binned as testbinned


def test():
    # We run tests with COMM_WORLD
    comm = MPI.COMM_WORLD
    
    outdir = "toast_test_output"

    if comm.rank == 0:
        outdir = os.path.abspath(outdir)
        if not os.path.isdir(outdir):
            os.makedirs(outdir)

    outdir = comm.bcast(outdir, root=0)

    # Run tests from the compiled library.  This separately uses
    # MPI_COMM_WORLD.
    test_ctoast()

    # Run python tests.

    loader = unittest.TestLoader()
    mpirunner = MPITestRunner(verbosity=2)
    suite = unittest.TestSuite()

    suite.addTest( loader.loadTestsFromModule(testcbuffer) )
    suite.addTest( loader.loadTestsFromModule(testcache) )
    suite.addTest( loader.loadTestsFromModule(testrng) )
    suite.addTest( loader.loadTestsFromModule(testfft) )
    suite.addTest( loader.loadTestsFromModule(testdist) )
    suite.addTest( loader.loadTestsFromModule(testqarray) )
    suite.addTest( loader.loadTestsFromModule(testtod) )
    suite.addTest( loader.loadTestsFromModule(testpsdmath) )
    suite.addTest( loader.loadTestsFromModule(testintervals) )
    suite.addTest( loader.loadTestsFromModule(testopspmat) )
    suite.addTest( loader.loadTestsFromModule(testcov) )
    suite.addTest( loader.loadTestsFromModule(testopsdipole) )
    suite.addTest( loader.loadTestsFromModule(testopssimnoise) )
    suite.addTest( loader.loadTestsFromModule(testopsmadam) )
    suite.addTest( loader.loadTestsFromModule(testmapsatellite) )
    suite.addTest( loader.loadTestsFromModule(testmapground) )
    suite.addTest( loader.loadTestsFromModule(testbinned) )

    with warnings.catch_warnings(record=True) as w:
        # Cause all toast warnings to be shown.
        warnings.simplefilter("always", UserWarning)
        mpirunner.run(suite)

    return
