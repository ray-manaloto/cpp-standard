# M0 (g) spike

`splice.cpp` and `tmpl.cpp` use the splice forms the design will need.
Each was formatted with clang-format 23.1.5 (`--style=LLVM`), and both the
original and the formatted file were built and run with the p2996
toolchain from spike-m0-h run 43509894509, in `ubuntu:26.10`:

```sh
clang-format --style=LLVM splice.cpp > compact.cpp
clang++ -std=c++26 -freflection-latest -stdlib=libc++ \
  -Wl,-rpath,<prefix>/lib/aarch64-unknown-linux-gnu splice.cpp -o splice
```

Both spellings print `3 7 5 9` (splice) or return 0 (tmpl). Results are in
`spikes/m0/README.md`. Deleted after M0.

`tsan.cpp` is the (c) TSan check, run the same way with
`-fsanitize=thread -g`; it reports a data race on line 5.
