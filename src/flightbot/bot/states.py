from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Shared flow for /new, /search and /explore. Every step has its own state; the FSM data holds
    `step` (current step), `history` (previous steps for the back button) and `purpose`."""

    dest = State()
    origin = State()
    trip = State()  # one way / round trip with N days / pick dates on a calendar
    when = State()  # month selection
    cal_dep = State()  # calendar: departure date
    cal_ret = State()  # calendar: return date
    target = State()
    x_when = State()  # explore: month selection
    x_list = State()  # explore: list of destinations
    x_detail = State()  # explore: the selected destination
    s_result = State()  # search: result
    edit_target = State()  # change the target of an existing watch
