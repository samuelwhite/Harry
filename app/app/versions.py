# app/versions.py

# -----------------------------------------------------------------------------
# Harry version model
# -----------------------------------------------------------------------------
# Harry deliberately uses separate version tracks for different concerns:
#
#   BRAIN_VERSION
#     Calendar version for the Brain application itself.
#
#   AGENT_VERSION
#     Semantic-ish version for the distributed agent script served from /dist.
#
# Schema version is not declared here directly because the Brain reads the
# active schema from schemas/harry/current.json at startup. That keeps schema
# activation file-based and visible to operators.
# -----------------------------------------------------------------------------

# Brain release version (calendar versioning)
BRAIN_VERSION = "2026.03.18"

# Distributed agent script version (not the schema version)
AGENT_VERSION = "0.2.3"

# -----------------------------------------------------------------------------
# Schema mismatch escalation policy
# -----------------------------------------------------------------------------
# Agents may be temporarily behind during rolling updates. Harry therefore does
# not treat a fresh mismatch as immediately critical.
#
# These thresholds allow compute_health() to distinguish:
#   - short-lived rollout lag
#   - sustained "node is not updating" behaviour
# -----------------------------------------------------------------------------
SCHEMA_BEHIND_WARN_MIN = 15
SCHEMA_BEHIND_CRIT_MIN = 60
