// libcortex_npu: keep QNN HTP context binaries loaded in one process and run them on demand.
//
// qnn-net-run reloads the context on every call (~400 ms each); this shim loads every graph once and
// then only pays for graphExecute. It moves raw bytes only: Python reads each tensor's dtype, scale and
// offset with cnpu_io_info() and does the (de)quantisation in numpy.
//
// C API (ctypes-friendly, every call returns 0 on success, otherwise see cnpu_last_error()):
//   cnpu_init(backend_so, system_so)       load libQnnHtp.so + libQnnSystem.so, create backend + device
//   cnpu_load(bin_path, &graph)            load one context binary (one graph) -> opaque handle
//   cnpu_num_io(graph, is_out)             number of inputs / outputs
//   cnpu_io_info(graph, is_out, i, ...)    name, dtype, scale, offset, rank, dims[8], byte size
//   cnpu_execute(graph, ins, outs)         ins/outs: arrays of buffers, in the order cnpu_io_info gives
//   cnpu_set_burst()                       vote the HTP to max clocks, no sleep, DCVS off
#include <dlfcn.h>
#include <exception>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "HTP/QnnHtpDevice.h"
#include "HTP/QnnHtpPerfInfrastructure.h"
#include "QnnInterface.h"
#include "System/QnnSystemInterface.h"

namespace {

QNN_INTERFACE_VER_TYPE g_qnn{};
QNN_SYSTEM_INTERFACE_VER_TYPE g_sys{};
Qnn_BackendHandle_t g_backend = nullptr;
Qnn_DeviceHandle_t g_device = nullptr;
Qnn_LogHandle_t g_log = nullptr;
bool g_ready = false;
std::string g_err;

void fail(const char* fmt, ...) {
  char b[512];
  va_list a;
  va_start(a, fmt);
  vsnprintf(b, sizeof b, fmt, a);
  va_end(a);
  g_err = b;
}

void log_cb(const char* fmt, QnnLog_Level_t level, uint64_t, va_list args) {
  if (level > QNN_LOG_LEVEL_WARN) return;
  fprintf(stderr, "[qnn] ");
  vfprintf(stderr, fmt, args);
  fprintf(stderr, "\n");
}

// V1 and V2 tensors share the same leading fields, so v1 reads both.
Qnn_TensorV1_t& v1(Qnn_Tensor_t& t) { return t.v1; }

size_t dtype_bytes(Qnn_DataType_t d) {
  switch (d) {
    case QNN_DATATYPE_FLOAT_32: case QNN_DATATYPE_INT_32: case QNN_DATATYPE_UINT_32:
    case QNN_DATATYPE_SFIXED_POINT_32: case QNN_DATATYPE_UFIXED_POINT_32: return 4;
    case QNN_DATATYPE_FLOAT_16: case QNN_DATATYPE_INT_16: case QNN_DATATYPE_UINT_16:
    case QNN_DATATYPE_SFIXED_POINT_16: case QNN_DATATYPE_UFIXED_POINT_16: return 2;
    case QNN_DATATYPE_INT_8: case QNN_DATATYPE_UINT_8: case QNN_DATATYPE_SFIXED_POINT_8:
    case QNN_DATATYPE_UFIXED_POINT_8: case QNN_DATATYPE_BOOL_8: return 1;
    default: return 0;
  }
}

struct Io {
  std::string name;
  std::vector<uint32_t> dims;
  Qnn_Tensor_t t;
  size_t bytes;
};

struct Graph {
  Qnn_ContextHandle_t ctx = nullptr;
  Qnn_GraphHandle_t graph = nullptr;
  std::vector<Io> in, out;
};

// Deep-copy a tensor description out of the system context's binary info (which we free afterwards).
void copy_io(const Qnn_Tensor_t* src, uint32_t n, std::vector<Io>& dst) {
  dst.resize(n);
  for (uint32_t i = 0; i < n; ++i) {
    Io& io = dst[i];
    io.t = src[i];
    const Qnn_TensorV1_t& s = src[i].v1;
    io.name = s.name ? s.name : "";
    io.dims.assign(s.dimensions, s.dimensions + s.rank);
    size_t e = 1;
    for (uint32_t d : io.dims) e *= d;
    io.bytes = e * dtype_bytes(s.dataType);
    Qnn_TensorV1_t& t = v1(io.t);
    t.name = io.name.c_str();
    t.dimensions = io.dims.data();
    t.memType = QNN_TENSORMEMTYPE_RAW;
    t.clientBuf = {nullptr, 0};
    if (io.t.version == QNN_TENSOR_VERSION_2) {
      io.t.v2.isDynamicDimensions = nullptr;
      io.t.v2.sparseParams = QNN_SPARSE_PARAMS_INIT;
    }
  }
}

template <class Info>
bool fill_from_graphs(const Info& bi, Graph& g, std::string& gname, const char* path) {
  if (bi.numGraphs != 1) {
    fail("%s: expected 1 graph, found %u", path, bi.numGraphs);
    return false;
  }
  const QnnSystemContext_GraphInfo_t& gi = bi.graphs[0];
  const char* name;
  if (gi.version == QNN_SYSTEM_CONTEXT_GRAPH_INFO_VERSION_1) {
    const auto& v = gi.graphInfoV1;
    name = v.graphName;
    copy_io(v.graphInputs, v.numGraphInputs, g.in);
    copy_io(v.graphOutputs, v.numGraphOutputs, g.out);
  } else if (gi.version == QNN_SYSTEM_CONTEXT_GRAPH_INFO_VERSION_2) {
    const auto& v = gi.graphInfoV2;
    name = v.graphName;
    copy_io(v.graphInputs, v.numGraphInputs, g.in);
    copy_io(v.graphOutputs, v.numGraphOutputs, g.out);
  } else if (gi.version == QNN_SYSTEM_CONTEXT_GRAPH_INFO_VERSION_3) {
    const auto& v = gi.graphInfoV3;
    name = v.graphName;
    copy_io(v.graphInputs, v.numGraphInputs, g.in);
    copy_io(v.graphOutputs, v.numGraphOutputs, g.out);
  } else {
    fail("%s: unknown graph info version %d", path, (int)gi.version);
    return false;
  }
  gname = name ? name : "";
  return true;
}

}  // namespace

// Nothing may throw across the C boundary (ctypes would abort the interpreter).
template <class F>
static int guarded(F f) {
  try {
    return f();
  } catch (const std::exception& e) {
    fail("C++ exception: %s", e.what());
  } catch (...) {
    fail("unknown C++ exception");
  }
  return 1;
}

extern "C" {

const char* cnpu_last_error() { return g_err.c_str(); }

static int cnpu_init_impl(const char* backend_so, const char* system_so) {
  if (g_ready) return 0;
  void* hb = dlopen(backend_so, RTLD_NOW | RTLD_GLOBAL);
  if (!hb) { fail("dlopen %s: %s", backend_so, dlerror()); return 1; }
  auto getp = (Qnn_ErrorHandle_t(*)(const QnnInterface_t***, uint32_t*))dlsym(hb, "QnnInterface_getProviders");
  if (!getp) { fail("no QnnInterface_getProviders"); return 1; }
  const QnnInterface_t** prov = nullptr;
  uint32_t np = 0;
  if (getp(&prov, &np) != QNN_SUCCESS || !prov || !np) { fail("no QNN interface providers"); return 1; }
  bool ok = false;
  for (uint32_t i = 0; i < np; ++i) {
    if (prov[i]->apiVersion.coreApiVersion.major == QNN_API_VERSION_MAJOR &&
        prov[i]->apiVersion.coreApiVersion.minor >= QNN_API_VERSION_MINOR) {
      g_qnn = prov[i]->QNN_INTERFACE_VER_NAME;
      ok = true;
      break;
    }
  }
  if (!ok) { fail("no QNN interface matching API %d.%d", QNN_API_VERSION_MAJOR, QNN_API_VERSION_MINOR); return 1; }

  void* hs = dlopen(system_so, RTLD_NOW | RTLD_LOCAL);
  if (!hs) { fail("dlopen %s: %s", system_so, dlerror()); return 1; }
  auto gets = (Qnn_ErrorHandle_t(*)(const QnnSystemInterface_t***, uint32_t*))dlsym(hs, "QnnSystemInterface_getProviders");
  if (!gets) { fail("no QnnSystemInterface_getProviders"); return 1; }
  const QnnSystemInterface_t** sprov = nullptr;
  if (gets(&sprov, &np) != QNN_SUCCESS || !sprov || !np) { fail("no QNN system providers"); return 1; }
  ok = false;
  for (uint32_t i = 0; i < np; ++i) {
    if (sprov[i]->systemApiVersion.major == QNN_SYSTEM_API_VERSION_MAJOR &&
        sprov[i]->systemApiVersion.minor >= QNN_SYSTEM_API_VERSION_MINOR) {
      g_sys = sprov[i]->QNN_SYSTEM_INTERFACE_VER_NAME;
      ok = true;
      break;
    }
  }
  if (!ok) { fail("no matching QNN system interface"); return 1; }

  g_qnn.logCreate(log_cb, QNN_LOG_LEVEL_WARN, &g_log);
  if (g_qnn.backendCreate(g_log, nullptr, &g_backend) != QNN_SUCCESS) { fail("backendCreate failed"); return 1; }
  if (g_qnn.deviceCreate && g_qnn.deviceCreate(g_log, nullptr, &g_device) != QNN_SUCCESS) {
    fail("deviceCreate failed");
    return 1;
  }
  g_ready = true;
  return 0;
}

static int cnpu_load_impl(const char* path, void** out) {
  *out = nullptr;
  if (!g_ready) { fail("cnpu_init not called"); return 1; }
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f) { fail("cannot open %s", path); return 1; }
  std::streamoff size = f.tellg();
  if (size <= 0) { fail("%s: empty or unreadable", path); return 1; }
  std::vector<char> buf((size_t)size);
  f.seekg(0);
  if (!f.read(buf.data(), buf.size())) { fail("%s: short read", path); return 1; }

  QnnSystemContext_Handle_t sc = nullptr;
  if (g_sys.systemContextCreate(&sc) != QNN_SUCCESS) { fail("systemContextCreate failed"); return 1; }
  const QnnSystemContext_BinaryInfo_t* bi = nullptr;
  Qnn_ContextBinarySize_t bisz = 0;
  if (g_sys.systemContextGetBinaryInfo(sc, buf.data(), buf.size(), &bi, &bisz) != QNN_SUCCESS || !bi) {
    g_sys.systemContextFree(sc);
    fail("%s: systemContextGetBinaryInfo failed", path);
    return 1;
  }
  auto* g = new Graph();
  bool ok;
  std::string gname;
  if (bi->version == QNN_SYSTEM_CONTEXT_BINARY_INFO_VERSION_1) ok = fill_from_graphs(bi->contextBinaryInfoV1, *g, gname, path);
  else if (bi->version == QNN_SYSTEM_CONTEXT_BINARY_INFO_VERSION_2) ok = fill_from_graphs(bi->contextBinaryInfoV2, *g, gname, path);
  else if (bi->version == QNN_SYSTEM_CONTEXT_BINARY_INFO_VERSION_3) ok = fill_from_graphs(bi->contextBinaryInfoV3, *g, gname, path);
  else { fail("%s: unknown binary info version %d", path, (int)bi->version); ok = false; }
  g_sys.systemContextFree(sc);
  if (!ok) { delete g; return 1; }

  if (g_qnn.contextCreateFromBinary(g_backend, g_device, nullptr, buf.data(), buf.size(), &g->ctx, nullptr) != QNN_SUCCESS) {
    delete g;
    fail("%s: contextCreateFromBinary failed", path);
    return 1;
  }
  if (g_qnn.graphRetrieve(g->ctx, gname.c_str(), &g->graph) != QNN_SUCCESS) {
    g_qnn.contextFree(g->ctx, nullptr);
    delete g;
    fail("%s: graphRetrieve(%s) failed", path, gname.c_str());
    return 1;
  }
  g_err.clear();
  *out = g;
  return 0;
}

int cnpu_num_io(void* h, int is_out) {
  auto* g = (Graph*)h;
  return (int)(is_out ? g->out.size() : g->in.size());
}

// dtype is the raw Qnn_DataType_t value (0x0232 float32, 0x0416 ufixed16, 0x0408 ufixed8, ...).
// float = (q + offset) * scale for fixed-point tensors; scale = 0 when the tensor is not quantised.
static int cnpu_io_info_impl(void* h, int is_out, int i, const char** name, int* dtype, float* scale, int* offset,
                 int* rank, uint32_t* dims8, uint64_t* bytes) {
  auto* g = (Graph*)h;
  auto& v = is_out ? g->out : g->in;
  if (i < 0 || i >= (int)v.size()) { fail("io index %d out of range", i); return 1; }
  Io& io = v[i];
  const Qnn_TensorV1_t& t = io.t.v1;
  *name = io.name.c_str();
  *dtype = (int)t.dataType;
  *scale = 0.f;
  *offset = 0;
  if (t.quantizeParams.encodingDefinition == QNN_DEFINITION_DEFINED &&
      t.quantizeParams.quantizationEncoding == QNN_QUANTIZATION_ENCODING_SCALE_OFFSET) {
    *scale = t.quantizeParams.scaleOffsetEncoding.scale;
    *offset = t.quantizeParams.scaleOffsetEncoding.offset;
  } else if (t.quantizeParams.encodingDefinition == QNN_DEFINITION_DEFINED) {
    fail("%s: unsupported quantization encoding %d", io.name.c_str(), (int)t.quantizeParams.quantizationEncoding);
    return 1;
  }
  *rank = (int)io.dims.size();
  if (io.dims.size() > 8) { fail("%s: rank > 8", io.name.c_str()); return 1; }
  for (size_t k = 0; k < io.dims.size(); ++k) dims8[k] = io.dims[k];
  *bytes = io.bytes;
  return 0;
}

static int cnpu_execute_impl(void* h, void** ins, void** outs) {
  auto* g = (Graph*)h;
  std::vector<Qnn_Tensor_t> ti, to;
  for (size_t i = 0; i < g->in.size(); ++i) {
    Qnn_Tensor_t t = g->in[i].t;
    t.v1.clientBuf = {ins[i], (uint32_t)g->in[i].bytes};
    ti.push_back(t);
  }
  for (size_t i = 0; i < g->out.size(); ++i) {
    Qnn_Tensor_t t = g->out[i].t;
    t.v1.clientBuf = {outs[i], (uint32_t)g->out[i].bytes};
    to.push_back(t);
  }
  Qnn_ErrorHandle_t e = g_qnn.graphExecute(g->graph, ti.data(), (uint32_t)ti.size(), to.data(), (uint32_t)to.size(),
                                           nullptr, nullptr);
  if (e != QNN_SUCCESS) { fail("graphExecute failed: %llu", (unsigned long long)e); return 1; }
  return 0;
}

static int cnpu_set_burst_impl() {
  if (!g_ready) { fail("cnpu_init not called"); return 1; }
  QnnDevice_Infrastructure_t infra = nullptr;
  if (g_qnn.deviceGetInfrastructure(&infra) != QNN_SUCCESS || !infra) { fail("deviceGetInfrastructure failed"); return 1; }
  auto* htp = (QnnHtpDevice_Infrastructure_t*)infra;
  if (htp->infraType != QNN_HTP_DEVICE_INFRASTRUCTURE_TYPE_PERF) { fail("not a perf infrastructure"); return 1; }
  auto& p = htp->perfInfra;
  uint32_t id = 0;
  if (p.createPowerConfigId(0, 0, &id) != QNN_SUCCESS) { fail("createPowerConfigId failed"); return 1; }
  QnnHtpPerfInfrastructure_PowerConfig_t c = QNN_HTP_PERF_INFRASTRUCTURE_POWER_CONFIG_INIT;
  c.option = QNN_HTP_PERF_INFRASTRUCTURE_POWER_CONFIGOPTION_DCVS_V3;
  auto& d = c.dcvsV3Config;
  d.contextId = id;
  d.setDcvsEnable = 1;
  d.dcvsEnable = 0;
  d.powerMode = QNN_HTP_PERF_INFRASTRUCTURE_POWERMODE_PERFORMANCE_MODE;
  d.setSleepLatency = 1;
  d.sleepLatency = 40;
  d.setSleepDisable = 1;
  d.sleepDisable = 1;
  d.setBusParams = 1;
  d.busVoltageCornerMin = d.busVoltageCornerTarget = d.busVoltageCornerMax = DCVS_VOLTAGE_VCORNER_MAX_VOLTAGE_CORNER;
  d.setCoreParams = 1;
  d.coreVoltageCornerMin = d.coreVoltageCornerTarget = d.coreVoltageCornerMax = DCVS_VOLTAGE_VCORNER_MAX_VOLTAGE_CORNER;
  const QnnHtpPerfInfrastructure_PowerConfig_t* list[] = {&c, nullptr};
  if (p.setPowerConfig(id, list) != QNN_SUCCESS) { fail("setPowerConfig failed"); return 1; }
  return 0;
}

int cnpu_init(const char* b, const char* s) { return guarded([&] { return cnpu_init_impl(b, s); }); }
int cnpu_load(const char* path, void** out) { return guarded([&] { return cnpu_load_impl(path, out); }); }
int cnpu_io_info(void* h, int is_out, int i, const char** name, int* dtype, float* scale, int* offset, int* rank,
                 uint32_t* dims8, uint64_t* bytes) {
  return guarded([&] { return cnpu_io_info_impl(h, is_out, i, name, dtype, scale, offset, rank, dims8, bytes); });
}
int cnpu_execute(void* h, void** ins, void** outs) { return guarded([&] { return cnpu_execute_impl(h, ins, outs); }); }
int cnpu_set_burst() { return guarded([] { return cnpu_set_burst_impl(); }); }

// Not thread-safe: one caller at a time per graph (Python reuses one set of output buffers per graph).
void cnpu_free(void* h) {
  auto* g = (Graph*)h;
  if (!g) return;
  if (g->ctx) g_qnn.contextFree(g->ctx, nullptr);
  delete g;
}

}  // extern "C"
