"""Task handler Port used to execute `Task` entities."""

from abc import ABC, abstractmethod

from domain.entities.task import Task


class TaskHandler(ABC):
    """Executes `Task` entities of a specific, named kind."""

    @property
    @abstractmethod
    def task_name(self) -> str:
        """Name of the task kind this handler is able to execute.

        Returns:
            The task name this handler is registered for.
        """
        ...

    @abstractmethod
    async def handle(self, task: Task) -> None:
        """Execute the given task.

        Args:
            task: The task instance to execute.
        """
        ...
