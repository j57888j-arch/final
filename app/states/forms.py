from aiogram.fsm.state import State, StatesGroup


class TopUpStates(StatesGroup):
    amount = State()
    proof = State()


class PromoStates(StatesGroup):
    code = State()


class SupportStates(StatesGroup):
    message = State()


class AdminCountryStates(StatesGroup):
    name = State()
    emoji = State()
    description = State()


class AdminServiceStates(StatesGroup):
    country_id = State()
    name = State()
    description = State()
    price = State()
    stock = State()
    stars_price = State()
    digital = State()


class AdminStockStates(StatesGroup):
    service_id = State()
    quantity = State()


class AdminInventoryImportStates(StatesGroup):
    service_id = State()
    file = State()


class AdminBroadcastStates(StatesGroup):
    message = State()
    button_text = State()
    button_url = State()


class AdminSearchStates(StatesGroup):
    query = State()


class AdminPromoStates(StatesGroup):
    code = State()
    discount_type = State()
    discount_value = State()
    max_uses = State()
    expiry_days = State()


class AdminEditServiceStates(StatesGroup):
    price = State()
