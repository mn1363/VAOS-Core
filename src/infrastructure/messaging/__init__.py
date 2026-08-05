"""Messaging adapters for task queues and event delivery.

This package intentionally ships without concrete adapters in Phase 1.
Future adapters (e.g. an async task queue) should live here and implement
dispatch to `application.interfaces.task.TaskHandler` instances.
"""
