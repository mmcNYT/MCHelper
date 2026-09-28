// _jigsaw_prims.cpp - RNG/rotation primitives (M1, parity-tested vs Python).
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <cstdint>

static constexpr uint64_t MASK64 = 0xFFFFFFFFFFFFFFFFULL;
static constexpr uint64_t MASK48 = (1ULL << 48) - 1ULL;
static constexpr uint64_t MULT = 25214903917ULL;
static constexpr uint64_t ADD = 11ULL;
static inline uint64_t u64(int64_t v){ return (uint64_t)v; }
static inline int64_t s64(uint64_t v){ return (v & 0x8000000000000000ULL) ? (int64_t)(v-(1ULL<<63))-(int64_t)(1ULL<<63) : (int64_t)v; }
static inline int64_t jint(int64_t v){ return (int64_t)(int32_t)((uint32_t)(uint64_t)v & 0xFFFFFFFFULL); }
static inline uint64_t us32(int32_t v){ return (uint64_t)(int64_t)v & MASK64; }

struct Rng {
    uint64_t st;
    void set_seed(int64_t s){ st = (u64(s) ^ MULT) & MASK48; }
    uint64_t next_bits(int b){ st = (st*MULT + ADD) & MASK48; return st >> (48-b); }
    int64_t next_long(){ int64_t h=jint((int64_t)next_bits(32)); int64_t l=jint((int64_t)next_bits(32)); return (h<<32)+l; }
    int64_t next_int(int64_t bound){
        int64_t r = (int64_t)next_bits(31);
        if ((bound & (bound-1)) == 0){ uint64_t p=(uint64_t)bound*(uint64_t)r; return (int64_t)(p>>31); }
        while (true){ int64_t val=r%bound; int64_t t=r-val+bound-1; if (t>0x7FFFFFFFLL){ r=(int64_t)next_bits(31); continue; } return val; }
    }
};
static void seed_layout(Rng& r, int64_t lv, int64_t cx, int64_t cz){
    r.set_seed(lv);
    uint64_t l1=u64(r.next_long()), l2=u64(r.next_long());
    uint64_t v = (us32((int32_t)jint(cx))*l1) ^ (us32((int32_t)jint(cz))*l2) ^ u64(lv);
    r.set_seed(s64(v & MASK64));
}

static const int kDV[6][3] = {{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}};
static int rot_dir(int rot,int d){
    if (rot==0) return d;
    int x=kDV[d][0], y=kDV[d][1], z=kDV[d][2], nx,ny,nz;
    if (rot==1){ nx=-z; ny=y; nz=x; } else if (rot==2){ nx=-x; ny=y; nz=-z; } else { nx=z; ny=y; nz=-x; }
    if (nx==0&&nz==-1) return 2; if (nx==0&&nz==1) return 3;
    if (nx==-1&&nz==0) return 4; if (nx==1&&nz==0) return 5;
    return d;
}
static void rot_pos(int rot,int x,int y,int z,int sx,int sz,int&ox,int&oy,int&oz){
    if (rot==0){ ox=x; oy=y; oz=z; }
    else if (rot==1){ ox=sz-1-z; oy=y; oz=x; }
    else if (rot==2){ ox=sx-1-x; oy=y; oz=sz-1-z; }
    else { ox=z; oy=y; oz=sx-1-x; }
}
static void rot_size(int rot,int sx,int sy,int sz,int&ox,int&oy,int&oz){
    if (rot==1||rot==3){ ox=sz; oy=sy; oz=sx; } else { ox=sx; oy=sy; oz=sz; }
}

static PyObject* py_next(PyObject*, PyObject* args){
    long long seed, cx, cz, bound; long count;
    if (!PyArg_ParseTuple(args, "LLLLl", &seed,&cx,&cz,&bound,&count)) return NULL;
    Rng r; seed_layout(r, seed, cx, cz);
    PyObject* out = PyList_New(count);
    for (long i=0;i<count;++i) PyList_SET_ITEM(out, i, PyLong_FromLongLong(r.next_int(bound)));
    return out;
}
static PyObject* py_rot_pos(PyObject*, PyObject* args){
    int rot,x,y,z,sx,sz;
    if (!PyArg_ParseTuple(args,"iiiiii",&rot,&x,&y,&z,&sx,&sz)) return NULL;
    int ox,oy,oz; rot_pos(rot,x,y,z,sx,sz,ox,oy,oz);
    return Py_BuildValue("(iii)",ox,oy,oz);
}
static PyObject* py_rot_dir(PyObject*, PyObject* args){
    int rot,d; if (!PyArg_ParseTuple(args,"ii",&rot,&d)) return NULL;
    return PyLong_FromLong(rot_dir(rot,d));
}
static PyObject* py_rot_size(PyObject*, PyObject* args){
    int rot,sx,sy,sz; if (!PyArg_ParseTuple(args,"iiii",&rot,&sx,&sy,&sz)) return NULL;
    int ox,oy,oz; rot_size(rot,sx,sy,sz,ox,oy,oz);
    return Py_BuildValue("(iii)",ox,oy,oz);
}

static PyMethodDef methods[] = {
    {"next_seq", py_next, METH_VARARGS, "layout RNG next_int sequence"},
    {"rot_pos", py_rot_pos, METH_VARARGS, "rotate piece pos"},
    {"rot_dir", py_rot_dir, METH_VARARGS, "rotate dir"},
    {"rot_size", py_rot_size, METH_VARARGS, "rotate size"},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef mod = { PyModuleDef_HEAD_INIT, "_jigsaw_prims", "", -1, methods };
PyMODINIT_FUNC PyInit__jigsaw_prims(void){ return PyModule_Create(&mod); }