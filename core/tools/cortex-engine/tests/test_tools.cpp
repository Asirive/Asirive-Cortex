// Tool calls through the C API: the model's own <tool_call> format, never spoken; results read back into the
// conversation and answered by the LM or spoken as a fixed sentence; ce_say for unprompted cues; the state line.
#include <cstdio>
#include <string>
#include <sys/stat.h>

#include "../include/cortex_engine.h"
#include "check.h"
#include "events.h"

using api_test::config;
using api_test::Events;
using api_test::json;

namespace {

// Two tools in the model's own JSON schema form, as the brain's registry renders them (one object per line).
const char* kTools =
    "{\"name\": \"bus_arrivals\", \"description\": \"When the next buses come at a bus stop.\", \"parameters\": "
    "{\"type\": \"object\", \"properties\": {\"service\": {\"type\": \"string\", \"description\": \"Bus number, "
    "e.g. 858\"}, \"stop\": {\"type\": \"string\", \"description\": \"5-digit bus stop code; empty = the nearest "
    "stop\"}}, \"required\": [\"service\"]}}\n"
    "{\"name\": \"search_places\", \"description\": \"Find a place by name or postal code.\", \"parameters\": "
    "{\"type\": \"object\", \"properties\": {\"query\": {\"type\": \"string\"}}, \"required\": [\"query\"]}}";

const char* kWav = "/tmp/ce_tools.wav";

std::string tools_extra(bool speak) {
    json t = kTools;
    std::string e = ",\"tools\":" + t.dump();
    if (speak) e += std::string(",\"speak\":true,\"speaker_device\":\"wav:") + kWav + "\"";
    return e;
}

void* open_tools(Events& ev, bool speak) {
    void* h = ce_open(config(tools_extra(speak)).c_str(), &Events::cb, &ev);
    if (!h) std::printf("  open failed: %s\n", ce_last_error());
    return h;
}

json status(void* h) { return json::parse(ce_status(h)); }

long file_size(const char* p) {
    struct stat st;
    return ::stat(p, &st) == 0 ? (long)st.st_size : -1;
}

}  // namespace

TEST(tools_bad_config_is_refused) {
    Events ev;
    CHECK(ce_open(config(",\"tools\":42").c_str(), &Events::cb, &ev) == nullptr);
    CHECK(std::string(ce_last_error()).find("tools") != std::string::npos);
}

TEST(tools_call_is_an_event_not_an_answer) {
    Events ev;
    void* h = open_tools(ev, false);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, "When is bus 858 coming?", 0) == 0);
    size_t a = 0, b = 0;
    json call, done;
    CHECK(ev.wait("tool_call", &call, &a, 60000));
    CHECK(ev.wait("done", &done, &b, 60000));
    const std::string t = call.value("text", "");
    std::printf("  call: %s\n", t.c_str());
    CHECK(t.find("<function=bus_arrivals>") != std::string::npos);
    CHECK(t.find("858") != std::string::npos);
    CHECK(done.value("stop", "") == "tool");
    CHECK(done.value("tool", false) == true);
    CHECK(ev.count("token") == 0);  // a call is never shown or spoken as an answer
    CHECK(status(h).value("awaiting_tool", false) == true);
    ce_close(h);
}

TEST(tools_chitchat_makes_no_call) {
    Events ev;
    void* h = open_tools(ev, false);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, "What is two plus two? Answer in a few words.", 0) == 0);
    size_t b = 0;
    json done;
    CHECK(ev.wait("done", &done, &b, 60000));
    CHECK(ev.count("tool_call") == 0);
    CHECK(done.value("stop", "") == "eog");
    CHECK(done.value("n_out", 0) > 0);
    CHECK(status(h).value("awaiting_tool", true) == false);
    ce_close(h);
}

TEST(tools_result_answered_by_the_lm) {
    Events ev;
    void* h = open_tools(ev, false);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_tool_result(h, "{}", nullptr) == -1);  // nothing is waiting for a result
    const size_t start = ev.size();                   // (that refusal is an error event)
    CHECK(ce_ask(h, "When is bus 858 coming?", 0) == 0);
    size_t a = 0, b = 0;
    json call, done;
    CHECK(ev.wait("tool_call", &call, &a, 60000));
    CHECK(ev.wait("done", &done, &b, 60000));
    const size_t mark = ev.size();
    CHECK(ce_tool_result(h, "{\"service\": \"858\", \"stop\": \"Opp Blk 101\", \"minutes\": [4, 13]}", nullptr) == 0);
    CHECK(ev.wait("done", &done, &b, 60000));
    std::string text;
    for (auto& e : ev.snapshot())
        if (e["type"] == "token") text += e.value("text", "");
    std::printf("  answer: %s\n", text.c_str());
    CHECK(done.value("stop", "") == "eog");
    CHECK(done.value("kind", "") == "tool_result");
    CHECK(text.find('4') != std::string::npos);
    CHECK(ev.count("token", mark) > 0);
    CHECK(status(h).value("awaiting_tool", true) == false);
    // the exchange is in the conversation: a follow-up knows which bus it was
    const size_t m2 = ev.size();
    CHECK(ce_ask(h, "Which bus number did I just ask about? Answer with the number only.", 0) == 0);
    CHECK(ev.wait("done", &done, &b, 60000));
    std::string follow;
    for (size_t i = m2; i < ev.size(); i++) {
        auto e = ev.snapshot()[i];
        if (e["type"] == "token") follow += e.value("text", "");
    }
    std::printf("  follow-up: %s\n", follow.c_str());
    CHECK(follow.find("858") != std::string::npos);
    CHECK(ev.count("error", start) == 0);
    ce_close(h);
}

TEST(tools_result_spoken_as_a_fixed_sentence) {
    std::remove(kWav);
    Events ev;
    void* h = open_tools(ev, true);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, "When is bus 858 coming?", 0) == 0);
    size_t a = 0, b = 0, s = 0;
    json call, done, end;
    CHECK(ev.wait("tool_call", &call, &a, 60000));
    CHECK(ev.wait("done", &done, &b, 60000));
    CHECK(ev.wait("sound_end", &end, &s, 20000));  // the call's answer has no sound, but still one end
    CHECK(end.value("sound_ms", 1.0) == 0.0);
    CHECK(ce_tool_result(h, "{\"service\": \"858\", \"minutes\": [4, 13]}", "Bus 858 comes in 4 minutes.") == 0);
    CHECK(ev.wait("done", &done, &b, 60000));
    CHECK(ev.wait("sound_end", &end, &s, 30000));
    std::printf("  say: frames %d, sound %.0f ms, stop %s\n", done.value("frames", 0), end.value("sound_ms", 0.0),
                done.value("stop", "").c_str());
    CHECK(done.value("stop", "") == "eog");
    CHECK(done.value("kind", "") == "tool_result");
    CHECK(done.value("frames", 0) > 10);              // about 2 s of speech for a short sentence
    CHECK(end.value("sound_ms", 0.0) > 800);
    CHECK(end.value("sound_ms", 0.0) < 8000);          // the sentence, not a story
    CHECK(file_size(kWav) > 44 + 24000);               // real samples reached the speaker
    CHECK(status(h).value("awaiting_tool", true) == false);
    ce_close(h);
}

TEST(tools_say_speaks_text) {
    std::remove(kWav);
    Events ev;
    void* h = open_tools(ev, true);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_say(h, "In thirty metres, turn left at the bus stop.") == 0);
    size_t b = 0, s = 0;
    json done, end;
    CHECK(ev.wait("done", &done, &b, 60000));
    CHECK(ev.wait("sound_end", &end, &s, 30000));
    std::printf("  say: ttft %.0f ms, frames %d, sound %.0f ms, n_text %d, stop %s\n", done.value("ttft_ms", 0.0),
                done.value("frames", 0), end.value("sound_ms", 0.0), done.value("n_out", 0), done.value("stop", "").c_str());
    CHECK(done.value("stop", "") == "eog");
    CHECK(done.value("kind", "") == "say");
    CHECK(end.value("sound_ms", 0.0) > 1000);
    CHECK(end.value("sound_ms", 0.0) < 10000);
    // say leaves the conversation alone: an ask afterwards still works and makes no call
    CHECK(ce_ask(h, "What is two plus two? Answer in a few words.", 0) == 0);
    CHECK(ev.wait("done", &done, &b, 60000));
    CHECK(done.value("stop", "") == "eog");
    ce_close(h);
}

TEST(tools_say_without_speaker_fails) {
    Events ev;
    void* h = open_tools(ev, false);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_say(h, "Hello.") == -1);
    ce_close(h);
}

TEST(tools_state_line) {
    Events ev;
    void* h = open_tools(ev, false);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_set_state(h, "mode=OUTDOOR_NAV; next=turn left at Yishun Ave 2 in 40 m") == 0);
    CHECK(ce_ask(h, "What do I do next? Answer in one short sentence.", 0) == 0);
    size_t b = 0;
    json done;
    CHECK(ev.wait("done", &done, &b, 60000));
    std::string text;
    for (auto& e : ev.snapshot())
        if (e["type"] == "token") text += e.value("text", "");
    std::printf("  answer: %s\n", text.c_str());
    CHECK(text.find("left") != std::string::npos || text.find("Left") != std::string::npos ||
          ev.count("tool_call") > 0);
    CHECK(ce_set_state(h, "") == 0);  // cleared
    ce_close(h);
}

TEST(tools_say_length_follows_the_text) {
    Events ev;
    void* h = open_tools(ev, true);
    CHECK(h != nullptr);
    if (!h) return;
    int frames[2] = {0, 0};
    const char* texts[2] = {"Stop.",
                            "Walk straight for two hundred metres, then turn right at the traffic light and cross "
                            "the road to the bus stop opposite the market."};
    size_t b = 0, s = 0;
    for (int i = 0; i < 2; i++) {
        std::remove(kWav);
        CHECK(ce_say(h, texts[i]) == 0);
        json done, end;
        CHECK(ev.wait("done", &done, &b, 60000));
        CHECK(ev.wait("sound_end", &end, &s, 30000));
        frames[i] = done.value("frames", 0);
        std::printf("  \"%.20s...\": %d frames\n", texts[i], frames[i]);
        if (i == 1) std::rename(kWav, "/tmp/ce_tools_long.wav");
    }
    CHECK(frames[0] > 0 && frames[0] < 25);  // "Stop." is well under 2 s
    CHECK(frames[1] > 3 * frames[0]);
    ce_close(h);
}
