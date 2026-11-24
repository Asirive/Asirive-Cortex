// Speech out: our LFM3 MIXED loop (src/speech.cpp) against llama.cpp's own pipeline, then through Lm.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

#include "../src/lm.h"
#include "../src/speech.h"
#include "check.h"
#include "llama.h"
#include "mtmd-helper.h"
#include "mtmd.h"

using namespace std::chrono;

namespace {

const char* kModel = "/var/lib/cortex/models/LFM3-Omni-2B-Q4_0.gguf";
const char* kMmproj = "/var/lib/cortex/models/mmproj-LFM3-Omni-2B-Q8_0.gguf";
const std::string kPrefix =
    "<|startoftext|><|im_start|>system\nSpeak using a female voice.<|im_end|>\n"
    "<|im_start|>user\nSay hello in one short sentence.<|im_end|>\n";
const std::string kLead = "<|im_start|>assistant\n";

std::vector<llama_token> toks(const llama_model* m, const std::string& s) {
    const llama_vocab* v = llama_model_get_vocab(m);
    int n = -llama_tokenize(v, s.c_str(), (int)s.size(), nullptr, 0, false, true);
    std::vector<llama_token> t(n);
    llama_tokenize(v, s.c_str(), (int)s.size(), t.data(), n, false, true);
    return t;
}

// the prefix on seq 0 from an empty memory; returns the next position
int decode_prefix(llama_context* ctx, const llama_model* m) {
    llama_memory_clear(llama_get_memory(ctx), true);
    auto t = toks(m, kPrefix);
    llama_batch b = llama_batch_init((int)t.size(), 0, 1);
    b.n_tokens = (int)t.size();
    for (int i = 0; i < b.n_tokens; i++)
        b.token[i] = t[i], b.pos[i] = i, b.n_seq_id[i] = 1, b.seq_id[i][0] = 0, b.logits[i] = false;
    const int rc = llama_decode(ctx, b);
    llama_batch_free(b);
    return rc == 0 ? (int)t.size() : -1;
}

std::string piece(const llama_model* m, llama_token t) {
    char buf[256];
    int n = llama_token_to_piece(llama_model_get_vocab(m), t, buf, sizeof buf, 0, false);
    return n > 0 ? std::string(buf, n) : std::string();
}

struct Run {
    std::string text;
    std::vector<float> pcm;
};

ce::LmConfig lm_config() {
    ce::LmConfig c;
    c.model = kModel, c.mmproj = kMmproj;
    c.speak = true, c.codec_inline = true;
    return c;
}

struct Pcm {
    std::vector<float> all;
    int ends = 0;
    std::function<void(const float*, int, bool)> fn() {
        return [this](const float* p, int n, bool end) {
            if (n > 0) all.insert(all.end(), p, p + n);
            ends += end;
        };
    }
};

}  // namespace

TEST(speech_matches_helper_golden) {
    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    llama_model* m = llama_model_load_from_file(kModel, mp);
    CHECK(m != nullptr);
    if (!m) return;
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = 4096, cp.n_batch = cp.n_ubatch = 2048, cp.n_threads = cp.n_threads_batch = 4;
    llama_context* ctx = llama_init_from_model(m, cp);
    mtmd_context_params mcp = mtmd_context_params_default();
    mcp.use_gpu = false, mcp.print_timings = false, mcp.warmup = false, mcp.n_threads = 4;
    mtmd_context* mctx = mtmd_init_from_file(kMmproj, m, mcp);
    CHECK(ctx && mctx);
    if (!ctx || !mctx) return;
    llama_sampler* greedy = llama_sampler_init_greedy();

    // (a) llama.cpp's step helper, MIXED continuation
    Run a;
    {
        const int n_past = decode_prefix(ctx, m);
        CHECK(n_past > 0);
        llama_set_embeddings(ctx, true);
        mtmd_helper_gen_audio* h = mtmd_helper_gen_audio_init(ctx, mctx);
        CHECK(h != nullptr);
        if (!h) return;
        mtmd_helper_gen_audio_inp in = mtmd_helper_gen_audio_inp_default();
        in.stream = true, in.seq_id = 0, in.prompt = kLead.c_str(), in.prompt_len = kLead.size();
        in.n_past = n_past, in.out_mode = MTMD_HELPER_GEN_AUDIO_OUT_MIXED, in.seed = 1234;
        in.out_type = MTMD_HELPER_GEN_AUDIO_OUTTYPE_PCM;
        CHECK(mtmd_helper_gen_audio_set_input(h, &in) == 0);
        while (mtmd_helper_gen_audio_step_prompt(h, 2048) > 0) {
        }
        const float* hs = nullptr;
        bool stop = false;
        auto out = [&] {
            int32_t sr;
            const char* d;
            size_t len;
            mtmd_helper_gen_audio_get_output(h, &sr, &d, &len, nullptr);
            const float* f = (const float*)d;
            a.pcm.insert(a.pcm.end(), f, f + len / sizeof(float));
        };
        for (int step = 0; step < 3000 && !stop; step++) {
            if (mtmd_helper_gen_audio_next_is_text(h)) {
                const llama_token t = llama_sampler_sample(greedy, ctx, -1);
                CHECK(mtmd_helper_gen_audio_step_gen(h, t, nullptr, &hs, &stop) == 0);
                if (!stop) a.text += piece(m, t);
            } else {
                CHECK(mtmd_helper_gen_audio_step_gen(h, LLAMA_TOKEN_NULL, hs, &hs, &stop) == 0);
            }
            out();
        }
        mtmd_helper_gen_audio_flush(h);
        out();
        mtmd_helper_gen_audio_free(h);
        llama_set_embeddings(ctx, false);
    }

    // (b) ours: Speech on the same context and prompt, codec inline on its own gen state
    Run b;
    ce::SpeakResult r;
    {
        int pos = decode_prefix(ctx, m);
        std::string err;
        auto sp = ce::Speech::open(ctx, mctx, &err);
        auto codec = ce::Codec::open(mctx, &err);
        CHECK(sp && codec);
        if (!sp || !codec) return;
        std::vector<float> pcm;
        ce::SpeakIo io;
        io.on_token = [&](const std::string& s) { b.text += s; };
        io.on_frame = [&](const int32_t* codes) { CHECK(codec->decode(codes, &b.pcm)); };
        io.cancelled = [] { return false; };
        r = sp->run(0, &pos, kLead, 400, 400, 1234, io);
        CHECK(codec->flush(&b.pcm));
    }
    std::printf("  helper: %zu samples \"%s\"\n  ours:   %zu samples \"%s\" (%d frames, stop %s, %.1f ms/frame)\n",
                a.pcm.size(), a.text.c_str(), b.pcm.size(), b.text.c_str(), r.frames, r.stop.c_str(), r.frame_ms);
    CHECK(r.stop == "eog");
    CHECK(a.text == b.text);
    CHECK(a.text == r.text);
    CHECK(a.pcm.size() == b.pcm.size());
    CHECK(a.pcm.size() >= 24000 / 2);
    double worst = 0;
    for (size_t i = 0; i < std::min(a.pcm.size(), b.pcm.size()); i++)
        worst = std::max(worst, (double)std::fabs(a.pcm[i] - b.pcm[i]));
    std::printf("  max |pcm diff| %g\n", worst);
    CHECK(worst <= 1e-4);
    llama_sampler_free(greedy);
    mtmd_free(mctx);
    llama_free(ctx);
    llama_model_free(m);
}

TEST(speech_lm_answer_speaks_and_follows_up) {
    Pcm pcm;
    auto c = lm_config();
    c.on_pcm = pcm.fn();
    std::string err;
    auto lm = ce::Lm::open(c, &err);
    if (!lm) std::printf("  open: %s\n", err.c_str());
    CHECK(lm != nullptr);
    if (!lm) return;
    auto r = lm->ask("What is two plus two? Answer in a few words.", 60, nullptr);
    std::printf("  \"%s\" stop %s frames %d frame_ms %.1f codec_ms %.1f ttft %.0f total %.0f samples %zu\n",
                r.text.c_str(), r.stop.c_str(), r.frames, r.frame_ms, r.codec_ms, r.ttft_ms, r.total_ms,
                pcm.all.size());
    CHECK(r.stop == "eog" && r.error.empty());
    CHECK(r.frames >= 12);
    CHECK(pcm.all.size() >= 24000);
    CHECK(pcm.ends == 1);
    CHECK(!r.text.empty() && r.text.find("<|") == std::string::npos);
    CHECK_NEAR(r.sound_ms, r.frames * 80.0, 0.1);

    // a follow-up continues S: positions re-synced, embeddings back on
    auto r2 = lm->ask("And three plus three?", 60, nullptr);
    std::printf("  \"%s\" stop %s frames %d\n", r2.text.c_str(), r2.stop.c_str(), r2.frames);
    CHECK(r2.stop == "eog" && r2.frames >= 6);
    CHECK(pcm.ends == 2);
}

TEST(speech_max_speech_s_stops) {
    Pcm pcm;
    auto c = lm_config();
    c.on_pcm = pcm.fn();
    c.max_speech_s = 1;
    std::string err;
    auto lm = ce::Lm::open(c, &err);
    CHECK(lm != nullptr);
    if (!lm) return;
    auto r = lm->ask("Count from one to thirty.", 200, nullptr);
    std::printf("  \"%s\" stop %s frames %d\n", r.text.c_str(), r.stop.c_str(), r.frames);
    CHECK(r.stop == "max");
    CHECK(r.frames <= 13);
    CHECK(lm->has_pending_turns());
    CHECK(pcm.ends == 1);
    auto r2 = lm->ask("Thanks. Say bye.", 60, nullptr);
    CHECK(r2.error.empty() && r2.stop != "error");
}

TEST(speech_cancel_stops_within_200ms) {
    Pcm pcm;
    auto c = lm_config();
    c.on_pcm = pcm.fn();
    std::string err;
    auto lm = ce::Lm::open(c, &err);
    CHECK(lm != nullptr);
    if (!lm) return;
    steady_clock::time_point cut;
    std::thread t([&] {
        std::this_thread::sleep_for(milliseconds(1500));
        cut = steady_clock::now();
        lm->cancel();
    });
    auto r = lm->ask("Tell me a long story about a lighthouse keeper.", 300, nullptr);
    const double after = duration<double, std::milli>(steady_clock::now() - cut).count();
    t.join();
    lm->clear_cancel();
    std::printf("  stop %s frames %d returned %.0f ms after cancel\n", r.stop.c_str(), r.frames, after);
    CHECK(r.cancelled && r.stop == "cancel");
    CHECK(after < 200);
    CHECK(pcm.ends == 1);
}

TEST(speech_off_is_text_only) {
    Pcm pcm;
    auto c = lm_config();
    c.speak = false;
    c.on_pcm = pcm.fn();
    std::string err;
    auto lm = ce::Lm::open(c, &err);
    CHECK(lm != nullptr);
    if (!lm) return;
    auto r = lm->ask("What is two plus two? Answer in a few words.", 40, nullptr);
    CHECK(r.stop == "eog" && r.frames == 0);
    CHECK(pcm.all.empty() && pcm.ends == 0);
}
