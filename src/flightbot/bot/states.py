from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Shared flow for /new, /search and /explore. Every step has its own state; the FSM data holds
    `step` (current step), `history` (previous steps for the back button) and `purpose`."""

    dest = State()
    origin = State()
    when = State()
    date = State()
    trip = State()
    ret = State()
    direct = State()
    target = State()
    x_when = State()  # explore: month selection
    x_list = State()  # explore: list of destinations
    x_detail = State()  # explore: the selected destination
    s_result = State()  # search: result
    edit_target = State()  # change the target of an existing watch
