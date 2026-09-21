class AppException(Exception):
    """Base application error — rendered as {"detail": message} by handlers."""

    status_code: int = 400

    def __init__(self, message: str | None = None):
        self.message = message or self.__class__.__name__
        super().__init__(self.message)


class ThreadNotFoundException(AppException):
    status_code = 404

    def __init__(self, thread_id: str):
        super().__init__(f"Thread not found: {thread_id}")


class InvalidThreadIdException(AppException):
    status_code = 400

    def __init__(self, thread_id: str):
        super().__init__(f"Invalid thread id: {thread_id}")


class NoTurnToModifyException(AppException):
    status_code = 400

    def __init__(self, thread_id: str):
        super().__init__(f"No turn to modify in thread: {thread_id}")


class ThreadBusyException(AppException):
    status_code = 409

    def __init__(self, thread_id: str):
        super().__init__(
            f"Thread is busy generating a response; retry shortly: {thread_id}"
        )


class AgentNotInitializedException(AppException):
    status_code = 503

    def __init__(self):
        super().__init__("Agent service is not initialized")
