// _jigsaw_engine.cpp - Minecraft 1.21 jigsaw placement engine (C++ port).
// Mirrors Utils/SeedReverser/jigsaw_assembly.py + mc_rng.py byte-for-byte.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// ---------------- 64-bit wraparound helpers ----------------
static constexpr uint64_t MASK64 = 0xFFFFFFFFFFFFFFFFULL;
static constexpr uint64_t MASK48 = (1ULL << 48) - 1ULL;
static constexpr uint64_t MULT = 25214903917ULL;
static constexpr uint64_t ADD = 11ULL;
static inline uint64_t u64(int64_t v){ return (uint64_t)v; }
static inline int64_t s64(uint64_t v){
    return (v & 0x8000000000000000ULL)
        ? (int64_t)(v-(1ULL<<63))-(int64_t)(1ULL<<63) : (int64_t)v;
}
static inline int64_t jint(int64_t v){
    return (int64_t)(int32_t)((uint32_t)(uint64_t)v & 0xFFFFFFFFULL);
}
static inline uint64_t us32(int32_t v){ return (uint64_t)(int64_t)v & MASK64; }

// ---- debug RNG trace (enabled via _trace_on) ----
static bool g_trace=false;
static std::vector<std::string> g_events;
static void ev(const std::string& s){ if(g_trace) g_events.push_back(s); }
static std::string rot_name(int r){ return r==0?"NONE":(r==1?"CLOCKWISE_90":(r==2?"CLOCKWISE_180":"COUNTERCLOCKWISE_90")); }

// ---------------- Java 48-bit LCG RNG ----------------
struct Rng {
    uint64_t st;
    void set_seed(int64_t s){ st = (u64(s) ^ MULT) & MASK48; }
    uint64_t next_bits(int b){ st = (st*MULT + ADD) & MASK48; return st >> (48-b); }
    int64_t next_long(){
        int64_t h=jint((int64_t)next_bits(32));
        int64_t l=jint((int64_t)next_bits(32));
        return (h<<32)+l;
    }
int64_t next_int(int64_t bound){
        int64_t r=(int64_t)next_bits(31);
        if ((bound&(bound-1))==0){ uint64_t p=(uint64_t)bound*(uint64_t)r; return (int64_t)(p>>31); }
        while (true){ int64_t val=r%bound; int64_t t=r-val+bound-1; if(t>0x7FFFFFFFLL){ r=(int64_t)next_bits(31); continue; } return val; }
    }
};
static void seed_layout(Rng& r,int64_t lv,int64_t cx,int64_t cz){
    r.set_seed(lv);
    uint64_t l1=u64(r.next_long()), l2=u64(r.next_long());
    uint64_t v = (us32((int32_t)jint(cx))*l1) ^ (us32((int32_t)jint(cz))*l2) ^ u64(lv);
    r.set_seed(s64(v & MASK64));
}
template<class T> static void shuffle_list(Rng& r, std::vector<T>& o){
    size_t i=o.size();
    while (i>1){ size_t j=(size_t)r.next_int((int64_t)i); std::swap(o[i-1],o[j]); i--; }
}

// ---------------- directions & rotation ----------------
static const int kOpp[6] = {1,0,3,2,5,4};
static const int kDV[6][3] = {{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}};
static int rot_dir(int rot,int d){
    if (rot==0) return d;
    int x=kDV[d][0], y=kDV[d][1], z=kDV[d][2], nx,ny,nz;
    if (rot==1){ nx=-z; ny=y; nz=x; }
    else if (rot==2){ nx=-x; ny=y; nz=-z; }
    else { nx=z; ny=y; nz=-x; }
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

// ---------------- geometry ----------------
struct Box { int64_t x0,y0,z0,x1,y1,z1; };
static Box moved(const Box& b,int64_t dx,int64_t dy,int64_t dz){
    return {b.x0+dx,b.y0+dy,b.z0+dz,b.x1+dx,b.y1+dy,b.z1+dz};
}
static Box box_pos(int64_t px,int64_t py,int64_t pz,int64_t sx,int64_t sy,int64_t sz){
    return {px,py,pz,px+sx-1,py+sy-1,pz+sz-1};
}
static bool contains(const Box& b,int64_t x,int64_t y,int64_t z){
    return b.x0<=x&&x<=b.x1 && b.y0<=y&&y<=b.y1 && b.z0<=z&&z<=b.z1;
}
static bool child_in(const Box& c,const Box& r){
    return r.x0<=c.x0&&c.x1<=r.x1 && r.y0<=c.y0&&c.y1<=r.y1 && r.z0<=c.z0&&c.z1<=r.z1;
}
static bool share_cell(const Box& a,const Box& b){
    return a.x0<=b.x1&&b.x0<=a.x1 && a.y0<=b.y1&&b.y0<=a.y1 && a.z0<=b.z1&&b.z0<=a.z1;
}
static Box encap(const std::vector<Box>& bs){
    Box r=bs[0];
    for (size_t i=1;i<bs.size();++i){
        r.x0=std::min(r.x0,bs[i].x0); r.y0=std::min(r.y0,bs[i].y0); r.z0=std::min(r.z0,bs[i].z0);
        r.x1=std::max(r.x1,bs[i].x1); r.y1=std::max(r.y1,bs[i].y1); r.z1=std::max(r.z1,bs[i].z1);
    }
    return r;
}
struct Domain {
    Box bounds;
    std::vector<Box> holes;
    Domain() {}
    Domain(const Box& b):bounds(b) {}
    bool rejects(const Box& c){
        if (!child_in(c,bounds)) return true;
        for (auto& h:holes) if (share_cell(c,h)) return true;
        return false;
    }
};

// ---------------- data models ----------------
struct Marker { int64_t x,y,z; int front,top,joint; std::string name,target,pool; int64_t pri; };
struct Template {
    std::string key; int64_t sx,sy,sz; std::vector<Marker> markers;
    void markers_at(int rot,std::vector<Marker>& o) const {
        o.clear();
        for (auto& m:markers){
            Marker mm=m; int ax,ay,az;
            rot_pos(rot,(int)m.x,(int)m.y,(int)m.z,(int)sx,(int)sz,ax,ay,az);
            mm.x=ax; mm.y=ay; mm.z=az; mm.front=rot_dir(rot,m.front); mm.top=rot_dir(rot,m.top);
            o.push_back(mm);
        }
    }
    Box bounding(int64_t px,int64_t py,int64_t pz,int rot) const {
        int x,y,z; rot_size(rot,(int)sx,(int)sy,(int)sz,x,y,z);
        return box_pos(px,py,pz,x,y,z);
    }
};
struct Elem {
    std::string location,etype,projection,processors;
    int64_t weight; bool is_list;
    std::vector<std::string> sub_locations, sub_processors;
};
struct Pool { std::string id; std::vector<Elem> elements; std::string fallback; };
struct Ctx {
    std::vector<Template> templates; std::vector<Pool> pools;
    std::unordered_map<std::string,size_t> ti, pi;
    const Template* tpl(const std::string& k){
        auto it=ti.find(k); return it==ti.end()?nullptr:&templates[it->second];
    }
    const Pool* pool(const std::string& k){
        auto it=pi.find(k); return it==pi.end()?nullptr:&pools[it->second];
    }
};
static std::string strip(const std::string& s){
    auto p=s.find(':'); return p==std::string::npos?s:s.substr(p+1);
}
static bool endswith(const std::string& s,const char* suf){
    size_t n=strlen(suf), l=s.size(); return l>=n && s.compare(l-n,n,suf)==0;
}
static int default_joint(int f){ return (f==0||f==1)?0:1; } // up/down aligned else rollable

// ---------------- engine ----------------
struct Piece {
    const Template* t; int rot;
    int64_t px,py,pz; Box box; int depth; std::string proj;
    std::vector<std::string> sub_ls, sub_pr; std::string proc;
    std::vector<Marker> wm; bool wm_ok=false;
    const std::vector<Marker>& world_markers(){
        if (!wm_ok){
            wm.clear();
            std::vector<Marker> b; t->markers_at(rot,b);
            for (auto& m:b){ Marker mm=m; mm.x+=px; mm.y+=py; mm.z+=pz; wm.push_back(mm); }
            wm_ok=true;
        }
        return wm;
    }
};
struct WorkItem { int64_t pri; size_t seq; Piece* p; Domain* d; };

struct Engine {
    Ctx* ctx; Rng rng; int max_depth; bool expansion; size_t seq_ctr=0;

    bool connects(const Marker& pa,const Marker& ch){
        int pj = pa.joint<0 ? default_joint(pa.front) : pa.joint;
        if (pa.front != kOpp[ch.front]) return false;
        if (!(pj==1 || pa.top==ch.top)) return false;
        return strip(pa.target)==strip(ch.name);
    }
    void child_markers(const Template* t,int rot,std::vector<Marker>& o){
        t->markers_at(rot,o);
        if (o.size()>1){ ev("marker_shuffle(M="+std::to_string(o.size())+")"); shuffle_list(rng,o); }
        std::stable_sort(o.begin(),o.end(),[](const Marker&a,const Marker&b){return a.pri>b.pri;});
    }
    void parent_markers(Piece* p,std::vector<Marker>& o){
        o = p->world_markers();
        if (o.size()>1){ ev("parent_marker_shuffle(M="+std::to_string(o.size())+")"); shuffle_list(rng,o); }
        std::stable_sort(o.begin(),o.end(),[](const Marker&a,const Marker&b){return a.pri>b.pri;});
    }
    void candidate_box(const Elem* e,int rot,std::string& loc,Box& b){
        if (e->is_list){
            std::vector<Box> bs;
            for (auto& k:e->sub_locations){ const Template* t=ctx->tpl(k); bs.push_back(t->bounding(0,0,0,rot)); }
            b=encap(bs); loc = e->sub_locations.empty()?e->location:e->sub_locations[0];
        } else {
            const Template* t=ctx->tpl(e->location); b=t->bounding(0,0,0,rot); loc=e->location;
        }
    }
    std::string cand_proj(const Elem* e){ return e->projection.empty()?"rigid":e->projection; }
    int pool_max_yspan(const Pool* p){
        int best=0; if(!p) return best;
        for (auto& e:p->elements){
            if (endswith(e.etype,"empty_pool_element")) continue;
            if (e.is_list){ for(auto& k:e.sub_locations){ const Template*t=ctx->tpl(k); if(t) best=std::max(best,(int)t->sy);} }
            else if (!e.location.empty()){ const Template* t=ctx->tpl(e.location); if(t) best=std::max(best,(int)t->sy); }
        }
        return best;
    }
    std::vector<Elem*> expanded(const Pool* p){
        std::vector<Elem*> o;
        for (auto& e:p->elements) for (int64_t i=0;i<e.weight;++i) o.push_back(const_cast<Elem*>(&e));
        return o;
    }
void try_place(Piece* piece,Domain* domain,std::vector<WorkItem>& wq,std::vector<Piece*>& pieces){
        Domain* priv=nullptr;
        int64_t pmy=piece->box.y0;
        bool rp = piece->proj=="rigid";
        std::vector<Marker> pm; parent_markers(piece,pm);
        for (auto& pmark:pm){
            int64_t tpx=pmark.x+kDV[pmark.front][0], tpy=pmark.y+kDV[pmark.front][1], tpz=pmark.z+kDV[pmark.front][2];
            int64_t mry=pmark.y-pmy, sy=kDV[pmark.front][1];
            Domain* du;
            if (contains(piece->box,tpx,tpy,tpz)){ if(!priv) priv=new Domain(piece->box); du=priv; } else du=domain;
            std::string pid=strip(pmark.pool);
            if (pid.empty()||pid=="empty") continue;
            const Pool* pool=ctx->pool(pid); if(!pool) continue;
            std::string fb = pool->fallback.empty()?"":strip(pool->fallback); if(fb.empty()) continue;
            std::vector<Elem*> cands;
            if (piece->depth!=max_depth){ ev("main_shuffle(pool="+pid+")"); cands=expanded(pool); shuffle_list(rng,cands); }
            const Pool* fbp=ctx->pool(fb);
            if (fbp){ ev("fallback_shuffle(pool="+fb+")"); auto v=expanded(fbp); shuffle_list(rng,v); cands.insert(cands.end(),v.begin(),v.end()); }
            for (auto* cand:cands){
                std::string ct=cand->etype;
                if (endswith(ct,"empty_pool_element")) break;
                if (endswith(ct,"feature_pool_element")){ ev("rotation_shuffled"); std::vector<int> r={0,1,2,3}; shuffle_list(rng,r); continue; }
                if (!(endswith(ct,"single_pool_element")||cand->is_list)) continue;
                ev("rotation_shuffled"); std::vector<int> rots={0,1,2,3}; shuffle_list(rng,rots);
                std::string tkey = cand->is_list?(cand->sub_locations.empty()?cand->location:cand->sub_locations[0]):cand->location;
                const Template* ctpl=ctx->tpl(tkey); if(!ctpl) continue;
                for (int rot:rots){
                    std::vector<Marker> cmarks; child_markers(ctpl,rot,cmarks);
                    std::string cbl; Box cb; candidate_box(cand,rot,cbl,cb);
                    int64_t yspan=cb.y1-cb.y0, fys=0;
                    if (expansion && yspan<=16){
                        for (auto& cm0:cmarks){
                            int64_t x=cm0.x+kDV[cm0.front][0], y=cm0.y+kDV[cm0.front][1], z=cm0.z+kDV[cm0.front][2];
                            if (!contains(cb,x,y,z)) continue;
                            const Pool* cp=ctx->pool(strip(cm0.pool));
                            const Pool* f2 = cp?ctx->pool(strip(cp->fallback)):nullptr;
                            int64_t m1 = cp?pool_max_yspan(cp):0, m2=f2?pool_max_yspan(f2):0;
                            fys=std::max(fys,std::max(m1,m2));
                        }
                    }
                    for (auto& cm: cmarks){
                        if (!connects(pmark,cm)) continue;
                        int64_t cpx=tpx-cm.x, cpy=tpy-cm.y, cpz=tpz-cm.z;
                        Box bat=moved(cb,cpx,cpy,cpz); int64_t bmy=bat.y0;
                        std::string cpj=cand_proj(cand);                         bool rc=cpj=="rigid";
                        int64_t ml=cm.y, rel=mry-ml+sy;
                        int64_t ay = (rp&&rc)?(pmy+rel):(63-ml);
                        int64_t dy=ay-bmy;
                        Box chb=moved(bat,0,dy,0);
                        int64_t pp0=cpx, pp1=cpy+dy, pp2=cpz;
                        if (fys>0){
                            int64_t ym=chb.y1-chb.y0, ex=std::max(fys+1,ym);
                            chb=encap({chb,{chb.x0,chb.y0,chb.z0,chb.x1,chb.y0+ex,chb.z1}});
                        }
                        if (du->rejects(chb)) continue;
                        du->holes.push_back(chb);
                        Piece* np=new Piece{ctpl,rot,pp0,pp1,pp2,chb,piece->depth+1,cpj,
                            cand->is_list?cand->sub_locations:std::vector<std::string>(),
                            cand->is_list?cand->sub_processors:std::vector<std::string>(),
                            cand->processors,{},false};
                        pieces.push_back(np);
                        if (piece->depth+1<=max_depth) wq.push_back({pmark.pri,seq_ctr++,np,du});
                        ev("PLACED "+cbl+" rot="+rot_name(rot)+" pos=("+std::to_string(pp0)+", "+std::to_string(pp1)+", "+std::to_string(pp2)+") depth="+std::to_string(piece->depth+1));
                        break;
                    }
                }
            }
        }
    }
    void run(Piece* start,Domain* free,std::vector<Piece*>& pieces){
        pieces.push_back(start);
        std::vector<WorkItem> wq; seq_ctr=0; wq.push_back({0,seq_ctr++,start,free});
        while (!wq.empty()){
            size_t bi=0;
            for (size_t i=1;i<wq.size();++i)
                if (std::make_pair(wq[i].pri,wq[i].seq)<std::make_pair(wq[bi].pri,wq[bi].seq)) bi=i;
            WorkItem it=wq[bi]; wq.erase(wq.begin()+bi);
            try_place(it.p,it.d,wq,pieces);
        }
    }
};

// ---------------- marshalling helpers ----------------
static long long ll(PyObject* o){ return PyLong_AsLongLong(o); }
static int li(PyObject* o){ return (int)PyLong_AsLong(o); }
static std::string ss(PyObject* o){ return std::string(PyUnicode_AsUTF8(o)); }

// 模板内容跨调用完全固定（NBT 解析结果），按 key 全局缓存。
// 池内容随 alias 逐 chunk 变化，不可缓存（保持每次 parse）。
static std::unordered_map<std::string, Template> g_tpl_cache;

static int parse_templates(PyObject* list,Ctx& ctx){
    PyObject* seq=PySequence_Fast(list,"templates");
    if(!seq) return -1;
    for(Py_ssize_t i=0;i<PySequence_Fast_GET_SIZE(seq);++i){
        PyObject* item=PySequence_Fast(PySequence_Fast_GET_ITEM(seq,i),"tpl");
        std::string key=ss(PySequence_Fast_GET_ITEM(item,0));
        auto it=g_tpl_cache.find(key);
        if(it!=g_tpl_cache.end()){
            // 缓存命中：直接复用 struct（内容固定，跨调用安全）
            ctx.ti[key]=ctx.templates.size();
            ctx.templates.push_back(it->second);
            continue;
        }
        PyObject* size=PySequence_Fast(PySequence_Fast_GET_ITEM(item,1),"size");
        Template t; t.key=key; t.sx=ll(PySequence_Fast_GET_ITEM(size,0)); t.sy=ll(PySequence_Fast_GET_ITEM(size,1)); t.sz=ll(PySequence_Fast_GET_ITEM(size,2));
        PyObject* mlist=PySequence_Fast(PySequence_Fast_GET_ITEM(item,2),"markers");
        for(Py_ssize_t j=0;j<PySequence_Fast_GET_SIZE(mlist);++j){
            PyObject* mrk=PySequence_Fast(PySequence_Fast_GET_ITEM(mlist,j),"marker");
            Marker m; m.x=ll(PySequence_Fast_GET_ITEM(mrk,0)); m.y=ll(PySequence_Fast_GET_ITEM(mrk,1)); m.z=ll(PySequence_Fast_GET_ITEM(mrk,2));
            m.front=li(PySequence_Fast_GET_ITEM(mrk,3)); m.top=li(PySequence_Fast_GET_ITEM(mrk,4)); m.joint=li(PySequence_Fast_GET_ITEM(mrk,5));
            m.name=ss(PySequence_Fast_GET_ITEM(mrk,6)); m.target=ss(PySequence_Fast_GET_ITEM(mrk,7)); m.pool=ss(PySequence_Fast_GET_ITEM(mrk,8));
            m.pri=ll(PySequence_Fast_GET_ITEM(mrk,9));
            t.markers.push_back(m);
        }
        g_tpl_cache.emplace(key,t);
        ctx.ti[key]=ctx.templates.size(); ctx.templates.push_back(t);
    }
    Py_DECREF(seq);
    return 0;
}
static int parse_pools(PyObject* list,Ctx& ctx){
    PyObject* seq=PySequence_Fast(list,"pools");
    if(!seq) return -1;
    for(Py_ssize_t i=0;i<PySequence_Fast_GET_SIZE(seq);++i){
        PyObject* item=PySequence_Fast(PySequence_Fast_GET_ITEM(seq,i),"pool");
        Pool p; p.id=ss(PySequence_Fast_GET_ITEM(item,0));
        PyObject* elist=PySequence_Fast(PySequence_Fast_GET_ITEM(item,1),"elems");
        for(Py_ssize_t j=0;j<PySequence_Fast_GET_SIZE(elist);++j){
            PyObject* e=PySequence_Fast(PySequence_Fast_GET_ITEM(elist,j),"elem");
            Elem em; em.location=ss(PySequence_Fast_GET_ITEM(e,0)); em.etype=ss(PySequence_Fast_GET_ITEM(e,1)); em.projection=ss(PySequence_Fast_GET_ITEM(e,2));
            em.weight=ll(PySequence_Fast_GET_ITEM(e,3)); em.processors=ss(PySequence_Fast_GET_ITEM(e,4)); em.is_list = PyObject_IsTrue(PySequence_Fast_GET_ITEM(e,5))==1;
            PyObject* sl=PySequence_Fast(PySequence_Fast_GET_ITEM(e,6),"sub_ls");
            for(Py_ssize_t k=0;k<PySequence_Fast_GET_SIZE(sl);++k) em.sub_locations.push_back(ss(PySequence_Fast_GET_ITEM(sl,k)));
            PyObject* sp=PySequence_Fast(PySequence_Fast_GET_ITEM(e,7),"sub_pr");
            for(Py_ssize_t k=0;k<PySequence_Fast_GET_SIZE(sp);++k) em.sub_processors.push_back(ss(PySequence_Fast_GET_ITEM(sp,k)));
            p.elements.push_back(em);
        }
        p.fallback = PySequence_Fast_GET_ITEM(item,2)==Py_None ? "" : ss(PySequence_Fast_GET_ITEM(item,2));
        ctx.pi[p.id]=ctx.pools.size(); ctx.pools.push_back(p);
    }
    Py_DECREF(seq);
    return 0;
}

// assemble(templates, pools, seed, cx, cz, start_pool, max_depth, start_y,
//          start_y_is_offset, max_dist, pad_bottom, pad_top, skip_y_bound,
//          expansion_hack, start_jigsaw_name) -> (pieces, start_index)
static PyObject* py_assemble(PyObject*, PyObject* args){
    PyObject *templates, *pools; long long seed,cx,cz,max_depth,start_y,max_dist,pad_bottom,pad_top,skip_y_bound;
    int start_y_is_offset, expansion_hack; const char* start_pool; const char* start_jigsaw;
    if(!PyArg_ParseTuple(args,"LLLLLLLLLiissOO",&seed,&cx,&cz,&max_depth,&start_y,&max_dist,&pad_bottom,&pad_top,&skip_y_bound,&start_y_is_offset,&expansion_hack,&start_pool,&start_jigsaw,&templates,&pools)) return NULL;
    Ctx ctx; if(parse_templates(templates,ctx)||parse_pools(pools,ctx)) return NULL;
    Engine eng; eng.ctx=&ctx; eng.max_depth=(int)max_depth; eng.expansion=expansion_hack!=0;
    Rng rng; seed_layout(rng,seed,cx,cz);
    if(skip_y_bound>0){ ev("start_height_skip(n="+std::to_string(skip_y_bound)+")"); rng.next_int(skip_y_bound); }
    ev("rotation_get_random"); int rot=(int)rng.next_int(4);
    const Pool* sp=ctx.pool(start_pool);
    if(!sp) return PyErr_Format(PyExc_ValueError,"start pool not found: %s",start_pool);
    auto ex=eng.expanded(sp);
    ev("start_pool_pick(n="+std::to_string(ex.size())+")"); int64_t start_pick=rng.next_int((int64_t)ex.size());
    Elem* elem=ex[(size_t)start_pick];
    const Template* st=ctx.tpl(elem->location);
    int64_t px,py,pz;
    if(start_jigsaw && start_jigsaw[0]){
        std::vector<Marker> mk; st->markers_at(rot,mk);
        if(mk.size()>1){ ev("start_anchor_shuffle(M="+std::to_string(mk.size())+")"); shuffle_list(rng,mk); }
        const Marker* anchor=nullptr; std::string an=strip(start_jigsaw);
        for(auto& m:mk){ if(strip(m.name)==an){ anchor=&m; break; } }
        if(!anchor) return PyErr_Format(PyExc_ValueError,"no start jigsaw %s in %s",start_jigsaw,start_pool);
        px=cx*16-anchor->x; py=start_y-anchor->y; pz=cz*16-anchor->z; ev("start_anchor_relocate");
    } else { px=cx*16; py=start_y; pz=cz*16; }
    Box box=st->bounding(px,py,pz,rot);
    int64_t dy = start_y_is_offset ? (py-(box.y0+1)) : (py-box.y0);
    box=moved(box,0,dy,0); py+=dy;
    Piece* startp=new Piece{st,rot,px,py,pz,box,0,elem->projection.empty()?"rigid":elem->projection,
        elem->is_list?elem->sub_locations:std::vector<std::string>(), elem->is_list?elem->sub_processors:std::vector<std::string>(), elem->processors,{},false};
    int64_t cxm=(box.x0+box.x1)/2, czm=(box.z0+box.z1)/2;
    const int64_t BEARD_MIN=-64, BEARD_MAX=320;
    Box outer={cxm-max_dist, std::max(start_y-max_dist,BEARD_MIN+pad_bottom), czm-max_dist, cxm+max_dist+1, std::min(start_y+max_dist+1,BEARD_MAX-pad_top), czm+max_dist+1};
    Domain free; free.bounds=outer; free.holes.push_back(box);
    eng.rng=rng;
    std::vector<Piece*> pieces; eng.run(startp,&free,pieces);
    // build result
    PyObject* plist=PyList_New((Py_ssize_t)pieces.size());
    for(size_t i=0;i<pieces.size();++i){
        Piece* p=pieces[i];
        PyObject* subls=PyList_New((Py_ssize_t)p->sub_ls.size());
        for(size_t k=0;k<p->sub_ls.size();++k) PyList_SET_ITEM(subls,k,PyUnicode_FromString(p->sub_ls[k].c_str()));
        PyObject* subpr=PyList_New((Py_ssize_t)p->sub_pr.size());
        for(size_t k=0;k<p->sub_pr.size();++k) PyList_SET_ITEM(subpr,k,PyUnicode_FromString(p->sub_pr[k].c_str()));
        PyObject* tup=Py_BuildValue("(s(lll)i(llllll)iOO)",
            p->t->key.c_str(),
            p->px,p->py,p->pz,
            p->rot,
            p->box.x0,p->box.y0,p->box.z0,p->box.x1,p->box.y1,p->box.z1,
            p->depth, subls, subpr);
        PyList_SET_ITEM(plist,(Py_ssize_t)i,tup);
    }
    return Py_BuildValue("(Ol)", plist, (long long)start_pick);
}

static PyObject* py_trace_on(PyObject*, PyObject* args){
    int on; if(!PyArg_ParseTuple(args,"p",&on)) return NULL;
    g_trace = on!=0; g_events.clear(); Py_RETURN_NONE;
}
static PyObject* py_trace_get(PyObject*, PyObject*){
    PyObject* o=PyList_New((Py_ssize_t)g_events.size());
    for(size_t i=0;i<g_events.size();++i) PyList_SET_ITEM(o,(Py_ssize_t)i,PyUnicode_FromString(g_events[i].c_str()));
    return o;
}
static PyMethodDef methods[] = {
    {"assemble", py_assemble, METH_VARARGS, "run jigsaw placement"},
    {"trace_on", py_trace_on, METH_VARARGS, "enable/clear next_int trace"},
    {"trace_get", py_trace_get, METH_VARARGS, "return traced bounds"},
    {NULL,NULL,0,NULL}
};
static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT,"_jigsaw_engine","",-1,methods};
PyMODINIT_FUNC PyInit__jigsaw_engine(void){ return PyModule_Create(&mod); }