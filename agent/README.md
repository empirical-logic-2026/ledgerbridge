# Connector agent (placeholder)

Lightweight service installed on the machine running Tally (or near other on-premise sources). It polls the local source and pushes changes outbound over HTTPS to the client deployment, with a local queue for outages (architecture.md §4.5, requirement SYN-004, ADR-006).

Deferred to Phase 1b. During the pilot the data plane reaches Tally directly at `TALLY_URL`.
