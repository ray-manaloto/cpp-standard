// The must-fail fixture: exported, built with coverage, never called.
export module uncovered;

export int never_called(int x) {
  return x * 3 + 1;
}
