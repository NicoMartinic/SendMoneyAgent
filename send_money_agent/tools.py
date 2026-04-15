"""
Mock tools for the Send Money Agent.
All validation and lookup logic is simulated — no real integrations required.

Changes from v1:
  - _normalize_country: fuzzy prefix/alias matching in addition to exact.
  - _normalize_delivery_method: normalises free-text input to canonical keys.
  - update_transfer_details: incomplete names are NOT saved; returns
    success=False so the agent is forced to ask for clarification.
  - confirm_transfer: requires explicit `user_confirmed=True` parameter
    (hard gate — prompt alone is insufficient).
  - flag_ambiguous_input: unchanged, kept for ambiguity logging.
  - get_supported_destinations / get_transfer_policies: expose safe,
    user-facing capability/business-rule information.
"""

import random
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
    "bank_transfer":  ["bank transfer", "bank", "wire", "wire transfer", "ach", "bank_transfer"],
    "cash_pickup":    ["cash pickup", "cash pick up", "cash", "pickup", "cash_pickup"],
    "mobile_wallet":  ["mobile wallet", "mobile_wallet", "wallet", "ewallet", "e-wallet", "mobile"],
    "mobile_money":   ["mobile money", "mobile_money", "mpesa", "m-pesa"],
    "upi":            ["upi", "unified payment", "unified payments interface"],
    "pix":            ["pix"],
}

MIN_AMOUNT_USD = 0.01
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


def _normalize_delivery_method(raw: str) -> Optional[str]:
    """
    Map free-text delivery method input to a canonical key, or return None.
    E.g. "mobile wallet", "Mobile Wallet", "wallet" → "mobile_wallet".
    """
    key = raw.strip().lower()
    for canonical, aliases in _DELIVERY_METHOD_ALIASES.items():
        if key in aliases or key == canonical:
            return canonical
    return None


def _name_seems_incomplete(name: str) -> bool:
    """
    Return True when a name appears to be first-name-only or title-only.
    Rules:
      - Must have at least 2 parts after splitting.
      - At least 2 of those parts must be non-title words (so "Dr. Smith" is
        complete: "Smith" is the one meaningful non-title part — wait, that's
        only 1. We allow title + last-name as a valid 2-part name.)
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
    """
    Return the current transfer state, including which fields have been
    collected and which are still missing.

    Returns:
        A dict with keys: recipient_name, recipient_country, amount_usd,
        delivery_method, status, missing_fields, is_complete.
        `is_complete` is True only when ALL four required fields are present
        AND recipient_name passes the completeness check.
    """
    state = _get_state(tool_context)
    _save_state(tool_context, state)
    read_token = _issue_read_token(tool_context, state["state_version"])
    required = list(REQUIRED_TRANSFER_FIELDS)
    missing = [f for f in required if not state.get(f)]

    # Extra guard: a saved name that is still incomplete counts as missing
    name = state.get("recipient_name")
    if name and _name_seems_incomplete(name) and "recipient_name" not in missing:
        missing.append("recipient_name")

    return {
        **state,
        "missing_fields": missing,
        "is_complete": len(missing) == 0,
        "read_token": read_token,
        "expected_version": state["state_version"],
    }


def update_transfer_details(
    tool_context: ToolContext,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
    recipient_name: Optional[str] = None,
    recipient_country: Optional[str] = None,
    amount_usd: Optional[float] = None,
    delivery_method: Optional[str] = None,
) -> dict:
    """
    Persist one or more transfer fields collected from the user.
    Only pass arguments for fields the user actually provided in this turn.

    Hard rules enforced here (not just in the prompt):
      • recipient_name must contain at least two meaningful words; if not,
        returns success=False so the name is NOT saved and the agent MUST ask.
      • recipient_country must be in the supported list (fuzzy-matched).
      • amount_usd must be 0 < x ≤ 10,000.
      • delivery_method is normalised from free text and validated against
        the methods available for the selected country.

    Returns:
        success, updated_fields, current_state, missing_fields, is_complete,
        and optionally ambiguity_warnings.
        On validation failure, returns success=False with an error message.
    """
    is_fresh, error, state = _validate_fresh_state(tool_context, read_token, expected_version)
    if not is_fresh:
        return error  # type: ignore[return-value]

    updated: list[str] = []
    ambiguity_warnings: list[str] = []

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
        if amount_usd < MIN_AMOUNT_USD:
            return {"success": False, "error": "Amount must be greater than $0.", "field": "amount_usd"}
        if amount_usd > MAX_AMOUNT_USD:
            return {"success": False, "error": "Single-transfer limit is $10,000 USD.", "field": "amount_usd"}
        state["amount_usd"] = round(float(amount_usd), 2)
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
    """
    Called when the user's message contains information that is underspecified
    or ambiguous. The agent should call this to log what was understood and
    get back structured guidance on what to clarify.

    Args:
        raw_text:         The original user message that was ambiguous.
        detected_name:    Name fragment detected (if any).
        detected_country: Country fragment detected (if any).
        detected_amount:  Amount detected (if any).

    Returns:
        A dict with `needs_clarification` (list of questions to ask the user)
        and `partial_state` (what could be salvaged).
    """
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
            needs_clarification.append("The amount must be between $0.01 and $10,000 USD.")

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
    """
    Look up whether a country is supported and what delivery methods are available.
    Accepts fuzzy input (aliases, prefixes, case-insensitive).

    Args:
        country: Country name to look up.

    Returns:
        supported (bool), and if supported: currency, available_delivery_methods.
    """
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
    """
    Return all currently supported destination countries.

    This tool is safe for direct user-facing capability questions.

    Args:
        include_details: If True, include currency + delivery-method details
                         per country.

    Returns:
        supported_countries (sorted), total_supported_countries, and optionally
        country_details.
    """
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
    """
    Return non-sensitive business rules and transfer capabilities.

    This is intended for questions like:
      - "What are your limits?"
      - "What info do you need to send money?"
      - "Which payout methods do you support?"
    """
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
            "Delivery method availability depends on destination country.",
            "Users can provide details in any order and correct them before confirmation.",
        ],
    }


def confirm_transfer(
    tool_context: ToolContext,
    user_confirmed: bool = False,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """
    Finalise the transfer.

    IMPORTANT: `user_confirmed` MUST be explicitly set to True by the agent.
    The agent must only pass True after the user has unambiguously said yes
    (e.g. "yes", "confirm", "go ahead"). This is a hard gate enforced in code —
    the prompt alone is not sufficient.

    Args:
        user_confirmed: Must be True to proceed. If False or omitted, the tool
                        returns a guidance error and does NOT commit the transfer.

    Returns:
        success, reference_number, and a confirmation summary dict.
        Returns success=False if:
          - user_confirmed is not True (explicit-consent gate).
          - any required field is missing.
          - the transfer has already been confirmed (double-confirm guard).
    """
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
            "delivery_method":   state["delivery_method"].replace("_", " ").title(),
            "status":            "✅ Confirmed",
            "reference_number":  ref,
        },
    }


def reset_transfer(
    tool_context: ToolContext,
    read_token: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """
    Reset the entire transfer state so the user can start over.

    Returns:
        Confirmation that the state has been cleared.
    """
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
