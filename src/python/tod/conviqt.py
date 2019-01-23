# Copyright (c) 2015-2018 by the parties listed in the AUTHORS file.
# All rights reserved.  Use of this source code is governed by
# a BSD-style license that can be found in the LICENSE file.

from ..mpi import MPI, MPI_Comm

import os

import ctypes as ct
from ctypes.util import find_library

import healpy as hp
import numpy as np
import numpy.ctypeslib as npc

from .. import qarray as qa
from ..dist import Comm, Data
from ..op import Operator
from ..tod import TOD
from ..tod import Interval
from ..tod import quat2angle

from .. import timing as timing

libconviqt = None

try:
    libconviqt = ct.CDLL("libconviqt.so")
except:
    path = find_library("conviqt")
    if path is not None:
        libconviqt = ct.CDLL(path)

if libconviqt is not None:
    # Beam functions

    libconviqt.conviqt_beam_new.restype = ct.c_void_p
    libconviqt.conviqt_beam_new.argtypes = []

    libconviqt.conviqt_beam_del.restype = ct.c_int
    libconviqt.conviqt_beam_del.argtypes = [ct.c_void_p]

    libconviqt.conviqt_beam_read.restype = ct.c_int
    libconviqt.conviqt_beam_read.argtypes = [
        ct.c_void_p,
        ct.c_long,
        ct.c_long,
        ct.c_byte,
        ct.c_char_p,
        MPI_Comm,
    ]

    libconviqt.conviqt_beam_lmax.restype = ct.c_int
    libconviqt.conviqt_beam_lmax.argtypes = [ct.c_void_p]

    libconviqt.conviqt_beam_mmax.restype = ct.c_int
    libconviqt.conviqt_beam_mmax.argtypes = [ct.c_void_p]

    libconviqt.conviqt_beam_normalize.restype = ct.c_double
    libconviqt.conviqt_beam_normalize.argtypes = [ct.c_void_p]

    # Sky functions

    libconviqt.conviqt_sky_new.restype = ct.c_void_p
    libconviqt.conviqt_sky_new.argtypes = []

    libconviqt.conviqt_sky_del.restype = ct.c_int
    libconviqt.conviqt_sky_del.argtypes = [ct.c_void_p]

    libconviqt.conviqt_sky_read.restype = ct.c_int
    libconviqt.conviqt_sky_read.argtypes = [
        ct.c_void_p,
        ct.c_long,
        ct.c_byte,
        ct.c_char_p,
        ct.c_double,
        MPI_Comm,
    ]

    libconviqt.conviqt_sky_lmax.restype = ct.c_int
    libconviqt.conviqt_sky_lmax.argtypes = [ct.c_void_p]

    libconviqt.conviqt_sky_remove_monopole.restype = ct.c_int
    libconviqt.conviqt_sky_remove_monopole.argtypes = [ct.c_void_p]

    libconviqt.conviqt_sky_remove_dipole.restype = ct.c_int
    libconviqt.conviqt_sky_remove_dipole.argtypes = [ct.c_void_p]

    # Detector functions

    libconviqt.conviqt_detector_new.restype = ct.c_void_p
    libconviqt.conviqt_detector_new.argtypes = []

    libconviqt.conviqt_detector_new_with_id.restype = ct.c_void_p
    libconviqt.conviqt_detector_new_with_id.argtypes = [ct.c_char_p]

    libconviqt.conviqt_detector_del.restype = ct.c_int
    libconviqt.conviqt_detector_del.argtypes = [ct.c_void_p]

    libconviqt.conviqt_detector_set_epsilon.restype = ct.c_int
    libconviqt.conviqt_detector_set_epsilon.argtypes = [ct.c_void_p, ct.c_double]

    libconviqt.conviqt_detector_get_epsilon.restype = ct.c_int
    libconviqt.conviqt_detector_get_epsilon.argtypes = [
        ct.c_void_p,
        ct.POINTER(ct.c_double),
    ]

    libconviqt.conviqt_detector_get_id.restype = ct.c_int
    libconviqt.conviqt_detector_get_id.argtypes = [ct.c_void_p, ct.c_char_p]

    # Pointing functions

    libconviqt.conviqt_pointing_new.restype = ct.c_void_p
    libconviqt.conviqt_pointing_new.argtypes = []

    libconviqt.conviqt_pointing_del.restype = ct.c_int
    libconviqt.conviqt_pointing_del.argtypes = [ct.c_void_p]

    libconviqt.conviqt_pointing_alloc.restype = ct.c_int
    libconviqt.conviqt_pointing_alloc.argtypes = [ct.c_void_p, ct.c_long]

    libconviqt.conviqt_pointing_data.restype = ct.POINTER(ct.c_double)
    libconviqt.conviqt_pointing_data.argtypes = [ct.c_void_p]

    # Convolver functions

    libconviqt.conviqt_convolver_new.restype = ct.c_void_p
    libconviqt.conviqt_convolver_new.argtypes = [
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_byte,
        ct.c_long,
        ct.c_long,
        ct.c_long,
        MPI_Comm,
    ]

    libconviqt.conviqt_convolver_convolve.restype = ct.c_int
    libconviqt.conviqt_convolver_convolve.argtypes = [
        ct.c_void_p,
        ct.c_void_p,
        ct.c_byte,
    ]

    libconviqt.conviqt_convolver_del.restype = ct.c_int
    libconviqt.conviqt_convolver_del.argtypes = [ct.c_void_p]


class OpSimConviqt(Operator):
    """
    Operator which uses libconviqt to generate beam-convolved timestreams.

    This passes through each observation and loops over each detector.
    For each detector, it produces the beam-convolved timestream.

    Args:
        lmax (int): Maximum ell (and m). Actual resolution in the Healpix FITS
            file may differ.
        beammmax (int): beam maximum m. Actual resolution in the Healpix FITS file
            may differ.
        detectordata (list): list of (detector_name, detector_sky_file,
            detector_beam_file, epsilon, psipol[radian]) tuples
        pol (bool) : boolean to determine if polarized simulation is needed
        fwhm (float) : width of a symmetric gaussian beam [in arcmin] already
            present in the skyfile (will be deconvolved away).
        order (int) : conviqt order parameter (expert mode)
        calibrate (bool) : Calibrate intensity to 1.0, rather than (1+epsilon)/2
        dxx (bool) : The beam frame is either Dxx or Pxx. Pxx includes the
            rotation to polarization sensitive basis, Dxx does not.  When
            Dxx=True, detector orientation from attitude quaternions is
            corrected for the polarization angle.
        out (str): the name of the cache object (<name>_<detector>) to
            use for output of the detector timestream.
    """

    def __init__(
        self,
        lmax,
        beammmax,
        detectordata,
        pol=True,
        fwhm=4.0,
        order=13,
        calibrate=True,
        dxx=True,
        out="conviqt",
        quat_name=None,
        flag_name=None,
        flag_mask=255,
        common_flag_name=None,
        common_flag_mask=255,
        apply_flags=False,
        remove_monopole=False,
        remove_dipole=False,
        normalize_beam=False,
        verbose=False,
    ):

        # We call the parent class constructor, which currently does nothing
        super().__init__()

        self._lmax = lmax
        self._beammmax = beammmax
        self._detectordata = {}
        for entry in detectordata:
            self._detectordata[entry[0]] = entry[1:]
        self._pol = pol
        self._fwhm = fwhm
        self._order = order
        self._calibrate = calibrate
        self._dxx = dxx
        self._quat_name = quat_name
        self._flag_name = flag_name
        self._flag_mask = flag_mask
        self._common_flag_name = common_flag_name
        self._common_flag_mask = common_flag_mask
        self._apply_flags = apply_flags
        self._remove_monopole = remove_monopole
        self._remove_dipole = remove_dipole
        self._normalize_beam = normalize_beam
        self._verbose = verbose

        self._out = out

    @property
    def available(self):
        """
        (bool): True if libconviqt is found in the library search path.
        """
        return libconviqt is not None

    def exec(self, data):
        """
        Loop over all observations and perform the convolution.

        This is done one detector at a time.  For each detector, all data
        products are read from disk.

        Args:
            data (toast.Data): The distributed data.
        """
        if libconviqt is None:
            raise RuntimeError("The conviqt library was not found")

        autotimer = timing.auto_timer(type(self).__name__)
        # the two-level pytoast communicator
        # comm = data.comm
        # the global communicator
        # cworld = comm.comm_world
        # the communicator within the group
        # cgroup = comm.comm_group
        # the communicator with all processes with
        # the same rank within their group
        # crank = comm.comm_rank

        xaxis, yaxis, zaxis = np.eye(3)
        nullquat = np.array([0, 0, 0, 1], dtype=np.float64)

        for obs in data.obs:
            tstart_obs = MPI.Wtime()
            tod = obs["tod"]
            intrvl = obs["intervals"]
            offset, nsamp = tod.local_samples

            comm_ptr = MPI._addressof(tod.mpicomm)
            comm = MPI_Comm.from_address(comm_ptr)

            for det in tod.local_dets:
                tstart_det = MPI.Wtime()
                try:
                    skyfile, beamfile, epsilon, psipol = self._detectordata[det]
                except:
                    raise Exception(
                        "ERROR: conviqt object not initialized to convolve "
                        "detector {}. Available detectors are {}".format(
                            det, self._detectordata.keys()
                        )
                    )

                sky = self.get_sky(skyfile, comm, det, tod)

                beam = self.get_beam(beamfile, comm, det, tod)

                detector = self.get_detector(det, epsilon)

                theta, phi, psi = self.get_pointing(tod, det, psipol)

                pnt = self.get_buffer(theta, phi, psi, tod, nsamp, det)

                convolved_data = self.convolve(
                    sky, beam, detector, comm, pnt, tod, nsamp, det
                )

                cachename = "{}_{}".format(self._out, det)
                if not tod.cache.exists(cachename):
                    tod.cache.create(cachename, np.float64, (nsamp,))
                ref = tod.cache.reference(cachename)
                if ref.size != convolved_data.size:
                    raise RuntimeError(
                        "{} already exists in tod.cache but has wrong size: {} "
                        "!= {}".format(cachename, ref.size, convolved_data.size)
                    )
                ref[:] += convolved_data

                libconviqt.conviqt_pointing_del(pnt)
                libconviqt.conviqt_detector_del(detector)
                libconviqt.conviqt_beam_del(beam)
                libconviqt.conviqt_sky_del(sky)

                tstop = MPI.Wtime()
                if self._verbose and tod.mpicomm.rank == 0:
                    print(
                        "{} processed in {:.2f}s".format(det, tstop - tstart_det),
                        flush=True,
                    )

            tstop = MPI.Wtime()
            if self._verbose and tod.mpicomm.rank == 0:
                print(
                    "{} convolved in {:.2f}s".format("observation", tstop - tstart_obs),
                    flush=True,
                )

        return

    def get_sky(self, skyfile, comm, det, tod):
        tstart = MPI.Wtime()
        sky = libconviqt.conviqt_sky_new()
        err = libconviqt.conviqt_sky_read(
            sky, self._lmax, self._pol, skyfile.encode(), self._fwhm, comm
        )
        if err != 0:
            raise RuntimeError("Failed to load " + skyfile)
        if self._remove_monopole:
            err = libconviqt.conviqt_sky_remove_monopole(sky)
            if err != 0:
                raise RuntimeError("Failed to remove monopole")
        if self._remove_dipole:
            err = libconviqt.conviqt_sky_remove_dipole(sky)
            if err != 0:
                raise RuntimeError("Failed to remove dipole")
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print(
                "{} sky initialized in {:.2f}s".format(det, tstop - tstart), flush=True
            )
        return sky

    def get_beam(self, beamfile, comm, det, tod):
        tstart = MPI.Wtime()
        beam = libconviqt.conviqt_beam_new()
        err = libconviqt.conviqt_beam_read(
            beam, self._lmax, self._beammmax, self._pol, beamfile.encode(), comm
        )
        if err != 0:
            raise Exception("Failed to load " + beamfile)
        if self._normalize_beam:
            scale = libconviqt.conviqt_beam_normalize(beam)
            if scale < 0:
                raise Exception(
                    "Failed to normalize the beam in {}. normalize() "
                    "returned {}".format(beamfile)
                )
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print(
                "{} beam initialized in {:.2f}s".format(det, tstop - tstart), flush=True
            )
        return beam

    def get_detector(self, det, epsilon):
        detector = libconviqt.conviqt_detector_new_with_id(det.encode())
        libconviqt.conviqt_detector_set_epsilon(detector, epsilon)
        return detector

    def get_pointing(self, tod, det, psipol):
        # We need the three pointing angles to describe the
        # pointing. local_pointing returns the attitude quaternions.
        tstart = MPI.Wtime()
        pdata = tod.local_pointing(det, self._quat_name).copy()
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print("{} pointing read in {:.2f}s".format(det, tstop - tstart), flush=True)

        if self._apply_flags:
            tstart = MPI.Wtime()
            common = tod.local_common_flags(self._common_flag_name)
            flags = tod.local_flags(det, self._flag_name)
            common = common & self._common_flag_mask
            flags = flags & self._flag_mask
            totflags = np.copy(flags)
            totflags |= common
            pdata[totflags != 0] = nullquat
            tstop = MPI.Wtime()
            if self._verbose and tod.mpicomm.rank == 0:
                print(
                    "{} flags initialized in {:.2f}s".format(det, tstop - tstart),
                    flush=True,
                )

        tstart = MPI.Wtime()
        theta, phi, psi = quat2angle(pdata)
        # Is the psi angle in Pxx or Dxx? Pxx will include the
        # detector polarization angle, Dxx will not.
        if self._dxx:
            psi -= psipol
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print(
                "{} pointing angles computed in {:.2f}s".format(det, tstop - tstart),
                flush=True,
            )
        return theta, phi, psi

    def get_buffer(self, theta, phi, psi, tod, nsamp, det):
        """
        Pack the pointing into the libconviqt pointing array
        """
        tstart = MPI.Wtime()
        pnt = libconviqt.conviqt_pointing_new()
        err = libconviqt.conviqt_pointing_alloc(pnt, 5 * nsamp)
        if err != 0:
            raise Exception("Failed to allocate pointing array")
        ppnt = libconviqt.conviqt_pointing_data(pnt)
        arr = np.ctypeslib.as_array(ppnt, shape=(nsamp, 5))
        arr[:, 0] = phi
        arr[:, 1] = theta
        arr[:, 2] = psi
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print(
                "{} input array packed in {:.2f}s".format(det, tstop - tstart),
                flush=True,
            )
        return pnt

    def convolve(self, sky, beam, detector, comm, pnt, tod, nsamp, det):
        tstart = MPI.Wtime()
        convolver = libconviqt.conviqt_convolver_new(
            sky,
            beam,
            detector,
            self._pol,
            self._lmax,
            self._beammmax,
            self._order,
            comm,
        )
        if convolver is None:
            raise Exception("Failed to instantiate convolver")
        err = libconviqt.conviqt_convolver_convolve(convolver, pnt, self._calibrate)
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print("{} convolved in {:.2f}s".format(det, tstop - tstart), flush=True)
        if err != 0:
            raise Exception("Convolution FAILED!")

        # The pointer to the data will have changed during
        # the convolution call ...

        tstart = MPI.Wtime()
        ppnt = libconviqt.conviqt_pointing_data(pnt)
        arr = np.ctypeslib.as_array(ppnt, shape=(nsamp, 5))
        convolved_data = arr[:, 3].astype(np.float64)
        tstop = MPI.Wtime()
        if self._verbose and tod.mpicomm.rank == 0:
            print(
                "{} convolved data extracted in {:.2f}s".format(det, tstop - tstart),
                flush=True,
            )

        libconviqt.conviqt_convolver_del(convolver)

        return convolved_data
