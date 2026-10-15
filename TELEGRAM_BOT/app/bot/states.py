from aiogram.fsm.state import State, StatesGroup


class QuestionState(StatesGroup):
    """FSM состояния для процесса отправки вопроса."""

    waiting_for_question = State()
