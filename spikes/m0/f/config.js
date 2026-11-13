// Self-hosted Renovate settings for the M0 (f) run. It only looks at the
// spike fixture and opens at most one PR, on a spike branch prefix. The
// mise entry is the one setting a repository's Renovate config needs:
// the mise manager matches only .config/mise/conf.d/*.toml by default
// (renovatebot/renovate lib/modules/manager/mise/config-files.ts).
module.exports = {
  platform: 'github',
  onboarding: false,
  requireConfig: 'ignored',
  enabledManagers: ['mise'],
  includePaths: ['spikes/m0/f/**'],
  branchPrefix: 'spike-m0f/',
  prHourlyLimit: 1,
  prConcurrentLimit: 1,
  // node 20.0.0 has minor and major updates; one PR keeps the check exact.
  separateMajorMinor: false,
  mise: {
    managerFilePatterns: ['/(^|/)\\.mise/conf\\.d/[^/]+\\.toml$/'],
  },
};
