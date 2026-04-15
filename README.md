# 💸 Send Money Agent

A conversational money-transfer assistant built with **Google ADK** (Agent Development Kit).  
Supports **Gemini**, **Claude (Anthropic)**, and **OpenAI GPT** models as the underlying LLM.

---

## What it does

The agent guides a user through an international money transfer in natural conversation:

| Step | What it collects |
|------|-----------------|
| 1 | **Recipient name** — full first + last name of who receives the money |
| 2 | **Destination country** — validated against supported list (fuzzy-matched) |
| 3 | **Amount (USD)** — up to $10,000 per transfer |
| 4 | **Delivery method** — options depend on the country; free-text normalised |

It handles:
- Open-ended starts ("I want to send money")  
- Out-of-order answers ("her name is Maria Garcia, she's in Mexico, $200")  
- Mid-flow corrections ("actually change the country to Colombia")  
- Ambiguity: single-word names are **hard-rejected** by the tool — agent must ask for full name  
- Country-specific delivery method validation  
- Free-text delivery method input ("mobile wallet", "bank", "mpesa" → canonical keys)  
- Fuzzy country matching (aliases, prefixes, case-insensitive)  
- A final confirmation step requiring **explicit user_confirmed=True** before committing  

---

## Project structure

```text
send_money_agent/
├── send_money_agent/
│   ├── __init__.py          # Exposes root_agent (ADK convention)
│   ├── agent.py             # Agent definition + model selection
│   └── tools.py             # All tools with mock validation logic
├── tests/
│   └── test_tools.py        # Comprehensive pytest test suite
├── main.py                  # Interactive CLI runner
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add the API key for your chosen model
```

| Model | Required key |
|-------|-------------|
| Gemini (default) | `GOOGLE_API_KEY` |
| Claude | `ANTHROPIC_API_KEY` |
| ChatGPT | `OPENAI_API_KEY` |

### 3. Load environment variables (local shell)

```bash
set -a
source .env
set +a
```

### 4. Run CLI

**CLI (interactive terminal):**
```bash
python main.py
python main.py --model claude
python main.py --model chatgpt
python main.py --model gemini
```

### 5. Run ADK Web UI (local)
```bash
adk web --host 0.0.0.0 --port 8002
```

Open: `http://localhost:8002`

### 6. Run ADK API server (local)
```bash
adk api_server --host 0.0.0.0 --port 8082
```

### 7. Run tests

```bash
pytest tests/ -v
```

### 8. Run with Docker

```bash
docker compose build
docker compose run --rm send-money-agent
```

### 8.1 Run ADK Web UI with Docker
```bash
docker compose run --rm --service-ports send-money-agent adk web --host 0.0.0.0 --port 8002
```

## Model aliases

| Alias | Actual model |
|------|---------------|
| `gemini` | `gemini-2.5-flash` |
| `gemini_pro` | `gemini-2.5-pro` |
| `claude` | `litellm/anthropic/claude-sonnet-4-6` |
| `claude_opus` | `litellm/anthropic/claude-opus-4-6` |
| `chatgpt` | `litellm/openai/gpt-5.4-mini` |
| `gpt54` | `litellm/openai/gpt-5.4` |
| `gpt54mini` | `litellm/openai/gpt-5.4-mini` |
| `gpt5` | `litellm/openai/gpt-5.4` |

Legacy aliases still accepted for compatibility:
- `gpt4` -> `litellm/openai/gpt-5.4-mini`
- `gpt4o` -> `litellm/openai/gpt-5.4-mini`

---

## Supported countries & delivery methods

| Country | Currency | Delivery methods |
|---------|----------|-----------------|
| Mexico | MXN | bank_transfer, cash_pickup, mobile_wallet |
| Colombia | COP | bank_transfer, cash_pickup |
| Philippines | PHP | bank_transfer, mobile_wallet |
| India | INR | bank_transfer, upi |
| Brazil | BRL | bank_transfer, pix |
| Nigeria | NGN | bank_transfer, mobile_money |
| Kenya | KES | mobile_money, bank_transfer |
| Guatemala | GTQ | cash_pickup, bank_transfer |
| El Salvador | USD | bank_transfer, cash_pickup |
| Honduras | HNL | cash_pickup, bank_transfer |
| Ecuador | USD | bank_transfer, cash_pickup |
| Peru | PEN | bank_transfer, cash_pickup, mobile_wallet |

---

## Agent tools

| Tool | Purpose |
|------|---------|
| `get_transfer_state` | Read current state; find what's missing. Guards: incomplete names count as missing. |
| `update_transfer_details` | Persist collected/corrected fields. Hard-rejects incomplete names, invalid countries/methods/amounts. |
| `flag_ambiguous_input` | Log ambiguous input; returns structured clarification questions. |
| `get_country_info` | Validate country (fuzzy), get delivery methods. |
| `get_supported_destinations` | Return all supported destination countries (optionally with currency + methods). |
| `get_transfer_policies` | Return user-facing limits, required fields, and non-sensitive transfer rules. |
| `confirm_transfer` | Finalise transfer. Requires `user_confirmed=True` as a hard code gate. |
| `reset_transfer` | Clear state, start over. |

---

## Example conversation

```
You: I need to send some money
Agent: I'd be happy to help! Who are you sending money to?
You: Maria
Agent: Could you give me the full name (first + last)?
You: Maria Santos
Agent: Got it! Which country are they in?
You: Philippines
Agent: How much would you like to send (in USD)?
You: 350
Agent: For the Philippines, you can receive via:
       1. bank_transfer
       2. mobile_wallet
       Which would you prefer?
You: mobile wallet
Agent: Here's a summary of your transfer:
       • Recipient:  Maria Santos
       • Country:    Philippines
       • Amount:     $350.00 USD → 20,300.00 PHP
       • Delivery:   Mobile Wallet
       Shall I confirm this transfer? (yes / no)
You: yes
Agent: ✅ Transfer confirmed! Reference: TXN847291
```

---

## Design notes

- **Hard enforcement in code, not just prompts** — incomplete names, explicit confirmation consent, and method normalisation are all enforced in `tools.py`. The agent prompt cannot accidentally bypass them.
- **Fuzzy input handling** — country aliases (`phil` → Philippines, `brasil` → Brazil), prefix matching, and free-text delivery methods (`mobile wallet`, `mpesa`) are normalised before validation.
- **State persistence** — all transfer data lives in ADK's session state (`tool_context.state["transfer_state"]`), surviving across turns automatically.
- **No custom router** — flow control is entirely driven by the agent's instruction prompt and tool return values; no hand-rolled router outside ADK's model.
- **Self-contained** — works fully offline except for the LLM API call itself.

---

## What changed from v1

| Area | v1 | v2 |
|------|----|----|
| Incomplete name | Saved with warning (LLM could ignore) | Hard `success=False`; name never saved |
| `confirm_transfer` gate | Prompt-only | `user_confirmed=True` required in code |
| Country matching | Exact case-insensitive only | + aliases + prefix matching |
| Delivery method input | Exact canonical key required | Free-text normalised (`mobile wallet` → `mobile_wallet`) |
| `get_transfer_state` | Simple field check | Also catches incomplete names already in state |
| README tool table | Missing capability-introspection tools | All 8 tools listed |
| Tests | None | 90+ pytest cases across all paths |
