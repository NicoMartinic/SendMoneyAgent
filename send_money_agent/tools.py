"""Send Money Agent tools with strict validation and safe mock transfer logic."""

from decimal import Decimal, InvalidOperation
import random
import unicodedata
from typing import Optional
from google.adk.tools import ToolContext

# ──────────────────────────────────────────────
# Simulated data
# ──────────────────────────────────────────────

SUPPORTED_COUNTRIES: dict[str, dict] = {
    "Mexico":      {"currency": "MXN", "rate": 17.20,  "methods": ["bank_transfer", "cash_pickup", "mobile_wallet"]},
    "Colombia":    {"currency": "COP", "rate": 4100.0,  "methods": ["bank_transfer", "cash_pickup"]},
    "Philippines": {"currency": "PHP", "rate": 58.00,   "methods": ["bank_transfer", "mobile_wallet"]},
    "India":       {"currency": "INR", "rate": 83.50,   "methods": ["bank_transfer", "upi"]},
    "Brazil":      {"currency": "BRL", "rate": 5.10,    "methods": ["bank_transfer", "pix"]},
    "Nigeria":     {"currency": "NGN", "rate": 1580.0,  "methods": ["bank_transfer", "mobile_money"]},
    "Kenya":       {"currency": "KES", "rate": 130.0,   "methods": ["mobile_money", "bank_transfer"]},
    "Guatemala":   {"currency": "GTQ", "rate": 7.80,    "methods": ["cash_pickup", "bank_transfer"]},
    "El Salvador": {"currency": "USD", "rate": 1.00,    "methods": ["bank_transfer", "cash_pickup"]},
    "Honduras":    {"currency": "HNL", "rate": 24.70,   "methods": ["cash_pickup", "bank_transfer"]},
    "Ecuador":     {"currency": "USD", "rate": 1.00,    "methods": ["bank_transfer", "cash_pickup"]},
    "Peru":        {"currency": "PEN", "rate": 3.75,    "methods": ["bank_transfer", "cash_pickup", "mobile_wallet"]},
}

# Common aliases / abbreviations → canonical country name
_COUNTRY_ALIASES: dict[str, str] = {
    "phil":         "Philippines",
    "phils":        "Philippines",
    "philippine":   "Philippines",
    "mex":          "Mexico",
    "col":          "Colombia",
    "colombie":     "Colombia",
    "brasil":       "Brazil",
    "br":           "Brazil",
    "elsalvador":   "El Salvador",   # no-space variant
    "salvador":     "El Salvador",
    "guat":         "Guatemala",
    "hondura":      "Honduras",
    "nig":          "Nigeria",
    "naija":        "Nigeria",
    "ecu":          "Ecuador",
}

# Canonical delivery-method keys → accepted free-text variants (lowercase)
_DELIVERY_METHOD_ALIASES: dict[str, list[str]] = {
    "bank_transfer":  [
        "bank transfer", "bank", "wire", "wire transfer", "ach", "bank_transfer",
        "transferencia bancaria", "transferencia",
    ],
    "cash_pickup":    [
        "cash pickup", "cash pick up", "cash", "pickup", "cash_pickup",
        "retiro en efectivo", "cobro en efectivo", "efectivo",
    ],
    "mobile_wallet":  [
        "mobile wallet", "mobile_wallet", "wallet", "ewallet", "e-wallet", "mobile",
        "billetera movil", "cartera movil", "monedero movil",
    ],
    "mobile_money":   [
        "mobile money", "mobile_money", "mpesa", "m-pesa",
        "dinero movil",
    ],
    "upi":            ["upi", "unified payment", "unified payments interface"],
    "pix":            ["pix"],
}

_SOURCE_AMOUNT_CURRENCY_ALIASES: dict[str, list[str]] = {
    "USD": [
        "usd",
        "us dollar",
        "us dollars",
        "dollar",
        "dollars",
        "$",
        "us$",
        "u$s",
        "dolar",
        "dolares",
        "dolar estadounidense",
        "dolares estadounidenses",
        "dólar",
        "dólares",
        "dólar estadounidense",
        "dólares estadounidenses",
    ],
}

_DELIVERY_METHOD_DISPLAY: dict[str, dict[str, str]] = {
    "bank_transfer": {"en": "Bank Transfer", "es": "Transferencia bancaria"},
    "cash_pickup": {"en": "Cash Pickup", "es": "Retiro en efectivo"},
    "mobile_wallet": {"en": "Mobile Wallet", "es": "Billetera móvil"},
    "mobile_money": {"en": "Mobile Money", "es": "Dinero móvil"},
    "upi": {"en": "UPI", "es": "UPI"},
    "pix": {"en": "PIX", "es": "PIX"},
}

MIN_AMOUNT_USD = 10.00
MAX_AMOUNT_USD = 10_000.0
SOURCE_AMOUNT_CURRENCY = "USD"
REQUIRED_TRANSFER_FIELDS = (
    "recipient_name",
    "recipient_country",
    "amount_usd",
    "delivery_method",
)

_EMPTY_STATE: dict = {
    "recipient_name":    None,
    "recipient_country": None,
    "amount_usd":        None,
    "delivery_method":   None,
    "status":            "in_progress",
    "state_version":     0,
}

_READ_CONTRACT_KEY = "_transfer_read_contract"
ERROR_FRESH_STATE_REQUIRED = "FRESH_STATE_REQUIRED"
ERROR_STALE_STATE = "STALE_STATE"
ERROR_CONFIRMED_TRANSFER_IMMUTABLE = "CONFIRMED_TRANSFER_IMMUTABLE"
ERROR_UNSUPPORTED_SOURCE_AMOUNT_CURRENCY = "UNSUPPORTED_SOURCE_AMOUNT_CURRENCY"


# ──────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────

def _get_state(tool_context: ToolContext) -> dict:
    state = dict(_EMPTY_STATE)
    state.update(tool_context.state.get("transfer_state", {}))
    if not isinstance(state.get("state_version"), int) or state["state_version"] < 0:
        state["state_version"] = 0
    return state


def _save_state(tool_context: ToolContext, state: dict) -> None:
    tool_context.state["transfer_state"] = state


def _issue_read_token(tool_context: ToolContext, state_version: int) -> str:
    token = f"rtok_{state_version}_{random.randint(100000, 999999)}"
    tool_context.state[_READ_CONTRACT_KEY] = {
        "latest_read_token": token,
        "token_version": state_version,
    }
    return token


def _invalidate_read_token(tool_context: ToolContext) -> None:
    tool_context.state[_READ_CONTRACT_KEY] = {
        "latest_read_token": None,
        "token_version": None,
    }


def _fresh_state_required_error(state_version: int) -> dict:
    return {
        "success": False,
        "error_code": ERROR_FRESH_STATE_REQUIRED,
        "error": (
            "A fresh read is required. Call get_transfer_state first, then retry "
            "with read_token and expected_version from that response."
        ),
        "state_version": state_version,
    }


def _stale_state_error(state_version: int, expected_version: int) -> dict:
    return {
        "success": False,
        "error_code": ERROR_STALE_STATE,
        "error": (
            f"Stale write detected: expected_version={expected_version}, "
            f"current state_version={state_version}."
        ),
        "state_version": state_version,
    }


def _confirmed_transfer_immutable_error(state: dict) -> dict:
    return {
        "success": False,
        "error_code": ERROR_CONFIRMED_TRANSFER_IMMUTABLE,
        "error": (
            "This transfer has already been confirmed and can no longer be edited. "
            "If the user wants different details, explain that the confirmed transfer "
            "is final and offer to start a new transfer instead."
        ),
        "status": state.get("status"),
        "reference_number": state.get("reference_number"),
        "state_version": state.get("state_version"),
        "action_required": "offer_new_transfer",
    }


def _validate_fresh_state(
    tool_context: ToolContext,
    read_token: Optional[str],
    expected_version: Optional[int],
) -> tuple[bool, dict | None, dict]:
    state = _get_state(tool_context)
    contract = tool_context.state.get(_READ_CONTRACT_KEY, {})
    latest_token = contract.get("latest_read_token")

    if read_token is None or expected_version is None:
        return False, _fresh_state_required_error(state["state_version"]), state

    if latest_token is None or read_token != latest_token:
        return False, _fresh_state_required_error(state["state_version"]), state

    if expected_version != state["state_version"]:
        return False, _stale_state_error(state["state_version"], expected_version), state

    return True, None, state


def _normalize_country(name: str) -> Optional[str]:
    """
    Return the canonical country name or None.
    Resolution order:
      1. Exact case-insensitive match against canonical names.
      2. Alias lookup (stripped of spaces/punctuation).
      3. Prefix match (≥4 chars) against canonical names — catches typos.
    """
    stripped = name.strip()
    lower = stripped.lower()

    # 1. Exact match
    for canonical in SUPPORTED_COUNTRIES:
        if canonical.lower() == lower:
            return canonical

    # 2. Alias map (normalise away spaces/hyphens for alias key lookup)
    alias_key = lower.replace(" ", "").replace("-", "")
    if alias_key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[alias_key]

    # 3. Prefix match (only if input is at least 4 characters)
    if len(lower) >= 4:
        for canonical in SUPPORTED_COUNTRIES:
            if canonical.lower().startswith(lower):
                return canonical

    return None


def _normalize_text_key(raw: str) -> str:
    """
    Normalize user-entered text for robust matching:
      - trim + lowercase
      - collapse internal whitespace
      - remove accents/diacritics
    """
    lowered = " ".join(raw.split()).strip().lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalize_delivery_method(raw: str) -> Optional[str]:
    """
    Map free-text delivery method input to a canonical key, or return None.
    E.g. "mobile wallet", "Mobile Wallet", "wallet" → "mobile_wallet".
    """
    key = _normalize_text_key(raw)
    for canonical, aliases in _DELIVERY_METHOD_ALIASES.items():
        if key == canonical:
            return canonical
        if any(key == _normalize_text_key(alias) for alias in aliases):
            return canonical
    return None


def _normalize_source_amount_currency(raw: str) -> Optional[str]:
    """Map free-text source amount currency input to a canonical key, or return None."""
    key = _normalize_text_key(raw)
    for canonical, aliases in _SOURCE_AMOUNT_CURRENCY_ALIASES.items():
        normalized_candidates = {_normalize_text_key(canonical)}
        normalized_candidates.update(_normalize_text_key(alias) for alias in aliases)
        if key in normalized_candidates:
            return canonical
    return None


def _amount_has_more_than_two_decimals(raw_amount: float) -> bool:
    """Return True when the provided amount uses more than two decimal places."""
    try:
        normalized = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return True
    return normalized.as_tuple().exponent < -2


def _localize_delivery_method(method_key: str, active_language: Optional[str]) -> str:
    """Return a user-facing delivery-method label in the active session language."""
    localized = _DELIVERY_METHOD_DISPLAY.get(method_key, {})
    if active_language in localized:
        return localized[active_language]
    if "en" in localized:
        return localized["en"]
    return method_key.replace("_", " ").title()


def _name_seems_incomplete(name: str) -> bool:
    """
    Return True when a name appears to be first-name-only or title-only.
    Rules:
      - Must have at least 2 parts after splitting.
      - At least 1 part must be a non-title word, so title + last-name inputs
        such as "Dr. Smith" and "Mr. Smith" are accepted.
      - Pure single-word input (even a title alone) is incomplete.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return True
    titles = {"mr", "ms", "mrs", "dr", "prof"}
    non_title_parts = [p for p in parts if p.rstrip(".").lower() not in titles]
    # At least one non-title word required (so "Mr. Smith" is OK, "Mr." alone fails)
    return len(non_title_parts) < 1


# ──────────────────────────────────────────────
# Public tools (called by the agent)
# ──────────────────────────────────────────────

def get_transfer_state(tool_context: ToolContext) -> dict:
    """Return current transfer state, missing fields, and fresh write tokens."""
    state = _get_state(tool_context)
    # Persist normalized/defaulted state so read-only calls also repair legacy session shape.
    _save_state(tool_context, state)
    read_token = _issue_read_token(tool_context, state["state_version"])
    required = list(REQUIRED_TRANSFER_FIELDS)
    missing = [f for f in required if not state.get(f)]

    # Extra guard: a saved name that is still incomplete counts as missing
    name = state.get("recipient_name")
    if name and _name_seems_incomplete(name) and "recipient_name" not in missing:
        missing.append("recipient_name")

    result = {
        **state,
        "missing_fields": missing,
        "is_complete": len(missing) == 0,
        "can_update_details": state.get("status") != "confirmed",
        "supported_source_amount_currencies": [SOURCE_AMOUNT_CURRENCY],
        "read_token": read_token,
        "expected_version": state["state_version"],
    }
    active_language = tool_context.state.get("active_language")
    if active_language in {"en", "es"}:
        result["active_language"] = active_language
    return result


def update_transfer_details(
    tool_context: ToolContext,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
    recipient_name: Optional[str] = None,
    recipient_country: Optional[str] = None,
    amount_usd: Optional[float] = None,
    source_amount_currency: Optional[str] = None,
    delivery_method: Optional[str] = None,
) -> dict:
    """Update provided transfer fields with validation, normalization, and state version checks."""
    if not any(
        value is not None
        for value in (
            recipient_name,
            recipient_country,
            amount_usd,
            source_amount_currency,
            delivery_method,
        )
    ):
        return {
            "success": False,
            "error": "No fields provided. Pass at least one field to update.",
        }

    is_fresh, error, state = _validate_fresh_state(tool_context, read_token, expected_version)
    if not is_fresh:
        return error  # type: ignore[return-value]

    if state.get("status") == "confirmed":
        return _confirmed_transfer_immutable_error(state)

    updated: list[str] = []
    ambiguity_warnings: list[str] = []
    validated_source_amount_currency: Optional[str] = None

    # ── source_amount_currency ──────────────────────────────────
    if source_amount_currency is not None:
        validated_source_amount_currency = _normalize_source_amount_currency(source_amount_currency)
        if validated_source_amount_currency != SOURCE_AMOUNT_CURRENCY:
            return {
                "success": False,
                "error_code": ERROR_UNSUPPORTED_SOURCE_AMOUNT_CURRENCY,
                "error": (
                    f"'{source_amount_currency}' is not a supported source currency. "
                    "Transfer amounts must be provided in USD."
                ),
                "field": "source_amount_currency",
                "supported_source_amount_currencies": [SOURCE_AMOUNT_CURRENCY],
                "action_required": "ask_user_for_amount_in_usd",
            }

    # ── recipient_name ──────────────────────────────────────────
    if recipient_name is not None:
        cleaned = " ".join(recipient_name.split()).title()  # collapse all whitespace
        if _name_seems_incomplete(cleaned):
            # Hard refusal: do NOT save; force the agent to ask for full name.
            return {
                "success": False,
                "error": (
                    f"'{cleaned}' appears to be a first name only. "
                    "A full name (first + last) is required. Ask the user for the complete name."
                ),
                "field": "recipient_name",
            }
        state["recipient_name"] = cleaned
        updated.append("recipient_name")

    # ── recipient_country ───────────────────────────────────────
    if recipient_country is not None:
        matched = _normalize_country(recipient_country)
        if not matched:
            return {
                "success": False,
                "error": f"'{recipient_country}' is not a supported destination.",
                "supported_countries": sorted(SUPPORTED_COUNTRIES.keys()),
                "field": "recipient_country",
            }
        state["recipient_country"] = matched
        # Reset delivery method when country changes and method is incompatible
        if state.get("delivery_method"):
            available = SUPPORTED_COUNTRIES[matched]["methods"]
            if state["delivery_method"] not in available:
                state["delivery_method"] = None
                ambiguity_warnings.append(
                    f"delivery_method was reset because it is not available in {matched}. "
                    f"Available methods: {available}. Ask the user to choose again."
                )
        updated.append("recipient_country")

    # ── amount_usd ──────────────────────────────────────────────
    if amount_usd is not None:
        if _amount_has_more_than_two_decimals(amount_usd):
            return {
                "success": False,
                "error": "Amount must have at most 2 decimal places.",
                "field": "amount_usd",
            }
        if amount_usd < MIN_AMOUNT_USD:
            return {
                "success": False,
                "error": f"Minimum transfer amount is ${MIN_AMOUNT_USD:,.2f} USD.",
                "field": "amount_usd",
            }
        if amount_usd > MAX_AMOUNT_USD:
            return {"success": False, "error": "Single-transfer limit is $10,000 USD.", "field": "amount_usd"}
        state["amount_usd"] = float(amount_usd)
        updated.append("amount_usd")

    # ── delivery_method ─────────────────────────────────────────
    if delivery_method is not None:
        # Normalise free-text input first
        canonical = _normalize_delivery_method(delivery_method)
        if canonical is None:
            return {
                "success": False,
                "error": (
                    f"'{delivery_method}' is not a recognised delivery method. "
                    f"Accepted values include: bank_transfer, cash_pickup, mobile_wallet, "
                    f"mobile_money, upi, pix."
                ),
                "field": "delivery_method",
            }
        # Country-level validation
        country = state.get("recipient_country")
        if country:
            available = SUPPORTED_COUNTRIES[country]["methods"]
            if canonical not in available:
                return {
                    "success": False,
                    "error": f"'{canonical}' is not available for {country}.",
                    "available_methods": available,
                    "field": "delivery_method",
                }
        state["delivery_method"] = canonical
        updated.append("delivery_method")

    if source_amount_currency is not None and not updated:
        return {
            "success": False,
            "error": (
                "Source currency was validated, but no transfer details were updated. "
                "Provide an amount in USD or another transfer field."
            ),
            "field": "source_amount_currency",
            "validated_source_amount_currency": validated_source_amount_currency,
        }

    state_changed = bool(updated)
    if state_changed:
        state["state_version"] += 1
        _invalidate_read_token(tool_context)
    _save_state(tool_context, state)

    required = list(REQUIRED_TRANSFER_FIELDS)
    missing = [f for f in required if not state.get(f)]

    result: dict = {
        "success": True,
        "updated_fields": updated,
        "current_state": state,
        "missing_fields": missing,
        "is_complete": len(missing) == 0,
        "state_version": state["state_version"],
    }
    if ambiguity_warnings:
        result["ambiguity_warnings"] = ambiguity_warnings
    if validated_source_amount_currency:
        result["validated_source_amount_currency"] = validated_source_amount_currency
    if state_changed:
        result["requires_new_read"] = True

    return result


def flag_ambiguous_input(
    tool_context: ToolContext,
    raw_text: str,
    detected_name: Optional[str] = None,
    detected_country: Optional[str] = None,
    detected_amount: Optional[float] = None,
) -> dict:
    """Log ambiguous user input and return clarification prompts plus salvageable partial data."""
    needs_clarification: list[str] = []
    partial_state: dict = {}

    if detected_name:
        if _name_seems_incomplete(detected_name):
            needs_clarification.append(
                f"You mentioned '{detected_name}' — could you give the recipient's full name (first + last)?"
            )
        else:
            partial_state["recipient_name"] = " ".join(detected_name.split()).title()

    if detected_country:
        matched = _normalize_country(detected_country)
        if matched:
            partial_state["recipient_country"] = matched
        else:
            needs_clarification.append(
                f"'{detected_country}' doesn't match a supported country. "
                f"Supported destinations: {', '.join(sorted(SUPPORTED_COUNTRIES.keys()))}."
            )

    if detected_amount is not None:
        if MIN_AMOUNT_USD <= detected_amount <= MAX_AMOUNT_USD:
            partial_state["amount_usd"] = round(float(detected_amount), 2)
        else:
            needs_clarification.append("The amount must be between $10.00 and $10,000 USD.")

    if not detected_name and not detected_country and not detected_amount:
        needs_clarification.append(
            "The message didn't contain recognisable transfer details. "
            "Ask the user who they want to send money to."
        )

    return {
        "raw_text": raw_text,
        "partial_state": partial_state,
        "needs_clarification": needs_clarification,
        "salvageable": bool(partial_state),
    }


def get_country_info(country: str) -> dict:
    """Return support status, currency, and delivery methods for a country (with fuzzy matching)."""
    matched = _normalize_country(country)
    if not matched:
        return {
            "supported": False,
            "message": f"'{country}' is not currently supported.",
            "supported_countries": sorted(SUPPORTED_COUNTRIES.keys()),
        }
    info = SUPPORTED_COUNTRIES[matched]
    return {
        "supported": True,
        "country": matched,
        "currency": info["currency"],
        "available_delivery_methods": info["methods"],
    }


def get_supported_destinations(include_details: bool = False) -> dict:
    """Return supported destination countries, optionally with currency and delivery-method details."""
    countries = sorted(SUPPORTED_COUNTRIES.keys())
    result: dict = {
        "supported_countries": countries,
        "total_supported_countries": len(countries),
    }
    if include_details:
        result["country_details"] = {
            country: {
                "currency": SUPPORTED_COUNTRIES[country]["currency"],
                "available_delivery_methods": SUPPORTED_COUNTRIES[country]["methods"],
            }
            for country in countries
        }
    return result


def get_transfer_policies() -> dict:
    """Return non-sensitive transfer limits, required fields, and capability rules."""
    supported_delivery_methods = sorted({
        method
        for country_data in SUPPORTED_COUNTRIES.values()
        for method in country_data["methods"]
    })
    return {
        "source_amount_currency": SOURCE_AMOUNT_CURRENCY,
        "minimum_amount_usd": MIN_AMOUNT_USD,
        "maximum_amount_usd": MAX_AMOUNT_USD,
        "required_fields": list(REQUIRED_TRANSFER_FIELDS),
        "requires_explicit_user_confirmation": True,
        "supported_delivery_methods": supported_delivery_methods,
        "notes": [
            "Recipient full name (first + last) is required.",
            "Source transfer amounts must be provided in USD only.",
            "Source transfer amounts can use at most 2 decimal places.",
            "Delivery method availability depends on destination country.",
            "Users can provide details in any order and correct them before confirmation.",
            "Confirmed transfers cannot be edited; a new transfer must be started for changes.",
        ],
    }


def confirm_transfer(
    tool_context: ToolContext,
    user_confirmed: bool = False,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """Confirm the transfer only when `user_confirmed=True` and all required fields are valid."""
    is_fresh, error, state = _validate_fresh_state(tool_context, read_token, expected_version)
    if not is_fresh:
        return error  # type: ignore[return-value]

    # ── Hard gate: explicit user consent ───────────────────────
    if not user_confirmed:
        return {
            "success": False,
            "error": (
                "Transfer not confirmed. You must set user_confirmed=True only after "
                "the user has explicitly said yes (e.g. 'yes', 'confirm', 'go ahead'). "
                "Show the summary and ask the user first."
            ),
            "action_required": "ask_user_to_confirm",
        }

    # ── Double-confirm guard ────────────────────────────────────
    if state.get("status") == "confirmed":
        return {
            "success": False,
            "error": "This transfer has already been confirmed.",
            "reference_number": state.get("reference_number"),
        }

    # ── Completeness check ──────────────────────────────────────
    required = list(REQUIRED_TRANSFER_FIELDS)
    missing = [f for f in required if not state.get(f)]
    # Also catch an incomplete name that somehow made it into state
    if state.get("recipient_name") and _name_seems_incomplete(state["recipient_name"]):
        if "recipient_name" not in missing:
            missing.append("recipient_name")
    if missing:
        return {
            "success": False,
            "error": "Cannot confirm: some fields are still missing or incomplete.",
            "missing": missing,
        }

    country_data = SUPPORTED_COUNTRIES[state["recipient_country"]]
    local_amount = round(state["amount_usd"] * country_data["rate"], 2)
    ref = f"TXN{random.randint(100_000, 999_999)}"
    active_language = tool_context.state.get("active_language")

    state.update(
        status="confirmed",
        reference_number=ref,
        local_amount=local_amount,
        local_currency=country_data["currency"],
        state_version=state["state_version"] + 1,
    )
    _save_state(tool_context, state)
    _invalidate_read_token(tool_context)

    return {
        "success": True,
        "reference_number": ref,
        "state_version": state["state_version"],
        "requires_new_read": True,
        "summary": {
            "recipient":         state["recipient_name"],
            "destination_country": state["recipient_country"],
            "amount_sent":       f"${state['amount_usd']:,.2f} USD",
            "amount_received":   f"{local_amount:,.2f} {country_data['currency']}",
            "exchange_rate":     f"1 USD = {country_data['rate']} {country_data['currency']}",
            "delivery_method":   _localize_delivery_method(state["delivery_method"], active_language),
            "status":            "✅ Confirmed",
            "reference_number":  ref,
        },
    }


def reset_transfer(
    tool_context: ToolContext,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """Clear transfer state and increment version so the user can start over."""
    is_fresh, error, state = _validate_fresh_state(tool_context, read_token, expected_version)
    if not is_fresh:
        return error  # type: ignore[return-value]

    cleared = dict(_EMPTY_STATE)
    cleared["state_version"] = state["state_version"] + 1
    _save_state(tool_context, cleared)
    _invalidate_read_token(tool_context)
    return {
        "success": True,
        "message": "Transfer cleared. Ready to start a new one.",
        "state_version": cleared["state_version"],
        "requires_new_read": True,
    }
