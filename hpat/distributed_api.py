import numpy as np
import numba
from numba import types
from numba.typing.templates import infer_global, AbstractTemplate, infer
from numba.typing import signature
from numba.extending import models, register_model, intrinsic, overload
import hpat
import time
from llvmlite import ir as lir
import hdist
import llvmlite.binding as ll
ll.add_symbol('c_alltoall', hdist.c_alltoall)
ll.add_symbol('c_gather_scalar', hdist.c_gather_scalar)
ll.add_symbol('c_gatherv', hdist.c_gatherv)

from enum import Enum

# get size dynamically from C code (mpich 3.2 is 4 bytes but openmpi 1.6 is 8)
import hdist
mpi_req_numba_type = getattr(types, "int"+str(8 * hdist.mpi_req_num_bytes))

MPI_ROOT = 0

class Reduce_Type(Enum):
    Sum = 0
    Prod = 1
    Min = 2
    Max = 3
    Argmin = 4
    Argmax = 5

_h5_typ_table = {
    types.int8: 0,
    types.uint8: 1,
    types.int32: 2,
    types.int64: 3,
    types.float32: 4,
    types.float64: 5,
    types.uint64: 6
}

def get_type_enum(arr):
    return np.int32(-1)

@overload(get_type_enum)
def get_type_enum_overload(arr_typ):
    typ_val = _h5_typ_table[arr_typ.dtype]
    return lambda a: np.int32(typ_val)

INT_MAX = np.iinfo(np.int32).max
_alltoall = types.ExternalFunction("c_alltoall", types.void(types.voidptr, types.voidptr, types.int32, types.int32))

@numba.njit
def alltoall(send_arr, recv_arr, count):
    # TODO: handle int64 counts
    assert count < INT_MAX
    type_enum = get_type_enum(send_arr)
    _alltoall(send_arr.ctypes, recv_arr.ctypes, np.int32(count), type_enum)

def gather_scalar(data):  # pragma: no cover
    return np.ones(1)

c_gather_scalar = types.ExternalFunction("c_gather_scalar", types.void(types.voidptr, types.voidptr, types.int32))

# TODO: test
@overload(gather_scalar)
def gather_scalar_overload(data_t):
    assert isinstance(data_t, (types.Integer, types.Float))
    # TODO: other types like boolean
    typ_val = _h5_typ_table[data_t]
    func_text = (
    "def gather_scalar_impl(val):\n"
    "  n_pes = hpat.distributed_api.get_size()\n"
    "  rank = hpat.distributed_api.get_rank()\n"
    "  send = np.full(1, val, np.{})\n"
    "  res_size = n_pes if rank == {} else 0\n"
    "  res = np.empty(res_size, np.{})\n"
    "  c_gather_scalar(send.ctypes, res.ctypes, np.int32({}))\n"
    "  return res\n").format(data_t, MPI_ROOT, data_t, typ_val)

    loc_vars = {}
    exec(func_text, {'hpat': hpat, 'np': np, 'c_gather_scalar': c_gather_scalar}, loc_vars)
    gather_impl = loc_vars['gather_scalar_impl']
    return gather_impl

# TODO: test
def gatherv(data):  # pragma: no cover
    return data

# sendbuf, sendcount, recvbuf, recv_counts, displs, dtype
c_gatherv = types.ExternalFunction("c_gatherv",
    types.void(types.voidptr, types.int32, types.voidptr, types.voidptr, types.voidptr, types.int32))

@overload(gatherv)
def gatherv_overload(data_t):
    assert isinstance(data_t, types.Array)
    # TODO: other types like boolean
    typ_val = _h5_typ_table[data_t.dtype]
    func_text = (
    "def gatherv_impl(data):\n"
    "  n_pes = hpat.distributed_api.get_size()\n"
    "  rank = hpat.distributed_api.get_rank()\n"
    "  n_loc = len(data)\n"
    "  recv_counts = gather_scalar(np.int32(n_loc))\n"
    "  n_total = recv_counts.sum()\n"
    "  all_data = np.empty(n_total, np.{})\n"
    # displacements
    "  displs = np.empty(n_pes, np.int32)\n"
    "  cur_ind = np.int32(0)\n"
    "  if rank == {}:\n"
    "    for i in range(n_pes):\n"
    "      displs[i] = cur_ind\n"
    "      cur_ind += recv_counts[i]\n"
    #"  print(rank, n_loc, n_total, recv_counts, displs)\n"
    "  c_gatherv(data.ctypes, np.int32(n_loc), all_data.ctypes, recv_counts.ctypes, displs.ctypes, np.int32({}))\n"
    "  return all_data\n").format(data_t.dtype, MPI_ROOT, typ_val)

    loc_vars = {}
    exec(func_text, {'hpat': hpat, 'np': np, 'c_gatherv': c_gatherv, 'gather_scalar': gather_scalar}, loc_vars)
    gatherv_impl = loc_vars['gatherv_impl']
    return gatherv_impl



def get_rank():  # pragma: no cover
    """dummy function for C mpi get_rank"""
    return 0


def barrier():  # pragma: no cover
    return 0


def get_size():  # pragma: no cover
    """dummy function for C mpi get_size"""
    return 0


def get_start(total_size, pes, rank):  # pragma: no cover
    """get end point of range for parfor division"""
    return 0


def get_end(total_size, pes, rank):  # pragma: no cover
    """get end point of range for parfor division"""
    return 0


def get_node_portion(total_size, pes, rank):  # pragma: no cover
    """get portion of size for alloc division"""
    return 0


def dist_reduce(value):  # pragma: no cover
    """dummy to implement simple reductions"""
    return value


def dist_arr_reduce(arr):  # pragma: no cover
    """dummy to implement array reductions"""
    return -1


def dist_cumsum(arr):  # pragma: no cover
    """dummy to implement cumsum"""
    return arr


def dist_cumprod(arr):  # pragma: no cover
    """dummy to implement cumprod"""
    return arr


def dist_exscan(value):  # pragma: no cover
    """dummy to implement simple exscan"""
    return value


def dist_setitem(arr, index, val):  # pragma: no cover
    return 0

def allgather(arr, val):  # pragma: no cover
    arr[0] = val

def dist_time():  # pragma: no cover
    return time.time()

def dist_return(A):  # pragma: no cover
    return A

def dist_input(A):  # pragma: no cover
    return A

def threaded_input(A):  # pragma: no cover
    return A

def threaded_return(A):  # pragma: no cover
    return A

def rebalance_array(A):
    return A

def rebalance_array_parallel(A):
    return A


@overload(rebalance_array)
@overload(dist_return)
@overload(dist_input)
@overload(threaded_input)
@overload(threaded_return)
def dist_return_overload(column):
    return dist_return

def irecv():  # pragma: no cover
    return 0


def isend():  # pragma: no cover
    return 0


def wait():  # pragma: no cover
    return 0

def waitall():  # pragma: no cover
    return 0

@infer_global(allgather)
class DistAllgather(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2  # array and val
        return signature(types.none, *args)

@infer_global(rebalance_array_parallel)
class DistRebalanceParallel(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2  # array and count
        return signature(args[0], *args)


@infer_global(get_rank)
class DistRank(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 0
        return signature(types.int32, *args)


@infer_global(get_size)
class DistSize(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 0
        return signature(types.int32, *args)


@infer_global(get_start)
class DistStart(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 3
        return signature(types.int64, *args)


@infer_global(get_end)
class DistEnd(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 3
        return signature(types.int64, *args)


@infer_global(get_node_portion)
class DistPortion(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 3
        return signature(types.int64, *args)


@infer_global(dist_reduce)
class DistReduce(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2  # value and reduce_op
        return signature(args[0], *args)


@infer_global(dist_exscan)
class DistExscan(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 1
        return signature(args[0], *args)


@infer_global(dist_arr_reduce)
class DistArrReduce(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2  # value and reduce_op
        return signature(types.int32, *args)


@infer_global(time.time)
class DistTime(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 0
        return signature(types.float64, *args)


@infer_global(dist_time)
class DistDistTime(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 0
        return signature(types.float64, *args)


@infer_global(barrier)
class DistBarrier(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 0
        return signature(types.int32, *args)


@infer_global(dist_cumsum)
@infer_global(dist_cumprod)
class DistCumsumprod(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2
        return signature(types.int32, *args)


@infer_global(irecv)
@infer_global(isend)
class DistIRecv(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) in [4, 5]
        return signature(mpi_req_numba_type, *args)


@infer_global(wait)
class DistWait(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2
        return signature(types.int32, *args)

@infer_global(waitall)
class DistWaitAll(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 2 and args == (types.int32, req_array_type)
        return signature(types.none, *args)

# @infer_global(dist_setitem)
# class DistSetitem(AbstractTemplate):
#     def generic(self, args, kws):
#         assert not kws
#         assert len(args)==5
#         return signature(types.int32, *args)


class ReqArrayType(types.Type):
    def __init__(self):
        super(ReqArrayType, self).__init__(
            name='ReqArrayType()')

req_array_type = ReqArrayType()
register_model(ReqArrayType)(models.OpaqueModel)

def comm_req_alloc():
    return 0

def comm_req_dealloc():
    return 0

@infer_global(comm_req_alloc)
class DistCommReqAlloc(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 1 and args[0] == types.int32
        return signature(req_array_type, *args)

@infer_global(comm_req_dealloc)
class DistCommReqDeAlloc(AbstractTemplate):
    def generic(self, args, kws):
        assert not kws
        assert len(args) == 1 and args[0] == req_array_type
        return signature(types.none, *args)

@infer
class SetItemReqArray(AbstractTemplate):
    key = "setitem"

    def generic(self, args, kws):
        assert not kws
        [ary, idx, val] = args
        if isinstance(ary, ReqArrayType) and idx == types.intp and val == mpi_req_numba_type:
            return signature(types.none, *args)
