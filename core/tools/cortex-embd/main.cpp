// cortex-embd: LFM3-Omni image features in and out of llama.cpp, for the NPU vision work.
//
//   cortex-embd dump   -m MODEL --mmproj MMPROJ --image IMG --out FEAT.f32
//       CPU image features as raw little-endian float32 [n_tokens, n_embd] + FEAT.f32.json
//       {"n_tokens":..,"n_embd":..,"encode_ms":..,"image_w":..,"image_h":..}
//   cortex-embd answer -m MODEL --mmproj MMPROJ --feat FEAT.f32 -p PROMPT [-n 60] [-t THREADS]
//       answers PROMPT with the features placed where an image of FEAT's size would be,
//       prints the answer, then one JSON line {"ttft_s":..,"decode_tps":..,"n_out":..}
//
// Built against llama.cpp b12679 (core/scripts/build_cortex_embd.sh). Greedy decoding, CPU only.
#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

using clk = std::chrono::steady_clock;

double secs(clk::time_point a, clk::time_point b) { return std::chrono::duration<double>(b - a).count(); }

[[noreturn]] void die(const std::string & msg) {
    std::fprintf(stderr, "cortex-embd: %s\n", msg.c_str());
    std::exit(1);
}

void quiet_log(ggml_log_level level, const char * text, void *) {
    if (level >= GGML_LOG_LEVEL_ERROR) std::fputs(text, stderr);
}

std::map<std::string, std::string> parse_args(int argc, char ** argv) {
    std::map<std::string, std::string> a;
    for (int i = 2; i < argc; i++) {
        std::string k = argv[i];
        if (i + 1 >= argc) die("missing value for " + k);
        a[k] = argv[++i];
    }
    return a;
}

std::string need(const std::map<std::string, std::string> & a, const std::string & k) {
    auto it = a.find(k);
    if (it == a.end()) die("missing " + k);
    return it->second;
}

// LFM chat format; the model's jinja template is not handled by llama_chat_apply_template.
std::string chat_prompt(const std::string & user) {
    return "<|startoftext|><|im_start|>user\n" + user + "<|im_end|>\n<|im_start|>assistant\n";
}

struct Loaded {
    llama_model * model = nullptr;
    llama_context * lctx = nullptr;
    mtmd_context * mctx = nullptr;
};

// n_threads 0 = llama.cpp's default
Loaded load(const std::string & model_path, const std::string & mmproj_path, int n_threads = 0) {
    Loaded L;
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;
    L.model = llama_model_load_from_file(model_path.c_str(), mp);
    if (!L.model) die("cannot load model " + model_path);
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = 4096;
    cp.n_batch = 2048;
    cp.n_ubatch = 2048;
    if (n_threads > 0) cp.n_threads = cp.n_threads_batch = n_threads;
    L.lctx = llama_init_from_model(L.model, cp);
    if (!L.lctx) die("cannot create context");
    mtmd_context_params mcp = mtmd_context_params_default();
    mcp.use_gpu = false;
    mcp.print_timings = false;
    mcp.warmup = true;
    L.mctx = mtmd_init_from_file(mmproj_path.c_str(), L.model, mcp);
    if (!L.mctx) die("cannot load mmproj " + mmproj_path);
    return L;
}

mtmd_input_chunks * tokenize(mtmd_context * mctx, const std::string & question, mtmd_bitmap * bmp) {
    std::string prompt = chat_prompt(std::string(mtmd_get_marker(mctx)) + "\n" + question);
    mtmd_input_text text{prompt.c_str(), prompt.size(), /*add_special*/ false, /*parse_special*/ true};
    mtmd_input_chunks * chunks = mtmd_input_chunks_init();
    const mtmd_bitmap * bitmaps[] = {bmp};
    if (mtmd_tokenize(mctx, chunks, &text, bitmaps, 1) != 0) die("tokenize failed");
    return chunks;
}

const mtmd_input_chunk * image_chunk(const mtmd_input_chunks * chunks) {
    for (size_t i = 0; i < mtmd_input_chunks_size(chunks); i++) {
        const mtmd_input_chunk * c = mtmd_input_chunks_get(chunks, i);
        if (mtmd_input_chunk_get_type(c) == MTMD_INPUT_CHUNK_TYPE_IMAGE) return c;
    }
    die("no image chunk in prompt");
}

int cmd_dump(const std::map<std::string, std::string> & a) {
    Loaded L = load(need(a, "-m"), need(a, "--mmproj"));
    std::string out = need(a, "--out");
    mtmd_helper_bitmap_wrapper w =
        mtmd_helper_bitmap_init_from_file(L.mctx, need(a, "--image").c_str(), false, mtmd_helper_init_opt_default());
    if (!w.bitmap) die("cannot read image " + need(a, "--image"));
    mtmd_input_chunks * chunks = tokenize(L.mctx, "x", w.bitmap);
    const mtmd_input_chunk * img = image_chunk(chunks);
    auto t0 = clk::now();
    if (mtmd_encode_chunk(L.mctx, img) != 0) die("encode failed");
    auto t1 = clk::now();
    const size_t n_tok = mtmd_input_chunk_get_n_tokens(img);
    const int n_embd = llama_model_n_embd_inp(L.model);
    const float * embd = mtmd_get_output_embd(L.mctx);
    std::ofstream f(out, std::ios::binary);
    f.write(reinterpret_cast<const char *>(embd), static_cast<std::streamsize>(n_tok * n_embd * sizeof(float)));
    if (!f) die("cannot write " + out);
    std::ofstream j(out + ".json");
    j << "{\"n_tokens\": " << n_tok << ", \"n_embd\": " << n_embd << ", \"encode_ms\": " << secs(t0, t1) * 1000
      << ", \"image_w\": " << mtmd_bitmap_get_nx(w.bitmap) << ", \"image_h\": " << mtmd_bitmap_get_ny(w.bitmap) << "}\n";
    std::printf("{\"n_tokens\": %zu, \"n_embd\": %d, \"encode_ms\": %.1f}\n", n_tok, n_embd, secs(t0, t1) * 1000);
    mtmd_input_chunks_free(chunks);
    mtmd_bitmap_free(w.bitmap);
    return 0;
}

int json_int(const std::string & s, const std::string & key) {
    size_t p = s.find("\"" + key + "\"");
    if (p == std::string::npos) die("feature json has no " + key);
    p = s.find(':', p);
    return std::atoi(s.c_str() + p + 1);
}

int cmd_answer(const std::map<std::string, std::string> & a) {
    Loaded L = load(need(a, "-m"), need(a, "--mmproj"), a.count("-t") ? std::atoi(a.at("-t").c_str()) : 0);
    const std::string feat = need(a, "--feat");
    const int n_predict = a.count("-n") ? std::atoi(a.at("-n").c_str()) : 60;
    std::stringstream js;
    js << std::ifstream(feat + ".json").rdbuf();
    const int n_tok = json_int(js.str(), "n_tokens"), n_embd = json_int(js.str(), "n_embd");
    const int img_w = json_int(js.str(), "image_w"), img_h = json_int(js.str(), "image_h");
    if (n_embd != llama_model_n_embd_inp(L.model)) die("feature width does not match the model");
    std::vector<float> embd(static_cast<size_t>(n_tok) * n_embd);
    std::ifstream f(feat, std::ios::binary);
    f.read(reinterpret_cast<char *>(embd.data()), static_cast<std::streamsize>(embd.size() * sizeof(float)));
    if (!f) die("cannot read " + feat + " (expected " + std::to_string(n_tok) + "x" + std::to_string(n_embd) + " float32)");

    // a grey stand-in of the same size gives the prompt the same image-token layout; its pixels are never used
    std::vector<unsigned char> grey(static_cast<size_t>(img_w) * img_h * 3, 128);
    mtmd_bitmap * stand_in = mtmd_bitmap_init(img_w, img_h, grey.data());
    mtmd_input_chunks * chunks = tokenize(L.mctx, need(a, "-p"), stand_in);
    if ((int) mtmd_input_chunk_get_n_tokens(image_chunk(chunks)) != n_tok)
        die("feature has " + std::to_string(n_tok) + " tokens, the prompt expects " +
            std::to_string(mtmd_input_chunk_get_n_tokens(image_chunk(chunks))));

    llama_sampler * smpl = llama_sampler_init_greedy();
    const llama_vocab * vocab = llama_model_get_vocab(L.model);
    auto t0 = clk::now();
    llama_pos n_past = 0;
    const size_t n_chunks = mtmd_input_chunks_size(chunks);
    for (size_t i = 0; i < n_chunks; i++) {
        const mtmd_input_chunk * c = mtmd_input_chunks_get(chunks, i);
        const bool last = i + 1 == n_chunks;
        int32_t rc = mtmd_input_chunk_get_type(c) == MTMD_INPUT_CHUNK_TYPE_IMAGE
            ? mtmd_helper_decode_image_chunk(L.mctx, L.lctx, c, embd.data(), n_past, 0, 2048, &n_past, nullptr, nullptr)
            : mtmd_helper_eval_chunk_single(L.mctx, L.lctx, c, n_past, 0, 2048, last, &n_past);
        if (rc != 0) die("decode failed on chunk " + std::to_string(i));
    }
    std::string answer;
    clk::time_point t_first{};
    int n_out = 0;
    for (; n_out < n_predict; n_out++) {
        llama_token tok = llama_sampler_sample(smpl, L.lctx, -1);
        if (n_out == 0) t_first = clk::now();
        if (llama_vocab_is_eog(vocab, tok)) break;
        char buf[256];
        int n = llama_token_to_piece(vocab, tok, buf, sizeof(buf), 0, false);
        if (n > 0) answer.append(buf, n);
        llama_batch b = llama_batch_get_one(&tok, 1);
        if (llama_decode(L.lctx, b) != 0) die("decode failed while generating");
    }
    auto t_end = clk::now();
    std::printf("%s\n", answer.c_str());
    const double gen = secs(t_first, t_end);
    std::printf("{\"ttft_s\": %.3f, \"decode_tps\": %.1f, \"n_out\": %d}\n", secs(t0, t_first),
                n_out > 1 && gen > 0 ? (n_out - 1) / gen : 0.0, n_out);
    llama_sampler_free(smpl);
    mtmd_input_chunks_free(chunks);
    mtmd_bitmap_free(stand_in);
    return 0;
}

}  // namespace

int main(int argc, char ** argv) {
    if (argc < 2) die("usage: cortex-embd dump|answer ...");
    llama_log_set(quiet_log, nullptr);
    mtmd_helper_log_set(quiet_log, nullptr);
    llama_backend_init();
    const std::string cmd = argv[1];
    auto args = parse_args(argc, argv);
    if (cmd == "dump") return cmd_dump(args);
    if (cmd == "answer") return cmd_answer(args);
    die("unknown command " + cmd);
}
