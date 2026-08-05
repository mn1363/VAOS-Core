"""Infrastructure layer: adapters implementing domain and application Ports.

`infrastructure` may depend on `domain`, `application`, and `core`. Phase 1
ships this layer's structure and composition entrypoint only; concrete
adapters (databases, message brokers, external APIs) are added in later
phases.
"""
