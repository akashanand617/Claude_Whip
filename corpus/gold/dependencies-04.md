---
id: dependencies-04
dimension: dependencies
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

The daemon needs command-line flags: `--device <mac>` (required),
`--rate <hz>` (default 25), `--verbose`.

# Context

A C++17 daemon cross-compiled for the embedded target. The build currently
has no third-party code at all.

## A (handroll)

Three flags fit a plain argv loop; the embedded build stays free of
third-party code:

```cpp
struct Options { std::string device; int rate = 25; bool verbose = false; };

static void usage() {
    std::fprintf(stderr,
        "usage: ringd --device <mac> [--rate <hz>] [--verbose]\n");
    std::exit(2);
}

Options parse_args(int argc, char** argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--device" && i + 1 < argc)    opt.device = argv[++i];
        else if (arg == "--rate" && i + 1 < argc) opt.rate = std::atoi(argv[++i]);
        else if (arg == "--verbose")              opt.verbose = true;
        else usage();
    }
    if (opt.device.empty()) usage();
    return opt;
}
```

## B (library)

Vendor the single header `CLI11.hpp` and declare the options; `--help`,
required-option errors, and integer validation of `--rate` come free:

```cpp
#include "CLI11.hpp"

int main(int argc, char** argv) {
    CLI::App app{"ring daemon"};
    std::string device;
    int rate = 25;
    bool verbose = false;
    app.add_option("--device", device, "ring MAC address")->required();
    app.add_option("--rate", rate, "sample rate in Hz");
    app.add_flag("--verbose", verbose, "log every packet");
    CLI11_PARSE(app, argc, argv);
    run(device, rate, verbose);
}
```

Adds CLI11 as a vendored header-only dependency (no link-time cost).

# Notes

Both accept the same three flags with the same defaults, require `--device`,
and exit non-zero with a usage message on anything malformed. A owns twenty
lines and adds nothing to the embedded build; B vendors one well-known
header and gets generated help and typed validation. The axis is whether a
20-line need justifies a dependency, not correctness or effort.
