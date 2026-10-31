from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """/new, /search, /explore üçün ortaq axın. Hər addımın öz state-i var; FSM data-sında
    `step` (cari addım), `history` (geri düyməsi üçün əvvəlki addımlar), `purpose` saxlanılır."""

    dest = State()
    origin = State()
    when = State()
    date = State()
    trip = State()
    ret = State()
    direct = State()
    target = State()
    x_when = State()  # explore: ay seçimi
    x_list = State()  # explore: istiqamətlər siyahısı
    x_detail = State()  # explore: seçilmiş istiqamət
    s_result = State()  # search: nəticə
    edit_target = State()  # mövcud izləmənin hədəfini dəyişmək
