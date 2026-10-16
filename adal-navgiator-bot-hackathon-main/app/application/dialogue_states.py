from enum import StrEnum


class DialogueState(StrEnum):
    AWAIT_DESCRIPTION = "await_description"
    AWAIT_CONFIRMATION = "await_confirmation"
    AWAIT_CLARIFICATION = "await_clarification"


CLARIFICATION_QUESTIONS = {
    "city": "clarify_city",
    "location_type": "clarify_location_type",
    "issue_details": "clarify_issue_details",
}
