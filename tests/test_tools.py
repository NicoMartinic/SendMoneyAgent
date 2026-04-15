"""
Run all tool tests without requiring a real google-adk install.
Usage:
  pytest tests/test_tools.py -v
  python -m unittest tests/test_tools.py -v
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

# ── Minimal ADK mock ──────────────────────────────────────────────────────────
google_mod = types.ModuleType("google")
google_adk = types.ModuleType("google.adk")
google_adk_tools = types.ModuleType("google.adk.tools")

class ToolContext:
    """Fake ToolContext backed by a real dict."""
    def __init__(self):
        self.state: dict = {}

google_adk_tools.ToolContext = ToolContext
sys.modules["google"] = google_mod
sys.modules["google.adk"] = google_adk
sys.modules["google.adk.tools"] = google_adk_tools
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, ".")

from send_money_agent.tools import (
    get_transfer_state,
    update_transfer_details,
    flag_ambiguous_input,
    get_country_info,
    get_supported_destinations,
    get_transfer_policies,
    confirm_transfer,
    reset_transfer,
    _normalize_country,
    _normalize_delivery_method,
    _name_seems_incomplete,
)

_RAW_GET_TRANSFER_STATE = get_transfer_state
_RAW_UPDATE_TRANSFER_DETAILS = update_transfer_details
_RAW_CONFIRM_TRANSFER = confirm_transfer
_RAW_RESET_TRANSFER = reset_transfer


def _fresh_contract(ctx):
    snapshot = _RAW_GET_TRANSFER_STATE(ctx)
    return snapshot["read_token"], snapshot["expected_version"]


def update_transfer_details(tool_context, *args, **kwargs):
    if "read_token" not in kwargs and "expected_version" not in kwargs:
        read_token, expected_version = _fresh_contract(tool_context)
        kwargs["read_token"] = read_token
        kwargs["expected_version"] = expected_version
    return _RAW_UPDATE_TRANSFER_DETAILS(tool_context, *args, **kwargs)


def confirm_transfer(tool_context, *args, **kwargs):
    if "read_token" not in kwargs and "expected_version" not in kwargs:
        read_token, expected_version = _fresh_contract(tool_context)
        kwargs["read_token"] = read_token
        kwargs["expected_version"] = expected_version
    return _RAW_CONFIRM_TRANSFER(tool_context, *args, **kwargs)


def reset_transfer(tool_context, *args, **kwargs):
    if "read_token" not in kwargs and "expected_version" not in kwargs:
        read_token, expected_version = _fresh_contract(tool_context)
        kwargs["read_token"] = read_token
        kwargs["expected_version"] = expected_version
    return _RAW_RESET_TRANSFER(tool_context, *args, **kwargs)


def make_ctx(initial_state=None):
    ctx = ToolContext()
    if initial_state:
        ctx.state["transfer_state"] = initial_state
    return ctx


def full_state(name="Maria Santos", country="Philippines", amount=350.0,
               method="mobile_wallet", status="in_progress"):
    return {
        "recipient_name":    name,
        "recipient_country": country,
        "amount_usd":        amount,
        "delivery_method":   method,
        "status":            status,
    }


# ══════════════════════════════════════════════════════════════════════════════
class TestNormalizeCountry(unittest.TestCase):
    def test_exact(self):           self.assertEqual(_normalize_country("Mexico"), "Mexico")
    def test_lower(self):           self.assertEqual(_normalize_country("mexico"), "Mexico")
    def test_upper(self):           self.assertEqual(_normalize_country("MEXICO"), "Mexico")
    def test_mixed(self):           self.assertEqual(_normalize_country("pHiLiPpInEs"), "Philippines")
    def test_alias_phil(self):      self.assertEqual(_normalize_country("Phil"), "Philippines")
    def test_alias_phils(self):     self.assertEqual(_normalize_country("phils"), "Philippines")
    def test_alias_philippine(self):self.assertEqual(_normalize_country("philippine"), "Philippines")
    def test_alias_salvador(self):  self.assertEqual(_normalize_country("Salvador"), "El Salvador")
    def test_alias_elsalvador(self):self.assertEqual(_normalize_country("ElSalvador"), "El Salvador")
    def test_alias_brasil(self):    self.assertEqual(_normalize_country("Brasil"), "Brazil")
    def test_prefix_colombi(self):  self.assertEqual(_normalize_country("Colombi"), "Colombia")
    def test_prefix_guatem(self):   self.assertEqual(_normalize_country("Guatem"), "Guatemala")
    def test_unsupported(self):     self.assertIsNone(_normalize_country("France"))
    def test_empty(self):           self.assertIsNone(_normalize_country(""))
    def test_el_salvador_exact(self): self.assertEqual(_normalize_country("El Salvador"), "El Salvador")
    def test_el_salvador_lower(self): self.assertEqual(_normalize_country("el salvador"), "El Salvador")


class TestNormalizeDeliveryMethod(unittest.TestCase):
    def test_canonical(self):         self.assertEqual(_normalize_delivery_method("bank_transfer"), "bank_transfer")
    def test_free_text_bank(self):    self.assertEqual(_normalize_delivery_method("bank transfer"), "bank_transfer")
    def test_bank_upper(self):        self.assertEqual(_normalize_delivery_method("Bank Transfer"), "bank_transfer")
    def test_bank_short(self):        self.assertEqual(_normalize_delivery_method("bank"), "bank_transfer")
    def test_wire(self):              self.assertEqual(_normalize_delivery_method("wire"), "bank_transfer")
    def test_cash(self):              self.assertEqual(_normalize_delivery_method("cash"), "cash_pickup")
    def test_cash_pickup_space(self): self.assertEqual(_normalize_delivery_method("cash pickup"), "cash_pickup")
    def test_mobile_wallet_space(self):self.assertEqual(_normalize_delivery_method("mobile wallet"), "mobile_wallet")
    def test_wallet(self):            self.assertEqual(_normalize_delivery_method("wallet"), "mobile_wallet")
    def test_ewallet(self):           self.assertEqual(_normalize_delivery_method("ewallet"), "mobile_wallet")
    def test_mobile_money(self):      self.assertEqual(_normalize_delivery_method("mobile money"), "mobile_money")
    def test_mpesa(self):             self.assertEqual(_normalize_delivery_method("mpesa"), "mobile_money")
    def test_mpesa_dash(self):        self.assertEqual(_normalize_delivery_method("m-pesa"), "mobile_money")
    def test_upi(self):               self.assertEqual(_normalize_delivery_method("upi"), "upi")
    def test_pix(self):               self.assertEqual(_normalize_delivery_method("pix"), "pix")
    def test_unknown(self):           self.assertIsNone(_normalize_delivery_method("carrier pigeon"))
    def test_empty(self):             self.assertIsNone(_normalize_delivery_method(""))


class TestNameCompleteness(unittest.TestCase):
    def test_single_word(self):       self.assertTrue(_name_seems_incomplete("Maria"))
    def test_title_only(self):        self.assertTrue(_name_seems_incomplete("Mr."))
    def test_title_no_period(self):   self.assertTrue(_name_seems_incomplete("Dr"))
    def test_full_name(self):         self.assertFalse(_name_seems_incomplete("Maria Santos"))
    def test_three_parts(self):       self.assertFalse(_name_seems_incomplete("John Michael Doe"))
    def test_title_plus_last(self):   self.assertFalse(_name_seems_incomplete("Dr. Smith"))
    def test_empty(self):             self.assertTrue(_name_seems_incomplete(""))
    def test_whitespace(self):        self.assertTrue(_name_seems_incomplete("   "))


# ══════════════════════════════════════════════════════════════════════════════
class TestGetTransferState(unittest.TestCase):
    def test_empty_all_missing(self):
        r = get_transfer_state(make_ctx())
        self.assertFalse(r["is_complete"])
        self.assertEqual(len(r["missing_fields"]), 4)

    def test_complete_state(self):
        r = get_transfer_state(make_ctx(full_state()))
        self.assertTrue(r["is_complete"])
        self.assertEqual(r["missing_fields"], [])

    def test_incomplete_name_in_state_counts_missing(self):
        r = get_transfer_state(make_ctx(full_state(name="Maria")))
        self.assertFalse(r["is_complete"])
        self.assertIn("recipient_name", r["missing_fields"])


class TestStateContract(unittest.TestCase):
    def test_update_requires_fresh_read(self):
        r = _RAW_UPDATE_TRANSFER_DETAILS(make_ctx(), recipient_name="Maria Santos")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "FRESH_STATE_REQUIRED")

    def test_confirm_requires_fresh_read(self):
        r = _RAW_CONFIRM_TRANSFER(make_ctx(full_state()), user_confirmed=True)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "FRESH_STATE_REQUIRED")

    def test_reset_requires_fresh_read(self):
        r = _RAW_RESET_TRANSFER(make_ctx(full_state()))
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "FRESH_STATE_REQUIRED")

    def test_old_read_token_rejected(self):
        ctx = make_ctx()
        snap_1 = _RAW_GET_TRANSFER_STATE(ctx)
        snap_2 = _RAW_GET_TRANSFER_STATE(ctx)
        r = _RAW_UPDATE_TRANSFER_DETAILS(
            ctx,
            read_token=snap_1["read_token"],
            expected_version=snap_1["expected_version"],
            recipient_name="Maria Santos",
        )
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "FRESH_STATE_REQUIRED")
        # Latest token should still work
        ok = _RAW_UPDATE_TRANSFER_DETAILS(
            ctx,
            read_token=snap_2["read_token"],
            expected_version=snap_2["expected_version"],
            recipient_name="Maria Santos",
        )
        self.assertTrue(ok["success"])

    def test_stale_expected_version_rejected(self):
        ctx = make_ctx()
        snap_1 = _RAW_GET_TRANSFER_STATE(ctx)
        ok = _RAW_UPDATE_TRANSFER_DETAILS(
            ctx,
            read_token=snap_1["read_token"],
            expected_version=snap_1["expected_version"],
            recipient_name="Maria Santos",
        )
        self.assertTrue(ok["success"])
        snap_2 = _RAW_GET_TRANSFER_STATE(ctx)
        stale = _RAW_UPDATE_TRANSFER_DETAILS(
            ctx,
            read_token=snap_2["read_token"],
            expected_version=0,
            recipient_country="Mexico",
        )
        self.assertFalse(stale["success"])
        self.assertEqual(stale["error_code"], "STALE_STATE")


# ══════════════════════════════════════════════════════════════════════════════
class TestUpdateTransferDetails(unittest.TestCase):

    # Name
    def test_full_name_accepted(self):
        ctx = make_ctx()
        r = update_transfer_details(ctx, recipient_name="maria santos")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["recipient_name"], "Maria Santos")

    def test_single_name_rejected_not_saved(self):
        ctx = make_ctx()
        r = update_transfer_details(ctx, recipient_name="Maria")
        self.assertFalse(r["success"])
        self.assertIsNone(ctx.state.get("transfer_state", {}).get("recipient_name"))

    def test_title_only_rejected(self):
        r = update_transfer_details(make_ctx(), recipient_name="Mr.")
        self.assertFalse(r["success"])

    # Country
    def test_valid_country(self):
        r = update_transfer_details(make_ctx(), recipient_country="Mexico")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["recipient_country"], "Mexico")

    def test_alias_country(self):
        r = update_transfer_details(make_ctx(), recipient_country="phil")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["recipient_country"], "Philippines")

    def test_unsupported_country(self):
        r = update_transfer_details(make_ctx(), recipient_country="France")
        self.assertFalse(r["success"])

    # Amount
    def test_valid_amount(self):
        r = update_transfer_details(make_ctx(), amount_usd=500.0)
        self.assertTrue(r["success"])

    def test_zero_rejected(self):
        r = update_transfer_details(make_ctx(), amount_usd=0)
        self.assertFalse(r["success"])

    def test_over_limit_rejected(self):
        r = update_transfer_details(make_ctx(), amount_usd=10_001)
        self.assertFalse(r["success"])

    def test_exact_limit_ok(self):
        r = update_transfer_details(make_ctx(), amount_usd=10_000)
        self.assertTrue(r["success"])

    def test_amount_rounded(self):
        r = update_transfer_details(make_ctx(), amount_usd=123.456)
        self.assertEqual(r["current_state"]["amount_usd"], 123.46)

    # Delivery method
    def test_free_text_method_normalised(self):
        ctx = make_ctx(full_state(method=None))
        r = update_transfer_details(ctx, delivery_method="mobile wallet")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["delivery_method"], "mobile_wallet")

    def test_method_not_for_country_rejected(self):
        ctx = make_ctx(full_state(country="Colombia", method=None))
        r = update_transfer_details(ctx, delivery_method="mobile_wallet")
        self.assertFalse(r["success"])

    def test_unknown_method_rejected(self):
        r = update_transfer_details(make_ctx(), delivery_method="teleportation")
        self.assertFalse(r["success"])

    # Country change
    def test_country_change_resets_incompatible_method(self):
        ctx = make_ctx(full_state(country="Philippines", method="mobile_wallet"))
        r = update_transfer_details(ctx, recipient_country="Colombia")
        self.assertTrue(r["success"])
        self.assertIsNone(r["current_state"]["delivery_method"])
        self.assertIn("ambiguity_warnings", r)

    def test_country_change_keeps_compatible_method(self):
        ctx = make_ctx(full_state(country="Mexico", method="bank_transfer"))
        r = update_transfer_details(ctx, recipient_country="India")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["delivery_method"], "bank_transfer")
        self.assertNotIn("ambiguity_warnings", r)

    # Misc
    def test_no_args_is_noop(self):
        ctx = make_ctx(full_state())
        r = update_transfer_details(ctx)
        self.assertTrue(r["success"])
        self.assertEqual(r["updated_fields"], [])
        self.assertTrue(r["is_complete"])

    def test_whitespace_trimmed_name(self):
        ctx = make_ctx()
        r = update_transfer_details(ctx, recipient_name="  maria   santos  ")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["recipient_name"], "Maria Santos")

    def test_case_insensitive_method(self):
        ctx = make_ctx(full_state(method=None))
        r = update_transfer_details(ctx, delivery_method="BANK_TRANSFER")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["delivery_method"], "bank_transfer")


# ══════════════════════════════════════════════════════════════════════════════
class TestConfirmTransfer(unittest.TestCase):

    def test_no_flag_rejected(self):
        r = confirm_transfer(make_ctx(full_state()))
        self.assertFalse(r["success"])
        self.assertEqual(r["action_required"], "ask_user_to_confirm")

    def test_false_flag_rejected(self):
        r = confirm_transfer(make_ctx(full_state()), user_confirmed=False)
        self.assertFalse(r["success"])

    def test_happy_path(self):
        r = confirm_transfer(make_ctx(full_state()), user_confirmed=True)
        self.assertTrue(r["success"])
        self.assertTrue(r["reference_number"].startswith("TXN"))
        self.assertEqual(r["summary"]["recipient"], "Maria Santos")

    def test_missing_fields_rejected(self):
        ctx = make_ctx({"recipient_name": "Ana Lima", "recipient_country": "Brazil",
                        "amount_usd": None, "delivery_method": None, "status": "in_progress"})
        r = confirm_transfer(ctx, user_confirmed=True)
        self.assertFalse(r["success"])
        self.assertIn("missing", r)

    def test_double_confirm_rejected(self):
        ctx = make_ctx(full_state(status="confirmed"))
        ctx.state["transfer_state"]["reference_number"] = "TXN000001"
        r = confirm_transfer(ctx, user_confirmed=True)
        self.assertFalse(r["success"])
        self.assertIn("already been confirmed", r["error"])

    def test_incomplete_name_blocks_confirm(self):
        ctx = make_ctx(full_state(name="SingleName"))
        r = confirm_transfer(ctx, user_confirmed=True)
        self.assertFalse(r["success"])
        self.assertIn("recipient_name", r["missing"])

    def test_sets_confirmed_status(self):
        ctx = make_ctx(full_state())
        confirm_transfer(ctx, user_confirmed=True)
        self.assertEqual(ctx.state["transfer_state"]["status"], "confirmed")

    def test_local_amount_calculated(self):
        ctx = make_ctx(full_state(amount=100.0))  # Philippines rate=58
        confirm_transfer(ctx, user_confirmed=True)
        self.assertEqual(ctx.state["transfer_state"]["local_amount"], 5800.0)

    def test_ref_format(self):
        r = confirm_transfer(make_ctx(full_state()), user_confirmed=True)
        self.assertRegex(r["reference_number"], r"^TXN\d{6}$")


# ══════════════════════════════════════════════════════════════════════════════
class TestResetTransfer(unittest.TestCase):

    def test_clears_all_fields(self):
        ctx = make_ctx(full_state())
        reset_transfer(ctx)
        s = ctx.state["transfer_state"]
        self.assertIsNone(s["recipient_name"])
        self.assertIsNone(s["recipient_country"])
        self.assertIsNone(s["amount_usd"])
        self.assertIsNone(s["delivery_method"])
        self.assertEqual(s["status"], "in_progress")

    def test_is_complete_false_after_reset(self):
        ctx = make_ctx(full_state())
        reset_transfer(ctx)
        self.assertFalse(get_transfer_state(ctx)["is_complete"])

    def test_safe_on_empty(self):
        r = reset_transfer(make_ctx())
        self.assertTrue(r["success"])


# ══════════════════════════════════════════════════════════════════════════════
class TestGetCountryInfo(unittest.TestCase):

    def test_supported(self):
        r = get_country_info("Mexico")
        self.assertTrue(r["supported"])
        self.assertEqual(r["currency"], "MXN")

    def test_unsupported(self):
        r = get_country_info("France")
        self.assertFalse(r["supported"])
        self.assertIn("supported_countries", r)

    def test_fuzzy(self):
        r = get_country_info("phil")
        self.assertTrue(r["supported"])
        self.assertEqual(r["country"], "Philippines")

    def test_case_insensitive(self):
        r = get_country_info("INDIA")
        self.assertTrue(r["supported"])

    def test_brazil_has_pix(self):
        r = get_country_info("Brazil")
        self.assertIn("pix", r["available_delivery_methods"])

    def test_kenya_has_mobile_money(self):
        r = get_country_info("Kenya")
        self.assertIn("mobile_money", r["available_delivery_methods"])


# ══════════════════════════════════════════════════════════════════════════════
class TestCapabilityTools(unittest.TestCase):

    def test_supported_destinations_basic(self):
        r = get_supported_destinations()
        self.assertIn("supported_countries", r)
        self.assertEqual(r["supported_countries"], sorted(r["supported_countries"]))
        self.assertEqual(r["total_supported_countries"], len(r["supported_countries"]))

    def test_supported_destinations_with_details(self):
        r = get_supported_destinations(include_details=True)
        self.assertIn("country_details", r)
        self.assertIn("Mexico", r["country_details"])
        mexico = r["country_details"]["Mexico"]
        self.assertEqual(mexico["currency"], "MXN")
        self.assertIn("bank_transfer", mexico["available_delivery_methods"])

    def test_transfer_policies(self):
        r = get_transfer_policies()
        self.assertEqual(r["source_amount_currency"], "USD")
        self.assertEqual(r["minimum_amount_usd"], 0.01)
        self.assertEqual(r["maximum_amount_usd"], 10_000.0)
        self.assertIn("recipient_name", r["required_fields"])
        self.assertIn("delivery_method", r["required_fields"])
        self.assertTrue(r["requires_explicit_user_confirmation"])
        self.assertIn("bank_transfer", r["supported_delivery_methods"])


# ══════════════════════════════════════════════════════════════════════════════
class TestFlagAmbiguousInput(unittest.TestCase):

    def test_single_name_flags_clarification(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="to Maria", detected_name="Maria")
        self.assertGreater(len(r["needs_clarification"]), 0)
        self.assertFalse(r["salvageable"])

    def test_full_name_salvaged(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="to Maria Santos", detected_name="Maria Santos")
        self.assertEqual(r["partial_state"]["recipient_name"], "Maria Santos")
        self.assertEqual(len(r["needs_clarification"]), 0)

    def test_supported_country_salvaged(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="Mexico", detected_country="Mexico")
        self.assertEqual(r["partial_state"]["recipient_country"], "Mexico")

    def test_unsupported_country_flagged(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="France", detected_country="France")
        self.assertGreater(len(r["needs_clarification"]), 0)

    def test_valid_amount_salvaged(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="500", detected_amount=500.0)
        self.assertEqual(r["partial_state"]["amount_usd"], 500.0)

    def test_over_limit_amount_flagged(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="50000", detected_amount=50000.0)
        self.assertGreater(len(r["needs_clarification"]), 0)

    def test_no_info_triggers_question(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="I need help")
        self.assertGreater(len(r["needs_clarification"]), 0)
        self.assertFalse(r["salvageable"])

    def test_multi_field_salvage(self):
        r = flag_ambiguous_input(make_ctx(), raw_text="...",
                                 detected_name="Maria Santos", detected_country="Mexico",
                                 detected_amount=200.0)
        self.assertEqual(r["partial_state"]["recipient_name"], "Maria Santos")
        self.assertEqual(r["partial_state"]["recipient_country"], "Mexico")
        self.assertEqual(r["partial_state"]["amount_usd"], 200.0)
        self.assertEqual(len(r["needs_clarification"]), 0)


# ══════════════════════════════════════════════════════════════════════════════
class TestIntegrationFlows(unittest.TestCase):

    def test_full_flow_philippines(self):
        ctx = make_ctx()
        self.assertTrue(update_transfer_details(ctx, recipient_name="Maria Santos")["success"])
        self.assertTrue(update_transfer_details(ctx, recipient_country="Philippines")["success"])
        self.assertTrue(update_transfer_details(ctx, amount_usd=350.0)["success"])
        r = update_transfer_details(ctx, delivery_method="mobile wallet")
        self.assertTrue(r["success"])
        self.assertTrue(r["is_complete"])
        self.assertFalse(confirm_transfer(ctx)["success"])          # no consent
        self.assertTrue(confirm_transfer(ctx, user_confirmed=True)["success"])

    def test_full_flow_india_upi(self):
        ctx = make_ctx()
        update_transfer_details(ctx, recipient_name="Raj Patel", recipient_country="India",
                                amount_usd=1000.0, delivery_method="upi")
        r = confirm_transfer(ctx, user_confirmed=True)
        self.assertTrue(r["success"])
        self.assertIn("INR", r["summary"]["amount_received"])

    def test_full_flow_nigeria_mobile_money(self):
        ctx = make_ctx()
        update_transfer_details(ctx, recipient_name="Amaka Obi", recipient_country="Nigeria",
                                amount_usd=500.0)
        r = update_transfer_details(ctx, delivery_method="mpesa")
        self.assertTrue(r["success"])
        self.assertEqual(r["current_state"]["delivery_method"], "mobile_money")

    def test_correction_name(self):
        ctx = make_ctx(full_state(name="Wrong Person"))
        r = update_transfer_details(ctx, recipient_name="Maria Santos")
        self.assertTrue(r["success"])
        self.assertEqual(ctx.state["transfer_state"]["recipient_name"], "Maria Santos")

    def test_correction_country_resets_method(self):
        ctx = make_ctx(full_state(country="Philippines", method="mobile_wallet"))
        update_transfer_details(ctx, recipient_country="Colombia")
        self.assertIsNone(ctx.state["transfer_state"]["delivery_method"])

    def test_out_of_order_amount_first(self):
        ctx = make_ctx()
        r = update_transfer_details(ctx, amount_usd=250.0)
        self.assertTrue(r["success"])
        self.assertFalse(r["is_complete"])

    def test_reset_then_new_flow(self):
        ctx = make_ctx(full_state())
        reset_transfer(ctx)
        r = update_transfer_details(ctx, recipient_name="New Person")
        self.assertTrue(r["success"])
        self.assertIsNone(r["current_state"]["recipient_country"])

    def test_confirm_after_reset_fails(self):
        ctx = make_ctx(full_state())
        confirm_transfer(ctx, user_confirmed=True)
        reset_transfer(ctx)
        self.assertFalse(confirm_transfer(ctx, user_confirmed=True)["success"])

    def test_all_fields_at_once(self):
        ctx = make_ctx()
        r = update_transfer_details(ctx, recipient_name="Ana Lima", recipient_country="Brazil",
                                    amount_usd=300.0, delivery_method="pix")
        self.assertTrue(r["success"])
        self.assertTrue(r["is_complete"])


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
