from aiogram.filters.callback_data import CallbackData


class PlaceCb(CallbackData, prefix="pl"):
    role: str  # 'o' (origin) | 'd' (destination)
    code: str


class MonthCb(CallbackData, prefix="mo"):
    which: str  # 'dep' | 'ret'
    ym: str  # 'YYYY-MM'


class TripCb(CallbackData, prefix="tr"):
    round_trip: int


class DirectCb(CallbackData, prefix="dr"):
    direct: int


class TargetCb(CallbackData, prefix="tg"):
    cents: int  # hədəf qiymət * 100 (onluq hissəni itirməmək üçün)
    force: int = 0  # 1 = "artıq hədəfdən aşağıdır" xəbərdarlığı təsdiqlənib


class EditTargetCb(CallbackData, prefix="et"):
    cents: int


class WatchCb(CallbackData, prefix="wt"):
    action: str  # 'pause' | 'resume' | 'del' | 'edit' | 'npause' (bildirişdən dayandır)
    id: int


class NavCb(CallbackData, prefix="nv"):
    action: str  # 'back' | 'cancel'


class GoCb(CallbackData, prefix="go"):
    to: str  # 'origin' | 'exact' | 'advanced' | 'explore' | 'watch' | 'retarget' | 'sethome'


class ExploreCb(CallbackData, prefix="xp"):
    i: int


class LangCb(CallbackData, prefix="lg"):
    lang: str


class CurCb(CallbackData, prefix="cu"):
    cur: str


class QuietCb(CallbackData, prefix="qh"):
    x: int = 1


class MenuCb(CallbackData, prefix="mn"):
    action: str  # 'new' | 'explore' | 'search' | 'list'


class DeleteCb(CallbackData, prefix="del"):
    action: str  # 'confirm' | 'cancel'
