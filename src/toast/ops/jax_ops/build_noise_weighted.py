# Copyright (c) 2015-2020 by the parties listed in the AUTHORS file.
# All rights reserved.  Use of this source code is governed by
# a BSD-style license that can be found in the LICENSE file.

import numpy as np

import jax
import jax.numpy as jnp
from jax.experimental.maps import xmap as jax_xmap

from toast.ops.jax_ops.utils.mutableArray import MutableJaxArray

from .utils import assert_data_localization, dataMovementTracker, select_implementation, ImplementationType
from .utils.intervals import JaxIntervals, ALL
from ..._libtoast import build_noise_weighted as build_noise_weighted_compiled

#-------------------------------------------------------------------------------------------------
# JAX

def build_noise_weighted_interval_jax(global2local, zmap, pixel_index, pixels, weight_index, weights, data_index, det_data, flag_index, det_flags, det_scale, det_flag_mask, shared_flags, shared_flag_mask,
                                      interval_starts, interval_ends, intervals_max_length):
    """
    Process all the intervals as a block.

    Args:
        global2local (array, int): size n_global_submap
        zmap (array, double): size n_local_submap*n_pix_submap*nnz
        pixel_index (array, int): size n_det
        pixels (array, int): size n_det*n_samp
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, double): The flat packed detectors weights for the specified mode (size n_det*n_samp*nnz)
        data_index (array, int): size n_det
        det_data (array, double): size n_det*n_samp
        flag_index (array, int): size n_det
        det_flags (array, uint8): size n_det*n_samp
        det_scale (array, double): size n_det
        det_flag_mask (uint8)
        shared_flags (array, uint8): size n_samp
        shared_flag_mask (uint8)
        interval_starts (array, int): size n_view
        interval_ends (array, int): size n_view
        intervals_max_length (int): maximum length of an interval

    Returns:
        zmap
    """
    # should we use flags?
    n_samp = pixels.shape[1]
    use_det_flags = (det_flags.shape[1] == n_samp)
    use_shared_flags = (shared_flags.size == n_samp)
    print(f"DEBUG: jit-compiling 'build_noise_weighted_interval_jax' with zmap_shape:{zmap.shape} n_det:{det_scale.size} intervals_max_length:{intervals_max_length} det_mask:{det_flag_mask} shared_flag_mask:{shared_flag_mask} use_flags:{det_flags is not None} use_shared_flags:{shared_flags is not None}")

    # extract interval slices
    intervals = JaxIntervals(interval_starts, interval_ends+1, intervals_max_length) # end+1 as the interval is inclusive
    pixels_interval = JaxIntervals.get(pixels, (pixel_index,intervals)) # pixels[pixel_index,intervals]
    weights_interval = JaxIntervals.get(weights, (weight_index,intervals,ALL)) # weights[weight_index,intervals,:]
    data_interval = JaxIntervals.get(det_data, (data_index,intervals)) # det_data[data_index,intervals]

    # setup det check
    if use_det_flags:
        det_flags_interval = JaxIntervals.get(det_flags, (flag_index,intervals)) # det_flags[flag_index,intervals]
        det_check = ((det_flags_interval & det_flag_mask) == 0)
    else:
        det_check = True
    # setup shared check
    if use_shared_flags:
        shared_flags_interval = JaxIntervals.get(shared_flags, intervals) # shared_flags[intervals]
        shared_check = ((shared_flags_interval & shared_flag_mask) == 0)
    else:
        shared_check = True
    # mask to identify valid samples
    valid_samples = (pixels_interval >= 0) & det_check & shared_check

    # computes the update to add to zmap
    scaled_data = data_interval * det_scale[:,jnp.newaxis,jnp.newaxis]
    update = jnp.where(valid_samples[:,:,:,jnp.newaxis], # if
                       weights_interval * scaled_data[:,:,:,jnp.newaxis], # then
                       0.) # else

    # computes the index in zmap
    n_pix_submap = zmap.shape[1]
    global_submap = pixels_interval // n_pix_submap
    local_submap = global2local[global_submap]
    isubpix = pixels_interval - global_submap * n_pix_submap

    # masks padded value before applying the update
    update_masked = jnp.where(intervals.mask[jnp.newaxis,:,:,jnp.newaxis], zmap[local_submap, isubpix, :], update)

    # updates zmap and returns
    zmap = zmap.at[local_submap, isubpix, :].add(update_masked)
    return zmap

# jit compiling
build_noise_weighted_interval_jax = jax.jit(build_noise_weighted_interval_jax, 
                                            static_argnames=['det_flag_mask', 'shared_flag_mask', 'intervals_max_length'],
                                            donate_argnums=[1]) # donate zmap

def build_noise_weighted_jax(global2local, zmap, pixel_index, pixels, weight_index, weights, data_index, det_data, flag_index, det_flags, det_scale, det_flag_mask, intervals, shared_flags, shared_flag_mask, use_accel):
    """
    Args:
        global2local (array, int): size n_global_submap
        zmap (array, double): size n_local_submap*n_pix_submap*nnz
        pixel_index (array, int): size n_det
        pixels (array, int): size n_det*n_samp
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, double): The flat packed detectors weights for the specified mode (size n_det*n_samp*nnz)
        data_index (array, int): size n_det
        det_data (array, double): size n_det*n_samp
        flag_index (array, int): size n_det
        det_flags (array, uint8): size n_det*n_samp
        det_scale (array, double): size n_det
        det_flag_mask (uint8)
        intervals (array, Interval): The intervals to modify (size n_view)
        shared_flags (array, uint8): size n_samp
        shared_flag_mask (uint8)
        use_accel (Bool): should we use the accelerator?

    Returns:
        None (the result is put in zmap).
    """
    # make sure the data is where we expect it
    assert_data_localization('build_noise_weighted', use_accel, [global2local, zmap, pixels, weights, det_data, det_flags, det_scale, shared_flags], [zmap])

    # prepares inputs
    if intervals.size == 0: return # deals with a corner case in tests
    intervals_max_length = np.max(1 + intervals.last - intervals.first) # end+1 as the interval is inclusive
    zmap_input = MutableJaxArray.to_array(zmap)
    global2local = MutableJaxArray.to_array(global2local)
    pixels = MutableJaxArray.to_array(pixels)
    pixel_index = MutableJaxArray.to_array(pixel_index)
    weights = MutableJaxArray.to_array(weights)
    weight_index = MutableJaxArray.to_array(weight_index)
    det_data = MutableJaxArray.to_array(det_data)
    data_index = MutableJaxArray.to_array(data_index)
    det_flags = MutableJaxArray.to_array(det_flags)
    flag_index = MutableJaxArray.to_array(flag_index)
    det_scale = MutableJaxArray.to_array(det_scale)
    shared_flags = MutableJaxArray.to_array(shared_flags)

    # track data movement
    dataMovementTracker.add("build_noise_weighted", use_accel, [global2local, zmap_input, pixel_index, pixels, weight_index, weights, data_index, det_data, flag_index, det_flags, det_scale, shared_flags, intervals.first, intervals.last], [zmap])

    # runs computation
    zmap[:] = build_noise_weighted_interval_jax(global2local, zmap_input, pixel_index, pixels, weight_index, weights, data_index, det_data, flag_index, det_flags, det_scale, det_flag_mask, shared_flags, shared_flag_mask,
                                                intervals.first, intervals.last, intervals_max_length)

#-------------------------------------------------------------------------------------------------
# NUMPY

def build_noise_weighted_inner_numpy(global2local, data, det_flag, shared_flag, pixel, weights, det_scale, zmap,
                                     det_mask, shared_mask):
    """
    Args:
        global2local (array, int): size n_global_submap
        data (double)
        det_flag (uint8): Optional, could be None
        shared_flag (uint8): Optional, could be None
        pixels(int)
        weights (array, double): The flat packed detectors weights for the specified mode (nnz)
        det_scale (double)
        zmap (array, double): size n_local_submap*n_pix_submap*nnz
        det_mask (uint8)
        shared_mask (uint8)

    Returns:
        None (the result is put in zmap).
    """
    det_check = True if (det_flag is None) else ((det_flag & det_mask) == 0)
    shared_check = True if (shared_flag is None) else ((shared_flag & shared_mask) == 0)
    if (pixel >= 0) and (det_check and shared_check): 
        # Good data, accumulate
        scaled_data = data * det_scale
        # computes the index in zmap
        n_pix_submap = zmap.shape[1]
        global_submap = pixel // n_pix_submap
        local_submap = global2local[global_submap]
        isubpix = pixel - global_submap * n_pix_submap
        # accumulates
        # cannot use += due to duplicated indices
        np.add.at(zmap, (local_submap, isubpix), scaled_data * weights)

def build_noise_weighted_numpy(global2local, zmap, pixel_index, pixels, weight_index, weights, data_index, det_data, flag_index, det_flags, det_scale, det_flag_mask, intervals, shared_flags, shared_flag_mask, use_accel):
    """
    Args:
        global2local (array, int): size n_global_submap
        zmap (array, double): size n_local_submap*n_pix_submap*nnz
        pixel_index (array, int): size n_det
        pixels (array, int): size ???*n_samp
        weight_index (array, int): The indexes of the weights (size n_det)
        weights (array, double): The flat packed detectors weights for the specified mode (size ???*n_samp*nnz)
        data_index (array, int): size n_det
        det_data (array, double): size ???*n_samp
        flag_index (array, int): size n_det
        det_flags (array, uint8): size ???*n_samp or 1*1
        det_scale (array, double): size n_det
        det_flag_mask (uint8)
        intervals (array, Interval): The intervals to modify (size n_view)
        shared_flags (array, uint8): size n_samp
        shared_flag_mask (uint8)
        use_accel (Bool): should we use the accelerator?

    Returns:
        None (the result is put in zmap).
    """
    # problem size
    n_det = data_index.size
    n_samp = pixels.shape[1]
    (n_local_submap,n_pix_submap,nnz) = zmap.shape
    print(f"DEBUG: running 'build_noise_weighted_numpy' with n_view:{intervals.size} n_det:{n_det} n_samp:{n_samp} n_local_submap:{n_local_submap} n_pix_submap:{n_pix_submap} nnz:{nnz} det_flag_mask:{det_flag_mask} shared_flag_mask:{shared_flag_mask}")

    # should we use flags?
    use_det_flags = (det_flags.shape[1] == n_samp)
    use_shared_flags = (shared_flags.size == n_samp)

    # iterates on detectors and intervals
    for idet in range(n_det):
        for interval in intervals:
            interval_start = interval['first']
            interval_end = interval['last']
            for isamp in range(interval_start,interval_end+1):
                p_index = pixel_index[idet]
                w_index = weight_index[idet]
                f_index = flag_index[idet]
                d_index = data_index[idet]
                build_noise_weighted_inner_numpy(
                    global2local,
                    det_data[d_index,isamp],
                    det_flags[f_index,isamp] if use_det_flags else None,
                    shared_flags[isamp] if use_shared_flags else None,
                    pixels[p_index,isamp],
                    weights[w_index,isamp,:],
                    det_scale[idet],
                    zmap,
                    det_flag_mask,
                    shared_flag_mask)

#-------------------------------------------------------------------------------------------------
# C++

"""
void build_noise_weighted_inner(
    int32_t const * pixel_index,
    int32_t const * weight_index,
    int32_t const * flag_index,
    int32_t const * data_index,
    int64_t const * global2local,
    double const * data,
    uint8_t const * det_flags,
    uint8_t const * shared_flags,
    int64_t const * pixels,
    double const * weights,
    double const * det_scale,
    double * zmap_val,
    int64_t * zoff,
    int64_t isamp,
    int64_t n_samp,
    int64_t idet,
    int64_t nnz,
    uint8_t det_mask,
    uint8_t shared_mask,
    int64_t n_pix_submap,
    bool use_shared_flags,
    bool use_det_flags) 
{
    int32_t w_indx = weight_index[idet];
    int32_t p_indx = pixel_index[idet];
    int32_t f_indx = flag_index[idet];
    int32_t d_indx = data_index[idet];

    int64_t off_p = p_indx * n_samp + isamp;
    int64_t off_w = w_indx * n_samp + isamp;
    int64_t off_d = d_indx * n_samp + isamp;
    int64_t off_f = f_indx * n_samp + isamp;
    int64_t isubpix;
    int64_t off_wt;
    double scaled_data;
    int64_t local_submap;
    int64_t global_submap;

    uint8_t det_check = 0;
    if (use_det_flags) 
    {
        det_check = det_flags[off_f] & det_mask;
    }
    uint8_t shared_check = 0;
    if (use_shared_flags) 
    {
        shared_check = shared_flags[isamp] & shared_mask;
    }

    if (
        (pixels[off_p] >= 0) &&
        (det_check == 0) &&
        (shared_check == 0)
    ) 
    {
        // Good data, accumulate
        global_submap = (int64_t)(pixels[off_p] / n_pix_submap);

        local_submap = global2local[global_submap];

        isubpix = pixels[off_p] - global_submap * n_pix_submap;
        (*zoff) = nnz * (local_submap * n_pix_submap + isubpix);

        off_wt = nnz * off_w;

        scaled_data = data[off_d] * det_scale[idet];

        for (int64_t iweight = 0; iweight < nnz; iweight++) 
        {
            zmap_val[iweight] = scaled_data * weights[off_wt + iweight];
        }
    } 
    else 
    {
        (*zoff) = -1;
        for (int64_t iweight = 0; iweight < nnz; iweight++) 
        {
            zmap_val[iweight] = 0.0;
        }
    }
}

void build_noise_weighted(
    py::buffer global2local,
    py::buffer zmap,
    py::buffer pixel_index,
    py::buffer pixels,
    py::buffer weight_index,
    py::buffer weights,
    py::buffer data_index,
    py::buffer det_data,
    py::buffer flag_index,
    py::buffer det_flags,
    py::buffer det_scale,
    uint8_t det_flag_mask,
    py::buffer intervals,
    py::buffer shared_flags,
    uint8_t shared_flag_mask,
    bool use_accel
) 
{
    // This is used to return the actual shape of each buffer
    std::vector <int64_t> temp_shape(3);

    int32_t * raw_pixel_index = extract_buffer <int32_t> (pixel_index, "pixel_index", 1, temp_shape, {-1});
    int64_t n_det = temp_shape[0];

    int64_t * raw_pixels = extract_buffer <int64_t> (pixels, "pixels", 2, temp_shape, {-1, -1});
    int64_t n_samp = temp_shape[1];

    int32_t * raw_weight_index = extract_buffer <int32_t> (weight_index, "weight_index", 1, temp_shape, {n_det});

    double * raw_weights = extract_buffer <double> (weights, "weights", 3, temp_shape, {-1, n_samp, -1});
    int64_t nnz = temp_shape[2];

    int32_t * raw_data_index = extract_buffer <int32_t> (data_index, "data_index", 1, temp_shape, {n_det});
    double * raw_det_data = extract_buffer <double> (det_data, "det_data", 2, temp_shape, {-1, n_samp});
    int32_t * raw_flag_index = extract_buffer <int32_t> (flag_index, "flag_index", 1, temp_shape, {n_det});

    double * raw_det_scale = extract_buffer <double> (det_scale, "det_scale", 1, temp_shape, {n_det});

    Interval * raw_intervals = extract_buffer <Interval> (intervals, "intervals", 1, temp_shape, {-1});
    int64_t n_view = temp_shape[0];

    int64_t * raw_global2local = extract_buffer <int64_t> (global2local, "global2local", 1, temp_shape, {-1});
    int64_t n_global_submap = temp_shape[0];

    // int64_t n_zmap = n_local_submap * n_pix_submap * nnz;
    double * raw_zmap = extract_buffer <double> (zmap, "zmap", 3, temp_shape, {-1, -1, nnz});
    int64_t n_local_submap = temp_shape[0];
    int64_t n_pix_submap = temp_shape[1];

    // Optionally use flags
    bool use_shared_flags = true;
    uint8_t * raw_shared_flags = extract_buffer <uint8_t> (shared_flags, "flags", 1, temp_shape, {-1});
    if (temp_shape[0] != n_samp) 
    {
        raw_shared_flags = (uint8_t *)omgr.null;
        use_shared_flags = false;
    }

    bool use_det_flags = true;
    uint8_t * raw_det_flags = extract_buffer <uint8_t> (det_flags, "det_flags", 2, temp_shape, {-1, -1});
    if (temp_shape[1] != n_samp) 
    {
        raw_det_flags = (uint8_t *)omgr.null;
        use_det_flags = false;
    }

    for (int64_t idet = 0; idet < n_det; idet++) 
    {
        for (int64_t iview = 0; iview < n_view; iview++) 
        {
            #pragma omp parallel for default(shared)
            for (int64_t isamp = raw_intervals[iview].first; isamp <= raw_intervals[iview].last; isamp++) 
            {
                double zmap_val[nnz];
                int64_t zoff;
                build_noise_weighted_inner(
                    raw_pixel_index,
                    raw_weight_index,
                    raw_flag_index,
                    raw_data_index,
                    raw_global2local,
                    raw_det_data,
                    raw_det_flags,
                    raw_shared_flags,
                    raw_pixels,
                    raw_weights,
                    raw_det_scale,
                    zmap_val,
                    &zoff,
                    isamp,
                    n_samp,
                    idet,
                    nnz,
                    det_flag_mask,
                    shared_flag_mask,
                    n_pix_submap,
                    use_shared_flags,
                    use_det_flags
                );

                #pragma omp critical
                {
                    for (int64_t iw = 0; iw < nnz; iw++) 
                    {
                        raw_zmap[zoff + iw] += zmap_val[iw];
                    }
                }
            }
        }
    }
}
"""

#-------------------------------------------------------------------------------------------------
# IMPLEMENTATION SWITCH

# lets us play with the various implementations
build_noise_weighted = select_implementation(build_noise_weighted_compiled, 
                                             build_noise_weighted_numpy, 
                                             build_noise_weighted_jax)

# To test:
# python -c 'import toast.tests; toast.tests.run("ops_sim_tod_conviqt", "ops_mapmaker_utils", "ops_mapmaker_binning", "ops_sim_tod_dipole", "ops_demodulate");'

# to bench:
# use scanmap config and check BuildNoiseWeighted field in timing.csv
# one problem: this includes call to other operators
