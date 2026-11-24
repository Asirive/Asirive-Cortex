#include "vision.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <sys/stat.h>

#include "fixed.h"
#include "island.h"

extern "C" {
const char* cnpu_last_error();
int cnpu_init(const char* backend_so, const char* system_so);
int cnpu_load(const char* path, void** out);
int cnpu_num_io(void* h, int is_out);
int cnpu_io_info(void* h, int is_out, int i, const char** name, int* dtype, float* scale, int* offset, int* rank,
                 uint32_t* dims8, uint64_t* bytes);
int cnpu_execute(void* h, void** ins, void** outs);
int cnpu_set_burst();
void cnpu_free(void* h);
}

namespace ce {

namespace {
std::atomic<bool> g_npu_opened{false};

bool is_file(const std::string& p) {
    struct stat st;
    return ::stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

struct NpuIo {
    std::string name;  // ONNX name
    QType type;
    float scale;
    int offset;
    size_t elems;
    std::vector<uint8_t> buf;  // raw QNN-side bytes
};
}  // namespace

struct Vision::Stage {
    std::string label;
    void* graph = nullptr;  // NPU segment
    std::vector<NpuIo> in, out;
    std::unique_ptr<Island> island;  // CPU island
    std::string q, k, v, o;
    ~Stage() {
        if (graph) cnpu_free(graph);
    }
};

Vision::~Vision() = default;

static NpuIo io_info(void* g, int is_out, int i) {
    const char* name = nullptr;
    int dtype = 0, offset = 0, rank = 0;
    float scale = 0;
    uint32_t dims[8];
    uint64_t bytes = 0;
    if (cnpu_io_info(g, is_out, i, &name, &dtype, &scale, &offset, &rank, dims, &bytes))
        throw std::runtime_error(std::string("io_info: ") + cnpu_last_error());
    NpuIo io{name, (QType)dtype, scale, offset, 1, {}};
    for (int r = 0; r < rank; r++) io.elems *= dims[r];
    if (io.elems * qtype_bytes(io.type) != bytes)
        throw std::runtime_error(std::string(name) + ": byte size does not match dims and type");
    io.buf.resize(bytes);
    return io;
}

std::unique_ptr<Vision> Vision::open(const std::string& dir, const std::string& qnn_lib_dir,
                                     const std::vector<int>& island_cpus, int island_threads,
                                        const std::vector<int>& island_small_cpus, std::string* err) {
    try {
        if (!is_file(dir + "/io.json") || !is_file(dir + "/npu0.bin"))
            throw std::runtime_error("no split encoder in " + dir + " (need io.json + npu*.bin)");
        if (!is_file(qnn_lib_dir + "/libQnnHtp.so"))
            throw std::runtime_error("libQnnHtp.so not in " + qnn_lib_dir + ": install qcom-qnn-sdk-v68 (QNN 2.42)");
        std::ifstream jf(dir + "/io.json");
        const nlohmann::json io = nlohmann::json::parse(jf);
        if (!io.contains("islands")) throw std::runtime_error(dir + "/io.json has no islands block (make_goldens.py --write-io)");
        if (g_npu_opened.exchange(true)) throw std::runtime_error("NPU already opened in this process");
        if (cnpu_init((qnn_lib_dir + "/libQnnHtp.so").c_str(), (qnn_lib_dir + "/libQnnSystem.so").c_str()))
            throw std::runtime_error(std::string("QNN init: ") + cnpu_last_error());
        if (cnpu_set_burst()) throw std::runtime_error(std::string("QNN burst: ") + cnpu_last_error());

        std::unique_ptr<Vision> v(new Vision());
        for (int k = 0;; k++) {
            const std::string label = (k % 2 == 0 ? "npu" : "cpu") + std::to_string(k);
            auto st = std::make_unique<Stage>();
            st->label = label;
            if (k % 2 == 0) {
                const std::string bin = dir + "/" + label + ".bin";
                if (!is_file(bin)) break;
                if (cnpu_load(bin.c_str(), &st->graph)) throw std::runtime_error(std::string("load: ") + cnpu_last_error());
                for (int is_out = 0; is_out < 2; is_out++) {
                    auto& list = is_out ? st->out : st->in;
                    std::vector<std::string> qnn_names;
                    for (int i = 0; i < cnpu_num_io(st->graph, is_out); i++) {
                        list.push_back(io_info(st->graph, is_out, i));
                        qnn_names.push_back(list.back().name);
                    }
                    auto onnx = match_names(qnn_names, io.at(label).at(is_out ? "out" : "in").get<std::vector<std::string>>());
                    for (size_t i = 0; i < list.size(); i++) list[i].name = onnx[i];
                }
                for (auto& o : st->out) v->env_[o.name].resize(o.elems);
                if (k == 0) v->pixel_count_ = st->in.at(0).elems;
            } else {
                if (!io["islands"].contains(label)) break;
                const auto& d = io["islands"][label];
                st->island = std::make_unique<Island>(d.at("n_tok").get<int>(), d.at("heads").get<int>(),
                                                      d.at("dim").get<int>(), d.at("scale").get<float>(), island_cpus,
                                                      island_threads, island_small_cpus);
                st->q = d.at("q"), st->k = d.at("k"), st->v = d.at("v"), st->o = d.at("out");
                v->env_[st->o].resize(st->island->numel());
            }
            v->stages_.push_back(std::move(st));
        }
        auto it = v->env_.find("image_features");
        if (it == v->env_.end()) throw std::runtime_error("no stage produces image_features");
        // image_features is [n_tokens, 2048]: the hidden size comes from the last NPU output's last dim.
        v->n_embd_ = 2048;
        v->n_tokens_ = (int)(it->second.size() / v->n_embd_);
        return v;
    } catch (const std::exception& e) {
        if (err) *err = e.what();
        return nullptr;
    }
}

std::shared_ptr<Vision> Vision::shared(const std::string& split_dir, const std::string& qnn_lib_dir,
                                       const std::vector<int>& island_cpus, int island_threads,
                                        const std::vector<int>& island_small_cpus, std::string* err) {
    static std::mutex mu;
    static std::shared_ptr<Vision> one;
    std::lock_guard<std::mutex> g(mu);
    // Never freed: destroying it during static destruction runs after QNN's own teardown (error spam at exit), and
    // the NPU is closed by process exit anyway.
    if (!one)
        if (Vision* v = open(split_dir, qnn_lib_dir, island_cpus, island_threads, island_small_cpus, err).release())
            one = std::shared_ptr<Vision>(v, [](Vision*) {});
    return one;
}

bool Vision::encode(const float* pixel_values, std::vector<float>* features, std::string* err) {
    try {
        last_ms_.clear();
        auto get = [&](const std::string& name) -> const float* {
            if (name == "pixel_values") return pixel_values;
            auto it = env_.find(name);
            if (it == env_.end()) throw std::runtime_error(name + " not produced by an earlier stage");
            return it->second.data();
        };
        for (auto& st : stages_) {
            const auto t0 = std::chrono::steady_clock::now();
            if (st->graph) {
                std::vector<void*> ins, outs;
                for (auto& i : st->in) {
                    to_fixed(get(i.name), i.elems, i.type, i.scale, i.offset, i.buf.data());
                    ins.push_back(i.buf.data());
                }
                for (auto& o : st->out) outs.push_back(o.buf.data());
                const auto t1 = std::chrono::steady_clock::now();
                if (cnpu_execute(st->graph, ins.data(), outs.data()))
                    throw std::runtime_error(st->label + ": " + cnpu_last_error());
                const auto t2 = std::chrono::steady_clock::now();
                for (auto& o : st->out) from_fixed(o.buf.data(), o.elems, o.type, o.scale, o.offset, env_[o.name].data());
                last_ms_[st->label + ":q"] = std::chrono::duration<double, std::milli>(t1 - t0).count();
                last_ms_[st->label + ":x"] = std::chrono::duration<double, std::milli>(t2 - t1).count();
                last_ms_[st->label + ":d"] =
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t2).count();
            } else {
                const bool big = gate_enter_ ? gate_enter_() : true;
                st->island->run(get(st->q), get(st->k), get(st->v), env_[st->o].data(), !big);
                if (gate_exit_) gate_exit_(big);            }
            last_ms_[st->label] = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        }
        *features = env_.at("image_features");
        return true;
    } catch (const std::exception& e) {
        if (err) *err = e.what();
        return false;
    }
}

}  // namespace ce
