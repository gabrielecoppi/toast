import jax

# the device used by JAX on this process
jax_local_device = None
"""
    The device that JAX operators should be using
    Use the function `set_JAX_device` to set this value (this should be done during MPI initialization)
    Use like this in your JAX code: `jax.device_put(data, device=jax_local_device)`
    Or set globally with: `jax.config.update("jax_default_device", jax_local_device)`
"""

def jax_accel_assign_device(node_procs, node_rank, disabled):
    """
    Assign processes to target devices.
    
    Args:
        node_procs (int): number of processes per node
        node_rank (int): rank of the current process, within the node
        disabled (bool): gpu computing is disabled

    Returns:
        None: the device is stored in a backend specific global variable
    """
    # list of GPUs / CPUs available
    devices_available = jax.devices()
    # gets id of device to be used by this process
    nb_devices = len(devices_available)
    device_id = 0 if disabled else (node_rank % nb_devices)
    # sets the device in a local variable and globaly
    global jax_local_device
    jax_local_device = devices_available[device_id]
    jax.config.update("jax_default_device", jax_local_device)
    # TODO convert this print to a log verbose
    print(f"DEBUGGING: JAX rank {node_rank}/{node_procs} uses device number {device_id}/{nb_devices} ({jax_local_device})")

def jax_accel_get_device():
    """Returns the device currenlty used by JAX or errors out."""
    if jax_local_device is None:
        raise RuntimeError("Jax device is not set, please insure that you have called 'accel_assign_device'")
    return jax_local_device