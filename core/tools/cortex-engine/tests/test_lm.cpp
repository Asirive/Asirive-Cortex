#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "../src/lm.h"
#include "check.h"
#include "golden.h"

static const std::string kModels = "/var/lib/cortex/models/";
static const std::string kQuestion = "What is the large toy in front of me? One sentence.";

static ce::LmConfig cfg() {
    ce::LmConfig c;
    c.model = kModels + "LFM3-Omni-2B-Q4_0.gguf";
    c.mmproj = kModels + "mmproj-LFM3-Omni-2B-Q8_0.gguf";
    return c;
}

static std::unique_ptr<ce::Lm> open_lm(const ce::LmConfig& c) {
    std::string err;
    auto lm = ce::Lm::open(c, &err);
    if (!lm) std::printf("  open failed: %s\n", err.c_str());
    return lm;
}

static std::vector<float> feat(const char* stem) { return golden::load_f32(golden::npu_feats + stem + ".npu.f32"); }

static std::string strip(std::string s) {
    for (const char* t : {"<think></think>", "<think>", "</think>"})
        for (size_t p; (p = s.find(t)) != std::string::npos;) s.erase(p, std::strlen(t));
    while (!s.empty() && (s.back() == '\n' || s.back() == ' ')) s.pop_back();
    while (!s.empty() && (s.front() == '\n' || s.front() == ' ')) s.erase(0, 1);
    return s;
}

TEST(lm_ask_matches_cortex_embd) {
    auto lm = open_lm(cfg());
    CHECK(lm != nullptr);
    if (!lm) return;
    auto f = feat("t001");
    std::string err;
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    auto r = lm->ask(kQuestion, 60, nullptr);
    const std::string cmd = "/opt/llama.cpp/cortex-embd/cortex-embd answer -m " + cfg().model + " --mmproj " +
                            cfg().mmproj + " --feat " + golden::npu_feats + "t001.npu.f32 -p '" + kQuestion +
                            "' -t 4 2>/dev/null | head -n -1";
    std::string want;
    if (FILE* p = popen(cmd.c_str(), "r")) {
        char buf[512];
        while (fgets(buf, sizeof buf, p)) want += buf;
        pclose(p);
    }
    std::printf("  engine:      %s\n  cortex-embd: %s\n", strip(r.text).c_str(), strip(want).c_str());
    CHECK(!strip(want).empty());
    CHECK(strip(r.text) == strip(want));
    CHECK(r.view_frame_id == 1);
}

TEST(lm_ask_ttft_with_view_ready) {
    auto lm = open_lm(cfg());
    if (!lm) { CHECK(false); return; }
    auto f = feat("t001");
    std::string err;
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    std::printf("  view read %.0f ms\n", lm->last_read_ms());
    std::vector<double> ttft;
    for (int i = 0; i < 5; i++) {
        auto r = lm->ask("What colour is it? One sentence.", 30, nullptr);
        ttft.push_back(r.ttft_ms);
        CHECK(lm->read_view(f.data(), 220, 2 + i, &err));  // fresh view: each ask starts from V, not a follow-up
    }
    std::printf("  ttft median %.0f ms (copy %.2f ms)\n", golden::median(ttft), lm->copy_ms());
    CHECK(golden::median(ttft) <= 400.0);
}

TEST(lm_follow_up_continues_conversation) {
    auto lm = open_lm(cfg());
    if (!lm) { CHECK(false); return; }
    auto f = feat("t001");
    std::string err;
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    auto a = lm->ask(kQuestion, 40, nullptr);
    auto b = lm->ask("What did I just ask you about? One sentence.", 40, nullptr);
    std::printf("  follow-up: %s (ttft %.0f ms)\n", strip(b.text).c_str(), b.ttft_ms);
    CHECK(!strip(b.text).empty());
    CHECK(b.ttft_ms <= 400.0);
}

TEST(lm_ask_preempts_background_read) {
    auto lm = open_lm(cfg());
    if (!lm) { CHECK(false); return; }
    auto f1 = feat("t001"), f8 = feat("t008");
    std::string err;
    CHECK(lm->read_view(f1.data(), 220, 1, &err));
    bool read_ok = true;
    std::string read_err;
    std::thread bg([&] { read_ok = lm->read_view(f8.data(), 220, 8, &read_err); });
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    auto r = lm->ask(kQuestion, 30, nullptr);
    bg.join();
    std::printf("  preempted read: ok=%d err=%s; ask ttft %.0f ms view %ld\n", read_ok, read_err.c_str(), r.ttft_ms,
                r.view_frame_id);
    CHECK(!read_ok && read_err == "preempted");
    CHECK(r.view_frame_id == 1);
    CHECK(r.ttft_ms <= 600.0);
}

TEST(lm_ask_without_view) {
    auto lm = open_lm(cfg());
    if (!lm) { CHECK(false); return; }
    auto r = lm->ask("Say hello in one short sentence.", 20, nullptr);
    std::printf("  no view: %s\n", strip(r.text).c_str());
    CHECK(!strip(r.text).empty());
    CHECK(r.view_frame_id == -1);
}

TEST(lm_commit_turns_keeps_read_image_only) {
    auto lm = open_lm(cfg());
    if (!lm) { CHECK(false); return; }
    auto f1 = feat("t001"), f8 = feat("t008");
    std::string err;
    CHECK(lm->read_view(f1.data(), 220, 1, &err));
    const double first = lm->last_read_ms();
    lm->ask(kQuestion, 40, nullptr);
    CHECK(lm->has_pending_turns());
    const int before = lm->history_tokens();
    CHECK(lm->commit_turns(&err));
    CHECK(!lm->has_pending_turns() && lm->history_tokens() > before);
    CHECK(lm->read_view(f8.data(), 220, 8, &err));
    std::printf("  read %.0f ms, after a committed turn %.0f ms (history %d tokens)\n", first, lm->last_read_ms(),
                lm->history_tokens());
    CHECK(lm->last_read_ms() <= first + 60.0);
    // the committed turn is in the conversation: a follow-up about the earlier question still works
    auto r = lm->ask("What did I ask you before this? One sentence.", 30, nullptr);
    std::printf("  recall: %s\n", strip(r.text).c_str());
    CHECK(strip(r.text).find("toy") != std::string::npos);
}

TEST(lm_history_overflow_drops_oldest) {
    auto c = cfg();
    c.max_history_tokens = 64;
    auto lm = open_lm(c);
    if (!lm) { CHECK(false); return; }
    auto f = feat("t001");
    std::string err;
    for (int i = 0; i < 4; i++) {
        CHECK(lm->read_view(f.data(), 220, i, &err));  // moves the last turn into H
        auto r = lm->ask("Describe it briefly.", 20, nullptr);
        CHECK(!strip(r.text).empty());
    }
    CHECK(lm->read_view(f.data(), 220, 9, &err));
    std::printf("  history tokens %d\n", lm->history_tokens());
    CHECK(lm->history_tokens() <= 64);
}
