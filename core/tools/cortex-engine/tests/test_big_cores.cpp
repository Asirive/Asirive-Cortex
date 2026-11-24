// The big-core gate between an answer and the vision islands.
#include <atomic>
#include <chrono>
#include <thread>

#include "../src/big_cores.h"
#include "check.h"

using namespace std::chrono;

TEST(big_cores_island_goes_small_during_ask) {
    ce::BigCores big;
    big.ask_enter();
    const auto t = steady_clock::now();
    const bool got_big = big.island_enter();
    const double waited = duration<double, std::milli>(steady_clock::now() - t).count();
    CHECK(!got_big);
    CHECK(waited < 5);
    big.island_exit(false);
    big.ask_exit();
    CHECK(big.island_enter());
    big.island_exit(true);
}

TEST(big_cores_ask_waits_for_big_island) {
    ce::BigCores big;
    CHECK(big.island_enter());
    std::atomic<bool> in{false};
    std::thread t([&] {
        big.ask_enter();
        in = true;
    });
    std::this_thread::sleep_for(milliseconds(30));
    CHECK(!in.load());
    big.island_exit(true);
    t.join();
    CHECK(in.load());
    // a small island does not hold the big cores
    CHECK(!big.island_enter());
    big.island_exit(false);
    big.ask_exit();
}
