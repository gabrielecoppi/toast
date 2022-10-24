# Copyright (c) 2015-2020 by the parties listed in the AUTHORS file.
# All rights reserved.  Use of this source code is governed by
# a BSD-style license that can be found in the LICENSE file.

import numpy as np

import jax
import jax.numpy as jnp
from jax.experimental.maps import xmap as jax_xmap

from .utils import (
    assert_data_localization,
    dataMovementTracker,
    select_implementation,
    ImplementationType,
    math_qarray as qarray,
)
from .utils.mutableArray import MutableJaxArray
from .utils.intervals import INTERVALS_JAX, JaxIntervals, ALL
from ..._libtoast import (
    stokes_weights_I as stokes_weights_I_compiled,
    stokes_weights_IQU as stokes_weights_IQU_compiled,
)

# -------------------------------------------------------------------------------------------------
# JAX


def stokes_weights_IQU_inner_jax(eps, cal, pin, hwpang):
    """
    Compute the Stokes weights for one detector.

    Args:
        eps (float):  The cross polar response.
        cal (float):  A constant to apply to the pointing weights.
        pin (array, float64):  The array of detector quaternions (size 4).
        hwpang (float64):  The HWP angle (could be None).

    Returns:
        weights (array, float64):  The detector weights for the specified mode (size 3)
    """
    # applies quaternion rotations
    zaxis = jnp.array([0.0, 0.0, 1.0])
    dir = qarray.rotate_one_one_jax(pin, zaxis)
    xaxis = jnp.array([1.0, 0.0, 0.0])
    orient = qarray.rotate_one_one_jax(pin, xaxis)

    # computes by and bx
    by = orient[0] * dir[1] - orient[1] * dir[0]
    bx = (
        orient[0] * (-dir[2] * dir[0])
        + orient[1] * (-dir[2] * dir[1])
        + orient[2] * (dir[0] * dir[0] + dir[1] * dir[1])
    )

    # computes detang
    detang = jnp.arctan2(by, bx)
    detang = detang + 2.0 * hwpang
    detang = 2.0 * detang

    # puts values into weights
    eta = (1.0 - eps) / (1.0 + eps)
    weights = jnp.array([cal, jnp.cos(detang) * eta * cal, jnp.sin(detang) * eta * cal])
    return weights


# maps over samples, intervals and detectors
stokes_weights_IQU_inner_jax = jax_xmap(
    stokes_weights_IQU_inner_jax,
    in_axes=[
        ["detectors"],  # epsilon
        [...],  # cal
        ["detectors", "intervals", "interval_size", ...],  # quats
        ["intervals", "interval_size"],
    ],  # hwp
    out_axes=["detectors", "intervals", "interval_size", ...],
)


def stokes_weights_IQU_interval_jax(
    quat_index,
    quats,
    weight_index,
    weights,
    hwp,
    epsilon,
    cal,
    interval_starts,
    interval_ends,
    intervals_max_length,
):
    """
    Process all the intervals as a block.

    Args:
        quat_index (array, int): size n_det
        quats (array, double): size ???*n_samp*4
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, float64): The flat packed detectors weights for the specified mode (size n_det*n_samp*3)
        hwp (array, float64):  The HWP angles (size n_samp).
        epsilon (array, float):  The cross polar response (size n_det).
        cal (float):  A constant to apply to the pointing weights.
        interval_starts (array, int): size n_view
        interval_ends (array, int): size n_view
        intervals_max_length (int): maximum length of an interval

    Returns:
        weights
    """
    # display sizes
    nb_intervals = interval_starts.size
    print(
        f"DEBUG: jit-compiling 'stokes_weights_IQU_interval_jax' with n_det:{epsilon.size} cal:{cal} nb_intervals:{nb_intervals} intervals_max_length:{intervals_max_length}"
    )

    # extract interval slices
    intervals = JaxIntervals(
        interval_starts, interval_ends + 1, intervals_max_length
    )  # end+1 as the interval is inclusive
    quats_interval = JaxIntervals.get(
        quats, (quat_index, intervals, ALL)
    )  # quats[quat_index,intervals,:]

    # insures hwp is a non empty array
    if hwp.size == 0:
        hwp_interval = jnp.zeros((nb_intervals, intervals_max_length))
    else:
        hwp_interval = JaxIntervals.get(hwp, intervals)  # hwp[intervals]

    # does the computation
    new_weights_interval = stokes_weights_IQU_inner_jax(
        epsilon, cal, quats_interval, hwp_interval
    )

    # updates results and returns
    # weights[weight_index,intervals,:] = new_weights_interval
    weights = JaxIntervals.set(
        weights, (weight_index, intervals, ALL), new_weights_interval
    )
    return weights


# jit compiling
stokes_weights_IQU_interval_jax = jax.jit(
    stokes_weights_IQU_interval_jax,
    static_argnames=["cal", "intervals_max_length"],
    donate_argnums=[3],
)  # donates weights


def stokes_weights_IQU_jax(
    quat_index, quats, weight_index, weights, hwp, intervals, epsilon, cal, use_accel
):
    """
    Compute the Stokes weights for the "IQU" mode.

    Args:
        quat_index (array, int): size n_det
        quats (array, double): size ???*n_samp*4
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, float64): The flat packed detectors weights for the specified mode (size n_det*n_samp*3)
        hwp (array, float64):  The HWP angles (size n_samp).
        intervals (array, Interval): The intervals to modify (size n_view)
        epsilon (array, float):  The cross polar response (size n_det).
        cal (float):  A constant to apply to the pointing weights.
        use_accel (bool): should we use the accelerator

    Returns:
        None (the result is put in weights).
    """
    # make sure the data is where we expect it
    assert_data_localization(
        "stokes_weights_IQU", use_accel, [quats, hwp, epsilon], [weights]
    )

    # prepares inputs
    intervals_max_length = INTERVALS_JAX.compute_max_intervals_length(intervals)
    quat_index_input = MutableJaxArray.to_array(quat_index)
    quats_input = MutableJaxArray.to_array(quats)
    weight_index_input = MutableJaxArray.to_array(weight_index)
    weights_input = MutableJaxArray.to_array(weights)
    hwp_input = MutableJaxArray.to_array(hwp)
    epsilon_input = MutableJaxArray.to_array(epsilon)

    # track data movement
    dataMovementTracker.add(
        "stokes_weights_IQU",
        use_accel,
        [
            quat_index_input,
            quats_input,
            weight_index_input,
            weights_input,
            hwp_input,
            epsilon_input,
            intervals.first,
            intervals.last,
        ],
        [weights],
    )

    # runs computation
    weights[:] = stokes_weights_IQU_interval_jax(
        quat_index_input,
        quats_input,
        weight_index_input,
        weights_input,
        hwp_input,
        epsilon_input,
        cal,
        intervals.first,
        intervals.last,
        intervals_max_length,
    )


def stokes_weights_I_jax(weight_index, weights, intervals, cal, use_accel):
    """
    Compute the Stokes weights for the "I" mode.
    TODO this does not use JAX as there is too little computation

    Args:
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, float64): The flat packed detectors weights for the specified mode (size n_det*n_samp)
        intervals (array, Interval): The intervals to modify (size n_view)
        cal (float):  A constant to apply to the pointing weights.
        use_accel (bool): should we use the accelerator

    Returns:
        None (the result is put in weights).
    """
    # problem size
    print(
        f"DEBUG: running 'stokes_weights_I_jax' with n_view:{intervals.size} n_det:{weight_index.size} n_samp:{weights.shape[1]} n_view:{intervals} cal:{cal}"
    )

    # iterate on the intervals
    for interval in intervals:
        interval_start = interval["first"]
        interval_end = interval["last"] + 1
        weights[weight_index, interval_start:interval_end] = cal


# -------------------------------------------------------------------------------------------------
# NUMPY


def stokes_weights_IQU_inner_numpy(eps, cal, pin, hwpang, weights):
    """
    Compute the Stokes weights for one detector and the IQU mode.

    Args:
        eps (float):  The cross polar response.
        cal (float):  A constant to apply to the pointing weights.
        pin (array, float64):  Ddetector quaternions (size 4).
        hwpang (float):  The HWP angle.
        weights (array, float64):  Detector weights for the specified mode (size 3).

    Returns:
        None (the result is put in weights).
    """
    # constants
    xaxis = np.array([1.0, 0.0, 0.0])
    zaxis = np.array([0.0, 0.0, 1.0])
    eta = (1.0 - eps) / (1.0 + eps)

    # applies quaternion rotation
    dir = qarray.rotate_one_one_numpy(pin, zaxis)
    orient = qarray.rotate_one_one_numpy(pin, xaxis)

    # computes by and bx
    by = orient[0] * dir[1] - orient[1] * dir[0]
    bx = (
        orient[0] * (-dir[2] * dir[0])
        + orient[1] * (-dir[2] * dir[1])
        + orient[2] * (dir[0] * dir[0] + dir[1] * dir[1])
    )

    # computes detang
    detang = np.arctan2(by, bx)
    detang += 2.0 * hwpang
    detang *= 2.0

    # puts values into weights
    weights[0] = cal
    weights[1] = np.cos(detang) * eta * cal
    weights[2] = np.sin(detang) * eta * cal


def stokes_weights_IQU_numpy(
    quat_index, quats, weight_index, weights, hwp, intervals, epsilon, cal, use_accel
):
    """
    Compute the Stokes weights for the "IQU" mode.

    Args:
        quat_index (array, int): size n_det
        quats (array, double): size ???*n_samp*4
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, float64): The flat packed detectors weights for the specified mode (size ???*n_samp*3)
        hwp (optional array, float64):  The HWP angles (size n_samp, could be None).
        intervals (array, Interval): The intervals to modify (size n_view)
        epsilon (array, float):  The cross polar response (size n_det).
        cal (float):  A constant to apply to the pointing weights.
        use_accel (bool): should we use the accelerator

    Returns:
        None (the result is put in weights).
    """
    # problem size
    n_det = quat_index.size
    n_samp = quats.shape[1]
    print(
        f"DEBUG: running 'stokes_weights_IQU_numpy' with n_view:{intervals.size} n_det:{n_det} n_samp:{n_samp}"
    )

    # insures hwp is a non empty array
    if (hwp is None) or (hwp.size == 0):
        hwp = np.zeros(n_samp)

    # iterates on detectors and intervals
    for idet in range(n_det):
        for interval in intervals:
            interval_start = interval["first"]
            interval_end = interval["last"] + 1
            for isamp in range(interval_start, interval_end):
                w_index = weight_index[idet]
                q_index = quat_index[idet]
                stokes_weights_IQU_inner_numpy(
                    epsilon[idet],
                    cal,
                    quats[q_index, isamp, :],
                    hwp[isamp],
                    weights[w_index, isamp, :],
                )


def stokes_weights_I_numpy(weight_index, weights, intervals, cal, use_accel):
    """
    Compute the Stokes weights for the "I" mode.

    Args:
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, float64): The flat packed detectors weights for the specified mode (size n_det*n_samp)
        intervals (array, Interval): The intervals to modify (size n_view)
        cal (float):  A constant to apply to the pointing weights.
        use_accel (bool): should we use the accelerator

    Returns:
        None (the result is put in weights).
    """
    # problem size
    n_det = weight_index.size
    print(
        f"DEBUG: running 'stokes_weights_I_numpy' with n_view:{intervals.size} n_det:{n_det} n_samp:{weights.shape[1]}"
    )

    for interval in intervals:
        interval_start = interval["first"]
        interval_end = interval["last"] + 1
        weights[weight_index, interval_start:interval_end] = cal


# -------------------------------------------------------------------------------------------------
# C++

"""
void stokes_weights_IQU_inner(
    double cal,
    int32_t const * quat_index,
    int32_t const * weight_index,
    double const * quats,
    double const * hwp,
    double const * epsilon,
    double * weights,
    int64_t isamp,
    int64_t n_samp,
    int64_t idet) 
{
    const double xaxis[3] = {1.0, 0.0, 0.0};
    const double zaxis[3] = {0.0, 0.0, 1.0};
    double eta = (1.0 - epsilon[idet]) / (1.0 + epsilon[idet]);
    int32_t q_indx = quat_index[idet];
    int32_t w_indx = weight_index[idet];

    double dir[3];
    double orient[3];

    int64_t off = (q_indx * 4 * n_samp) + 4 * isamp;
    qa_rotate(&(quats[off]), zaxis, dir);
    qa_rotate(&(quats[off]), xaxis, orient);

    double y = orient[0] * dir[1] - orient[1] * dir[0];
    double x = orient[0] * (-dir[2] * dir[0]) + orient[1] * (-dir[2] * dir[1]) + orient[2] * (dir[0] * dir[0] + dir[1] * dir[1]);
    double ang = atan2(y, x);

    ang += 2.0 * hwp[isamp];
    ang *= 2.0;
    double cang = cos(ang);
    double sang = sin(ang);

    off = (w_indx * 3 * n_samp) + 3 * isamp;
    weights[off] = cal;
    weights[off + 1] = cang * eta * cal;
    weights[off + 2] = sang * eta * cal;
}

void stokes_weights_IQU(
            py::buffer quat_index,
            py::buffer quats,
            py::buffer weight_index,
            py::buffer weights,
            py::buffer hwp,
            py::buffer intervals,
            py::buffer epsilon,
            double cal,
            bool use_accel
        )
{
    // This is used to return the actual shape of each buffer
    std::vector <int64_t> temp_shape(3);

    int32_t * raw_quat_index = extract_buffer <int32_t> (quat_index, "quat_index", 1, temp_shape, {-1});
    int64_t n_det = temp_shape[0];

    int32_t * raw_weight_index = extract_buffer <int32_t> (weight_index, "weight_index", 1, temp_shape, {n_det});

    double * raw_weights = extract_buffer <double> (weights, "weights", 3, temp_shape, {-1, -1, 3});
    int64_t n_samp = temp_shape[1];

    double * raw_quats = extract_buffer <double> (quats, "quats", 3, temp_shape, {-1, n_samp, 4});

    double * raw_hwp = extract_buffer <double> (hwp, "hwp", 1, temp_shape, {n_samp});

    Interval * raw_intervals = extract_buffer <Interval> (intervals, "intervals", 1, temp_shape, {-1});
    int64_t n_view = temp_shape[0];

    double * raw_epsilon = extract_buffer <double> (epsilon, "epsilon", 1, temp_shape, {n_det});

    double * dev_weights = raw_weights;
    double * dev_hwp = raw_hwp;
    double * dev_quats = raw_quats;
    Interval * dev_intervals = raw_intervals;
    
    for (int64_t idet = 0; idet < n_det; idet++) 
    {
        for (int64_t iview = 0; iview < n_view; iview++) 
        {
            #pragma omp parallel for
            for (int64_t isamp = dev_intervals[iview]['first']; isamp <= dev_intervals[iview]['last']; isamp++)
            {
                stokes_weights_IQU_inner(
                    cal,
                    raw_quat_index,
                    raw_weight_index,
                    dev_quats,
                    dev_hwp,
                    raw_epsilon,
                    dev_weights,
                    isamp,
                    n_samp,
                    idet
                );
            }
        }
    }
}

void stokes_weights_I(py::buffer weight_index, py::buffer weights, py::buffer intervals, double cal) 
{
    // NOTE:  Flags are not needed here, since the quaternions
    // have already had bad samples converted to null rotations.

    // This is used to return the actual shape of each buffer
    std::vector <int64_t> temp_shape(3);

    int32_t * raw_weight_index = extract_buffer <int32_t> (weight_index, "weight_index", 1, temp_shape, {-1});
    int64_t n_det = temp_shape[0];

    double * raw_weights = extract_buffer <double> (weights, "weights", 2, temp_shape, {n_det, -1});
    int64_t n_samp = temp_shape[1];

    Interval * raw_intervals = extract_buffer <Interval> (intervals, "intervals", 1, temp_shape, {-1});
    int64_t n_view = temp_shape[0];

    double * dev_weights = raw_weights;
    Interval * dev_intervals = raw_intervals;
    
    for (int64_t idet = 0; idet < n_det; idet++) 
    {
        for (int64_t iview = 0; iview < n_view; iview++) 
        {
            #pragma omp parallel for
            for (int64_t isamp = dev_intervals[iview]['first']; isamp <= dev_intervals[iview]['last']; isamp++)
            {
                int32_t w_indx = raw_weight_index[idet];
                int64_t off = (w_indx * n_samp) + isamp;
                dev_weights[off] = cal;
            }
        }
    }
}
"""

# -------------------------------------------------------------------------------------------------
# IMPLEMENTATION SWITCH

# lets us play with the various implementations
stokes_weights_I = select_implementation(
    stokes_weights_I_compiled, stokes_weights_I_numpy, stokes_weights_I_jax
)
stokes_weights_IQU = select_implementation(
    stokes_weights_IQU_compiled, stokes_weights_IQU_numpy, stokes_weights_IQU_jax
)

# To test:
# python -c 'import toast.tests; toast.tests.run("ops_pointing_healpix"); toast.tests.run("ops_sim_tod_dipole")'

# to bench:
# use scanmap config and check StokesWeights._exec field in timing.csv