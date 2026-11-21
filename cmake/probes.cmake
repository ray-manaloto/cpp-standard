# The configure-time capability probes (D39, D42), started from cpp-utilities
# catalogue/cmake/ProfileCheck.cmake (D4) and reduced to what this repository's
# gate checks: the sanitizers, TSan and Valgrind of section 5 steps 6 and 7.
# Each
# probe sets one CPPSTD_HAS_<X> and the combined result goes to
# build/<preset>/capabilities.json, which `mise run ci:caps` compares with
# cmake/capabilities.lock.json; probe and adapt stays for the build (D39).
#
# The sanitizer probes compile, link and run, because a flag can compile and
# still miss its runtime, and they run with the preset's own sanitizer flags
# held out of CMAKE_CXX_FLAGS and CMAKE_EXE_LINKER_FLAGS, so one sanitizer's
# build can probe another. The Valgrind probe looks for the tool, gcc16 only
# (D37): the shared image installs Valgrind on every compiler's PATH, and the
# lock records it for gcc16 alone. A compiler the lock does not name makes the
# probe file say "unknown" (a warning, not fatal) and the comparison with the
# lock fails.

include(CheckCXXSourceRuns)

# The compiler the preset builds with: the chainload toolchain file names it
# (cmake/toolchains/<name>.cmake); the compiler path decides for a configure
# without the presets.
set(_cppstd_toolchain "")
set(_cppstd_p2996_bin "$ENV{CPPSTD_P2996_PREFIX}/bin")
cmake_path(IS_PREFIX _cppstd_p2996_bin "${CMAKE_CXX_COMPILER}"
           _cppstd_using_p2996)
if(VCPKG_CHAINLOAD_TOOLCHAIN_FILE)
  get_filename_component(
    _cppstd_toolchain "${VCPKG_CHAINLOAD_TOOLCHAIN_FILE}"
    NAME_WE)
endif()
if(_cppstd_toolchain MATCHES "^(gcc16|clang23|p2996)$")
  set(CPPSTD_COMPILER_NAME "${_cppstd_toolchain}")
elseif(NOT "$ENV{CPPSTD_P2996_PREFIX}" STREQUAL "" AND _cppstd_using_p2996)
  set(CPPSTD_COMPILER_NAME "p2996")
elseif(CMAKE_CXX_COMPILER MATCHES "(clang|clang\\+\\+)-?23")
  set(CPPSTD_COMPILER_NAME "clang23")
elseif(CMAKE_CXX_COMPILER MATCHES "(g\\+\\+|gcc)-16")
  set(CPPSTD_COMPILER_NAME "gcc16")
else()
  # A configure with no gate preset may use a compiler the capability lock does
  # not name (D42); an ordinary configure is not fatal for that. The probe file
  # still names the compiler, so the comparison with the lock fails for it: a
  # gate run on a compiler the lock has no entry for never passes (D42).
  set(CPPSTD_COMPILER_NAME "unknown")
  message(
    WARNING
      "the capability probes name no compiler (CMAKE_CXX_COMPILER: "
      "${CMAKE_CXX_COMPILER}); the capability lock has no entry for it, so "
      "`mise run ci:caps` fails this build tree")
endif()

set(_cppstd_probe_src "int main() { return 0; }\n")
# The probes see the compiler alone: the preset's own -fsanitize flags stand in
# CMAKE_CXX_FLAGS and CMAKE_EXE_LINKER_FLAGS (cmake/presets/checks.json), and a
# sanitizer refuses to share a build with another, so an ASan+UBSan configure
# could never probe TSan, or a TSan configure ASan, while the preset's flags
# were in place. Strip only the sanitizer switches inside the probe scope.
block()
  foreach(_flags IN ITEMS CMAKE_CXX_FLAGS CMAKE_EXE_LINKER_FLAGS)
    string(REGEX REPLACE "-fsanitize=[^ 	]+" "" ${_flags} "${${_flags}}")
  endforeach()
  foreach(cap IN ITEMS ASAN UBSAN TSAN)
    unset(CPPSTD_HAS_${cap} CACHE)
  endforeach()
  set(CMAKE_REQUIRED_FLAGS "-fsanitize=address")
  check_cxx_source_runs("${_cppstd_probe_src}" CPPSTD_HAS_ASAN)
  set(CMAKE_REQUIRED_FLAGS
      "-fsanitize=undefined -fno-sanitize-recover=undefined")
  check_cxx_source_runs("${_cppstd_probe_src}" CPPSTD_HAS_UBSAN)
  set(CMAKE_REQUIRED_FLAGS "-fsanitize=thread")
  check_cxx_source_runs("${_cppstd_probe_src}" CPPSTD_HAS_TSAN)
endblock()

# Valgrind is gcc16's check on Linux (D37): the shared image installs it, so it
# is on every compiler's PATH and a plain find_program would report it for all
# of them while the lock keeps it gcc16-only, with its skip_reason (D42). Only
# gcc16 is probed; the others are false without a probe.
if(CPPSTD_COMPILER_NAME STREQUAL "gcc16" AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
  unset(CPPSTD_VALGRIND_EXECUTABLE CACHE)
  find_program(
    CPPSTD_VALGRIND_EXECUTABLE valgrind
    DOC "The Valgrind tool for the gate's memcheck")
  if(CPPSTD_VALGRIND_EXECUTABLE)
    set(CPPSTD_HAS_VALGRIND TRUE)
  else()
    set(CPPSTD_HAS_VALGRIND FALSE)
  endif()
else()
  set(CPPSTD_HAS_VALGRIND FALSE)
endif()

# This environment, as the capability lock names it: <system>-<arch> with the
# repository's names (linux, macos; arm64, amd64).
string(TOLOWER "${CMAKE_SYSTEM_NAME}" _cppstd_system)
if(_cppstd_system STREQUAL "darwin")
  set(_cppstd_system "macos")
endif()
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
  set(_cppstd_arch "arm64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64")
  set(_cppstd_arch "amd64")
else()
  set(_cppstd_arch "${CMAKE_SYSTEM_PROCESSOR}")
endif()
set(CPPSTD_ENVIRONMENT_NAME "${_cppstd_system}-${_cppstd_arch}")
unset(_cppstd_system)
unset(_cppstd_arch)

set(_cppstd_caps_asan "false")
if(CPPSTD_HAS_ASAN)
  set(_cppstd_caps_asan "true")
endif()
set(_cppstd_caps_ubsan "false")
if(CPPSTD_HAS_UBSAN)
  set(_cppstd_caps_ubsan "true")
endif()
set(_cppstd_caps_tsan "false")
if(CPPSTD_HAS_TSAN)
  set(_cppstd_caps_tsan "true")
endif()
set(_cppstd_caps_valgrind "false")
if(CPPSTD_HAS_VALGRIND)
  set(_cppstd_caps_valgrind "true")
endif()

# CMake places each preset in build/<preset>; direct gate runs name it
# explicitly.
if(NOT DEFINED CPPSTD_GATE_PRESET)
  get_filename_component(CPPSTD_GATE_PRESET "${CMAKE_BINARY_DIR}" NAME)
endif()
if(NOT CPPSTD_GATE_PRESET MATCHES "^[a-z0-9]+-[a-z-]+$")
  set(CPPSTD_GATE_PRESET "unknown")
endif()

set(_cppstd_caps_json
    "{
  \"preset\": \"${CPPSTD_GATE_PRESET}\",
  \"compiler\": \"${CPPSTD_COMPILER_NAME}\",
  \"environment\": \"${CPPSTD_ENVIRONMENT_NAME}\",
  \"capabilities\": {
    \"asan\": ${_cppstd_caps_asan},
    \"ubsan\": ${_cppstd_caps_ubsan},
    \"tsan\": ${_cppstd_caps_tsan},
    \"valgrind\": ${_cppstd_caps_valgrind}
  }
}
")
file(WRITE "${CMAKE_BINARY_DIR}/capabilities.json" "${_cppstd_caps_json}")
message(
  STATUS
    "capability probes (${CPPSTD_COMPILER_NAME}, ${CPPSTD_ENVIRONMENT_NAME}): "
    "asan=${_cppstd_caps_asan} ubsan=${_cppstd_caps_ubsan} "
    "tsan=${_cppstd_caps_tsan} valgrind=${_cppstd_caps_valgrind}")
unset(_cppstd_caps_json)
unset(_cppstd_caps_asan)
unset(_cppstd_caps_ubsan)
unset(_cppstd_caps_tsan)
unset(_cppstd_caps_valgrind)
unset(_cppstd_probe_src)
unset(_cppstd_toolchain)
unset(_cppstd_p2996_bin)
unset(_cppstd_using_p2996)
