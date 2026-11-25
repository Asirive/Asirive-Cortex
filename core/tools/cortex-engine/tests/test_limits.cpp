// Answer limits: an answer ends at its own end (eog); max_tokens, max_speech_s and the context only stop a runaway,
// so they are broad. n_ctx is configurable.
#include <cstdio>
#include <string>

#include "../include/cortex_engine.h"
#include "check.h"
#include "events.h"

using api_test::config;
using api_test::Events;
using api_test::json;

TEST(limits_defaults_are_broad) {
    Events ev;
    void* h = ce_open(config("").c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    const json st = json::parse(ce_status(h));
    CHECK(st.value("n_ctx", 0) == 8192);
    CHECK(st.value("max_tokens", 0) == 2048);
    CHECK(st.value("max_speech_s", 0) == 180);
    ce_close(h);
}

TEST(limits_bad_values_are_refused) {
    Events ev;
    CHECK(ce_open(config(",\"n_ctx\":100").c_str(), &Events::cb, &ev) == nullptr);
    CHECK(std::string(ce_last_error()).find("n_ctx") != std::string::npos);
    CHECK(ce_open(config(",\"max_speech_s\":601").c_str(), &Events::cb, &ev) == nullptr);
    CHECK(ce_open(config(",\"max_tokens\":0").c_str(), &Events::cb, &ev) == nullptr);
}

TEST(limits_long_answer_passes_the_old_cap) {
    // the old default (512) cut this answer; with 2048 it runs to its end
    Events ev;
    void* h = ce_open(config("").c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, "Count from 1 to 300 in digits, separated by commas. Do not stop early.", 0) == 0);
    size_t b = 0;
    json done;
    CHECK(ev.wait("done", &done, &b, 240000));
    std::printf("  n_out %d, stop %s, %.1f s\n", done.value("n_out", 0), done.value("stop", "").c_str(),
                done.value("total_ms", 0.0) / 1000);
    CHECK(done.value("n_out", 0) > 512);
    CHECK(done.value("stop", "") == "eog");
    ce_close(h);
}
