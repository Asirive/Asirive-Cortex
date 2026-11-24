// Minimal test registry for engine_tests (no external framework on the box).
//   TEST(name) { CHECK(cond); CHECK_NEAR(a, b, tol); }
//   engine_tests [filter]   runs every test whose name contains filter; exit code = failed tests.
#pragma once
#include <cmath>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace check {
struct Case { const char* name; std::function<void()> fn; };
inline std::vector<Case>& registry() { static std::vector<Case> r; return r; }
inline int& failures() { static int f = 0; return f; }
struct Reg { Reg(const char* n, std::function<void()> f) { registry().push_back({n, std::move(f)}); } };
}  // namespace check

#define CHECK_CAT2(a, b) a##b
#define CHECK_CAT(a, b) CHECK_CAT2(a, b)
#define TEST(name)                                                         \
    static void test_##name();                                             \
    static check::Reg CHECK_CAT(reg_, name)(#name, test_##name);           \
    static void test_##name()

#define CHECK(cond)                                                                        \
    do {                                                                                   \
        if (!(cond)) {                                                                     \
            std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                  \
            ++check::failures();                                                           \
        }                                                                                  \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                              \
    do {                                                                                   \
        double _a = (a), _b = (b);                                                         \
        if (!(std::fabs(_a - _b) <= (tol))) {                                              \
            std::printf("  FAIL %s:%d: %s = %g, %s = %g (tol %g)\n", __FILE__, __LINE__,   \
                        #a, _a, #b, _b, (double)(tol));                                    \
            ++check::failures();                                                           \
        }                                                                                  \
    } while (0)
