from dataclasses import dataclass


@dataclass
class DirectorError(Exception):
    code: str
    message: str
    status: int = 400

    def __str__(self) -> str:
        return self.message


class SubmissionUncertain(DirectorError):
    def __init__(self, message: str = "The provider may have accepted this request. Do not resubmit. Check the provider console and reconcile the task ID."):
        super().__init__("SUBMISSION_UNCERTAIN", message, 502)
