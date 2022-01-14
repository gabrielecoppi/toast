
# enable 64bits precision
from jax.config import config as jax_config
jax_config.update("jax_enable_x64", True)

# JAX utilities function that might be called from other parts of the code
from .utils import set_JAX_device

# operators that have been ported to JAX
from .polyfilter1D import filter_polynomial
from .polyfilter2D import filter_poly2D
from .scan_map import scan_map

# dummy call to warm-up the jit for further JAX compilations
# NOTE: we could remove this, it makes a 1 or 2s difference to the full runtime
import numpy as np
from .polyfilter1D import filter_polynomial_interval as jit_warmup_function
dummy_order = 1
dummy_scanlen = 2
dummy_nsignal = 1
dummy_flags = np.zeros(shape=(dummy_scanlen,))
dummy_interval = np.zeros(shape=(dummy_scanlen,dummy_nsignal))
jit_warmup_function(dummy_flags, dummy_interval, dummy_order)