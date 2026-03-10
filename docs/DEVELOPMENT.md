# Development Guide

This document covers internal architecture details, design patterns, and guidelines for contributing.

---

## 1. Code Organization

### Core Modules

```
app/
├── main.py          # Streamlit UI orchestration
├── archetypes.py    # Persona definitions + prompts
├── inference.py     # Model backend abstraction
└── database.py      # Data persistence layer
```

### Scripts

```
scripts/
├── parse_chats.py          # Raw OnlyFans export → JSONL
├── convert_adapter_to_mlx.py # PEFT → MLX format
├── audit_data.py           # Training data validation
└── modal_server.py         # Cloud inference endpoint
```

### Configuration

```
requirements.txt        # MLX-LM + utilities
app_requirements.txt    # Streamlit + UI deps
Makefile               # Build recipes + workflows
docker-compose.yml     # Container orchestration
start_mlx_server.sh    # MLX server launcher
```

---

## 2. Design Patterns

### 2.1 Inference Backend Abstraction

**File**: `app/inference.py`

The module abstracts inference backend selection:

```python
BACKEND = os.getenv("INFERENCE_BACKEND", "modal").lower()

def query_model(conversation_history, archetype):
    """Stream model responses from configured backend"""
    
    if BACKEND == "modal":
        # Query Modal GPU API
        ...
    elif BACKEND == "mlx":
        # Query local MLX server
        ...
    else:
        raise ValueError(f"Unknown backend: {BACKEND}")
    
    yield response_chunk  # Stream-friendly generator
```

**Benefits**:
- Seamless switching between Modal GPU and local MLX
- No code duplication in UI layer
- Easy to add new backends (e.g., vLLM, TensorRT)

### 2.2 Database Locking Strategy

**File**: `app/database.py`

Thread-safe operations with explicit locks:

```python
_lock = threading.Lock()

def save_message(conversation_id, role, content):
    conn = _get_conn()
    with _lock:  # Acquire lock before write
        conn.execute(...)
        conn.commit()
        # Lock released when exiting context
```

**Benefits**:
- Prevents race conditions in concurrent scenarios
- Streamlit can handle multiple sessions
- SQLite WAL mode for better concurrency

### 2.3 Archetype Parameterization

**File**: `app/archetypes.py`

Archetypes are data-driven dictionaries:

```python
ARCHETYPES = {
    "horny": {
        "label": "Horny",
        "emoji": "🔥",
        "description": "...",
        "opener": "...",
        "intro": "...",
    },
    # ...
}

_ARCHETYPE_PARAMS = {
    "horny": {max_tokens: 80, temperature: 0.75, ...},
    "cheapskate": {max_tokens: 100, temperature: 0.70, ...},
    # ...
}

_SUBSCRIBER_SYSTEMS = {
    "horny": "You are a sexually forward subscriber...",
    # ...
}
```

**Benefits**:
- Easy to add/modify archetypes without code changes
- Generation parameters tuned per-archetype
- System prompts centralized and version-controlled

### 2.4 Streamlit State Management

**File**: `app/main.py`

Uses Streamlit's reactive state:

```python
if "current_conversation_id" not in st.session_state:
    st.session_state.current_conversation_id = None

# Sidebar conversation selector
with st.sidebar:
    if st.button("New Conversation"):
        conversation_id = db.create_conversation(...)
        st.session_state.current_conversation_id = conversation_id
        st.rerun()  # Refresh UI

# Main chat area
if st.session_state.current_conversation_id:
    messages = db.get_messages(st.session_state.current_conversation_id)
    # Display messages...
```

**Benefits**:
- State persists across reruns (user interactions)
- Streamlit handles event loop internally
- No manual state serialization needed

---

## 3. Data Structures

### Conversation Schema

**SQLite**:
```sql
CREATE TABLE conversations (
    id         TEXT PRIMARY KEY,        -- UUID
    title      TEXT NOT NULL,           -- Auto-generated from first message
    archetype  TEXT NOT NULL,           -- e.g., "horny", "casual"
    created_at TEXT NOT NULL,           -- ISO 8601 timestamp
    updated_at TEXT NOT NULL            -- ISO 8601 timestamp
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,      -- "user" (Jasmin) or "assistant" (subscriber)
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
```

### Archetype Definition

```python
{
    "label": str,              # Display name
    "emoji": str,              # UI indicator
    "icon": str,               # Material icon name
    "gradient": str,           # CSS gradient for cards
    "description": str,        # One-liner for UI
    "opener": str,             # First message bot sends
    "intro": str,              # Response after user selects archetype
}
```

### Generation Parameters

```python
{
    "max_tokens": int,         # Response length limit
    "temperature": float,      # Randomness (0.0-1.0+)
    "top_p": float,            # Nucleus sampling (0.0-1.0)
    "rep_pen": float,          # Repetition penalty (1.0+)
    "stop": list[str],         # Stop tokens
}
```

---

## 4. Workflows & Lifecycle

### 4.1 Conversation Initialization

```python
# app/main.py
with st.columns([2, 1]):
    if st.button("Start New Chat"):
        # 1. Create conversation in DB
        conversation_id = db.create_conversation(
            title=f"{archetype.title()} Chat",
            archetype=archetype
        )
        
        # 2. Store in Streamlit state
        st.session_state.current_conversation_id = conversation_id
        
        # 3. Save intro message from bot
        intro_msg = ARCHETYPES[archetype]["intro"]
        db.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=intro_msg
        )
        
        # 4. Rerun UI to display new conversation
        st.rerun()
```

### 4.2 Message Exchange

```python
# User types and submits message
user_input = st.chat_input("Type as Jasmin...")

if user_input:
    # 1. Save user message
    db.save_message(
        conversation_id=st.session_state.current_conversation_id,
        role="user",
        content=user_input
    )
    
    # 2. Fetch conversation history
    messages = db.get_messages(st.session_state.current_conversation_id)
    
    # 3. Query model
    response_generator = inference.query_model(
        conversation_history=messages,
        archetype=ARCHETYPES[selected_archetype]
    )
    
    # 4. Stream response to UI
    with st.chat_message("assistant"):
        response_text = st.write_stream(response_generator)
    
    # 5. Save assistant message
    db.save_message(
        conversation_id=st.session_state.current_conversation_id,
        role="assistant",
        content=response_text
    )
```

### 4.3 Model Inference

```python
# app/inference.py
def query_model(conversation_history, archetype):
    """
    Args:
        conversation_history: List[{"role": str, "content": str}]
        archetype: str (archetype key, e.g., "horny")
    
    Yields:
        str: Response chunks for streaming display
    """
    
    # 1. Build system prompt
    system_prompt = _SUBSCRIBER_SYSTEMS[archetype]
    
    # 2. Format message history (Llama 2 Chat format)
    formatted_prompt = format_conversation_for_prompt(
        system_prompt=system_prompt,
        messages=conversation_history
    )
    
    # 3. Get generation parameters
    params = _ARCHETYPE_PARAMS.get(archetype, _DEFAULT_PARAMS)
    
    # 4. Query backend
    if BACKEND == "modal":
        response = requests.post(
            os.getenv("MODAL_ENDPOINT"),
            json={"prompt": formatted_prompt, **params}
        )
        yield response.text
    
    elif BACKEND == "mlx":
        # MLX server endpoint (streaming)
        with requests.post(
            os.getenv("MLX_SERVER_URL") + "/generate",
            json={"prompt": formatted_prompt, **params},
            stream=True
        ) as r:
            for chunk in r.iter_content(decode_unicode=True):
                yield chunk
```

---

## 5. Prompt Engineering

### System Prompt Template

```python
_SUBSCRIBER_SYSTEMS = {
    "horny": """You are a horny, sexually forward OnlyFans subscriber. You are direct about your desires and often ask for explicit content or custom videos. You use casual language, emojis, and flirtation. Keep responses short and reactive.""",
    
    "casual": """You are a casual, friendly OnlyFans subscriber who values genuine conversation. You ask about her day, interests, and life. You're respectful but engaged. Keep responses short and natural.""",
    
    # ... more archetypes
}
```

### Conversation Formatting

Llama 2 Chat format:

```
<s>[INST] <<SYS>>
{system_prompt}
<</SYS>>

{user_message_1}[/INST] {assistant_message_1}</s>

<s>[INST] {user_message_2}[/INST] {assistant_message_2}</s>

... (continue alternating)

<s>[INST] {current_user_message}[/INST]
```

The model completes the response after the final `[/INST]` token.

---

## 6. Extension Points

### Adding a New Archetype

1. **Define in `app/archetypes.py`**:
   ```python
   ARCHETYPES["new_type"] = {
       "label": "New Type",
       "emoji": "🎯",
       "icon": "target",
       "gradient": "#color1, #color2",
       "description": "Brief description",
       "opener": "First message",
       "intro": "Response after selection",
   }
   
   _SUBSCRIBER_SYSTEMS["new_type"] = "You are a... [system prompt]"
   
   _ARCHETYPE_PARAMS["new_type"] = {
       "max_tokens": 80,
       "temperature": 0.70,
       "top_p": 0.85,
       "rep_pen": 1.05,
   }
   ```

2. **No UI changes needed** — archetype picker auto-discovers from ARCHETYPES dict

### Adding a New Inference Backend

1. **Implement in `app/inference.py`**:
   ```python
   def query_model(conversation_history, archetype):
       backend = os.getenv("INFERENCE_BACKEND", "modal").lower()
       
       if backend == "new_backend":
           # Implement new backend logic
           ...
       # ... existing backends
   ```

2. **Update `docker-compose.yml`** with new env vars:
   ```yaml
   environment:
     - INFERENCE_BACKEND=new_backend
     - NEW_BACKEND_URL=https://...
   ```

### Adding a New Data Export Format

1. **Implement in `scripts/parse_chats.py`**:
   ```python
   def export_as_csv(conversations):
       """Export conversations to CSV format"""
       ...
   ```

2. **Update Makefile** with new target:
   ```makefile
   export-csv:
       $(VENV_PY) scripts/parse_chats.py --format=csv
   ```

---

## 7. Testing & Validation

### Testing Locally

1. **Manual UI testing**:
   ```bash
   make server  # Terminal 1
   make app     # Terminal 2
   # Interact with UI, verify behavior
   ```

2. **Backend testing**:
   ```bash
   # Test inference
   python -c "
   import app.inference as inf
   from app.archetypes import ARCHETYPES
   
   history = [{'role': 'user', 'content': 'Hey!'}]
   for chunk in inf.query_model(history, 'horny'):
       print(chunk, end='', flush=True)
   "
   ```

3. **Database testing**:
   ```bash
   python -c "
   import app.database as db
   db.init_db()
   cid = db.create_conversation('Test', 'horny')
   db.save_message(cid, 'user', 'Hello')
   messages = db.get_messages(cid)
   print(messages)
   "
   ```

### Data Validation

```bash
# Check training data integrity
make parse && python scripts/audit_data.py

# Expected output:
# ✅ 256 conversations parsed
# ✅ 8,496 training turns
# ✅ All formats valid
# ⚠️ 2 duplicates (skipped)
```

---

## 8. Debugging

### Enable Verbose Logging

```bash
export DEBUG=true
make app  # or make server
```

Logs include:
- Inference request/response details
- Database operations
- Archetype selection and parameters

### Database Inspection

```bash
# Connect to SQLite
sqlite3 data/chat.db

# View conversations
SELECT id, title, archetype, created_at FROM conversations;

# View messages for a conversation
SELECT role, content, created_at FROM messages 
WHERE conversation_id = '<conversation_id>' 
ORDER BY created_at;

# Check database health
PRAGMA integrity_check;
```

### Model Inference Debugging

```bash
# Test MLX server directly
curl -X POST http://localhost:8080/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hello, how are you?",
    "max_tokens": 50,
    "temperature": 0.7
  }'

# Or for Modal (requires URL):
curl -X POST https://your-modal-url/infer \
  -H "Content-Type: application/json" \
  -d '{...}'
```

---

## 9. Performance Optimization

### Inference Speed

1. **Reduce max_tokens** in archetype params
2. **Lower temperature** (0.6-0.7 is faster than 0.8+)
3. **Use Modal GPU** instead of local MLX
4. **Cache model between requests** (handled by inference server)

### Database Performance

1. **Pagination** for large conversation histories:
   ```python
   # Only fetch last N messages for context window
   messages = db.get_messages(cid, limit=20)
   ```

2. **Index on conversation_id** (already added):
   ```sql
   CREATE INDEX idx_messages_conversation_id 
   ON messages(conversation_id);
   ```

3. **Use WAL mode** (already enabled):
   ```python
   _conn.execute("PRAGMA journal_mode=WAL")
   ```

### UI Responsiveness

1. **Stream responses** using `st.write_stream()`:
   ```python
   with st.chat_message("assistant"):
       st.write_stream(query_generator)
   ```

2. **Cache archetype definitions**:
   ```python
   @st.cache_data
   def get_archetypes():
       return ARCHETYPES
   ```

---

## 10. Deployment Checklist

Before deploying to production:

- [ ] All tests pass locally
- [ ] `.env` file not committed (check `.gitignore`)
- [ ] Database migration plan (WAL mode enabled)
- [ ] Monitoring/logging configured
- [ ] Error handling for API failures
- [ ] Rate limiting on inference endpoint
- [ ] SSL certificates for Modal/cloud deployment
- [ ] Backups of chat database
- [ ] Documentation updated

---

## 11. Common Pitfalls

### Database Locks

❌ **Bad**:
```python
def save_message(cid, role, content):
    conn = _get_conn()
    conn.execute(...)  # Can deadlock with concurrent access
    conn.commit()
```

✅ **Good**:
```python
def save_message(cid, role, content):
    conn = _get_conn()
    with _lock:
        conn.execute(...)
        conn.commit()
```

### Prompt Injection

❌ **Bad**:
```python
prompt = f"User said: {user_input}"  # User input directly in prompt
```

✅ **Good**:
```python
# User input is in structured message format, not in system prompt
prompt = format_prompt(
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_input}]
)
```

### Streaming Generators

❌ **Bad**:
```python
def query_model(...):
    full_response = ""
    # ... query model ...
    return full_response  # Can't stream
```

✅ **Good**:
```python
def query_model(...):
    # ... query model with streaming ...
    for chunk in response:
        yield chunk  # Stream chunks to UI
```

---

## 12. Contributing

1. **Clone and setup**:
   ```bash
   git clone <repo>
   cd subscriber-sim
   make setup
   ```

2. **Create feature branch**:
   ```bash
   git checkout -b feature/your-feature
   ```

3. **Make changes** and test locally:
   ```bash
   make server  # Terminal 1
   make app     # Terminal 2
   ```

4. **Commit with conventional messages**:
   ```bash
   git commit -m "feat: add new archetype" \
     -m "Describes what this change does in detail" \
     -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
   ```

5. **Push and create PR**:
   ```bash
   git push origin feature/your-feature
   ```

---

## 13. Resources

- [Streamlit Docs](https://docs.streamlit.io/)
- [MLX Documentation](https://ml-explore.github.io/mlx/)
- [Modal Documentation](https://modal.com/docs)
- [SQLite Best Practices](https://www.sqlite.org/bestpractice.html)
- [Llama 2 Chat Format](https://huggingface.co/meta-llama/Llama-2-7b-chat)
- [LoRA Fine-Tuning](https://huggingface.co/docs/peft/en/developer_guides/lora)

---

## Questions?

Check `docs/ARCHITECTURE.md` for system-level design or `docs/QUICK_START.md` for operational workflows.
