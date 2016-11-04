import multiprocessing as mp
from itertools import count
from contextlib import closing
import sys
from functools import partial
import ctypes
from operator import mul

import numpy as np
import mdtraj as md


def sound_trajectory(trj, top):
    '''
    Determine the length of a trajectory on disk in log(n) time and
    constant space by loading individual frames from disk at
    exponentially increasing indices.
    '''
    search_space = [0, sys.maxsize]
    base = 2

    while search_space[0]+1 != search_space[1]:
        start = search_space[0]
        for iteration in count():
            frame = start+(base**iteration)

            try:
                md.load(trj, top=top, frame=frame)
                search_space[0] = frame
            except IndexError:
                search_space[1] = frame
                break

    return search_space[1]


def load_as_concatenated(filenames, topology, processes=None, debug=False):
    '''
    Load the given files from disk into a single numpy array. Returns a
    tuple of trajectory lengths and xyz
    '''
    lengths = [sound_trajectory(f, topology) for f in filenames]

    root_trj = md.load(filenames[0], top=topology, frame=0)
    shape = root_trj.xyz.shape

    # TODO: check all inputs against root

    full_shape = (sum(lengths), shape[1], shape[2])
    # mp.Arrays are one-dimensional, so multiply the shape together for size
    shared_array = mp.Array(ctypes.c_double, reduce(mul, full_shape, 1))

    proc_list = []
    with closing(mp.Pool(processes=processes, initializer=init,
                         initargs=(shared_array,))) as p:
        proc_list.append(p.map_async(
            partial(load_to_position, top=topology, arr_shape=full_shape),
            zip([sum(lengths[0:i]) for i in range(len(lengths))],
                filenames)
            ))

    # gather exceptions.
    [x.get() for x in proc_list]
    p.join()

    xyz = tonumpyarray(shared_array).reshape(full_shape)

    return lengths, xyz


def init(shared_array_):
    # for some reason, the shared array must be inhereted, not passed
    # as an argument
    global shared_array
    shared_array = shared_array_


def tonumpyarray(mp_arr):
    return np.frombuffer(mp_arr.get_obj())


def load_to_position(spec, top, arr_shape):
    '''
    Load a specified file into a specified position by spec, using the
    topology top. The arr_shape parameter lets us know how big the final
    array should be.
    '''
    (position, filename) = spec

    xyz = md.load(filename, top=top).xyz

    # mp.Array must be converted to numpy array and reshaped
    arr = tonumpyarray(shared_array).reshape(arr_shape)

    # dump coordinates in.
    arr[position:position+len(xyz)] = xyz