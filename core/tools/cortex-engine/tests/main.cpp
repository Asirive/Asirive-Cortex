#include <cstring>

#include "check.h"

int main(int argc, char** argv) {
    const char* filter = argc > 1 ? argv[1] : "";
    int passed = 0, failed = 0;
    for (auto& c : check::registry()) {
        if (*filter && !std::strstr(c.name, filter)) continue;
        int before = check::failures();
        std::printf("[ RUN  ] %s\n", c.name);
        std::fflush(stdout);
        c.fn();
        if (check::failures() == before) {
            ++passed;
            std::printf("[  OK  ] %s\n", c.name);
        } else {
            ++failed;
            std::printf("[ FAIL ] %s\n", c.name);
        }
        std::fflush(stdout);
    }
    std::printf("%d passed, %d failed\n", passed, failed);
    return failed;
}
